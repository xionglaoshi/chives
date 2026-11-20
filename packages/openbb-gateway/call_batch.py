"""Developer probe: run a batch of OpenBB MCP tool calls in one session.

Reads `_work/calls.json` (a list of {"label", "tool", "args", "sleep"}) and
appends one compact JSON line per call to `_work/results.jsonl`. Calls are
spaced by `sleep` seconds (default 2.5) to stay under 30 requests/minute.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PKG = Path(__file__).resolve().parent
CATEGORIES = os.environ.get("OPENBB_CATEGORIES", "equity,sec,news,yfinance,technical,nasdaq")


def summary(res, text: str) -> dict:
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        pass
    out = {
        "is_error": getattr(res, "is_error", None),
        "chars": len(text),
        "preview": text[:300],
    }
    if isinstance(obj, dict):
        out["keys"] = sorted(obj.keys())[:12]
        rows = obj.get("results")
        if isinstance(rows, list):
            out["rows"] = len(rows)
            if rows and isinstance(rows[0], dict):
                out["row_keys"] = sorted(rows[0].keys())[:20]
    return out


async def main() -> None:
    calls = json.loads((PKG / "_work/calls.json").read_text())
    params = StdioServerParameters(
        command=str(PKG / ".venv/bin/openbb-mcp"),
        args=["--transport", "stdio", "--allowed-categories", CATEGORIES],
        cwd=str(PKG),
        env={**os.environ, "HOME": str(PKG / ".home")},
    )
    out = open(PKG / "_work/results.jsonl", "a")
    async with stdio_client(params, errlog=sys.stderr) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 240)
            for call in calls:
                started = time.time()
                rec: dict = {"label": call["label"], "tool": call["tool"], "args": call.get("args", {})}
                try:
                    res = await asyncio.wait_for(s.call_tool(call["tool"], call.get("args") or {}), 180)
                    text = "".join(getattr(b, "text", "") for b in res.content)
                    rec.update(summary(res, text))
                except Exception as exc:  # noqa: BLE001 - probe tool
                    rec["exception"] = f"{type(exc).__name__}: {exc}"[:300]
                rec["seconds"] = round(time.time() - started, 1)
                line = json.dumps(rec, ensure_ascii=False)
                print(line)
                out.write(line + "\n")
                out.flush()
                await asyncio.sleep(float(call.get("sleep", 2.5)))
    out.close()


if __name__ == "__main__":
    asyncio.run(main())
