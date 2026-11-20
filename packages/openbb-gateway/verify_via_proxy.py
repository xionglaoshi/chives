"""Developer smoke test: call the OpenBB gateway through mcp-filter-proxy.

Run with the proxy venv (it owns the MCP 1.x client):

    packages/mcp-filter-proxy/.venv/bin/python packages/openbb-gateway/verify_via_proxy.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PROXY_PY = ROOT / "packages/mcp-filter-proxy/.venv/bin/python"
CFG = ROOT / "gateways/openbb/config.yaml"

CALLS = [
    ("price_history", "ob_equity_price_historical", {"provider": "nasdaq", "symbol": "AAPL", "start_date": "2026-09-01"}),
    ("income_statement", "ob_equity_fundamental_income", {"provider": "sec", "symbol": "AAPL", "period": "annual", "limit": 1}),
    ("company_profile", "ob_equity_profile", {"provider": "nasdaq", "symbol": "AAPL"}),
    ("quote", "ob_equity_price_quote", {"provider": "nasdaq", "symbol": "AAPL"}),
    ("balance", "ob_equity_fundamental_balance", {"provider": "sec", "symbol": "AAPL", "period": "annual", "limit": 1}),
    ("ratios", "ob_equity_fundamental_ratios", {"provider": "nasdaq", "symbol": "AAPL", "limit": 1}),
    ("insider", "ob_equity_ownership_insider_trading", {"provider": "sec", "symbol": "AAPL"}),
    ("earnings_calendar", "ob_yfinance_company_calendar", {"symbol": "AAPL"}),
    ("company_profile_cache_hit", "ob_equity_profile", {"provider": "nasdaq", "symbol": "AAPL"}),
    ("treasury", "ob_federal_reserve_treasury_rates", {"provider": "federal_reserve"}),
    ("options", "ob_nasdaq_options_chains", {"symbol": "AAPL", "expiration": "2026-11-20"}),
]


async def main() -> None:
    sp = StdioServerParameters(
        command=str(PROXY_PY),
        args=["-m", "mcp_filter_proxy", "--config", str(CFG)],
        cwd=str(ROOT / "packages/mcp-filter-proxy"),
        env=dict(os.environ),
    )
    async with stdio_client(sp, errlog=open(os.devnull, "w")) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 180)
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            print("TOOLS", len(tools))
            for label, tool, args in CALLS:
                res = await asyncio.wait_for(s.call_tool(tool, args), 180)
                text = "".join(getattr(b, "text", "") for b in res.content)
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = None
                meta = obj.get("meta") if isinstance(obj, dict) else None
                rows = obj.get("results") if isinstance(obj, dict) else None
                print(label, "ERR" if res.isError else "ok", "rows=", len(rows) if isinstance(rows, list) else "n/a",
                      "meta=", meta, "preview=", text[:160].replace("\n", " "))
                await asyncio.sleep(2.5)


if __name__ == "__main__":
    asyncio.run(main())
