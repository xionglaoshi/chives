"""Command line entry point for chives-radar."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from datetime import timedelta
from typing import Sequence

from .calendar import build_calendar
from .clock import RealClock, SimulatedClock
from .config import ConfigError, load_config
from .engine import Engine, run_once
from .server import start_server, stop_server
from .sources import GatewaySource, ReplaySource
from .storage import FileStore

logger = logging.getLogger("chives_radar")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chives-radar",
        description="Deterministic A-share watch engine (no LLM, read-only).",
    )
    parser.add_argument("--config", required=True, help="YAML configuration file")
    parser.add_argument("--out-dir", default="./cn-watch-data", help="output directory")
    parser.add_argument("--once", action="store_true", help="poll once and print one JSON object")
    parser.add_argument("--replay", metavar="FILE", help="replay a JSONL quote stream with a simulated clock")
    parser.add_argument("--serve", action="store_true", help="with --replay, keep serving HTTP afterwards")
    parser.add_argument("--check-config", action="store_true", help="validate the configuration and exit")
    return parser


def _install_stop_handlers(stop: threading.Event) -> None:
    def handler(signum: int, frame: object) -> None:  # noqa: ARG001
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _run_replay(config, args, store: FileStore, stop: threading.Event, calendar) -> int:
    try:
        source = ReplaySource(args.replay)
    except (OSError, ValueError) as exc:
        logger.error("无法加载回放文件: %s", exc)
        return 1
    clock = SimulatedClock(source.start_time)
    engine = Engine(config, source, clock, store, calendar=calendar, config_path=args.config)
    end_at = source.last_time + timedelta(seconds=10)
    engine.run(stop, end_at=end_at)
    if not args.serve:
        return 0
    if stop.is_set():
        return 0
    httpd, thread = start_server(engine, config.api.host, config.api.port)
    logger.info("HTTP 服务监听 %s:%s（回放已结束）", config.api.host, config.api.port)
    try:
        stop.wait()
    finally:
        stop_server(httpd, thread)
    return 0


def _run_once(config, store: FileStore, calendar) -> int:
    clock = RealClock()
    source = GatewaySource(config.gateway_url, timeout=config.polling.timeout_seconds)
    payload = run_once(config, source, clock, store, calendar=calendar)
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    return 0


def _run_live(config, store: FileStore, stop: threading.Event, calendar, config_path) -> int:
    clock = RealClock(stop)
    source = GatewaySource(config.gateway_url, timeout=config.polling.timeout_seconds)
    engine = Engine(config, source, clock, store, calendar=calendar, config_path=config_path)
    httpd, thread = start_server(engine, config.api.host, config.api.port)
    logger.info("HTTP 服务监听 %s:%s", config.api.host, config.api.port)
    try:
        engine.run(stop)
    finally:
        stop_server(httpd, thread)
    return 0


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

    if args.check_config:
        print("OK")
        return 0

    if args.serve and not args.replay:
        print("参数错误: --serve 只能与 --replay 一起使用", file=sys.stderr)
        return 2
    if args.once and (args.replay or args.serve):
        print("参数错误: --once 不能与 --replay/--serve 同时使用", file=sys.stderr)
        return 2

    try:
        store = FileStore(args.out_dir)
    except OSError as exc:
        logger.error("无法创建输出目录 %s: %s", args.out_dir, exc)
        return 1

    calendar = build_calendar(config.calendar, args.out_dir)

    if args.replay:
        stop = threading.Event()
        _install_stop_handlers(stop)
        return _run_replay(config, args, store, stop, calendar)

    if args.once:
        return _run_once(config, store, calendar)

    stop = threading.Event()
    _install_stop_handlers(stop)
    return _run_live(config, store, stop, calendar, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
