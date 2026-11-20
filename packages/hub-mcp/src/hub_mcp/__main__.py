"""`python -m hub_mcp` entry point (stdio MCP server)."""

from __future__ import annotations

import asyncio
import logging
import sys

from hub_mcp.config import resolve_base_url, resolve_profile
from hub_mcp.errors import HubConfigError
from hub_mcp.server import serve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        resolve_base_url()
        resolve_profile()
    except HubConfigError as exc:
        print(f"hub-mcp: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(serve())


if __name__ == "__main__":
    raise SystemExit(main())
