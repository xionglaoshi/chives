from __future__ import annotations

import pytest

from hub_mcp.__main__ import main
from hub_mcp.client import HubClient
from hub_mcp.config import resolve_profile, validate_profile
from hub_mcp.errors import HubConfigError
from hub_mcp.server import (
    READONLY_TOOL_NAMES,
    TOOLS,
    TOOLS_BY_PROFILE,
    create_server,
    dispatch,
    tools_for_profile,
)
from hub_mcp.service import HubService
from tests.support_v2 import FakeHubV2

AGENT_TOOLS = [
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
READONLY_TOOLS = [
    "hub_candidate_stats",
    "hub_get_card",
    "hub_get_review_data",
    "hub_get_signal",
    "hub_list_cards",
    "hub_list_plans",
    "hub_list_settings",
    "hub_list_signals",
]
WRITE_TOOLS = sorted(set(AGENT_TOOLS) - set(READONLY_TOOLS))


def test_agent_profile_has_exactly_the_agreed_tools() -> None:
    assert sorted(tool.name for tool in TOOLS_BY_PROFILE["agent"]) == AGENT_TOOLS
    assert len(TOOLS) == 14


def test_readonly_profile_keeps_only_reads() -> None:
    assert sorted(tool.name for tool in TOOLS_BY_PROFILE["readonly"]) == READONLY_TOOLS
    assert READONLY_TOOL_NAMES == frozenset(READONLY_TOOLS)


def test_readonly_is_a_strict_subset_of_agent() -> None:
    assert set(READONLY_TOOLS) < set(AGENT_TOOLS)
    assert len(WRITE_TOOLS) == 6


def test_no_banned_tools_exist() -> None:
    joined = " ".join(tool.name for tool in TOOLS)
    for word in (
        "confirm",
        "tighten",
        "set_state",
        "action",
        "judgement",
        "judgment",
        "trigger",
        "order",
        "buy",
        "sell",
        "trade",
        "adopt",
    ):
        assert word not in joined


def test_no_adopt_set_clear_dismiss_tools() -> None:
    names = {tool.name for tool in TOOLS}
    for name in ("hub_adopt_setting", "hub_set_setting", "hub_clear_setting", "hub_dismiss_settings"):
        assert name not in names


def test_propose_card_schema_has_no_control_fields() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_propose_card")
    props = tool.inputSchema["properties"]
    assert "proposed_by" not in props
    assert "status" not in props
    assert set(tool.inputSchema["required"]) == {"code", "thesis", "risk"}


def test_propose_plan_schema_still_has_no_control_fields() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_propose_plan")
    props = tool.inputSchema["properties"]
    assert "proposed_by" not in props
    assert "status" not in props


def test_save_review_schema_requires_date_kind_env() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_save_review")
    assert set(tool.inputSchema["required"]) == {"date", "kind", "env"}
    assert "proposed_by" not in tool.inputSchema["properties"]


def test_suggest_setting_schema_requires_basis() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "hub_suggest_setting")
    assert set(tool.inputSchema["required"]) == {"key", "value", "basis"}


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_readonly_profile_blocks_writes(service_v2: HubService, fake_hub_v2: FakeHubV2, name: str) -> None:
    payload = dispatch(service_v2, name, {}, profile="readonly")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "tool_not_available"
    assert fake_hub_v2.log == []


def test_readonly_profile_allows_reads(service_v2: HubService) -> None:
    assert dispatch(service_v2, "hub_get_review_data", {}, profile="readonly")["ok"] is True


def test_agent_profile_allows_writes(service_v2: HubService) -> None:
    payload = dispatch(service_v2, "hub_get_card", {"id": 20}, profile="agent")
    assert payload["ok"] is True


def test_tools_for_profile_unknown() -> None:
    with pytest.raises(ValueError):
        tools_for_profile("admin")


def test_create_server_unknown_profile(service_v2: HubService) -> None:
    with pytest.raises(ValueError):
        create_server(service_v2, "admin")


@pytest.mark.parametrize("raw", ["", "  ", "admin", "Agent ", "readonly2"])
def test_validate_profile_rejects_unknown(raw: str) -> None:
    if raw.strip().lower() == "agent":
        assert validate_profile(raw) == "agent"
        return
    with pytest.raises(HubConfigError):
        validate_profile(raw)


def test_resolve_profile_defaults_to_core(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUB_MCP_PROFILE", raising=False)
    assert resolve_profile() == "core"


CORE_TOOLS = ["hub_cancel_plan", "hub_get_signal", "hub_list_plans", "hub_list_signals", "hub_propose_plan"]


def test_core_profile_has_only_signal_and_plan_tools() -> None:
    assert sorted(tool.name for tool in TOOLS_BY_PROFILE["core"]) == CORE_TOOLS
    assert sorted(tool.name for tool in TOOLS_BY_PROFILE["core_readonly"]) == [
        "hub_get_signal",
        "hub_list_plans",
        "hub_list_signals",
    ]


@pytest.mark.parametrize("name", sorted(set(AGENT_TOOLS) - set(CORE_TOOLS)))
def test_core_profile_blocks_review_card_and_setting_tools(service_v2: HubService, name: str) -> None:
    payload = dispatch(service_v2, name, {}, profile="core")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "tool_not_available"


def test_resolve_profile_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_MCP_PROFILE", "readonly")
    assert resolve_profile() == "readonly"


def test_main_refuses_unknown_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIVES_HUB_URL", "http://127.0.0.1:8867")
    monkeypatch.setenv("HUB_MCP_PROFILE", "superuser")
    assert main() == 2


async def test_mcp_session_agent_lists_fourteen(service_v2: HubService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service_v2, "agent")
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert sorted(tool.name for tool in listed.tools) == AGENT_TOOLS


async def test_mcp_session_readonly_lists_eight_and_refuses_write(service_v2: HubService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service_v2, "readonly")
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert sorted(tool.name for tool in listed.tools) == READONLY_TOOLS
        result = await session.call_tool("hub_propose_card", {})
        assert result.content
        assert '"tool_not_available"' in result.content[0].text


def test_unreachable_still_reports_hub_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    service = HubService(HubClient("http://127.0.0.1:9", timeout=0.2))
    payload = dispatch(service, "hub_list_cards", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "hub_unreachable"


def test_support_fake_hub_fixture_is_wired(fake_hub_v2: FakeHubV2) -> None:
    assert fake_hub_v2.url.startswith("http://127.0.0.1:")
