"""Pure normalizers for company/research upstream records (no I/O)."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

try:  # pandas is an AKShare dependency; keep the helpers usable without it in unit tests.
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


def num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if pd is not None:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def integer(value: Any) -> int | None:
    number = num(value)
    return None if number is None else int(round(number))


def text(value: Any) -> str | None:
    if value is None:
        return None
    if pd is not None:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    result = str(value).strip()
    return result or None


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_COMPACT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def iso_date(value: Any) -> str | None:
    """Accept date/datetime/Timestamp, YYYYMMDD, YYYY-MM-DD or an ISO timestamp."""
    if value is None:
        return None
    if pd is not None:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    match = _DATE_RE.match(raw)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = _COMPACT_RE.match(raw)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def compact_date(value: str) -> str:
    return value.replace("-", "")


def report_name(day: str | None) -> str | None:
    if day is None:
        return None
    suffix = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}
    return suffix.get(day[5:])


def _canonical(digits: Any) -> str | None:
    raw = text(digits)
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


def _market(exchange: str) -> str:
    return {"SH": "沪", "SZ": "深", "BJ": "北"}[exchange]


def _suggest_type(row: dict[str, Any]) -> str | None:
    security_name = text(row.get("SecurityTypeName")) or ""
    classify = text(row.get("Classify")) or ""
    security_type = text(row.get("SecurityType"))
    if security_name == "指数" or classify == "Index":
        return "指数"
    if security_name in {"沪A", "深A", "京A"} or classify in {"AStock", "NEEQ"}:
        return "股票"
    if classify == "Fund" and security_type == "8":
        return "ETF"
    return None


def _suggest_exchange(row: dict[str, Any], kind: str, digits: str) -> str | None:
    security_name = text(row.get("SecurityTypeName")) or ""
    market_type = text(row.get("MarketType")) or ""
    if security_name == "京A" or digits.startswith(("92", "43", "83", "87", "88")):
        return "BJ"
    if kind == "指数":
        if digits.startswith("399"):
            return "SZ"
        if digits.startswith("899"):
            return "BJ"
        return "SH" if market_type == "1" or digits.startswith("000") else "SZ"
    if market_type == "1":
        return "SH"
    if market_type == "2":
        return "SZ"
    if digits.startswith(("5", "6")):
        return "SH"
    if digits.startswith(("0", "1", "3")):
        return "SZ"
    return None


def normalize_suggest(payload: Any) -> list[dict[str, Any]]:
    table = payload.get("QuotationCodeTable") if isinstance(payload, dict) else None
    rows = table.get("Data") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        digits = text(row.get("Code"))
        if digits is None or not digits.isdigit() or len(digits) != 6:
            continue
        kind = _suggest_type(row)
        if kind is None:
            continue
        exchange = _suggest_exchange(row, kind, digits)
        if exchange is None:
            continue
        code = f"{digits}.{exchange}"
        if code in seen:
            continue
        seen.add(code)
        output.append(
            {
                "code": code,
                "name": text(row.get("Name")),
                "market": _market(exchange),
                "type": kind,
                "pinyin": text(row.get("PinYin")),
            }
        )
    return output


def normalize_names(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in rows:
        code = _canonical(row.get("代码"))
        name = text(row.get("名称"))
        if code and name:
            names[code] = name
    return names


# --------------------------------------------------------------------------- financials

_INDICATOR_FIELDS = {
    "revenue_yuan": "TOTALOPERATEREVE",
    "revenue_yoy_pct": "TOTALOPERATEREVETZ",
    "net_profit_yuan": "PARENTNETPROFIT",
    "net_profit_yoy_pct": "PARENTNETPROFITTZ",
    "net_profit_deducted_yuan": "KCFJCXSYJLR",
    "net_profit_deducted_yoy_pct": "KCFJCXSYJLRTZ",
    "eps_yuan": "EPSJB",
    "bps_yuan": "BPS",
    "roe_pct": "ROEJQ",
    "gross_margin_pct": "XSMLL",
    "net_margin_pct": "XSJLL",
    "debt_ratio_pct": "ZCFZL",
    "operating_cash_flow_per_share_yuan": "MGJYXJJE",
    "total_liabilities_yuan": "LIABILITY",
}

_STATEMENT_FIELDS: dict[str, dict[str, str]] = {
    "income": {
        "total_revenue_yuan": "营业总收入",
        "operating_revenue_yuan": "营业收入",
        "operating_cost_yuan": "营业成本",
        "taxes_surcharges_yuan": "营业税金及附加",
        "sales_expense_yuan": "销售费用",
        "admin_expense_yuan": "管理费用",
        "rd_expense_yuan": "研发费用",
        "finance_expense_yuan": "财务费用",
        "operating_profit_yuan": "营业利润",
        "total_profit_yuan": "利润总额",
        "income_tax_yuan": "所得税费用",
        "net_profit_yuan": "净利润",
        "net_profit_parent_yuan": "归属于母公司所有者的净利润",
        "minority_profit_yuan": "少数股东损益",
        "eps_basic_yuan": "基本每股收益",
        "eps_diluted_yuan": "稀释每股收益",
    },
    "balance": {
        "monetary_cash_yuan": "货币资金",
        "accounts_receivable_yuan": "应收账款",
        "inventory_yuan": "存货",
        "current_assets_yuan": "流动资产合计",
        "fixed_assets_yuan": "固定资产净额",
        "intangible_assets_yuan": "无形资产",
        "total_assets_yuan": "资产总计",
        "short_term_loan_yuan": "短期借款",
        "accounts_payable_yuan": "应付账款",
        "current_liabilities_yuan": "流动负债合计",
        "long_term_loan_yuan": "长期借款",
        "total_liabilities_yuan": "负债合计",
        "parent_equity_yuan": "归属于母公司股东权益合计",
        "total_equity_yuan": "所有者权益(或股东权益)合计",
    },
    "cashflow": {
        "sales_cash_yuan": "销售商品、提供劳务收到的现金",
        "operating_inflow_yuan": "经营活动现金流入小计",
        "operating_outflow_yuan": "经营活动现金流出小计",
        "operating_cash_flow_yuan": "经营活动产生的现金流量净额",
        "capex_yuan": "购建固定资产、无形资产和其他长期资产所支付的现金",
        "investing_cash_flow_yuan": "投资活动产生的现金流量净额",
        "financing_cash_flow_yuan": "筹资活动产生的现金流量净额",
        "cash_increase_yuan": "现金及现金等价物净增加额",
        "ending_cash_yuan": "期末现金及现金等价物余额",
    },
}


def normalize_indicators(rows: Iterable[dict[str, Any]], periods: int) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        day = iso_date(row.get("REPORT_DATE"))
        if day is None:
            continue
        item: dict[str, Any] = {
            "report_date": day,
            "report_name": text(row.get("REPORT_DATE_NAME")) or report_name(day),
            "report_type": text(row.get("REPORT_TYPE")),
            "announce_date": iso_date(row.get("NOTICE_DATE")),
            "currency": text(row.get("CURRENCY")),
        }
        for name, column in _INDICATOR_FIELDS.items():
            item[name] = num(row.get(column))
        output.append(item)
    output.sort(key=lambda item: item["report_date"], reverse=True)
    return output[:periods]


def cash_flow_by_date(rows: Iterable[dict[str, Any]]) -> dict[str, float | None]:
    mapping: dict[str, float | None] = {}
    for row in rows:
        day = iso_date(row.get("报告日"))
        if day is not None:
            mapping[day] = num(row.get("经营活动产生的现金流量净额"))
    return mapping


def normalize_statement(
    rows: Iterable[dict[str, Any]], statement: str, periods: int
) -> list[dict[str, Any]]:
    fields = _STATEMENT_FIELDS[statement]
    output = []
    for row in rows:
        day = iso_date(row.get("报告日"))
        if day is None:
            continue
        item: dict[str, Any] = {
            "report_date": day,
            "report_name": report_name(day),
            "announce_date": iso_date(row.get("公告日期")),
            "currency": text(row.get("币种")),
            "audited": text(row.get("是否审计")),
        }
        for name, column in fields.items():
            item[name] = num(row.get(column))
        output.append(item)
    output.sort(key=lambda item: item["report_date"], reverse=True)
    return output[:periods]


# --------------------------------------------------------------------------- valuation

def _window(rows: list[dict[str, Any]], key: str, years: int) -> list[dict[str, Any]]:
    dated = [row for row in rows if row.get(key)]
    if not dated:
        return []
    last = max(row[key] for row in dated)
    try:
        start = last.replace(year=last.year - years)
    except ValueError:
        start = last.replace(year=last.year - years, day=28)
    return [row for row in dated if row[key] > start]


def _parse_day(value: Any) -> date | None:
    iso = iso_date(value)
    return None if iso is None else date.fromisoformat(iso)


def percentile_block(values: Iterable[Any], current: float | None, minimum: int = 60) -> dict[str, Any]:
    kept: list[float] = []
    excluded = 0
    for value in values:
        number = num(value)
        if number is None:
            continue
        if number <= 0:
            excluded += 1
        else:
            kept.append(number)
    block: dict[str, Any] = {"pct": None, "samples": len(kept), "excluded_nonpositive": excluded}
    if current is None:
        block["reason"] = "当前值缺失，无法计算分位"
    elif current <= 0:
        block["reason"] = "当前值非正，无法计算分位"
    elif len(kept) < minimum:
        block["reason"] = "窗口内有效样本不足 60 个，暂不计算分位"
    else:
        block["pct"] = round(sum(1 for value in kept if value <= current) / len(kept) * 100.0, 2)
    return block


def _weekly_last(rows: list[dict[str, Any]], date_key: str) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        day = row.get(date_key)
        if not isinstance(day, date):
            continue
        iso = day.isocalendar()
        buckets[(iso[0], iso[1])] = row
    return [buckets[key] for key in sorted(buckets)]


def _monthly_last(rows: list[dict[str, Any]], date_key: str) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        day = row.get(date_key)
        if not isinstance(day, date):
            continue
        buckets[(day.year, day.month)] = row
    return [buckets[key] for key in sorted(buckets)]


def _cap(rows: list[dict[str, Any]], limit: int = 160) -> tuple[list[dict[str, Any]], int]:
    count = len(rows)
    if count <= limit:
        return rows, 1
    step = math.ceil(count / limit)
    positions = list(range(count - 1, -1, -step))[::-1]
    return [rows[index] for index in positions], step


def _stock_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        day = iso_date(row.get("数据日期"))
        if day is None:
            continue
        output.append(
            {
                "_d": date.fromisoformat(day),
                "date": day,
                "close": num(row.get("当日收盘价")),
                "change_pct": num(row.get("当日涨跌幅")),
                "market_cap_yuan": num(row.get("总市值")),
                "float_cap_yuan": num(row.get("流通市值")),
                "total_shares": num(row.get("总股本")),
                "float_shares": num(row.get("流通股本")),
                "pe_ttm": num(row.get("PE(TTM)")),
                "pe_static": num(row.get("PE(静)")),
                "pb_mrq": num(row.get("市净率")),
                "ps_ttm": num(row.get("市销率")),
            }
        )
    output.sort(key=lambda item: item["_d"])
    return output


def normalize_stock_valuation(rows: Iterable[dict[str, Any]], years: int) -> dict[str, Any] | None:
    parsed = _stock_rows(rows)
    if not parsed:
        return None
    current_row = parsed[-1]
    window = _window(parsed, "_d", years)
    percentile = {
        "pe_ttm_pctile": percentile_block([row["pe_ttm"] for row in window], current_row["pe_ttm"])["pct"],
        "pb_mrq_pctile": percentile_block([row["pb_mrq"] for row in window], current_row["pb_mrq"])["pct"],
        "ps_ttm_pctile": percentile_block([row["ps_ttm"] for row in window], current_row["ps_ttm"])["pct"],
        "pe_ttm_pct": percentile_block([row["pe_ttm"] for row in window], current_row["pe_ttm"])["pct"],
        "pb_mrq_pct": percentile_block([row["pb_mrq"] for row in window], current_row["pb_mrq"])["pct"],
        "ps_ttm_pct": percentile_block([row["ps_ttm"] for row in window], current_row["ps_ttm"])["pct"],
        "window_years": years,
        "samples": len(window),
        "definition": "窗口内不大于当前值的样本占比（0–100），非正值不计入",
    }
    blocks = {
        "pe_ttm": percentile_block([row["pe_ttm"] for row in window], current_row["pe_ttm"]),
        "pb_mrq": percentile_block([row["pb_mrq"] for row in window], current_row["pb_mrq"]),
        "ps_ttm": percentile_block([row["ps_ttm"] for row in window], current_row["ps_ttm"]),
    }
    reasons = {name: block["reason"] for name, block in blocks.items() if "reason" in block}
    if reasons:
        percentile["reasons"] = reasons
    sampled, step = _cap(_weekly_last(window, "_d"))
    series = [
        {
            "date": row["date"],
            "pe_ttm": row["pe_ttm"],
            "pb_mrq": row["pb_mrq"],
            "ps_ttm": row["ps_ttm"],
        }
        for row in sampled
    ]
    current = {key: value for key, value in current_row.items() if key != "_d"}
    current["total_mv_yuan"] = current.get("market_cap_yuan")
    current["float_mv_yuan"] = current.get("float_cap_yuan")
    return {
        "current": current,
        "percentile": percentile,
        "series": series,
        "series_step_weeks": step,
    }


def normalize_baidu_valuation(
    pe_rows: Iterable[dict[str, Any]], pb_rows: Iterable[dict[str, Any]], years: int
) -> dict[str, Any] | None:
    merged: dict[str, dict[str, Any]] = {}
    for rows, field in ((pe_rows, "pe_ttm"), (pb_rows, "pb_mrq")):
        for row in rows:
            day = iso_date(row.get("date"))
            if day is None:
                continue
            merged.setdefault(day, {"_d": date.fromisoformat(day), "date": day})[field] = num(row.get("value"))
    parsed = [merged[key] for key in sorted(merged)]
    if not parsed:
        return None
    current_row = parsed[-1]
    window = _window(parsed, "_d", years)
    blocks = {
        "pe_ttm": percentile_block([row.get("pe_ttm") for row in window], current_row.get("pe_ttm")),
        "pb_mrq": percentile_block([row.get("pb_mrq") for row in window], current_row.get("pb_mrq")),
    }
    percentile: dict[str, Any] = {
        "pe_ttm_pctile": blocks["pe_ttm"]["pct"],
        "pb_mrq_pctile": blocks["pb_mrq"]["pct"],
        "ps_ttm_pctile": None,
        "pe_ttm_pct": blocks["pe_ttm"]["pct"],
        "pb_mrq_pct": blocks["pb_mrq"]["pct"],
        "ps_ttm_pct": None,
        "window_years": years,
        "samples": len(window),
        "definition": "窗口内不大于当前值的样本占比（0–100），非正值不计入",
        "ps_ttm_reason": "该口径不提供市销率",
    }
    reasons = {name: block["reason"] for name, block in blocks.items() if "reason" in block}
    if reasons:
        percentile["reasons"] = reasons
    sampled, step = _cap(_weekly_last(window, "_d"))
    series = [
        {"date": row["date"], "pe_ttm": row.get("pe_ttm"), "pb_mrq": row.get("pb_mrq"), "ps_ttm": None}
        for row in sampled
    ]
    current = {key: value for key, value in current_row.items() if key != "_d"}
    current["total_mv_yuan"] = current.get("market_cap_yuan")
    current["float_mv_yuan"] = current.get("float_cap_yuan")
    return {
        "current": current,
        "percentile": percentile,
        "series": series,
        "series_step_weeks": step,
    }


def normalize_industry_valuation(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any] | None:
    rows = list(rows)
    if not rows:
        return None
    output = []
    for row in rows[:limit]:
        cap = num(row.get("总市值-静态"))
        profit = num(row.get("净利润-静态"))
        output.append(
            {
                "industry_code": text(row.get("行业编码")),
                "industry_name": text(row.get("行业名称")),
                "level": integer(row.get("行业层级")),
                "company_count": integer(row.get("公司数量")),
                "included_company_count": integer(row.get("纳入计算公司数量")),
                "total_market_cap_yuan": None if cap is None else cap * 1e8,
                "total_mv_yuan": None if cap is None else cap * 1e8,
                "net_profit_yuan": None if profit is None else profit * 1e8,
                "pe_static_weighted": num(row.get("静态市盈率-加权平均")),
                "pe_static_median": num(row.get("静态市盈率-中位数")),
                "pe_static_mean": num(row.get("静态市盈率-算术平均")),
            }
        )
    first = rows[0]
    return {
        "date": iso_date(first.get("变动日期")),
        "classification": text(first.get("行业分类")),
        "total_rows": len(rows),
        "rows": output,
    }


_INDEX_VALUE_FIELDS = {
    "pe_static": "静态市盈率",
    "pe_static_median": "静态市盈率中位数",
    "pe_static_equal_weight": "等权静态市盈率",
    "pe_ttm": "滚动市盈率",
    "pe_ttm_median": "滚动市盈率中位数",
    "pe_ttm_equal_weight": "等权滚动市盈率",
}


def _index_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        day = iso_date(row.get("日期"))
        if day is None:
            continue
        item: dict[str, Any] = {
            "_d": date.fromisoformat(day),
            "date": day,
            "index_close": num(row.get("指数")),
        }
        for name, column in _INDEX_VALUE_FIELDS.items():
            item[name] = num(row.get(column))
        output.append(item)
    output.sort(key=lambda item: item["_d"])
    return output


def normalize_index_valuation(rows: Iterable[dict[str, Any]], index_name: str) -> dict[str, Any] | None:
    parsed = _index_rows(rows)
    if not parsed:
        return None
    current_row = parsed[-1]
    window = _window(parsed, "_d", 10)
    blocks = {
        name: percentile_block([row.get(name) for row in window], current_row.get(name))
        for name in ("pe_ttm", "pe_ttm_median", "pe_static")
    }
    percentile: dict[str, Any] = {
        **{f"{name}_pctile": block["pct"] for name, block in blocks.items()},
        **{f"{name}_pct": block["pct"] for name, block in blocks.items()},
        "window_years": 10,
        "samples": len(window),
        "definition": "10 年窗口内不大于当前值的样本占比（0–100），非正值不计入",
    }
    reasons = {name: block["reason"] for name, block in blocks.items() if "reason" in block}
    if reasons:
        percentile["reasons"] = reasons
    sampled, step = _cap(_monthly_last(window, "_d"))
    series = [
        {
            "date": row["date"],
            "pe_ttm": row.get("pe_ttm"),
            "pe_ttm_median": row.get("pe_ttm_median"),
            "pe_static": row.get("pe_static"),
            "index_close": row.get("index_close"),
        }
        for row in sampled
    ]
    current = {key: value for key, value in current_row.items() if key != "_d"}
    return {
        "index": index_name,
        "current": current,
        "percentile": percentile,
        "series": series,
        "series_step_months": step,
    }


def normalize_all_a(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    parsed = []
    for row in rows:
        day = iso_date(row.get("date"))
        if day is None:
            continue
        parsed.append(
            {
                "_d": date.fromisoformat(day),
                "date": day,
                "pe_ttm_median": num(row.get("middlePETTM")),
                "pe_ttm_average": num(row.get("averagePETTM")),
                "pe_static_median": num(row.get("middlePELYR")),
                "pe_static_average": num(row.get("averagePELYR")),
            }
        )
    parsed.sort(key=lambda item: item["_d"])
    if not parsed:
        return None
    current_row = parsed[-1]
    window = _window(parsed, "_d", 10)
    blocks = {
        name: percentile_block([row.get(name) for row in window], current_row.get(name))
        for name in ("pe_ttm_median", "pe_ttm_average")
    }
    percentile: dict[str, Any] = {
        **{f"{name}_pctile": block["pct"] for name, block in blocks.items()},
        **{f"{name}_pct": block["pct"] for name, block in blocks.items()},
        "window_years": 10,
        "samples": len(window),
        "definition": "10 年窗口内不大于当前值的样本占比（0–100），非正值不计入",
    }
    reasons = {name: block["reason"] for name, block in blocks.items() if "reason" in block}
    if reasons:
        percentile["reasons"] = reasons
    sampled, step = _cap(_monthly_last(window, "_d"))
    series = [
        {
            "date": row["date"],
            "pe_ttm_median": row.get("pe_ttm_median"),
            "pe_ttm_average": row.get("pe_ttm_average"),
            "pe_static_median": row.get("pe_static_median"),
        }
        for row in sampled
    ]
    current = {key: value for key, value in current_row.items() if key != "_d"}
    return {
        "current": current,
        "percentile": percentile,
        "series": series,
        "series_step_months": step,
    }


# --------------------------------------------------------------------------- consensus / reports

RATING_KEYS = {
    "buy": "买入",
    "overweight": "增持",
    "neutral": "中性",
    "underweight": "减持",
    "sell": "卖出",
}

_YEAR_EPS_RE = re.compile(r"^(\d{4})预测每股收益$")


def normalize_consensus_em(rows: Iterable[dict[str, Any]], digits: str) -> dict[str, Any] | None:
    for row in rows:
        raw = text(row.get("代码"))
        if raw is None or raw.zfill(6) != digits:
            continue
        eps = []
        for column, value in row.items():
            match = _YEAR_EPS_RE.match(str(column))
            number = num(value) if match else None
            if match and number is not None:
                eps.append({"year": int(match.group(1)), "eps_yuan": number})
        eps.sort(key=lambda item: item["year"])
        counts = {
            key: integer(row.get(f"机构投资评级(近六个月)-{label}")) for key, label in RATING_KEYS.items()
        }
        return {
            "code": f"{digits}.{_exchange_for(digits)}",
            "name": text(row.get("名称")),
            "report_count": integer(row.get("研报数")),
            "rating_counts": counts,
            "eps_forecast": eps,
        }
    return None


def _exchange_for(digits: str) -> str:
    canonical = _canonical(digits)
    return "SH" if canonical is None else canonical.split(".")[1]


def normalize_consensus_ths(rows: Iterable[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    factor = 1.0 if kind == "eps" else 1e8
    output = []
    for row in rows:
        year = integer(row.get("年度"))
        if year is None:
            continue
        output.append(
            {
                "year": year,
                "analysts": integer(row.get("预测机构数")),
                "min": None if num(row.get("最小值")) is None else num(row.get("最小值")) * factor,
                "mean": None if num(row.get("均值")) is None else num(row.get("均值")) * factor,
                "max": None if num(row.get("最大值")) is None else num(row.get("最大值")) * factor,
            }
        )
    output.sort(key=lambda item: item["year"])
    return output


def consensus_disagrees(eps: list[dict[str, Any]], ths: list[dict[str, Any]], threshold: float) -> bool:
    primary = {item["year"]: item["eps_yuan"] for item in eps}
    for item in ths:
        mean = item.get("mean")
        base = primary.get(item["year"])
        if mean is None or base is None:
            continue
        if base == 0:
            if mean != 0:
                return True
            continue
        if abs(base - mean) / abs(base) > threshold:
            return True
    return False


def normalize_ratings(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any]:
    output = []
    for row in rows:
        day = iso_date(row.get("评级日期"))
        output.append(
            {
                "date": day,
                "org": text(row.get("评级机构")),
                "analyst": text(row.get("分析师")),
                "rating": text(row.get("最新评级")),
                "target_price_yuan": num(row.get("目标价")),
            }
        )
    output = [item for item in output if item["date"] is not None]
    output.sort(key=lambda item: item["date"] or "", reverse=True)
    return {
        "count": min(limit, len(output)),
        "total_available": len(output),
        "rows": output[:limit],
    }


_REPORT_FORECAST_RE = re.compile(r"^(\d{4})-盈利预测-(收益|市盈率)$")


def normalize_reports(rows: Iterable[dict[str, Any]], limit: int) -> dict[str, Any]:
    output = []
    for row in rows:
        day = iso_date(row.get("日期"))
        if day is None:
            continue
        forecasts: dict[str, dict[str, float | None]] = {}
        for column, value in row.items():
            match = _REPORT_FORECAST_RE.match(str(column))
            number = num(value) if match else None
            if match and number is not None:
                year = int(match.group(1))
                forecasts.setdefault(f"{year}", {})["eps_yuan" if match.group(2) == "收益" else "pe"] = number
        output.append(
            {
                "date": day,
                "title": text(row.get("报告名称")),
                "org": text(row.get("机构")),
                "rating": text(row.get("东财评级")),
                "forecasts": forecasts,
                "untrusted_text": True,
            }
        )
    output.sort(key=lambda item: item["date"] or "", reverse=True)
    selected = output[:limit]
    return {
        "count": len(selected),
        "total_available": len(output),
        "untrusted_text": True,
        "reports": selected,
    }
