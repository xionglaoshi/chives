from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest
import yaml

from mcp_filter_proxy.config import ConfigError, parse_config
from support import PKG_ROOT, make_config, proxy_session, result_json

CALL_TIMEOUT = 30
HINT = "use the minute-bar tool for history; this interval only covers today"

CHECK = {
    "tool": "bars_tool",
    "type": "bars_within_requested_dates",
    "start_arg": "start_date",
    "end_arg": "end_date",
    "date_field": "trade_date",
}


async def call(session, name: str, arguments: dict | None = None):
    return await asyncio.wait_for(session.call_tool(name, arguments or {}), CALL_TIMEOUT)


def hint_config(tmp_path, *, hint: str | None = None):
    check = dict(CHECK)
    if hint is not None:
        check["hint"] = hint
    return make_config(
        tmp_path,
        allow=["bars_tool"],
        checks=[check],
        cache={"ttl_seconds": {"default": 0}},
    )


def arguments(mode: str = "out") -> dict:
    return {"start_date": "2026-10-26", "end_date": "2026-10-30", "mode": mode}


def check_config(**extra) -> dict:
    return {
        "name": "proxy",
        "upstream": {"command": "/bin/true"},
        "allow": ["bars_tool"],
        "checks": [dict(CHECK, **extra)],
    }


async def test_failed_check_includes_hint_and_returned_count(tmp_path):
    config = hint_config(tmp_path, hint=HINT)
    async with proxy_session(config) as session:
        payload = result_json(await call(session, "p_bars_tool", arguments()))

    error = payload["error"]
    assert error["code"] == "date_range_mismatch"
    assert error["hint"] == HINT
    assert error["returned_count"] == 2
    assert error["requested"] == ["2026-10-26", "2026-10-30"]
    assert error["returned_dates"] == ["2026-10-26", "2026-11-02"]


async def test_failed_check_without_hint_omits_field(tmp_path):
    config = hint_config(tmp_path)
    async with proxy_session(config) as session:
        payload = result_json(await call(session, "p_bars_tool", arguments()))

    error = payload["error"]
    assert error["code"] == "date_range_mismatch"
    assert "hint" not in error
    assert error["returned_count"] == 2


async def test_returned_count_ignores_rows_without_usable_date(tmp_path):
    config = hint_config(tmp_path, hint=HINT)
    async with proxy_session(config) as session:
        payload = result_json(await call(session, "p_bars_tool", arguments("out_mixed")))

    error = payload["error"]
    assert error["returned_count"] == 2
    assert error["returned_dates"] == ["2026-10-26", "2026-11-02"]


def test_hint_is_parsed_and_optional():
    configured = parse_config(check_config(hint=HINT), environ={})
    default = parse_config(check_config(), environ={})

    assert configured.checks[0].hint == HINT
    assert default.checks[0].hint is None


@pytest.mark.parametrize("bad_hint", [5, ["a"], None, "", "x" * 301])
def test_invalid_hint_is_rejected(bad_hint):
    with pytest.raises(ConfigError) as info:
        parse_config(check_config(hint=bad_hint), environ={})

    assert "hint" in str(info.value)


@pytest.mark.parametrize("bad_hint", [5, "", "x" * 301])
def test_invalid_hint_config_exits_with_code_2(tmp_path, bad_hint):
    data = {
        "name": "x",
        "upstream": {"command": "/usr/bin/true"},
        "allow": ["bars_tool"],
        "rename_prefix": "",
        "checks": [dict(CHECK, hint=bad_hint)],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "mcp_filter_proxy", "--config", str(path)],
        cwd=str(PKG_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert out.returncode == 2
    assert out.stdout == ""
    assert "hint" in out.stderr
