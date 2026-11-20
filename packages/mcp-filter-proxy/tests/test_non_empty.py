from __future__ import annotations

import asyncio

import pytest

from mcp_filter_proxy.config import ConfigError, parse_config
from support import make_config, proxy_session, result_json

CALL_TIMEOUT = 30
HINT = "upstream returned nothing; it may be rate limited, retry later"
TOOLS = [
    "json_tool",
    "text_tool",
    "empty_text_tool",
    "blank_text_tool",
    "empty_results_tool",
    "empty_list_tool",
    "flaky_tool",
    "allowed_empty_tool",
]

CHECK = {
    "tool": "*",
    "type": "non_empty_result",
    "hint": HINT,
    "allow_empty": ["allowed_empty_tool"],
}


async def call(session, name: str, arguments: dict | None = None):
    return await asyncio.wait_for(session.call_tool(name, arguments or {}), CALL_TIMEOUT)


def config(tmp_path, *, ttl: int = 60, check: dict | None = None):
    return make_config(
        tmp_path,
        allow=TOOLS,
        checks=[CHECK if check is None else check],
        cache={"ttl_seconds": {"default": ttl}},
        rate={"max_calls_per_minute": 120},
    )


@pytest.mark.parametrize(
    "name",
    ["empty_text_tool", "blank_text_tool", "empty_results_tool", "empty_list_tool"],
)
async def test_empty_success_becomes_empty_result_error(tmp_path, name):
    async with proxy_session(config(tmp_path)) as session:
        result = await call(session, f"p_{name}")

    assert result.isError is True
    payload = result_json(result)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "empty_result"
    assert payload["error"]["tool"] == name
    assert payload["error"]["message"]
    assert payload["error"]["hint"] == HINT
    assert "meta" not in payload


async def test_non_empty_json_and_text_pass_through(tmp_path):
    async with proxy_session(config(tmp_path)) as session:
        json_result = await call(session, "p_json_tool", {"x": 3})
        text_result = await call(session, "p_text_tool")

    assert json_result.isError is False
    assert result_json(json_result)["x"] == 3
    assert text_result.isError is False
    assert "plain text result" in "".join(b.text for b in text_result.content)


async def test_allow_empty_exempts_only_listed_tools(tmp_path):
    async with proxy_session(config(tmp_path)) as session:
        allowed = await call(session, "p_allowed_empty_tool")
        refused = await call(session, "p_empty_results_tool")

    assert allowed.isError is False
    assert result_json(allowed)["results"] == []
    assert refused.isError is True
    assert result_json(refused)["error"]["code"] == "empty_result"


async def test_empty_result_is_not_cached(tmp_path):
    async with proxy_session(config(tmp_path, ttl=60)) as session:
        first = await call(session, "p_flaky_tool")
        second = await call(session, "p_flaky_tool")
        third = await call(session, "p_flaky_tool")

    assert first.isError is True
    assert result_json(first)["error"]["code"] == "empty_result"
    second_payload = result_json(second)
    assert second.isError is False
    assert second_payload["results"] == [{"v": 2}]
    assert second_payload["meta"]["cache"] == "miss"
    third_payload = result_json(third)
    assert third_payload["results"] == [{"v": 2}]
    assert third_payload["meta"]["cache"] == "hit"


async def test_check_scoped_to_one_tool_leaves_others_alone(tmp_path):
    check = {"tool": "empty_results_tool", "type": "non_empty_result"}
    async with proxy_session(config(tmp_path, check=check)) as session:
        refused = await call(session, "p_empty_results_tool")
        untouched = await call(session, "p_empty_text_tool")

    assert refused.isError is True
    assert result_json(refused)["error"]["code"] == "empty_result"
    assert "hint" not in result_json(refused)["error"]
    assert untouched.isError is False


def base_check(**overrides):
    check = {"tool": "*", "type": "non_empty_result"}
    check.update(overrides)
    return check


def config_data(check: dict) -> dict:
    return {
        "name": "proxy",
        "upstream": {"command": "/bin/true"},
        "allow": ["json_tool", "allowed_empty_tool"],
        "checks": [check],
    }


def test_wildcard_check_and_allow_empty_are_parsed():
    cfg = parse_config(
        config_data(base_check(hint=HINT, allow_empty=["allowed_empty_tool"])),
        environ={},
    )
    check = cfg.checks[0]
    assert check.tool == "*"
    assert check.type == "non_empty_result"
    assert check.start_arg is None
    assert check.date_field is None
    assert check.allow_empty == ("allowed_empty_tool",)
    assert cfg.checks_for("json_tool") == (check,)
    assert cfg.checks_for("allowed_empty_tool") == (check,)


@pytest.mark.parametrize(
    "check",
    [
        base_check(hint=""),
        base_check(hint=5),
        base_check(hint="x" * 301),
        base_check(hint=None),
        base_check(allow_empty="allowed_empty_tool"),
        base_check(allow_empty=[]),
        base_check(allow_empty=["json_tool"], tool="json_tool"),
        base_check(allow_empty=["not_in_allow"]),
        base_check(tool="not_in_allow"),
        base_check(allow_empty=[5]),
    ],
)
def test_invalid_non_empty_config_is_rejected(check):
    with pytest.raises(ConfigError):
        parse_config(config_data(check), environ={})


def test_allow_empty_is_rejected_on_other_check_types():
    with pytest.raises(ConfigError):
        parse_config(
            {
                "name": "proxy",
                "upstream": {"command": "/bin/true"},
                "allow": ["json_tool", "allowed_empty_tool"],
                "checks": [
                    {
                        "tool": "json_tool",
                        "type": "bars_within_requested_dates",
                        "start_arg": "start_date",
                        "end_arg": "end_date",
                        "date_field": "trade_date",
                        "allow_empty": ["allowed_empty_tool"],
                    }
                ],
            },
            environ={},
        )
