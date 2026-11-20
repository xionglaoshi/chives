"""Tiny in-process cn-watch stand-in for HTTP-level hub tests (no public net)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

CN_TZ_OFFSET = "+08:00"


class FakeCnWatch:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.actors: list[Optional[str]] = []
        self.upserts: list[dict[str, Any]] = []
        self.removes: list[dict[str, Any]] = []
        self.reject: Optional[tuple[str, str]] = None
        self.down = False
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle -------------------------------------------------------
    def start(self) -> "FakeCnWatch":
        handler = self._handler()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def base(self) -> str:
        assert self._httpd is not None
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    # -- state helpers ---------------------------------------------------
    def plan_state(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": plan["id"],
            "code": plan["code"],
            "label": plan.get("label") or "",
            "state": "observe",
            "since": f"2026-11-04T10:00:00{CN_TZ_OFFSET}",
            "last_price": None,
            "held": bool(plan.get("held")),
            "conds": {
                key: [None] * len(plan.get(key) or [])
                for key in ("market", "sector", "stock", "giveup")
            },
            "history": [],
            "expires_at": plan.get("expires_at"),
            "active": True,
        }

    def set_state(
        self,
        plan_id: str,
        state: str,
        *,
        price: Optional[float] = None,
        conds: Optional[dict[str, list[Optional[bool]]]] = None,
        ts: str = f"2026-11-04T10:00:03{CN_TZ_OFFSET}",
        reason: str = "测试驱动",
    ) -> dict[str, Any]:
        plan = self.states[plan_id]
        plan["history"].append(
            {"ts": ts, "from": plan["state"], "to": state, "reason": reason}
        )
        plan["state"] = state
        plan["since"] = ts
        if price is not None:
            plan["last_price"] = price
        if conds is not None:
            plan["conds"] = conds
        return plan

    # -- HTTP ------------------------------------------------------------
    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def _send(self, status: int, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read(self) -> Any:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def _route(self, method: str) -> None:
                if fake.down:
                    self._send(503, {"ok": False, "code": "down", "message": "down"})
                    return
                path = self.path.split("?", 1)[0]
                if method == "GET" and path == "/plans":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "as_of": f"2026-11-04T10:00:00{CN_TZ_OFFSET}",
                            "market_context": {"ok": True, "age_s": 1.0, "regime": "strong"},
                            "plans": list(fake.states.values()),
                        },
                    )
                    return
                if method == "GET" and path in {"/state", "/alerts"}:
                    self._send(200, {"ok": True, "quotes": {}, "alerts": []})
                    return
                if method == "POST" and path == "/plans/upsert":
                    payload = self._read()
                    fake.actors.append(self.headers.get("X-Actor"))
                    fake.upserts.append(payload)
                    if fake.reject:
                        code, message = fake.reject
                        self._send(
                            400,
                            {
                                "ok": False,
                                "code": code,
                                "message": message,
                                "field": "code",
                            },
                        )
                        return
                    state = fake.states.get(payload["id"])
                    if state is None:
                        state = fake.plan_state(payload)
                    else:
                        state["held"] = bool(payload.get("held"))
                        state["label"] = payload.get("label") or ""
                        state["expires_at"] = payload.get("expires_at")
                    fake.states[payload["id"]] = state
                    self._send(200, {"ok": True, "status": "upserted", "plan": state})
                    return
                if method == "POST" and path == "/plans/remove":
                    payload = self._read()
                    fake.actors.append(self.headers.get("X-Actor"))
                    fake.removes.append(payload)
                    if payload.get("id") not in fake.states:
                        self._send(
                            404,
                            {"ok": False, "code": "not_found", "message": "not found"},
                        )
                        return
                    del fake.states[payload["id"]]
                    self._send(200, {"ok": True, "status": "removed", "id": payload["id"]})
                    return
                self._send(404, {"ok": False, "code": "not_found", "message": "not found"})

            def do_GET(self) -> None:  # noqa: N802
                self._route("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._route("POST")

        return Handler
