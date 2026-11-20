from __future__ import annotations

import json

import pytest

from profile_mcp.service import ProfileService
from profile_mcp.server import FIELD_SCHEMA, TOOLS, TOOL_NAMES, create_server, dispatch

EXPECTED_TOOLS = ["profile_clear", "profile_get", "profile_update"]


def test_exactly_three_tools() -> None:
    assert sorted(TOOL_NAMES) == EXPECTED_TOOLS
    assert len(TOOLS) == 3


def test_every_whitelisted_field_has_a_schema_entry() -> None:
    from profile_mcp.fields import FIELD_ORDER

    assert set(FIELD_SCHEMA) == set(FIELD_ORDER)


def test_update_description_restricts_calls_to_the_user() -> None:
    update = next(tool for tool in TOOLS if tool.name == "profile_update")
    description = update.description or ""
    assert "Only call when the user personally describes their preferences" in description
    assert "never infer" in description


def test_dispatch_unknown_tool() -> None:
    payload = dispatch(ProfileService.__new__(ProfileService), "profile_wipe", {})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_tool"


def test_dispatch_routes_all_tools(service: ProfileService) -> None:
    assert dispatch(service, "profile_get", {})["status"] == "empty"
    assert dispatch(service, "profile_update", {"fields": {"language": "zh"}})["ok"] is True
    cleared = dispatch(service, "profile_clear", {"fields": None})
    assert cleared["ok"] is True


async def test_mcp_session_lists_and_calls_tools(service: ProfileService) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_server(service)
    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        assert sorted(tool.name for tool in listed.tools) == EXPECTED_TOOLS

        empty = await session.call_tool("profile_get", {})
        empty_payload = json.loads(empty.content[0].text)
        assert empty_payload["status"] == "empty"

        updated = await session.call_tool("profile_update", {"fields": {"risk_level": "balanced"}})
        updated_payload = json.loads(updated.content[0].text)
        assert updated_payload["ok"] is True
        assert updated_payload["data"]["after"] == {"risk_level": "balanced"}

        rejected = await session.call_tool("profile_update", {"fields": {"nickname": "x"}})
        rejected_payload = json.loads(rejected.content[0].text)
        assert rejected_payload["error"]["code"] == "unknown_field"
