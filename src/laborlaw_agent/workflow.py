from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .llm import LLMConfig, LLMError, OpenAICompatibleClient
from .agents import (
    AnalysisAgent,
    AnswerAgent,
    CitationVerifierAgent,
    EvaluationAgent,
    IntakeAgent,
    RetrievalAgent,
    RetrievalPlannerAgent,
    RiskAgent,
    add_handoff,
    new_trace_id,
)
from .audit import AuditLogger, AuditRecord
from .models import (
    AnswerStatus,
    CaseState,
    IssueCategory,
    MissingFact,
    RiskFlag,
    RiskSeverity,
    UserRole,
    now_mo,
)
from .repository import LegalSourceRepository


class AgentService:
    def __init__(
        self,
        repository: LegalSourceRepository,
        audit_log_path: str | Path | None = "artifacts/audit/audit.jsonl",
    ) -> None:
        self.repository = repository
        self.audit = AuditLogger(audit_log_path)
        self._cases: dict[str, UserRole] = {}
        self.intake = IntakeAgent()
        self.planner = RetrievalPlannerAgent()
        self.retriever = RetrievalAgent(repository)
        self.analyzer = AnalysisAgent()
        self.citation_verifier = CitationVerifierAgent(repository)
        self.risk = RiskAgent()
        self.answer = AnswerAgent()
        self.evaluation = EvaluationAgent()

    def handle(
        self,
        query: str,
        user_role: UserRole | str = UserRole.UNKNOWN,
        facts: dict[str, Any] | None = None,
        case_id: str | None = None,
        trace_id: str | None = None,
        llm_config: LLMConfig | None = None,
        llm_client: OpenAICompatibleClient | None = None,
        allow_incomplete: bool = False,
    ) -> CaseState:
        role = (
            user_role
            if isinstance(user_role, UserRole)
            else UserRole(str(user_role))
        )
        state = CaseState(
            case_id=case_id or new_trace_id()[:16],
            trace_id=trace_id or new_trace_id(),
            raw_query=query,
            user_role=role,
            facts=dict(facts or {}),
            allow_incomplete=allow_incomplete,
        )

        if self._has_role_conflict(state):
            return self._finish_role_conflict(state)

        client = llm_client
        if client is None and llm_config and llm_config.is_usable():
            client = OpenAICompatibleClient(llm_config)
        if client is not None:
            self._run_llm_planning(state, client)

        state = self.intake.run(state)
        self._merge_llm_missing_facts(state)
        self._lock_role(state)
        state = self.risk.preflight(state)

        status = self._preflight_status(state)
        if status is not None:
            return self._finish(state, status)

        state = self.planner.run(state)
        state = self.retriever.run(state)
        state = self.analyzer.run(state, llm_client=client)
        state = self.citation_verifier.run(state)
        state = self.risk.evaluate(state)
        status = self._final_status(state)
        return self._finish(state, status)

    def _run_llm_planning(
        self,
        state: CaseState,
        client: OpenAICompatibleClient,
    ) -> None:
        model_name = getattr(getattr(client, "config", None), "model", None)
        state.llm_result = {
            "enabled": True,
            "model": model_name,
            "plan_used": False,
            "analysis_used": False,
        }
        try:
            plan = client.plan_query(
                query=state.raw_query,
                role=state.user_role.value,
                known_facts=state.facts,
                current_date=now_mo()[:10],
            )
            self._apply_llm_plan(state, plan)
            state.llm_result["plan"] = plan
            state.llm_result["plan_used"] = True
        except LLMError as exc:
            state.llm_result["plan_error"] = str(exc)
            state.risk_flags.append(
                RiskFlag(
                    code="llm_plan_error",
                    severity=RiskSeverity.MEDIUM,
                    message=f"模型檢索規劃失敗，已回退規則模式：{exc}",
                )
            )

    @staticmethod
    def _apply_llm_plan(state: CaseState, plan: dict[str, Any]) -> None:
        facts = plan.get("facts")
        if isinstance(facts, dict):
            for raw_key, raw_value in facts.items():
                key = str(raw_key).strip()
                value = str(raw_value).strip()
                if not key or not value or len(key) > 80 or len(value) > 2_000:
                    continue
                state.facts.setdefault(key, value)

        categories: list[IssueCategory] = []
        raw_categories = plan.get("issue_categories")
        if isinstance(raw_categories, list):
            for raw_category in raw_categories:
                try:
                    categories.append(IssueCategory(str(raw_category)))
                except ValueError:
                    continue
        for category in categories:
            if category not in state.issue_categories:
                state.issue_categories.append(category)

        queries: list[str] = []
        raw_queries = plan.get("retrieval_queries")
        if isinstance(raw_queries, list):
            for raw_query in raw_queries:
                query = str(raw_query).strip()
                if not query or len(query) > 300:
                    continue
                if re.search(r"第[一二三四五六七八九十百零\d]+(?:-[A-Z])?條", query):
                    continue
                queries.append(query)
        state.llm_queries = list(dict.fromkeys(queries))[:5]
        if plan.get("high_risk") is True:
            state.risk_flags.append(
                RiskFlag(
                    code="llm_high_risk",
                    severity=RiskSeverity.HIGH,
                    message="模型判斷此問題可能屬高風險，應由澳門法律專業人士處理。",
                )
            )
            state.escalation_required = True
            if state.risk_flags[-1].message not in state.escalation_reasons:
                state.escalation_reasons.append(state.risk_flags[-1].message)

    @staticmethod
    def _merge_llm_missing_facts(state: CaseState) -> None:
        if not state.llm_result:
            return
        plan = state.llm_result.get("plan")
        if not isinstance(plan, dict):
            return
        raw_items = plan.get("missing_facts")
        if not isinstance(raw_items, list):
            return
        existing_codes = {item.code for item in state.missing_facts}
        existing_questions = {
            _normalize_question(item.question)
            for item in state.missing_facts
        }
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            code = str(raw_item.get("code") or "").strip()
            question = str(raw_item.get("question") or "").strip()
            reason = str(raw_item.get("reason") or "").strip()
            if (
                not code
                or not question
                or code in existing_codes
                or _missing_fact_already_answered(state, code)
                or _normalize_question(question) in existing_questions
                or len(code) > 80
                or len(question) > 300
            ):
                continue
            state.missing_facts.append(
                MissingFact(code=code, question=question, reason=reason)
            )
            existing_codes.add(code)
            existing_questions.add(_normalize_question(question))
            if len(state.missing_facts) >= 4:
                break

    def _has_role_conflict(self, state: CaseState) -> bool:
        existing = self._cases.get(state.case_id)
        return (
            existing is not None
            and state.user_role is not UserRole.UNKNOWN
            and existing is not state.user_role
        )

    def close_case(self, case_id: str) -> None:
        self._cases.pop(case_id, None)

    def _lock_role(self, state: CaseState) -> None:
        if state.user_role is UserRole.UNKNOWN:
            return
        self._cases.setdefault(state.case_id, state.user_role)

    def _finish_role_conflict(self, state: CaseState) -> CaseState:
        flag = RiskFlag(
            code="case_role_conflict",
            severity=RiskSeverity.BLOCKER,
            message="同一案件不得混合僱員與僱主角色，已停止自動分析。",
        )
        state.risk_flags.append(flag)
        state.escalation_required = True
        state.escalation_reasons.append(flag.message)
        add_handoff(
            state=state,
            from_agent="A0_coordinator",
            to_agent="A0_coordinator",
            status="blocked",
            artifact_keys=["risk_flags"],
            decisions=["阻止同一案件跨角色共用狀態。"],
            tests=["case_role_isolation"],
            risks=[flag.message],
            blocked_by=[flag.message],
        )
        return self._finish(state, AnswerStatus.ESCALATE_HUMAN)

    @staticmethod
    def _preflight_status(state: CaseState) -> AnswerStatus | None:
        blocking_codes = {
            flag.code
            for flag in state.risk_flags
            if flag.severity is RiskSeverity.BLOCKER
        }
        if "prohibited_request" in blocking_codes:
            return AnswerStatus.ESCALATE_HUMAN
        if state.scope_status is AnswerStatus.OUT_OF_SCOPE:
            return AnswerStatus.OUT_OF_SCOPE
        if state.escalation_required:
            return AnswerStatus.ESCALATE_HUMAN
        if state.missing_facts and not state.allow_incomplete:
            return AnswerStatus.NEED_MORE_FACTS
        return None

    @staticmethod
    def _final_status(state: CaseState) -> AnswerStatus:
        accepted_claims = [
            claim for claim in state.legal_claims if claim.accepted
        ]
        hard_blockers = {
            flag.code
            for flag in state.risk_flags
            if flag.code in {"citation_failed", "version_conflict"}
            or flag.severity is RiskSeverity.BLOCKER
        }
        if hard_blockers:
            return AnswerStatus.ESCALATE_HUMAN
        if not accepted_claims:
            return AnswerStatus.INSUFFICIENT_SOURCES
        if state.escalation_required:
            return AnswerStatus.ESCALATE_HUMAN
        return AnswerStatus.ANSWERED

    def _finish(self, state: CaseState, status: AnswerStatus) -> CaseState:
        state = self.answer.run(state, status)
        state = self.evaluation.run(state, status)
        self.audit.write(state)
        state.touch()
        return state

    def audit_record(self, state: CaseState) -> AuditRecord:
        status = state.answer.status.value if state.answer else "not_assembled"
        return AuditRecord(
            trace_id=state.trace_id,
            case_id=state.case_id,
            created_at=state.updated_at,
            status=status,
            source_ids=sorted(set(state.source_ids)),
            handoff_count=len(state.handoffs),
            tests=state.audit_tests,
            unresolved_risks=state.unresolved_risks,
            retention_days=state.retention_days,
        )


def _missing_fact_already_answered(state: CaseState, code: str) -> bool:
    if code in state.facts:
        return True
    normalized_code = code.lower()
    fact_keys = " ".join(state.facts.keys()).lower()

    if any(
        token in normalized_code
        for token in ("written", "contract_signed", "contract_form", "onboarding")
    ):
        return any(
            token in fact_keys
            for token in (
                "written",
                "contract_signed",
                "contract_form",
                "onboarding",
                "書面",
                "入職",
            )
        )

    if any(
        token in normalized_code
        for token in ("payment", "salary", "wage", "remuneration")
    ):
        return any(
            token in fact_keys
            for token in (
                "payment",
                "salary",
                "wage",
                "remuneration",
                "contract_agreed_terms",
                "工資",
                "報酬",
            )
        )

    if any(
        token in normalized_code
        for token in ("work_schedule", "work_period", "work_days", "working_hours")
    ):
        return any(
            token in fact_keys
            for token in (
                "work_start",
                "work_end",
                "work_days",
                "actual_work_days",
                "work_schedule",
                "working_hours",
                "工作安排",
            )
        )

    if any(
        token in normalized_code
        for token in ("evidence", "witness", "message", "proof")
    ):
        return any(
            token in fact_keys
            for token in (
                "evidence",
                "witness",
                "wechat",
                "message",
                "proof",
                "通訊",
                "證人",
            )
        )
    return False


def _normalize_question(value: str) -> str:
    return "".join(str(value).lower().split())
