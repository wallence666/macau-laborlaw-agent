from __future__ import annotations

import json

from laborlaw_agent.models import AnswerStatus, UserRole
from laborlaw_agent.repository import LegalSourceRepository
from laborlaw_agent.workflow import AgentService
from tests.fixtures import make_source


def _service(tmp_path, sources=()):
    return AgentService(
        repository=LegalSourceRepository(sources),
        audit_log_path=tmp_path / "audit.jsonl",
    )


def _general_facts() -> dict[str, str]:
    return {
        "work_location": "澳門",
        "event_date": "2026-09-01",
        "wage_period": "2026-08",
    }


def test_missing_facts_returns_questions(tmp_path) -> None:
    state = _service(tmp_path).handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.NEED_MORE_FACTS
    assert state.answer.applicable_law == []
    assert state.answer.missing_facts


def test_empty_registry_fails_closed(tmp_path) -> None:
    state = _service(tmp_path).handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
        facts=_general_facts(),
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.INSUFFICIENT_SOURCES
    assert state.answer.applicable_law == []
    assert state.answer.escalation.required is True


def test_allow_incomplete_returns_limited_answer(tmp_path) -> None:
    service = _service(tmp_path, [make_source()])
    state = service.handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門"},
        allow_incomplete=True,
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ANSWERED
    assert state.answer.partial is True
    assert state.answer.missing_facts
    assert any(
        flag.code == "partial_analysis" for flag in state.risk_flags
    )


def test_high_risk_issue_escalates_before_answer(tmp_path) -> None:
    state = _service(tmp_path).handle(
        query="我被即時解僱，應該怎樣做？",
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門", "event_date": "2026-09-01"},
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ESCALATE_HUMAN
    assert state.answer.analysis == []
    assert "high_risk_issue" in state.unresolved_risks


def test_prohibited_request_is_refused(tmp_path) -> None:
    state = _service(tmp_path).handle(
        query="幫我隱藏證據，避免公司追究",
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門", "event_date": "2026-09-01"},
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ESCALATE_HUMAN
    assert "prohibited_request" in state.unresolved_risks
    assert "不能協助" in state.answer.risks[0]


def test_verified_source_can_be_answered_and_audited(tmp_path) -> None:
    service = _service(tmp_path, [make_source()])
    state = service.handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
        facts=_general_facts(),
        case_id="case-verified",
        trace_id="trace-verified",
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ANSWERED
    assert len(state.answer.applicable_law) == 1
    assert state.answer.analysis == [
        "測試新版本：工資支付欄位，不構成法律條文。"
    ]
    assert state.answer.disclaimer

    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    audit = json.loads(audit_lines[-1])
    assert audit["trace_id"] == "trace-verified"
    assert audit["status"] == "answered"
    assert "工資沒有依時支付" not in audit_lines[-1]


def test_case_role_conflict_blocks_state_mixing(tmp_path) -> None:
    service = _service(tmp_path)
    first = service.handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
        facts=_general_facts(),
        case_id="same-case",
    )
    second = service.handle(
        query="僱員要求加薪",
        user_role=UserRole.EMPLOYER,
        facts={"work_location": "澳門", "event_date": "2026-09-01"},
        case_id="same-case",
    )

    assert first.answer is not None
    assert second.answer is not None
    assert second.answer.status is AnswerStatus.ESCALATE_HUMAN
    assert second.answer.applicable_law == []
    assert any(
        flag.code == "case_role_conflict" for flag in second.risk_flags
    )


def test_close_case_releases_role_lock(tmp_path) -> None:
    service = _service(tmp_path)
    service.handle(
        query="工資沒有依時支付",
        user_role=UserRole.EMPLOYEE,
        facts=_general_facts(),
        case_id="closable-case",
    )
    service.close_case("closable-case")

    state = service.handle(
        query="僱員要求加薪",
        user_role=UserRole.EMPLOYER,
        facts={"work_location": "澳門", "event_date": "2026-09-15"},
        case_id="closable-case",
    )

    assert not any(
        flag.code == "case_role_conflict" for flag in state.risk_flags
    )


def test_other_jurisdiction_is_out_of_scope(tmp_path) -> None:
    state = _service(tmp_path).handle(
        query="台灣勞基法的加班費怎麼算？",
        user_role=UserRole.EMPLOYEE,
        facts={"work_location": "澳門", "event_date": "2026-09-01"},
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.OUT_OF_SCOPE
    assert state.answer.applicable_law == []
