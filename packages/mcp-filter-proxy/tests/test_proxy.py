from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from fake_upstream import TOOLS
from support import PKG_ROOT, make_config, proxy_session, result_json, result_text

CALL_TIMEOUT = 30


async def call(session, name: str, arguments: dict | None = None):
    return await asyncio.wait_for(session.call_tool(name, arguments or {}), CALL_TIMEOUT)


async def test_tool_list_is_allowlisted_prefixed_and_schemas_pass_through(tmp_path):
    config = make_config(
        tmp_path, allow=["json_tool", "text_tool", "missing_tool"], prefix="cn_"
    )
    async with proxy_session(config) as session:
        tools = (await session.list_tools()).tools

    assert [tool.name for tool in tools] == ["cn_json_tool", "cn_text_tool"]
    by_name = {tool.name: tool for tool in tools}
    for upstream in TOOLS:
        exposed = by_name.get(f"cn_{upstream.name}")
        if exposed is None:
            continue
        assert exposed.description == upstream.description
        assert exposed.inputSchema == upstream.inputSchema


async def test_disallowed_tools_are_refused_and_never_forwarded(tmp_path):
    config = make_config(tmp_path, allow=["counter_tool"], cache={"ttl_seconds": {"default": 60}})
    async with proxy_session(config) as session:
        for blocked in ("counter_tool", "extra_tool", "cn_extra_tool", "does_not_exist"):
            refusal = await call(session, blocked)
            assert refusal.isError, blocked
            payload = result_json(refusal)
            assert payload["error"]["code"] == "tool_not_allowed"

        allowed = await call(session, "p_counter_tool", {"key": "k"})
        assert allowed.isError is False
        assert result_json(allowed)["count"] == 1


async def test_json_result_gets_meta_and_plain_text_is_untouched(tmp_path):
    config = make_config(
        tmp_path,
        allow=["json_tool", "text_tool", "multi_block_tool"],
        cache={"ttl_seconds": {"default": 60}},
    )
    async with proxy_session(config) as session:
        first = await call(session, "p_json_tool", {"x": 3})
        payload = result_json(first)
        assert payload["ok"] is True
        assert payload["x"] == 3
        assert payload["nested"] == {"b": 2, "a": 1}
        assert payload["meta"]["cache"] == "miss"
        assert isinstance(payload["meta"]["latency_ms"], int)
        assert payload["meta"]["proxy"] == "mcp-filter-proxy"

        second = await call(session, "p_json_tool", {"x": 3})
        assert result_json(second)["meta"]["cache"] == "hit"

        plain = await call(session, "p_text_tool")
        assert result_text(plain) == "plain text result"

        multi = await call(session, "p_multi_block_tool")
        assert [block.text for block in multi.content] == ['{"first": 1}', "second block"]


async def test_existing_meta_is_moved_to_proxy_meta(tmp_path):
    config = make_config(tmp_path, allow=["meta_tool"])
    async with proxy_session(config) as session:
        payload = result_json(await call(session, "p_meta_tool"))

    assert payload["meta"] == {"origin": "upstream"}
    assert payload["_proxy_meta"]["cache"] == "miss"
    assert payload["_proxy_meta"]["proxy"] == "mcp-filter-proxy"


async def test_cache_key_normalizes_argument_order(tmp_path):
    config = make_config(tmp_path, allow=["counter_tool"])
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_counter_tool", {"key": "a", "extra": 1}))
        assert first["count"] == 1
        assert first["meta"]["cache"] == "miss"

        reordered = result_json(await call(session, "p_counter_tool", {"extra": 1, "key": "a"}))
        assert reordered["count"] == 1
        assert reordered["meta"]["cache"] == "hit"

        different = result_json(await call(session, "p_counter_tool", {"key": "b"}))
        assert different["count"] == 2
        assert different["meta"]["cache"] == "miss"


async def test_zero_ttl_disables_cache(tmp_path):
    config = make_config(
        tmp_path, allow=["counter_tool"], cache={"ttl_seconds": {"default": 0}}
    )
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_counter_tool", {"key": "a"}))
        second = result_json(await call(session, "p_counter_tool", {"key": "a"}))

    assert first["count"] == 1
    assert second["count"] == 2
    assert first["meta"]["cache"] == "miss"
    assert second["meta"]["cache"] == "miss"


async def test_only_successful_results_are_cached(tmp_path):
    config = make_config(
        tmp_path,
        allow=["error_tool", "ok_false_tool"],
        cache={"ttl_seconds": {"default": 60}},
    )
    async with proxy_session(config) as session:
        error_one = await call(session, "p_error_tool")
        error_two = await call(session, "p_error_tool")
        assert error_one.isError and error_two.isError
        assert result_text(error_one) == "fake upstream failure #1"
        assert result_text(error_two) == "fake upstream failure #2"

        false_one = result_json(await call(session, "p_ok_false_tool"))
        false_two = result_json(await call(session, "p_ok_false_tool"))
        assert false_one["ok"] is False
        assert false_one["count"] == 1
        assert false_two["count"] == 2
        assert false_one["meta"]["cache"] == "miss"
        assert false_two["meta"]["cache"] == "miss"


async def test_cache_evicts_oldest_when_max_entries_exceeded(tmp_path):
    config = make_config(
        tmp_path,
        allow=["counter_tool"],
        cache={"max_entries": 2, "ttl_seconds": {"default": 60}},
    )
    async with proxy_session(config) as session:
        counts = []
        for key in ("a", "b", "c", "a"):
            counts.append(result_json(await call(session, "p_counter_tool", {"key": key}))["count"])

    assert counts == [1, 2, 3, 4]


async def test_rate_limit_returns_structured_error_without_calling_upstream(tmp_path):
    config = make_config(
        tmp_path,
        allow=["counter_tool"],
        cache={"ttl_seconds": {"default": 0}},
        rate={"max_calls_per_minute": 2},
    )
    async with proxy_session(config) as session:
        first = await call(session, "p_counter_tool", {"key": "a"})
        second = await call(session, "p_counter_tool", {"key": "b"})
        third = await call(session, "p_counter_tool", {"key": "c"})

    assert first.isError is False
    assert second.isError is False
    assert third.isError is True
    payload = result_json(third)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "rate_limited"
    assert "meta" not in payload


async def test_structured_content_is_passed_through(tmp_path):
    config = make_config(tmp_path, allow=["structured_tool"])
    async with proxy_session(config) as session:
        result = await call(session, "p_structured_tool")

    assert result.isError is False
    assert result.structuredContent == {"ok": True, "n": 5}
    payload = result_json(result)
    assert payload["meta"]["proxy"] == "mcp-filter-proxy"


async def test_upstream_crash_is_reported_and_proxy_survives(tmp_path):
    config = make_config(
        tmp_path, allow=["crash_tool", "json_tool"], cache={"ttl_seconds": {"default": 0}}
    )
    async with proxy_session(config) as session:
        try:
            crashed = await call(session, "p_crash_tool")
            assert crashed.isError
        except Exception:
            pass

        after = await call(session, "p_json_tool", {"x": 1})
        assert after.isError
        assert "upstream" in result_text(after)

        tools = (await session.list_tools()).tools
        assert [tool.name for tool in tools] == ["p_crash_tool", "p_json_tool"]


async def test_environment_isolation_and_no_secret_logging(tmp_path):
    config = make_config(
        tmp_path,
        allow=["env_tool"],
        env={"PROBE_SECRET": "${DSH_T10_TEST_SECRET}"},
        inherit_env=False,
    )
    stderr_path = tmp_path / "stderr.log"
    with stderr_path.open("w+", encoding="utf-8") as stderr:
        async with proxy_session(
            config,
            errlog=stderr,
            env_extra={"DSH_T10_TEST_SECRET": "s3cr3t-value", "EXTRA_VISIBLE": "leaky"},
        ) as session:
            payload = result_json(await call(session, "p_env_tool"))

    keys = set(payload["keys"])
    assert {"PATH", "HOME", "PROBE_SECRET"} <= keys
    assert "EXTRA_VISIBLE" not in keys
    log = stderr_path.read_text(encoding="utf-8")
    assert "s3cr3t-value" not in log


def run_proxy(config, *, check: bool, env=None):
    command = [sys.executable, "-m", "mcp_filter_proxy", "--config", str(config)]
    if check:
        command.append("--check")
    return subprocess.run(
        command,
        cwd=str(PKG_ROOT),
        env=env if env is not None else dict(os.environ),
        capture_output=True,
        text=True,
        timeout=120,
    )


async def test_per_tool_ttl_overrides_default(tmp_path):
    config = make_config(
        tmp_path,
        allow=["counter_tool"],
        cache={"ttl_seconds": {"default": 60, "counter_tool": 0}},
    )
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_counter_tool", {"key": "a"}))
        second = result_json(await call(session, "p_counter_tool", {"key": "a"}))

    assert first["count"] == 1
    assert second["count"] == 2
    assert second["meta"]["cache"] == "miss"


async def test_cache_hits_do_not_consume_rate_limit(tmp_path):
    config = make_config(
        tmp_path,
        allow=["counter_tool"],
        cache={"ttl_seconds": {"default": 60}},
        rate={"max_calls_per_minute": 2},
    )
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_counter_tool", {"key": "a"}))
        hit = result_json(await call(session, "p_counter_tool", {"key": "a"}))
        second = result_json(await call(session, "p_counter_tool", {"key": "b"}))
        limited = await call(session, "p_counter_tool", {"key": "c"})

    assert first["count"] == 1
    assert hit["meta"]["cache"] == "hit"
    assert second["count"] == 2
    assert limited.isError is True
    assert result_json(limited)["error"]["code"] == "rate_limited"


async def test_inherit_env_true_receives_proxy_environment(tmp_path):
    config = make_config(tmp_path, allow=["env_tool"], inherit_env=True)
    async with proxy_session(
        config, env_extra={"EXTRA_VISIBLE": "visible-to-upstream"}
    ) as session:
        payload = result_json(await call(session, "p_env_tool"))

    assert "EXTRA_VISIBLE" in payload["keys"]


def test_check_mode_prints_one_json_line_and_warns_about_missing(tmp_path):
    config = make_config(
        tmp_path, allow=["json_tool", "text_tool", "missing_tool"], prefix="cn_"
    )
    out = run_proxy(config, check=True)

    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["upstream_total"] == len(TOOLS)
    assert report["exposed"] == ["cn_json_tool", "cn_text_tool"]
    assert report["missing"] == ["missing_tool"]
    assert "missing_tool" in out.stderr


def test_empty_allow_exits_with_code_2(tmp_path):
    config = make_config(tmp_path, allow=[])
    out = run_proxy(config, check=True)

    assert out.returncode == 2
    assert out.stdout == ""
    assert "allow" in out.stderr
    assert "non-empty" in out.stderr


def test_missing_env_reference_exits_with_code_2(tmp_path):
    config = make_config(
        tmp_path,
        allow=["json_tool"],
        env={"TOKEN": "${DSH_T10_TEST_MISSING_TOKEN}"},
    )
    env = {k: v for k, v in os.environ.items() if k != "DSH_T10_TEST_MISSING_TOKEN"}
    out = run_proxy(config, check=True, env=env)

    assert out.returncode == 2
    assert out.stdout == ""
    assert "DSH_T10_TEST_MISSING_TOKEN" in out.stderr


@pytest.mark.parametrize("prefix", ["", "x_"])
async def test_prefix_is_applied_and_stripped(tmp_path, prefix):
    config = make_config(tmp_path, allow=["json_tool"], prefix=prefix)
    expected = f"{prefix}json_tool"
    async with proxy_session(config) as session:
        names = [tool.name for tool in (await session.list_tools()).tools]
        result = await call(session, expected, {"x": 1})
    assert names == [expected]
    assert result.isError is False
