from __future__ import annotations

import json
import urllib.request

import pytest

from cn_market_gateway.daemon import GatewayDaemon
from cn_market_gateway.mcp_server import fetch_tools, forward_call
from fakes import FakeSources, make_service, tencent_fixture_rows

EXPECTED_TOOLS = {
    "market_quote",
    "market_bars",
    "market_intraday",
    "market_global",
    "market_overview",
    "market_movers",
    "market_limit_pool",
    "market_sectors",
    "market_fund_flow",
    "market_trading_activity",
    "market_northbound",
    "company_search",
    "company_financials",
    "company_valuation",
    "company_consensus",
    "company_reports",
    "company_earnings",
    "company_holders",
    "company_profile",
    "news",
    "company_announcements",
    "convertible_bonds",
}


def _daemon() -> tuple[GatewayDaemon, FakeSources]:
    sources = FakeSources()
    sources.quote_tencent = tencent_fixture_rows()
    service = make_service(sources)
    return GatewayDaemon(service, port=0).start(), sources


def _get(port: int, path: str) -> dict:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        f"http://127.0.0.1:{port}{path}", timeout=5
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def test_daemon_serves_call_tools_and_health():
    daemon, _ = _daemon()
    try:
        payload = forward_call("market_quote", {"codes": ["600000"]}, port=daemon.port)
        assert payload["status"] == "ok"
        tools = _get(daemon.port, "/v1/tools")["tools"]
        assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
        health = _get(daemon.port, "/health")
        assert health["status"] == "ok"
        assert health["upstreams"]
    finally:
        daemon.stop()


def test_daemon_refuses_non_loopback_binding():
    with pytest.raises(ValueError):
        GatewayDaemon(port=0, host="0.0.0.0")


def test_daemon_unknown_tool_returns_unavailable_envelope():
    daemon, _ = _daemon()
    try:
        payload = forward_call("unknown_tool", {}, port=daemon.port)
        assert payload["status"] == "unavailable"
        assert "未知工具" in payload["message"]
    finally:
        daemon.stop()


def test_forwarding_layer_when_daemon_is_down():
    payload = forward_call("market_quote", {"codes": ["600000"]}, port=1, timeout=0.2)
    assert payload["status"] == "unavailable"
    assert payload["message"] == "数据服务没有启动"


def test_fetch_tools_falls_back_to_static_list_when_daemon_is_down():
    tools = fetch_tools(port=1, timeout=0.2)
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS


def test_forwarder_reports_a_slow_daemon_as_slow_not_as_down():
    import socket
    import threading

    from cn_market_gateway.mcp_server import TIMEOUT_MESSAGE, forward_call

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    held = []
    threading.Thread(target=lambda: held.append(listener.accept()), daemon=True).start()
    try:
        payload = forward_call("market_quote", {"codes": ["600519"]}, port=port, timeout=0.3)
    finally:
        listener.close()
    assert payload["status"] == "unavailable"
    assert payload["message"] == TIMEOUT_MESSAGE


def test_warm_up_calls_each_slow_tool_and_survives_errors():
    from cn_market_gateway import daemon as daemon_module

    calls = []

    class Service:
        def call(self, tool, args):
            calls.append((tool, args))
            raise RuntimeError("upstream down")

    daemon_module.warm_up(Service())  # must not raise
    assert [tool for tool, _ in calls] == [tool for tool, _ in daemon_module.WARM_UP_CALLS]
