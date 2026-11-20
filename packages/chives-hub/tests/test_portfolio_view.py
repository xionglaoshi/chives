from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from chives_hub.portfolio_view import PortfolioView, ensure_portfolio_path
from chives_hub.store import HubStore
from tests.support import NOW


def position(
    code="601099.SH",
    name="太平洋",
    qty=1000,
    cost=10.0,
    price=11.0,
    prev=10.0,
    weight=0.5,
    sellable=True,
    unavailable=False,
):
    return {
        "code": code,
        "name": name,
        "qty_shares": qty,
        "cost_price_cny_per_share": cost,
        "price_cny": price,
        "prev_close_cny": prev,
        "change_pct": None if price is None or prev in (None, 0) else (price / prev - 1) * 100,
        "market_value_cny": None if price is None else price * qty,
        "pnl_cny": None if price is None else (price - cost) * qty,
        "pnl_pct": None if price is None else (price - cost) / cost * 100,
        "weight": weight,
        "sellable_today": sellable,
        "price_unavailable": unavailable,
    }


class FakeService:
    def __init__(self, data=None, risk=None, risk_error=None, risk_calls=None):
        self.data = data or {"positions": [], "total_market_value_cny": 0.0, "total_cost_cny": 0.0,
                             "total_pnl_cny": 0.0, "total_pnl_pct": 0.0, "cash_cny": 0.0,
                             "total_assets_cny": 0.0, "quote_time": None}
        self.risk_payload = risk
        self.risk_error = risk_error
        self.risk_calls = risk_calls if risk_calls is not None else []
        self.valuation_calls = 0

    def valuation(self):
        self.valuation_calls += 1
        return {"ok": True, "private": True, "data": self.data}

    def risk(self, args=None):
        self.risk_calls.append(args)
        if self.risk_error:
            raise self.risk_error
        if self.risk_payload is None:
            return {"ok": True, "data": {}}
        return {"ok": True, "data": self.risk_payload}


def make_view(tmp_path: Path, service: FakeService, clock=lambda: NOW) -> PortfolioView:
    return PortfolioView(HubStore(tmp_path / "hub.db"), service=service, now=clock)


def test_ensure_portfolio_path() -> None:
    path = ensure_portfolio_path()
    assert (path / "portfolio_mcp").is_dir()


def test_private_and_empty(tmp_path: Path) -> None:
    service = FakeService({"positions": [], "total_market_value_cny": 0.0, "total_cost_cny": 0.0,
                           "total_pnl_cny": 0.0, "total_pnl_pct": 0.0, "cash_cny": 1000.0,
                           "total_assets_cny": 1000.0, "quote_time": None})
    payload = make_view(tmp_path, service).overview()
    assert payload["private"] is True
    assert payload["empty"] is True
    assert payload["totals"]["cash_cny"] == 1000.0
    assert payload["risk"] is None
    assert payload["risk_reason"] == "empty_portfolio"


def test_positions_and_totals_manual(tmp_path: Path) -> None:
    data = {
        "positions": [
            position(qty=1000, cost=10, price=11, prev=10, weight=11000 / 21000),
            position(code="002553.SZ", name="南方精工", qty=500, cost=20, price=20, prev=21, weight=10000 / 21000),
        ],
        "total_market_value_cny": 21000.0,
        "total_cost_cny": 20000.0,
        "total_pnl_cny": 1000.0,
        "total_pnl_pct": 5.0,
        "cash_cny": 5000.0,
        "total_assets_cny": 26000.0,
        "quote_time": "2026-11-04 10:00:00",
    }
    service = FakeService(data, risk={"annualized_vol_ratio": 0.25, "beta": 1.1,
                                      "max_drawdown_ratio": -0.1, "top1_weight_ratio": 0.6,
                                      "effective_n": 2.0})
    payload = make_view(tmp_path, service).overview()
    assert payload["empty"] is False
    first, second = payload["positions"]
    assert first["cost_price_cny"] == 10 and second["cost_price_cny"] == 20  # real field: cost_price_cny_per_share
    assert first["day_pnl_cny"] == 1000.0
    assert second["day_pnl_cny"] == -500.0
    totals = payload["totals"]
    assert totals["day_pnl_cny"] == 500.0
    assert round(totals["day_pnl_pct"], 6) == round(500 / 20500 * 100, 6)
    assert round(totals["position_ratio_pct"], 6) == round(21000 / 26000 * 100, 6)
    assert round(first["weight_pct"], 4) == round(11000 / 21000 * 100, 4)
    assert payload["quote_time"] == "2026-11-04 10:00:00"
    assert payload["risk"] == {
        "annualized_vol_pct": 25.0,
        "beta": 1.1,
        "max_drawdown_pct": -10.0,
        "top1_weight_pct": 60.0,
        "effective_n": 2.0,
    }


def test_price_unavailable_day_pnl_null(tmp_path: Path) -> None:
    data = {
        "positions": [position(price=None, unavailable=True), position(code="002553.SZ", qty=100, cost=20, price=21, prev=20)],
        "total_market_value_cny": 2100.0,
        "total_cost_cny": 2000.0,
        "total_pnl_cny": 100.0,
        "total_pnl_pct": 5.0,
        "cash_cny": 0.0,
        "total_assets_cny": 2100.0,
        "quote_time": None,
    }
    payload = make_view(tmp_path, FakeService(data)).overview()
    assert payload["positions"][0]["day_pnl_cny"] is None
    assert payload["positions"][0]["price_unavailable"] is True
    assert payload["positions"][1]["day_pnl_cny"] == 100.0


def test_risk_cache(tmp_path: Path) -> None:
    calls = []
    data = {"positions": [position()], "total_market_value_cny": 11000.0, "total_cost_cny": 10000.0,
            "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0, "cash_cny": 0.0,
            "total_assets_cny": 11000.0, "quote_time": None}
    service = FakeService(data, risk={"annualized_vol_ratio": 0.1, "beta": 1.0,
                                      "max_drawdown_ratio": -0.2, "top1_weight_ratio": 1.0,
                                      "effective_n": 1.0}, risk_calls=calls)
    view = make_view(tmp_path, service)
    view.overview()
    view.overview()
    assert len(calls) == 1


def test_risk_cache_expires(tmp_path: Path) -> None:
    calls = []
    data = {"positions": [position()], "total_market_value_cny": 11000.0, "total_cost_cny": 10000.0,
            "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0, "cash_cny": 0.0,
            "total_assets_cny": 11000.0, "quote_time": None}
    service = FakeService(data, risk={"annualized_vol_ratio": 0.1, "beta": 1.0,
                                      "max_drawdown_ratio": -0.2, "top1_weight_ratio": 1.0,
                                      "effective_n": 1.0}, risk_calls=calls)
    clock = [NOW]
    view = PortfolioView(HubStore(tmp_path / "hub.db"), service=service, now=lambda: clock[0])
    view.overview()
    from datetime import timedelta
    clock[0] = NOW + timedelta(seconds=601)
    view.overview()
    assert len(calls) == 2


def test_risk_failure_null_reason(tmp_path: Path) -> None:
    data = {"positions": [position()], "total_market_value_cny": 11000.0, "total_cost_cny": 10000.0,
            "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0, "cash_cny": 0.0,
            "total_assets_cny": 11000.0, "quote_time": None}
    payload = make_view(tmp_path, FakeService(data, risk_error=RuntimeError("boom"))).overview()
    assert payload["risk"] is None
    assert payload["risk_reason"] == "risk_unavailable"


def test_risk_all_null(tmp_path: Path) -> None:
    data = {"positions": [position()], "total_market_value_cny": 11000.0, "total_cost_cny": 10000.0,
            "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0, "cash_cny": 0.0,
            "total_assets_cny": 11000.0, "quote_time": None}
    payload = make_view(tmp_path, FakeService(data, risk={})).overview()
    assert payload["risk"] is None
    assert payload["risk_reason"] == "risk_unavailable"


def test_history_reads_snapshots(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_snapshot(day=date(2026, 11, 3), market_value_cny=1.0, total_assets_cny=2.0,
                          pnl_cny=0.5, day_pnl_cny=0.1, quote_time=None, now=NOW)
    store.insert_snapshot(day=date(2026, 11, 4), market_value_cny=2.0, total_assets_cny=3.0,
                          pnl_cny=0.6, day_pnl_cny=0.2, quote_time=None, now=NOW)
    view = PortfolioView(store, service=FakeService())
    payload = view.history(90)
    assert payload["private"] is True
    assert [point["date"] for point in payload["points"]] == ["2026-11-03", "2026-11-04"]
    assert "不回补历史" in payload["note"]


def test_history_days_limit(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    for day in (1, 2, 3):
        store.insert_snapshot(day=date(2026, 11, day), market_value_cny=1.0, total_assets_cny=1.0,
                              pnl_cny=0.0, day_pnl_cny=0.0, quote_time=None, now=NOW)
    payload = PortfolioView(store, service=FakeService()).history(2)
    assert len(payload["points"]) == 2


def test_history_days_in_overview(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_snapshot(day=date(2026, 11, 3), market_value_cny=1.0, total_assets_cny=1.0,
                          pnl_cny=0.0, day_pnl_cny=0.0, quote_time=None, now=NOW)
    payload = PortfolioView(store, service=FakeService()).overview()
    assert payload["history_days"] == 1


def test_snapshot_values(tmp_path: Path) -> None:
    data = {"positions": [position()], "total_market_value_cny": 11000.0, "total_cost_cny": 10000.0,
            "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0, "cash_cny": 0.0,
            "total_assets_cny": 11000.0, "quote_time": "2026-11-04 10:00:00"}
    values = make_view(tmp_path, FakeService(data)).snapshot_values()
    assert values == {
        "market_value_cny": 11000.0,
        "total_assets_cny": 11000.0,
        "pnl_cny": 1000.0,
        "day_pnl_cny": 1000.0,
        "quote_time": "2026-11-04 10:00:00",
    }


def test_snapshot_values_failure(tmp_path: Path) -> None:
    service = FakeService()
    service.valuation = lambda: (_ for _ in ()).throw(RuntimeError("bad 601099.SH"))
    assert PortfolioView(HubStore(tmp_path / "hub.db"), service=service).snapshot_values() is None


def test_logs_do_not_contain_holdings(tmp_path: Path, caplog) -> None:
    data = {"positions": [position(code="601099.SH")], "total_market_value_cny": 11000.0,
            "total_cost_cny": 10000.0, "total_pnl_cny": 1000.0, "total_pnl_pct": 10.0,
            "cash_cny": 0.0, "total_assets_cny": 11000.0, "quote_time": None}
    service = FakeService(data, risk_error=RuntimeError("secret 601099.SH"))
    with caplog.at_level(logging.WARNING):
        PortfolioView(HubStore(tmp_path / "hub.db"), service=service).overview()
    assert "601099" not in caplog.text


def test_service_error_not_leaked(tmp_path: Path) -> None:
    service = FakeService()
    service.valuation = lambda: (_ for _ in ()).throw(RuntimeError("601099.SH"))
    try:
        PortfolioView(HubStore(tmp_path / "hub.db"), service=service).overview()
    except RuntimeError as exc:
        assert "601099" in str(exc)
