from __future__ import annotations

from fmp_mcp.client import FmpClient
from fmp_mcp.config import Settings
from fmp_mcp.tools import dispatch
from fake_upstream import FakeFmp

KEY = "TESTKEY_123456"


def test_local_rate_limit_blocks_the_21st_call(fake: FakeFmp) -> None:
    client = FmpClient(
        Settings(base_url=f"http://127.0.0.1:{fake.port}", api_key=KEY, key_source="test"),
        rate_limit_calls=3,
        rate_limit_window=60.0,
    )
    codes = []
    for i in range(5):
        payload = dispatch("fmp_get_profile", {"symbol": f"AA{i}"}, client)
        codes.append(payload.get("error", {}).get("code", "ok"))
    assert codes == ["ok", "ok", "ok", "rate_limited", "rate_limited"]
    assert len(fake.requests) == 3


def test_rate_limit_window_slides(fake: FakeFmp) -> None:
    now = [0.0]
    client = FmpClient(
        Settings(base_url=f"http://127.0.0.1:{fake.port}", api_key=KEY, key_source="test"),
        clock=lambda: now[0],
        rate_limit_calls=1,
        rate_limit_window=60.0,
    )
    assert dispatch("fmp_get_profile", {"symbol": "AA"}, client)["ok"] is True
    assert dispatch("fmp_get_profile", {"symbol": "BB"}, client)["error"]["code"] == "rate_limited"
    now[0] = 61.0
    assert dispatch("fmp_get_profile", {"symbol": "CC"}, client)["ok"] is True
    assert len(fake.requests) == 2


def test_cached_calls_do_not_consume_rate_limit(fake: FakeFmp) -> None:
    client = FmpClient(
        Settings(base_url=f"http://127.0.0.1:{fake.port}", api_key=KEY, key_source="test"),
        rate_limit_calls=1,
        rate_limit_window=60.0,
    )
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert len(fake.requests) == 1
