"""20-session pricing overlay. Only deploy forward-tested, per-symbol artifacts."""

import json
import math
from datetime import date, timedelta
from statistics import median
import numpy as np
from .storage import library

FEATURES = ("market", "financing", "sentiment")
RATING = {"卖出": -2, "减持": -1, "中性": 0, "持有": 0, "增持": 1, "买入": 2}
# Fixed physical scales keep ridge penalty and clipping independent of holdout data.
SCALES = {"market": 0.10, "financing": 0.01, "sentiment": 1.0}


def sentiment(events, day):
    start = (date.fromisoformat(day) - timedelta(days=45)).isoformat()
    by_org = {}
    for r in sorted(
        events, key=lambda x: (str(x.get("publishDate")), str(x.get("infoCode")))
    ):
        when = str(r.get("publishDate") or "")[:10]
        new, old = RATING.get(r["emRatingName"]), RATING.get(r["lastEmRatingName"])
        if r["orgCode"] and new is not None and old is not None and start <= when < day:
            by_org[r["orgCode"]] = (new > old) - (new < old)
    return {
        "value": sum(by_org.values()) / len(by_org) if len(by_org) >= 3 else None,
        "institutions": len(by_org),
        "scope": "45日个股券商评级变动，同机构取最近一份",
    }


def features(signals):
    m = signals.get("market") or {}
    return {
        "market": (m["sh_60d"] + m["sz_60d"]) / 2
        if "sh_60d" in m and "sz_60d" in m
        else None,
        "financing": signals.get("financing_net_5d_over_float_cap"),
        "sentiment": (signals.get("sentiment") or {}).get("value"),
    }


def vector(x, names):
    return [max(-3, min(3, x[n] / SCALES[n])) for n in names]


def fit(training, names):
    X = np.array([vector(r["x"], names) for r in training], dtype=float)
    y = np.array([math.log(r["target"] / r["static"]) for r in training])
    return np.linalg.solve(X.T @ X + 4 * np.eye(len(names)), X.T @ y).tolist()


def overlay(x, names, weights):
    terms = [v * w for v, w in zip(vector(x, names), weights)]
    size = abs(sum(terms))
    # Cap the entire price deviation without losing the additive attribution.
    scale = min(1.0, math.log(1.30) / size) if size else 1.0
    return {name: t * scale for name, t in zip(names, terms)}


def forecast(row, names, weights):
    return row["static"] * math.exp(sum(overlay(row["x"], names, weights).values()))


def calibrate(observations, code, version, cutoff):
    eligible = sorted(
        [r for r in observations if r["end"] <= cutoff], key=lambda r: r["date"]
    )
    report = {
        "code": code,
        "model_version": version,
        "validated_through": cutoff,
        "observations": len(eligible),
        "trials": [],
    }
    # Reserve the final eighteen months before inspecting any factor or error quantile.
    holdout_start = (date.fromisoformat(cutoff) - timedelta(days=548)).isoformat()
    development = [r for r in eligible if r["end"] < holdout_start]
    holdout = [r for r in eligible if r["date"] >= holdout_start]
    active = []
    for name in FEATURES:
        names = active + [name]
        points = [
            r for r in development if all(r["x"].get(n) is not None for n in names)
        ]
        forecasts = []
        for r in points:
            # No training label crosses the start of the out-of-sample prediction.
            train = [p for p in points if p["end"] < r["date"]]
            if len(train) < 24:
                continue
            pred = forecast(r, names, fit(train, names))
            simpler = forecast(r, active, fit(train, active)) if active else r["static"]
            prev = [f["residual"] for f in forecasts if f["end"] < r["date"]]
            bounds = (
                np.quantile(prev, [0.10, 0.90]).tolist() if len(prev) >= 12 else None
            )
            forecasts.append(
                dict(
                    date=r["date"],
                    end=r["end"],
                    residual=math.log(r["target"] / pred),
                    close_error=abs(math.log(r["target"] / r["close"])),
                    static_error=abs(math.log(r["target"] / r["static"])),
                    simpler_error=abs(math.log(r["target"] / simpler)),
                    bounds=bounds,
                )
            )
        trial = {
            "factors": names,
            "forward_observations": len(forecasts),
            "accepted": False,
        }
        report["trials"].append(trial)
        if not forecasts:
            continue

        def beats(group):
            return median(abs(f["residual"]) for f in group) < min(
                median(f[k] for f in group)
                for k in ("close_error", "static_error", "simpler_error")
            )

        trial["median_abs_log_errors"] = {
            k: median(abs(f[k]) for f in forecasts)
            for k in ("residual", "close_error", "static_error", "simpler_error")
        }
        scored = [f for f in forecasts if f["bounds"]]
        if not scored:
            continue
        coverage = sum(
            f["bounds"][0] <= f["residual"] <= f["bounds"][1] for f in scored
        ) / len(scored)
        width = median(
            math.exp(f["bounds"][1]) - math.exp(f["bounds"][0]) for f in scored
        )
        trial.update(coverage=coverage, relative_width=width)
        years = {f["date"][:4] for f in forecasts}
        groups = [
            [f for f in forecasts if f["date"].startswith(year)] for year in years
        ]
        if (
            len(scored) < 24
            or not beats(forecasts)
            or sum(len(g) >= 6 and beats(g) for g in groups) < 3
            or not 0.75 <= coverage <= 0.85
            or width > 0.60
        ):
            continue
        active = names
        trial["accepted"] = True
        report["model"] = {
            "names": active,
            "weights": fit(points, active),
            "errors": np.quantile(
                [f["residual"] for f in forecasts], [0.10, 0.90]
            ).tolist(),
        }
    candidate = report.pop("model", None)
    report["holdout_start"] = holdout_start
    if candidate:
        names = candidate["names"]
        dev = [r for r in development if all(r["x"].get(n) is not None for n in names)]
        unseen = [r for r in holdout if all(r["x"].get(n) is not None for n in names)]
        lo, hi = candidate["errors"]
        if len(unseen) >= 12 and lo <= 0 <= hi:
            actual, close_err, static_err, covered, scores, baseline_scores = (
                [],
                [],
                [],
                [],
                [],
                [],
            )
            base_lo, base_hi = np.quantile(
                [math.log(r["target"] / r["close"]) for r in dev], [0.1, 0.9]
            )

            def interval_score(y, lower, upper):
                return upper - lower + 10 * (max(0, lower - y) + max(0, y - upper))

            for r in unseen:
                pred = forecast(r, names, candidate["weights"])
                y = math.log(r["target"] / pred)
                yc = math.log(r["target"] / r["close"])
                actual.append(abs(y))
                close_err.append(abs(yc))
                static_err.append(abs(math.log(r["target"] / r["static"])))
                covered.append(lo <= y <= hi)
                scores.append(interval_score(y, lo, hi))
                baseline_scores.append(interval_score(yc, base_lo, base_hi))
            coverage = sum(covered) / len(covered)
            passed = (
                median(actual) < min(median(close_err), median(static_err))
                and 0.75 <= coverage <= 0.85
                and sum(scores) < sum(baseline_scores)
            )
            report["holdout"] = dict(
                count=len(unseen),
                coverage=coverage,
                median_error=median(actual),
                close_error=median(close_err),
                static_error=median(static_err),
                passed=passed,
            )
            if passed:
                report["model"] = candidate
    return report


def apply_validated(result):
    if not result["static"]:
        return
    loc = library() / "valuations" / "calibration" / result["code"]
    # Use only previously frozen validation, never a future-trained model on a past date.
    files = sorted(loc.glob("????-??-??.json"), reverse=True)
    for path in files:
        if path.stem >= result["as_of"]:
            continue
        try:
            record = json.loads(path.read_bytes())
            cutoff = date.fromisoformat(path.stem)
        except (ValueError, OSError):
            return
        if not isinstance(record, dict):
            return
        if (
            record.get("model_version") != result["model_version"]
            or record.get("code") != result["code"]
        ):
            continue
        if (date.fromisoformat(result["as_of"]) - cutoff).days > 365:
            return
        holdout = record.get("holdout")
        if (
            record.get("validated_through") != path.stem
            or not isinstance(holdout, dict)
            or holdout.get("passed") is not True
        ):
            return
        model = record.get("model")
        if not isinstance(model, dict):
            return
        names, weights, errors = (model.get(k) for k in ("names", "weights", "errors"))
        if not all(isinstance(v, list) for v in (names, weights, errors)):
            return
        if (
            not names
            or any(n not in FEATURES for n in names)
            or len(set(names)) != len(names)
            or len(weights) != len(names)
            or len(errors) != 2
            or any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in weights + errors
            )
        ):
            return
        lo, hi = errors
        if not -20 <= lo <= 0 <= hi <= 20:
            return
        x = features(result["signals"])
        if any(x[n] is None for n in names):
            return
        parts = overlay(x, names, weights)
        mid = result["static"]["mid"] * math.exp(sum(parts.values()))
        result.update(
            dynamic=dict(
                low=round(mid * math.exp(min(0, lo)), 2),
                mid=round(mid, 2),
                high=round(mid * math.exp(max(0, hi)), 2),
            ),
            status="动态估值",
            dynamic_status="已校准",
            calibration_date=path.stem,
            contributions=parts,
        )
        result["signals"]["applied_factors"] = model["names"]
        result["reasons"][-1] = "动态区间使用该股已冻结的样本外误差；贡献为对数调整量。"
        return
