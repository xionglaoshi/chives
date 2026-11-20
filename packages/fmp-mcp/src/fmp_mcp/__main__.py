"""`python -m fmp_mcp` entry point (stdio MCP server, logs to stderr only)."""

from __future__ import annotations

import asyncio
import logging
import sys

from fmp_mcp.client import FmpClient
from fmp_mcp.config import ConfigError, load_settings
from fmp_mcp.server import serve

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"fmp-mcp: {exc}", file=sys.stderr)
        return 2
    if settings.api_key is None:
        logger.warning("FMP_API_KEY 未配置：服务器仍会列出工具，调用返回 missing_key")
    client = FmpClient(settings)
    return asyncio.run(serve(client))


if __name__ == "__main__":
    raise SystemExit(main())
