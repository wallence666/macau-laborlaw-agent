from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "data" / "snapshots" / "mo"
DEFAULT_OUTPUT = ROOT / "data" / "source-registry" / "registry.json"

BASE_PDF = SNAPSHOT_DIR / "mo-labor-relations-law-7-2008-consolidated-2020.pdf"
LAW_23_2024_PDF = SNAPSHOT_DIR / "mo-law-23-2024-amendment.pdf"
LAW_9_2026_PDF = SNAPSHOT_DIR / "mo-law-9-2026-amendment.pdf"

BASE_URL = "https://search.bo.dsaj.gov.mo/zh-mo/legismac/58185"
LAW_23_2024_URL = "https://search.bo.dsaj.gov.mo/zh-mo/legismac/92511"
LAW_9_2026_URL = "https://search.bo.dsaj.gov.mo/zh-mo/legismac/95002"

HAN_PATTERN = re.compile(r"[\u3400-\u9fff]")
ARTICLE_PATTERN = re.compile(
    r"^(?P<quote>[“\"]?)第(?P<number>[一二三四五六七八九十百零]+)"
    r"(?:-(?P<suffix>[A-Z]))?條(?P<end_quote>”?)$"
)
SECTION_PATTERN = re.compile(
    r"^第[一二三四五六七八九十百零]+(?:章|節|編|分節)$"
)
PARAGRAPH_PATTERN = re.compile(
    r"^(?P<label>[一二三四五六七八九十百零]+)、"
)
SUBPARAGRAPH_PATTERN = re.compile(r"^（(?P<label>[一二三四五六七八九十]+)）")
PLACEHOLDER_PATTERN = re.compile(r"^〔[……\.]+〕$")

CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_han_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = [
                word
                for word in page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=3,
                    keep_blank_chars=False,
                )
                if HAN_PATTERN.search(word["text"])
            ]
            page_lines: list[dict[str, Any]] = []
            for word in words:
                for line in page_lines:
                    if abs(line["top"] - word["top"]) <= 3:
                        line["words"].append(word)
                        break
                else:
                    page_lines.append({"top": word["top"], "words": [word]})
            for line in sorted(page_lines, key=lambda item: item["top"]):
                text = "".join(
                    word["text"]
                    for word in sorted(line["words"], key=lambda item: item["x0"])
                ).strip()
                if text:
                    lines.append((page.page_number, text))
    return lines


def parse_main_articles(
    lines: list[tuple[int, str]],
) -> OrderedDict[str, dict[str, Any]]:
    headings: list[tuple[int, re.Match[str]]] = []
    quote_depth = 0
    started = False
    for index, (_, line) in enumerate(lines):
        match = ARTICLE_PATTERN.fullmatch(line)
        if match and not match.group("quote") and quote_depth == 0:
            if line == "第一條":
                started = True
            if started:
                headings.append((index, match))
            if line == "第九十七條":
                break
        quote_depth += line.count("“") - line.count("”")

    articles: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for position, (index, match) in enumerate(headings):
        next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        article_label = match.group(0)
        title = lines[index + 1][1].strip() if index + 1 < next_index else ""
        body = clean_body_lines(lines[index + 2 : next_index], article_label=article_label)
        if article_label == "第九十七條":
            body = _trim_after(body, "二零零八年八月五日通過。")
        body_text = "\n".join(text for _, text in body)
        text = "\n".join([title, *(text for _, text in body)]).strip()
        key = article_key(match)
        articles[key] = {
            "label": article_label,
            "title": title,
            "body": body_text,
            "text": text,
            "page_start": lines[index][0],
            "page_end": max(
                [lines[index][0], *(page for page, _ in body)],
                default=lines[index][0],
            ),
        }
    return articles


def parse_quoted_articles(
    lines: list[tuple[int, str]], expected: set[str]
) -> OrderedDict[str, dict[str, Any]]:
    quoted_blocks: list[tuple[int, re.Match[str]]] = []
    active = False
    closing_index: int | None = None
    for index, (_, line) in enumerate(lines):
        normalized = line.strip()
        if not active and normalized.startswith("“"):
            match = ARTICLE_PATTERN.fullmatch(normalized)
            if match:
                active = True
        if not active:
            continue
        match = ARTICLE_PATTERN.fullmatch(normalized)
        if match:
            quoted_blocks.append((index, match))
        if normalized.endswith("”") and not normalized.startswith("“"):
            closing_index = index + 1
            break

    articles: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for position, (index, match) in enumerate(quoted_blocks):
        key = article_key(match)
        if key not in expected:
            continue
        next_index = (
            quoted_blocks[position + 1][0]
            if position + 1 < len(quoted_blocks)
            else (closing_index if closing_index is not None else len(lines))
        )
        article_label = match.group(0).lstrip("“").rstrip("”")
        title = lines[index + 1][1].strip() if index + 1 < next_index else ""
        body = clean_body_lines(
            lines[index + 2 : next_index],
            article_label=article_label,
            strip_terminal_quote=True,
        )
        body_text = "\n".join(text for _, text in body)
        articles[key] = {
            "label": article_label,
            "title": title,
            "body": body_text,
            "text": "\n".join([title, *(text for _, text in body)]).strip(),
            "page_start": lines[index][0],
            "page_end": max(
                [lines[index][0], *(page for page, _ in body)],
                default=lines[index][0],
            ),
        }
    return articles


def clean_body_lines(
    lines: list[tuple[int, str]],
    *,
    article_label: str,
    strip_terminal_quote: bool = False,
) -> list[tuple[int, str]]:
    cleaned: list[tuple[int, str]] = []
    skip_next_section_title = False
    for page_number, raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if "澳門特別行政區公報——第一組" in line:
            continue
        if line.startswith("N.º") or line.startswith("BOLETIM"):
            continue
        if SECTION_PATTERN.fullmatch(line):
            skip_next_section_title = True
            continue
        if skip_next_section_title:
            skip_next_section_title = False
            if not ARTICLE_PATTERN.fullmatch(line):
                continue
        if strip_terminal_quote and line.endswith("”"):
            line = line[:-1]
        if line:
            cleaned.append((page_number, line))
    return cleaned


def merge_article_version(
    base_article: dict[str, str], amendment_article: dict[str, str]
) -> str:
    base_paragraphs = split_paragraphs(base_article["body"])
    amendment_paragraphs = split_paragraphs(amendment_article["body"])
    merged = OrderedDict(base_paragraphs)

    for key, amendment_paragraph in amendment_paragraphs.items():
        base_paragraph = base_paragraphs.get(key)
        if base_paragraph is None:
            merged[key] = amendment_paragraph
            continue

        amendment_prefix, amendment_subparagraphs = split_subparagraphs(
            amendment_paragraph["lines"]
        )
        base_prefix, base_subparagraphs = split_subparagraphs(base_paragraph["lines"])
        placeholder = (
            bool(amendment_prefix)
            and PLACEHOLDER_PATTERN.fullmatch(
                amendment_prefix[0].split("、", 1)[-1].strip()
            )
        )

        if placeholder:
            prefix = base_prefix
        else:
            prefix = amendment_prefix or base_prefix

        if amendment_subparagraphs:
            merged_subparagraphs: list[dict[str, Any]] = []
            base_by_label = {
                item["label"]: item for item in base_subparagraphs
            }
            for item in amendment_subparagraphs:
                content = item["text_without_label"].strip()
                if not content or PLACEHOLDER_PATTERN.fullmatch(content):
                    fallback = base_by_label.get(item["label"])
                    if fallback:
                        merged_subparagraphs.append(fallback)
                        continue
                merged_subparagraphs.append(item)
            lines = [*prefix, *render_subparagraphs(merged_subparagraphs)]
        elif placeholder:
            lines = base_paragraph["lines"]
        else:
            lines = amendment_paragraph["lines"]
        merged[key] = {
            "label": key,
            "lines": lines,
            "text": "\n".join(lines),
        }

    body = "\n".join(
        paragraph["text"] for paragraph in merged.values()
    )
    return "\n".join([amendment_article["title"], body]).strip()


def split_paragraphs(body: str) -> OrderedDict[str, dict[str, Any]]:
    paragraphs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    current_label: str | None = None
    current_lines: list[str] = []
    for line in body.splitlines():
        match = PARAGRAPH_PATTERN.match(line)
        if match:
            if current_label is not None:
                paragraphs[current_label] = {
                    "label": current_label,
                    "lines": current_lines,
                    "text": "\n".join(current_lines),
                }
            current_label = match.group("label")
            current_lines = [line]
        elif current_label is not None:
            current_lines.append(line)
    if current_label is not None:
        paragraphs[current_label] = {
            "label": current_label,
            "lines": current_lines,
            "text": "\n".join(current_lines),
        }
    if not paragraphs:
        paragraphs["__single__"] = {
            "label": "__single__",
            "lines": body.splitlines(),
            "text": body,
        }
    return paragraphs


def split_subparagraphs(
    lines: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    prefix: list[str] = []
    subparagraphs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        match = SUBPARAGRAPH_PATTERN.match(line)
        if match:
            if current:
                subparagraphs.append(_finalize_subparagraph(current))
            current = {"label": match.group("label"), "lines": [line]}
        elif current:
            current["lines"].append(line)
        else:
            prefix.append(line)
    if current:
        subparagraphs.append(_finalize_subparagraph(current))
    return prefix, subparagraphs


def render_subparagraphs(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(item["lines"])
    return lines


def _finalize_subparagraph(item: dict[str, Any]) -> dict[str, Any]:
    line = item["lines"][0]
    return {
        "label": item["label"],
        "lines": item["lines"],
        "text_without_label": line.split("）", 1)[-1],
    }


def _trim_after(
    lines: list[tuple[int, str]], marker: str
) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for line in lines:
        result.append(line)
        if marker in line[1]:
            break
    return result


def article_key(match: re.Match[str]) -> str:
    number = chinese_number_to_int(match.group("number"))
    suffix = match.group("suffix") or ""
    return f"{number}{suffix}"


def chinese_number_to_int(value: str) -> int:
    if value == "零":
        return 0
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
        elif char == "十":
            section += (number or 1) * 10
            number = 0
        elif char == "百":
            section += (number or 1) * 100
            number = 0
    total += section + number
    return total


def make_provision(
    *,
    article: dict[str, str],
    key: str,
    source_slug: str,
    effective_from: str,
    effective_to: str | None,
    official_url: str,
) -> dict[str, Any]:
    return {
        "provision_id": f"mo-law-7-2008-art-{key}-{source_slug}",
        "article": article["label"],
        "heading": article["title"],
        "text": article["text"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "language": "zh-MO",
        "official_url": official_url,
        "page_start": article.get("page_start"),
        "page_end": article.get("page_end"),
    }


def make_source(
    *,
    source_id: str,
    version_label: str,
    official_title: str,
    law_number: str,
    published_at: str,
    effective_from: str,
    effective_to: str | None,
    retrieved_at: str,
    checksum: str,
    official_url: str,
    pdf_path: str,
    provisions: list[dict[str, Any]],
    approve_for_testing: bool,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": "law",
        "official_title": official_title,
        "law_number": law_number,
        "jurisdiction": "MO",
        "language": "zh-MO",
        "source_authority": "澳門特別行政區公報／法務局 LegisMac",
        "official_url": official_url,
        "pdf_url": f"/api/documents/{source_id}",
        "pdf_path": pdf_path,
        "published_at": published_at,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "version_label": version_label,
        "checksum": checksum,
        "retrieved_at": retrieved_at,
        "review_status": "approved" if approve_for_testing else "pending",
        "reviewed_by": (
            "專案使用者測試授權（非法律審核）"
            if approve_for_testing
            else "待澳門法律專業人士覆核"
        ),
        "review_scope": "test_only" if approve_for_testing else "unreviewed",
        "provisions": provisions,
    }


def build_registry(
    output: Path, *, approve_for_testing: bool = False
) -> dict[str, Any]:
    retrieved_at = "2026-09-15"
    base_lines = extract_han_lines(BASE_PDF)
    base_articles = parse_main_articles(base_lines)
    if len(base_articles) != 100:
        raise RuntimeError(f"預期 100 條主條文，實際解析到 {len(base_articles)} 條。")

    amendment_23_lines = extract_han_lines(LAW_23_2024_PDF)
    amendment_9_lines = extract_han_lines(LAW_9_2026_PDF)
    amendment_23 = parse_quoted_articles(amendment_23_lines, {"70"})
    amendment_9 = parse_quoted_articles(
        amendment_9_lines, {"46", "54", "56", "75", "85"}
    )
    if set(amendment_23) != {"70"}:
        raise RuntimeError("第23/2024號法律解析失敗。")
    if set(amendment_9) != {"46", "54", "56", "75", "85"}:
        raise RuntimeError("第9/2026號法律解析失敗。")

    base_effective_to = {
        "70": "2024-12-26",
        "54": "2026-07-27",
        "56": "2026-07-27",
        "46": "2026-12-31",
        "75": "2026-12-31",
        "85": "2026-12-31",
    }
    base_provisions = [
        make_provision(
            article=article,
            key=key,
            source_slug="consolidated-2020",
            effective_from="2020-06-22",
            effective_to=base_effective_to.get(key),
            official_url=BASE_URL,
        )
        for key, article in base_articles.items()
    ]

    article_70 = {
        **amendment_23["70"],
        "text": merge_article_version(base_articles["70"], amendment_23["70"]),
    }
    article_54 = {
        **amendment_9["54"],
        "text": merge_article_version(base_articles["54"], amendment_9["54"]),
    }
    article_56 = {
        **amendment_9["56"],
        "text": merge_article_version(base_articles["56"], amendment_9["56"]),
    }
    future_articles = {
        key: {
            **amendment_9[key],
            "text": merge_article_version(base_articles[key], amendment_9[key]),
        }
        for key in ("46", "75", "85")
    }

    sources = [
        make_source(
            source_id="mo-law-7-2008-consolidated-2020",
            version_label="BORAEM 25/2020, Despacho 134/2020",
            official_title=(
                "第7/2008號法律《勞動關係法》"
                "（經第134/2020號行政長官批示重新公佈）"
            ),
            law_number="第7/2008號法律",
            published_at="2020-06-22",
            effective_from="2020-06-22",
            effective_to=None,
            retrieved_at=retrieved_at,
            checksum=sha256(BASE_PDF),
            official_url=BASE_URL,
            pdf_path=str(BASE_PDF.relative_to(ROOT)).replace("\\", "/"),
            provisions=base_provisions,
            approve_for_testing=approve_for_testing,
        ),
        make_source(
            source_id="mo-law-23-2024-amendment",
            version_label="BORAEM 52/2024, Lei 23/2024",
            official_title="第23/2024號法律（修改《勞動關係法》第七十條）",
            law_number="第23/2024號法律",
            published_at="2024-12-26",
            effective_from="2024-12-27",
            effective_to=None,
            retrieved_at=retrieved_at,
            checksum=sha256(LAW_23_2024_PDF),
            official_url=LAW_23_2024_URL,
            pdf_path=str(LAW_23_2024_PDF.relative_to(ROOT)).replace("\\", "/"),
            provisions=[
                make_provision(
                    article=article_70,
                    key="70",
                    source_slug="amendment-2024",
                    effective_from="2024-12-27",
                    effective_to=None,
                    official_url=LAW_23_2024_URL,
                )
            ],
            approve_for_testing=approve_for_testing,
        ),
        make_source(
            source_id="mo-law-9-2026-immediate",
            version_label="BORAEM 30/2026, Lei 9/2026, immediate effects",
            official_title="第9/2026號法律（即日生效部分）",
            law_number="第9/2026號法律",
            published_at="2026-07-27",
            effective_from="2026-07-28",
            effective_to=None,
            retrieved_at=retrieved_at,
            checksum=sha256(LAW_9_2026_PDF),
            official_url=LAW_9_2026_URL,
            pdf_path=str(LAW_9_2026_PDF.relative_to(ROOT)).replace("\\", "/"),
            provisions=[
                make_provision(
                    article=article_54,
                    key="54",
                    source_slug="amendment-2026",
                    effective_from="2026-07-28",
                    effective_to=None,
                    official_url=LAW_9_2026_URL,
                ),
                make_provision(
                    article=article_56,
                    key="56",
                    source_slug="amendment-2026",
                    effective_from="2026-07-28",
                    effective_to=None,
                    official_url=LAW_9_2026_URL,
                ),
            ],
            approve_for_testing=approve_for_testing,
        ),
        make_source(
            source_id="mo-law-9-2026-delayed",
            version_label="BORAEM 30/2026, Lei 9/2026, delayed effects",
            official_title="第9/2026號法律（自2027-01-01產生效力部分）",
            law_number="第9/2026號法律",
            published_at="2026-07-27",
            effective_from="2027-01-01",
            effective_to=None,
            retrieved_at=retrieved_at,
            checksum=sha256(LAW_9_2026_PDF),
            official_url=LAW_9_2026_URL,
            pdf_path=str(LAW_9_2026_PDF.relative_to(ROOT)).replace("\\", "/"),
            provisions=[
                make_provision(
                    article=future_articles[key],
                    key=key,
                    source_slug="amendment-2026-delayed",
                    effective_from="2027-01-01",
                    effective_to=None,
                    official_url=LAW_9_2026_URL,
                )
                for key in ("46", "75", "85")
            ],
            approve_for_testing=approve_for_testing,
        ),
    ]

    payload = {
        "schema_version": "1.0",
        "jurisdiction": "MO",
        "generated_at": retrieved_at,
        "review_state": (
            "approved_for_local_testing_only"
            if approve_for_testing
            else "pending_legal_review"
        ),
        "sources": sources,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="從官方澳門公報 PDF 建立勞動法 registry。"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--approve-for-testing",
        action="store_true",
        help="以本機測試用途把來源標記為 approved，不代表法律審核。",
    )
    args = parser.parse_args()
    payload = build_registry(
        args.output,
        approve_for_testing=args.approve_for_testing,
    )
    provision_count = sum(
        len(source["provisions"]) for source in payload["sources"]
    )
    print(
        f"已建立 {len(payload['sources'])} 個來源、"
        f"{provision_count} 條 provision：{args.output}"
    )
    if args.approve_for_testing:
        print("已標記為本機測試專用核准，不代表澳門法律專業人士審核。")
    else:
        print("review_status 維持 pending，須由澳門法律專業人士覆核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
