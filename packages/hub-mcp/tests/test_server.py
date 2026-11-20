from __future__ import annotations

import json

import pytest

from hub_mcp.client import HubClient
from hub_mcp.config import resolve_base_url
from hub_mcp.errors import HubConfigError
from hub_mcp.__main__ import main
from hub_mcp.server import TOOL_NAMES, TOOLS, create_server, dispatch
from hub_mcp.service import HubService
from tests.conftest import FakeHub

EXPECTED = [
    "hub_cancel_card",
    "hub_cancel_plan",
    "hub_candidate_stats",
    "hub_get_card",
    "hub_get_review_data",
    "hub_get_signal",
    "hub_list_cards",
    "hub_list_plans",
    "hub_list_settings",
    "hub_list_signals",
    "hub_propose_card",
    "hub_propose_plan",
    "hub_save_review",
    "hub_suggest_setting",
]


def test_exactly_fourteen_tools() -> None:
    assert sorted(TOOL_NAMES) == EXPECTED
    assert len(TOOLS) == 14


def test_no_trading_words_in_tool_names() -> None:
    joined = " ".join(TOOL_NAMES)
    assert not any(word in joined for word in ("order", "buy", "sell", "trade", "confirm", "extend"))


def test_propose_schema_has_no_proposed_by_or_status() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_propose_plan")
    props = tool.inputSchema["properties"]
    assert "proposed_by" not in props
    assert "status" not in props
    assert set(tool.inputSchema["required"]) == {"code", "kind", "condition", "rationale"}


def test_propose_description_says_pending_confirmation() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_propose_plan")
    description = tool.description or ""
    assert 'proposed_by="agent"' in description
    assert "does not take effect until the user confirms" in description
    assert "never places an order" in description


def test_get_signal_description_marks_untrusted() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_get_signal")
    assert "untrusted_text" in (tool.description or "")


def test_cancel_description_limits_scope() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_cancel_plan")
    description = tool.description or ""
    assert "proposed_by=agent" in description
    assert "still in status proposed" in description
    assert "never confirm" in description


def test_dispatch_unknown_tool(service: HubService) -> None:
    payload = dispatch(service, "hub_delete_everything", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_tool"


def test_dispatch_validation_error(service: HubService) -> None:
    payload = dispatch(service, "hub_propose_plan", {"code": "AAPL"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_code"


def test_dispatch_unreachable_returns_hub_unreachable() -> None:
    service = HubService(HubClient("http://127.0.0.1:9", timeout=0.2))
    payload = dispatch(service, "hub_list_signals", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "hub_unreachable"


async def test_mcp_session_lists_and_calls(service: HubService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service)
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert sorted(tool.name for tool in listed.tools) == EXPECTED

        signals = await session.call_tool("hub_list_signals", {})
        signals_payload = json.loads(signals.content[0].text)
        assert signals_payload["ok"] is True
        assert signals_payload["signals"][0]["id"] == 1

        detail = await session.call_tool("hub_get_signal", {"id": 1})
        detail_payload = json.loads(detail.content[0].text)
        assert detail_payload["untrusted_text"] is True
        assert detail_payload["analysis"]["conclusion"]

        proposed = await session.call_tool(
            "hub_propose_plan",
            {
                "code": "600000.SH",
                "kind": "entry",
                "condition": {"type": "price_cross", "direction": "down", "level": 9.5},
                "rationale": "回踩 VWAP 附近分批关注",
            },
        )
        proposed_payload = json.loads(proposed.content[0].text)
        assert proposed_payload["status"] == "proposed"
        assert "等待" in proposed_payload["message"]


async def test_mcp_forged_fields_still_agent_only(service: HubService, fake_hub: FakeHub) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service)
    async with create_connected_server_and_client_session(server) as session:
        await session.call_tool(
            "hub_propose_plan",
            {
                "code": "600000.SH",
                "kind": "entry",
                "condition": {"type": "price_cross", "direction": "down", "level": 9.5},
                "rationale": "回踩 VWAP 附近分批关注",
                "proposed_by": "user",
                "status": "active",
            },
        )
    body = fake_hub.posts()[-1][2]
    assert body["proposed_by"] == "agent"
    assert "status" not in body


def test_main_refuses_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIVES_HUB_URL", "http://example.com:8867")
    assert main() == 2


def test_main_validation_does_not_need_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIVES_HUB_URL", "http://127.0.0.1:8867")
    assert resolve_base_url() == "http://127.0.0.1:8867"
    with pytest.raises(HubConfigError):
        resolve_base_url("http://example.com")
