from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from helpers import StubClient, user
from mcp.shared.memory import create_connected_server_and_client_session
from x_mcp.budget import DailyBudget
from x_mcp.redact import Redactor
from x_mcp.ratelimit import TokenBucket
from x_mcp.server import create_server, load_settings, build_service
from x_mcp.service import XService


def _payload(result) -> dict:
    return json.loads("".join(part.text for part in result.content if getattr(part, "text", None)))


async def test_protocol_lists_five_tools_and_returns_envelopes(local_tmp: Path) -> None:
    settings = load_settings(
        {
            "DSH_FINANCE_SECRETS": str(local_tmp / "none.env"),
            "X_BUDGET_STATE": str(local_tmp / "budget.json"),
        }
    )
    async with create_connected_server_and_client_session(create_server(build_service(settings))) as session:
        names = [tool.name for tool in (await session.list_tools()).tools]
        assert names == [
            "x_search_recent",
            "x_get_post",
            "x_get_user",
            "x_user_posts",
            "x_counts_recent",
        ]
        missing = _payload(await session.call_tool("x_get_user", {"username": "someone"}))
        assert missing["error"]["code"] == "missing_key"
        invalid = _payload(await session.call_tool("x_search_recent", {"query": ""}))
        assert invalid["error"]["code"] == "invalid_argument"
        unknown = _payload(await session.call_tool("x_unknown_tool", {}))
        assert unknown["error"]["code"] == "internal_error"


async def test_protocol_success_path_with_a_stub_upstream(local_tmp: Path) -> None:
    budget = DailyBudget(10, local_tmp / "budget.json", now=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))
    service = XService(
        StubClient(user={"data": user()}),
        redactor=Redactor(None),
        budget=budget,
        limiter=TokenBucket(10, 1.0, clock=lambda: 0.0),
    )
    async with create_connected_server_and_client_session(create_server(service)) as session:
        payload = _payload(await session.call_tool("x_get_user", {"username": "@testuser"}))
    assert payload["ok"] is True
    assert payload["source"] == "x"
    assert payload["data"]["user"]["username"] == "testuser"
    assert payload["data"]["budget"] == {"used_today": 1, "remaining": 9}
