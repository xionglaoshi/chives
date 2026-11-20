"""Command line entry point for hub-trigger."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from datetime import datetime
from typing import Sequence

from . import __version__
from .clock import SHANGHAI, parse_now
from .config import ConfigError, load_config
from .hub import HubClient, HubError
from .service import FastJudgeService
from .store import FastJudgeStore, StateError

logger = logging.getLogger("hub_trigger")


def _nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是非负整数") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hub_trigger",
        description="Read-only fast-judgement runner for the chives hub trigger queue.",
    )
    parser.add_argument("--config", required=True, help="YAML configuration file")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument(
        "--from-id", type=_nonnegative_int, metavar="N", help="start from trigger id > N"
    )
    parser.add_argument(
        "--now", metavar="ISO8601", help="use this Asia/Shanghai time instead of the wall clock"
    )
    parser.add_argument("--dry-run", action="store_true", help="run all checks but start no runner")
    parser.add_argument("--version", action="version", version=f"hub-trigger {__version__}")
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

    fixed_now: datetime | None = None
    if args.now:
        try:
            fixed_now = parse_now(args.now)
        except ValueError:
            print(f"参数错误: --now 不是合法的 ISO8601 时间: {args.now!r}", file=sys.stderr)
            return 2

    if fixed_now is not None:
        clock = lambda: fixed_now  # noqa: E731
    else:
        clock = lambda: datetime.now(SHANGHAI)  # noqa: E731

    try:
        store = FastJudgeStore(config.state_dir)
    except OSError as exc:
        logger.error("无法创建 state_dir %s: %s", config.state_dir, exc)
        return 1

    service = FastJudgeService(
        config,
        HubClient(config.hub),
        store,
        clock,
        dry_run=args.dry_run,
        from_id=args.from_id,
    )

    if args.once:
        try:
            service.run_cycle()
        except (HubError, StateError, OSError) as exc:
            logger.error("运行失败：%s", exc)
            return 1
        return 0

    stop = threading.Event()
    _install_stop_handlers(stop)
    return service.run_forever(stop)


if __name__ == "__main__":
    raise SystemExit(main())
