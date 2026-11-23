"""Replay monthly A-share observations and freeze per-stock validation outcomes."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import math
from statistics import median
from .market import symbol
from .storage import library, save, snapshot
from .valuation import evaluate, VERSION
from .valuation_calibration import calibrate, features
from .valuation_data import (
    rows,
    financial_versions,
    SourceUnavailable,
    index_history,
    market_months,
    peer_rows,
    rating_events,
    REPORT_FIELDS,
    PEER_FIELDS,
    SECURITIES,
    REPORTS,
    FINANCING,
)


def replay(code, start, cutoff):
    code = symbol(code)
    start_day = date.fromisoformat(start)
    index_start = (start_day - timedelta(days=365 * 5 + 120)).isoformat()
    with ThreadPoolExecutor(max_workers=5) as pool:
        indices = pool.submit(index_history, index_start, cutoff)
        quotes = pool.submit(
            rows,
            SECURITIES,
            PEER_FIELDS
            + ",BOARD_NAME,BOARD_CODE,CLOSE_PRICE,TOTAL_SHARES,NOTLIMITED_MARKETCAP_A,CHANGE_RATE",
            f"(SECUCODE=\"{code}\")(TRADE_DATE>='{start}')(TRADE_DATE<='{cutoff}')",
            "TRADE_DATE",
        )
        statements = pool.submit(
            rows,
            REPORTS,
            REPORT_FIELDS,
            f"(SECUCODE=\"{code}\")(NOTICE_DATE<='{cutoff}')",
            "REPORT_DATE",
        )
        flow = pool.submit(
            rows,
            FINANCING,
            "SECUCODE,DATE,RZJME5D",
            f"(SECUCODE=\"{code}\")(DATE>='{start}')(DATE<='{cutoff}')",
            "DATE",
        )
        ratings = pool.submit(
            rating_events, code, (start_day - timedelta(days=45)).isoformat(), cutoff
        )
        series, prices, events = indices.result(), quotes.result(), ratings.result()
        fin = financial_versions(code, statements.result(), cutoff)
        try:
            financing = flow.result()
        except SourceUnavailable:
            financing = []
    daily = {r["TRADE_DATE"][:10]: r for r in prices}
    calendar = sorted(
        k for k, values in series.items() if start <= k <= cutoff and len(values) == 2
    )
    month_ends = {d[:7]: d for d in calendar}
    candidates, required = [], defaultdict(set)
    for day in month_ends.values():
        pos = bisect_right(calendar, day)
        future = calendar[pos : pos + 20]
        if (
            day not in daily
            or len(future) < 20
            or any(not daily.get(d) for d in future)
        ):
            continue
        months, market = market_months(day, series)
        board = str(daily[day]["BOARD_CODE"])
        required[board].update(m["date"] for m in months)
        candidates.append((day, future, board, months, market))
    panels = {}
    for industry, days in required.items():
        panels[industry] = defaultdict(list)
        for r in peer_rows(industry, [{"date": d} for d in sorted(days)]):
            panels[industry][r["TRADE_DATE"][:10]].append(r)
    observations = []
    gaps = defaultdict(int)
    for day, future, board, months, market in candidates:
        panel = [r for m in months for r in panels[board][m["date"]]]
        past_flow = [r for r in financing if r["DATE"][:10] < day][:1]
        r = evaluate(
            code,
            day,
            dict(
                quote=daily[day],
                reports=fin,
                peers=panel,
                market_signal=market,
                financing=past_flow,
                rating_events=events,
            ),
        )
        if not r["static"]:
            gaps[r["reasons"][0]] += 1
            continue
        close = daily[day]["CLOSE_PRICE"]
        adjusted = close
        outcomes = []
        for d in future:
            change = daily[d]["CHANGE_RATE"]
            if change is None or not math.isfinite(change) or change <= -100:
                break
            adjusted *= 1 + change / 100
            outcomes.append(adjusted)
        if len(outcomes) == 20:
            observations.append(
                dict(
                    date=day,
                    end=future[-1],
                    close=close,
                    target=median(outcomes),
                    static=r["static"]["mid"],
                    x=features(r["signals"]),
                )
            )
    result = calibrate(observations, code, VERSION, cutoff)
    result.update(
        start=start,
        candidate_dates=len(candidates),
        gaps=dict(gaps),
        observation_snapshot=snapshot({"code": code, "observations": observations}),
        price_basis="估值日原始收盘价，向后复合每日除权参考口径的涨跌幅；连续20个宽基交易日收盘中位数",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    if (
        not date.fromisoformat(args.start)
        < date.fromisoformat(args.through)
        <= date.today()
    ):
        parser.error("请指定已发生的日期区间")
    result = replay(args.code, args.start, args.through)
    path = (
        library()
        / "valuations"
        / "calibration"
        / result["code"]
        / (args.through + ".json")
    )
    save(path, result)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
