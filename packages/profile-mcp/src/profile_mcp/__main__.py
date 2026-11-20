"""`python -m profile_mcp` entry point (stdio MCP server)."""

from __future__ import annotations

import asyncio
import logging
import sys

from profile_mcp.server import serve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(serve())


if __name__ == "__main__":
    raise SystemExit(main())
