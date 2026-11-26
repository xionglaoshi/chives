"""Loopback read-only HTTP API for market-watch (GET only)."""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .engine import Engine

logger = logging.getLogger("chives_compass.server")

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
SECTOR_RE = re.compile(r"^/sectors/(BK[0-9]{4})$")
MEMBERS_RE = re.compile(r"^/sectors/(BK[0-9]{4})/members$")


class MarketHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], engine: Engine) -> None:
        self.engine = engine
        super().__init__(address, MarketRequestHandler)


class MarketRequestHandler(BaseHTTPRequestHandler):
    server_version = "chives-compass/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"ok": False, "error": {"code": code, "message": message}})

    def _reject_method(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        body = json.dumps(
            {"ok": False, "error": {"code": "method_not_allowed", "message": "只允许 GET"}},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        engine: Engine = self.server.engine  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path == "/health":
                self._send(200, engine.health_dict())
                return
            if path == "/overview":
                self._send(200, engine.overview_dict())
                return
            if path == "/rules":
                self._send(200, engine.rules_payload())
                return
            if path == "/sectors":
                level = query.get("level", ["sw1"])[-1]
                self._send(200, engine.sectors_dict(level))
                return
            if path == "/summary":
                self._send(200, engine.summary_dict())
                return
            if path == "/movers":
                kind = query.get("kind", ["gainers"])[-1]
                try:
                    limit = int(query.get("limit", ["10"])[-1])
                except ValueError:
                    self._error(200, "bad_request", "limit 必须是 5–20 的整数")
                    return
                flags: dict[str, bool] = {}
                for name in ("include_st", "include_new", "include_bj"):
                    raw = query.get(name, ["0"])[-1]
                    if raw not in {"0", "1"}:
                        self._error(200, "bad_request", f"{name} 只接受 0 或 1")
                        return
                    flags[name] = raw == "1"
                self._send(200, engine.movers_dict(kind, limit, **flags))
                return
            if path == "/flows/northbound":
                self._send(200, engine.northbound_dict())
                return
            if path == "/flows":
                kind = query.get("kind", ["sector_in"])[-1]
                try:
                    limit = int(query.get("limit", ["10"])[-1])
                except ValueError:
                    self._error(400, "bad_request", "limit 必须是 5–20 的整数")
                    return
                flags: dict[str, bool] = {}
                for name in ("include_st", "include_new", "include_bj"):
                    raw = query.get(name, ["0"])[-1]
                    if raw not in {"0", "1"}:
                        self._error(400, "bad_request", f"{name} 只接受 0 或 1")
                        return
                    flags[name] = raw == "1"
                payload = engine.flows_dict(kind, limit, **flags)
                self._send(200 if payload.get("ok") else 400, payload)
                return
            if path == "/pool":
                kind = query.get("kind", ["zt"])[-1]
                date_text = query.get("date", [None])[-1]
                raw_limit = query.get("limit", ["200"])[-1]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self._send(200, engine.pool_dict(kind, date_text, -1))
                    return
                self._send(200, engine.pool_dict(kind, date_text, limit))
                return
            if path == "/pool/ladder":
                self._send(200, engine.pool_ladder_dict(query.get("date", [None])[-1]))
                return
            if path == "/pool/history":
                raw_days = query.get("days", ["20"])[-1]
                try:
                    days = int(raw_days)
                except ValueError:
                    self._send(200, engine.pool_history_dict(-1))
                    return
                self._send(200, engine.pool_history_dict(days))
                return
            if path == "/pool/yesterday":
                self._send(200, engine.pool_yesterday_dict())
                return
            if path == "/pool/by-industry":
                self._send(200, engine.pool_by_industry_dict(query.get("date", [None])[-1]))
                return
            if path == "/breadth/series":
                self._send(200, engine.breadth_series_dict(query.get("date", [None])[-1]))
                return
            if path == "/themes":
                kind = query.get("kind", ["concept"])[-1]
                sort = query.get("sort", ["change"])[-1]
                raw_limit = query.get("limit", ["20"])[-1]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self._send(200, engine.themes_dict(kind, -1, sort))
                    return
                self._send(200, engine.themes_dict(kind, limit, sort))
                return
            if path == "/alerts":
                since_id = 0
                limit = 50
                if "since_id" in query:
                    try:
                        since_id = int(query["since_id"][-1])
                    except ValueError:
                        self._error(200, "invalid_param", "since_id 必须是整数")
                        return
                if "limit" in query:
                    try:
                        limit = int(query["limit"][-1])
                    except ValueError:
                        self._error(200, "invalid_param", "limit 必须是整数")
                        return
                self._send(200, engine.alerts_dict(since_id=since_id, limit=limit))
                return
            match = SECTOR_RE.match(path)
            if match:
                self._send(200, engine.sector_dict(match.group(1)))
                return
            match = MEMBERS_RE.match(path)
            if match:
                self._send(200, engine.members_dict(match.group(1)))
                return
            self._error(404, "not_found", f"未知路径: {path}")
        except Exception:  # noqa: BLE001 - upstream/data errors must never produce a 500
            logger.exception("处理请求失败: %s", self.path)
            self._error(200, "internal_error", "引擎内部错误，详见日志")

    def do_POST(self) -> None:  # noqa: N802
        self._reject_method()

    do_PUT = do_POST  # type: ignore[assignment]
    do_DELETE = do_POST  # type: ignore[assignment]
    do_PATCH = do_POST  # type: ignore[assignment]
    do_HEAD = do_POST  # type: ignore[assignment]
    do_OPTIONS = do_POST  # type: ignore[assignment]


def make_server(engine: Engine, host: str, port: int) -> MarketHTTPServer:
    # Never bind a wildcard address: the API is loopback-only by contract.
    return MarketHTTPServer(("127.0.0.1", port), engine)


def start_server(engine: Engine, host: str, port: int) -> tuple[MarketHTTPServer, threading.Thread]:
    httpd = make_server(engine, host, port)
    thread = threading.Thread(target=httpd.serve_forever, name="chives-compass-http", daemon=True)
    thread.start()
    return httpd, thread


def stop_server(httpd: MarketHTTPServer, thread: threading.Thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()
