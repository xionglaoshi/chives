"""A tiny fake stdio MCP server used only by the test suite.

It never touches the network and defines one tool for each behaviour the proxy
must preserve: JSON, plain text, errors, caching, crash, environment, multi-block
and structured results.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

STATE = {"count": 0, "errors": 0, "bars": 0, "flaky": 0}


def _tool(name: str, description: str, schema: dict | None = None) -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema=schema
        or {"type": "object", "properties": {}, "additionalProperties": False},
    )


TOOLS: list[types.Tool] = [
    _tool(
        "json_tool",
        "Returns a JSON object.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "echoed back"},
            },
            "required": ["x"],
            "additionalProperties": False,
        },
    ),
    _tool("text_tool", "Returns plain text."),
    _tool("empty_text_tool", "Returns an empty text block."),
    _tool("blank_text_tool", "Returns a whitespace-only text block."),
    _tool("empty_results_tool", "Returns a JSON object with an empty results list."),
    _tool("empty_list_tool", "Returns an empty JSON list."),
    _tool("flaky_tool", "Returns empty on the first call and data afterwards."),
    _tool("allowed_empty_tool", "Returns a JSON object with an empty results list."),
    _tool("error_tool", "Always raises an error."),
    _tool(
        "counter_tool",
        "Counts calls per key; used to observe cache hits and forwarded calls.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "extra": {"type": "integer"},
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    ),
    _tool("meta_tool", "Returns JSON that already contains a meta field."),
    _tool("ok_false_tool", "Returns JSON with ok=false but isError=false."),
    _tool("crash_tool", "Exits the upstream process immediately."),
    _tool("env_tool", "Returns the names (never values) of its environment variables."),
    _tool("multi_block_tool", "Returns two separate text blocks."),
    _tool("structured_tool", "Returns text plus structuredContent."),
    _tool("slow_tool", "Sleeps briefly before returning JSON."),
    _tool(
        "bars_tool",
        "Returns date-stamped bars; used to exercise response checks.",
        {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "mode": {"type": "string"},
                "symbol": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    _tool("extra_tool", "Present upstream but never allowlisted in tests."),
]

TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}


def _text(value: str) -> types.TextContent:
    return types.TextContent(type="text", text=value)


server: Server = Server("fake-upstream", version="0.1.0")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict | None):
    args = arguments or {}
    if name == "json_tool":
        payload = '{"ok": true, "x": %d, "nested": {"b": 2, "a": 1}}' % int(args.get("x", 0))
        return types.CallToolResult(content=[_text(payload)])
    if name == "text_tool":
        return types.CallToolResult(content=[_text("plain text result")])
    if name == "empty_text_tool":
        return types.CallToolResult(content=[_text("")])
    if name == "blank_text_tool":
        return types.CallToolResult(content=[_text("  \n\t ")])
    if name == "empty_results_tool":
        return types.CallToolResult(
            content=[_text('{"results": [], "warnings": ["rate limited"]}')]
        )
    if name == "empty_list_tool":
        return types.CallToolResult(content=[_text("[]")])
    if name == "flaky_tool":
        STATE["flaky"] += 1
        if STATE["flaky"] == 1:
            return types.CallToolResult(content=[])
        return types.CallToolResult(
            content=[_text(json.dumps({"results": [{"v": STATE["flaky"]}]}))]
        )
    if name == "allowed_empty_tool":
        return types.CallToolResult(content=[_text('{"results": []}')])
    if name == "error_tool":
        STATE["errors"] += 1
        raise RuntimeError(f"fake upstream failure #{STATE['errors']}")
    if name == "counter_tool":
        STATE["count"] += 1
        payload = {
            "ok": True,
            "key": str(args.get("key")),
            "count": STATE["count"],
        }
        if "extra" in args:
            payload["extra"] = args["extra"]
        return types.CallToolResult(content=[_text(json.dumps(payload))])
    if name == "meta_tool":
        return types.CallToolResult(
            content=[_text('{"ok": true, "meta": {"origin": "upstream"}, "value": 1}')]
        )
    if name == "ok_false_tool":
        STATE["count"] += 1
        return types.CallToolResult(
            content=[_text('{"ok": false, "count": %d}' % STATE["count"])]
        )
    if name == "crash_tool":
        os._exit(7)
    if name == "env_tool":
        return types.CallToolResult(
            content=[_text(json.dumps({"ok": True, "keys": sorted(os.environ)}))]
        )
    if name == "multi_block_tool":
        return types.CallToolResult(content=[_text('{"first": 1}'), _text("second block")])
    if name == "structured_tool":
        return [_text('{"ok": true, "n": 5}')], {"ok": True, "n": 5}
    if name == "slow_tool":
        await asyncio.sleep(0.2)
        return types.CallToolResult(content=[_text('{"ok": true, "slow": true}')])
    if name == "bars_tool":
        STATE["bars"] += 1
        mode = str(args.get("mode", "ok"))
        start = str(args.get("start_date", "2026-10-26"))
        end = str(args.get("end_date", "2026-10-30"))
        symbol = str(args.get("symbol", "002553.SZ"))
        if mode == "empty":
            rows: list[object] = []
        elif mode == "out":
            rows = [
                {"trade_date": f"{start}T09:31:00", "close": 1.0},
                {"trade_date": "2026-11-02T09:31:00", "close": 2.0},
            ]
        elif mode == "out_mixed":
            rows = [
                {"trade_date": f"{start}T09:31:00", "close": 1.0},
                {"close": 9.9},
                {"trade_date": None},
                {"trade_date": "2026-11-02T09:31:00", "close": 2.0},
            ]
        elif mode == "out_tick":
            rows = [
                {"trade_date": f"{start}T09:31:00", "close": 1.0},
                {
                    "trade_date": f"2026-11-{min(STATE['bars'] + 1, 9):02d}T09:31:00",
                    "close": 2.0,
                },
            ]
        elif mode == "malformed":
            rows = [
                {"open": 1.0},
                {"trade_date": None},
                {"trade_date": "not-a-date"},
                "not-a-row",
                {"trade_date": f"{start}T09:31:00"},
            ]
        elif mode == "bad_shape":
            payload = {
                "ok": True,
                "bars": "not-a-list",
                "calls": STATE["bars"],
            }
            return types.CallToolResult(content=[_text(json.dumps(payload))])
        else:
            rows = [
                {"trade_date": f"{start}T09:31:00", "close": 1.0},
                {"trade_date": f"{end} 15:00:00", "close": 2.0},
            ]
        payload = {
            symbol: rows,
            "_provenance": {symbol: {"source": "fake"}},
            "calls": STATE["bars"],
        }
        return types.CallToolResult(content=[_text(json.dumps(payload))])
    if name == "extra_tool":
        return types.CallToolResult(content=[_text('{"ok": true, "extra": true}')])
    raise RuntimeError(f"unknown fake tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
