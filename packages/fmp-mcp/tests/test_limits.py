from __future__ import annotations

from fmp_mcp.client import FmpClient
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp


def test_explicit_limit_is_enforced_when_upstream_ignores_it(client: FmpClient, fake: FakeFmp) -> None:
    payload = dispatch("fmp_get_analyst_grades", {"symbol": "MANY", "limit": 3}, client)
    data = payload["data"]
    assert data["count"] == 3 and len(data["rows"]) == 3
    assert data["available"] == 8 and data["truncated"] is True
    assert any("截断" in note for note in data["notes"])


def test_default_limit_is_enforced_when_limit_is_omitted(client: FmpClient, fake: FakeFmp) -> None:
    data = dispatch("fmp_get_analyst_grades", {"symbol": "MANY"}, client)["data"]
    assert data["count"] == 5 and len(data["rows"]) == 5
    assert data["available"] == 8 and data["truncated"] is True


def test_insider_trades_limit_is_enforced_too(client: FmpClient, fake: FakeFmp) -> None:
    data = dispatch("fmp_get_insider_trades", {"symbol": "MANY", "limit": 2}, client)["data"]
    assert data["count"] == 2 and len(data["rows"]) == 2
    assert data["available"] == 8 and data["truncated"] is True


def test_tools_without_limit_are_capped_at_200_rows(client: FmpClient, fake: FakeFmp) -> None:
    data = dispatch(
        "fmp_get_historical_prices",
        {"symbol": "MANY", "from_date": "2025-01-01", "to_date": "2026-01-01"},
        client,
    )["data"]
    assert data["count"] == 200 and len(data["rows"]) == 200
    assert data["available"] == 250 and data["truncated"] is True


def test_no_truncation_is_disclosed_when_rows_fit(client: FmpClient, fake: FakeFmp) -> None:
    data = dispatch("fmp_get_profile", {"symbol": "AAPL"}, client)["data"]
    assert data["count"] == 1 and data["available"] == 1 and data["truncated"] is False
