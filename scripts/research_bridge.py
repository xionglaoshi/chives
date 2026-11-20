"""Open a registered research MCP on demand for the Chives coordinator."""
import asyncio
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ResearchBridge:
    def __init__(self, declarations):
        self.servers = {s['name']: s for s in declarations}

    @asynccontextmanager
    async def connect(self, name):
        if name not in self.servers:
            raise ValueError('未登记该研究接口')
        spec = self.servers[name]
        params = StdioServerParameters(command=spec['command'], args=spec['args'],
                                      env={p['name']: p['value'] for p in spec.get('env', [])})
        async with stdio_client(params) as streams, ClientSession(*streams) as session:
            await session.initialize()
            yield session

    async def discover(self, name, query):
        if not name:
            return {'services': sorted(self.servers)}
        try:
            async with asyncio.timeout(40), self.connect(name) as session:
                cursor = None
                tools = []
                while True:
                    page = await session.list_tools(cursor=cursor)
                    tools.extend(tool for tool in page.tools if query.casefold() in
                                 (tool.name+' '+(tool.description or '')).casefold())
                    cursor = page.nextCursor
                    if not cursor:
                        break
                return {'service': name, 'tools': [t.model_dump(include={'name','description','inputSchema'}) for t in tools]}
        except Exception as error:
            raise ValueError(f'{name} 无法连接或列举工具，请选择其他已登记接口。') from error

    async def call(self, name, tool, arguments):
        try:
            async with asyncio.timeout(120), self.connect(name) as session:
                result = await session.call_tool(tool, arguments)
                return result.model_dump(mode='json', exclude_none=True)
        except Exception as error:
            raise ValueError(f'{name} 的 {tool} 调用未完成，请核对服务和参数。') from error
