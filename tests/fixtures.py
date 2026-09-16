from __future__ import annotations

from laborlaw_agent.models import (
    LegalProvision,
    LegalSource,
    ReviewStatus,
    SourceType,
)


def make_source(
    *,
    jurisdiction: str = "MO",
    source_type: SourceType = SourceType.OFFICIAL_GUIDANCE,
) -> LegalSource:
    return LegalSource(
        source_id="test-source",
        source_type=source_type,
        official_title="[測試資料] 工資支付流程，不是澳門法律",
        law_number="TEST-ONLY",
        jurisdiction=jurisdiction,
        language="zh-MO",
        source_authority="TEST_ONLY",
        official_url="https://test.invalid/test-only",
        published_at="2024-01-01",
        effective_from="2020-01-01",
        effective_to=None,
        version_label="test-2026",
        checksum="test-checksum",
        retrieved_at="2026-09-15",
        review_status=ReviewStatus.APPROVED,
        reviewed_by="test-reviewer",
        provisions=(
            LegalProvision(
                provision_id="test-provision-old",
                article="TEST-1",
                paragraph="1",
                heading="工資支付",
                text="測試舊版本：工資支付欄位，不構成法律條文。",
                effective_from="2020-01-01",
                effective_to="2024-12-31",
                language="zh-MO",
                official_url="https://test.invalid/test-only/old",
            ),
            LegalProvision(
                provision_id="test-provision-current",
                article="TEST-1",
                paragraph="1",
                heading="工資支付",
                text="測試新版本：工資支付欄位，不構成法律條文。",
                effective_from="2025-01-01",
                effective_to=None,
                language="zh-MO",
                official_url="https://test.invalid/test-only/current",
            ),
        ),
    )
