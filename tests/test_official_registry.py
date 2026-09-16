from __future__ import annotations

from pathlib import Path

from laborlaw_agent.models import AnswerStatus, ReviewStatus, UserRole
from laborlaw_agent.repository import LegalSourceRepository
from laborlaw_agent.workflow import AgentService


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "source-registry"
    / "registry.json"
)


def test_official_registry_is_complete_and_test_approved() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    provisions = [
        provision
        for source in repository.sources
        for provision in source.provisions
    ]

    assert len(repository.sources) == 4
    assert len(provisions) == 106
    assert all(
        source.review_status is ReviewStatus.APPROVED
        for source in repository.sources
    )
    assert all(source.review_scope == "test_only" for source in repository.sources)


def test_official_version_boundaries_are_preserved() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    records = {
        provision.provision_id: (source, provision)
        for source in repository.sources
        for provision in source.provisions
    }

    old_54 = records["mo-law-7-2008-art-54-consolidated-2020"][1]
    new_54 = records["mo-law-7-2008-art-54-amendment-2026"][1]
    old_70 = records["mo-law-7-2008-art-70-consolidated-2020"][1]
    new_70 = records["mo-law-7-2008-art-70-amendment-2024"][1]
    future_46 = records["mo-law-7-2008-art-46-amendment-2026-delayed"][1]

    assert old_54.effective_to == "2026-07-27"
    assert new_54.effective_from == "2026-07-28"
    assert "九十日產假" in new_54.text
    assert old_70.effective_to == "2024-12-26"
    assert new_70.effective_from == "2024-12-27"
    assert "澳門元二萬一千五百元" in new_70.text
    assert future_46.effective_from == "2027-01-01"


def test_official_registry_contains_pdf_page_locations() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    records = {
        provision.provision_id: (source, provision)
        for source in repository.sources
        for provision in source.provisions
    }

    source, article_62 = records[
        "mo-law-7-2008-art-62-consolidated-2020"
    ]

    assert source.pdf_url == (
        "/api/documents/mo-law-7-2008-consolidated-2020"
    )
    assert source.pdf_path is not None
    assert article_62.page_start == 27
    assert article_62.page_end == 27


def test_test_approved_sources_are_returned_for_legal_answers() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)

    results = repository.search_legal_sources(
        query="工資須在九個工作日內支付",
        effective_date="2026-09-15",
    )

    assert any("九個工作日內" in item.content for item in results)
    assert all(item.review_scope == "test_only" for item in results)


def test_approved_official_sources_support_current_and_historical_versions() -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)

    wage_results = repository.search_legal_sources(
        query="基本報酬 支付 九個工作日",
        effective_date="2026-09-15",
    )
    current_maternity = repository.search_legal_sources(
        query="產假 九十日",
        effective_date="2026-09-15",
    )
    previous_maternity = repository.search_legal_sources(
        query="產假 七十日",
        effective_date="2026-07-27",
    )

    assert any("九個工作日內" in item.content for item in wage_results)
    assert any("九十日產假" in item.content for item in current_maternity)
    assert any("七十日產假" in item.content for item in previous_maternity)
    assert not any("九十日產假" in item.content for item in previous_maternity)


def test_official_registry_can_answer_in_test_mode(tmp_path) -> None:
    repository = LegalSourceRepository.from_path(REGISTRY_PATH)
    service = AgentService(
        repository=repository,
        audit_log_path=tmp_path / "audit.jsonl",
    )

    state = service.handle(
        query="工資最遲應在何時支付？",
        user_role=UserRole.EMPLOYEE,
        facts={
            "work_location": "澳門",
            "event_date": "2026-09-15",
            "wage_period": "2026-08",
        },
    )

    assert state.answer is not None
    assert state.answer.status is AnswerStatus.ANSWERED
    assert any(
        "九個工作日內" in item.content for item in state.answer.applicable_law
    )
    assert any("本機測試專用" in risk for risk in state.answer.risks)
