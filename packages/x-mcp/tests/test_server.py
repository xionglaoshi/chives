from __future__ import annotations

from pathlib import Path

import pytest

from x_mcp.config import ConfigError
from x_mcp.server import TOOLS, Settings, build_service, load_settings


def test_exactly_five_read_only_tools() -> None:
    names = [tool.name for tool in TOOLS]
    assert names == [
        "x_search_recent",
        "x_get_post",
        "x_get_user",
        "x_user_posts",
        "x_counts_recent",
    ]
    assert all(tool.inputSchema["additionalProperties"] is False for tool in TOOLS)


def test_no_write_or_account_tools_are_exposed() -> None:
    names = " ".join(tool.name.lower() for tool in TOOLS)
    for forbidden in ("post_tweet", "create", "delete", "like", "follow", "dm", "message", "upload"):
        assert forbidden not in names


def test_tool_schemas_match_the_documented_bounds() -> None:
    by_name = {tool.name: tool for tool in TOOLS}
    search = by_name["x_search_recent"].inputSchema
    assert search["required"] == ["query"]
    assert search["properties"]["query"]["maxLength"] == 512
    assert search["properties"]["max_results"]["minimum"] == 10
    assert search["properties"]["max_results"]["maximum"] == 100
    assert search["properties"]["max_results"]["default"] == 10

    post = by_name["x_get_post"].inputSchema
    assert post["required"] == ["tweet_id"]
    assert post["properties"]["tweet_id"]["pattern"] == r"^[0-9]{1,25}$"

    account = by_name["x_get_user"].inputSchema
    assert account["properties"]["username"]["pattern"] == r"^@?[A-Za-z0-9_]{1,15}$"

    posts = by_name["x_user_posts"].inputSchema
    assert posts["properties"]["max_results"]["minimum"] == 5
    assert posts["properties"]["max_results"]["maximum"] == 100

    counts = by_name["x_counts_recent"].inputSchema
    assert counts["properties"]["granularity"]["enum"] == ["minute", "hour", "day"]


def test_missing_key_still_builds_a_working_service(local_tmp: Path) -> None:
    settings = load_settings(
        {
            "DSH_FINANCE_SECRETS": str(local_tmp / "none.env"),
            "X_BUDGET_STATE": str(local_tmp / "budget.json"),
        }
    )
    assert settings.api_key is None
    assert settings.base_url == "https://api.x.com"
    service = build_service(settings)
    assert service.get_user({"username": "someone"})["error"]["code"] == "missing_key"


def test_key_from_dotenv_is_used(local_tmp: Path) -> None:
    env_file = local_tmp / "s.env"
    env_file.write_text("X_BEARER_TOKEN=file-token\n", encoding="utf-8")
    settings = load_settings(
        {
            "DSH_FINANCE_SECRETS": str(env_file),
            "X_BUDGET_STATE": str(local_tmp / "budget.json"),
        }
    )
    assert settings.api_key == "file-token"
    assert settings.base_url == "https://api.x.com"


def test_budget_settings_are_loaded(local_tmp: Path) -> None:
    state = local_tmp / "budget.json"
    settings = load_settings(
        {
            "DSH_FINANCE_SECRETS": str(local_tmp / "none.env"),
            "X_BUDGET_STATE": str(state),
            "X_DAILY_POST_BUDGET": "12",
            "X_RATE_CAPACITY": "4",
            "X_RATE_REFILL_SECONDS": "2.5",
        }
    )
    assert settings.daily_budget == 12
    assert settings.state_path == state
    assert settings.rate_capacity == 4
    assert settings.rate_refill_seconds == 2.5


def test_base_url_test_mode_is_honoured(local_tmp: Path) -> None:
    settings = load_settings(
        {
            "DSH_FINANCE_SECRETS": str(local_tmp / "none.env"),
            "X_TEST_MODE": "1",
            "X_BASE_URL": "http://127.0.0.1:8865",
            "X_BUDGET_STATE": str(local_tmp / "budget.json"),
        }
    )
    assert settings.base_url == "http://127.0.0.1:8865"


def test_unsafe_base_url_is_rejected(local_tmp: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings({"X_BASE_URL": "http://127.0.0.1:8865"})


def test_settings_are_immutable(local_tmp: Path) -> None:
    settings = Settings("https://api.x.com", None, 500, local_tmp / "b.json", 30, 30.0)
    with pytest.raises(Exception) as info:
        settings.api_key = "changed"  # type: ignore[misc]
    assert info.value.__class__.__name__ == "FrozenInstanceError"
