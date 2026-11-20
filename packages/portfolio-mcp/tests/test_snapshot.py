from __future__ import annotations

import json
from datetime import date

from portfolio_mcp.__main__ import main
from portfolio_mcp.fields import validate_positions
from portfolio_mcp.quotes import Quote
from portfolio_mcp.service import PortfolioService
from portfolio_mcp.snapshot import build_snapshot
from portfolio_mcp.store import PortfolioState, PortfolioStore

from helpers import FakeQuoteServer, quote_line

TODAY = date(2026, 11, 3)


class StubQuotes:
    """Returns fixed `Quote` objects; no network."""

    def __init__(self, quotes: dict[str, Quote]) -> None:
        self.quotes = quotes

    def fetch(self, codes: list[str]) -> dict[str, Quote]:
        return {code: self.quotes[code] for code in codes if code in self.quotes}


def _seed(store, rows, cash=None) -> None:
    validated = validate_positions(rows, today=TODAY)
    store.apply(lambda state: PortfolioState(positions=validated, cash=cash, as_of="2026-11-03"))


def _row(code: str, qty: int, cost: float, name: str = "测试股票") -> dict[str, object]:
    return {"code": code, "name": name, "qty": qty, "cost_price": cost}


def _quote(code: str, name: str, price: float | None, prev_close: float | None) -> Quote:
    change = None
    if price is not None and prev_close:
        change = round((price - prev_close) / prev_close * 100, 2)
    return Quote(
        code=code,
        name=name,
        price=price,
        prev_close=prev_close,
        change_pct=change,
        time="2026-11-03T10:30:00+08:00",
        limit_up=None,
        limit_down=None,
    )


def test_empty_portfolio_prints_empty_snapshot(store) -> None:
    payload = build_snapshot(store, PortfolioService(store, quotes=None, today=lambda: TODAY))
    assert payload["status"] == "empty"
    assert payload["positions"] == []
    assert payload["unpriced"] == []
    assert payload["cash"] is None
    assert payload["as_of"] is None
    assert payload["summary"]["total_market_value"] == 0.0


def test_snapshot_hand_computes_pnl_and_today(store) -> None:
    _seed(
        store,
        [
            _row("600000", 1000, 8.0, "浦发银行"),
            _row("000001", 500, 25.0, "平安银行"),
        ],
        cash=5000.0,
    )
    quotes = StubQuotes(
        {
            "600000.SH": _quote("600000.SH", "浦发银行", 10.0, 9.0),
            "000001.SZ": _quote("000001.SZ", "平安银行", 20.0, 19.0),
        }
    )
    service = PortfolioService(store, quotes=quotes, today=lambda: TODAY)
    payload = build_snapshot(store, service)

    assert payload["status"] == "ready"
    assert payload["cash"] == 5000.0
    assert payload["as_of"] == "2026-11-03T10:30:00+08:00"
    first, second = payload["positions"]
    # Sorted by market value, descending: 600000 (10000) before 000001 (10000)? tie broken by code.
    assert [row["code"] for row in payload["positions"]] == ["000001.SZ", "600000.SH"]
    assert first["name"] == "平安银行"
    assert first["qty"] == 500
    assert first["cost_price"] == 25.0
    assert first["price"] == 20.0
    assert first["market_value"] == 10000.0
    assert first["pnl"] == -2500.0
    assert first["pnl_pct"] == -20.0
    assert first["today_pnl"] == 500.0
    assert second["today_pnl"] == 1000.0
    assert second["price_available"] is True

    summary = payload["summary"]
    assert summary["position_count"] == 2
    assert summary["priced_count"] == 2
    assert summary["total_market_value"] == 20000.0
    assert summary["total_pnl"] == -500.0
    assert summary["today_pnl"] == 1500.0
    # (1500 / (9*1000 + 19*500)) * 100
    assert summary["today_pnl_pct"] == 1500 / 18500 * 100


def test_snapshot_lists_unpriced_rows_and_keeps_today_unknown(store) -> None:
    _seed(
        store,
        [
            _row("600000", 1000, 8.0, "浦发银行"),
            _row("000001", 500, 25.0, "平安银行"),
        ],
    )
    quotes = StubQuotes({"000001.SZ": _quote("000001.SZ", "平安银行", 20.0, None)})
    service = PortfolioService(store, quotes=quotes, today=lambda: TODAY)
    payload = build_snapshot(store, service)

    codes = [row["code"] for row in payload["positions"]]
    assert codes == ["000001.SZ", "600000.SH"]
    missing = payload["positions"][1]
    assert missing["price"] is None
    assert missing["price_available"] is False
    assert missing["today_pnl"] is None
    assert [row["code"] for row in payload["unpriced"]] == ["600000.SH"]
    assert payload["unpriced"][0]["reason"]
    assert payload["summary"]["unpriced_count"] == 1
    # One row has no prev_close, so today's P&L cannot be summed.
    assert payload["summary"]["today_pnl"] is None
    assert payload["summary"]["today_pnl_pct"] is None


def test_snapshot_keeps_today_unknown_when_one_prev_close_is_missing(store) -> None:
    _seed(
        store,
        [
            _row("600000", 1000, 8.0, "浦发银行"),
            _row("000001", 500, 25.0, "平安银行"),
        ],
    )
    quotes = StubQuotes(
        {
            "600000.SH": _quote("600000.SH", "浦发银行", 10.0, 9.0),
            "000001.SZ": _quote("000001.SZ", "平安银行", 20.0, None),
        }
    )
    service = PortfolioService(store, quotes=quotes, today=lambda: TODAY)
    payload = build_snapshot(store, service)

    by_code = {row["code"]: row for row in payload["positions"]}
    assert by_code["600000.SH"]["today_pnl"] == 1000.0
    assert by_code["000001.SZ"]["today_pnl"] is None
    assert payload["summary"]["today_pnl"] is None
    assert payload["summary"]["today_pnl_pct"] is None


def test_cli_snapshot_prints_json(store, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DSH_HOME", str(store.profile_dir))
    assert main(["snapshot"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "empty"
    assert payload["positions"] == []


def test_cli_rejects_unknown_arguments(capsys) -> None:
    assert main(["snapshot", "--json"]) == 2
    assert "usage" in capsys.readouterr().err


def test_cli_snapshot_uses_temporary_home_and_live_quote_path(
    home, monkeypatch, capsys
) -> None:
    store = PortfolioStore(profile_dir=home)
    _seed(store, [_row("600000", 1000, 8.0, "浦发银行")], cash=1000.0)
    server = FakeQuoteServer(
        {
            "sh600000": quote_line(
                "sh600000",
                "浦发银行",
                10.0,
                9.0,
                11.11,
                quote_time="2026-11-03T10:30:00+08:00",
            )
        }
    )
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)
    try:
        assert main(["snapshot"]) == 0
    finally:
        server.close()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["cash"] == 1000.0
    row = payload["positions"][0]
    assert row["code"] == "600000.SH"
    assert row["price"] == 10.0
    assert row["today_pnl"] == 1000.0
    assert payload["summary"]["today_pnl"] == 1000.0
