"""Developer probe: list or call OpenBB MCP tools over stdio.

Usage:
    .venv/bin/python probe.py list
    .venv/bin/python probe.py call <tool> '<json args>'
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PKG = Path(__file__).resolve().parent
PY = PKG / ".venv/bin/openbb-mcp"
HOME = PKG / ".home"


def params(*extra: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=str(PY),
        args=["--transport", "stdio", *extra],
        cwd=str(PKG),
        env={**os.environ, "HOME": str(HOME)},
    )


async def main() -> None:
    argv = sys.argv[1:]
    sep = argv.index("--") if "--" in argv else len(argv)
    head, extra = argv[:sep], argv[sep + 1:]
    mode = head[0] if head else "list"
    wanted = head[1:]
    if mode == "call":
        tool, args = wanted[0], json.loads(wanted[1]) if len(wanted) > 1 else {}
    async with stdio_client(params(*extra), errlog=sys.stderr) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 180)
            if mode == "list":
                tools = sorted(t.name for t in (await s.list_tools()).tools)
                print(len(tools))
                print("\n".join(tools))
            elif mode in ("schema", "schemas"):
                wanted = set(wanted)
                found = []
                for t in (await s.list_tools()).tools:
                    if t.name in wanted:
                        found.append({"name": t.name, "description": t.description,
                                      "inputSchema": getattr(t, "input_schema", None)})
                if mode == "schema":
                    for item in found:
                        print(json.dumps(item, indent=2, default=str))
                else:
                    print(json.dumps(found, indent=2, default=str))
            else:
                res = await asyncio.wait_for(s.call_tool(tool, args), 300)
                print("isError:", getattr(res, "is_error", getattr(res, "isError", None)))
                for block in res.content:
                    print(getattr(block, "text", block))


if __name__ == "__main__":
    asyncio.run(main())
