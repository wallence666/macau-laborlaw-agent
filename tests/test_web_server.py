from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from laborlaw_agent.web.server import DEFAULT_REGISTRY, create_server


def _start_server(tmp_path: Path):
    server = create_server(
        "127.0.0.1",
        0,
        registry_path=DEFAULT_REGISTRY,
        audit_log_path=tmp_path / "audit.jsonl",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def test_web_meta_endpoint(tmp_path) -> None:
    server, thread, base_url = _start_server(tmp_path)
    try:
        with urllib.request.urlopen(f"{base_url}/api/meta", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["approved_source_count"] == 4
        assert payload["provision_count"] == 106
        assert payload["test_only"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_web_index_is_served_with_security_headers(tmp_path) -> None:
    server, thread, base_url = _start_server(tmp_path)
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=10) as response:
            html = response.read().decode("utf-8")
            csp = response.headers["Content-Security-Policy"]
        assert "澳門勞動法 Agent" in html
        assert "/app.js" in html
        assert "default-src 'self'" in csp
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_web_ask_endpoint_answers_and_sets_security_headers(tmp_path) -> None:
    server, thread, base_url = _start_server(tmp_path)
    body = json.dumps(
        {
            "query": "工資最遲應在何時支付？",
            "role": "employee",
            "case_id": "web-test-case",
            "facts": {
                "work_location": "澳門",
                "event_date": "2026-09-15",
                "wage_period": "2026-08",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/ask",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            csp = response.headers["Content-Security-Policy"]
        assert payload["answer"]["status"] == "answered"
        assert payload["answer"]["applicable_law"][0]["article"] == "第六十二條"
        assert "default-src 'self'" in csp
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_web_close_case_endpoint(tmp_path) -> None:
    server, thread, base_url = _start_server(tmp_path)
    body = json.dumps({"case_id": "close-me"}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/case/close",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload == {"ok": True, "case_id": "close-me"}
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_web_serves_source_pdf_with_range_support(tmp_path) -> None:
    server, thread, base_url = _start_server(tmp_path)
    request = urllib.request.Request(
        (
            f"{base_url}/api/documents/"
            "mo-law-7-2008-consolidated-2020"
        ),
        headers={"Range": "bytes=0-99"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read()
            content_type = response.headers["Content-Type"]
            content_range = response.headers["Content-Range"]
        assert response.status == 206
        assert content_type == "application/pdf"
        assert len(data) == 100
        assert content_range.startswith("bytes 0-99/")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
