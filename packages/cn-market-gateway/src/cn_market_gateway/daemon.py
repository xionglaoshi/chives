"""Loopback-only HTTP daemon for the gateway."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import config, schemas
from .envelope import now_iso, unavailable
from .service import GatewayService

logger = logging.getLogger(__name__)
MAX_BODY = 1024 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "cn-market-gateway/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self) -> GatewayService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str) -> dict[str, Any]:
        return unavailable(now_iso(self.service.now()), message)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, self.service.health())
            return
        if path == "/v1/tools":
            self._send(200, {"tools": schemas.static_tools()})
            return
        self._send(404, self._error("接口不存在；可用 /v1/call、/v1/tools、/health"))

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path != "/v1/call":
            self._send(404, self._error("接口不存在；可用 /v1/call、/v1/tools、/health"))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send(200, self._error("请求体缺失或过大；请发送 {\"tool\": \"...\", \"args\": {...}}"))
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(200, self._error("请求体不是合法 JSON；请发送 {\"tool\": \"...\", \"args\": {...}}"))
            return
        if not isinstance(body, dict) or not isinstance(body.get("tool"), str):
            self._send(200, self._error("请求体必须包含 tool 与 args"))
            return
        try:
            payload = self.service.call(body["tool"], body.get("args"))
        except Exception:  # defensive: handler must always answer JSON
            logger.exception("unhandled daemon error")
            payload = self._error("数据服务处理请求时出错，请稍后再试")
        self._send(200, payload)


class GatewayDaemon:
    def __init__(self, service: GatewayService | None = None, *, host: str = config.DEFAULT_HOST, port: int = config.DEFAULT_PORT) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("the gateway only listens on the loopback address")
        self.service = service or GatewayService()
        self.httpd = ThreadingHTTPServer((config.DEFAULT_HOST, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.service = self.service  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> "GatewayDaemon":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="cn-market-gateway", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def __enter__(self) -> "GatewayDaemon":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


#: Slow, rarely changing data fetched once in the background when the daemon starts, so the
#: first bot that asks does not wait minutes (quarterly holdings pages, recent northbound days).
WARM_UP_CALLS: tuple[tuple[str, dict], ...] = (
    ("market_northbound", {"kind": "daily", "days": 10}),
    ("market_northbound", {"kind": "holdings", "limit": 1}),
)


def warm_up(service: GatewayService) -> None:
    for tool, args in WARM_UP_CALLS:
        try:
            # Each call waits at most CALL_BUDGET_SECONDS; the background fill keeps going.
            service.call(tool, dict(args))
        except Exception:  # noqa: BLE001 - warm-up is best effort
            logger.exception("warm-up %s failed", tool)


def serve(host: str = config.DEFAULT_HOST, port: int = config.DEFAULT_PORT) -> int:
    daemon = GatewayDaemon(host=host, port=port)
    logger.info("cn-market-gateway listening on %s:%s", host, daemon.port)
    threading.Thread(target=warm_up, args=(daemon.service,), name="cn-market-warm-up", daemon=True).start()
    try:
        daemon.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.httpd.server_close()
    return 0
