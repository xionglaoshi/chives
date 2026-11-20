"""Normalizers for earnings, holders and company profile records (T142)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from .company_parse import integer, iso_date, num, report_name, text

_CHANGE_RANGE_RE = re.compile(
    r"同比上年(增长|下降|降低|变动):\s*(-?\d+(?:\.\d+)?)%(?:至(-?\d+(?:\.\d+)?)%)?"
)


def _parse_change_range(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    match = _CHANGE_RANGE_RE.search(value)
    if match is None:
        return None, None
    sign = -1.0 if match.group(1) in ("下降", "降低") else 1.0
    first = sign * float(match.group(2))
    second = sign * float(match.group(3)) if match.group(3) is not None else first
    return min(first, second), max(first, second)


def _canonical(value: Any) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    raw = raw.zfill(6)[:6]
    if not raw.isdigit():
        return None
    if raw.startswith(("6", "5")):
        return f"{raw}.SH"
    if raw.startswith(("0", "1", "3")):
        return f"{raw}.SZ"
    if raw.startswith(("92", "43", "83", "87", "88")):
        return f"{raw}.BJ"
    return None


# --------------------------------------------------------------------------- earnings

def _forecast(row: dict[str, Any]) -> dict[str, Any]:
    summary = text(row.get("业绩变动"))
    low, high = _parse_change_range(summary)
    metric = text(row.get("预测指标"))
    value = num(row.get("预测数值"))
    prior = num(row.get("上年同期值"))
    per_share = metric == "每股收益"
    return {
        "code": _canonical(row.get("股票代码")),
        "name": text(row.get("股票简称")),
        "metric": metric,
        "forecast_type": text(row.get("预告类型")),
        "change_pct_mid": num(row.get("业绩变动幅度")),
        "change_pct_min": low,
        "change_pct_max": high,
        "forecast_mid_yuan": None if per_share else value,
        "prior_year_yuan": None if per_share else prior,
        "forecast_mid_eps_yuan": value if per_share else None,
        "prior_year_eps_yuan": prior if per_share else None,
        "summary": summary,
        "reason": text(row.get("业绩变动原因")),
        "announce_date": iso_date(row.get("公告日期")),
    }


def _express(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": _canonical(row.get("股票代码")),
        "name": text(row.get("股票简称")),
        "eps_yuan": num(row.get("每股收益")),
        "revenue_yuan": num(row.get("营业收入-营业收入")),
        "revenue_prior_yuan": num(row.get("营业收入-去年同期")),
        "revenue_yoy_pct": num(row.get("营业收入-同比增长")),
        "net_profit_yuan": num(row.get("净利润-净利润")),
        "net_profit_prior_yuan": num(row.get("净利润-去年同期")),
        "net_profit_yoy_pct": num(row.get("净利润-同比增长")),
        "bps_yuan": num(row.get("每股净资产")),
        "roe_pct": num(row.get("净资产收益率")),
        "industry": text(row.get("所处行业")),
        "announce_date": iso_date(row.get("公告日期")),
        "unconfirmed_upstream": {
            "营业收入-季度环比增长": num(row.get("营业收入-季度环比增长")),
            "净利润-季度环比增长": num(row.get("净利润-季度环比增长")),
        },
    }


def _report(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": _canonical(row.get("股票代码")),
        "name": text(row.get("股票简称")),
        "eps_yuan": num(row.get("每股收益")),
        "revenue_yuan": num(row.get("营业总收入-营业总收入")),
        "revenue_yoy_pct": num(row.get("营业总收入-同比增长")),
        "net_profit_yuan": num(row.get("净利润-净利润")),
        "net_profit_yoy_pct": num(row.get("净利润-同比增长")),
        "bps_yuan": num(row.get("每股净资产")),
        "roe_pct": num(row.get("净资产收益率")),
        "industry": text(row.get("所处行业")),
        "announce_date": iso_date(row.get("最新公告日期")),
        "unconfirmed_upstream": {
            "营业总收入-季度环比增长": num(row.get("营业总收入-季度环比增长")),
            "净利润-季度环比增长": num(row.get("净利润-季度环比增长")),
            "每股经营现金流量": num(row.get("每股经营现金流量")),
            "销售毛利率": num(row.get("销售毛利率")),
        },
    }


def normalize_earnings(rows: Iterable[dict[str, Any]], kind: str, limit: int) -> dict[str, Any]:
    builder = {"forecast": _forecast, "express": _express, "report": _report}[kind]
    output = [builder(row) for row in rows]
    output = [item for item in output if item["code"] is not None]
    output.sort(key=lambda item: item["announce_date"] or "", reverse=True)
    selected = output[:limit]
    data: dict[str, Any] = {
        "kind": kind,
        "count": len(selected),
        "total_matching": len(output),
        "events": selected,
    }
    if kind == "forecast":
        data["untrusted_text"] = True
    return data


def normalize_schedule(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any]:
    output = []
    for row in rows:
        first = iso_date(row.get("首次预约时间"))
        changes = [
            day
            for day in (iso_date(row.get(column)) for column in ("一次变更日期", "二次变更日期", "三次变更日期"))
            if day
        ]
        output.append(
            {
                "code": _canonical(row.get("股票代码")),
                "name": text(row.get("股票简称")),
                "first_scheduled_date": first,
                "change_dates": changes,
                "current_scheduled_date": changes[-1] if changes else first,
                "actual_disclosure_date": iso_date(row.get("实际披露时间")),
            }
        )
    output = [item for item in output if item["code"] is not None]
    output.sort(
        key=lambda item: (
            item["current_scheduled_date"] is None,
            item["current_scheduled_date"] or "",
            item["code"] or "",
        )
    )
    selected = output[:limit]
    return {
        "count": len(selected),
        "total_matching": len(output),
        "items": selected,
    }


# --------------------------------------------------------------------------- holders

def normalize_top10(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    output = []
    for row in rows:
        change = num(row.get("增减"))
        item: dict[str, Any] = {
            "rank": integer(row.get("名次")),
            "name": text(row.get("股东名称")),
            "holder_type": text(row.get("股东性质")),
            "share_type": text(row.get("股份类型")),
            "shares": num(row.get("持股数")),
            "float_ratio_pct": num(row.get("占总流通股本持股比例")),
            "change_shares": change,
            "change_pct": num(row.get("变动比率")),
        }
        if change is None:
            item["change_raw"] = text(row.get("增减"))
        output.append(item)
    output.sort(key=lambda item: (item["rank"] is None, item["rank"] or 0))
    return {"count": len(output), "rows": output}


def normalize_funds(
    rows: Iterable[dict[str, Any]], period: str | None, limit: int, today: date
) -> dict[str, Any]:
    parsed = []
    available: set[str] = set()
    for row in rows:
        day = iso_date(row.get("截止日期"))
        if day is None:
            continue
        if day <= today.isoformat():
            available.add(day)
        parsed.append((day, row))
    target = period
    if target is None:
        eligible = sorted(available, reverse=True)
        target = eligible[0] if eligible else None
    if target is None:
        return {"period": None, "fund_count": 0, "returned": 0, "available_periods": [], "rows": []}
    subset = [
        (
            text(row.get("基金名称")),
            text(row.get("基金代码")),
            num(row.get("持仓数量")),
            num(row.get("占流通股比例")),
            num(row.get("持股市值")),
        )
        for day, row in parsed
        if day == target
    ]
    subset.sort(key=lambda item: (item[4] is None, -(item[4] or 0.0)))
    output = [
        {
            "fund_name": name,
            "fund_code": code,
            "shares": shares,
            "float_ratio_pct": ratio,
            "market_value_yuan": value,
            "period": target,
        }
        for name, code, shares, ratio, value in subset
    ]
    ratio_total = sum(item["float_ratio_pct"] for item in output if item["float_ratio_pct"] is not None)
    return {
        "period": target,
        "fund_count": len(output),
        "returned": min(limit, len(output)),
        "total_float_ratio_pct": round(ratio_total, 4),
        "total_float_ratio_pct_computed": True,
        "available_periods": sorted(available, reverse=True),
        "rows": output[:limit],
    }


def normalize_holder_count(
    rows: Iterable[dict[str, Any]], periods: int, today: date
) -> dict[str, Any]:
    parsed = []
    for row in rows:
        day = iso_date(row.get("股东户数统计截止日"))
        if day is None or day > today.isoformat():
            continue
        parsed.append(
            {
                "end_date": day,
                "holder_count": integer(row.get("股东户数-本次")),
                "holder_count_prev": integer(row.get("股东户数-上次")),
                "holder_count_change": integer(row.get("股东户数-增减")),
                "holder_count_change_pct": num(row.get("股东户数-增减比例")),
                "avg_hold_shares": num(row.get("户均持股数量")),
                "avg_hold_amount_yuan": num(row.get("户均持股市值")),
                "total_market_cap_yuan": num(row.get("总市值")),
                "announce_date": iso_date(row.get("股东户数公告日期")),
            }
        )
    parsed.sort(key=lambda item: item["end_date"], reverse=True)
    parsed = parsed[:periods]
    for index, item in enumerate(parsed):
        item["prev_period_end"] = parsed[index + 1]["end_date"] if index + 1 < len(parsed) else None
        if index > 0:
            item["avg_hold_shares"] = None
            item["avg_hold_amount_yuan"] = None
            item["total_market_cap_yuan"] = None
    return {"count": len(parsed), "rows": parsed}


def normalize_lockup(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any]:
    output = []
    for row in rows:
        free_ratio = num(row.get("占流通市值比例"))
        total_ratio = num(row.get("占总市值比例"))
        output.append(
            {
                "free_date": iso_date(row.get("解禁时间")),
                "free_shares": num(row.get("解禁数量")),
                "able_free_shares": num(row.get("实际解禁数量")),
                "lockup_market_cap_yuan": num(row.get("实际解禁数量市值")),
                "free_ratio_pct": None if free_ratio is None else free_ratio * 100.0,
                "total_ratio_pct": None if total_ratio is None else total_ratio * 100.0,
                "share_type": text(row.get("限售股类型")),
                "holder_count": integer(row.get("解禁股东数")),
                "price_before_yuan": num(row.get("解禁前一交易日收盘价")),
            }
        )
    output = [item for item in output if item["free_date"] is not None]
    output.sort(key=lambda item: item["free_date"] or "", reverse=True)
    return {"count": min(limit, len(output)), "total_available": len(output), "rows": output[:limit]}


def normalize_lockup_market(
    rows: Iterable[dict[str, Any]], start: str, end: str
) -> list[dict[str, Any]]:
    """Whole-market lockup events; upstream shares are 10k shares and cap is 10k yuan."""
    output = []
    for row in rows:
        day = iso_date(row.get("FREE_DATE"))
        if day is None or day < start or day > end:
            continue
        shares = num(row.get("CURRENT_FREE_SHARES"))
        if shares is not None:
            shares *= 10_000.0
        market_cap = num(row.get("LIFT_MARKET_CAP"))
        if market_cap is not None:
            market_cap *= 10_000.0
        price = num(row.get("NEW"))
        if market_cap is None and shares is not None and price is not None:
            market_cap = shares * price
        float_ratio = num(row.get("FREE_RATIO"))
        total_ratio = num(row.get("TOTAL_RATIO"))
        output.append(
            {
                "date": day,
                "code": _canonical(row.get("SECURITY_CODE")),
                "name": text(row.get("SECURITY_NAME_ABBR")),
                "shares": shares,
                "market_cap_yuan": market_cap,
                "float_ratio_pct": None if float_ratio is None else float_ratio * 100.0,
                "total_ratio_pct": None if total_ratio is None else total_ratio * 100.0,
                "holder_type": text(row.get("FREE_SHARES_TYPE")),
            }
        )
    output.sort(key=lambda item: (item["date"], item["code"] or ""))
    return output


def summarize_lockup_days(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    days: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = days.setdefault(row["date"], {"date": row["date"], "count": 0, "market_cap_yuan": 0.0})
        bucket["count"] += 1
        if row.get("market_cap_yuan") is not None:
            bucket["market_cap_yuan"] += row["market_cap_yuan"]
    return [
        {
            "date": item["date"],
            "count": item["count"],
            "market_cap_yuan": round(item["market_cap_yuan"], 2),
        }
        for item in sorted(days.values(), key=lambda value: value["date"])
    ]


# --------------------------------------------------------------------------- profile

_SEGMENT_BY = {"product": "按产品分类", "region": "按地区分类", "industry": "按行业分类"}


def normalize_segments(
    rows: Iterable[dict[str, Any]], by: str, period: str | None, today: date
) -> dict[str, Any]:
    target_type = _SEGMENT_BY[by]
    parsed = []
    for row in rows:
        if text(row.get("分类类型")) != target_type:
            continue
        day = iso_date(row.get("报告日期"))
        if day is None:
            continue
        parsed.append((day, row))
    if period is not None:
        subset = [(day, row) for day, row in parsed if day == period]
    else:
        eligible = [(day, row) for day, row in parsed if day <= today.isoformat()]
        if not eligible:
            eligible = parsed
        latest = max(day for day, _ in eligible) if eligible else None
        subset = [(day, row) for day, row in eligible if day == latest]
    if not subset:
        return {"period": None, "by": by, "classification": target_type, "count": 0, "rows": []}
    used = subset[0][0]
    output = []
    any_computed = False
    for _, row in subset:
        revenue = num(row.get("主营收入"))
        share = num(row.get("收入比例"))
        cost = num(row.get("主营成本"))
        gross_profit = num(row.get("主营利润"))
        margin = num(row.get("毛利率"))
        profit_computed = False
        margin_computed = False
        if gross_profit is None and revenue is not None and cost is not None:
            gross_profit = revenue - cost
            profit_computed = True
        if margin is None and revenue not in (None, 0) and cost is not None:
            margin = (revenue - cost) / revenue
            margin_computed = True
        item = {
            "name": text(row.get("主营构成")),
            "revenue_yuan": revenue,
            "revenue_share_pct": None if share is None else share * 100.0,
            "cost_yuan": cost,
            "gross_profit_yuan": gross_profit,
            "gross_margin_pct": None if margin is None else margin * 100.0,
        }
        if profit_computed:
            item["gross_profit_computed"] = True
            any_computed = True
        if margin_computed:
            item["gross_margin_computed"] = True
            any_computed = True
        output.append(item)
    output.sort(key=lambda item: (item["revenue_yuan"] is None, -(item["revenue_yuan"] or 0.0), item["name"] or ""))
    data: dict[str, Any] = {
        "period": used,
        "by": by,
        "classification": target_type,
        "count": len(output),
        "rows": output,
    }
    if any_computed:
        data["computed"] = True
    return data


def normalize_org_info(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        path = text(row.get("EM2016"))
        industry = None
        if path:
            parts = [part for part in path.split("-") if part]
            industry = {
                "name": parts[-1] if parts else None,
                "path": path,
                "classification": "三级行业分类，取最后一级",
            }
        return {
            "name": text(row.get("SECURITY_NAME_ABBR")),
            "org_name": text(row.get("ORG_NAME")),
            "former_name": text(row.get("FORMERNAME")),
            "security_type": text(row.get("SECURITY_TYPE")),
            "industry": industry,
            "csrc_industry": text(row.get("INDUSTRYCSRC1")),
            "province": text(row.get("PROVINCE")),
        }
    return None


def normalize_concepts(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        name = text(row.get("BOARD_NAME"))
        if name is None:
            continue
        output.append(
            {
                "code": text(row.get("NEW_BOARD_CODE")) or text(row.get("BOARD_CODE")),
                "name": name,
                "precise": text(row.get("IS_PRECISE")) == "1",
                "reason": text(row.get("SELECTED_BOARD_REASON")),
            }
        )
    output.sort(key=lambda item: (not item["precise"], item["name"]))
    return output


def normalize_index_constituents(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any]:
    output = []
    dates = []
    dropped = 0
    for row in rows:
        day = iso_date(row.get("日期"))
        if day:
            dates.append(day)
        code = _canonical(row.get("成分券代码"))
        if code is None:
            dropped += 1
            continue
        output.append(
            {
                "code": code,
                "name": text(row.get("成分券名称")),
                "market": {"SH": "沪", "SZ": "深", "BJ": "北"}[code.split(".")[1]],
            }
        )
    return {
        "as_of": max(dates) if dates else None,
        "count": len(output),
        "returned": min(limit, len(output)),
        "dropped": dropped,
        "rows": output[:limit],
    }
