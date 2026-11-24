"""CLI entry point: ``python -m chives_hub --config config.example.yaml``."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .config import ConfigError, load_config
from .engine import HubEngine
from .models import CN_TZ
from .server import start_server, stop_server

logger = logging.getLogger("chives_hub")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chives_hub",
        description="Deterministic local hub for signals, plans and the private portfolio view.",
    )
    parser.add_argument("--config", required=True, help="YAML/JSON-subset configuration file")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="runtime directory (pid/log live here for scripts/chives-hub.sh)",
    )
    parser.add_argument("--db-path", type=Path, help="override the hub state database path")
    parser.add_argument("--check-config", action="store_true", help="validate configuration and exit")
    parser.add_argument("--once", action="store_true", help="run one tick, print /health, exit")
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
    if args.db_path:
        config = replace(config, db_path=args.db_path.resolve())
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    if args.check_config:
        print("OK")
        return 0

    from datetime import datetime

    clock = lambda: datetime.now(CN_TZ)  # noqa: E731
    engine = HubEngine(config, clock=clock)
    engine.bootstrap()
    if args.once:
        print(json.dumps(engine.health_dict(), ensure_ascii=False, allow_nan=False))
        return 0

    stop = threading.Event()
    _install_stop_handlers(stop)
    httpd, thread = start_server(engine, config.api_host, config.api_port)
    logger.info("HTTP 服务监听 %s:%s", config.api_host, config.api_port)
    try:
        engine.run(stop)
    finally:
        stop_server(httpd, thread)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
