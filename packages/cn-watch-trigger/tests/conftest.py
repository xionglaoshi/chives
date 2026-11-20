"""Local fake engine for offline tests."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import pytest


@dataclass
class FakeEngine:
    url: str
    server: ThreadingHTTPServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def engine_factory() -> Callable[..., FakeEngine]:
    created: list[FakeEngine] = []

    def make(alerts: list[dict[str, Any]] | None = None, *, status: int = 200) -> FakeEngine:
        rows = list(alerts or [])

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, code: int, body: Any) -> None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("content-type", "application/json; charset=utf-8")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                if parts.path != "/alerts":
                    self._send(404, {"error": "not_found"})
                    return
                if status != 200:
                    self._send(status, {"error": "boom"})
                    return
                query = parse_qs(parts.query)
                after = int(query.get("after_id", ["0"])[0])
                limit = int(query.get("limit", ["100"])[0])
                page = [row for row in rows if row["id"] > after][:limit]
                self._send(200, {"alerts": page})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fake = FakeEngine(
            url=f"http://127.0.0.1:{server.server_address[1]}",
            server=server,
            thread=thread,
        )
        created.append(fake)
        return fake

    yield make
    for fake in created:
        fake.stop()
