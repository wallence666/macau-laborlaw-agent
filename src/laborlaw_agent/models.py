from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo


MACAU_TZ = ZoneInfo("Asia/Macau")


def now_mo() -> str:
    return datetime.now(MACAU_TZ).isoformat(timespec="seconds")


class UserRole(str, Enum):
    EMPLOYEE = "employee"
    EMPLOYER = "employer"
    REPRESENTATIVE = "representative"
    OTHER = "other"
    UNKNOWN = "unknown"


class IssueCategory(str, Enum):
    WAGES = "wages"
    WORKING_TIME = "working_time"
    WEEKLY_REST = "weekly_rest"
    MANDATORY_HOLIDAY = "mandatory_holiday"
    ANNUAL_LEAVE = "annual_leave"
    SICK_LEAVE = "sick_leave"
    PROBATION = "probation"
    CONTRACT = "contract"
    TERMINATION = "termination"
    WORK_ACCIDENT = "work_accident"
    OCCUPATIONAL_DISEASE = "occupational_disease"
    FOREIGN_EMPLOYEE = "foreign_employee"
    MATERNITY = "maternity"
    DISCRIMINATION = "discrimination"
    MINOR = "minor"
    COLLECTIVE = "collective"
    CRIMINAL = "criminal"
    OTHER = "other"


class SourceType(str, Enum):
    LAW = "law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    OFFICIAL_GUIDANCE = "official_guidance"
    COURT_DECISION = "court_decision"
    APPROVED_COMMENTARY = "approved_commentary"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AnswerStatus(str, Enum):
    NEED_MORE_FACTS = "need_more_facts"
    ANSWERED = "answered"
    INSUFFICIENT_SOURCES = "insufficient_sources"
    ESCALATE_HUMAN = "escalate_human"
    OUT_OF_SCOPE = "out_of_scope"


class RiskSeverity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class LegalProvision:
    provision_id: str
    article: str
    text: str
    effective_from: str
    language: str
    paragraph: str | None = None
    subparagraph: str | None = None
    heading: str | None = None
    effective_to: str | None = None
    official_url: str | None = None
    parent_provision_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LegalProvision":
        return cls(
            provision_id=str(data["provision_id"]),
            article=str(data["article"]),
            paragraph=_optional_str(data.get("paragraph")),
            subparagraph=_optional_str(data.get("subparagraph")),
            heading=_optional_str(data.get("heading")),
            text=str(data["text"]),
            effective_from=str(data["effective_from"]),
            effective_to=_optional_str(data.get("effective_to")),
            official_url=_optional_str(data.get("official_url")),
            language=str(data["language"]),
            parent_provision_id=_optional_str(data.get("parent_provision_id")),
            page_start=_optional_int(data.get("page_start")),
            page_end=_optional_int(data.get("page_end")),
        )


@dataclass(frozen=True)
class LegalSource:
    source_id: str
    source_type: SourceType
    official_title: str
    law_number: str
    jurisdiction: str
    language: str
    source_authority: str
    official_url: str
    published_at: str
    effective_from: str
    version_label: str
    checksum: str
    retrieved_at: str
    review_status: ReviewStatus
    reviewed_by: str
    provisions: tuple[LegalProvision, ...]
    effective_to: str | None = None
    review_scope: str = "production"
    pdf_url: str | None = None
    pdf_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LegalSource":
        return cls(
            source_id=str(data["source_id"]),
            source_type=SourceType(data["source_type"]),
            official_title=str(data["official_title"]),
            law_number=str(data["law_number"]),
            jurisdiction=str(data["jurisdiction"]),
            language=str(data["language"]),
            source_authority=str(data["source_authority"]),
            official_url=str(data["official_url"]),
            published_at=str(data["published_at"]),
            effective_from=str(data["effective_from"]),
            effective_to=_optional_str(data.get("effective_to")),
            version_label=str(data["version_label"]),
            checksum=str(data["checksum"]),
            retrieved_at=str(data["retrieved_at"]),
            review_status=ReviewStatus(data["review_status"]),
            reviewed_by=str(data["reviewed_by"]),
            provisions=tuple(
                LegalProvision.from_dict(item) for item in data.get("provisions", [])
            ),
            review_scope=str(data.get("review_scope", "production")),
            pdf_url=_optional_str(data.get("pdf_url")),
            pdf_path=_optional_str(data.get("pdf_path")),
        )


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    provision_id: str
    content: str
    law_title: str
    law_number: str
    article: str
    paragraph: str | None
    subparagraph: str | None
    effective_from: str
    effective_to: str | None
    official_url: str
    source_type: SourceType
    language: str
    version_label: str
    review_scope: str
    pdf_url: str | None
    page_start: int | None
    page_end: int | None
    score: float
    retrieval_method: str


@dataclass(frozen=True)
class VersionDiff:
    provision_id: str
    from_date: str
    to_date: str
    old_text: str | None
    new_text: str | None
    changed: bool


@dataclass
class MissingFact:
    code: str
    question: str
    reason: str


@dataclass
class LegalClaim:
    claim_id: str
    claim_type: str
    text: str
    evidence_ids: list[str]
    support_quote: str | None = None
    accepted: bool = True


@dataclass
class CitationCheck:
    claim_id: str
    passed: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class RiskFlag:
    code: str
    severity: RiskSeverity
    message: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Escalation:
    required: bool = False
    reasons: list[str] = field(default_factory=list)
    recipient_type: str | None = None


@dataclass
class AgentHandoff:
    task_id: str
    from_agent: str
    to_agent: str
    status: str
    artifact_keys: list[str]
    decisions: list[str]
    tests: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    trace_id: str = ""
    created_at: str = field(default_factory=now_mo)


@dataclass
class Answer:
    status: AnswerStatus
    role: UserRole
    summary: str
    known_facts: list[dict[str, Any]] = field(default_factory=list)
    missing_facts: list[MissingFact] = field(default_factory=list)
    applicable_law: list[Evidence] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    escalation: Escalation = field(default_factory=Escalation)
    disclaimer: str = ""
    trace_id: str = ""
    unresolved_risks: list[str] = field(default_factory=list)
    partial: bool = False


@dataclass
class CaseState:
    case_id: str
    trace_id: str
    raw_query: str
    user_role: UserRole = UserRole.UNKNOWN
    jurisdiction: str = "MO"
    language: str = "zh-MO"
    facts: dict[str, Any] = field(default_factory=dict)
    missing_facts: list[MissingFact] = field(default_factory=list)
    issue_categories: list[IssueCategory] = field(default_factory=list)
    event_dates: dict[str, str] = field(default_factory=dict)
    retrieval_queries: list[str] = field(default_factory=list)
    retrieval_query_weights: dict[str, float] = field(default_factory=dict)
    llm_queries: list[str] = field(default_factory=list)
    llm_result: dict[str, Any] | None = None
    evidence: list[Evidence] = field(default_factory=list)
    legal_claims: list[LegalClaim] = field(default_factory=list)
    citation_checks: list[CitationCheck] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)
    escalation_required: bool = False
    escalation_reasons: list[str] = field(default_factory=list)
    allow_incomplete: bool = False
    answer: Answer | None = None
    scope_status: AnswerStatus | None = None
    scope_reason: str | None = None
    source_ids: list[str] = field(default_factory=list)
    handoffs: list[AgentHandoff] = field(default_factory=list)
    audit_tests: list[str] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)
    retention_days: int = 30
    created_at: str = field(default_factory=now_mo)
    updated_at: str = field(default_factory=now_mo)

    def touch(self) -> None:
        self.updated_at = now_mo()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_plain_data(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: to_plain_data(item)
            for key, item in asdict(value).items()
        }
    return value
