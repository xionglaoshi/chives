"""`python -m portfolio_mcp` entry point.

With no arguments it serves the stdio MCP server. `snapshot` prints one JSON
document for the Chives dashboard and exits; it never starts the server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from portfolio_mcp.server import serve
from portfolio_mcp.snapshot import build_snapshot

USAGE = "usage: python -m portfolio_mcp [snapshot]"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["snapshot"]:
        if len(args) > 1:
            print(USAGE, file=sys.stderr)
            return 2
        sys.stdout.write(json.dumps(build_snapshot(), ensure_ascii=False))
        sys.stdout.write("\n")
        return 0
    if args:
        print(USAGE, file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(serve())


if __name__ == "__main__":
    raise SystemExit(main())
