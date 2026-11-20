from __future__ import annotations

import os

import pytest

from fmp_mcp.client import FmpClient
from fmp_mcp.config import load_settings
from fmp_mcp.tools import dispatch

pytestmark = pytest.mark.network


def test_real_quote() -> None:
    if not os.environ.get("FMP_API_KEY") and not load_settings().api_key:
        pytest.skip("FMP_API_KEY is not configured")
    client = FmpClient(load_settings(), timeout=10.0)
    payload = dispatch("fmp_get_quote", {"symbol": "AAPL"}, client)
    assert payload["source"] == "fmp"
    assert payload["status"] in {"ready", "empty"}
    if payload["status"] == "error":
        assert payload["error"]["code"] in {"plan_restricted", "rate_limited"}
