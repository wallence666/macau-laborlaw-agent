from __future__ import annotations

import argparse
import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..llm import LLMConfig, LLMError, OpenAICompatibleClient
from ..models import ReviewStatus, UserRole, to_plain_data
from ..repository import LegalSourceRepository, RegistryError
from ..workflow import AgentService


ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_REGISTRY = ROOT / "data" / "source-registry" / "registry.json"
MAX_REQUEST_BYTES = 1_000_000


class LaborLawHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: AgentService,
        repository: LegalSourceRepository,
    ) -> None:
        super().__init__(server_address, LaborLawRequestHandler)
        self.service = service
        self.repository = repository
        self.request_lock = threading.Lock()


class LaborLawRequestHandler(BaseHTTPRequestHandler):
    server: LaborLawHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/api/meta":
            self._send_json(HTTPStatus.OK, self._meta_payload())
            return
        if path.startswith("/api/documents/"):
            self._serve_source_pdf(unquote(path.removeprefix("/api/documents/")))
            return
        self._serve_static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/documents/"):
            self._serve_source_pdf(
                unquote(path.removeprefix("/api/documents/")),
                head_only=True,
            )
            return
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "不支援此方法。"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/api/ask", "/api/llm/test", "/api/case/close"}:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "找不到 API 路徑。"},
            )
            return
        try:
            payload = self._read_json()
            if path == "/api/case/close":
                response = self._handle_close_case(payload)
            elif path == "/api/llm/test":
                response = self._handle_llm_test(payload)
            else:
                response = self._handle_ask(payload)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except LLMError as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Agent 執行失敗，請查看本機終端紀錄。"},
            )
            raise
        self._send_json(HTTPStatus.OK, response)

    def _handle_ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("請提供問題。")
        query = query.strip()
        if len(query) > 4_000:
            raise ValueError("問題不可超過 4000 個字元。")

        role_value = payload.get("role", UserRole.UNKNOWN.value)
        try:
            role = UserRole(str(role_value))
        except ValueError as exc:
            raise ValueError("使用者角色格式錯誤。") from exc

        facts_payload = payload.get("facts", {})
        if not isinstance(facts_payload, dict):
            raise ValueError("案件事實必須是 JSON 物件。")
        if len(facts_payload) > 30:
            raise ValueError("案件事實欄位過多。")
        facts: dict[str, str] = {}
        for key, value in facts_payload.items():
            clean_key = str(key).strip()
            clean_value = str(value).strip()
            if not clean_key or not clean_value:
                continue
            if len(clean_key) > 80 or len(clean_value) > 2_000:
                raise ValueError("案件事實欄位過長。")
            facts[clean_key] = clean_value

        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("缺少案件 ID。")
        if len(case_id) > 120:
            raise ValueError("案件 ID 過長。")

        llm_config = self._parse_llm_config(payload.get("llm"))
        allow_incomplete = bool(payload.get("allow_incomplete", False))
        with self.server.request_lock:
            state = self.server.service.handle(
                query=query,
                user_role=role,
                facts=facts,
                case_id=case_id,
                llm_config=llm_config,
                allow_incomplete=allow_incomplete,
            )
        if state.answer is None:
            raise RuntimeError("Agent 未組裝回答。")
        return {
            "answer": to_plain_data(state.answer),
            "trace_id": state.trace_id,
            "source_ids": state.source_ids,
            "risk_flags": to_plain_data(state.risk_flags),
            "llm": self._llm_response_meta(state.llm_result),
        }

    def _handle_llm_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._parse_llm_config(payload.get("llm"))
        if config is None:
            raise ValueError("請先提供完整的模型設定。")
        client = OpenAICompatibleClient(config)
        model = client.test_connection()
        return {"ok": True, "model": model}

    def _handle_close_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = str(payload.get("case_id") or "").strip()
        if not case_id or len(case_id) > 120:
            raise ValueError("案件 ID 格式錯誤。")
        with self.server.request_lock:
            self.server.service.close_case(case_id)
        return {"ok": True, "case_id": case_id}

    @staticmethod
    def _parse_llm_config(raw_config: Any) -> LLMConfig | None:
        if raw_config is None:
            return None
        if not isinstance(raw_config, dict):
            raise ValueError("模型設定格式錯誤。")
        if not bool(raw_config.get("enabled")):
            return None
        base_url = str(raw_config.get("base_url") or "").strip()
        model = str(raw_config.get("model") or "").strip()
        provider = str(raw_config.get("provider") or "auto").strip()
        api_key = str(raw_config.get("api_key") or "").strip()
        if not base_url or len(base_url) > 1_000:
            raise ValueError("模型 Base URL 格式錯誤。")
        if not model or len(model) > 200:
            raise ValueError("模型名稱格式錯誤。")
        if len(api_key) > 10_000:
            raise ValueError("API Key 過長。")
        try:
            temperature = float(raw_config.get("temperature", 0.1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Temperature 格式錯誤。") from exc
        temperature = min(max(temperature, 0.0), 1.0)
        config = LLMConfig(
            enabled=True,
            base_url=base_url,
            model=model,
            provider=provider,
            api_key=api_key,
            temperature=temperature,
            json_mode=bool(raw_config.get("json_mode", True)),
            timeout_seconds=90,
        )
        if not config.is_usable():
            raise ValueError(
                "模型設定不完整；遠端 API 必須提供 API Key。"
            )
        return config

    @staticmethod
    def _llm_response_meta(result: dict[str, Any] | None) -> dict[str, Any]:
        if not result:
            return {
                "enabled": False,
                "plan_used": False,
                "analysis_used": False,
            }
        return {
            "enabled": bool(result.get("enabled")),
            "model": result.get("model"),
            "plan_used": bool(result.get("plan_used")),
            "analysis_used": bool(result.get("analysis_used")),
            "plan_error": result.get("plan_error"),
            "analysis_error": result.get("analysis_error"),
        }

    def _meta_payload(self) -> dict[str, Any]:
        approved_sources = [
            source
            for source in self.server.repository.sources
            if source.review_status is ReviewStatus.APPROVED
        ]
        provision_count = sum(
            len(source.provisions) for source in approved_sources
        )
        test_only = bool(approved_sources) and all(
            source.review_scope == "test_only"
            for source in approved_sources
        )
        return {
            "app_name": "澳門勞動法 Agent",
            "jurisdiction": "MO",
            "approved_source_count": len(approved_sources),
            "provision_count": provision_count,
            "test_only": test_only,
            "roles": [role.value for role in UserRole],
        }

    def _serve_static(self, path: str) -> None:
        relative_path = unquote(path).lstrip("/") or "index.html"
        candidate = (STATIC_DIR / relative_path).resolve()
        static_root = STATIC_DIR.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到檔案。"})
            return
        if not candidate.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到檔案。"})
            return
        content_type, _ = mimetypes.guess_type(candidate.name)
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _serve_source_pdf(
        self, source_id: str, *, head_only: bool = False
    ) -> None:
        source = next(
            (
                item
                for item in self.server.repository.sources
                if item.source_id == source_id
            ),
            None,
        )
        if source is None or not source.pdf_path:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到 PDF 來源。"})
            return
        candidate = (ROOT / source.pdf_path).resolve()
        if ROOT.resolve() not in candidate.parents or not candidate.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到 PDF 檔案。"})
            return

        file_size = candidate.stat().st_size
        start = 0
        end = file_size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            parsed_range = _parse_range(range_header, file_size)
            if parsed_range is None:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            start, end = parsed_range
            status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header(
            "Content-Disposition",
            f'inline; filename="{candidate.name}"',
        )
        self.send_header("Cache-Control", "private, max-age=3600")
        if status is HTTPStatus.PARTIAL_CONTENT:
            self.send_header(
                "Content-Range", f"bytes {start}-{end}/{file_size}"
            )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if head_only:
            return
        with candidate.open("rb") as stream:
            stream.seek(start)
            self.wfile.write(stream.read(length))

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise ValueError("要求內容必須是 application/json。")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("缺少 Content-Length。")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length 格式錯誤。") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("要求內容大小不合法。")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 格式錯誤。") from exc
        if not isinstance(payload, dict):
            raise ValueError("要求內容必須是 JSON 物件。")
        return payload

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; "
                "font-src 'self'; object-src 'none'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} {format % args}")


def create_server(
    host: str,
    port: int,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    audit_log_path: str | Path | None = ROOT / "artifacts" / "audit" / "audit.jsonl",
) -> LaborLawHTTPServer:
    repository = LegalSourceRepository.from_path(registry_path)
    service = AgentService(
        repository=repository,
        audit_log_path=audit_log_path,
    )
    return LaborLawHTTPServer((host, port), service, repository)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    audit_log_path: str | Path | None = ROOT / "artifacts" / "audit" / "audit.jsonl",
) -> None:
    server = create_server(
        host,
        port,
        registry_path=registry_path,
        audit_log_path=audit_log_path,
    )
    actual_host, actual_port = server.server_address[:2]
    print(f"澳門勞動法 Agent UI：http://{actual_host}:{actual_port}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服務。")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="啟動澳門勞動法 Agent 本機 Web UI。"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=ROOT / "artifacts" / "audit" / "audit.jsonl",
    )
    args = parser.parse_args(argv)
    try:
        run_server(
            host=args.host,
            port=args.port,
            registry_path=args.registry,
            audit_log_path=args.audit_log,
        )
    except RegistryError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(f"無法啟動服務：{exc}")
    return 0


def _parse_range(value: str, file_size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or "," in value:
        return None
    raw_range = value.removeprefix("bytes=").strip()
    if "-" not in raw_range:
        return None
    raw_start, raw_end = raw_range.split("-", 1)
    try:
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else file_size - 1
        else:
            suffix_length = int(raw_end)
            if suffix_length <= 0:
                return None
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= file_size:
        return None
    return start, min(end, file_size - 1)


if __name__ == "__main__":
    raise SystemExit(main())
