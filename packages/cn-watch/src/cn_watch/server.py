"""Loopback HTTP API: read-only state plus restricted watchlist/rule writes."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .engine import Engine, RuleError, WatchlistError
from .plans import PlanError
from .rule_store import sanitize_actor

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
MAX_BODY_BYTES = 8192
WATCHLIST_WRITE_PATHS = {"/watchlist/add", "/watchlist/remove"}
RULE_WRITE_PATHS = {"/rules/upsert", "/rules/remove", "/rules/revert"}
PLAN_WRITE_PATHS = {"/plans/upsert", "/plans/remove"}


class WatchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], engine: Engine) -> None:
        self.engine = engine
        super().__init__(address, WatchRequestHandler)


class WatchRequestHandler(BaseHTTPRequestHandler):
    server_version = "cn-watch/0.1"

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"error": message})

    def _watchlist_error(self, exc: WatchlistError) -> None:
        status = {"watchlist_full": 409, "protected_symbol": 409, "persistence_error": 500}.get(
            exc.code, 400
        )
        self._send(
            status,
            {"ok": False, "code": exc.code, "message": str(exc), "error": str(exc)},
        )

    def _rule_error(self, exc: RuleError) -> None:
        payload: dict[str, Any] = {
            "ok": False,
            "code": exc.code,
            "message": str(exc),
            "error": str(exc),
        }
        if exc.field is not None:
            payload["field"] = exc.field
        if exc.minimum is not None:
            payload["min"] = exc.minimum
            payload["minimum"] = exc.minimum
        if exc.maximum is not None:
            payload["max"] = exc.maximum
            payload["maximum"] = exc.maximum
        if exc.code == "out_of_bounds":
            payload["exclusive_min"] = exc.exclusive_minimum
            allowed: dict[str, Any] = {}
            if exc.exclusive_minimum:
                allowed["gt"] = exc.minimum
            elif exc.minimum is not None:
                allowed["min"] = exc.minimum
            if exc.maximum is not None:
                allowed["max"] = exc.maximum
            payload["allowed"] = allowed
            payload["range"] = [exc.minimum, exc.maximum]
        self._send(exc.status_code, payload)

    def _plan_error(self, exc: PlanError) -> None:
        payload: dict[str, Any] = {
            "ok": False,
            "code": exc.code,
            "message": str(exc),
            "error": str(exc),
        }
        if exc.field is not None:
            payload["field"] = exc.field
        self._send(exc.status_code, payload)

    def _actor(self) -> str:
        return sanitize_actor(self.headers.get("X-Actor"))

    def _read_json(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._error(400, "missing Content-Length")
            return None
        try:
            length = int(raw_length)
        except ValueError:
            self._error(400, "invalid Content-Length")
            return None
        if length < 0:
            self._error(400, "invalid Content-Length")
            return None
        if length > MAX_BODY_BYTES:
            self._error(413, "request body too large")
            return None
        try:
            body = self.rfile.read(length)
        except OSError:
            self._error(400, "cannot read request body")
            return None
        if len(body) != length:
            self._error(400, "truncated request body")
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "request body must be UTF-8 JSON")
            return None
        if not isinstance(payload, dict):
            self._error(400, "request body must be a JSON object")
            return None
        return payload

    def _reject_method(self, allow: str = "GET, POST") -> None:
        self.send_response(405)
        self.send_header("Allow", allow)
        body = json.dumps({"error": "method not allowed"}).encode("utf-8")
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        engine: Engine = self.server.engine  # type: ignore[attr-defined]
        if parsed.path == "/health":
            self._send(200, engine.health_dict())
            return
        if parsed.path == "/state":
            self._send(200, engine.state_dict())
            return
        if parsed.path == "/rules":
            self._send(200, engine.rules_payload())
            return
        if parsed.path == "/rules/history":
            query = parse_qs(parsed.query)
            limit = 50
            if "limit" in query:
                try:
                    limit = int(query["limit"][-1])
                except ValueError:
                    self._error(400, "limit must be an integer")
                    return
                if limit < 0:
                    self._error(400, "limit must be a non-negative integer")
                    return
                limit = min(limit, 500)
            self._send(200, engine.rule_history(limit=limit))
            return
        if parsed.path == "/watchlist":
            self._send(200, engine.watchlist_dict())
            return
        if parsed.path == "/plans":
            query = parse_qs(parsed.query)
            plan_id = query.get("id", [None])[-1]
            if plan_id is None:
                self._send(200, engine.plans_payload())
                return
            try:
                self._send(200, engine.plan_payload(plan_id))
            except PlanError as exc:
                self._plan_error(exc)
            return
        if parsed.path in WATCHLIST_WRITE_PATHS:
            self._reject_method("POST")
            return
        if parsed.path in RULE_WRITE_PATHS:
            self._reject_method("POST")
            return
        if parsed.path in PLAN_WRITE_PATHS:
            self._reject_method("POST")
            return
        if parsed.path == "/alerts":
            query = parse_qs(parsed.query)
            after_id: int | None = None
            if "after_id" in query or "since_id" in query:
                key = "after_id" if "after_id" in query else "since_id"
                try:
                    after_id = int(query[key][-1])
                except ValueError:
                    self._error(400, f"{key} must be an integer")
                    return
            limit = 100
            if "limit" in query:
                try:
                    limit = int(query["limit"][-1])
                except ValueError:
                    self._error(400, "limit must be an integer")
                    return
                limit = max(0, min(limit, 500))
            self._send(200, engine.alerts(after_id=after_id, limit=limit))
            return
        self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        engine: Engine = self.server.engine  # type: ignore[attr-defined]
        if parsed.path in PLAN_WRITE_PATHS:
            payload = self._read_json()
            if payload is None:
                return
            actor = self._actor()
            try:
                if parsed.path == "/plans/upsert":
                    body = payload
                    if "id" not in payload and isinstance(payload.get("plan"), dict):
                        body = payload["plan"]
                    result = engine.upsert_plan(body, actor=actor)
                else:
                    if "id" not in payload:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "code": "invalid_plan",
                                "message": "缺少 id",
                                "error": "缺少 id",
                                "field": "id",
                            },
                        )
                        return
                    result = engine.remove_plan(payload["id"], actor=actor)
            except PlanError as exc:
                self._plan_error(exc)
                return
            self._send(200, result)
            return
        if parsed.path in RULE_WRITE_PATHS:
            payload = self._read_json()
            if payload is None:
                return
            actor = self._actor()
            try:
                if parsed.path == "/rules/upsert":
                    body = payload
                    if "id" not in payload and isinstance(payload.get("rule"), dict):
                        body = payload["rule"]
                    result = engine.upsert_rule(body, actor=actor)
                else:
                    if "id" not in payload:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "code": "invalid_id",
                                "message": "缺少 id",
                                "error": "缺少 id",
                                "field": "id",
                            },
                        )
                        return
                    if parsed.path == "/rules/remove":
                        result = engine.remove_rule(payload["id"], actor=actor)
                    else:
                        result = engine.revert_rule(payload["id"], actor=actor)
            except RuleError as exc:
                self._rule_error(exc)
                return
            self._send(200, result)
            return
        if parsed.path not in WATCHLIST_WRITE_PATHS:
            if parsed.path in {"/health", "/state", "/rules", "/rules/history", "/alerts", "/watchlist", "/plans"}:
                self._reject_method("GET")
            else:
                self._error(404, "not found")
            return
        payload = self._read_json()
        if payload is None:
            return
        if "code" not in payload:
            self._send(
                400,
                {
                    "ok": False,
                    "code": "invalid_symbol",
                    "message": "缺少 code",
                    "error": "缺少 code",
                },
            )
            return
        try:
            if parsed.path == "/watchlist/add":
                result = engine.add_symbol(payload["code"])
            else:
                result = engine.remove_symbol(payload["code"])
        except WatchlistError as exc:
            self._watchlist_error(exc)
            return
        self._send(200, result)

    def do_PUT(self) -> None:  # noqa: N802
        self._reject_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject_method()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._reject_method()

    def do_HEAD(self) -> None:  # noqa: N802
        self._reject_method()


def make_server(engine: Engine, host: str, port: int) -> WatchHTTPServer:
    # Never bind a wildcard address, regardless of how the config spells loopback.
    bind_host = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else host
    return WatchHTTPServer((bind_host, port), engine)


def start_server(engine: Engine, host: str, port: int) -> tuple[WatchHTTPServer, threading.Thread]:
    httpd = make_server(engine, host, port)
    thread = threading.Thread(target=httpd.serve_forever, name="cn-watch-http", daemon=True)
    thread.start()
    return httpd, thread


def stop_server(httpd: WatchHTTPServer, thread: threading.Thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()
