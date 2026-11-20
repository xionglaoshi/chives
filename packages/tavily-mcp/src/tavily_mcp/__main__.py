"""`python -m tavily_mcp` entry point (stdio MCP server)."""

from __future__ import annotations

import asyncio
import logging
import sys

from tavily_mcp.config import ConfigError
from tavily_mcp.server import load_settings, serve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"tavily_mcp: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(serve(settings))


if __name__ == "__main__":
    raise SystemExit(main())
