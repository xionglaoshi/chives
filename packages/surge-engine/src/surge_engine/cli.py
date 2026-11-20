"""Command line interface for the surge engine."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from cn_daily_store import DailyStore

from .annotate import annotate_round
from .market import DailyStoreSource
from .outputs import OutputStore, default_paths
from .replay import SurgeReplay


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def _latest(db: str | None) -> date:
    store = DailyStore(db)
    try:
        latest = store.latest_trading_day()
        if latest is None:
            raise SystemExit("daily store has no calendar")
        return latest
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="surge-engine", description="首板观察池 / 主升浪规则引擎")
    parser.add_argument("--db", help="cn-daily-store SQLite path")
    parser.add_argument("--output", help="surge output SQLite path (default runtime/surge/surge.sqlite)")
    parser.add_argument("--state", help="incremental state JSON path (default runtime/surge/state.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="逐日回放全市场")
    replay.add_argument("--start", type=_date, default=date(2020, 1, 1))
    replay.add_argument("--end", type=_date)
    replay.add_argument("--no-csv", action="store_true")
    replay.add_argument("--verbose", action="store_true")

    step = sub.add_parser("step", help="从上次状态继续推进一个交易日")
    step.add_argument("--date", type=_date, required=True)
    step.add_argument("--verbose", action="store_true")

    pools = sub.add_parser("pools", help="打印某日两个池的排序")
    pools.add_argument("--date", type=_date)
    pools.add_argument("--limit", type=int, default=20)

    round_cmd = sub.add_parser("round", help="打印某股当前/最近轮次")
    round_cmd.add_argument("code")
    round_cmd.add_argument("--date", type=_date)
    round_cmd.add_argument("--round-id", type=int)

    annotate = sub.add_parser("annotate", help="生成某轮次的 K 线标注")
    annotate.add_argument("code")
    annotate.add_argument("round_id", type=int)
    annotate.add_argument("--outdir")

    backtest = sub.add_parser("backtest", help="按冻结规则回测一个入场方案")
    backtest.add_argument("--scheme", required=True, choices=["p1", "p2", "start", "second_board"])
    backtest.add_argument("--start", type=_date, default=date(2020, 1, 1))
    backtest.add_argument("--end", type=_date)
    backtest.add_argument("--out-root", help="结果根目录（默认 runtime/surge/backtest）")
    backtest.add_argument("--no-benchmark", action="store_true", help="不取指数日线（仅调试用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_path = Path(args.output) if args.output else default_paths()[0]
    state_path = Path(args.state) if args.state else default_paths()[1]
    if args.command == "backtest":
        from cn_daily_store.db import default_db_path

        from .backtest import run_backtest, write_result

        result = run_backtest(
            surge_db=output_path,
            daily_db=args.db or str(default_db_path()),
            scheme=args.scheme,
            start=args.start,
            end=args.end,
            benchmark_closes={} if args.no_benchmark else None,
        )
        run_dir = write_result(result, args.out_root)
        print(
            f"backtest {args.scheme} done: signals={result['summary']['signal_count']} "
            f"trades={result['summary']['per_trade']['count']} "
            f"portfolio={result['summary']['portfolio']['total_return_pct']}%"
        )
        print(f"run_dir: {run_dir}")
        return 0

    if args.command == "annotate":
        output = OutputStore(output_path)
        try:
            payload = annotate_round(
                args.code, args.round_id, output=output, out_dir=args.outdir
            )
            print(f"json: {payload['json_path']}")
            print(f"html: {payload['html_path']}")
        finally:
            output.close()
        return 0

    output = OutputStore(output_path)
    try:
        if args.command == "replay":
            end = args.end or _latest(args.db)
            source = DailyStoreSource(args.db)
            replay = SurgeReplay(source, output, state_path=state_path)
            try:
                last = replay.run(args.start, end, verbose=args.verbose)
            finally:
                source.close()
            if not args.no_csv:
                output.export_csv(output.path.parent)
            _print_replay_summary(output, last)
        elif args.command == "step":
            source = DailyStoreSource(args.db)
            replay = SurgeReplay(source, output, state_path=state_path)
            try:
                events = replay.step(args.date, verbose=args.verbose)
            finally:
                source.close()
            print(f"stepped {args.date}: {len(events)} events")
            output.export_csv(output.path.parent)
        elif args.command == "pools":
            day = args.date or _stored_date(output)
            _print_pools(output, day, args.limit)
        elif args.command == "round":
            _print_round(output, args.code, args.date, args.round_id)
    finally:
        output.close()
    return 0


def _stored_date(output: OutputStore) -> date:
    stored = output.get_meta("last_date")
    if not stored:
        raise SystemExit("no replay yet; run `surge-engine replay` first")
    return date.fromisoformat(stored)


def _print_replay_summary(output: OutputStore, last: date) -> None:
    events = output.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    snapshots = output.conn.execute("SELECT COUNT(*) FROM pool_snapshots").fetchone()[0]
    rounds = output.conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0]
    print(f"replay done through {last}: events={events} snapshots={snapshots} rounds={rounds}")
    print(f"sqlite: {output.path}")


def _print_pools(output: OutputStore, day: date, limit: int) -> None:
    first_all = output.pool_rows("first", day)
    main_all = output.pool_rows("main", day)
    first = first_all[:limit]
    main = main_all[:limit]
    print(f"{day} 首板观察池 {len(first_all)} 行（显示前 {min(limit, len(first_all))}）")
    print("rank code        status     score k  T*          P*      Hb      S1          S2")
    for row in first:
        print(
            f"{row['rank']:>4} {row['code']:<11} {str(row['status']):<9} {str(row['score']):>5} "
            f"{str(row['k']):>2} {str(row['t_star'] or '-'):<11} {_num(row['p_star']):>7} "
            f"{_num(row['hb']):>7} {str(row['s1_status'] or '-'):<11} {str(row['s2_status'] or '-'):<11}"
        )
    print()
    print(f"{day} 主升浪池 {len(main_all)} 行（显示前 {min(limit, len(main_all))}）")
    print("rank code        score B       Hmax    gain    drawdown MA10 n obs")
    for row in main:
        print(
            f"{row['rank']:>4} {row['code']:<11} {str(row['score']):>5} {_num(row['basis']):>7} "
            f"{_num(row['hmax']):>7} {_pct(row['gain']):>7} {_pct(row['drawdown']):>8} "
            f"{str(row['ma10_count']):>4} {str(row['ma10_obs_left']):>3}"
        )


def _print_round(output: OutputStore, code: str, day: date | None, round_id: int | None) -> None:
    rounds = output.rounds_for(code)
    if not rounds:
        raise SystemExit(f"no rounds for {code}")
    selected = None
    if round_id is not None:
        selected = next((row for row in rounds if int(row["round_id"]) == round_id), None)
    elif day is not None:
        target = day.isoformat()
        candidates = [row for row in rounds if row["F"] <= target]
        selected = candidates[-1] if candidates else None
        for row in candidates:
            ends = [value for value in (row["main_out_date"], row["first_out_date"]) if value]
            if all(end >= target for end in ends):
                selected = row
                break
    else:
        selected = rounds[-1]
    if selected is None:
        raise SystemExit(f"round not found for {code}")
    rid = int(selected["round_id"])
    print(
        f"{code} 轮次 {rid}: F={selected['F']} 首板收={_num(selected['C_F'])} 低={_num(selected['L_F'])} "
        f"G={_num(selected['G'])} 回撤={_pct(selected['drawdown'])} 分支={selected['branch']}"
    )
    print(
        f"  启动={selected['started']} T*={selected['T_star']} P*={_num(selected['P_star'])} "
        f"E={selected['E']} B={_num(selected['B'])} 优先级={selected['priority']} "
        f"MA10次数={selected['ma10_count']} 移出={selected['main_out_reason'] or selected['first_out_reason'] or '-'}"
    )
    print("  事件：")
    for event in output.events_for(code, rid):
        print(f"    {event['date']} {event['event']} {event['values']}")
    rows = output.snapshots_for_round(code, rid)
    if day is not None:
        rows = [row for row in rows if row["date"] == day.isoformat()]
    print("  快照：")
    for row in rows:
        print(
            f"    {row['date']} {row['pool']:<5} rank={row['rank']} score={row['score']} "
            f"status={row['status']} k={row['k']} S1={row['s1_status']} S2={row['s2_status']} "
            f"base={row['base_score']} ded={row['deduction']} ma10={row['ma10_count']}/{row['ma10_obs_left']}"
        )


def _num(value: object) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _pct(value: object) -> str:
    return "-" if value is None else f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    sys.exit(main())
