"""Minimal loopback fake of the cn-market-gateway ``POST /v1/call`` endpoint."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


def envelope(
    status: str,
    quotes: list[dict[str, Any]] | None = None,
    *,
    message: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": status,
        "as_of": "2026-11-03T09:30:00+08:00",
        "data": {"quotes": quotes} if quotes is not None else {},
        "missing": [],
        "stale": False,
    }
    if message is not None:
        body["message"] = message
    return body


def quote_item(
    code: str,
    name: str,
    price: float | str,
    prev_close: float | str,
    *,
    open_: float | str | None = None,
    high: float | str | None = None,
    low: float | str | None = None,
    volume_shares: int | None = 1_000_000,
    amount_yuan: float | None = 15_000_000.0,
    limit_up: float | None = 16.5,
    limit_down: float | None = 13.5,
    volume_ratio: float | None = 1.2,
    quote_time: str = "2026-11-03T09:30:00+08:00",
    change_pct: float = 0.0,
) -> dict[str, Any]:
    open_value = price if open_ is None else open_
    return {
        "code": code,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "open": open_value,
        "high": price if high is None else high,
        "low": price if low is None else low,
        "volume_shares": volume_shares,
        "amount_yuan": amount_yuan,
        "turnover_pct": 0.5,
        "volume_ratio": volume_ratio,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "quote_time": quote_time,
    }


class FakeGateway:
    """Serve ``/v1/call`` with a callback; records every request body."""

    def __init__(self, respond: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.calls.append(body)
                payload = outer.respond(body.get("tool", ""), body.get("args") or {})
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
