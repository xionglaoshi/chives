from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cn_research_mcp import server
from helpers import load, make_service

NAMES = [
    "cn_get_consensus",
    "cn_get_ratings",
    "cn_get_research_reports",
    "cn_get_valuation",
    "cn_get_industry_valuation",
    "cn_get_index_valuation",
    "cn_get_earnings_events",
    "cn_get_disclosure_schedule",
    "cn_get_stock_news",
    "cn_get_flash_news",
    "cn_get_econ_calendar",
    "cn_get_suspensions",
    "cn_get_irm_qa",
    "cn_get_cb_list",
    "cn_get_cb_quote",
    "cn_get_index_bars",
    "cn_get_index_constituents",
    "cn_get_holders",
    "cn_get_business_segments",
]
NO_REQUIRED = (
    "cn_get_industry_valuation",
    "cn_get_index_valuation",
    "cn_get_flash_news",
    "cn_get_econ_calendar",
    "cn_get_suspensions",
    "cn_get_cb_list",
    "cn_get_index_bars",
    "cn_get_index_constituents",
)


def test_exactly_nineteen_tools_in_order():
    assert [t.name for t in server.TOOLS] == NAMES
    assert all(t.inputSchema["type"] == "object" and t.inputSchema["additionalProperties"] is False for t in server.TOOLS)


def test_schema_bounds():
    schemas = {t.name: t.inputSchema for t in server.TOOLS}
    assert schemas["cn_get_ratings"]["properties"]["limit"]["maximum"] == 50
    assert schemas["cn_get_valuation"]["properties"]["years"]["maximum"] == 8
    assert schemas["cn_get_earnings_events"]["properties"]["kind"]["enum"] == ["forecast", "express", "report"]
    assert schemas["cn_get_earnings_events"]["required"] == ["period", "kind"]
    assert schemas["cn_get_consensus"]["required"] == ["code"]
    assert schemas["cn_get_index_valuation"]["required"] == []
    assert schemas["cn_get_stock_news"]["properties"]["limit"]["maximum"] == 20
    assert schemas["cn_get_flash_news"]["properties"]["limit"]["maximum"] == 50
    assert schemas["cn_get_flash_news"]["properties"]["source"]["enum"] == ["cls", "em"]
    assert schemas["cn_get_flash_news"]["properties"]["keyword"]["maxLength"] == 20
    assert schemas["cn_get_irm_qa"]["properties"]["limit"]["maximum"] == 30
    assert schemas["cn_get_cb_list"]["properties"]["limit"]["maximum"] == 500
    assert schemas["cn_get_cb_quote"]["properties"]["bond_codes"]["maxItems"] == 20
    assert schemas["cn_get_index_bars"]["properties"]["limit"]["maximum"] == 750
    assert schemas["cn_get_index_constituents"]["properties"]["limit"]["maximum"] == 1000
    assert schemas["cn_get_holders"]["properties"]["view"]["enum"] == ["top10_float", "funds"]
    assert schemas["cn_get_business_segments"]["properties"]["by"]["enum"] == ["product", "region", "industry"]


@pytest.mark.parametrize(
    "name,args",
    [(n, {}) for n in NAMES if n not in NO_REQUIRED]
    + [("cn_get_earnings_events", {"period": "2026-09-30"}), ("cn_get_earnings_events", {"kind": "report"})],
)
def test_missing_arguments_are_envelopes(name, args):
    svc, fake = make_service()
    out = server.dispatch(name, args, svc)
    assert out["ok"] is False and out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_unknown_argument_rejected():
    svc, fake = make_service()
    out = server.dispatch("cn_get_consensus", {"code": "600519", "bogus": 1}, svc)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_unknown_tool():
    assert server.dispatch("cn_nope", {})["error"]["code"] == "unknown_tool"


def test_non_object_arguments():
    assert server.dispatch("cn_get_consensus", ["x"])["error"]["code"] == "invalid_argument"


def test_dispatch_defaults_pass_through():
    svc, fake = make_service(institute_recommend=load("recommend"))
    out = server.dispatch("cn_get_ratings", {"code": "600519"}, svc)
    assert len(out["data"]["ratings"]) == 20
    out = server.dispatch("cn_get_ratings", {"code": "600519", "limit": 2}, svc)
    assert len(out["data"]["ratings"]) == 2


def test_dispatch_routes_all_tools_with_fakes():
    svc, fake = make_service(
        profit_forecast_em=load("em_forecast"),
        profit_forecast_ths=load("ths"),
        institute_recommend=load("recommend"),
        research_report=load("reports"),
        stock_value=load("value"),
        industry_pe=load("industry"),
        index_pe=load("idx300"),
        yjyg=load("yjyg"),
        yjkb=load("yjkb"),
        yjbb=load("yjbb"),
        yysj=load("yysj"),
        stock_news=load("news_em"),
        flash_cls=load("flash_cls"),
        flash_em=load("flash_em"),
        econ_calendar=load("econ_calendar"),
        suspensions=load("suspensions"),
        irm_qa=load("irm"),
        cb_list=load("cb_list"),
        cb_spot=load("cb_spot"),
        index_bars=load("index_bars"),
        index_constituents=load("index_cons"),
        holders_top10=load("holders_top10"),
        fund_holders=load("fund_holders"),
        business_segments=load("business_segments"),
    )
    calls = {
        "cn_get_consensus": {"code": "600519"},
        "cn_get_ratings": {"code": "600519"},
        "cn_get_research_reports": {"code": "600519"},
        "cn_get_valuation": {"code": "600519"},
        "cn_get_industry_valuation": {"date": "2026-11-13"},
        "cn_get_index_valuation": {},
        "cn_get_earnings_events": {"period": "2026-09-30", "kind": "forecast"},
        "cn_get_disclosure_schedule": {"period": "2026-09-30"},
        "cn_get_stock_news": {"code": "600519"},
        "cn_get_flash_news": {"source": "cls"},
        "cn_get_econ_calendar": {"date": "2026-11-16"},
        "cn_get_suspensions": {"date": "2026-11-16"},
        "cn_get_irm_qa": {"code": "002594"},
        "cn_get_cb_list": {},
        "cn_get_cb_quote": {"bond_codes": ["113643"]},
        "cn_get_index_bars": {"index": "沪深300"},
        "cn_get_index_constituents": {"index": "000300"},
        "cn_get_holders": {"code": "600519"},
        "cn_get_business_segments": {"code": "600519"},
    }
    for name, args in calls.items():
        out = server.dispatch(name, args, svc)
        assert out["ok"] is True and out["status"] == "ready", name
        assert out["market"] == "cn" and out["as_of"]
        json.dumps(out, allow_nan=False)


def test_stdio_lists_exactly_nineteen_tools_and_rejects_bad_args():
    root = Path(__file__).resolve().parents[1]

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "cn_research_mcp"], cwd=str(root))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("cn_get_consensus", {"code": "920418"})
                bad = await session.call_tool("cn_get_valuation", {"code": "600519", "years": 99})
                return [t.name for t in tools.tools], result, bad

    names, result, bad = asyncio.run(asyncio.wait_for(run(), 60))
    assert names == NAMES
    payload = json.loads(result.content[0].text)
    assert payload["error"]["code"] == "unsupported_market" and not result.isError
    assert json.loads(bad.content[0].text)["error"]["code"] == "invalid_argument"
