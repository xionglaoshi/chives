from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from hub_mcp.client import HubClient
from hub_mcp.service import HubService

SIGNALS = [
    {
        "id": 1,
        "ts": "2026-11-04T10:00:00+08:00",
        "kind": "risk",
        "kind_label": "风险",
        "object": {"type": "stock", "code": "600000.SH", "name": "浦发银行"},
        "title": "浦发银行 放量下跌",
        "direction": "bear",
        "direction_label": "偏空",
        "conclusion": "放量下跌，先观望。",
        "brief": "成交额放大。",
        "status": "new",
        "decide": True,
        "secret_extra": "should never be returned",
    }
]

PLANS: dict[int, dict[str, Any]] = {
    7: {"id": 7, "code": "600000.SH", "status": "proposed", "proposed_by": "agent", "kind": "entry"},
    8: {"id": 8, "code": "600000.SH", "status": "active", "proposed_by": "user", "kind": "entry"},
    9: {"id": 9, "code": "600000.SH", "status": "proposed", "proposed_by": "user", "kind": "entry"},
    10: {"id": 10, "code": "000001.SZ", "status": "proposed", "proposed_by": "agent", "kind": "giveup"},
}


class FakeHub:
    def __init__(self) -> None:
        self.log: list[tuple[str, str, Any]] = []
        self.per_plan_get = True
        self.extra_signals: list[dict[str, Any]] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # noqa: D401
                return

            def _send(self, payload: Any, code: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _error(self, code: int, name: str, message: str) -> None:
                self._send({"ok": False, "error": {"code": name, "message": message}}, code)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                hub.log.append(("GET", self.path, None))
                if path == "/large":
                    body = b"x" * (600 * 1024)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/slow":
                    time.sleep(0.4)
                    self._send({"ok": True})
                    return
                if path == "/badjson":
                    body = b"not json"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/array":
                    self._send([1, 2, 3])
                    return
                if path == "/business_error":
                    self._error(200, "boom", "upstream failed")
                    return
                if path.startswith("/signals/"):
                    signal_id = int(path.rsplit("/", 1)[1])
                    if signal_id == 404:
                        self._error(404, "signal_not_found", "信号不存在")
                        return
                    if signal_id == 2:
                        self._send(
                            {
                                "ok": True,
                                "signal": SIGNALS[0] | {"id": 2},
                                "analysis": {
                                    "markdown": "x" * 9000,
                                    "sections": {
                                        "conclusion": "嵌套形状",
                                        "direction": "bull",
                                        "points": ["p1", "p2"],
                                        "detail": "d" * 9000,
                                    },
                                },
                            }
                        )
                        return
                    self._send(
                        {
                            "ok": True,
                            **SIGNALS[0],
                            "analysis": {
                                "markdown": "x" * 9000,
                                "sections": {
                                    "conclusion": "放量下跌，先观望。",
                                    "direction": "bear",
                                    "points": ["14:05 放量", "距跌停 5%"],
                                    "detail": "d" * 9000,
                                },
                            },
                        }
                    )
                    return
                if path == "/signals":
                    wanted = (query.get("status") or ["active"])[-1]
                    if wanted == "all":
                        rows = list(SIGNALS + hub.extra_signals)
                    elif wanted == "active":
                        rows = [row for row in SIGNALS + hub.extra_signals if row["status"] in {"new", "seen"}]
                    else:
                        rows = [row for row in SIGNALS + hub.extra_signals if row["status"] == wanted]
                    self._send({"ok": True, "as_of": "2026-11-04T10:00:01+08:00", "signals": rows, "counts": {"decide": 1}})
                    return
                if path.startswith("/plans/"):
                    plan_id = int(path.rsplit("/", 1)[1])
                    if not hub.per_plan_get:
                        self._error(404, "not_found", "未知路径")
                        return
                    if plan_id in PLANS:
                        self._send({"ok": True, "plan": PLANS[plan_id]})
                    else:
                        self._error(404, "plan_not_found", "计划不存在")
                    return
                if path == "/plans":
                    status = (query.get("status") or ["all"])[-1]
                    rows = [p for p in PLANS.values() if status == "all" or p["status"] == status]
                    self._send({"ok": True, "as_of": "2026-11-04T10:00:01+08:00", "plans": rows, "counts": {}})
                    return
                self._error(404, "not_found", "未知路径")

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                body = json.loads(raw or b"{}")
                parsed = urlsplit(self.path)
                hub.log.append(("POST", self.path, body))
                if parsed.path == "/plans":
                    self._send(
                        {
                            "ok": True,
                            "plan": {
                                "id": 100,
                                "status": "proposed",
                                "proposed_by": body.get("proposed_by"),
                                "code": body.get("code"),
                            },
                        }
                    )
                    return
                if parsed.path.startswith("/plans/") and parsed.path.endswith("/action"):
                    plan_id = int(parsed.path.split("/")[2])
                    plan = dict(PLANS.get(plan_id, {"id": plan_id, "status": "cancelled"}))
                    plan["status"] = "cancelled"
                    self._send({"ok": True, "plan": plan})
                    return
                self._error(404, "not_found", "未知路径")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> "FakeHub":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def posts(self) -> list[tuple[str, str, Any]]:
        return [entry for entry in self.log if entry[0] == "POST"]


@pytest.fixture
def fake_hub() -> FakeHub:
    hub = FakeHub().start()
    try:
        yield hub
    finally:
        hub.stop()


@pytest.fixture
def client(fake_hub: FakeHub) -> HubClient:
    return HubClient(fake_hub.url, timeout=2.0)


@pytest.fixture
def service(client: HubClient) -> HubService:
    return HubService(client)


@pytest.fixture
def fake_hub_v2():
    from tests.support_v2 import FakeHubV2

    hub = FakeHubV2().start()
    try:
        yield hub
    finally:
        hub.stop()


@pytest.fixture
def client_v2(fake_hub_v2):
    return HubClient(fake_hub_v2.url, timeout=2.0)


@pytest.fixture
def service_v2(client_v2: HubClient) -> HubService:
    return HubService(client_v2)
