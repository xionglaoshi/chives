from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fake_upstream import FakeFmp

PKG = Path(__file__).resolve().parents[1]
KEY = "TESTKEY_123456"


def _env(port: int, *, key: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "FMP_TEST_MODE": "1",
            "FMP_BASE_URL": f"http://127.0.0.1:{port}",
            "DSH_FINANCE_SECRETS": "/nonexistent/none.env",
        }
    )
    if key is None:
        env.pop("FMP_API_KEY", None)
    else:
        env["FMP_API_KEY"] = key
    return env


async def _session(env: dict[str, str]):
    params = StdioServerParameters(command=sys.executable, args=["-m", "fmp_mcp"], cwd=str(PKG), env=env)
    return stdio_client(params)


@pytest.mark.asyncio
async def test_stdio_server_lists_seventeen_tools_and_calls_one(fake: FakeFmp) -> None:
    async with await _session(_env(fake.port, key=KEY)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert sorted(tool.name for tool in tools.tools) == sorted(
                [
                    "fmp_search_symbol",
                    "fmp_search_name",
                    "fmp_get_quote",
                    "fmp_get_profile",
                    "fmp_get_income_statement",
                    "fmp_get_balance_sheet",
                    "fmp_get_cash_flow",
                    "fmp_get_ratios",
                    "fmp_get_key_metrics",
                    "fmp_get_analyst_estimates",
                    "fmp_get_price_target",
                    "fmp_get_analyst_grades",
                    "fmp_get_insider_trades",
                    "fmp_get_earnings_calendar",
                    "fmp_get_historical_prices",
                    "fmp_get_shares_float",
                    "fmp_get_stock_peers",
                ]
            )
            result = await session.call_tool("fmp_get_quote", {"symbol": "AAPL"})
            payload = json.loads("".join(part.text for part in result.content))
            assert payload["ok"] is True and payload["status"] == "ready"
            assert payload["data"]["rows"][0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_stdio_server_without_key_lists_tools_and_returns_missing_key(fake: FakeFmp) -> None:
    async with await _session(_env(fake.port, key=None)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 17
            result = await session.call_tool("fmp_get_quote", {"symbol": "AAPL"})
            payload = json.loads("".join(part.text for part in result.content))
            assert payload["ok"] is False and payload["error"]["code"] == "missing_key"
    assert fake.requests == []


@pytest.mark.parametrize(
    "env",
    [
        {"FMP_BASE_URL": "http://127.0.0.1:9", "FMP_API_KEY": "x"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "http://10.1.2.3:80", "FMP_API_KEY": "x"},
        {"FMP_TEST_MODE": "1", "FMP_BASE_URL": "https://financialmodelingprep.com.evil.com", "FMP_API_KEY": "x"},
    ],
)
def test_bad_base_url_refuses_to_start(env: dict) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "fmp_mcp"],
        cwd=str(PKG),
        env={**os.environ, **env},
        input="",
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode != 0
    assert "FMP_BASE_URL" in proc.stderr
