from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable


def canonical(key: str) -> str:
    """sh600000 -> 600000.SH."""
    return f"{key[2:]}.{key[:2].upper()}"


def quote_line(
    key: str,
    name: str,
    price: float | str,
    prev_close: float | str,
    change_pct: float | str = 0.0,
    *,
    quote_time: str = "2026-11-03T10:30:00+08:00",
    limit_up: float | str | None = None,
    limit_down: float | str | None = None,
) -> dict[str, Any]:
    """Build one gateway `market_quote` row for a vendor-style fixture key."""
    return {
        "code": canonical(key),
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "open": prev_close,
        "high": price,
        "low": price,
        "volume_shares": 1_000_000,
        "amount_yuan": 15_000_000.0,
        "turnover_pct": 0.5,
        "volume_ratio": 1.0,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "quote_time": quote_time,
    }


def kline_rows(dates: Iterable[str], closes: Iterable[float]) -> list[list[str]]:
    """Fixture rows: [date, open, close, high, low, volume(shares)]."""
    return [
        [day, f"{close}", f"{close}", f"{close}", f"{close}", "1000"]
        for day, close in zip(dates, closes)
    ]


class _GatewayServer:
    """Loopback fake of ``POST /v1/call``; subclasses build the envelope."""

    def __init__(self, *, status: int = 200, location: str | None = None) -> None:
        self.status = status
        self.location = location
        self.calls: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.calls.append(body)
                if outer.status != 200:
                    self.send_response(outer.status)
                    if outer.location:
                        self.send_header("Location", outer.location)
                    self.end_headers()
                    return
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

    def respond(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def _envelope(status: str, data: dict[str, Any], message: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "as_of": "2026-11-03T10:30:00+08:00",
        "data": data,
        "missing": [],
        "stale": False,
    }
    if message is not None:
        payload["message"] = message
    return payload


class FakeQuoteServer(_GatewayServer):
    """Serves `market_quote`; keys are vendor-style fixture symbols."""

    def __init__(
        self,
        quotes: dict[str, dict[str, Any]] | None = None,
        *,
        status: int = 200,
        location: str | None = None,
        envelope_status: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(status=status, location=location)
        self.quotes = quotes or {}
        self.envelope_status = envelope_status
        self.message = message

    def respond(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        assert tool == "market_quote"
        requested = [str(code) for code in args.get("codes") or []]
        items = []
        for code in requested:
            key = code.split(".")[1].lower() + code.split(".")[0]
            if key in self.quotes:
                items.append(self.quotes[key])
        if self.envelope_status is not None:
            return _envelope(self.envelope_status, {}, self.message)
        status = "ok" if len(items) == len(requested) else "partial"
        return _envelope(status, {"quotes": items})


class FakeKlineServer(_GatewayServer):
    """Serves `market_bars`; `data[symbol]` keeps the old day/qfqday fixture shape."""

    def __init__(
        self,
        data: dict[str, dict[str, list[list[str]]]] | None = None,
        *,
        status: int = 200,
        location: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status=status, location=location)
        self.data = data or {}
        self.payload = payload
        self.params: list[dict[str, Any]] = []
        self.symbols: list[str] = []

    def respond(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        assert tool == "market_bars"
        symbol = str(args.get("code") or "")
        self.symbols.append(symbol)
        self.params.append(dict(args))
        if self.payload is not None:
            return self.payload
        key = "qfqday" if args.get("adjust") == "qfq" else "day"
        entry = self.data.get(symbol)
        if entry is None or key not in entry:
            return _envelope("unavailable", {}, "该代码在该时段没有 K 线数据")
        bars = [
            {
                "time": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume_shares": int(float(row[5])),
                "amount_yuan": None,
                "turnover_pct": None,
            }
            for row in entry[key]
        ]
        return _envelope("ok", {"code": symbol, "interval": "1d", "bars": bars, "count": len(bars)})
