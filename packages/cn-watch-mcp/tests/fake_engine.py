"""Deterministic local fake of the cn-watch HTTP API for offline tests."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ALERTS = [
    {
        "id": i,
        "ts": f"2026-11-03T09:3{i}:00+08:00",
        "code": "002553.SZ",
        "name": "南方精工",
        "rule_id": "pct_up_3",
        "direction": "up",
        "price": 15.47,
    }
    for i in range(1, 6)
]

STATE: dict[str, Any] = {
    "updated_at": "2026-11-03T10:00:00+08:00",
    "health": "ok",
    "status": "ok",
    "mode": "base",
    "next_interval": 3.0,
    "stale": False,
    "lag_seconds": 3.0,
    "max_lag_seconds": 20.0,
    "trading_day": True,
    "session": "open",
    "last_rule_eval_ts": "2026-11-03T09:59:57+08:00",
    "consecutive_failures": 0,
    "last_poll_ts": "2026-11-03T10:00:00+08:00",
    "last_exchange_time": "2026-11-03T09:59:57+08:00",
    "quotes": {
        "002553.SZ": {
            "code": "002553.SZ",
            "name": "南方精工",
            "price": 15.47,
            "prev_close": 15.0,
            "change_pct": 3.13,
            "vwap": 15.4,
            "vwap_dev_pct": 0.45,
        }
    },
    "rules": [],
}

RULES = [
    {
        "id": "pct_up_3",
        "type": "pct_change",
        "direction": "up",
        "threshold_pct": 3.0,
        "symbols": ["002553.SZ"],
        "source": "config",
        "disabled": False,
        "enabled": True,
    },
    {
        "id": "vwap_dev_2",
        "type": "vwap_deviation",
        "threshold_pct": 2.0,
        "symbols": None,
        "source": "config",
        "disabled": False,
        "enabled": True,
    },
]

DEFAULT_WATCHLIST = [{"code": "002553.SZ", "name": "南方精工", "source": "config"}]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        engine: FakeEngine = self.server.owner  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        path = self.path.partition("?")[0]
        engine.requests.append(f"POST {path} {json.dumps(body, ensure_ascii=False)}")
        engine.actors.append(self.headers.get("X-Actor"))
        if engine.post_error is not None:
            status, payload = engine.post_error
            self._send(status, payload)
            return
        if path == "/rules/upsert":
            rule = dict(body)
            rule_id = rule.get("id")
            before = next((row for row in engine.rules if row.get("id") == rule_id), None)
            source = "override" if before and before.get("source") == "config" else "runtime"
            after = {
                **rule,
                "symbols": rule.get("symbols"),
                "source": source,
                "disabled": False,
                "enabled": True,
            }
            engine.rules = [row for row in engine.rules if row.get("id") != rule_id]
            engine.rules.append(after)
            engine.history.append(
                {
                    "ts": "2026-11-03T10:00:00+08:00",
                    "action": "upsert",
                    "rule_id": rule_id,
                    "before": before,
                    "after": after,
                    "actor": self.headers.get("X-Actor") or "unknown",
                }
            )
            self._send(
                200,
                {
                    "ok": True,
                    "status": "created" if before is None else (
                        "override" if before.get("source") == "config" else "replaced"
                    ),
                    "rule_id": rule_id,
                    "source": source,
                    "before": before,
                    "after": after,
                    "count": len(engine.rules),
                    "limit": 30,
                },
            )
            return
        if path in ("/rules/remove", "/rules/revert"):
            rule_id = body.get("id")
            before = next((row for row in engine.rules if row.get("id") == rule_id), None)
            if before is None:
                self._send(
                    404,
                    {
                        "ok": False,
                        "code": "rule_not_found",
                        "message": f"规则不存在: {rule_id}",
                        "error": f"规则不存在: {rule_id}",
                    },
                )
                return
            if path == "/rules/remove":
                after = {**before, "source": "override", "disabled": True, "enabled": False}
                engine.rules = [
                    after if row.get("id") == rule_id else row for row in engine.rules
                ]
                status = "disabled"
            else:
                engine.rules = [row for row in engine.rules if row.get("id") != rule_id]
                after = None
                status = "reverted"
            engine.history.append(
                {
                    "ts": "2026-11-03T10:00:00+08:00",
                    "action": "remove" if path == "/rules/remove" else "revert",
                    "rule_id": rule_id,
                    "before": before,
                    "after": after,
                    "actor": self.headers.get("X-Actor") or "unknown",
                }
            )
            self._send(
                200,
                {
                    "ok": True,
                    "status": status,
                    "rule_id": rule_id,
                    "source": (after or {}).get("source"),
                    "before": before,
                    "after": after,
                    "count": len(engine.rules),
                    "limit": 30,
                },
            )
            return
        code = body.get("code")
        if path == "/watchlist/add":
            if any(row["code"] == code for row in engine.watchlist):
                self._send(
                    200,
                    {
                        "ok": True,
                        "status": "already_present",
                        "code": code,
                        "name": "南方精工",
                        "source": "runtime",
                        "count": len(engine.watchlist),
                        "limit": 10,
                    },
                )
                return
            engine.watchlist.append({"code": code, "name": "太平洋", "source": "runtime"})
            self._send(
                200,
                {
                    "ok": True,
                    "status": "added",
                    "code": code,
                    "name": "太平洋",
                    "source": "runtime",
                    "count": len(engine.watchlist),
                    "limit": 10,
                },
            )
            return
        if path == "/watchlist/remove":
            row = next((item for item in engine.watchlist if item["code"] == code), None)
            if row is None:
                self._send(
                    200,
                    {
                        "ok": True,
                        "status": "not_present",
                        "code": code,
                        "name": None,
                        "source": None,
                        "count": len(engine.watchlist),
                        "limit": 10,
                    },
                )
                return
            if row["source"] == "config":
                self._send(
                    409,
                    {
                        "ok": False,
                        "code": "protected_symbol",
                        "message": "该标的来自配置文件，不能通过接口删除；请修改 config/watch.yaml",
                        "error": "protected",
                    },
                )
                return
            engine.watchlist.remove(row)
            self._send(
                200,
                {
                    "ok": True,
                    "status": "removed",
                    "code": code,
                    "name": row["name"],
                    "source": "runtime",
                    "count": len(engine.watchlist),
                    "limit": 10,
                },
            )
            return
        self._send(404, {"error": "not_found"})

    def do_GET(self) -> None:  # noqa: N802
        engine: FakeEngine = self.server.owner  # type: ignore[attr-defined]
        engine.requests.append(f"GET {self.path}")
        if engine.mode == "hang":
            time.sleep(5)
            return
        if engine.mode == "error500":
            self._send(500, {"error": "boom"})
            return
        path, _, query = self.path.partition("?")
        if path == "/health":
            keys = (
                "status",
                "health",
                "mode",
                "next_interval",
                "consecutive_failures",
                "last_poll_ts",
                "last_exchange_time",
                "stale",
                "lag_seconds",
                "max_lag_seconds",
                "trading_day",
                "session",
                "last_rule_eval_ts",
            )
            self._send(200, {key: engine.state[key] for key in keys if key in engine.state})
            return
        if path == "/state":
            self._send(200, engine.state)
            return
        if path == "/rules":
            self._send(
                200,
                {
                    "rules": engine.rules,
                    "count": len(engine.rules),
                    "enabled_count": sum(1 for row in engine.rules if not row.get("disabled")),
                },
            )
            return
        if path == "/rules/history":
            params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
            limit = int(params.get("limit", 50))
            rows = list(reversed(engine.history))[:limit]
            self._send(200, {"history": rows, "count": len(rows)})
            return
        if path == "/watchlist":
            self._send(
                200,
                {"watchlist": engine.watchlist, "count": len(engine.watchlist), "limit": 10},
            )
            return
        if path == "/alerts":
            params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
            after = int(params.get("after_id", 0))
            limit = int(params.get("limit", 100))
            rows = [row for row in ALERTS if row["id"] > after][:limit]
            self._send(200, {"alerts": rows})
            return
        self._send(404, {"error": "not_found"})


class FakeEngine:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.requests: list[str] = []
        self.watchlist: list[dict[str, Any]] = [dict(row) for row in DEFAULT_WATCHLIST]
        self.rules: list[dict[str, Any]] = [dict(row) for row in RULES]
        self.history: list[dict[str, Any]] = []
        self.actors: list[str | None] = []
        self.post_error: tuple[int, dict[str, Any]] | None = None
        state = dict(STATE)
        if mode == "stale":
            state["stale"] = True
            state["health"] = "stale"
        elif mode == "closed":
            state["trading_day"] = False
            state["session"] = "non_trading_day"
            state["last_rule_eval_ts"] = None
        elif mode == "after_hours":
            state["session"] = "after_hours"
        elif mode == "pre_open":
            state["session"] = "pre_open"
        elif mode == "legacy":
            state.pop("session")
            state.pop("last_rule_eval_ts")
        elif mode == "degraded":
            state["health"] = "degraded"
            state["consecutive_failures"] = 2
        self.state = state
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.owner = self  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
