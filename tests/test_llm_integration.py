from __future__ import annotations

from types import SimpleNamespace

from laborlaw_agent.models import AnswerStatus, UserRole
from laborlaw_agent.repository import LegalSourceRepository
from laborlaw_agent.workflow import AgentService


REGISTRY_PATH = "data/source-registry/registry.json"


class FakeLLMClient:
    def __init__(
        self,
        *,
        bad_quote: bool = False,
        missing_facts: list[dict[str, str]] | None = None,
    ) -> None:
        self.config = SimpleNamespace(model="fake-macau-legal-model")
        self.bad_quote = bad_quote
        self.missing_facts = missing_facts or []

    def plan_query(self, **kwargs):
        return {
            "facts": {
                "event_date": "2026-08-10",
                "employment_start_date": "2026-08-10",
                "written_contract": "否",
                "wage_period": "2026-08",
            },
            "issue_categories": ["contract", "wages"],
            "retrieval_queries": [
                "口頭 勞動合同 合同訂立 合同形式",
                "報酬 訂定 支付期 僱主義務",
            ],
            "missing_facts": self.missing_facts,
            "high_risk": False,
        }

    def analyze_evidence(self, state):
        evidence_by_article = {item.article: item for item in state.evidence}
        article_17 = evidence_by_article["第十七條"]
        article_62 = evidence_by_article["第六十二條"]
        quote_17 = "勞動合同不須遵守特定形式，可以口頭或書面方式訂立"
        quote_62 = "基本報酬須由有關支付義務的到期日起計九個工作日內支付。"
        if self.bad_quote:
            quote_62 = "僱主必須在三十日內支付所有報酬。"
        return {
            "summary": (
                "口頭約定不因欠缺書面合同而當然無效；已提供的十五日工作"
                "仍涉及報酬支付義務。"
            ),
            "analysis": [
                {
                    "statement": "一般勞動合同可以口頭方式訂立。",
                    "evidence_id": article_17.evidence_id,
                    "quote": quote_17,
                },
                {
                    "statement": "基本報酬須在支付義務到期後九個工作日內支付。",
                    "evidence_id": article_62.evidence_id,
                    "quote": quote_62,
                },
            ],
            "options": ["先以訊息或書面方式要求僱主結清約定的報酬。"],
            "next_steps": ["保存能證明實際提供十五日工作的紀錄及雙方通訊。"],
            "uncertainties": ["口頭約定的報酬金額及支付日期仍須由證據確認。"],
        }


def test_llm_plan_and_grounded_analysis_are_verified() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    service = AgentService(repository=repository, audit_log_path=None)

    state = service.handle(
        query=(
            "今年8月10日和僱主口頭約定工作15天以得到一定金錢，"
            "沒有簽合同，工作完成後僱主沒有給錢。"
        ),
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門"},
        case_id="llm-case",
        llm_client=FakeLLMClient(),
    )

    assert state.facts["event_date"] == "2026-08-10"
    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ANSWERED
    assert "口頭方式訂立" in state.answer.analysis[0]
    assert any("九個工作日" in item for item in state.answer.analysis)
    assert all(item.passed for item in state.citation_checks)
    assert state.llm_result is not None
    assert state.llm_result["plan_used"] is True
    assert state.llm_result["analysis_used"] is True


def test_bad_llm_quote_is_blocked_by_citation_verifier() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    service = AgentService(repository=repository, audit_log_path=None)

    state = service.handle(
        query="口頭合同工作後沒有收到報酬。",
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門"},
        case_id="bad-llm-case",
        llm_client=FakeLLMClient(bad_quote=True),
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ESCALATE_HUMAN
    assert any(
        flag.code == "citation_failed" for flag in state.risk_flags
    )


def test_answered_facts_are_not_asked_again() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    service = AgentService(repository=repository, audit_log_path=None)
    repeated_questions = [
        {
            "code": "written_contract",
            "question": "雙方是否曾簽署書面合同？",
            "reason": "確認合同形式",
        },
        {
            "code": "payment_terms",
            "question": "約定的報酬金額及支付日期為何？",
            "reason": "確認工資債權",
        },
        {
            "code": "work_schedule",
            "question": "實際工作起訖日期及每日工時為何？",
            "reason": "計算工作期間",
        },
        {
            "code": "evidence_available",
            "question": "目前有哪些通訊紀錄或證人？",
            "reason": "評估證據",
        },
    ]

    state = service.handle(
        query="口頭約定工作完成後僱主拒絕支付報酬。",
        user_role=UserRole.EMPLOYEE,
        facts={
            "work_location": "澳門",
            "written_contract": "沒有簽署書面合同",
            "payment_terms": "3,000澳門元，2026-09-15支付",
            "work_schedule": "2026-08-17至2026-09-15，除去雙休",
            "evidence_available": "有通訊紀錄及證人",
        },
        case_id="repeated-question-case",
        llm_client=FakeLLMClient(missing_facts=repeated_questions),
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ANSWERED
    assert state.answer.missing_facts == []
