"""Stateless MCP forwarding layer: every call goes to the local daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__, config, schemas
from .envelope import now_iso, unavailable

logger = logging.getLogger(__name__)
SERVER_NAME = "cn_market"
STARTUP_MESSAGE = "数据服务没有启动"
TIMEOUT_MESSAGE = "数据服务这次响应太慢，请约 1 分钟后再试"
#: Must exceed the daemon's CALL_BUDGET_SECONDS (40 s) and stay under dsh's 60 s MCP limit.
CALL_TIMEOUT_SECONDS = 55.0


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def fetch_tools(host: str = config.DEFAULT_HOST, port: int = config.DEFAULT_PORT, timeout: float = 3.0) -> list[dict[str, Any]]:
    """Read the tool list from the daemon; fall back to the packaged static list."""
    url = _base_url(host, port) + "/v1/tools"
    try:
        with _opener().open(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        tools = payload.get("tools") if isinstance(payload, dict) else None
        if isinstance(tools, list) and tools:
            return tools
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        logger.info("tool list unavailable; using the static list")
    return schemas.static_tools()


def forward_call(
    tool: str,
    args: dict[str, Any] | None,
    *,
    host: str = config.DEFAULT_HOST,
    port: int = config.DEFAULT_PORT,
    timeout: float = CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Forward one call. A missing daemon yields the uniform unavailable envelope."""
    body = json.dumps({"tool": tool, "args": args or {}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _base_url(host, port) + "/v1/call",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with _opener().open(request, timeout=timeout) as response:
            raw = response.read()
    except (TimeoutError, socket.timeout):
        # The daemon is up but slower than this call allows (it answers within
        # CALL_BUDGET_SECONDS, so this should be rare): do not claim it is down.
        return unavailable(now_iso(datetime.now(config.CN_TZ)), TIMEOUT_MESSAGE)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return unavailable(now_iso(datetime.now(config.CN_TZ)), TIMEOUT_MESSAGE)
        return unavailable(now_iso(datetime.now(config.CN_TZ)), STARTUP_MESSAGE)
    except OSError:
        return unavailable(now_iso(datetime.now(config.CN_TZ)), STARTUP_MESSAGE)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return unavailable(now_iso(datetime.now(config.CN_TZ)), "数据服务返回了无法识别的内容，请稍后再试")
    if not isinstance(payload, dict):
        return unavailable(now_iso(datetime.now(config.CN_TZ)), "数据服务返回了无法识别的内容，请稍后再试")
    return payload


def _result(payload: dict[str, Any]) -> types.CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=False)


def build_server(
    tools: list[dict[str, Any]],
    *,
    host: str = config.DEFAULT_HOST,
    port: int = config.DEFAULT_PORT,
    call_timeout: float = CALL_TIMEOUT_SECONDS,
) -> Server:
    server: Server = Server(SERVER_NAME, version=__version__)
    desk = os.environ.get('CHIVES_MARKET_DESK', '')
    common = {'market_quote', 'market_bars', 'company_search'}
    by_desk = {
        'trader': common | {'market_intraday', 'market_trading_activity'},
        'ceo': common | {'market_global', 'market_overview', 'news', 'company_profile', 'company_announcements'},
        'analyst': common | {'company_profile', 'company_financials', 'company_valuation', 'company_consensus', 'company_reports', 'company_earnings', 'company_holders', 'company_announcements'},
        'cro': common | {'market_global', 'market_sectors', 'market_fund_flow', 'market_limit_pool', 'market_trading_activity','market_overview','company_financials', 'company_announcements', 'news', 'company_holders'},
        'cio': common | {'market_global', 'market_overview', 'market_movers', 'market_limit_pool','market_sectors', 'market_fund_flow', 'market_northbound','news','company_financials','company_announcements','company_profile','company_holders'},
    }
    allowed = by_desk.get(desk) if desk else None
    tool_objects = [
        types.Tool(
            name=str(tool["name"]),
            description=str(tool.get("description", "")),
            inputSchema=tool.get("inputSchema") or {"type": "object"},
        )
        for tool in tools
        if isinstance(tool, dict) and tool.get("name") and (allowed is None or tool["name"] in allowed)
    ]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tool_objects

    async def call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
        if allowed is not None and request.params.name not in allowed:
            return types.ServerResult(_result(unavailable(now_iso(datetime.now(config.CN_TZ)), "该岗位未获此行情工具授权")))
        try:
            payload = forward_call(
                request.params.name,
                request.params.arguments or {},
                host=host,
                port=port,
                timeout=call_timeout,
            )
        except Exception:  # protocol errors must not escape the forwarding layer
            logger.exception("forwarding failed")
            payload = unavailable(now_iso(datetime.now(config.CN_TZ)), "数据服务没有启动")
        return types.ServerResult(_result(payload))

    server.request_handlers[types.CallToolRequest] = call_tool_handler
    return server


async def serve(host: str, port: int) -> int:
    tools = fetch_tools(host, port)
    server = build_server(tools, host=host, port=port)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options, raise_exceptions=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cn-market-mcp", description="MCP forwarding layer for chives-data")
    parser.add_argument("--host", default=config.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parsed = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(serve(parsed.host, parsed.port))


if __name__ == "__main__":
    raise SystemExit(main())
