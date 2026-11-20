from __future__ import annotations

from fmp_mcp.client import FmpClient
from fmp_mcp.config import Settings
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp


def test_quote_is_cached_for_two_calls(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert len(fake.requests) == 1


def test_non_quote_is_cached_too(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_get_profile", {"symbol": "AAPL"}, client)
    dispatch("fmp_get_profile", {"symbol": "AAPL"}, client)
    assert len(fake.requests) == 1


def test_empty_results_are_not_cached(client: FmpClient, fake: FakeFmp) -> None:
    first = dispatch("fmp_get_quote", {"symbol": "ZZZZ"}, client)
    second = dispatch("fmp_get_quote", {"symbol": "ZZZZ"}, client)
    assert first["status"] == "empty" and second["status"] == "empty"
    assert len(fake.requests) == 2


def test_errors_are_not_cached(client: FmpClient, fake: FakeFmp) -> None:
    assert dispatch("fmp_get_quote", {"symbol": "LIMIT"}, client)["error"]["code"] == "rate_limited"
    assert dispatch("fmp_get_quote", {"symbol": "LIMIT"}, client)["error"]["code"] == "rate_limited"
    assert len(fake.requests) == 2


def test_cache_expires_after_ttl(fake: FakeFmp) -> None:
    now = [1000.0]
    client = FmpClient(
        Settings(base_url=f"http://127.0.0.1:{fake.port}", api_key="TESTKEY_123456", key_source="test"),
        clock=lambda: now[0],
        quote_ttl=15.0,
    )
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    now[0] += 14.9
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert len(fake.requests) == 1
    now[0] += 0.2
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert len(fake.requests) == 2


def test_different_tools_with_same_params_do_not_share_cache(client: FmpClient, fake: FakeFmp) -> None:
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    dispatch("fmp_get_profile", {"symbol": "AAPL"}, client)
    assert [r["path"] for r in fake.requests] == ["/stable/quote", "/stable/profile"]
