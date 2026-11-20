"""Entry point: ``python -m cn_watch_mcp``."""

from __future__ import annotations

import sys

from .config import EngineConfigError, resolve_engine_base
from .server import run


def main() -> int:
    try:
        base_url = resolve_engine_base()
    except EngineConfigError as exc:
        print(f"cn-watch-mcp: {exc}", file=sys.stderr)
        return 2
    return run(base_url)


if __name__ == "__main__":
    sys.exit(main())
