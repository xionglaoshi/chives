from __future__ import annotations

import pytest

from fmp_mcp.client import FmpClient
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp

CASES = [
    ("fmp_search_symbol", {"query": "AAPL"}, "/stable/search-symbol"),
    ("fmp_search_name", {"query": "apple"}, "/stable/search-name"),
    ("fmp_get_quote", {"symbol": "aapl"}, "/stable/quote"),
    ("fmp_get_profile", {"symbol": "AAPL"}, "/stable/profile"),
    ("fmp_get_income_statement", {"symbol": "AAPL", "period": "quarter", "limit": 1}, "/stable/income-statement"),
    ("fmp_get_balance_sheet", {"symbol": "AAPL"}, "/stable/balance-sheet-statement"),
    ("fmp_get_cash_flow", {"symbol": "AAPL"}, "/stable/cash-flow-statement"),
    ("fmp_get_ratios", {"symbol": "AAPL"}, "/stable/ratios"),
    ("fmp_get_key_metrics", {"symbol": "AAPL"}, "/stable/key-metrics"),
    ("fmp_get_analyst_estimates", {"symbol": "AAPL", "period": "annual"}, "/stable/analyst-estimates"),
    ("fmp_get_price_target", {"symbol": "AAPL"}, "/stable/price-target-summary"),
    ("fmp_get_analyst_grades", {"symbol": "AAPL"}, "/stable/grades"),
    ("fmp_get_insider_trades", {"symbol": "AAPL"}, "/stable/insider-trading/search"),
    ("fmp_get_earnings_calendar", {"from_date": "2026-10-26", "to_date": "2026-11-09"}, "/stable/earnings-calendar"),
    ("fmp_get_historical_prices", {"symbol": "AAPL", "from_date": "2026-10-01", "to_date": "2026-10-31"}, "/stable/historical-price-eod/full"),
    ("fmp_get_shares_float", {"symbol": "AAPL"}, "/stable/shares-float"),
    ("fmp_get_stock_peers", {"symbol": "AAPL"}, "/stable/stock-peers"),
]


@pytest.mark.parametrize(("name", "args", "path"), CASES, ids=[c[0] for c in CASES])
def test_each_tool_uses_its_upstream_path_and_returns_ready(
    client: FmpClient, fake: FakeFmp, name: str, args: dict, path: str
) -> None:
    payload = dispatch(name, args, client)
    assert payload["ok"] is True
    assert payload["source"] == "fmp"
    assert payload["market"] == "us"
    assert payload["status"] == "ready"
    data = payload["data"]
    assert data["endpoint"] == name
    assert data["count"] >= 1
    assert isinstance(data["rows"], list)
    assert isinstance(data["notes"], list) and data["notes"]
    request = fake.requests[-1]
    assert request["path"] == path
    assert request["query"]["apikey"] == "TESTKEY_123456"


def test_all_seventeen_tools_are_covered() -> None:
    from fmp_mcp.tools import TOOLS

    assert {c[0] for c in CASES} == {t.name for t in TOOLS} and len(TOOLS) == 17


def test_symbols_are_upper_cased(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_get_quote", {"symbol": "aapl"}, client)
    assert fake.requests[-1]["query"]["symbol"] == "AAPL"


def test_search_sends_query_and_limit(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_search_symbol", {"query": "AAPL", "limit": 3}, client)
    query = fake.requests[-1]["query"]
    assert query["query"] == "AAPL" and query["limit"] == "3"


def test_search_name_returns_company_matches(client: FmpClient, fake: FakeFmp) -> None:
    payload = dispatch("fmp_search_name", {"query": "apple"}, client)
    assert fake.requests[-1]["path"] == "/stable/search-name"
    assert payload["data"]["count"] == 2
    assert payload["data"]["rows"][1]["symbol"] == "APLE"


def test_statement_rows_and_defaults_are_passed_through(client: FmpClient, fake: FakeFmp) -> None:
    payload = dispatch("fmp_get_income_statement", {"symbol": "AAPL", "limit": 2}, client)
    rows = payload["data"]["rows"]
    assert len(rows) == 2
    assert rows[0]["revenue"] == 416161000000
    assert rows[1]["netIncome"] == 93736000000
    query = fake.requests[-1]["query"]
    assert query["period"] == "annual" and query["limit"] == "2"


def test_earnings_calendar_maps_from_date_to_upstream_from_to(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_get_earnings_calendar", {"from_date": "2026-10-26", "to_date": "2026-11-09"}, client)
    query = fake.requests[-1]["query"]
    assert query["from"] == "2026-10-26" and query["to"] == "2026-11-09"


def test_historical_prices_map_dates_and_symbol(client: FmpClient, fake: FakeFmp) -> None:
    dispatch(
        "fmp_get_historical_prices",
        {"symbol": "msft", "from_date": "2026-10-01", "to_date": "2026-10-31"},
        client,
    )
    query = fake.requests[-1]["query"]
    assert query["symbol"] == "MSFT"
    assert query["from"] == "2026-10-01" and query["to"] == "2026-10-31"


def test_statement_notes_cover_currency_period_and_fiscal_year(client: FmpClient) -> None:
    for name in (
        "fmp_get_income_statement",
        "fmp_get_balance_sheet",
        "fmp_get_cash_flow",
    ):
        notes = " ".join(dispatch(name, {"symbol": "AAPL"}, client)["data"]["notes"])
        assert "reportedCurrency" in notes
        assert "period" in notes
        assert "fiscalYear" in notes
        assert "date" in notes


def test_historical_notes_say_adjustment_unconfirmed(client: FmpClient) -> None:
    notes = " ".join(
        dispatch(
            "fmp_get_historical_prices",
            {"symbol": "AAPL", "from_date": "2026-10-01", "to_date": "2026-10-31"},
            client,
        )["data"]["notes"]
    )
    assert "复权" in notes and "未确认" in notes


def test_empty_upstream_is_status_empty(client: FmpClient) -> None:
    payload = dispatch("fmp_get_quote", {"symbol": "ZZZZ"}, client)
    assert payload["ok"] is True and payload["status"] == "empty"
    assert payload["data"]["count"] == 0 and payload["data"]["rows"] == []
    assert "notes" in payload["data"]
