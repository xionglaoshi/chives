"""`python -m paper_broker_mcp` entry point (stdio MCP server)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from paper_broker_mcp.server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paper_broker_mcp", description="Simulated A-share broker (stdio MCP).")
    parser.add_argument("--state-dir", required=True, type=Path, help="directory holding ledger.jsonl and STOP")
    parser.add_argument("--test-mode", action="store_true", help="honor as_of and read quotes from --quote-file")
    parser.add_argument("--quote-file", type=Path, help="JSON quote fixture for --test-mode")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.quote_file is not None and not args.test_mode:
        logging.getLogger(__name__).warning("--quote-file is ignored without --test-mode")
    return asyncio.run(
        serve(
            state_dir=args.state_dir,
            test_mode=args.test_mode,
            quote_file=args.quote_file if args.test_mode else None,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
