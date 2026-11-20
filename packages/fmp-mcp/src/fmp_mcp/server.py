"""stdio MCP server exposing exactly 17 read-only FMP tools."""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from fmp_mcp import __version__
from fmp_mcp.client import FmpClient
from fmp_mcp.envelope import envelope
from fmp_mcp.redact import redact
from fmp_mcp.tools import PLAN_RESTRICTED_HINT, TOOLS, dispatch

logger = logging.getLogger(__name__)

SERVER_NAME = "fmp"

TOOL_OBJECTS: list[types.Tool] = [
    types.Tool(
        name=tool.name,
        description=f"{tool.description} {PLAN_RESTRICTED_HINT}",
        inputSchema=tool.schema(),
    )
    for tool in TOOLS
]


def _result(payload: dict[str, Any], api_key: str | None) -> types.CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    # Defence in depth: no key material may leave the process in a tool result.
    text = redact(text, api_key)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def create_server(client: FmpClient) -> Server:
    server: Server = Server(SERVER_NAME, version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOL_OBJECTS

    async def call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        try:
            payload = dispatch(name, request.params.arguments, client)
        except Exception as exc:  # keep stdout protocol-only, never echo upstream details
            logger.error("unexpected tool error in %s: %s", name, type(exc).__name__)
            payload = envelope(
                endpoint=name,
                status="error",
                error={"code": "internal_error", "message": "工具内部错误"},
            )
        return types.ServerResult(_result(payload, client.credential))

    server.request_handlers[types.CallToolRequest] = call_tool_handler
    return server


async def serve(client: FmpClient) -> int:
    server = create_server(client)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options, raise_exceptions=False)
    return 0
