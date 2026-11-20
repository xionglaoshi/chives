"""Command line entry point: run the stdio MCP server or `--check` the wiring."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Sequence

from mcp_filter_proxy.config import ConfigError, EmptyAllowlistError, ProxyConfig, load_config
from mcp_filter_proxy.server import build_registry, serve
from mcp_filter_proxy.upstream import UpstreamGateway, UpstreamUnavailable

logger = logging.getLogger("mcp_filter_proxy")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


async def run_check(config: ProxyConfig) -> int:
    async with UpstreamGateway(config.upstream) as gateway:
        registry, missing = build_registry(gateway.tools, config.allow, config.rename_prefix)
        for name in missing:
            logger.warning("allowlisted tool does not exist upstream: %s", name)
        report = {
            "upstream_total": len(gateway.tools),
            "exposed": list(registry.keys()),
            "missing": missing,
        }
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_filter_proxy",
        description="Expose an allowlisted subset of an upstream stdio MCP server.",
    )
    parser.add_argument("--config", required=True, help="path to the proxy YAML configuration")
    parser.add_argument(
        "--check",
        action="store_true",
        help="connect to the upstream, print the exposure report as JSON and exit",
    )
    args = parser.parse_args(argv)

    _configure_logging()
    try:
        config = load_config(args.config)
    except EmptyAllowlistError as exc:
        print(f"mcp-filter-proxy: configuration error: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"mcp-filter-proxy: configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.check:
            return asyncio.run(run_check(config))
        return asyncio.run(serve(config))
    except UpstreamUnavailable as exc:
        print(f"mcp-filter-proxy: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
