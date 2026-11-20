from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fake_engine import FLOWS_DEFINITION, FakeEngine, free_port
from market_watch_mcp.client import MarketClient
from market_watch_mcp.config import EngineConfigError, resolve_engine_base
from market_watch_mcp.server import TOOLS
from market_watch_mcp.service import dispatch

PKG = Path(__file__).resolve().parents[1]
TOOL_NAMES = [
    "mkt_get_alerts", "mkt_get_flows", "mkt_get_movers", "mkt_get_overview", "mkt_get_pool",
    "mkt_get_pool_stats", "mkt_get_sector", "mkt_get_sectors", "mkt_get_summary", "mkt_get_themes",
]


@pytest.fixture
def engine():
    fake = FakeEngine()
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def client(engine):
    c = MarketClient(engine.base_url, timeout=1.0)
    try:
        yield c
    finally:
        c.close()


def call(client, name, args=None):
    return dispatch(name, args, client)


# ---------- tool surface ----------

def test_tool_names_exact():
    assert sorted(t.name for t in TOOLS) == TOOL_NAMES


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_descriptions_are_read_only_with_units(tool):
    assert "只读" in tool.description
    assert "_pct" in tool.description and "_yuan" in tool.description and "_ratio" in tool.description
    assert tool.inputSchema["additionalProperties"] is False


def test_flows_description_carries_definition():
    flows = next(t for t in TOOLS if t.name == "mkt_get_flows")
    assert FLOWS_DEFINITION in flows.description


def test_package_has_no_write_methods():
    for path in (PKG / "market_watch_mcp").glob("*.py"):
        text = path.read_text()
        for needle in ("post(", "put(", "delete(", ".request(", "subprocess", "eval(", "exec("):
            assert needle not in text, (path.name, needle)


# ---------- successful pass-through ----------

PASSTHROUGH = [
    ("mkt_get_overview", {}, "/overview", {}),
    ("mkt_get_summary", {}, "/summary", {}),
    ("mkt_get_themes", {}, "/themes", {"kind": "concept", "sort": "change", "limit": "20"}),
    ("mkt_get_themes", {"sort": "amount", "limit": 5}, "/themes", {"kind": "concept", "sort": "amount", "limit": "5"}),
    ("mkt_get_movers", {"kind": "gainers"}, "/movers", {"kind": "gainers", "limit": "10"}),
    ("mkt_get_movers", {"kind": "losers", "limit": 20}, "/movers", {"kind": "losers", "limit": "20"}),
    ("mkt_get_movers", {"kind": "active", "limit": 5}, "/movers", {"kind": "active", "limit": "5"}),
    ("mkt_get_flows", {"kind": "sector_in"}, "/flows", {"kind": "sector_in", "limit": "10"}),
    ("mkt_get_flows", {"kind": "sector_out", "limit": 7}, "/flows", {"kind": "sector_out", "limit": "7"}),
    ("mkt_get_flows", {"kind": "stock_in"}, "/flows", {"kind": "stock_in", "limit": "10"}),
    ("mkt_get_flows", {"kind": "stock_out"}, "/flows", {"kind": "stock_out", "limit": "10"}),
    ("mkt_get_pool", {"kind": "zt"}, "/pool", {"kind": "zt", "limit": "50"}),
    ("mkt_get_pool", {"kind": "zb", "limit": 1}, "/pool", {"kind": "zb", "limit": "1"}),
    ("mkt_get_pool", {"kind": "dt", "date": "2026-11-03", "limit": 200}, "/pool",
     {"kind": "dt", "limit": "200", "date": "2026-11-03"}),
    ("mkt_get_pool_stats", {"view": "ladder"}, "/pool/ladder", {}),
    ("mkt_get_pool_stats", {"view": "ladder", "date": "2026-11-03"}, "/pool/ladder", {"date": "2026-11-03"}),
    ("mkt_get_pool_stats", {"view": "history"}, "/pool/history", {"days": "20"}),
    ("mkt_get_pool_stats", {"view": "history", "days": 30}, "/pool/history", {"days": "30"}),
    ("mkt_get_pool_stats", {"view": "yesterday"}, "/pool/yesterday", {}),
    ("mkt_get_pool_stats", {"view": "by_industry", "date": "2026-11-03"}, "/pool/by-industry", {"date": "2026-11-03"}),
    ("mkt_get_alerts", {}, "/alerts", {"since_id": "0", "limit": "50"}),
    ("mkt_get_alerts", {"since_id": 5, "limit": 200}, "/alerts", {"since_id": "5", "limit": "200"}),
]


@pytest.mark.parametrize("name,args,path,query", PASSTHROUGH)
def test_passthrough(engine, client, name, args, path, query):
    result = call(client, name, args)
    assert result["ok"] is True and result["status"] == "ready"
    assert result["source"] == "market-watch" and result["market"] == "cn"
    assert engine.requests == [("GET", path, query)]
    expected = copy.deepcopy(engine.responses[path])
    expected["untrusted_text"] = True
    assert result["data"] == expected
    assert result["as_of"] == expected.get("as_of", result["as_of"])


def test_as_of_falls_back_to_now(engine, client):
    result = call(client, "mkt_get_pool_stats", {"view": "ladder"})
    assert result["as_of"].endswith("+08:00")


def test_untrusted_text_flag_on_all_tools(engine, client):
    result = call(client, "mkt_get_summary")
    assert result["data"]["untrusted_text"] is True


def test_sectors_default_truncates_to_30(engine, client):
    result = call(client, "mkt_get_sectors")
    assert len(result["data"]["rows"]) == 30
    assert engine.requests == [("GET", "/sectors", {"level": "sw1"})]


@pytest.mark.parametrize("limit", [5, 12, 40])
def test_sectors_limit(engine, client, limit):
    assert len(call(client, "mkt_get_sectors", {"limit": limit})["data"]["rows"]) == limit


def test_sector_detail_only(engine, client):
    result = call(client, "mkt_get_sector", {"code": "BK0433"})
    assert result["status"] == "ready" and "members" not in result["data"]
    assert engine.paths() == ["/sectors/BK0433"]


def test_sector_members_two_requests(engine, client):
    result = call(client, "mkt_get_sector", {"code": "BK0433", "members": True})
    assert engine.paths() == ["/sectors/BK0433", "/sectors/BK0433/members"]
    assert result["status"] == "ready" and result["warnings"] == []
    assert len(result["data"]["members"]["rows"]) == 20
    assert result["data"]["name"] == "食品饮料"


@pytest.mark.parametrize("limit", [5, 100])
def test_sector_member_limit(engine, client, limit):
    result = call(client, "mkt_get_sector", {"code": "BK0433", "members": True, "member_limit": limit})
    assert len(result["data"]["members"]["rows"]) == limit


@pytest.mark.parametrize("failure_kind", ["status", "unreachable_json", "ok_false", "too_large"])
def test_sector_members_failure_keeps_detail(engine, client, failure_kind):
    path = "/sectors/BK0433/members"
    if failure_kind == "status":
        engine.override(path, status=500, body={})
    elif failure_kind == "unreachable_json":
        engine.override(path, raw=b"not json")
    elif failure_kind == "ok_false":
        engine.override(path, body={"ok": False, "error": {"code": "x", "message": "y"}})
    else:
        engine.override(path, raw=b"x" * (600 * 1024))
    result = call(client, "mkt_get_sector", {"code": "BK0433", "members": True})
    assert result["ok"] is True and result["status"] == "ready"
    assert result["warnings"] == ["members_unavailable"]
    assert result["data"]["name"] == "食品饮料"


def test_sector_detail_failure_skips_members(engine, client):
    engine.override("/sectors/BK0433", status=500, body={})
    result = call(client, "mkt_get_sector", {"code": "BK0433", "members": True})
    assert result["ok"] is False and result["error"]["code"] == "engine_error"
    assert engine.paths() == ["/sectors/BK0433"]


# ---------- invalid arguments never reach the engine ----------

INVALID = [
    ("mkt_get_overview", {"x": 1}),
    ("mkt_get_summary", {"x": 1}),
    ("mkt_get_sectors", {"limit": 4}),
    ("mkt_get_sectors", {"limit": 41}),
    ("mkt_get_sectors", {"limit": "10"}),
    ("mkt_get_sectors", {"limit": True}),
    ("mkt_get_sectors", {"limit": 10.5}),
    ("mkt_get_sectors", {"extra": 1}),
    ("mkt_get_sector", {}),
    ("mkt_get_sector", {"code": "bk0433"}),
    ("mkt_get_sector", {"code": "BK043"}),
    ("mkt_get_sector", {"code": "BK04333"}),
    ("mkt_get_sector", {"code": "BK0433/members"}),
    ("mkt_get_sector", {"code": "../health"}),
    ("mkt_get_sector", {"code": 433}),
    ("mkt_get_sector", {"code": "BK0433\n"}),
    ("mkt_get_sector", {"code": "BK0433", "members": "yes"}),
    ("mkt_get_sector", {"code": "BK0433", "members": 1}),
    ("mkt_get_sector", {"code": "BK0433", "members": True, "member_limit": 4}),
    ("mkt_get_sector", {"code": "BK0433", "members": True, "member_limit": 101}),
    ("mkt_get_sector", {"code": "BK0433", "member_limit": "20"}),
    ("mkt_get_themes", {"sort": "rank"}),
    ("mkt_get_themes", {"sort": 1}),
    ("mkt_get_themes", {"limit": 4}),
    ("mkt_get_themes", {"limit": 31}),
    ("mkt_get_movers", {}),
    ("mkt_get_movers", {"kind": "up"}),
    ("mkt_get_movers", {"kind": None}),
    ("mkt_get_movers", {"kind": "gainers", "limit": 4}),
    ("mkt_get_movers", {"kind": "gainers", "limit": 21}),
    ("mkt_get_flows", {}),
    ("mkt_get_flows", {"kind": "northbound"}),
    ("mkt_get_flows", {"kind": "sector_in", "limit": 4}),
    ("mkt_get_flows", {"kind": "sector_in", "limit": 21}),
    ("mkt_get_pool", {}),
    ("mkt_get_pool", {"kind": "zz"}),
    ("mkt_get_pool", {"kind": "zt", "limit": 0}),
    ("mkt_get_pool", {"kind": "zt", "limit": 201}),
    ("mkt_get_pool", {"kind": "zt", "date": "2026/11/04"}),
    ("mkt_get_pool", {"kind": "zt", "date": "20261104"}),
    ("mkt_get_pool", {"kind": "zt", "date": "2026-13-01"}),
    ("mkt_get_pool", {"kind": "zt", "date": "2026-02-30"}),
    ("mkt_get_pool", {"kind": "zt", "date": 20261104}),
    ("mkt_get_pool_stats", {}),
    ("mkt_get_pool_stats", {"view": "daily"}),
    ("mkt_get_pool_stats", {"view": "history", "days": 9}),
    ("mkt_get_pool_stats", {"view": "history", "days": 31}),
    ("mkt_get_pool_stats", {"view": "ladder", "date": "bad"}),
    ("mkt_get_alerts", {"since_id": -1}),
    ("mkt_get_alerts", {"since_id": "1"}),
    ("mkt_get_alerts", {"since_id": 1.5}),
    ("mkt_get_alerts", {"limit": 0}),
    ("mkt_get_alerts", {"limit": 201}),
]


@pytest.mark.parametrize("name,args", INVALID)
def test_invalid_argument_never_reaches_engine(engine, client, name, args):
    result = call(client, name, args)
    assert result["ok"] is False and result["status"] == "error"
    assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_arguments_not_object(engine, client):
    result = dispatch("mkt_get_overview", ["x"], client)  # type: ignore[arg-type]
    assert result["error"]["code"] == "invalid_argument" and engine.requests == []


def test_unknown_tool(engine, client):
    assert call(client, "mkt_nope")["error"]["code"] == "unknown_tool"
    assert engine.requests == []


# ---------- engine errors, empty, warnings ----------

def test_ok_false_passthrough(engine, client):
    err = {"code": "not_trading_day", "message": "非交易日"}
    engine.override("/pool", body={"ok": False, "error": err})
    result = call(client, "mkt_get_pool", {"kind": "zt", "date": "2026-11-01"})
    assert result["ok"] is False and result["status"] == "error" and result["error"] == err


def test_ok_false_passthrough_bad_request(engine, client):
    err = {"code": "bad_request", "message": "x"}
    engine.override("/flows", body={"ok": False, "error": err})
    assert call(client, "mkt_get_flows", {"kind": "stock_in"})["error"] == err


def test_empty_with_reason(engine, client):
    engine.override("/movers", body={"ok": True, "as_of": "2026-11-04T09:00:00+08:00", "kind": "gainers",
                                     "rows": [], "reason": "pre_open"})
    result = call(client, "mkt_get_movers", {"kind": "gainers"})
    assert result["ok"] is True and result["status"] == "empty"
    assert result["data"]["reason"] == "pre_open"


def test_empty_ladder_tiers(engine, client):
    engine.override("/pool/ladder", body={"ok": True, "date": "2026-11-04", "max_streak": None,
                                          "tiers": [], "first_board_count": None, "reason": "no_data"})
    assert call(client, "mkt_get_pool_stats", {"view": "ladder"})["status"] == "empty"


def test_rows_empty_without_reason_is_ready(engine, client):
    engine.override("/alerts", body={"ok": True, "alerts": [], "next_id": 1})
    assert call(client, "mkt_get_alerts")["status"] == "ready"


def test_stale_warning_nested(engine, client):
    body = copy.deepcopy(engine.responses["/overview"])
    body["breadth"]["stale"] = True
    engine.override("/overview", body=body)
    assert "data_stale" in call(client, "mkt_get_overview")["warnings"]


def test_stale_warning_in_row(engine, client):
    body = copy.deepcopy(engine.responses["/sectors"])
    body["rows"][0]["stale"] = True
    engine.override("/sectors", body=body)
    assert "data_stale" in call(client, "mkt_get_sectors")["warnings"]


def test_stale_false_has_no_warning(engine, client):
    assert call(client, "mkt_get_overview")["warnings"] == []


@pytest.mark.parametrize("state", ["pre_open", "lunch", "closed", "holiday"])
def test_market_closed_warning(engine, client, state):
    body = copy.deepcopy(engine.responses["/overview"])
    body["trading_state"] = state
    body["state_note"] = "休市，显示上一交易时段最后值"
    engine.override("/overview", body=body)
    result = call(client, "mkt_get_overview")
    assert "market_closed" in result["warnings"]
    assert result["data"]["state_note"] == "休市，显示上一交易时段最后值"


def test_open_has_no_closed_warning(engine, client):
    assert "market_closed" not in call(client, "mkt_get_overview")["warnings"]


def test_backfill_running_warning(engine, client):
    body = copy.deepcopy(engine.responses["/pool/history"])
    body["backfill"]["running"] = True
    engine.override("/pool/history", body=body)
    assert call(client, "mkt_get_pool_stats", {"view": "history"})["warnings"] == ["backfill_running"]


def test_backfill_idle_no_warning(engine, client):
    assert call(client, "mkt_get_pool_stats", {"view": "history"})["warnings"] == []


def test_multiple_warnings_together(engine, client):
    body = copy.deepcopy(engine.responses["/overview"])
    body["trading_state"] = "closed"
    body["indexes"][0]["stale"] = True
    engine.override("/overview", body=body)
    assert call(client, "mkt_get_overview")["warnings"] == ["data_stale", "market_closed"]


# ---------- transport failures ----------

def test_engine_unreachable():
    c = MarketClient(f"http://127.0.0.1:{free_port()}", timeout=1.0)
    result = dispatch("mkt_get_overview", None, c)
    assert result["ok"] is False and result["error"]["code"] == "engine_unreachable"


def test_engine_timeout(engine):
    engine.override("/overview", delay=1.5)
    c = MarketClient(engine.base_url, timeout=0.4)
    result = dispatch("mkt_get_overview", None, c)
    assert result["error"]["code"] == "engine_unreachable"


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_non_2xx(engine, client, status):
    engine.override("/overview", status=status, body={"ok": False})
    result = call(client, "mkt_get_overview")
    assert result["ok"] is False and result["error"]["code"] == "engine_error"
    assert result["error"]["status_code"] == status


def test_response_too_large(engine, client):
    engine.override("/overview", raw=b"[" + b"1," * (300 * 1024) + b"1]")
    result = call(client, "mkt_get_overview")
    assert result["error"]["code"] == "response_too_large"


def test_response_just_under_limit_ok(engine, client):
    pad = "x" * (500 * 1024)
    engine.override("/summary", body={"ok": True, "as_of": "2026-11-04T10:00:00+08:00", "headlines": [], "pad": pad})
    assert call(client, "mkt_get_summary")["ok"] is True


def test_invalid_json(engine, client):
    engine.override("/overview", raw=b"<html>")
    assert call(client, "mkt_get_overview")["error"]["code"] == "engine_error"


def test_non_object_json(engine, client):
    engine.override("/overview", raw=b"[1,2]")
    assert call(client, "mkt_get_overview")["error"]["code"] == "engine_error"


def test_unreachable_never_raises_protocol_error():
    c = MarketClient(f"http://127.0.0.1:{free_port()}", timeout=0.5)
    for name in TOOL_NAMES:
        args = {"kind": "zt"} if name == "mkt_get_pool" else {}
        if name in ("mkt_get_movers", "mkt_get_flows"):
            args = {"kind": "gainers" if name == "mkt_get_movers" else "stock_in"}
        if name == "mkt_get_sector":
            args = {"code": "BK0433"}
        if name == "mkt_get_pool_stats":
            args = {"view": "ladder"}
        assert dispatch(name, args, c)["error"]["code"] == "engine_unreachable"


# ---------- GET only ----------

def test_only_get_methods_sent(engine, client):
    for name, args, *_ in PASSTHROUGH:
        call(client, name, args)
    call(client, "mkt_get_sector", {"code": "BK0433", "members": True})
    assert engine.requests and {m for m, _, _ in engine.requests} == {"GET"}


def test_redirect_not_followed(engine, client):
    engine.override("/overview", status=302, body={})
    assert call(client, "mkt_get_overview")["error"]["code"] == "engine_error"


# ---------- config ----------

@pytest.mark.parametrize("url", ["http://127.0.0.1:8866", "http://localhost:8866", "http://[::1]:8866/"])
def test_loopback_accepted(url):
    assert resolve_engine_base({"MARKET_WATCH_URL": url}) == url.rstrip("/")


def test_default_url():
    assert resolve_engine_base({}) == "http://127.0.0.1:8866"


@pytest.mark.parametrize("url", [
    "http://example.com:8866", "http://192.168.1.5:8866", "http://0.0.0.0:8866", "ftp://127.0.0.1",
    "http://user:pw@127.0.0.1:8866", "http://127.0.0.1:8866/api", "http://127.0.0.1.evil.com", "http://:8866",
    "http://127.0.0.1:99999",
])
def test_non_loopback_rejected(url):
    with pytest.raises(EngineConfigError):
        resolve_engine_base({"MARKET_WATCH_URL": url})


def test_main_exits_nonzero_for_non_loopback():
    env = {**os.environ, "MARKET_WATCH_URL": "http://example.com:8866", "PYTHONPATH": str(PKG)}
    proc = subprocess.run([sys.executable, "-m", "market_watch_mcp"], env=env, capture_output=True,
                          text=True, timeout=20, cwd=PKG)
    assert proc.returncode != 0 and "loopback" in proc.stderr and proc.stdout == ""


# ---------- real stdio ----------

async def test_stdio_lists_ten_tools_and_calls_one(engine):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "market_watch_mcp"], cwd=str(PKG),
        env={"MARKET_WATCH_URL": engine.base_url, "PATH": os.environ.get("PATH", "")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert sorted(t.name for t in tools.tools) == TOOL_NAMES
            res = await session.call_tool("mkt_get_movers", {"kind": "gainers", "limit": 5})
            payload = json.loads(res.content[0].text)
            assert payload["ok"] is True and payload["source"] == "market-watch"
            res = await session.call_tool("mkt_get_movers", {"kind": "bad"})
            assert json.loads(res.content[0].text)["error"]["code"] == "invalid_argument"
