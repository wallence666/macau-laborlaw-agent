from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from laborlaw_agent.llm import LLMConfig, OpenAICompatibleClient


class FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    received_payload: dict | None = None
    call_count = 0

    def do_POST(self) -> None:  # noqa: N802
        self.__class__.call_count += 1
        length = int(self.headers["Content-Length"])
        self.__class__.received_payload = json.loads(
            self.rfile.read(length).decode("utf-8")
        )
        content = (
            ""
            if self.__class__.call_count == 1
            else '{"ok": true, "message": "ok"}'
        )
        body = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": (
                            "length"
                            if self.__class__.call_count == 1
                            else "stop"
                        ),
                        "message": {
                            "content": content,
                            "reasoning_content": (
                                "thinking"
                                if self.__class__.call_count == 1
                                else None
                            ),
                        }
                    }
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def test_openai_compatible_client_uses_chat_completions_endpoint() -> None:
    FakeModelHandler.call_count = 0
    FakeModelHandler.received_payload = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        client = OpenAICompatibleClient(
            LLMConfig(
                enabled=True,
                base_url=f"http://{host}:{port}/v1",
                model="fake-model",
                provider="deepseek",
                api_key="",
            )
        )
        assert client.test_connection() == "fake-model"
        assert FakeModelHandler.received_payload is not None
        assert FakeModelHandler.received_payload["model"] == "fake-model"
        assert FakeModelHandler.received_payload["response_format"] == {
            "type": "json_object"
        }
        assert FakeModelHandler.received_payload["thinking"] == {
            "type": "disabled"
        }
        assert FakeModelHandler.call_count == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
