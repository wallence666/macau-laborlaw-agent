from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .models import UserRole, to_plain_data
from .repository import LegalSourceRepository, RegistryError
from .workflow import AgentService


DEFAULT_REGISTRY = Path("data/source-registry/registry.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="澳門勞動法資訊與初步風險評估 Agent MVP"
    )
    parser.add_argument("--query", help="使用者的自然語言問題。")
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.UNKNOWN.value,
        help="使用者角色。",
    )
    parser.add_argument(
        "--fact",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="結構化事實，可重複使用。",
    )
    parser.add_argument("--event-date", help="事件日期，格式 YYYY-MM-DD。")
    parser.add_argument("--case-id", help="案件 ID；相同案件不得切換角色。")
    parser.add_argument("--trace-id", help="追蹤 ID。")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="法源 registry JSON 路徑。",
    )
    parser.add_argument(
        "--audit-log",
        default="artifacts/audit/audit.jsonl",
        help="最小化審計 JSONL 路徑；傳入空字串可停用。",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="缺少事實時在終端追問。",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="缺少事實時仍按目前資料作有限分析。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repository = LegalSourceRepository.from_path(args.registry)
    except RegistryError as exc:
        parser.error(str(exc))

    service = AgentService(
        repository=repository,
        audit_log_path=args.audit_log or None,
    )
    if args.interactive:
        return _interactive(service, args)

    if not args.query:
        parser.error("請使用 --query 提供問題，或使用 --interactive。")
    facts = _parse_facts(args.fact)
    if args.event_date:
        facts["event_date"] = args.event_date
    state = service.handle(
        query=args.query,
        user_role=args.role,
        facts=facts,
        case_id=args.case_id,
        trace_id=args.trace_id,
        allow_incomplete=args.allow_incomplete,
    )
    _print_state(state)
    return 0


def _interactive(service: AgentService, args: argparse.Namespace) -> int:
    query = args.query or input("請描述澳門勞動法問題：").strip()
    role = args.role
    if role == UserRole.UNKNOWN.value:
        role = input("你的角色（employee/employer/representative/other）：").strip()
    facts = _parse_facts(args.fact)
    if args.event_date:
        facts["event_date"] = args.event_date

    state = service.handle(
        query=query,
        user_role=role,
        facts=facts,
        case_id=args.case_id,
        trace_id=args.trace_id,
        allow_incomplete=args.allow_incomplete,
    )
    while (
        state.answer
        and state.answer.status.value == "need_more_facts"
        and len(state.missing_facts) > 0
    ):
        requirement = state.missing_facts[0]
        answer = input(f"{requirement.question} ").strip()
        if not answer:
            break
        facts[requirement.code] = answer
        state = service.handle(
            query=query,
            user_role=role,
            facts=facts,
            case_id=args.case_id,
            trace_id=args.trace_id,
            allow_incomplete=args.allow_incomplete,
        )
    _print_state(state)
    return 0


def _parse_facts(items: list[str]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"事實格式錯誤：{item}，應為 KEY=VALUE。")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise SystemExit(f"事實格式錯誤：{item}，KEY 與 VALUE 不可為空。")
        facts[key] = value
    return facts


def _print_state(state) -> None:
    if state.answer is None:
        print(json.dumps({"status": "not_assembled"}, ensure_ascii=False, indent=2))
        return
    print(
        json.dumps(
            to_plain_data(state.answer),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
