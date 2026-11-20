"""`cn-market-gateway` entry point (daemon by default)."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config
from .daemon import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cn-market-gateway", description="Read-only China market data gateway")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve"])
    parser.add_argument("--host", default=config.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parsed = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return serve(parsed.host, parsed.port)


if __name__ == "__main__":
    raise SystemExit(main())
