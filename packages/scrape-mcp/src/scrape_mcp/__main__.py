"""`python -m scrape_mcp` entry point (stdio MCP server)."""

from __future__ import annotations

import asyncio
import logging
import sys

from scrape_mcp.config import ConfigError
from scrape_mcp.server import load_server_settings, serve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        settings = load_server_settings()
    except ConfigError as exc:
        print(f"scrape_mcp: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(serve(settings))


if __name__ == "__main__":
    raise SystemExit(main())
