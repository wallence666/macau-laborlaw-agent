from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import CaseState, to_plain_data


@dataclass
class AuditRecord:
    trace_id: str
    case_id: str
    created_at: str
    status: str
    source_ids: list[str] = field(default_factory=list)
    handoff_count: int = 0
    tests: list[str] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)
    retention_days: int = 30


class AuditLogger:
    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None

    def write(self, state: CaseState) -> AuditRecord:
        status = state.answer.status.value if state.answer else "not_assembled"
        record = AuditRecord(
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
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(to_plain_data(record), ensure_ascii=False) + "\n"
                )
        return record
