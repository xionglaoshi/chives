"""stdio MCP server exposing the simulated paper-broker tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from paper_broker_mcp import __version__
from paper_broker_mcp.envelope import envelope, now_cn
from paper_broker_mcp.service import DEFAULT_ORDER_LIMIT, MAX_ORDER_LIMIT, PaperBroker

logger = logging.getLogger(__name__)

SERVER_NAME = "paper_broker"

TOOLS: list[types.Tool] = [
    types.Tool(
        name="paper_get_account",
        description=(
            "Simulated China A-share account snapshot: cash, positions (with T+1 sellable quantity), "
            "market value and equity. No real broker is involved."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="paper_place_order",
        description=(
            "Place a simulated A-share order. Market orders fill at the quote; limit orders fill only when "
            "marketable and never rest. Returns a rejected order (with an error code) when a trading rule "
            "or the STOP kill switch blocks it. This tool can never reach a real broker."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "A-share code, e.g. 600000.SH or 600000"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "quantity": {"type": "integer", "minimum": 1, "description": "shares"},
                "price": {
                    "type": ["number", "null"],
                    "description": "limit price; null/omitted means market order filled at the quote",
                },
                "as_of": {
                    "type": ["string", "null"],
                    "description": "ISO-8601 timestamp honored only with --test-mode; ignored otherwise",
                },
            },
            "required": ["code", "side", "quantity"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="paper_list_orders",
        description="List simulated orders, newest first. Read-only.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_ORDER_LIMIT,
                    "default": DEFAULT_ORDER_LIMIT,
                }
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="paper_verify_ledger",
        description=(
            "Replay ledger.jsonl from the beginning, recompute cash and positions, and compare them with "
            "the live in-memory account. Read-only."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
]

TOOL_NAMES = {tool.name for tool in TOOLS}


def _result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))],
        isError=False,
    )


def create_server(broker: PaperBroker) -> Server:
    server: Server = Server(SERVER_NAME, version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    async def call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        args = request.params.arguments or {}
        try:
            payload = await dispatch(broker, name, args)
        except Exception as exc:  # defensive boundary: stdout carries protocol frames only
            logger.error("unexpected tool error in %s: %s", name, type(exc).__name__)
            payload = envelope(
                as_of=now_cn(),
                status="error",
                error_code="internal_error",
                error_message=f"unexpected tool error ({type(exc).__name__})",
            )
        return types.ServerResult(_result(payload))

    server.request_handlers[types.CallToolRequest] = call_tool_handler
    return server


async def dispatch(broker: PaperBroker, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "paper_get_account":
        return await broker.async_account()
    if name == "paper_place_order":
        return await broker.async_place_order(
            code=args.get("code"),
            side=args.get("side"),
            quantity=args.get("quantity"),
            price=args.get("price"),
            as_of=args.get("as_of"),
        )
    if name == "paper_list_orders":
        return await broker.async_orders(args.get("limit", DEFAULT_ORDER_LIMIT))
    if name == "paper_verify_ledger":
        return await broker.async_verify()
    return envelope(
        as_of=now_cn(),
        status="error",
        error_code="unknown_tool",
        error_message=f"unknown tool: {name}",
    )


async def serve(*, state_dir: Path, test_mode: bool, quote_file: Path | None) -> int:
    broker = PaperBroker(state_dir=state_dir, test_mode=test_mode, quote_file=quote_file)
    server = create_server(broker)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options, raise_exceptions=False)
    return 0
