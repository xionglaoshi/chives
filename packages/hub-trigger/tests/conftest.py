"""Local fake hub for offline tests."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@dataclass
class FakeHub:
    url: str
    server: ThreadingHTTPServer
    thread: threading.Thread
    triggers: list[dict[str, Any]] = field(default_factory=list)
    contexts: dict[int, dict[str, Any]] = field(default_factory=dict)
    judgements: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)
    reject_ids: set[int] = field(default_factory=set)
    error_ids: set[int] = field(default_factory=set)
    fail_trigger_page: bool = False

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def add(self, trigger: dict[str, Any], context: dict[str, Any] | None = None) -> None:
        self.triggers.append(trigger)
        if context is not None:
            self.contexts[trigger["id"]] = context


@pytest.fixture
def hub_factory() -> Callable[..., FakeHub]:
    created: list[FakeHub] = []

    def make(triggers: list[dict[str, Any]] | None = None) -> FakeHub:
        holder: dict[str, FakeHub] = {}

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
                hub = holder["hub"]
                parts = urlsplit(self.path)
                hub.requests.append(("GET", self.path))
                if parts.path == "/health":
                    self._send(200, {"ok": True})
                    return
                if parts.path == "/triggers":
                    if hub.fail_trigger_page:
                        self._send(500, {"ok": False})
                        return
                    query = parse_qs(parts.query)
                    since = int(query.get("since_id", ["0"])[0])
                    limit = int(query.get("limit", ["50"])[0])
                    rows = sorted(
                        (row for row in hub.triggers if row["id"] > since),
                        key=lambda row: row["id"],
                    )[:limit]
                    next_id = max((row["id"] for row in hub.triggers), default=0)
                    self._send(200, {"ok": True, "triggers": rows, "next_id": next_id})
                    return
                if parts.path.startswith("/triggers/") and parts.path.endswith("/context"):
                    try:
                        trigger_id = int(parts.path.split("/")[2])
                    except (IndexError, ValueError):
                        self._send(404, {"ok": False})
                        return
                    if trigger_id in hub.error_ids:
                        self._send(503, {"ok": False})
                        return
                    if trigger_id not in hub.contexts:
                        self._send(200, {"ok": False, "error": {"code": "no_context"}})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "trigger": next(
                                (row for row in hub.triggers if row["id"] == trigger_id), None
                            ),
                            "context": hub.contexts[trigger_id],
                        },
                    )
                    return
                self._send(404, {"ok": False, "error": {"code": "not_found"}})

            def do_POST(self) -> None:  # noqa: N802
                hub = holder["hub"]
                parts = urlsplit(self.path)
                hub.requests.append(("POST", self.path))
                length = int(self.headers.get("content-length", "0"))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, {"ok": False})
                    return
                if not (
                    parts.path.startswith("/triggers/") and parts.path.endswith("/judgement")
                ):
                    self._send(404, {"ok": False, "error": {"code": "not_found"}})
                    return
                try:
                    trigger_id = int(parts.path.split("/")[2])
                except (IndexError, ValueError):
                    self._send(404, {"ok": False})
                    return
                if trigger_id in hub.reject_ids:
                    hub.judgements.append({"id": trigger_id, "body": body, "accepted": False})
                    self._send(200, {"ok": False, "error": {"code": "bad_value"}})
                    return
                if any(item["id"] == trigger_id for item in hub.judgements):
                    hub.judgements.append({"id": trigger_id, "body": body, "accepted": False})
                    self._send(200, {"ok": False, "error": {"code": "already_judged"}})
                    return
                hub.judgements.append({"id": trigger_id, "body": body, "accepted": True})
                self._send(200, {"ok": True, "trigger_id": trigger_id})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fake = FakeHub(
            url=f"http://127.0.0.1:{server.server_address[1]}",
            server=server,
            thread=thread,
            triggers=list(triggers or []),
        )
        holder["hub"] = fake
        created.append(fake)
        return fake

    yield make
    for fake in created:
        fake.stop()
