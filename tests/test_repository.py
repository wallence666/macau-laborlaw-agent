from __future__ import annotations

from laborlaw_agent.models import SourceType
from laborlaw_agent.repository import LegalSourceRepository, RegistryError
from tests.fixtures import make_source


def test_effective_date_filters_versions() -> None:
    repository = LegalSourceRepository([make_source()])
    old_results = repository.search_legal_sources(
        query="工資 支付",
        source_types={SourceType.OFFICIAL_GUIDANCE},
        effective_date="2024-01-01",
    )
    current_results = repository.search_legal_sources(
        query="工資 支付",
        source_types={SourceType.OFFICIAL_GUIDANCE},
        effective_date="2026-01-01",
    )

    assert [item.content for item in old_results] == [
        "測試舊版本：工資支付欄位，不構成法律條文。"
    ]
    assert [item.content for item in current_results] == [
        "測試新版本：工資支付欄位，不構成法律條文。"
    ]


def test_non_mo_source_is_rejected() -> None:
    source = make_source(jurisdiction="TW")
    try:
        LegalSourceRepository([source])
    except RegistryError as exc:
        assert "法域不是 MO" in str(exc)
    else:
        raise AssertionError("應拒絕非澳門法域來源。")


def test_guidance_search_filters_source_type(tmp_path) -> None:
    repository = LegalSourceRepository(
        [make_source(source_type=SourceType.OFFICIAL_GUIDANCE)]
    )

    guidance = repository.search_official_guidance(
        query="工資支付",
        effective_date="2026-01-01",
    )

    assert len(guidance) == 1
