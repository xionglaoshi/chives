"""A second fake hub covering the hub v1.1 endpoints used by the v2 tools."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

REVIEW_DATA: dict[str, Any] = {
    "ok": True,
    "private": True,
    "as_of": "2026-11-04T19:45:00+08:00",
    "trading_day": True,
    "date": "2026-11-04",
    "next_trading_day": "2026-11-05",
    "data_cutoff": "19:45",
    "env": {"regime": "strong", "rule_label": "偏强", "evidence": ["涨停 62 家", "成交额放大"]},
    "market": {"indexes": [{"code": "000001.SH", "name": "上证指数", "change_pct": 0.82}], "breadth": {"up": 3100}},
    "pool": {"counts": {"zt": 62, "zb": 8, "dt": 3}, "seal_ratio_pct": 88.5, "max_streak": 5, "ladder": []},
    "themes": [{"name": "机器人", "note": "涨停 9 家"}],
    "sectors": [{"code": "BK0433", "name": "机器人", "change_pct": 3.2}],
    "flows": [],
    "holdings": {
        "empty": False,
        "positions": [{"code": "600000.SH", "name": "浦发银行", "weight_pct": 12.5, "pnl_pct": 3.1, "industry": "银行"}],
        "totals": {"total_assets_cny": 1000000},
        "limits": {"total_cap_pct": 70},
    },
    "cards": {"open": [], "yesterday_cards": []},
    "settings": [],
    "discipline": {"paused": False},
    "last_review": {"date": "2026-11-03", "env_label": "neutral", "candidates": ["600000.SH"]},
    "missing": [{"part": "lhb", "reason": "not_published"}],
}

SHORT_REVIEW_DATA: dict[str, Any] = {
    "ok": True,
    "trading_day": False,
    "date": "2026-11-07",
    "next_trading_day": "2026-11-10",
}

SETTINGS: list[dict[str, Any]] = [
    {"key": "total_cap_strong_pct", "label": "总仓位上限（强势）", "unit": "%", "value": 70.0, "source": "adopted", "suggestion": None},
    {"key": "single_stock_cap_pct", "label": "单票上限", "unit": "%", "value": None, "source": "unset", "suggestion": {"value": 20.0, "basis": "示例", "backtested": False}},
]

CARDS: dict[int, dict[str, Any]] = {
    20: {"id": 20, "code": "600000.SH", "name": "浦发银行", "status": "proposed", "state": "observe", "proposed_by": "agent", "thesis": "回踩承接", "risk": {"stop_price": 9.1}},
    21: {"id": 21, "code": "600000.SH", "name": "浦发银行", "status": "proposed", "state": "observe", "proposed_by": "user", "thesis": "用户自己的卡", "risk": {"stop_price": 9.1}},
    22: {"id": 22, "code": "000001.SZ", "name": "平安银行", "status": "active", "state": "observe", "proposed_by": "agent", "thesis": "已确认", "risk": {"stop_price": 10.1}},
    23: {"id": 23, "code": "300750.SZ", "name": "宁德时代", "status": "cancelled", "state": "abandon", "proposed_by": "agent", "thesis": "已取消", "risk": {"stop_price": 180.0}},
}


class FakeHubV2:
    def __init__(self) -> None:
        self.log: list[tuple[str, str, Any]] = []
        self.review_trading_day = True
        self.big_paths: set[str] = set()
        self.business_errors: dict[str, tuple[str, str]] = {}
        self.post_business_errors: dict[str, tuple[str, str]] = {}
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _send(self, payload: Any, code: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _raw(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _error(self, code: str, message: str) -> None:
                self._send({"ok": False, "error": {"code": code, "message": message}})

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                hub.log.append(("GET", self.path, None))
                if path in hub.big_paths:
                    self._raw(b'{"ok":true,"pad":"' + b"x" * (600 * 1024) + b'"}')
                    return
                if path in hub.business_errors:
                    self._error(*hub.business_errors[path])
                    return
                if path == "/review-data":
                    self._send(REVIEW_DATA if hub.review_trading_day else SHORT_REVIEW_DATA)
                    return
                if path == "/settings":
                    self._send({"ok": True, "as_of": "2026-11-04T19:45:00+08:00", "settings": SETTINGS})
                    return
                if path == "/candidates/stats":
                    days = int((query.get("days") or ["20"])[-1])
                    self._send({"ok": True, "n": days, "sample_insufficient": days < 30, "trigger_rate_pct": 41.5, "note": "示例"})
                    return
                if path == "/cards":
                    status = (query.get("status") or ["all"])[-1]
                    if status == "closed":
                        rows = [card for card in CARDS.values() if card["status"] in {"expired", "cancelled", "closed"}]
                    else:
                        rows = [card for card in CARDS.values() if status == "all" or card["status"] == status]
                    self._send({"ok": True, "cards": rows, "counts": {"proposed": 2, "active": 1}})
                    return
                if path.startswith("/cards/"):
                    try:
                        card_id = int(path.rsplit("/", 1)[1])
                    except ValueError:
                        self._error("not_found", "未知路径")
                        return
                    card = CARDS.get(card_id)
                    if card is None:
                        self._error("card_not_found", "作战卡不存在")
                    else:
                        self._send({"ok": True, "card": card})
                    return
                self._error("not_found", "未知路径")

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                body = json.loads(raw or b"{}")
                path = urlsplit(self.path).path
                hub.log.append(("POST", self.path, body))
                if path in hub.post_business_errors:
                    self._error(*hub.post_business_errors[path])
                    return
                if path == "/reviews":
                    self._send({"ok": True, "review": {**body, "revision": 2}, "revision": 2})
                    return
                if path.startswith("/settings/") and path.endswith("/suggest"):
                    key = path.split("/")[2]
                    self._send(
                        {
                            "ok": True,
                            "setting": {
                                "key": key,
                                "value": None,
                                "source": "unset",
                                "suggestion": {
                                    "value": body.get("value"),
                                    "basis": body.get("basis"),
                                    "backtested": False,
                                },
                            },
                        }
                    )
                    return
                if path == "/cards":
                    self._send(
                        {
                            "ok": True,
                            "card": {
                                "id": 30,
                                "code": body.get("code"),
                                "status": "proposed",
                                "state": "observe",
                                "proposed_by": body.get("proposed_by"),
                            },
                            "warnings": [],
                        }
                    )
                    return
                if path.startswith("/cards/") and path.endswith("/action"):
                    card_id = int(path.split("/")[2])
                    card = dict(CARDS.get(card_id, {"id": card_id}))
                    card["status"] = "cancelled"
                    self._send({"ok": True, "card": card})
                    return
                self._error("not_found", "未知路径")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> "FakeHubV2":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def posts(self) -> list[tuple[str, str, Any]]:
        return [entry for entry in self.log if entry[0] == "POST"]

    def gets(self) -> list[tuple[str, str, Any]]:
        return [entry for entry in self.log if entry[0] == "GET"]
