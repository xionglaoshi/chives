"""The 17 read-only tools: schemas, argument validation, upstream mapping and client-side row caps."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from fmp_mcp.client import FmpClient
from fmp_mcp.envelope import envelope

SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-^]{1,15}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIODS = ("annual", "quarter")
MAX_ROWS_WITHOUT_LIMIT = 200
PLAN_RESTRICTED_HINT = "上游可能按套餐返回 plan_restricted（如内部人交易、非美交易所行情）。"


class InvalidArgument(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    description: str
    required: bool = False
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None
    enum: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ToolDef:
    name: str
    path: str
    description: str
    params: tuple[Param, ...]
    build: Callable[[dict[str, Any]], dict[str, Any]]
    note_fn: Callable[[list[Any], dict[str, Any]], list[str]]
    quote: bool = False

    def schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for param in self.params:
            prop: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum is not None:
                prop["enum"] = list(param.enum)
            if param.minimum is not None:
                prop["minimum"] = param.minimum
            if param.maximum is not None:
                prop["maximum"] = param.maximum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
        return {
            "type": "object",
            "properties": properties,
            "required": [p.name for p in self.params if p.required],
            "additionalProperties": False,
        }


# --------------------------------------------------------------------- validation
def _text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidArgument(f"{name} 必须是非空字符串")
    return value.strip()


def _symbol(args: dict[str, Any]) -> str:
    value = _text(args, "symbol")
    if not SYMBOL_PATTERN.fullmatch(value):
        raise InvalidArgument("symbol 必须匹配 ^[A-Za-z0-9.\\-^]{1,15}$")
    return value.upper()


def _integer(args: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
    value = args.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidArgument(f"{name} 必须是整数")
    if not low <= value <= high:
        raise InvalidArgument(f"{name} 必须在 {low}–{high} 之间")
    return value


def _period(args: dict[str, Any]) -> str:
    value = args.get("period")
    if value is None:
        return "annual"
    if not isinstance(value, str) or value.lower() not in PERIODS:
        raise InvalidArgument("period 只能是 annual 或 quarter")
    return value.lower()


def _day(args: dict[str, Any], name: str) -> date:
    value = args.get(name)
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise InvalidArgument(f"{name} 必须是 YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidArgument(f"{name} 不是有效日期") from exc


def _range(args: dict[str, Any], max_days: int | None, *, years: int | None = None) -> dict[str, str]:
    start = _day(args, "from_date")
    end = _day(args, "to_date")
    if end < start:
        raise InvalidArgument("to_date 不能早于 from_date")
    if max_days is not None and (end - start).days > max_days:
        raise InvalidArgument(f"日期区间不能超过 {max_days} 天")
    if years is not None:
        try:
            ceiling = start.replace(year=start.year + years)
        except ValueError:
            ceiling = start.replace(year=start.year + years, day=28)
        if end > ceiling:
            raise InvalidArgument(f"日期区间不能超过 {years} 年")
    return {"from": start.isoformat(), "to": end.isoformat()}


def _statement_params(args: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": _symbol(args), "period": _period(args), "limit": _integer(args, "limit", 1, 40, 5)}


def _estimate_params(args: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": _symbol(args), "period": _period(args), "limit": _integer(args, "limit", 1, 40, 5)}


def _search_params(args: dict[str, Any]) -> dict[str, Any]:
    query = _text(args, "query")
    if len(query) > 100:
        raise InvalidArgument("query 长度不能超过 100")
    return {"query": query, "limit": _integer(args, "limit", 1, 50, 10)}


def _symbol_params(args: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": _symbol(args)}


def _graded_params(args: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": _symbol(args), "limit": _integer(args, "limit", 1, 100, 5)}


def _earnings_params(args: dict[str, Any]) -> dict[str, Any]:
    return _range(args, 90)


def _price_params(args: dict[str, Any]) -> dict[str, Any]:
    window = _range(args, None, years=5)
    return {"symbol": _symbol(args), **window}


# ------------------------------------------------------------------------- notes
def _quote_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["报价是上游快照；as_of 是本地请求时间，行内 timestamp 才是上游时间。"]


def _search_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["检索结果按上游顺序原样返回；超出 limit 的行在客户端截断。"]


def _profile_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["公司资料字段与币种以上游原值为准，未换算为美元。"]


def _statement_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    currencies = sorted(
        {str(row.get("reportedCurrency")) for row in rows if isinstance(row, dict) and row.get("reportedCurrency")}
    )
    if currencies:
        note = f"金额为 reportedCurrency 的原始值，未做汇率换算；本次响应币种：{', '.join(currencies)}。"
        if any(code.upper() != "USD" for code in currencies):
            note += "其中包含非美元报表，金额不是美元。"
    else:
        note = "金额为上游原值；reportedCurrency 缺失，币种未确认。"
    return [
        note,
        "period=annual 表示年度报表、quarter 表示季度报表；行内 period 字段（如 FY、Q1）是上游原始标签。",
        "fiscalYear 是财年标签，date 是财报期末日期（YYYY-MM-DD），两者含义不同。",
    ]


def _estimate_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return [
        "period=annual/quarter 是请求的估计频率；估计值为上游一致预期，可能随上游更新。",
        "fiscalYear/date 分别为财年标签与期末日期，数值未做单位换算。",
    ]


def _price_target_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["目标价为上游汇总口径原值，单位与币种以上游字段为准。"]


def _grades_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["评级记录按上游顺序原样返回；评级文本是第三方观点，不构成投资建议。"]


def _insider_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["内部人交易为上游原样记录；金额与股数未做单位换算。"]


def _earnings_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return [
        "from_date/to_date 是自然日闭区间（≤90 天），已映射为上游 from/to 参数。",
        "日期为上游公告的计划/实际日期，可能变更。",
    ]


def _historical_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["价格为上游 /historical-price-eod/full 原样返回；复权口径未确认（本包不改写任何数值）。"]


def _shares_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["股本与流通股为上游原值，单位以上游字段为准。"]


def _peers_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return ["同业列表由上游按其口径生成，包含同一交易所/行业/市值区间的公司。"]


def _ratios_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return [
        "比率为上游按 reportedCurrency 报表计算的原值，未做换算；口径见上游字段名。",
        "fiscalYear 是财年标签，date 是期末日期。",
    ]


def _metrics_notes(rows: list[Any], params: dict[str, Any]) -> list[str]:
    return [
        "关键指标为上游按 reportedCurrency 报表计算的原值，未做换算。",
        "fiscalYear 是财年标签，date 是期末日期。",
    ]


# --------------------------------------------------------------------- tool table
_SYMBOL = Param("symbol", "string", "美股代码，如 AAPL；允许字母数字 . - ^，最长 15，自动转大写", required=True)
_PERIOD = Param("period", "string", "报表频率", default="annual", enum=PERIODS)
_LIMIT_40 = Param("limit", "integer", "返回期数", default=5, minimum=1, maximum=40)

TOOLS: tuple[ToolDef, ...] = (
    ToolDef(
        "fmp_search_symbol",
        "/stable/search-symbol",
        "Read-only FMP symbol search by ticker or ticker fragment. 按代码或代码片段搜索，按公司名请用 fmp_search_name。",
        (
            Param("query", "string", "代码或代码片段", required=True),
            Param("limit", "integer", "最多返回行数", default=10, minimum=1, maximum=50),
        ),
        _search_params,
        _search_notes,
    ),
    ToolDef(
        "fmp_search_name",
        "/stable/search-name",
        "Read-only FMP company-name search (e.g. apple). 按公司名搜索，返回匹配公司的代码与名称。",
        (
            Param("query", "string", "公司名或其中一部分", required=True),
            Param("limit", "integer", "最多返回行数", default=10, minimum=1, maximum=50),
        ),
        _search_params,
        _search_notes,
    ),
    ToolDef(
        "fmp_get_quote",
        "/stable/quote",
        "Read-only real-time-ish US quote snapshot from FMP. Cached for 15 seconds.",
        (_SYMBOL,),
        _symbol_params,
        _quote_notes,
        quote=True,
    ),
    ToolDef(
        "fmp_get_profile",
        "/stable/profile",
        "Read-only company profile (name, sector, market cap, currency) from FMP.",
        (_SYMBOL,),
        _symbol_params,
        _profile_notes,
    ),
    ToolDef(
        "fmp_get_income_statement",
        "/stable/income-statement",
        "Read-only income statements from FMP, annual or quarterly.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _statement_params,
        _statement_notes,
    ),
    ToolDef(
        "fmp_get_balance_sheet",
        "/stable/balance-sheet-statement",
        "Read-only balance sheet statements from FMP, annual or quarterly.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _statement_params,
        _statement_notes,
    ),
    ToolDef(
        "fmp_get_cash_flow",
        "/stable/cash-flow-statement",
        "Read-only cash flow statements from FMP, annual or quarterly.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _statement_params,
        _statement_notes,
    ),
    ToolDef(
        "fmp_get_ratios",
        "/stable/ratios",
        "Read-only financial ratios from FMP, annual or quarterly.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _statement_params,
        _ratios_notes,
    ),
    ToolDef(
        "fmp_get_key_metrics",
        "/stable/key-metrics",
        "Read-only key metrics (market cap, enterprise value, etc.) from FMP.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _statement_params,
        _metrics_notes,
    ),
    ToolDef(
        "fmp_get_analyst_estimates",
        "/stable/analyst-estimates",
        "Read-only analyst consensus estimates (revenue, EPS) from FMP.",
        (_SYMBOL, _PERIOD, _LIMIT_40),
        _estimate_params,
        _estimate_notes,
    ),
    ToolDef(
        "fmp_get_price_target",
        "/stable/price-target-summary",
        "Read-only analyst price target summary from FMP.",
        (_SYMBOL,),
        _symbol_params,
        _price_target_notes,
    ),
    ToolDef(
        "fmp_get_analyst_grades",
        "/stable/grades",
        "Read-only analyst grade changes from FMP.",
        (
            _SYMBOL,
            Param("limit", "integer", "最多返回行数", default=5, minimum=1, maximum=100),
        ),
        _graded_params,
        _grades_notes,
    ),
    ToolDef(
        "fmp_get_insider_trades",
        "/stable/insider-trading/search",
        "Read-only insider trading records from FMP.",
        (
            _SYMBOL,
            Param("limit", "integer", "最多返回行数", default=5, minimum=1, maximum=100),
        ),
        _graded_params,
        _insider_notes,
    ),
    ToolDef(
        "fmp_get_earnings_calendar",
        "/stable/earnings-calendar",
        "Read-only US earnings calendar for a date window of at most 90 days.",
        (
            Param("from_date", "string", "起始日 YYYY-MM-DD", required=True),
            Param("to_date", "string", "结束日 YYYY-MM-DD（含）", required=True),
        ),
        _earnings_params,
        _earnings_notes,
    ),
    ToolDef(
        "fmp_get_historical_prices",
        "/stable/historical-price-eod/full",
        "Read-only end-of-day OHLCV history from FMP for a window of at most 5 years.",
        (
            _SYMBOL,
            Param("from_date", "string", "起始日 YYYY-MM-DD", required=True),
            Param("to_date", "string", "结束日 YYYY-MM-DD（含）", required=True),
        ),
        _price_params,
        _historical_notes,
    ),
    ToolDef(
        "fmp_get_shares_float",
        "/stable/shares-float",
        "Read-only share float and outstanding shares from FMP.",
        (_SYMBOL,),
        _symbol_params,
        _shares_notes,
    ),
    ToolDef(
        "fmp_get_stock_peers",
        "/stable/stock-peers",
        "Read-only peer company list from FMP.",
        (_SYMBOL,),
        _symbol_params,
        _peers_notes,
    ),
)

BY_NAME: dict[str, ToolDef] = {tool.name: tool for tool in TOOLS}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _row_limit(tool: ToolDef, params: dict[str, Any]) -> int:
    if any(param.name == "limit" for param in tool.params):
        return int(params["limit"])
    return MAX_ROWS_WITHOUT_LIMIT


def dispatch(name: str, arguments: dict[str, Any] | None, client: FmpClient) -> dict[str, Any]:
    tool = BY_NAME.get(name)
    if tool is None:
        return envelope(
            endpoint=name,
            status="error",
            error={"code": "unknown_tool", "message": f"未知工具：{name}"},
        )
    if arguments is not None and not isinstance(arguments, dict):
        return envelope(
            endpoint=name,
            status="error",
            error={"code": "invalid_argument", "message": "arguments 必须是对象"},
        )
    try:
        params = tool.build(arguments or {})
    except InvalidArgument as exc:
        return envelope(
            endpoint=name,
            status="error",
            error={"code": "invalid_argument", "message": str(exc)},
        )
    result = client.get_rows(tool.path, params, quote=tool.quote)
    if result.error is not None:
        return envelope(
            endpoint=name,
            status="error",
            error={"code": result.error.code, "message": result.error.message},
        )
    if not result.rows:
        return envelope(
            endpoint=name,
            status="empty",
            rows=[],
            notes=[f"上游 {tool.path} 返回空数组。"],
        )
    notes = [f"数据来自 FMP {tool.path}，行内容原样返回，未改数值；as_of 是本地请求时间。"]
    limit = _row_limit(tool, params)
    available = len(result.rows)
    rows = result.rows[:limit]
    truncated = available > len(rows)
    notes.extend(tool.note_fn(rows, params))
    if truncated:
        notes.append(f"上游实际返回 {available} 行，客户端已截断为 {len(rows)} 行（上限 {limit}）。")
    return envelope(
        endpoint=name,
        status="ready",
        rows=rows,
        notes=_dedupe(notes),
        available=available,
        truncated=truncated,
    )
