from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import date

from .models import (
    AgentHandoff,
    AnswerStatus,
    CaseState,
    CitationCheck,
    Evidence,
    IssueCategory,
    LegalClaim,
    MissingFact,
    ReviewStatus,
    RiskFlag,
    RiskSeverity,
    SourceType,
    UserRole,
    now_mo,
)
from .llm import LLMError, OpenAICompatibleClient
from .policies import (
    GENERIC_REQUIREMENTS,
    GUARANTEE_KEYWORDS,
    HIGH_RISK_CATEGORIES,
    HIGH_RISK_KEYWORDS,
    ISSUE_KEYWORDS,
    ISSUE_QUERY_TEMPLATE,
    ISSUE_REQUIREMENTS,
    MO_KEYWORDS,
    NON_MO_KEYWORDS,
    PROHIBITED_KEYWORDS,
)
from .repository import LegalSourceRepository


def add_handoff(
    state: CaseState,
    from_agent: str,
    to_agent: str,
    status: str,
    artifact_keys: list[str],
    decisions: list[str],
    tests: list[str] | None = None,
    risks: list[str] | None = None,
    blocked_by: list[str] | None = None,
) -> None:
    state.handoffs.append(
        AgentHandoff(
            task_id=f"{state.trace_id}:{len(state.handoffs) + 1}",
            from_agent=from_agent,
            to_agent=to_agent,
            status=status,
            artifact_keys=artifact_keys,
            decisions=decisions,
            tests=tests or [],
            risks=risks or [],
            blocked_by=blocked_by or [],
            trace_id=state.trace_id,
        )
    )
    state.touch()


class IntakeAgent:
    name = "A1_intake"

    def run(self, state: CaseState) -> CaseState:
        query = state.raw_query.lower()
        if any(keyword in query for keyword in NON_MO_KEYWORDS):
            state.scope_status = AnswerStatus.OUT_OF_SCOPE
            state.scope_reason = "目前只支援澳門特別行政區，不能直接套用其他法域。"

        if any(keyword in query for keyword in MO_KEYWORDS):
            state.facts.setdefault("work_location", "澳門")

        detected_issues = [
            category
            for category, keywords in ISSUE_KEYWORDS.items()
            if any(keyword.lower() in query for keyword in keywords)
        ]
        issues = list(state.issue_categories)
        for category in detected_issues:
            if category not in issues:
                issues.append(category)
        if not issues:
            issues = [IssueCategory.OTHER]
        state.issue_categories = issues
        state.event_dates = _extract_event_dates(state)
        state.missing_facts = _find_missing_facts(state)

        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A0_coordinator",
            status="completed",
            artifact_keys=[
                "user_role",
                "issue_categories",
                "event_dates",
                "missing_facts",
            ],
            decisions=["已完成角色、議題與最少必要事實檢查。"],
            tests=["role_schema", "issue_classification"],
        )
        return state


class RetrievalPlannerAgent:
    name = "A2_retrieval_planner"

    def run(self, state: CaseState) -> CaseState:
        weighted_queries: list[tuple[str, float]] = [
            (query, 2.4) for query in state.llm_queries
        ]
        for category in state.issue_categories:
            query = ISSUE_QUERY_TEMPLATE.get(category)
            if query:
                weighted_queries.append((query, 1.5))
        normalized_query = _normalize(state.raw_query)
        if any(
            keyword in normalized_query
            for keyword in ("口頭", "沒有簽", "未簽", "無合同")
        ):
            weighted_queries.append(
                ("口頭 勞動合同 合同訂立 合同形式", 2.2)
            )
        if any(
            keyword in normalized_query
            for keyword in (
                "沒有給",
                "不給",
                "欠薪",
                "欠付",
                "拖欠",
                "未付款",
                "沒有支付",
            )
        ):
            weighted_queries.append(
                ("報酬 訂定 支付期 僱主義務 遲延", 2.2)
            )
        if state.raw_query.strip():
            raw_weight = 2.0 if len(state.raw_query) <= 40 else 1.0
            weighted_queries.append((state.raw_query.strip(), raw_weight))

        queries: list[str] = []
        weights: dict[str, float] = {}
        for query, weight in weighted_queries:
            if query not in weights:
                queries.append(query)
                weights[query] = weight
            else:
                weights[query] = max(weights[query], weight)
        state.retrieval_queries = queries
        state.retrieval_query_weights = weights
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A3_retrieval",
            status="completed",
            artifact_keys=["retrieval_queries"],
            decisions=["查詢只使用議題詞與使用者原文，沒有加入未經驗證的條號。"],
            tests=["no_generated_article_numbers"],
        )
        return state


class RetrievalAgent:
    name = "A3_retrieval"

    def __init__(self, repository: LegalSourceRepository) -> None:
        self.repository = repository

    def run(self, state: CaseState) -> CaseState:
        effective_date = _effective_date(state)
        collected: dict[str, Evidence] = {}
        for query in state.retrieval_queries:
            results = self.repository.search_legal_sources(
                query=query,
                jurisdiction=state.jurisdiction,
                source_types={
                    SourceType.LAW,
                    SourceType.ADMINISTRATIVE_REGULATION,
                    SourceType.COURT_DECISION,
                    SourceType.APPROVED_COMMENTARY,
                },
                effective_date=effective_date,
                top_k=30,
                rerank_top_n=6,
            )
            for evidence in results:
                query_weight = state.retrieval_query_weights.get(query, 1.0)
                evidence = replace(
                    evidence,
                    score=round(evidence.score * query_weight, 4),
                )
                previous = collected.get(evidence.evidence_id)
                if previous is None or evidence.score > previous.score:
                    collected[evidence.evidence_id] = evidence

        guidance = self.repository.search_official_guidance(
            query=" ".join(state.retrieval_queries),
            effective_date=effective_date,
            top_k=5,
        )
        for evidence in guidance:
            previous = collected.get(evidence.evidence_id)
            if previous is None or evidence.score > previous.score:
                collected[evidence.evidence_id] = evidence

        ranked = sorted(
            collected.values(), key=lambda item: item.score, reverse=True
        )
        if ranked:
            relevance_cutoff = max(3.0, ranked[0].score * 0.6)
            ranked = [
                item for item in ranked if item.score >= relevance_cutoff
            ]
        evidence_limit = 8 if state.llm_queries else 3
        state.evidence = ranked[:evidence_limit]
        state.source_ids = sorted({item.source_id for item in state.evidence})
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A4_analysis",
            status="completed" if state.evidence else "insufficient_evidence",
            artifact_keys=["evidence", "source_ids"],
            decisions=["只回傳 registry 中經核准且符合事件日期的來源。"],
            tests=["review_status_filter", "effective_date_filter"],
            risks=[] if state.evidence else ["evidence_insufficient"],
        )
        return state


class AnalysisAgent:
    name = "A4_analysis"

    def run(
        self,
        state: CaseState,
        llm_client: OpenAICompatibleClient | None = None,
    ) -> CaseState:
        claims: list[LegalClaim] = []
        llm_used = False
        if llm_client and state.evidence:
            try:
                result = llm_client.analyze_evidence(state)
                claims = _claims_from_llm_result(state, result)
                if claims:
                    llm_used = True
                    current = state.llm_result or {}
                    current["analysis"] = result
                    current["analysis_used"] = True
                    state.llm_result = current
            except LLMError as exc:
                current = state.llm_result or {}
                current["analysis_error"] = str(exc)
                state.llm_result = current
                state.risk_flags.append(
                    RiskFlag(
                        code="llm_analysis_error",
                        severity=RiskSeverity.MEDIUM,
                        message=f"模型分析失敗，已回退證據原文模式：{exc}",
                    )
                )

        if not claims:
            claims = [
                LegalClaim(
                    claim_id=f"C{index}",
                    claim_type="direct_quote",
                    text=evidence.content,
                    evidence_ids=[evidence.evidence_id],
                    support_quote=evidence.content,
                )
                for index, evidence in enumerate(state.evidence, start=1)
            ]
        state.legal_claims = claims
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A5_citation_verifier",
            status="completed" if claims else "insufficient_evidence",
            artifact_keys=["legal_claims"],
            decisions=[
                (
                    "已使用模型生成受證據約束的分析，交由 A5 逐字驗證。"
                    if llm_used
                    else "已回退為只列實際證據原文，沒有生成超出證據的法律推論。"
                )
            ],
            tests=[
                "llm_grounded_analysis" if llm_used else "evidence_only_analysis"
            ],
            risks=[] if claims else ["evidence_insufficient"],
        )
        return state


class CitationVerifierAgent:
    name = "A5_citation_verifier"

    def __init__(self, repository: LegalSourceRepository) -> None:
        self.repository = repository

    def run(self, state: CaseState) -> CaseState:
        evidence_by_id = {item.evidence_id: item for item in state.evidence}
        checks: list[CitationCheck] = []
        for claim in state.legal_claims:
            issues: list[str] = []
            if not claim.evidence_ids:
                issues.append("主張沒有關聯證據。")
            for evidence_id in claim.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    issues.append(f"找不到證據 {evidence_id}。")
                    continue
                source_item = self.repository.find_evidence_source(evidence)
                if source_item is None:
                    issues.append(f"證據 {evidence_id} 不在已核准 registry。")
                    continue
                if claim.claim_type == "grounded_analysis":
                    support_quote = claim.support_quote or ""
                    if not support_quote:
                        issues.append(f"主張 {claim.claim_id} 沒有支持引文。")
                    elif _normalize(support_quote) not in _normalize(
                        source_item.provision.text
                    ):
                        issues.append(f"主張 {claim.claim_id} 的支持引文不精確。")
                elif _normalize(claim.text) != _normalize(
                    source_item.provision.text
                ):
                    issues.append(f"主張 {claim.claim_id} 的引文不精確。")
                if evidence.article != source_item.provision.article:
                    issues.append(f"主張 {claim.claim_id} 的條號不一致。")
                if evidence.law_title != source_item.source.official_title:
                    issues.append(f"證據 {evidence_id} 的法規名稱不一致。")
                if evidence.law_number != source_item.source.law_number:
                    issues.append(f"證據 {evidence_id} 的法規編號不一致。")
                if evidence.version_label != source_item.source.version_label:
                    issues.append(f"證據 {evidence_id} 的版本標籤不一致。")
                if (
                    evidence.effective_from != source_item.provision.effective_from
                    or evidence.effective_to != source_item.provision.effective_to
                ):
                    issues.append(f"證據 {evidence_id} 的生效日期不一致。")
                if source_item.source.jurisdiction != "MO":
                    issues.append(f"來源 {source_item.source.source_id} 不是澳門法域。")
                if source_item.source.review_status is not ReviewStatus.APPROVED:
                    issues.append(f"來源 {source_item.source.source_id} 尚未核准。")
                if not evidence.official_url.startswith(("https://", "http://")):
                    issues.append(f"證據 {evidence_id} 沒有可用官方網址。")
                effective_date = _effective_date(state)
                if not _is_active_date(
                    source_item.source.effective_from,
                    source_item.source.effective_to,
                    effective_date,
                ):
                    issues.append(f"來源 {source_item.source.source_id} 在事件日期無效。")
                if not _is_active_date(
                    source_item.provision.effective_from,
                    source_item.provision.effective_to,
                    effective_date,
                ):
                    issues.append(
                        f"條文 {source_item.provision.provision_id} 在事件日期無效。"
                    )
            passed = not issues
            claim.accepted = passed
            checks.append(
                CitationCheck(
                    claim_id=claim.claim_id, passed=passed, issues=issues
                )
            )
        state.citation_checks = checks
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A6_risk",
            status="completed" if all(item.passed for item in checks) else "returned",
            artifact_keys=["citation_checks", "legal_claims"],
            decisions=["逐字比對引文、條號、來源審核狀態與官方網址。"],
            tests=["citation_exact_match"],
            risks=[
                f"citation_failed:{item.claim_id}"
                for item in checks
                if not item.passed
            ],
        )
        return state


class RiskAgent:
    name = "A6_risk"

    def preflight(self, state: CaseState) -> CaseState:
        query = _normalize(state.raw_query)
        if any(_normalize(keyword) in query for keyword in PROHIBITED_KEYWORDS):
            _add_risk(
                state,
                RiskFlag(
                    code="prohibited_request",
                    severity=RiskSeverity.BLOCKER,
                    message="系統不能協助隱匿或偽造證據、規避法定義務或報復他人。",
                ),
            )
        if any(_normalize(keyword) in query for keyword in GUARANTEE_KEYWORDS):
            _add_risk(
                state,
                RiskFlag(
                    code="guaranteed_outcome_request",
                    severity=RiskSeverity.HIGH,
                    message="不能保證法律程序、賠償或談判結果。",
                ),
            )

        high_risk_issues = [
            category
            for category in state.issue_categories
            if category in HIGH_RISK_CATEGORIES
        ]
        high_risk_keywords = [
            keyword for keyword in HIGH_RISK_KEYWORDS if _normalize(keyword) in query
        ]
        if high_risk_issues or high_risk_keywords:
            _add_risk(
                state,
                RiskFlag(
                    code="high_risk_issue",
                    severity=RiskSeverity.HIGH,
                    message="此問題屬高風險類型，應由澳門法律專業人士盡快處理。",
                ),
            )

        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A0_coordinator",
            status="blocked" if state.escalation_required else "completed",
            artifact_keys=["risk_flags", "escalation_required"],
            decisions=["先執行禁止行為與高風險前置檢查。"],
            tests=["preflight_risk_gate"],
            risks=state.escalation_reasons,
            blocked_by=state.escalation_reasons,
        )
        return state

    def evaluate(self, state: CaseState) -> CaseState:
        if state.allow_incomplete and state.missing_facts:
            _add_risk(
                state,
                RiskFlag(
                    code="partial_analysis",
                    severity=RiskSeverity.MEDIUM,
                    message=(
                        "部分事實未提供，以下結果只根據目前資料作有限分析；"
                        "缺少資料可能改變適用結論。"
                    ),
                ),
            )
        failed_checks = [item for item in state.citation_checks if not item.passed]
        if failed_checks:
            _add_risk(
                state,
                RiskFlag(
                    code="citation_failed",
                    severity=RiskSeverity.BLOCKER,
                    message="引用驗證失敗，已阻止未經驗證的法律分析。",
                ),
            )
        if not state.evidence:
            _add_risk(
                state,
                RiskFlag(
                    code="evidence_insufficient",
                    severity=RiskSeverity.HIGH,
                    message="沒有足夠的已審核來源支持個案分析。",
                ),
            )
        if self.repository_conflict(state):
            _add_risk(
                state,
                RiskFlag(
                    code="version_conflict",
                    severity=RiskSeverity.BLOCKER,
                    message="同一條文在事件日期存在不同有效版本，需要真人核對。",
                ),
            )
        if any(item.review_scope == "test_only" for item in state.evidence):
            _add_risk(
                state,
                RiskFlag(
                    code="test_only_sources",
                    severity=RiskSeverity.MEDIUM,
                    message=(
                        "目前使用的是本機測試專用核准來源，"
                        "未經澳門法律專業人士覆核，不得用於實際個案。"
                    ),
                    evidence_ids=[
                        item.evidence_id
                        for item in state.evidence
                        if item.review_scope == "test_only"
                    ],
                ),
            )

        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A7_answer",
            status="blocked" if state.escalation_required else "completed",
            artifact_keys=["risk_flags", "escalation_required"],
            decisions=["完成引用、證據與版本風險檢查。"],
            tests=["evidence_sufficiency", "version_conflict_gate"],
            risks=state.escalation_reasons,
            blocked_by=state.escalation_reasons,
        )
        return state

    @staticmethod
    def repository_conflict(state: CaseState) -> bool:
        groups: dict[tuple[str, str, str | None], set[tuple[str, str]]] = {}
        for evidence in state.evidence:
            key = (evidence.law_number, evidence.article, evidence.paragraph)
            groups.setdefault(key, set()).add(
                (evidence.version_label, evidence.content)
            )
        return any(len(values) > 1 for values in groups.values())


class AnswerAgent:
    name = "A7_answer"

    disclaimer = (
        "本輸出僅為澳門勞動法資訊與初步風險提示，不構成正式法律意見，"
        "也不能替代澳門執業律師的個案判斷。"
    )

    def run(self, state: CaseState, status: AnswerStatus) -> CaseState:
        accepted_claims = [claim for claim in state.legal_claims if claim.accepted]
        accepted_ids = {
            evidence_id
            for claim in accepted_claims
            for evidence_id in claim.evidence_ids
        }
        applicable_law = [
            item for item in state.evidence if item.evidence_id in accepted_ids
        ]

        summary, options, next_steps = self._content_for(
            state=state, status=status, accepted_claims=accepted_claims
        )
        if status is AnswerStatus.ANSWERED and state.llm_result:
            analysis_result = state.llm_result.get("analysis")
            if isinstance(analysis_result, dict):
                summary = str(analysis_result.get("summary") or summary)
                options = _string_list(
                    analysis_result.get("options"), fallback=options
                )
                next_steps = _string_list(
                    analysis_result.get("next_steps"), fallback=next_steps
                )
                uncertainties = _string_list(
                    analysis_result.get("uncertainties"), fallback=[]
                )
                next_steps.extend(
                    f"需要確認：{item}" for item in uncertainties
                )
                if state.allow_incomplete and state.missing_facts:
                    summary = f"按現有資料的有限分析：{summary}"
        state.answer = _build_answer(
            state=state,
            status=status,
            summary=summary,
            applicable_law=applicable_law,
            analysis=[claim.text for claim in accepted_claims],
            options=options,
            next_steps=next_steps,
        )
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A8_evaluation",
            status="completed",
            artifact_keys=["answer"],
            decisions=["按最終風險門檻組裝結構化回答。"],
            tests=["disclaimer_present", "no_formal_legal_advice"],
            risks=state.escalation_reasons,
        )
        return state

    @staticmethod
    def _content_for(
        state: CaseState,
        status: AnswerStatus,
        accepted_claims: list[LegalClaim],
    ) -> tuple[str, list[str], list[str]]:
        if status is AnswerStatus.OUT_OF_SCOPE:
            return (
                state.scope_reason or "問題不在目前支援的法域範圍內。",
                [],
                ["如有需要，請諮詢相應法域的執業律師。"],
            )
        if status is AnswerStatus.ESCALATE_HUMAN:
            return (
                "此案件已被風險或安全門檻阻止自動回答，應交由真人處理。",
                [],
                ["請聯絡澳門執業律師或相關官方支援單位處理個案。"],
            )
        if status is AnswerStatus.NEED_MORE_FACTS:
            return (
                "現有事實不足以安全判斷，請先補充最少必要資料。",
                [],
                [item.question for item in state.missing_facts],
            )
        if status is AnswerStatus.INSUFFICIENT_SOURCES or not accepted_claims:
            return (
                "目前沒有足夠且經核准的澳門來源支持分析，系統不會自行生成法律結論。",
                [],
                [
                    "由法律審核者加入並核准適用的澳門官方來源。",
                    "如個案有時效或程序風險，請諮詢澳門執業律師。",
                ],
            )
        if state.allow_incomplete and state.missing_facts:
            return (
                "已按目前提供的資料作有限分析；未提供的事實可能影響適用結論。",
                [
                    "核對已列出的法源原文，並補交仍然欠缺的案件事實。",
                    "如涉及期限、金額或程序風險，交由澳門執業律師覆核。",
                ],
                [
                    "補交缺少的事實後重新分析。",
                    "保存與事件相關的合同、工資單、排班、訊息或其他證據。",
                ],
            )
        return (
            "已找到並驗證下列來源原文，以下只呈現證據，不把它擴張成個案勝敗或最終法律結論。",
            [
                "核對原文、版本與生效日期是否符合你的事件日期。",
                "如需要適用性或行動策略，交由澳門執業律師覆核。",
            ],
            ["保存與事件相關的合同、工資單、排班、訊息或其他證據。"],
        )


class EvaluationAgent:
    name = "A8_evaluation"

    def run(self, state: CaseState, status: AnswerStatus) -> CaseState:
        tests = [
            "handoff_contract",
            "jurisdiction_mo",
            _citation_test_result(state),
            "privacy_minimized_audit",
        ]
        state.audit_tests = tests
        state.unresolved_risks = sorted(
            {flag.code for flag in state.risk_flags}
            | {
                issue
                for check in state.citation_checks
                for issue in check.issues
            }
        )
        if state.answer is not None:
            state.answer.unresolved_risks = state.unresolved_risks
        add_handoff(
            state=state,
            from_agent=self.name,
            to_agent="A0_coordinator",
            status="completed",
            artifact_keys=["audit_tests", "unresolved_risks"],
            decisions=["記錄測試、來源 ID 與未解風險。"],
            tests=tests,
            risks=state.unresolved_risks,
        )
        return state


def _extract_event_dates(state: CaseState) -> dict[str, str]:
    event_dates: dict[str, str] = {}
    for key, value in state.facts.items():
        if key.endswith("_date") and _is_iso_date(str(value)):
            event_dates[key] = str(value)
    return event_dates


def _find_missing_facts(state: CaseState) -> list[MissingFact]:
    missing: list[MissingFact] = []
    if state.user_role is UserRole.UNKNOWN:
        missing.append(
            MissingFact(
                code="user_role",
                question="你是僱員、僱主、代理人，還是其他身分？",
                reason="不同角色的分析與程序提示不同。",
            )
        )
    for requirement in GENERIC_REQUIREMENTS:
        if requirement.code == "work_location":
            location = str(state.facts.get("work_location", "")).lower()
            if not any(keyword in location for keyword in MO_KEYWORDS):
                missing.append(
                    MissingFact(
                        code=requirement.code,
                        question=requirement.question,
                        reason=requirement.reason,
                    )
                )
        elif requirement.code == "event_date":
            if not state.event_dates:
                missing.append(
                    MissingFact(
                        code=requirement.code,
                        question=requirement.question,
                        reason=requirement.reason,
                    )
                )

    if state.issue_categories == [IssueCategory.OTHER]:
        missing.append(
            MissingFact(
                code="issue_description",
                question="請用一兩句指出你遇到的具體勞動爭議類型。",
                reason="需要先確定問題是否在 MVP 支援範圍內。",
            )
        )

    for category in state.issue_categories:
        for requirement in ISSUE_REQUIREMENTS.get(category, ()):
            if requirement.code not in state.facts:
                missing.append(
                    MissingFact(
                        code=requirement.code,
                        question=requirement.question,
                        reason=requirement.reason,
                    )
                )
        if len(missing) >= 3:
            break
    return missing[:3]


def _effective_date(state: CaseState) -> str:
    if "event_date" in state.event_dates:
        return state.event_dates["event_date"]
    if state.event_dates:
        return sorted(state.event_dates.values())[0]
    return date.today().isoformat()


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_active_date(
    effective_from: str, effective_to: str | None, effective_date: str
) -> bool:
    try:
        start = date.fromisoformat(effective_from)
        end = date.fromisoformat(effective_to) if effective_to else None
        target = date.fromisoformat(effective_date)
    except ValueError:
        return False
    return start <= target and (end is None or target <= end)


def _citation_test_result(state: CaseState) -> str:
    if not state.legal_claims:
        return "citation_not_applicable"
    if all(item.passed for item in state.citation_checks):
        return "citation_verified"
    return "citation_blocked"


def _claims_from_llm_result(
    state: CaseState, result: dict[str, object]
) -> list[LegalClaim]:
    evidence_ids = {item.evidence_id for item in state.evidence}
    items = result.get("analysis")
    if not isinstance(items, list):
        return []
    claims: list[LegalClaim] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        evidence_id = str(item.get("evidence_id") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not statement or evidence_id not in evidence_ids or not quote:
            continue
        claims.append(
            LegalClaim(
                claim_id=f"L{index}",
                claim_type="grounded_analysis",
                text=statement,
                evidence_ids=[evidence_id],
                support_quote=quote,
            )
        )
    return claims


def _string_list(value: object, *, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    items = [str(item).strip() for item in value if str(item).strip()]
    return items or list(fallback)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _add_risk(state: CaseState, flag: RiskFlag) -> None:
    if not any(
        existing.code == flag.code and existing.message == flag.message
        for existing in state.risk_flags
    ):
        state.risk_flags.append(flag)
    if flag.severity in {RiskSeverity.HIGH, RiskSeverity.BLOCKER}:
        state.escalation_required = True
        if flag.message not in state.escalation_reasons:
            state.escalation_reasons.append(flag.message)


def _build_answer(
    state: CaseState,
    status: AnswerStatus,
    summary: str,
    applicable_law: list[Evidence],
    analysis: list[str],
    options: list[str],
    next_steps: list[str],
):
    from .models import Answer, Escalation

    known_facts = [
        {"code": key, "value": value}
        for key, value in sorted(state.facts.items())
    ]
    return Answer(
        status=status,
        role=state.user_role,
        summary=summary,
        known_facts=known_facts,
        missing_facts=state.missing_facts,
        applicable_law=applicable_law,
        analysis=analysis,
        options=options,
        risks=[flag.message for flag in state.risk_flags],
        next_steps=next_steps,
        escalation=Escalation(
            required=state.escalation_required,
            reasons=state.escalation_reasons,
            recipient_type="lawyer" if state.escalation_required else None,
        ),
        disclaimer=AnswerAgent.disclaimer,
        trace_id=state.trace_id,
        unresolved_risks=state.unresolved_risks,
        partial=state.allow_incomplete and bool(state.missing_facts),
    )


def new_trace_id() -> str:
    return uuid.uuid4().hex
