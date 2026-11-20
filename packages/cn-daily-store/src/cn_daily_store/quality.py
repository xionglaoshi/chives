"""Data quality checks: calendar, OHLC, daily change, coverage and limit-pool cross-check."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .db import connect, default_db_path
from .limits import limit_ratio_for
from .sources import GatewayClient
from .store import DailyStore

ISSUE_CAP = 200
MAX_CHANGE_TOLERANCE = 0.005
DEFAULT_POOL_DAYS = 15


@dataclass
class CheckOutput:
    report: dict[str, Any] = field(default_factory=dict)
    text: list[str] = field(default_factory=list)


def _issue(bucket: list[dict[str, Any]], counter: Counter[str], item: dict[str, Any]) -> None:
    counter[item["kind"]] += 1
    if len(bucket) < ISSUE_CAP:
        bucket.append(item)


def _normalize_pool_codes(codes: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for code in codes:
        text = str(code).strip().upper()
        if "." in text:
            out.add(text)
        elif len(text) == 6 and text.isdigit():
            out.add(f"{text}.SH" if text.startswith("6") else f"{text}.SZ")
    return out


def _limit_pool_check(
    store: DailyStore,
    conn,
    days: int,
    gateway: GatewayClient | None = None,
) -> dict[str, Any]:
    gateway = gateway or GatewayClient()
    candidates = list(reversed(store.calendar()))[: max(days * 3, days + 10)]
    known = set(store.all_codes())
    results: list[dict[str, Any]] = []
    for day in candidates:
        if len(results) >= days:
            break
        try:
            status, raw_codes, reported_count = gateway.limit_pool(day)
        except (OSError, ValueError):
            continue
        if status == "unavailable":
            continue
        theirs_all = _normalize_pool_codes(raw_codes)
        # A truncated pool cannot be compared fairly.
        if reported_count > len(theirs_all):
            continue
        bars = store.bars_on(day, adjust="none")
        ours_all = {code for code in bars if store.is_limit_up(code, day)}
        universe = set(store.universe(day))
        ours = ours_all & universe
        theirs = theirs_all & universe
        both = ours & theirs
        union = ours | theirs
        raw_union = ours_all | theirs_all
        raw_both = ours_all & theirs_all

        def outside_reason(code: str) -> str:
            if code not in known:
                return "非本库证券（北交所/退市/未收录）"
            if code not in bars:
                return "当日无 bar（停牌或数据缺口）"
            row = store.security(code)
            list_date = row["list_date"] if row is not None else None
            if list_date and store.trading_days_since(str(list_date), day) < 60:
                return "上市不足 60 个交易日（股票池排除）"
            if store.is_st(code, day):
                return "ST（股票池排除）"
            return "不在股票池"

        excluded_ours = [{"code": code, "reason": outside_reason(code)} for code in sorted(ours_all - universe)]
        excluded_theirs = [{"code": code, "reason": outside_reason(code)} for code in sorted(theirs_all - universe)]
        ours_only = sorted(ours - theirs)
        theirs_only = sorted(theirs - ours)
        reasons: dict[str, list[dict[str, str]]] = {"ours_only": [], "theirs_only": []}
        for code in ours_only:
            if code not in bars:
                reason = "本库无该证券 bar（退市/未收录）"
            elif store.limit_ratio(code, day) is None:
                reason = "新股前5日或上市不足，不判定"
            elif store.is_st(code, day):
                reason = "ST 5% 口径差异"
            else:
                reason = "复权/涨停价口径或源差异"
            reasons["ours_only"].append({"code": code, "reason": reason})
        for code in theirs_only:
            if code not in bars:
                reason = "本库当日无 bar（停牌或数据缺口）"
            elif store.limit_ratio(code, day) is None:
                reason = "新股前5日不判定"
            else:
                reason = "涨停价口径差异（除权/ST/源）"
            reasons["theirs_only"].append({"code": code, "reason": reason})
        results.append(
            {
                "date": day.isoformat(),
                "gateway_status": status,
                "gateway_count": reported_count,
                "raw_ours": len(ours_all),
                "raw_theirs": len(theirs_all),
                "raw_intersection": len(raw_both),
                "raw_union": len(raw_union),
                "raw_agreement": round(len(raw_both) / len(raw_union), 4) if raw_union else 1.0,
                "ours": len(ours),
                "theirs": len(theirs),
                "intersection": len(both),
                "union": len(union),
                "agreement": round(len(both) / len(union), 4) if union else 1.0,
                "ours_only": ours_only,
                "theirs_only": theirs_only,
                "reasons": reasons,
                "excluded_ours": excluded_ours[:50],
                "excluded_theirs": excluded_theirs[:50],
                "excluded_ours_total": len(excluded_ours),
                "excluded_theirs_total": len(excluded_theirs),
            }
        )
        time.sleep(0.1)
    total_union = sum(item["union"] for item in results)
    total_both = sum(item["intersection"] for item in results)
    raw_union = sum(item["raw_union"] for item in results)
    raw_both = sum(item["raw_intersection"] for item in results)
    overall = round(total_both / total_union, 4) if total_union else (1.0 if results else None)
    raw_overall = round(raw_both / raw_union, 4) if raw_union else (1.0 if results else None)
    return {
        "days": results,
        "overall_agreement": overall,
        "raw_overall_agreement": raw_overall,
        "target": 0.99,
        "target_met": overall is not None and overall >= 0.99,
        "note": (
            "agreement is |intersection| / |union| per day on the spec stock universe "
            "（沪深主板/创业板/科创板、非 ST、上市≥60 日；北交所不在本库）；"
            "raw_agreement additionally includes gateway-only BJ/ST rows"
        ),
    }


def run_check(
    db_path: Path | str | None = None,
    *,
    pool_days: int = DEFAULT_POOL_DAYS,
    gateway: GatewayClient | None = None,
) -> dict[str, Any]:
    path = Path(db_path).expanduser() if db_path else default_db_path()
    store = DailyStore(path)
    conn = connect(path, readonly=True)
    try:
        calendar = store.calendar()
        calendar_set = set(calendar)
        latest = calendar[-1] if calendar else None
        per_year: Counter[str] = Counter()
        issue_buckets: dict[str, list[dict[str, Any]]] = {
            "calendar": [], "ohlc": [], "negative": [], "daily_change": [],
            "ex_rights": [], "st_history_mismatch": [],
        }
        counts: Counter[str] = Counter()
        coverage: list[dict[str, Any]] = []
        total_bars = 0
        for security in conn.execute("SELECT code, name, list_date, delist_date FROM securities ORDER BY code"):
            code = str(security["code"])
            rows = list(
                conn.execute(
                    "SELECT date, open, high, low, close, volume, amount, adj_factor "
                    "FROM bars WHERE code=? ORDER BY date",
                    (code,),
                )
            )
            if not rows:
                continue
            total_bars += len(rows)
            board_row = store.security(code)
            board = str(board_row["board"]) if board_row is not None else ""
            st = store.is_st(code, latest) if latest else False
            list_date = security["list_date"]
            prev = None
            for index, row in enumerate(rows):
                day = date.fromisoformat(str(row["date"]))
                per_year[str(day.year)] += 1
                if day not in calendar_set:
                    _issue(issue_buckets["calendar"], counts, {"kind": "calendar", "code": code, "date": day.isoformat()})
                open_, high, low, close = (float(row[k]) for k in ("open", "high", "low", "close"))
                volume = int(row["volume"])
                amount = row["amount"]
                if min(open_, high, low, close) <= 0 or volume < 0 or (amount is not None and float(amount) < 0):
                    _issue(issue_buckets["negative"], counts, {"kind": "negative", "code": code, "date": day.isoformat()})
                if not (low <= open_ <= high and low <= close <= high):
                    _issue(
                        issue_buckets["ohlc"], counts,
                        {"kind": "ohlc", "code": code, "date": day.isoformat(),
                         "open": open_, "high": high, "low": low, "close": close},
                    )
                if prev is not None:
                    prev_close = float(prev["close"])
                    ratio = limit_ratio_for(board, day, st)
                    if ratio is not None and prev_close > 0:
                        change = close / prev_close - 1.0
                        threshold = float(ratio) + MAX_CHANGE_TOLERANCE
                        if abs(change) > threshold:
                            in_first_five = False
                            if list_date:
                                in_first_five = store.trading_days_since(str(list_date), day) <= 5
                            qfq_change = (close * float(row["adj_factor"])) / (
                                prev_close * float(prev["adj_factor"])
                            ) - 1.0
                            if st and not in_first_five:
                                non_st = limit_ratio_for(board, day, False)
                                if non_st is not None and abs(change) <= float(non_st) + MAX_CHANGE_TOLERANCE:
                                    _issue(
                                        issue_buckets["st_history_mismatch"], counts,
                                        {"kind": "st_history_mismatch", "code": code, "date": day.isoformat(),
                                         "raw_pct": round(change * 100, 2), "limit_pct": float(ratio) * 100},
                                    )
                                    prev = row
                                    continue
                            if not in_first_five and abs(qfq_change) <= threshold:
                                _issue(
                                    issue_buckets["ex_rights"], counts,
                                    {"kind": "ex_rights", "code": code, "date": day.isoformat(),
                                     "raw_pct": round(change * 100, 2), "qfq_pct": round(qfq_change * 100, 2)},
                                )
                            elif not in_first_five:
                                _issue(
                                    issue_buckets["daily_change"], counts,
                                    {"kind": "daily_change", "code": code, "date": day.isoformat(),
                                     "raw_pct": round(change * 100, 2), "qfq_pct": round(qfq_change * 100, 2),
                                     "limit_pct": float(ratio) * 100},
                                )
                prev = row
            expected_start = max(date(2019, 1, 1), date.fromisoformat(str(list_date))) if list_date else date(2019, 1, 1)
            expected_end = latest or date.today()
            if security["delist_date"]:
                expected_end = min(expected_end, date.fromisoformat(str(security["delist_date"])))
            expected = store.trading_days_since(expected_start, expected_end) if expected_end >= expected_start else 0
            if expected >= 20:
                missing = max(0, expected - len(rows))
                coverage.append(
                    {
                        "code": code, "name": str(security["name"]), "expected": expected,
                        "bars": len(rows), "missing": missing,
                        "missing_rate": round(missing / expected, 4),
                    }
                )
        coverage.sort(key=lambda item: (item["missing_rate"], item["missing"]), reverse=True)
        limit_pool = _limit_pool_check(store, conn, pool_days, gateway) if latest else {}
        report = {
            "database": str(path),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "calendar": {"days": len(calendar), "first": calendar[0].isoformat() if calendar else None,
                         "last": latest.isoformat() if latest else None},
            "securities": len(store.all_codes()),
            "bar_rows": total_bars,
            "per_year": dict(sorted(per_year.items())),
            "issue_counts": {key: value for key, value in counts.items()
                             if key in {"calendar", "ohlc", "negative", "daily_change"}},
            "annotation_counts": {key: value for key, value in counts.items()
                                  if key in {"ex_rights", "st_history_mismatch"}},
            "issues": issue_buckets,
            "coverage_top_missing": coverage[:20],
            "limit_pool": limit_pool,
        }
        return report
    finally:
        conn.close()
        store.close()


def write_report(report: dict[str, Any], path: Path | str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def summary_lines(report: dict[str, Any]) -> list[str]:
    lines = [
        f"calendar {report['calendar']['first']}..{report['calendar']['last']} "
        f"({report['calendar']['days']} days)",
        f"securities {report['securities']}, bar rows {report['bar_rows']}",
        "issues " + ", ".join(f"{k}={v}" for k, v in sorted(report["issue_counts"].items())),
        "annotations " + ", ".join(f"{k}={v}" for k, v in sorted(report.get("annotation_counts", {}).items())),
        "bars per year " + ", ".join(f"{y}:{n}" for y, n in report["per_year"].items()),
    ]
    pool = report.get("limit_pool") or {}
    if pool.get("days"):
        lines.append(
            f"limit pool {len(pool['days'])} days, spec-universe agreement "
            f"{pool['overall_agreement']} (target {pool['target']}, met={pool['target_met']}), "
            f"raw agreement incl. BJ/ST {pool.get('raw_overall_agreement')}"
        )
        for item in pool["days"]:
            lines.append(
                f"  {item['date']} ours={item['ours']} theirs={item['theirs']} "
                f"both={item['intersection']} union={item['union']} agreement={item['agreement']}"
            )
    for item in report["coverage_top_missing"][:20]:
        lines.append(
            f"missing {item['code']} {item['name']} {item['bars']}/{item['expected']} "
            f"({item['missing_rate']:.2%})"
        )
    return lines
