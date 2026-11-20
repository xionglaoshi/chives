"""Command line entry point: ``python -m market_watch --config <file>``."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .config import ConfigError, load_config
from .engine import Engine
from .models import CN_TZ
from .server import start_server, stop_server

logger = logging.getLogger("market_watch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="market_watch",
        description="Deterministic A-share index/sector/breadth watch engine (no LLM).",
    )
    parser.add_argument("--config", required=True, help="YAML/JSON-subset configuration file")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="runtime directory (pid/log live here for scripts/market-watch.sh)",
    )
    parser.add_argument("--check-config", action="store_true", help="validate configuration and exit")
    parser.add_argument("--once", action="store_true", help="run one tick, print /overview, exit")
    return parser


def _install_stop_handlers(stop: threading.Event) -> None:
    def handler(signum: int, frame: object) -> None:  # noqa: ARG001
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    if args.check_config:
        print("OK")
        return 0

    clock = lambda: datetime.now(CN_TZ)  # noqa: E731
    engine = Engine(config, clock=clock, config_path=args.config)
    engine.bootstrap()
    if args.once:
        engine.tick()
        print(json.dumps(engine.overview_dict(), ensure_ascii=False, allow_nan=False))
        return 0

    stop = threading.Event()
    _install_stop_handlers(stop)
    httpd, thread = start_server(engine, config.api.host, config.api.port)
    logger.info("HTTP 服务监听 %s:%s", config.api.host, config.api.port)
    try:
        engine.run(stop)
    finally:
        stop_server(httpd, thread)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
