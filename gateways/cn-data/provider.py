"""Serve the ten registered equity data functions with their native schemas."""
import asyncio
import importlib
import logging
import os
from pathlib import Path
import sys
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

root = Path(__file__).resolve().parents[2]
sdk = root / 'runtime/cn-data-sdk/cb99dca528695ffe78429483a90399a89f61d614'
if not sdk.is_dir():
    raise RuntimeError('请按 cn-data 网关说明安装只读数据组件')
sys.path.insert(0, str(sdk))
os.environ['VIBE_TRADING_HOME'] = str(root / 'runtime/cn-data-state')
modules = ['symbol_search','market_data','financial_statements','fund_flow','dragon_tiger',
           'margin_trading','block_trades','shareholder_count','lockup_expiry','sector']
tools = {}
for module in modules:
    package = importlib.import_module('src.tools.' + module + '_tool')
    for cls in vars(package).values():
        if isinstance(cls,type) and cls.__module__ == package.__name__ and getattr(cls,'name',''):
            tools[cls.name] = cls()
server = Server('cn-data-provider')

@server.list_tools()
async def list_tools():
    return [types.Tool(name=t.name,description=t.description,inputSchema=t.parameters) for t in tools.values()]

@server.call_tool()
async def call_tool(name, arguments):
    value = await asyncio.to_thread(tools[name].execute, **arguments)
    return [types.TextContent(type='text',text=value)]

async def main():
    async with stdio_server() as streams:
        await server.run(*streams,server.create_initialization_options())

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stderr,level=logging.WARNING)
    asyncio.run(main())
