"""stdio MCP server exposing exactly three local profile tools."""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from profile_mcp import __version__
from profile_mcp.envelope import envelope
from profile_mcp.fields import FIELD_ORDER
from profile_mcp.service import ProfileService
from profile_mcp.store import ProfileStore

logger = logging.getLogger(__name__)

SERVER_NAME = "profile"

FIELD_SCHEMA: dict[str, Any] = {
    "investor_type": {
        "type": "string",
        "enum": ["practitioner", "active_retail", "long_term", "beginner"],
        "description": "投资者类型",
    },
    "experience_years": {
        "type": "integer",
        "minimum": 0,
        "maximum": 60,
        "description": "投资经验年数（整数）",
    },
    "risk_level": {
        "type": "string",
        "enum": ["conservative", "balanced", "aggressive"],
        "description": "风险偏好",
    },
    "horizon": {
        "type": "string",
        "enum": ["intraday", "days", "weeks", "months", "years"],
        "description": "持有周期",
    },
    "markets": {
        "type": "array",
        "items": {"type": "string", "enum": ["cn", "us", "hk"]},
        "maxItems": 3,
        "description": "关注市场：cn/us/hk",
    },
    "sectors": {
        "type": "array",
        "items": {"type": "string", "maxLength": 30},
        "maxItems": 10,
        "description": "关注行业，每项不超过 30 字",
    },
    "styles": {
        "type": "array",
        "items": {"type": "string", "maxLength": 30},
        "maxItems": 10,
        "description": "投资风格，每项不超过 30 字",
    },
    "asset_classes": {
        "type": "array",
        "items": {"type": "string", "maxLength": 30},
        "maxItems": 10,
        "description": "资产类别，每项不超过 30 字",
    },
    "capital_range": {
        "type": "string",
        "enum": ["lt_100k", "100k_1m", "1m_10m", "gt_10m"],
        "description": "资金粗粒度档位（人民币），不要询问或保存精确金额",
    },
    "constraints": {
        "type": "array",
        "items": {"type": "string", "maxLength": 60},
        "maxItems": 8,
        "description": "硬性约束，如“不碰 ST”“不做融资”，每项不超过 60 字",
    },
    "research_depth": {
        "type": "string",
        "enum": ["light", "adaptive", "thorough"],
        "description": "研究深度",
    },
    "output_format": {
        "type": "array",
        "items": {"type": "string", "enum": ["chart", "file", "text"]},
        "maxItems": 3,
        "description": "输出偏好，按优先级排列",
    },
    "language": {"type": "string", "enum": ["zh", "en"], "description": "输出语言"},
    "agent_preference": {
        "type": "string",
        "maxLength": 300,
        "description": "用户原话补充偏好，最多 300 字",
    },
}

TOOLS: list[types.Tool] = [
    types.Tool(
        name="profile_get",
        description=(
            "Read the saved investment profile (fields, per-field updated_at, profile updated_at). "
            "Read-only. If no profile is saved, returns an empty object plus a hint."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="profile_update",
        description=(
            "Save investment-profile fields the USER stated in this conversation. "
            "Only call when the user personally describes their preferences or asks you to remember them; "
            "never infer or write a profile on your own, and never store secrets or exact account amounts. "
            "Unknown fields are rejected. Returns before/after so you can restate the change to the user. "
            "The change is also rendered into the user-global AGENTS.md block and takes effect in NEW sessions; "
            "this session must rely on the returned after values."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "properties": FIELD_SCHEMA,
                    "additionalProperties": False,
                    "description": "field name -> value; at least one field",
                }
            },
            "required": ["fields"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="profile_clear",
        description=(
            "Delete saved profile fields. Omit fields/null to clear the whole profile, or pass a list of "
            "field names to clear only those. Only call when the user personally asks to forget something. "
            "The AGENTS.md block is updated (removed when the profile becomes empty)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "fields": {
                    "type": ["array", "null"],
                    "items": {"type": "string", "enum": list(FIELD_ORDER)},
                    "description": "field names to clear; null or omitted clears everything",
                }
            },
            "additionalProperties": False,
        },
    ),
]

TOOL_NAMES = {tool.name for tool in TOOLS}


def _result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))],
        isError=False,
    )


def dispatch(service: ProfileService, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "profile_get":
        return service.get(args)
    if name == "profile_update":
        return service.update(args)
    if name == "profile_clear":
        return service.clear(args)
    return envelope(
        status="error",
        error_code="unknown_tool",
        error_message=f"unknown tool: {name}",
    )


def create_server(service: ProfileService) -> Server:
    server: Server = Server(SERVER_NAME, version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    async def call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
        name = request.params.name
        args = request.params.arguments or {}
        try:
            payload = dispatch(service, name, args)
        except Exception as exc:  # defensive boundary: stdout carries protocol frames only
            logger.error("unexpected tool error in %s: %s", name, type(exc).__name__)
            payload = envelope(
                status="error",
                error_code="internal_error",
                error_message=f"unexpected tool error ({type(exc).__name__})",
            )
        return types.ServerResult(_result(payload))

    server.request_handlers[types.CallToolRequest] = call_tool_handler
    return server


async def serve() -> int:
    service = ProfileService(ProfileStore())
    server = create_server(service)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options, raise_exceptions=False)
    return 0
