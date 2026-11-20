"""stdio MCP server exposing exactly local portfolio tools."""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from portfolio_mcp import __version__
from portfolio_mcp.envelope import envelope
from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioStore

logger = logging.getLogger(__name__)

SERVER_NAME = "portfolio"

POSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "A 股代码：NNNNNN.SH/.SZ/.BJ，或 6 位裸码（按前缀推断）",
        },
        "name": {"type": "string", "maxLength": 20, "description": "证券名称，≤20 字"},
        "qty": {
            "type": "integer",
            "minimum": 1,
            "description": "持仓数量，单位股（正整数；允许零股，不要求整百）",
        },
        "available_qty": {
            "type": "integer",
            "minimum": 0,
            "description": "可选。可用（可卖）数量，单位股，≤qty",
        },
        "cost_price": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "成本价，单位元/股（正数）",
        },
        "opened_date": {
            "type": "string",
            "description": "可选。建仓日期 YYYY-MM-DD，不得晚于今天",
        },
        "industry": {"type": "string", "maxLength": 20, "description": "可选。行业，≤20 字"},
        "note": {"type": "string", "maxLength": 60, "description": "可选。备注，≤60 字"},
    },
    "required": ["code", "name", "qty", "cost_price"],
    "additionalProperties": False,
}

TOOLS: list[types.Tool] = [
    types.Tool(
        name="portfolio_get",
        description=(
            "Read the local A-share holdings book (positions, cash, import as_of). Read-only. "
            "Sensitive private data: only call when the user asks about their portfolio; never "
            "send it to external services and never put it into AGENTS.md. Returns an empty hint "
            "when nothing is saved."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="portfolio_parse_csv",
        description=(
            "Parse a pasted broker holdings table (CSV/TSV/aligned text) into canonical rows. "
            "Recognizes common Chinese broker headers; ignores market value/profit/fee columns. "
            "Never writes to disk. Returns rows plus rejected lines with reasons."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "用户粘贴的持仓表文本（含表头；不要包含资金账号等列）",
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_import_preview",
        description=(
            "Validate rows and show the diff against the saved book (added/changed/removed/"
            "unchanged) plus warnings. Does NOT write. Returns a one-time confirm_token bound to "
            "the rows and mode, valid for 10 minutes. When the user asked for the import, call "
            "portfolio_import_commit right after this preview; only show warnings or rows that "
            "would be removed/overwritten to the user first."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": POSITION_SCHEMA,
                    "maxItems": 100,
                    "description": "标准持仓行（通常来自 portfolio_parse_csv 的 rows）",
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "merge"],
                    "default": "replace",
                    "description": "replace=整簿替换；merge=按代码合并（未出现的保留）",
                },
            },
            "required": ["rows"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_import_commit",
        description=(
            "Write a previewed import to disk. 用户要求导入时，preview 后可直接 commit，不必再让用户二次确认；"
            "仅当 preview 有警告、或会删除/覆盖已有持仓时，先把这些点告诉用户再提交。"
            "When the user asked for the import, commit directly after preview; tell the user "
            "first only if the preview has warnings or would remove/overwrite existing positions. "
            "Requires the unexpired one-time confirm_token; invalid, expired or reused tokens are "
            "rejected with invalid_token."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "confirm_token": {
                    "type": "string",
                    "description": "portfolio_import_preview 返回的一次性令牌",
                }
            },
            "required": ["confirm_token"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_add_position",
        description=(
            "Record one buy directly when the user asks to log it (e.g. “7.9 元买入 400 股柳工”). "
            "Writes to disk immediately; do not ask for a second confirmation. If the code is new, "
            "adds the position and returns before=null plus after and the position count. If the "
            "code already exists and merge=true (default), quantities are added and the cost is "
            "the quantity-weighted average rounded to 4 decimals, with the formula returned. "
            "merge=false is rejected with invalid and points to portfolio_update_position. "
            "Returns warnings such as name_mismatch but still writes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "A 股代码：NNNNNN.SH/.SZ/.BJ，或 6 位裸码（按前缀推断）",
                },
                "quantity": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "本次买入数量，单位股（正整数；允许零股，不要求整百）",
                },
                "cost": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "本次买入成本价，单位元/股（正数）",
                },
                "name": {"type": "string", "maxLength": 20, "description": "可选。证券名称，≤20 字"},
                "available": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "可选。可用（可卖）数量，单位股，≤合并后的数量",
                },
                "opened_at": {
                    "type": "string",
                    "description": "可选。建仓日期 YYYY-MM-DD，不得晚于今天",
                },
                "industry": {"type": "string", "maxLength": 20, "description": "可选。行业，≤20 字"},
                "note": {"type": "string", "maxLength": 60, "description": "可选。备注，≤60 字"},
                "merge": {
                    "type": "boolean",
                    "default": True,
                    "description": "代码已存在时：true=数量相加、成本加权平均；false=拒绝并提示用 update",
                },
            },
            "required": ["code", "quantity", "cost"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_update_position",
        description=(
            "Update one existing position directly whenever the user says they sold part of it, "
            "changed the cost, or otherwise edited it; do not ask for a second confirmation. "
            "Returns before/after so you can report before→after. Cannot change the code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "持仓代码，NNNNNN.SH/.SZ/.BJ 或 6 位裸码"},
                "fields": {
                    "type": "object",
                    "properties": {
                        key: value
                        for key, value in POSITION_SCHEMA["properties"].items()
                        if key != "code"
                    },
                    "additionalProperties": False,
                    "description": "要修改的字段（至少一个）；可选字段可传 null 清除",
                },
            },
            "required": ["code", "fields"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_remove_position",
        description=(
            "Remove one position directly when the user says they sold all of it or no longer "
            "hold it; do not ask for a second confirmation. Returns the removed row and counts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "持仓代码，NNNNNN.SH/.SZ/.BJ 或 6 位裸码"}
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_set_cash",
        description=(
            "Set the account-level cash balance in CNY (>= 0) directly when the user states the "
            "amount; do not ask for a second confirmation. Cash is used for total assets and "
            "weights including cash."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cash": {"type": "number", "minimum": 0, "description": "现金，单位元，≥0"}
            },
            "required": ["cash"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_clear",
        description=(
            "Delete the whole local holdings book and cash. Requires confirm=true; only call when "
            "the user explicitly asks to clear the book (“清空”)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean", "description": "必须显式为 true"}
            },
            "required": ["confirm"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="portfolio_valuation",
        description=(
            "Value all positions with one gateway snapshot request: price, market value, cost, "
            "PnL, limit-up/down flags, T+1 sellable flag, weights and concentration (top1/top5 "
            "HHI, effective N). All amounts are CNY and quantities are shares. Missing quotes are "
            "flagged price_unavailable and excluded from totals instead of failing. Sensitive "
            "private data: do not send it to external services."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="portfolio_risk",
        description=(
            "Historical risk of the saved A-share portfolio: annualized volatility, beta to the "
            "chosen benchmark, max drawdown, concentration (top1/top5/HHI/effective N), board / "
            "industry / asset-class exposure and pairwise correlations. Daily K-lines come from "
            "the local market-data gateway; positions with missing K-lines or fewer than 60 valid bars are returned in "
            "excluded and never estimated. Read-only and sensitive private data: 只在用户要求诊断持仓时调用"
            "（only call when the user asks to diagnose their portfolio）; never send it to external "
            "services and never write it to files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 500,
                    "default": 250,
                    "description": "回放窗口的基准交易日数，60–500，默认 250",
                },
                "benchmark": {
                    "type": "string",
                    "default": "000300.SH",
                    "description": (
                        "基准指数代码，白名单：000300.SH, 000001.SH, 000905.SH, 000852.SH, "
                        "399001.SZ, 399006.SZ, 000688.SH"
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
]

TOOLS.extend([
    types.Tool(name="portfolio_record_trade",description="登记用户已实际成交的记录。先预览，用户确认后以同一 UUID 和 confirm=true 登记；只更新本地持仓。",
      inputSchema={"type":"object","properties":{"id":{"type":"string"},"date":{"type":"string"},"side":{"enum":["buy","sell"]},
        "code":{"type":"string"},"shares":{"type":"integer","minimum":1},"price":{"type":"number","exclusiveMinimum":0},
        "fees":{"type":"number","minimum":0},"confirm":{"type":"boolean","default":False}},
        "additionalProperties":False,"required":["id","date","side","code","shares","price"]}),
    types.Tool(name="portfolio_trade_history",description="分页查看用户在本机登记的成交，不向券商发送指令。",
      inputSchema={"type":"object","properties":{"offset":{"type":"integer"},"limit":{"type":"integer"}},"additionalProperties":False})
])

TOOL_NAMES = {tool.name for tool in TOOLS}


def _result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))],
        isError=False,
    )


def dispatch(service: PortfolioService, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "portfolio_record_trade":
        return service.record_trade(args)
    if name == "portfolio_trade_history":
        return service.trade_history(args)
    if name == "portfolio_get":
        return service.get(args)
    if name == "portfolio_parse_csv":
        return service.parse_csv(args)
    if name == "portfolio_import_preview":
        return service.import_preview(args)
    if name == "portfolio_import_commit":
        return service.import_commit(args)
    if name == "portfolio_add_position":
        return service.add_position(args)
    if name == "portfolio_update_position":
        return service.update_position(args)
    if name == "portfolio_remove_position":
        return service.remove_position(args)
    if name == "portfolio_set_cash":
        return service.set_cash(args)
    if name == "portfolio_clear":
        return service.clear(args)
    if name == "portfolio_valuation":
        return service.valuation(args)
    if name == "portfolio_risk":
        return service.risk(args)
    return envelope(
        status="error",
        error_code="unknown_tool",
        error_message=f"unknown tool: {name}",
    )


def create_server(service: PortfolioService) -> Server:
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
    service = PortfolioService(PortfolioStore())
    server = create_server(service)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options, raise_exceptions=False)
    return 0
