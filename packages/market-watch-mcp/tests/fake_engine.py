"""Deterministic local fake of the market-watch HTTP API for offline tests."""

from __future__ import annotations

import copy
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

AS_OF = "2026-11-04T15:00:00+08:00"
FLOWS_DEFINITION = "东财主力净流入（大单+超大单，厂商口径，仅作辅助参考）"


def _rows(n: int, **extra: Any) -> list[dict[str, Any]]:
    return [
        {"rank": i + 1, "code": f"60000{i % 10}.SH", "name": f"股票{i + 1}", "change_pct": 5.0 - i * 0.1,
         "amount_yuan": 1.0e9 - i * 1e6, **extra}
        for i in range(n)
    ]


def default_responses() -> dict[str, dict[str, Any]]:
    block = {"as_of": AS_OF, "stale": False}
    return {
        "/overview": {
            "ok": True, "as_of": AS_OF, "trading_state": "open",
            "indexes": [{"code": "000001.SH", "name": "上证指数", "price": 3300.5, "prev_close": 3290.0,
                         "change_pct": 0.32, "amount_yuan": 4.0e11, "spark": [], **block}],
            "breadth": {"up": 3000, "down": 1900, "flat": 100, "up_ratio": 0.6, "limit_up": 60,
                        "limit_down": 3, "broken": 20, "seal_ratio": 0.75, "max_streak": 5,
                        "amount_yuan": 9.0e11, **block},
            "regime": {"label": "neutral", "reasons": ["宽度中性"]},
        },
        "/summary": {
            "ok": True, "as_of": AS_OF, "generated_by": "engine",
            "headlines": [{"id": "h1", "tone": "up", "title": "指数收涨", "body": "上证指数 +0.32%", "refs": []}],
        },
        "/sectors": {
            "ok": True, "as_of": AS_OF, "level": "sw1", "sort": "change_pct", "trading_state": "open",
            "rows": [{"code": f"BK04{i:02d}", "name": f"行业{i}", "change_pct": 3.0 - i * 0.1,
                      "amount_yuan": 1e10, "rank": i + 1, "member_count": 40, **block} for i in range(40)],
        },
        "/sectors/BK0433": {
            "ok": True, "as_of": AS_OF, "code": "BK0433", "name": "食品饮料", "change_pct": 1.2,
            "trading_state": "open", "trend": [{"t": "09:31", "change_pct": 0.1}],
            "history": {"ret_5d_pct": 2.0, "ret_20d_pct": 5.0, "rank_5d": 3, "rank_20d": 8}, "stale": False,
        },
        "/sectors/BK0433/members": {
            "ok": True, "as_of": AS_OF,
            "rows": [{"code": f"60{i:04d}.SH", "name": f"成分{i}", "price": 10.0, "change_pct": 1.0,
                      "amount_yuan": 1e8, "limit_up": False, "limit_down": False} for i in range(100)],
        },
        "/themes": {
            "ok": True, "as_of": AS_OF, "kind": "concept", "sort": "change", "stale": False,
            "definition": "东财概念板块（厂商口径）", "source": "eastmoney.clist",
            "rows": [{"rank": i + 1, "code": f"BK1{i:03d}", "name": f"概念{i}", "change_pct": 4.0,
                      "amount_yuan": 1e9, "up_count": 20, "down_count": 5, "leader": None} for i in range(30)],
        },
        "/movers": {"ok": True, "as_of": AS_OF, "kind": "gainers", "rows": _rows(20), "stale": False,
                    "filters": {"include_st": 0, "include_new": 0, "include_bj": 0}, "source": "tencent"},
        "/flows": {"ok": True, "as_of": AS_OF, "kind": "sector_in", "stale": False,
                   "definition": FLOWS_DEFINITION, "source": "eastmoney.clist",
                   "rows": [{"rank": i + 1, "code": f"BK04{i:02d}", "name": f"行业{i}", "main_net_yuan": 1e8,
                             "main_net_pct": 2.0, "change_pct": 1.0, "amount_yuan": 1e9} for i in range(20)]},
        "/pool": {"ok": True, "as_of": AS_OF, "date": "2026-11-04", "kind": "zt", "count": 60, "stale": False,
                  "definition": "涨停池", "source": "eastmoney.pool",
                  "rows": [{"code": f"00{i:04d}.SZ", "name": f"涨停{i}", "streak": 2, "price": 10.0} for i in range(60)]},
        "/pool/ladder": {"ok": True, "date": "2026-11-04", "max_streak": 5, "first_board_count": 40,
                         "tiers": [{"streak": 5, "count": 1, "rows": []}, {"streak": 1, "count": 40}],
                         "definition": "梯队", "source": "eastmoney.pool"},
        "/pool/history": {"ok": True, "as_of": AS_OF, "days": [{"date": "2026-11-04", "zt": 60, "dt": 3, "zb": 20,
                          "seal_ratio_pct": 75.0, "max_streak": 5, "available": True}],
                          "backfill": {"running": False, "done": 30, "total": 30, "failed": 0},
                          "definition": "历史", "source": "eastmoney.pool"},
        "/pool/yesterday": {"ok": True, "date": "2026-11-04", "prev_date": "2026-11-03", "avg_open_pct": 1.0,
                            "avg_high_pct": 3.0, "avg_close_pct": 0.5, "win_ratio_pct": 55.0,
                            "rows": [{"code": "000001.SZ", "name": "昨日1", "prev_streak": 2, "open_pct": 1.0,
                                      "high_pct": 3.0, "low_pct": 0.0, "now_pct": 0.5}],
                            "definition": "昨日表现", "source": "eastmoney.pool+tencent"},
        "/pool/by-industry": {"ok": True, "as_of": AS_OF, "date": "2026-11-04",
                              "rows": [{"industry": "半导体", "zt_count": 5, "zb_count": 1, "max_streak": 3,
                                        "leaders": []}], "definition": "行业口径", "source": "eastmoney.pool"},
        "/alerts": {"ok": True, "next_id": 3, "alerts": [
            {"id": i, "ts": AS_OF, "rule_id": "R1", "object": {"type": "index", "code": "000001.SH", "name": "上证指数"},
             "severity": "L1", "title": f"告警{i}", "detail": "d", "payload": {}, "status": "new"} for i in (1, 2)]},
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _handle(self) -> None:
        engine: FakeEngine = self.server.engine  # type: ignore[attr-defined]
        parts = urlsplit(self.path)
        engine.record(self.command, parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()})
        if self.command != "GET":
            self.send_response(405)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        override = engine.overrides.get(parts.path)
        if override is None and parts.path not in engine.responses:
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        override = override or {}
        if override.get("delay"):
            time.sleep(override["delay"])
        status = override.get("status", 200)
        if "raw" in override:
            body = override["raw"]
        else:
            body = json.dumps(override.get("body", engine.responses.get(parts.path)), ensure_ascii=False).encode()
        try:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


class FakeEngine:
    def __init__(self) -> None:
        self.responses = copy.deepcopy(default_responses())
        self.overrides: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.engine = self  # type: ignore[attr-defined]
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def record(self, method: str, path: str, query: dict[str, str]) -> None:
        with self._lock:
            self.requests.append((method, path, query))

    def paths(self) -> list[str]:
        return [p for _, p, _ in self.requests]

    def override(self, path: str, **kwargs: Any) -> None:
        self.overrides[path] = kwargs

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
