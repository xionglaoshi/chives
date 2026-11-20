from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from support import PKG_ROOT, make_config, proxy_session, result_json

CALL_TIMEOUT = 30

CHECK = {
    "tool": "bars_tool",
    "type": "bars_within_requested_dates",
    "start_arg": "start_date",
    "end_arg": "end_date",
    "date_field": "trade_date",
}

VOLUME_UNITS = "lots (1 lot = 100 shares)"


async def call(session, name: str, arguments: dict | None = None):
    return await asyncio.wait_for(session.call_tool(name, arguments or {}), CALL_TIMEOUT)


def guard_config(tmp_path, *, allow=None, annotations=None, ttl=60):
    return make_config(
        tmp_path,
        allow=allow or ["bars_tool"],
        checks=[CHECK],
        annotations=annotations,
        cache={"ttl_seconds": {"default": ttl}},
    )


def arguments(mode: str) -> dict:
    return {
        "start_date": "2026-10-26",
        "end_date": "2026-10-30",
        "mode": mode,
    }


async def test_rows_inside_range_pass_and_both_date_formats_are_accepted(tmp_path):
    config = guard_config(tmp_path)
    async with proxy_session(config) as session:
        result = await call(session, "p_bars_tool", arguments("ok"))

    assert result.isError is False
    payload = result_json(result)
    assert payload["calls"] == 1
    rows = payload["002553.SZ"]
    assert [row["trade_date"] for row in rows] == [
        "2026-10-26T09:31:00",
        "2026-10-30 15:00:00",
    ]
    assert payload["meta"]["cache"] == "miss"


async def test_one_out_of_range_row_is_refused(tmp_path):
    config = guard_config(tmp_path)
    async with proxy_session(config) as session:
        result = await call(session, "p_bars_tool", arguments("out"))

    assert result.isError is True
    payload = result_json(result)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "date_range_mismatch"
    assert payload["error"]["requested"] == ["2026-10-26", "2026-10-30"]
    assert payload["error"]["returned_dates"] == ["2026-10-26", "2026-11-02"]
    assert "meta" not in payload


async def test_empty_row_list_passes(tmp_path):
    config = guard_config(tmp_path, ttl=60)
    async with proxy_session(config) as session:
        result = await call(session, "p_bars_tool", arguments("empty"))

    assert result.isError is False
    payload = result_json(result)
    assert payload["002553.SZ"] == []
    assert payload["meta"]["cache"] == "miss"


async def test_missing_date_arguments_pass(tmp_path):
    config = guard_config(tmp_path, ttl=0)
    async with proxy_session(config) as session:
        result = await call(session, "p_bars_tool", {"mode": "out"})

    assert result.isError is False
    payload = result_json(result)
    assert payload["calls"] == 1
    assert payload["002553.SZ"][1]["trade_date"] == "2026-11-02T09:31:00"


async def test_malformed_rows_and_non_row_payloads_pass(tmp_path):
    config = guard_config(tmp_path, ttl=0)
    async with proxy_session(config) as session:
        malformed = await call(session, "p_bars_tool", arguments("malformed"))
        bad_shape = await call(session, "p_bars_tool", arguments("bad_shape"))

    assert malformed.isError is False
    assert result_json(malformed)["calls"] == 1
    assert bad_shape.isError is False
    assert result_json(bad_shape)["bars"] == "not-a-list"


async def test_out_of_range_response_is_not_cached(tmp_path):
    config = guard_config(tmp_path, ttl=60)
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_bars_tool", arguments("out_tick")))
        second = result_json(await call(session, "p_bars_tool", arguments("out_tick")))

    assert first["error"]["returned_dates"][-1] == "2026-11-02"
    assert second["error"]["returned_dates"][-1] == "2026-11-03"


async def test_annotations_merge_into_meta_on_miss_and_cache_hit(tmp_path):
    annotations = {"json_tool": {"units": {"volume": VOLUME_UNITS}}}
    config = make_config(
        tmp_path,
        allow=["json_tool"],
        annotations=annotations,
        cache={"ttl_seconds": {"default": 60}},
    )
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_json_tool", {"x": 3}))
        second = result_json(await call(session, "p_json_tool", {"x": 3}))

    for payload, cache_state in ((first, "miss"), (second, "hit")):
        assert payload["meta"]["cache"] == cache_state
        assert payload["meta"]["units"]["volume"] == VOLUME_UNITS
        assert payload["meta"]["proxy"] == "mcp-filter-proxy"


async def test_annotations_use_proxy_meta_when_upstream_meta_exists(tmp_path):
    annotations = {"meta_tool": {"units": {"volume": VOLUME_UNITS}}}
    config = make_config(
        tmp_path,
        allow=["meta_tool"],
        annotations=annotations,
        cache={"ttl_seconds": {"default": 60}},
    )
    async with proxy_session(config) as session:
        first = result_json(await call(session, "p_meta_tool"))
        second = result_json(await call(session, "p_meta_tool"))

    for payload, cache_state in ((first, "miss"), (second, "hit")):
        assert payload["meta"] == {"origin": "upstream"}
        assert payload["_proxy_meta"]["cache"] == cache_state
        assert payload["_proxy_meta"]["units"]["volume"] == VOLUME_UNITS


BASE_CONFIG = (
    "name: x\n"
    "upstream:\n"
    "  command: /usr/bin/true\n"
    "allow: [get_market_data]\n"
    "rename_prefix: ''\n"
)


def run_config(tmp_path, body: str) -> subprocess.CompletedProcess:
    path = tmp_path / "config.yaml"
    path.write_text(BASE_CONFIG + body, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "mcp_filter_proxy", "--config", str(path)],
        cwd=str(PKG_ROOT),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            "checks:\n"
            "  - tool: get_market_data\n"
            "    type: nope\n"
            "    start_arg: start_date\n"
            "    end_arg: end_date\n"
            "    date_field: trade_date\n",
            "not supported",
        ),
        (
            "checks:\n"
            "  - tool: other_tool\n"
            "    type: bars_within_requested_dates\n"
            "    start_arg: start_date\n"
            "    end_arg: end_date\n"
            "    date_field: trade_date\n",
            "not in allow",
        ),
        (
            "checks:\n"
            "  - tool: get_market_data\n"
            "    type: bars_within_requested_dates\n"
            "    start_arg: start_date\n"
            "    end_arg: end_date\n",
            "date_field is required",
        ),
        (
            "annotations:\n"
            "  other_tool:\n"
            "    units: {a: b}\n",
            "not in allow",
        ),
    ],
)
def test_invalid_response_config_exits_with_code_2(tmp_path, body, expected):
    out = run_config(tmp_path, body)

    assert out.returncode == 2
    assert out.stdout == ""
    assert expected in out.stderr
