from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .models import (
    Evidence,
    LegalProvision,
    LegalSource,
    ReviewStatus,
    SourceType,
    VersionDiff,
)


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SourceProvision:
    source: LegalSource
    provision: LegalProvision


class LegalSourceRepository:
    def __init__(self, sources: Iterable[LegalSource]) -> None:
        self.sources = tuple(sources)
        self._validate()
        self._provisions: tuple[SourceProvision, ...] = tuple(
            SourceProvision(source=source, provision=provision)
            for source in self.sources
            for provision in source.provisions
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "LegalSourceRepository":
        registry_path = Path(path)
        if not registry_path.exists():
            raise RegistryError(f"找不到法源 registry：{registry_path}")
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"無法讀取法源 registry：{exc}") from exc

        if payload.get("schema_version") != "1.0":
            raise RegistryError("不支援的法源 registry schema_version。")

        try:
            sources = [
                LegalSource.from_dict(item) for item in payload.get("sources", [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryError(f"法源 registry 欄位不完整或格式錯誤：{exc}") from exc
        return cls(sources)

    def search_legal_sources(
        self,
        query: str,
        jurisdiction: str = "MO",
        source_types: set[SourceType] | None = None,
        effective_date: str | None = None,
        top_k: int = 30,
        rerank_top_n: int = 8,
    ) -> list[Evidence]:
        as_of = effective_date or date.today().isoformat()
        query_terms = _query_terms(query)
        if not query_terms:
            return []

        allowed_types = source_types or {
            SourceType.LAW,
            SourceType.ADMINISTRATIVE_REGULATION,
            SourceType.COURT_DECISION,
            SourceType.APPROVED_COMMENTARY,
        }
        ranked: list[tuple[float, SourceProvision]] = []
        for item in self._provisions:
            source = item.source
            provision = item.provision
            if source.review_status is not ReviewStatus.APPROVED:
                continue
            if source.jurisdiction != jurisdiction:
                continue
            if source.source_type not in allowed_types:
                continue
            if not _is_active(source.effective_from, source.effective_to, as_of):
                continue
            if not _is_active(provision.effective_from, provision.effective_to, as_of):
                continue

            score = _score(query, query_terms, source, provision)
            if score > 0:
                ranked.append((score, item))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            _to_evidence(item, score)
            for score, item in ranked[: min(top_k, max(rerank_top_n, 0))]
        ]

    def search_official_guidance(
        self,
        query: str,
        authority: str | None = None,
        effective_date: str | None = None,
        jurisdiction: str = "MO",
        top_k: int = 10,
    ) -> list[Evidence]:
        if authority:
            query = f"{query} {authority}"
        return self.search_legal_sources(
            query=query,
            jurisdiction=jurisdiction,
            source_types={SourceType.OFFICIAL_GUIDANCE},
            effective_date=effective_date,
            top_k=top_k,
            rerank_top_n=top_k,
        )

    def fetch_provision(
        self,
        law_id: str,
        article: str,
        paragraph: str | None,
        effective_date: str,
        language: str,
    ) -> Evidence | None:
        for item in self._provisions:
            source = item.source
            provision = item.provision
            matches_law = source.source_id == law_id or source.law_number == law_id
            matches_paragraph = paragraph is None or provision.paragraph == paragraph
            if (
                matches_law
                and provision.article == article
                and matches_paragraph
                and provision.language == language
                and source.review_status is ReviewStatus.APPROVED
                and source.jurisdiction == "MO"
                and _is_active(source.effective_from, source.effective_to, effective_date)
                and _is_active(
                    provision.effective_from, provision.effective_to, effective_date
                )
            ):
                return _to_evidence(item, 1.0)
        return None

    def compare_provision_versions(
        self, provision_id: str, from_date: str, to_date: str
    ) -> VersionDiff:
        versions = [
            item
            for item in self._provisions
            if item.provision.provision_id == provision_id
        ]
        old_item = next(
            (
                item
                for item in versions
                if _is_active(
                    item.provision.effective_from,
                    item.provision.effective_to,
                    from_date,
                )
            ),
            None,
        )
        new_item = next(
            (
                item
                for item in versions
                if _is_active(
                    item.provision.effective_from,
                    item.provision.effective_to,
                    to_date,
                )
            ),
            None,
        )
        old_text = old_item.provision.text if old_item else None
        new_text = new_item.provision.text if new_item else None
        return VersionDiff(
            provision_id=provision_id,
            from_date=from_date,
            to_date=to_date,
            old_text=old_text,
            new_text=new_text,
            changed=old_text != new_text,
        )

    def find_evidence_source(self, evidence: Evidence) -> SourceProvision | None:
        for item in self._provisions:
            if (
                item.source.source_id == evidence.source_id
                and item.provision.provision_id == evidence.provision_id
            ):
                return item
        return None

    def has_version_conflict(self, evidence: list[Evidence]) -> bool:
        groups: dict[tuple[str, str, str | None], set[tuple[str, str]]] = {}
        active_ids = {item.evidence_id for item in evidence}
        for item in self._provisions:
            evidence_id = f"{item.source.source_id}:{item.provision.provision_id}"
            if evidence_id not in active_ids:
                continue
            key = (
                item.source.law_number,
                item.provision.article,
                item.provision.paragraph,
            )
            groups.setdefault(key, set()).add(
                (item.source.version_label, item.provision.text)
            )
        return any(len(values) > 1 for values in groups.values())

    def _validate(self) -> None:
        source_ids: set[str] = set()
        provision_ids: set[str] = set()
        for source in self.sources:
            if source.source_id in source_ids:
                raise RegistryError(f"重複 source_id：{source.source_id}")
            source_ids.add(source.source_id)
            if source.jurisdiction != "MO":
                raise RegistryError(f"{source.source_id} 的法域不是 MO。")
            if not source.official_url.startswith(("https://", "http://")):
                raise RegistryError(f"{source.source_id} 缺少可用官方網址。")
            if source.review_status is ReviewStatus.APPROVED and not source.reviewed_by:
                raise RegistryError(f"{source.source_id} 已核准但沒有 reviewed_by。")
            for provision in source.provisions:
                if provision.provision_id in provision_ids:
                    raise RegistryError(
                        f"重複 provision_id：{provision.provision_id}"
                    )
                provision_ids.add(provision.provision_id)
                if not provision.text.strip():
                    raise RegistryError(
                        f"{provision.provision_id} 沒有條文內容。"
                    )


def _optional_text(value: str | None) -> str:
    return value or ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _query_terms(query: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", query.lower()))
    terms = {word for word in words if len(word) >= 2}
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            for size in (2, 3, 4):
                if len(word) >= size:
                    terms.update(
                        word[index : index + size]
                        for index in range(len(word) - size + 1)
                    )
    return terms


def _score(
    query: str,
    query_terms: set[str],
    source: LegalSource,
    provision: LegalProvision,
) -> float:
    title_haystack = _normalize(
        " ".join(
            [
                source.official_title,
                source.law_number,
                source.source_authority,
                _optional_text(provision.heading),
                provision.article,
            ]
        )
    )
    body_haystack = _normalize(
        " ".join(
            [
                _optional_text(provision.paragraph),
                provision.text,
            ]
        )
    )
    score = 0.0
    normalized_query = _normalize(query)
    if normalized_query and normalized_query in title_haystack:
        score += 30.0
    elif normalized_query and normalized_query in body_haystack:
        score += 20.0
    for term in query_terms:
        term_weight = min(len(term), 5)
        if term in title_haystack:
            score += term_weight * 1.5
        if term in body_haystack:
            score += term_weight
    length_penalty = min(len(body_haystack) / 600.0, 3.0)
    return max(score - length_penalty, 0.0)


def _is_active(
    effective_from: str, effective_to: str | None, effective_date: str
) -> bool:
    try:
        start = date.fromisoformat(effective_from)
        end = date.fromisoformat(effective_to) if effective_to else None
        target = date.fromisoformat(effective_date)
    except ValueError:
        return False
    return start <= target and (end is None or target <= end)


def _to_evidence(item: SourceProvision, score: float) -> Evidence:
    source = item.source
    provision = item.provision
    return Evidence(
        evidence_id=f"{source.source_id}:{provision.provision_id}",
        source_id=source.source_id,
        provision_id=provision.provision_id,
        content=provision.text,
        law_title=source.official_title,
        law_number=source.law_number,
        article=provision.article,
        paragraph=provision.paragraph,
        subparagraph=provision.subparagraph,
        effective_from=provision.effective_from,
        effective_to=provision.effective_to,
        official_url=provision.official_url or source.official_url,
        source_type=source.source_type,
        language=source.language,
        version_label=source.version_label,
        review_scope=source.review_scope,
        pdf_url=source.pdf_url,
        page_start=provision.page_start,
        page_end=provision.page_end,
        score=round(score, 4),
        retrieval_method="keyword_version_filter",
    )
