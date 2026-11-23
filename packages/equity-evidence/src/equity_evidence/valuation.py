"""A-share fair value in CNY per ordinary share, with reproducible public evidence."""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from .market import symbol
from .storage import library, save_bytes, snapshot
from .valuation_calibration import apply_validated, sentiment
from .valuation_data import collect, number, SourceUnavailable

VERSION = "ashare-peer-1.0"
CYCLICAL = (
    "煤炭",
    "钢铁",
    "水泥",
    "工业金属",
    "小金属",
    "能源金属",
    "化学原料",
    "油气开采",
    "炼化",
)
SPECIAL = ("保险", "证券", "多元金融", "房地产开发")


def quantile(values, pct):
    seq = sorted(values)
    i = (len(seq) - 1) * pct
    lo = int(i)
    return seq[lo] + (seq[min(lo + 1, len(seq) - 1)] - seq[lo]) * (i - lo)


def visible_reports(rows, day):
    reports = {}
    for r in sorted(rows, key=lambda x: str(x.get("UPDATE_DATE") or "")):
        period = str(r.get("REPORT_DATE") or "")[:10]
        published = str(r.get("NOTICE_DATE") or "")[:10]
        revised = str(r.get("UPDATE_DATE") or "")[:10]
        if (
            period
            and published
            and period <= published <= day
            and revised
            and revised <= day
            and r.get("_first_seen", "") <= day
            and r.get("CURRENCY") == "CNY"
        ):
            reports[period] = {k: v for k, v in r.items() if k != "_first_seen"}
    return reports


def trailing(reports, period, field):
    year = int(period[:4])
    value = number(reports[period].get(field))
    if value is None or period.endswith("12-31"):
        return value
    end = number(reports.get(f"{year - 1}-12-31", {}).get(field))
    prior = number(reports.get(f"{year - 1}" + period[4:], {}).get(field))
    if end is None or prior is None:
        return None
    return value + end - prior


def fundamentals(quote, rows):
    day = quote["TRADE_DATE"][:10]
    reports = visible_reports(rows, day)
    if not reports:
        raise ValueError("缺少估值日已经披露、且修订日可核对的人民币财报")
    period = max(reports)
    if (date.fromisoformat(day) - date.fromisoformat(period)).days > 220:
        raise ValueError("最近可核验财报超过 220 天")
    r = reports[period]
    industry = quote["BOARD_NAME"]
    shares = number(quote.get("TOTAL_SHARES"))
    book = number(r.get("BPS"))
    if not shares or shares <= 0:
        raise ValueError("缺少估值日总股本")
    if any(s in industry for s in SPECIAL):
        raise ValueError("该行业需专门模型，当前通用 PE 与银行 PB 不适用")
    bank = r.get("ORG_TYPE") == "银行" or industry in ("银行", "银行Ⅱ")
    cyclical = any(s in industry for s in CYCLICAL)
    profit = trailing(reports, period, "PARENTNETPROFIT")
    core = trailing(reports, period, "KCFJCXSYJLR")
    eps = None if core is None or profit is None else min(profit, core) / shares
    normal_roe = None
    if book and book > 0 and eps is not None:
        normal_roe = eps / book
    info = dict(
        report_period=period,
        published=r["NOTICE_DATE"][:10],
        revised=r["UPDATE_DATE"][:10],
        shares=shares,
        book_per_share=book,
        ttm_parent_profit=profit,
        ttm_recurring_profit=core,
        reported_roe_ytd_pct=r.get("ROEJQ"),
        operating_cash_per_share_ytd=r.get("MGJYXJJE"),
        debt_pct=r.get("ZCFZL"),
    )
    if bank or cyclical:
        if book is None or book <= 0:
            raise ValueError("缺少正的每股净资产，无法使用 PB")
        price, pb = number(quote.get("CLOSE_PRICE")), number(quote.get("PB_MRQ"))
        if not pb or pb <= 0 or not price or abs(price / pb / book - 1) > 0.05:
            raise ValueError(
                "财报与估值日每股净资产口径不一致，需核对股本变动或权益口径"
            )
        if bank:
            bank_eps = trailing(reports, period, "EPSJB")
            if bank_eps is None or bank_eps <= 0:
                raise ValueError("缺少银行最近四季正的普通股收益")
            normal_roe = bank_eps / book
            info.update(
                nonperforming_loan_pct=r.get("NONPERLOAN"),
                core_tier1_pct=r.get("HXYJBCZL"),
            )
        else:
            margins = []
            for p in sorted(reports, reverse=True):
                if p.endswith("12-31"):
                    revenue = number(reports[p].get("TOTALOPERATEREVE"))
                    recurring = number(reports[p].get("KCFJCXSYJLR"))
                    if revenue and revenue > 0 and recurring is not None:
                        margins.append(recurring / revenue)
            ttm_sales = trailing(reports, period, "TOTALOPERATEREVE")
            if (
                len(margins) < 3
                or not ttm_sales
                or ttm_sales <= 0
                or median(margins[:5]) <= 0
            ):
                raise ValueError("周期企业缺少三个可核验年度的可持续盈利")
            normal_roe = median(margins[:5]) * ttm_sales / shares / book
            info["cycle_margins"] = margins[:5]
        return "银行 PB" if bank else "周期 PB", "PB_MRQ", book, normal_roe, info
    if eps is None or eps <= 0:
        raise ValueError("归母与扣非最近四季盈利未同时为正，无法建立可持续 PE")
    return "正常化 PE", "PE_TTM", eps, normal_roe, info


def peer_bands(panel, code, metric, target_roe):
    by_month = defaultdict(dict)
    for row in panel:
        if row["SECUCODE"] != code:
            by_month[row["TRADE_DATE"][:10]][row["SECUCODE"]] = row
    months = []
    for day, members in sorted(by_month.items()):
        valid = [r for r in members.values() if (number(r.get(metric)) or 0) > 0]
        if len(valid) < 4 or len(valid) < len(members) * 0.5:
            continue
        # PB/PE cancels share price and approximates trailing earnings / latest book.
        matched = [
            r
            for r in valid
            if (number(r.get("PE_TTM")) or 0) > 0 and (number(r.get("PB_MRQ")) or 0) > 0
        ]
        core = valid
        if target_roe is not None and len(matched) >= 12:
            core = sorted(
                matched,
                key=lambda r: (
                    abs(r["PB_MRQ"] / r["PE_TTM"] - target_roe),
                    r["SECUCODE"],
                ),
            )[: max(8, len(matched) // 2)]
        values = [r[metric] for r in core]
        months.append(
            dict(
                date=day,
                count=len(members),
                valid=len(valid),
                core=len(core),
                peer_codes=sorted(r["SECUCODE"] for r in core),
                industry_median=median(r[metric] for r in valid),
                bands=[quantile(values, q) for q in (0.25, 0.50, 0.75)],
            )
        )
    return months


def evaluate(code, day, data):
    quote = data.get("quote") or {}
    traded = str(quote.get("TRADE_DATE") or "")[:10] or None
    result = dict(
        code=code,
        requested_as_of=day,
        as_of=traded or day,
        currency="CNY",
        unit="元/普通股",
        model_version=VERSION,
        industry=quote.get("BOARD_NAME"),
        static=None,
        dynamic=None,
        horizon_trading_days=20,
        dynamic_status="待校准",
        signals={},
        status="依据不足",
        reasons=[],
    )
    flow = (data.get("financing") or [{}])[0]
    flowday = str(flow.get("DATE") or "")[:10]
    cap = number(quote.get("NOTLIMITED_MARKETCAP_A"))
    net = number(flow.get("RZJME5D"))
    financing = (
        net / cap
        if cap
        and cap > 0
        and net is not None
        and flowday
        and traded
        and 0 < (date.fromisoformat(traded) - date.fromisoformat(flowday)).days <= 7
        else None
    )
    market = data.get("market_signal") or {}
    result["signals"] = {
        "market": market if traded and market.get("date") == traded else None,
        "financing_net_5d_over_float_cap": financing,
        "financing_date": flowday or None,
        "sentiment": sentiment(data.get("rating_events", []), traded or day),
        "applied_factors": [],
    }
    if not quote or data.get("stale"):
        result["reasons"] = [data.get("error") or "没有近期可核验的交易日估值数据"]
        return result
    try:
        method, metric, base, roe, financials = fundamentals(quote, data["reports"])
    except ValueError as exc:
        result["reasons"] = [str(exc)]
        return result
    months = peer_bands(data["peers"], code, metric, roe)
    if len(months) < 6 or len({m["date"][:4] for m in months}) < 2:
        result["reasons"] = ["同行有效样本或中性月份不足（至少 4 家、6 个月、跨 2 年）"]
        return result
    multiples = [median(m["bands"][i] for m in months) for i in range(3)]
    band = [round(base * m, 2) for m in multiples]
    if band[0] <= 0:
        result["reasons"] = ["估值区间低于分币精度"]
        return result
    data["matched_months"] = months
    result.update(
        status="静态参考",
        method=method,
        static=dict(zip(("low", "mid", "high"), band)),
        financials=financials,
        base_per_share=base,
        quality_roe=roe,
        multiples=multiples,
        all_peer_median=median(m["industry_median"] for m in months),
        neutral_month_count=len(months),
        peer_count_range=[
            min(m["core"] for m in months),
            max(m["core"] for m in months),
        ],
        confidence="中"
        if len(months) >= 12 and min(m["core"] for m in months) >= 8
        else "有限",
        reasons=[
            "使用上证综指与深证成指作为宽基代理，以过去60日趋势选取中性月；当期行业分类以供应商历史快照为准。",
            "静态区间为同行估值情景；三个动态因子均未通过样本外校准。",
        ],
    )
    return result


def estimate_equity_value(code: str, as_of: str | None = None) -> dict:
    """测算沪深北个股的人民币每股合理估值，按日期返回静态区间、动态验证状态和可复核的 valuation_id。"""
    code = symbol(code)
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.date()
    requested = date.fromisoformat(as_of) if as_of else today
    if requested > today or requested.year < 2000:
        raise ValueError("估值日应为 2000 年起的已到日期")
    cutoff = requested
    if requested == today and now.hour < 16:
        cutoff -= timedelta(days=1)
    try:
        inputs = collect(code, cutoff.isoformat())
    except SourceUnavailable as exc:
        inputs = {"error": str(exc)}
    directory = library() / "valuations" / code / requested.isoformat()
    if inputs.get("error") and directory.is_dir():
        # A transient source outage should not supersede a completed same-day receipt.
        for path in sorted(
            directory.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True
        ):
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != path.stem:
                continue
            previous = json.loads(blob)
            if previous.get("static") and previous.get("model_version") == VERSION:
                return {
                    **previous,
                    "valuation_id": path.stem,
                    "retrieval_note": inputs["error"],
                }
    if inputs.get("reports") and inputs.get("quote"):
        visible = visible_reports(inputs["reports"], inputs["quote"]["TRADE_DATE"][:10])
        inputs["reports"] = list(visible.values())
    result = evaluate(code, requested.isoformat(), inputs)
    apply_validated(result)
    result["input_snapshot"] = snapshot(inputs)
    blob = json.dumps(
        result, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2
    ).encode()
    key = hashlib.sha256(blob).hexdigest()
    save_bytes(directory / (key + ".json"), blob)
    return {**result, "valuation_id": key}
