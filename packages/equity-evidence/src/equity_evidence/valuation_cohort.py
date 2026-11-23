"""Offline chronological CSI 300 benchmark. The dated public input pool is external."""

import argparse
from collections import Counter, defaultdict
from datetime import date
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from .storage import save
from .valuation import CYCLICAL, SPECIAL, evaluate, peer_bands, quantile
from .valuation_data import market_months
from .valuation_direction import HORIZON, assess_direction, direction, dominant, sign


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def returns(history, sessions):
    """No bridging suspensions. Each change uses that session's ex-rights reference."""
    path = []
    relative = 1.0
    for day in sessions:
        change = history.get(day, {}).get("CHANGE_RATE")
        if change is None or not math.isfinite(change) or change <= -100:
            return None
        relative *= 1 + change / 100
        path.append(relative)
    return path


def inputs(pool, through):
    indices = json.loads((pool / "沪深宽基.json").read_bytes())
    calendar = sorted(
        d for d, prices in indices.items() if d <= through and len(prices) == 2
    )
    rosters = {}
    for path in sorted((pool / "成分").glob("*.json")):
        origin = date.fromisoformat(path.stem).isoformat()
        if origin > through:
            continue
        rows = json.loads(path.read_bytes())
        members = {r["con_code"] for r in rows}
        if (
            len(rows) != 300
            or len(members) != 300
            or origin not in calendar
            or any(
                r["trade_date"] != path.stem or r["index_code"] != "000300.SH"
                for r in rows
            )
        ):
            raise ValueError(f"invalid dated membership: {origin}")
        rosters[origin] = members
    months = {d: market_months(d, indices) for d in rosters}
    peers = {}
    for day in sorted({m["date"] for chosen, _ in months.values() for m in chosen}):
        groups = defaultdict(list)
        for r in read_rows(pool / "截面" / (day + ".json.gz")):
            if r["TRADE_DATE"][:10] != day:
                raise ValueError(f"wrong peer panel date: {day}")
            groups[r["BOARD_CODE"]].append(r)
        peers[day] = groups
    return calendar, indices, rosters, months, peers


def ratio_anchor(code, quote, peers):
    """A dated market-multiple fallback; it does not reconstruct recurring earnings."""
    price = quote.get("CLOSE_PRICE")
    if not price or price <= 0:
        return None, None
    pe, pb, ps = (quote.get(k) for k in ("PE_TTM", "PB_MRQ", "PS_TTM"))
    board = quote.get("BOARD_NAME") or ""
    if any(k in board for k in (*CYCLICAL, *SPECIAL, "银行")):
        metric, multiple, quality = "PB_MRQ", pb, pb / pe if pb and pe else None
    elif pe and pe > 0:
        metric, multiple, quality = "PE_TTM", pe, pb / pe if pb and pb > 0 else None
    else:
        metric, multiple, quality = "PS_TTM", ps, ps / pe if ps and pe else None
    if not multiple or multiple <= 0:
        return None, None
    months = peer_bands(peers, code, metric, quality)
    if len(months) < 6 or len({m["date"][:4] for m in months}) < 2:
        return None, None
    return price / multiple * median(m["bands"][1] for m in months), metric


def gather(pool, through):
    calendar, indices, rosters, months, peers = inputs(pool, through)
    observations = []
    for code in sorted(set.union(*rosters.values())):
        quotes = read_rows(pool / "行情" / (code + ".json.gz"))
        reports = read_rows(pool / "财报" / (code + ".json.gz"))
        history = {r["TRADE_DATE"][:10]: r for r in quotes}
        activity = {
            r["date"]: r for r in read_rows(pool / "交易日" / (code + ".json.gz"))
        }
        # These dates must have independent evidence of trading, including unchanged closes.
        traded = {
            day: r
            for day, r in history.items()
            if day < "2022-01-01"
            or (
                activity.get(day, {}).get("tradestatus") == "1"
                and float(activity[day].get("volume") or 0) > 0
            )
        }
        # An archived broker quote can still resolve a target when the vendor has
        # removed a merged/delisted security. Keep these cases in baseline denominators.
        outcomes = dict(traded)
        for d, row in activity.items():
            if row["tradestatus"] != "1" or float(row["volume"] or 0) <= 0:
                continue
            if d not in outcomes and row["close"] and row["pctChg"]:
                outcomes[d] = {
                    "CLOSE_PRICE": float(row["close"]),
                    "CHANGE_RATE": float(row["pctChg"]),
                }
        # A 120-day majority comparator uses only finished non-overlapping blocks.
        long_history = []
        for i in range(19, len(calendar) - 120, 120):
            path = returns(traded, calendar[i + 1 : i + 121])
            if path and returns(traded, calendar[i - 19 : i + 1]):
                long_history.append((calendar[i + 120], direction(median(path) - 1)))
        for day, cohort in rosters.items():
            if code not in cohort:
                continue
            pos = calendar.index(day)
            spot = traded.get(day) or {}
            close = outcomes.get(day, {}).get("CLOSE_PRICE")
            chosen, market = months[day]
            panel = [
                p
                for m in chosen
                for p in peers[m["date"]].get(spot.get("BOARD_CODE"), ())
            ]
            # evaluate itself enforces both disclosure and revision date on the accounts.
            result = evaluate(
                code,
                day,
                dict(quote=spot, reports=reports, peers=panel, market_signal=market),
            )
            past = (
                returns(traded, calendar[max(0, pos - 19) : pos + 1])
                if pos >= 19
                else None
            )
            # Use the shipping direction function and its own historical calendar alignment.
            pick, _ = assess_direction(
                [r for r in quotes if r["TRADE_DATE"][:10] <= day], indices, day
            )
            anchor, anchor_method = (
                (result["static"]["mid"], result["method"])
                if result["static"]
                else ratio_anchor(code, spot, panel)
            )
            for horizon in (20, 120):
                future = calendar[pos + 1 : pos + 1 + horizon]
                matured = len(future) == horizon
                path = returns(outcomes, future) if close and matured else None
                historic = [side for end, side in long_history if end <= day]
                prior = dominant(Counter(historic), 0) if historic and past else None
                outlook = sign(pick["score"]) if horizon == HORIZON and pick else None
                observations.append(
                    dict(
                        date=day,
                        code=code,
                        horizon=horizon,
                        mature=matured,
                        end=future[-1] if matured else None,
                        close=close,
                        static=result["static"],
                        method=result.get("method"),
                        anchor=anchor,
                        anchor_method=anchor_method,
                        gap=None if result["static"] else result["reasons"][0],
                        momentum=math.log(past[-1]) if past else None,
                        production=outlook,
                        history=prior
                        if horizon == 120
                        else (
                            pick["rules"]["历史多数"]
                            if pick and pick["history_windows"]
                            else None
                        ),
                        target=median(path) if path else None,
                        terminal=path[-1] if path else None,
                    )
                )
    return observations


def candidate(row, valuation_weight, momentum_weight):
    if not row["anchor"] or not row["close"] or row["momentum"] is None:
        return None
    gap = math.log(row["anchor"] / row["close"])
    return math.exp(
        valuation_weight * max(-math.log(2), min(math.log(2), gap))
        + momentum_weight * max(-0.2, min(0.2, row["momentum"]))
    )


def train(rows):
    eligible = [r for r in rows if r["target"] and candidate(r, 0.1, 0) is not None]
    if not eligible:
        raise ValueError("no usable training rows")
    points, sides = [], []
    for w in (0.1, 0.25, 0.5):
        for m in (0.0, 0.1):
            pairs = [(candidate(r, w, m), r["target"]) for r in eligible]
            points.append((median(abs(p / y - 1) for p, y in pairs), w, m))
            sides.append(
                (-sum(direction(p - 1) == direction(y - 1) for p, y in pairs), w, m)
            )
    point, side = min(points)[1:], min(sides)[1:]
    residuals = [math.log(r["target"] / candidate(r, *point)) for r in eligible]
    spot_errors = [math.log(r["target"]) for r in eligible]
    return dict(
        point=point,
        side=side,
        count=len(eligible),
        interval=[quantile(residuals, q) for q in (0.1, 0.9)],
        spot_interval=[quantile(spot_errors, q) for q in (0.1, 0.9)],
    )


def classify(value):
    return direction(value - 1) if value is not None else None


def metrics(rows, model):
    eligible = [r for r in rows if r["target"] is not None]
    band_metrics = defaultdict(list)
    sides = defaultdict(list)
    for r in eligible:
        truth = classify(r["target"])
        point = candidate(r, *model["point"])
        prediction = classify(candidate(r, *model["side"]))
        trend = classify(math.exp(r["momentum"])) if r["momentum"] is not None else None
        simple = {
            "always_up": 1,
            "always_down": -1,
            "always_flat": 0,
            "momentum": trend,
            "history": r["history"],
        }
        rules = {**simple, "production": r["production"], "candidate": prediction}
        for comparator, available in (
            ("matched", prediction),
            ("prod_matched", r["production"]),
        ):
            if available is not None:
                rules.update({comparator + "_" + k: v for k, v in simple.items()})
        for key, pred in rules.items():
            if pred is not None:
                sides[key].append((pred, truth, classify(r["terminal"])))
        bands = {}
        if r["static"] and r["close"]:
            bands["static"] = [
                r["static"][k] / r["close"] for k in ("low", "mid", "high")
            ]
            bands["static_spot"] = [
                math.exp(model["spot_interval"][0]),
                1,
                math.exp(model["spot_interval"][1]),
            ]
        if point is not None:
            bands["candidate"] = [
                point * math.exp(model["interval"][0]),
                point,
                point * math.exp(model["interval"][1]),
            ]
            bands["spot"] = [
                math.exp(model["spot_interval"][0]),
                1,
                math.exp(model["spot_interval"][1]),
            ]
        for key, (low, mid, high) in bands.items():
            y = r["target"]
            band_metrics[key].append(
                (
                    low <= y <= high,
                    abs(mid / y - 1),
                    high - low,
                    high - low + 10 * max(low - y, y - high, 0),
                )
            )

    def score(items):
        return dict(
            n=len(items),
            correct=sum(a == b for a, b, _ in items),
            endpoint_correct=sum(a == c for a, _, c in items),
            confusion={
                f"{a}/{b}": sum(i == a and j == b for i, j, _ in items)
                for a in (-1, 0, 1)
                for b in (-1, 0, 1)
            },
        )

    return dict(
        scheduled=len(rows),
        labeled=len(eligible),
        price_gaps=sum(r["close"] is None for r in rows),
        static_gaps=dict(Counter(r["gap"] for r in rows if r["gap"])),
        directions={k: score(v) for k, v in sides.items()},
        bands={
            k: dict(
                n=len(v),
                covered=sum(x[0] for x in v),
                median_ape=median(x[1] for x in v),
                median_width=median(x[2] for x in v),
                mean_interval_score=sum(x[3] for x in v) / len(v),
            )
            for k, v in band_metrics.items()
        },
    )


def direction_gate(test, name):
    predictions = test["directions"].get(name)
    if not predictions or not test["scheduled"]:
        return {"passed": False, "reason": "no resolved forecasts"}
    prefix = "matched_" if name == "candidate" else "prod_matched_"
    comparable = {
        k: v["correct"]
        for k, v in test["directions"].items()
        if k.startswith(prefix) and v["n"] == predictions["n"]
    }
    accuracy = predictions["correct"] / predictions["n"]
    coverage = predictions["n"] / test["scheduled"]
    return dict(
        accuracy=accuracy,
        scored_share=coverage,
        best_baseline_correct=max(comparable.values()) if comparable else None,
        passed=bool(comparable)
        and accuracy >= 0.80
        and coverage >= 0.80
        and predictions["correct"] > max(comparable.values()),
    )


def summarize(rows, split, showcase=None):
    output = {}
    for h in (20, 120):
        cohort = [r for r in rows if r["horizon"] == h and r["date"] != showcase]
        training = [r for r in cohort if r["end"] and r["end"] < split]
        test = [r for r in cohort if r["date"] >= split and r["mature"]]
        model = train(training)
        dates = sorted({r["date"] for r in test})
        nonoverlap = []
        last = ""
        groups = {}
        for d in dates:
            batch = [r for r in test if r["date"] == d]
            groups[d] = metrics(batch, model)
            if d >= last:
                nonoverlap.extend(batch)
                last = batch[0]["end"]
        test_metrics = metrics(test, model)
        output[str(h)] = dict(
            gates={
                name: direction_gate(test_metrics, name)
                for name in ("candidate", "production")
            },
            model=model,
            train_origins=sorted({r["date"] for r in training}),
            train=metrics(training, model),
            test=test_metrics,
            by_date=groups,
            disjoint_dates=sorted({r["date"] for r in nonoverlap}),
            disjoint=metrics(nonoverlap, model),
            crossing_split=sum(
                r["date"] < split and (r["end"] or "") >= split for r in cohort
            ),
            pending=sum(not r["mature"] for r in cohort),
            example=metrics(
                [
                    r
                    for r in rows
                    if r["horizon"] == h and r["date"] == showcase and r["mature"]
                ],
                model,
            ),
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--through", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument(
        "--showcase",
        help="Extra dated membership excluded from model fitting and main test",
    )
    args = parser.parse_args()
    if (
        not date.fromisoformat(args.split)
        < date.fromisoformat(args.through)
        <= date.today()
    ):
        parser.error("expected historical split before evaluation cutoff")
    if args.out.resolve().is_relative_to(args.pool.resolve()):
        parser.error("save experiment results outside the input snapshot")
    rows = gather(args.pool, args.through)
    save(args.out / "observations.json", rows)
    result = summarize(rows, args.split, args.showcase)
    save(args.out / "metrics.json", result)
    checksums = args.pool / "SHA256SUMS"
    save(
        args.out / "run.json",
        dict(
            through=args.through,
            split=args.split,
            showcase=args.showcase,
            pool=args.pool.name,
            input_sha256=hashlib.sha256(checksums.read_bytes()).hexdigest()
            if checksums.is_file()
            else None,
            observations=len(rows),
            metrics_sha256=hashlib.sha256(
                (args.out / "metrics.json").read_bytes()
            ).hexdigest(),
        ),
    )


if __name__ == "__main__":
    main()
