from __future__ import annotations

import pytest

from fmp_mcp.client import FmpClient
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp

INVALID = [
    ("fmp_get_quote", {"symbol": "AA PL"}),
    ("fmp_get_quote", {"symbol": ""}),
    ("fmp_get_quote", {"symbol": "X" * 30}),
    ("fmp_get_quote", {"symbol": "A;B"}),
    ("fmp_get_quote", {}),
    ("fmp_search_symbol", {"query": "apple", "limit": 51}),
    ("fmp_search_symbol", {"query": "apple", "limit": 0}),
    ("fmp_search_symbol", {"query": ""}),
    ("fmp_search_name", {"query": "apple", "limit": 51}),
    ("fmp_search_name", {"query": ""}),
    ("fmp_get_income_statement", {"symbol": "AAPL", "period": "monthly"}),
    ("fmp_get_income_statement", {"symbol": "AAPL", "limit": 0}),
    ("fmp_get_income_statement", {"symbol": "AAPL", "limit": 41}),
    ("fmp_get_income_statement", {"symbol": "AAPL", "limit": "5"}),
    ("fmp_get_earnings_calendar", {"from_date": "2026-13-01", "to_date": "2026-11-09"}),
    ("fmp_get_earnings_calendar", {"from_date": "2026-11-09", "to_date": "2026-10-01"}),
    ("fmp_get_earnings_calendar", {"from_date": "2026-01-01", "to_date": "2026-06-30"}),
    ("fmp_get_earnings_calendar", {"from_date": "2026-1-1", "to_date": "2026-02-01"}),
    ("fmp_get_historical_prices", {"symbol": "AAPL", "from_date": "2015-01-01", "to_date": "2026-01-01"}),
    ("fmp_get_historical_prices", {"symbol": "AAPL", "from_date": "2026-02-01", "to_date": "2026-01-01"}),
]


@pytest.mark.parametrize(("name", "args"), INVALID, ids=[f"{n}-{i}" for i, (n, _) in enumerate(INVALID)])
def test_invalid_arguments_never_reach_upstream(
    client: FmpClient, fake: FakeFmp, name: str, args: dict
) -> None:
    payload = dispatch(name, args, client)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_argument"
    assert fake.requests == []


def test_unknown_tool_is_an_envelope_not_a_protocol_error(client: FmpClient, fake: FakeFmp) -> None:
    payload = dispatch("fmp_get_everything", {}, client)
    assert payload["ok"] is False and payload["error"]["code"] == "unknown_tool"
    assert fake.requests == []


def test_invalid_arguments_is_not_cached_or_rate_limited(client: FmpClient, fake: FakeFmp) -> None:
    for _ in range(30):
        assert dispatch("fmp_get_quote", {"symbol": "bad symbol"}, client)["error"]["code"] == "invalid_argument"
    assert fake.requests == []
