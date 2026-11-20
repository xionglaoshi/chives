"""Command line entry point: ``cn-daily-store backfill|update|check|stats|init``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .db import connect, default_db_path, init_db
from .ingest import DEFAULT_START, backfill, update
from .quality import run_check, summary_lines, write_report
from .store import DailyStore


def _codes(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    parts = [part.strip().upper() for part in raw.replace(";", ",").split(",") if part.strip()]
    out: list[str] = []
    for part in parts:
        if "." in part:
            out.append(part)
        elif len(part) == 6 and part.isdigit():
            out.append(f"{part}.SH" if part.startswith("6") else f"{part}.SZ")
        else:
            raise SystemExit(f"bad code: {part}")
    return out


def _db(args: argparse.Namespace) -> Path:
    return Path(args.db).expanduser() if args.db else default_db_path()


def _cmd_init(args: argparse.Namespace) -> int:
    path = init_db(_db(args))
    print(f"initialized {path}")
    return 0


def _cmd_backfill(args: argparse.Namespace) -> int:
    started = date.fromisoformat(args.start) if args.start else DEFAULT_START
    ended = date.fromisoformat(args.end) if args.end else None
    stats = backfill(
        _db(args),
        start=started,
        end=ended,
        codes=_codes(args.codes),
        limit=args.limit,
        force=args.force,
        full_calendar=True,
        refresh_securities=not args.no_securities,
        workers=args.workers,
    )
    print(
        f"backfill done: total={stats.total} done={stats.done} skipped={stats.skipped} "
        f"failed={stats.failed} bars={stats.rows}"
    )
    return 0 if stats.failed == 0 else 1


def _cmd_update(args: argparse.Namespace) -> int:
    target = date.fromisoformat(args.date) if args.date else None
    stats = update(
        _db(args),
        target=target,
        codes=_codes(args.codes),
        limit=args.limit,
        refresh_securities=not args.no_securities,
    )
    print(
        f"update done: total={stats.total} written_codes={stats.done} skipped={stats.skipped} "
        f"failed={stats.failed} new_bars={stats.rows} factor_refetch={stats.factor_refetch}"
    )
    return 0 if stats.failed == 0 else 1


def _cmd_check(args: argparse.Namespace) -> int:
    path = _db(args)
    report = run_check(path, pool_days=args.pool_days)
    target = Path(args.json).expanduser() if args.json else path.parent / "check_report.json"
    write_report(report, target)
    for line in summary_lines(report):
        print(line)
    print(f"report written to {target}")
    pool = report.get("limit_pool") or {}
    return 0 if pool.get("target_met", False) else 2


def _cmd_stats(args: argparse.Namespace) -> int:
    path = _db(args)
    store = DailyStore(path)
    try:
        conn = connect(path, readonly=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS securities, "
                "(SELECT COUNT(*) FROM bars) AS bars, "
                "(SELECT COUNT(*) FROM calendar) AS calendar "
                "FROM securities"
            ).fetchone()
            boards = {
                str(item["board"]): int(item["n"])
                for item in conn.execute("SELECT board, COUNT(*) AS n FROM securities GROUP BY board")
            }
            first_last = conn.execute(
                "SELECT MIN(date) AS first, MAX(date) AS last FROM bars"
            ).fetchone()
        finally:
            conn.close()
        print(json.dumps(
            {
                "database": str(path),
                "securities": row["securities"],
                "bars": row["bars"],
                "calendar_days": row["calendar"],
                "boards": boards,
                "bars_first": first_last["first"],
                "bars_last": first_last["last"],
                "latest_trading_day": store.latest_trading_day().isoformat() if store.latest_trading_day() else None,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cn-daily-store", description="Local A-share daily bar store")
    parser.add_argument("--db", help="SQLite path (default runtime/marketdata/daily.sqlite)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the database and schema")
    init.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    init.set_defaults(func=_cmd_init)

    fill = sub.add_parser("backfill", help="backfill history (resumable)")
    fill.add_argument("--start", default=DEFAULT_START.isoformat())
    fill.add_argument("--end")
    fill.add_argument("--limit", type=int)
    fill.add_argument("--codes")
    fill.add_argument("--force", action="store_true")
    fill.add_argument("--workers", type=int, default=3)
    fill.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    fill.add_argument("--no-securities", action="store_true")
    fill.set_defaults(func=_cmd_backfill)

    upd = sub.add_parser("update", help="increment the latest trading day")
    upd.add_argument("--date")
    upd.add_argument("--limit", type=int)
    upd.add_argument("--codes")
    upd.add_argument("--no-securities", action="store_true")
    upd.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    upd.set_defaults(func=_cmd_update)

    check = sub.add_parser("check", help="run data quality checks")
    check.add_argument("--pool-days", type=int, default=15)
    check.add_argument("--json")
    check.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    check.set_defaults(func=_cmd_check)

    stats = sub.add_parser("stats", help="print database summary")
    stats.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    stats.set_defaults(func=_cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted; progress is saved per code", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
