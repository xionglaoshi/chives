from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cn_watch_mcp.client import WatchClient
from cn_watch_mcp.config import EngineConfigError, resolve_engine_base
from cn_watch_mcp.server import TOOLS
from cn_watch_mcp.service import dispatch
from fake_engine import FakeEngine, free_port

PKG = Path(__file__).resolve().parents[1]
ALLOWED_TOOLS = [
    "watch_add_symbol",
    "watch_get_alerts",
    "watch_get_health",
    "watch_get_rule_history",
    "watch_get_rules",
    "watch_get_state",
    "watch_get_watchlist",
    "watch_remove_rule",
    "watch_remove_symbol",
    "watch_revert_rule",
    "watch_upsert_rule",
]
READ_ONLY_TOOLS = [
    "watch_get_alerts",
    "watch_get_health",
    "watch_get_rule_history",
    "watch_get_rules",
    "watch_get_state",
    "watch_get_watchlist",
]
WATCHLIST_WRITE_TOOLS = ["watch_add_symbol", "watch_remove_symbol"]
RULE_WRITE_TOOLS = ["watch_upsert_rule", "watch_remove_rule", "watch_revert_rule"]


@pytest.fixture
def engine():
    fake = FakeEngine()
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def client(engine):
    watcher = WatchClient(engine.base_url, timeout=1.0)
    try:
        yield watcher
    finally:
        watcher.close()


def test_tool_catalog_is_six_read_only_and_five_write_tools() -> None:
    assert sorted(tool.name for tool in TOOLS) == ALLOWED_TOOLS
    by_name = {tool.name: tool.description or "" for tool in TOOLS}
    for name in READ_ONLY_TOOLS:
        assert "read-only" in by_name[name].lower()
    for name in WATCHLIST_WRITE_TOOLS:
        assert "只增删自选股，不改规则，不下单；调用前须已得到用户明确同意" in by_name[name]
    for name in RULE_WRITE_TOOLS:
        assert "只影响盯盘告警，不涉及下单" in by_name[name]
        assert "改前→改后" in by_name[name]
        assert "可撤销" in by_name[name]


def test_health_passes_through_without_warnings(engine, client) -> None:
    result = dispatch("watch_get_health", {}, client)
    assert result["ok"] is True
    assert result["source"] == "cn-watch"
    assert result["market"] == "cn"
    assert result["status"] == "ready"
    assert result["data"]["health"] == "ok"
    assert result["warnings"] == []


def test_state_passes_through_and_uses_engine_updated_at(engine, client) -> None:
    result = dispatch("watch_get_state", {}, client)
    assert result["data"]["quotes"]["002553.SZ"]["price"] == 15.47
    assert result["as_of"] == "2026-11-03T10:00:00+08:00"


@pytest.mark.parametrize(
    ("mode", "warning"),
    [("stale", "data_stale"), ("closed", "market_closed"), ("degraded", "engine_degraded")],
)
def test_warnings_keep_status_ready(mode, warning) -> None:
    fake = FakeEngine(mode)
    watcher = WatchClient(fake.base_url)
    try:
        result = dispatch("watch_get_health", {}, watcher)
    finally:
        watcher.close()
        fake.stop()
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert warning in result["warnings"]


def test_alerts_pagination_count_and_untrusted_marker(engine, client) -> None:
    result = dispatch("watch_get_alerts", {"after_id": 2, "limit": 2}, client)
    assert [row["id"] for row in result["data"]["alerts"]] == [3, 4]
    assert result["data"]["count"] == 2
    assert result["data"]["untrusted_text"] is True
    assert engine.requests[-1] == "GET /alerts?after_id=2&limit=2"


def test_alerts_defaults(engine, client) -> None:
    result = dispatch("watch_get_alerts", {}, client)
    assert result["data"]["count"] == 5
    assert engine.requests[-1] == "GET /alerts?after_id=0&limit=50"


def test_rules_passes_through_with_symbols_and_source(engine, client) -> None:
    result = dispatch("watch_get_rules", {}, client)
    assert result["data"]["count"] == 2
    assert result["data"]["rules"][0]["symbols"] == ["002553.SZ"]
    assert result["data"]["rules"][1]["symbols"] is None
    assert result["data"]["rules"][0]["source"] == "config"


@pytest.mark.parametrize(
    "arguments",
    [
        {"after_id": -1},
        {"after_id": "abc"},
        {"after_id": True},
        {"after_id": 1.5},
        {"limit": 0},
        {"limit": 501},
        {"limit": 1.5},
        {"limit": "10"},
    ],
)
def test_invalid_alerts_arguments_never_reach_the_engine(engine, client, arguments) -> None:
    result = dispatch("watch_get_alerts", arguments, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_invalid_arguments_shape_is_rejected_before_the_engine(engine, client) -> None:
    result = dispatch("watch_get_health", ["not", "an", "object"], client)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_http_500_becomes_engine_error() -> None:
    fake = FakeEngine("error500")
    watcher = WatchClient(fake.base_url)
    try:
        result = dispatch("watch_get_state", {}, watcher)
    finally:
        watcher.close()
        fake.stop()
    assert result["ok"] is False
    assert result["error"]["code"] == "engine_error"
    assert result["error"]["status_code"] == 500


def test_nothing_listening_is_engine_unreachable() -> None:
    watcher = WatchClient(f"http://127.0.0.1:{free_port()}", timeout=0.5)
    try:
        result = dispatch("watch_get_state", {}, watcher)
    finally:
        watcher.close()
    assert result["ok"] is False
    assert result["error"]["code"] == "engine_unreachable"


def test_hanging_engine_times_out_as_unreachable() -> None:
    fake = FakeEngine("hang")
    watcher = WatchClient(fake.base_url, timeout=0.3)
    try:
        started = time.monotonic()
        result = dispatch("watch_get_state", {}, watcher)
        elapsed = time.monotonic() - started
    finally:
        watcher.close()
        fake.stop()
    assert result["ok"] is False
    assert result["error"]["code"] == "engine_unreachable"
    assert elapsed < 2.0


def test_only_get_requests_are_sent(engine, client) -> None:
    dispatch("watch_get_health", {}, client)
    dispatch("watch_get_state", {}, client)
    dispatch("watch_get_alerts", {"after_id": 0, "limit": 1}, client)
    dispatch("watch_get_rules", {}, client)
    assert engine.requests
    assert all(line.startswith("GET ") for line in engine.requests)


def test_engine_base_accepts_loopback_only() -> None:
    assert resolve_engine_base({}) == "http://127.0.0.1:8865"
    for url in ("http://127.0.0.1:9999", "http://localhost:8865", "http://[::1]:8865", "https://LOCALHOST:8865"):
        assert resolve_engine_base({"WATCH_ENGINE": url})
    for url in (
        "http://10.1.2.3:8865",
        "http://example.com:8865",
        "http://0.0.0.0:8865",
        "ftp://127.0.0.1",
        "http://[::1",
    ):
        with pytest.raises(EngineConfigError):
            resolve_engine_base({"WATCH_ENGINE": url})


def test_non_loopback_engine_refuses_to_start() -> None:
    env = {**os.environ, "WATCH_ENGINE": "http://10.1.2.3:8865"}
    result = subprocess.run(
        [sys.executable, "-m", "cn_watch_mcp"],
        cwd=PKG,
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "loopback" in result.stderr


def test_stdio_server_lists_tools_and_calls_health(engine) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cn_watch_mcp"],
        cwd=str(PKG),
        env={**os.environ, "WATCH_ENGINE": engine.base_url},
    )

    async def check() -> None:
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert sorted(tool.name for tool in tools.tools) == ALLOWED_TOOLS
                result = await session.call_tool("watch_get_health", {})
                payload = json.loads(result.content[0].text)
                assert payload["ok"] is True
                assert payload["data"]["health"] == "ok"

    import asyncio

    asyncio.run(check())


@pytest.mark.parametrize(
    ("mode", "want", "absent"),
    [
        ("after_hours", ["outside_session"], ["market_closed"]),
        ("pre_open", ["outside_session"], ["market_closed"]),
        ("closed", ["market_closed", "outside_session"], []),
        ("ok", [], ["outside_session", "market_closed"]),
        ("legacy", [], ["outside_session", "market_closed"]),
    ],
)
def test_session_warnings(mode, want, absent) -> None:
    fake = FakeEngine(mode)
    watcher = WatchClient(fake.base_url)
    try:
        result = dispatch("watch_get_health", {}, watcher)
    finally:
        watcher.close()
        fake.stop()
    warnings = result["warnings"]
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert all(item in warnings for item in want)
    assert not any(item in warnings for item in absent)


def test_state_tool_carries_the_same_session_warning() -> None:
    fake = FakeEngine("after_hours")
    watcher = WatchClient(fake.base_url)
    try:
        result = dispatch("watch_get_state", {}, watcher)
    finally:
        watcher.close()
        fake.stop()
    assert result["data"]["session"] == "after_hours"
    assert "outside_session" in result["warnings"]


def test_health_passes_session_and_last_rule_eval_through() -> None:
    fake = FakeEngine()
    watcher = WatchClient(fake.base_url)
    try:
        result = dispatch("watch_get_health", {}, watcher)
    finally:
        watcher.close()
        fake.stop()
    assert result["data"]["session"] == "open"
    assert result["data"]["last_rule_eval_ts"] == "2026-11-03T09:59:57+08:00"


def test_tool_descriptions_document_session_fields() -> None:
    by_name = {tool.name: tool.description or "" for tool in TOOLS}
    for name in ("watch_get_health", "watch_get_state"):
        assert "session" in by_name[name]
        assert "last_rule_eval_ts" in by_name[name]


def test_watchlist_tool_passes_through(engine, client) -> None:
    result = dispatch("watch_get_watchlist", {}, client)
    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["limit"] == 10
    assert result["data"]["untrusted_text"] is True
    assert result["data"]["watchlist"][0] == {
        "code": "002553.SZ",
        "name": "南方精工",
        "source": "config",
    }
    assert engine.requests[-1] == "GET /watchlist"


def test_add_symbol_posts_and_returns_engine_result(engine, client) -> None:
    result = dispatch("watch_add_symbol", {"code": "601099"}, client)
    assert result["ok"] is True
    assert result["data"]["status"] == "added"
    assert result["data"]["code"] == "601099"
    assert result["data"]["name"] == "太平洋"
    assert result["data"]["source"] == "runtime"
    assert result["data"]["count"] == 2
    assert engine.requests[-1] == 'POST /watchlist/add {"code": "601099"}'


def test_duplicate_add_is_reported_as_already_present(engine, client) -> None:
    dispatch("watch_add_symbol", {"code": "601099"}, client)
    result = dispatch("watch_add_symbol", {"code": "601099"}, client)
    assert result["ok"] is True
    assert result["data"]["status"] == "already_present"
    assert engine.requests[-1] == 'POST /watchlist/add {"code": "601099"}'


def test_remove_symbol_posts_and_returns_engine_result(engine, client) -> None:
    dispatch("watch_add_symbol", {"code": "601099"}, client)
    result = dispatch("watch_remove_symbol", {"code": "601099"}, client)
    assert result["ok"] is True
    assert result["data"]["status"] == "removed"
    assert result["data"]["name"] == "太平洋"
    assert result["data"]["count"] == 1
    assert engine.requests[-1] == 'POST /watchlist/remove {"code": "601099"}'


def test_protected_symbol_error_code_passes_through(engine, client) -> None:
    result = dispatch("watch_remove_symbol", {"code": "002553.SZ"}, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "protected_symbol"
    assert result["error"]["status_code"] == 409
    assert "配置文件" in result["error"]["message"]


def test_unsupported_market_error_code_passes_through(engine, client) -> None:
    engine.post_error = (
        400,
        {
            "ok": False,
            "code": "unsupported_market",
            "message": "引擎暂不支持北交所",
            "error": "引擎暂不支持北交所",
        },
    )
    result = dispatch("watch_add_symbol", {"code": "920001"}, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported_market"
    assert "北交所" in result["error"]["message"]


def test_unsupported_instrument_error_code_passes_through(engine, client) -> None:
    engine.post_error = (
        400,
        {
            "ok": False,
            "code": "unsupported_instrument",
            "message": "引擎暂不支持指数代码",
            "error": "引擎暂不支持指数代码",
        },
    )
    result = dispatch("watch_add_symbol", {"code": "399975"}, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported_instrument"
    assert "指数" in result["error"]["message"]


def test_unknown_engine_error_code_is_not_rewritten(engine, client) -> None:
    engine.post_error = (
        400,
        {"ok": False, "code": "some_new_code", "message": "引擎返回的新错误"},
    )
    result = dispatch("watch_add_symbol", {"code": "601099"}, client)
    assert result["error"]["code"] == "some_new_code"
    assert result["error"]["message"] == "引擎返回的新错误"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"code": ""},
        {"code": "   "},
        {"code": True},
        {"code": 1.5},
        {"code": None},
        {"code": ["601099"]},
    ],
)
def test_invalid_code_arguments_never_reach_the_engine(engine, client, arguments) -> None:
    result = dispatch("watch_add_symbol", arguments, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_missing_engine_for_add_is_unreachable() -> None:
    watcher = WatchClient(f"http://127.0.0.1:{free_port()}", timeout=0.5)
    try:
        result = dispatch("watch_add_symbol", {"code": "601099"}, watcher)
    finally:
        watcher.close()
    assert result["ok"] is False
    assert result["error"]["code"] == "engine_unreachable"


def test_write_tools_only_target_the_watchlist_endpoints(engine, client) -> None:
    dispatch("watch_get_watchlist", {}, client)
    dispatch("watch_add_symbol", {"code": "601099"}, client)
    dispatch("watch_remove_symbol", {"code": "601099"}, client)
    writes = [line for line in engine.requests if line.startswith("POST ")]
    assert writes
    assert all(
        line.startswith("POST /watchlist/add ") or line.startswith("POST /watchlist/remove ")
        for line in writes
    )
    assert not any("/rules" in line or "order" in line.lower() for line in engine.requests)


def test_upsert_rule_posts_rule_and_returns_before_after(engine, client) -> None:
    rule = {
        "id": "pct_up_5",
        "type": "pct_change",
        "direction": "up",
        "threshold_pct": 5.0,
        "symbols": ["002553.SZ"],
    }
    result = dispatch("watch_upsert_rule", {"rule": rule}, client)
    assert result["ok"] is True
    assert result["data"]["status"] == "created"
    assert result["data"]["source"] == "runtime"
    assert result["data"]["before"] is None
    assert result["data"]["after"]["id"] == "pct_up_5"
    assert result["data"]["after"]["symbols"] == ["002553.SZ"]
    assert engine.actors[-1] == "agent"
    assert engine.requests[-1] == (
        'POST /rules/upsert {"id": "pct_up_5", "type": "pct_change", '
        '"direction": "up", "threshold_pct": 5.0, "symbols": ["002553.SZ"]}'
    )


def test_upsert_existing_config_rule_returns_override(engine, client) -> None:
    rule = {
        "id": "pct_up_3",
        "type": "pct_change",
        "direction": "up",
        "threshold_pct": 2.5,
    }
    result = dispatch("watch_upsert_rule", {"rule": rule}, client)
    assert result["ok"] is True
    assert result["data"]["status"] == "override"
    assert result["data"]["source"] == "override"
    assert result["data"]["before"]["threshold_pct"] == 3.0
    assert result["data"]["after"]["threshold_pct"] == 2.5


@pytest.mark.parametrize("arguments", [{}, {"rule": "not-an-object"}, {"rule": []}])
def test_invalid_rule_argument_never_reaches_the_engine(engine, client, arguments) -> None:
    result = dispatch("watch_upsert_rule", arguments, client)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_remove_and_revert_rule(engine, client) -> None:
    removed = dispatch("watch_remove_rule", {"id": "pct_up_3"}, client)
    assert removed["ok"] is True
    assert removed["data"]["status"] == "disabled"
    assert removed["data"]["after"]["disabled"] is True
    assert engine.actors[-1] == "agent"

    reverted = dispatch("watch_revert_rule", {"id": "pct_up_3"}, client)
    assert reverted["ok"] is True
    assert reverted["data"]["status"] == "reverted"
    assert reverted["data"]["after"] is None
    assert engine.actors[-1] == "agent"


def test_rule_history_passes_through_and_validates_limit(engine, client) -> None:
    dispatch(
        "watch_upsert_rule",
        {"rule": {"id": "r_new", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}},
        client,
    )
    result = dispatch("watch_get_rule_history", {"limit": 10}, client)
    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["history"][0]["action"] == "upsert"
    assert result["data"]["history"][0]["actor"] == "agent"
    assert engine.requests[-1] == "GET /rules/history?limit=10"
    assert engine.actors[-1] == "agent"

    for bad in (0, 501, 1.5, "10", True):
        rejected = dispatch("watch_get_rule_history", {"limit": bad}, client)
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "invalid_argument"


def test_rule_errors_pass_through_with_codes(engine, client) -> None:
    engine.post_error = (
        400,
        {
            "ok": False,
            "code": "out_of_bounds",
            "message": "threshold_pct 必须在 [0.1, 25] 之间",
            "error": "out of range",
            "allowed": {"min": 0.1, "max": 25},
        },
    )
    result = dispatch(
        "watch_upsert_rule",
        {"rule": {"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 99}},
        client,
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "out_of_bounds"
    assert "允许范围" in result["error"]["message"]


def test_missing_rule_id_never_reaches_the_engine(engine, client) -> None:
    for name in ("watch_remove_rule", "watch_revert_rule"):
        result = dispatch(name, {}, client)
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_argument"
    assert engine.requests == []


def test_rule_write_tools_only_target_rule_endpoints(engine, client) -> None:
    dispatch(
        "watch_upsert_rule",
        {"rule": {"id": "r_new", "type": "pct_change", "direction": "up", "threshold_pct": 1.0}},
        client,
    )
    dispatch("watch_remove_rule", {"id": "r_new"}, client)
    dispatch("watch_revert_rule", {"id": "r_new"}, client)
    dispatch("watch_get_rule_history", {}, client)
    assert all(
        line.startswith(("POST /rules/", "GET /rules/history"))
        for line in engine.requests
    )
    assert not any("order" in line.lower() or "config" in line.lower() for line in engine.requests)
