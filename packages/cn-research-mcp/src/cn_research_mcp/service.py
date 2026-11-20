"""Validation, caching, unit conversion and envelopes behind the nineteen tools."""

from __future__ import annotations

import logging
import math
import re
import threading
from collections.abc import Callable
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from cn_research_mcp import calc, textproc
from cn_research_mcp.envelope import envelope
from cn_research_mcp.infra import (
    BIG_TABLE_TIMEOUT,
    DEFAULT_TIMEOUT,
    TTLCache,
    UpstreamClient,
    UpstreamError,
)
from cn_research_mcp.sources import ENDPOINTS, Sources, supported_index_names
from cn_research_mcp.symbols import InvalidSymbol, Symbol, UnsupportedMarket, normalize_symbol

logger = logging.getLogger(__name__)

BIG_TTL = 30 * 60
STOCK_TTL = 10 * 60
NEWS_TTL = 5 * 60
FLASH_TTL = 30
EVENT_TTL = 10 * 60
_CN_TZ = timezone(timedelta(hours=8))

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
EVENT_DEFAULT_LIMIT = 50
EVENT_MAX_LIMIT = 200
STOCK_NEWS_DEFAULT_LIMIT = 10
STOCK_NEWS_MAX_LIMIT = 20
FLASH_DEFAULT_LIMIT = 20
FLASH_MAX_LIMIT = 50
IRM_DEFAULT_LIMIT = 10
IRM_MAX_LIMIT = 30
FLASH_SOURCES = ("cls", "em")
FLASH_KEYWORD_MAX = 20
SUMMARY_MAX = 300
BODY_MAX = 400
QUESTION_MAX = 300
ANSWER_MAX = 500
SUSPENSION_REASON_MAX = 500
SUSPENSION_NAME_MAX = 100
INDUSTRY_DEFAULT_LIMIT = 40
INDUSTRY_MAX_LIMIT = 200
VALUATION_DEFAULT_YEARS = 3
VALUATION_MAX_YEARS = 8
INDEX_WINDOW_YEARS = 10
INDUSTRY_FALLBACK_DAYS = 5
STALE_DAYS = 10
DISAGREE_THRESHOLD = 0.10
EARNINGS_KINDS = ("forecast", "express", "report")
PERIOD_RE = re.compile(r"^(\d{4})-(03-31|06-30|09-30|12-31)$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
BOND_CODE_RE = re.compile(r"^\d{6}$")
CB_LIST_DEFAULT_LIMIT = 50
CB_LIST_MAX_LIMIT = 500
CB_QUOTE_MAX_CODES = 20
CB_QUOTE_TTL = 30
INDEX_BARS_DEFAULT_LIMIT = 250
INDEX_BARS_MAX_LIMIT = 750
INDEX_CONS_DEFAULT_LIMIT = 500
INDEX_CONS_MAX_LIMIT = 1000
HOLDER_VIEWS = ("top10_float", "funds")
FUNDS_DEFAULT_LIMIT = 20
FUNDS_MAX_LIMIT = 50
HOLDER_PERIOD_LOOKBACK = 5
SEGMENT_BY = {"product": "按产品分类", "region": "按地区分类", "industry": "按行业分类"}
INDEX_VOLUME_LOT_SIZE = 100

# Daily index bars: Eastmoney's kline volume is in lots (1 lot = 100 shares) and amount is in yuan.
# Verified on 2026-11-16 against market-watch /overview's amount_yuan for 000300.SH (see README);
# set to False if a future re-check fails, which keeps the raw values and marks them "unconfirmed".
INDEX_UNITS_CONFIRMED = False
INDEX_UNITS_EVIDENCE = "runtime comparison with a same-day public amount is pending"

# Index universe for cn_get_index_bars / cn_get_index_constituents. Only these are accepted.
INDEX_UNIVERSE: dict[str, dict[str, str]] = {
    "000001.SH": {"name": "上证指数", "symbol": "sh000001", "digits": "000001"},
    "399001.SZ": {"name": "深证成指", "symbol": "sz399001", "digits": "399001"},
    "399006.SZ": {"name": "创业板指", "symbol": "sz399006", "digits": "399006"},
    "000300.SH": {"name": "沪深300", "symbol": "sh000300", "digits": "000300"},
    "000905.SH": {"name": "中证500", "symbol": "sh000905", "digits": "000905"},
    "000852.SH": {"name": "中证1000", "symbol": "sh000852", "digits": "000852"},
    "000688.SH": {"name": "科创50", "symbol": "sh000688", "digits": "000688"},
    "000016.SH": {"name": "上证50", "symbol": "sh000016", "digits": "000016"},
}
_INDEX_BY_NAME = {spec["name"]: canonical for canonical, spec in INDEX_UNIVERSE.items()}
_INDEX_BY_DIGITS = {spec["digits"]: canonical for canonical, spec in INDEX_UNIVERSE.items()}
# The csindex constituent file endpoint has no files for the two Shenzhen index codes; documented in README.
CONSTITUENTS_UNSUPPORTED = {
    "399001.SZ": "csindex does not publish a constituent file for 深证成指",
    "399006.SZ": "csindex does not publish a constituent file for 创业板指",
}
INDEX_CANDIDATES = (
    "全A",
    "上证50",
    "沪深300",
    "中证500",
    "中证1000",
    "创业板50",
    "上证380",
    "上证180",
    "深证红利",
    "深证100",
    "上证红利",
    "中证100",
    "中证800",
)
RATING_KEYS = {
    "buy": "买入",
    "overweight": "增持",
    "neutral": "中性",
    "underweight": "减持",
    "sell": "卖出",
}
YEAR_EPS_RE = re.compile(r"^(\d{4})预测每股收益$")
CHANGE_RANGE_RE = re.compile(
    r"同比上年(增长|下降|降低|变动):\s*(-?\d+(?:\.\d+)?)%(?:至(-?\d+(?:\.\d+)?)%)?"
)

SOURCE_LABELS = {
    "consensus": "eastmoney",
    "ratings": "sina",
    "reports": "eastmoney",
    "valuation": "eastmoney",
    "industry": "cninfo",
    "index": "legulegu",
    "earnings": "eastmoney",
    "schedule": "eastmoney",
    "stock_news": "eastmoney",
    "flash_cls": "cls",
    "flash_em": "eastmoney",
    "calendar": "baidu",
    "suspensions": "eastmoney",
    "irm": "cninfo",
    "cb_list": "eastmoney",
    "cb_quote": "sina",
    "index_bars": "eastmoney",
    "index_constituents": "csindex",
    "holders_top10": "eastmoney",
    "holders_funds": "sina",
    "business_segments": "eastmoney",
}


class ArgumentError(ValueError):
    pass


def _need(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise UpstreamError("upstream_error", f"upstream response is missing columns: {missing}")


def _int_arg(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArgumentError(f"{name} must be an integer between {low} and {high}")
    if not low <= value <= high:
        raise ArgumentError(f"{name} must be between {low} and {high}")
    return value


def _symbol_arg(code: Any) -> Symbol:
    try:
        return normalize_symbol(code)
    except UnsupportedMarket as exc:
        raise _Unsupported(str(exc)) from exc
    except InvalidSymbol as exc:
        raise ArgumentError(str(exc)) from exc


class _Unsupported(ValueError):
    pass


def _period_arg(period: Any) -> str:
    if not isinstance(period, str) or PERIOD_RE.match(period.strip()) is None:
        raise ArgumentError("period must be a report period: YYYY-03-31, YYYY-06-30, YYYY-09-30 or YYYY-12-31")
    text = period.strip()
    year = int(text[:4])
    if not 2000 <= year <= 2100:
        raise ArgumentError("period year must be between 2000 and 2100")
    return text


def _date_arg(name: str, value: Any) -> date_type:
    if not isinstance(value, str) or DATE_RE.match(value.strip()) is None:
        raise ArgumentError(f"{name} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ArgumentError(f"{name} is not a real calendar date") from exc


def _text_arg(name: str, value: Any, max_chars: int | None = None) -> str:
    if not isinstance(value, str):
        raise ArgumentError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise ArgumentError(f"{name} must not be empty")
    if max_chars is not None and len(text) > max_chars:
        raise ArgumentError(f"{name} must be at most {max_chars} characters")
    return text


def _keyword_arg(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArgumentError("keyword must be a string")
    text = value.strip()
    if not text:
        return None
    if len(text) > FLASH_KEYWORD_MAX:
        raise ArgumentError(f"keyword must be at most {FLASH_KEYWORD_MAX} characters")
    return text


def _since_arg(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, (str, datetime, date_type)):
        raise ArgumentError("since must be an ISO8601 time")
    moment = textproc.to_datetime(value)
    if moment is None:
        raise ArgumentError("since must be an ISO8601 time")
    return moment


def _importance_arg(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArgumentError("min_importance must be a number")
    if not math.isfinite(float(value)):
        raise ArgumentError("min_importance must be a finite number")
    return float(value)


def _timestamp(value: str | None) -> float:
    if value is None:
        return float("-inf")
    moment = textproc.to_datetime(value)
    return float("-inf") if moment is None else moment.timestamp()


def _warn_once(warnings: list[str], code: str) -> None:
    if code not in warnings:
        warnings.append(code)


def _parse_time_field(value: Any, warnings: list[str]) -> str | None:
    parsed = textproc.parse_time(value)
    if parsed is None:
        _warn_once(warnings, "time_unparsed")
    return parsed


def _parse_date_field(value: Any, warnings: list[str]) -> str | None:
    if textproc.is_missing(value):
        return None
    parsed = textproc.parse_date(value)
    if parsed is None:
        _warn_once(warnings, "time_unparsed")
    return parsed


def _suspend_code(value: Any) -> str | None:
    text = calc.ftext(value)
    if text is None:
        return None
    text = text.strip()
    if isinstance(value, str):
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        if text.isdigit():
            # A string code must already be a full 6-digit A-share code: 5-digit strings are
            # Hong Kong codes and must not be zero-padded into a fake Shenzhen code.
            if len(text) != 6:
                return None
        else:
            try:
                return normalize_symbol(text).canonical
            except (InvalidSymbol, UnsupportedMarket):
                return None
    else:
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        if text.isdigit():
            text = text.zfill(6)
    try:
        return normalize_symbol(text).canonical
    except (InvalidSymbol, UnsupportedMarket):
        return None


def _dedupe_exact(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    kept: list[dict[str, Any]] = []
    for item in entries:
        key = (item.get("title"), item.get("published_at"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _region_matches(region: str, row: pd.Series) -> bool:
    wanted = region.casefold()
    for column in ("地区", "国家"):
        text, _ = textproc.clean_text(_get(row, column))
        if text and wanted in text.casefold():
            return True
    return False


def _yyyymmdd(text: str) -> str:
    return text.replace("-", "")


def _canonical(digits: Any) -> str | None:
    text = calc.ftext(digits)
    if text is None:
        return None
    text = text.zfill(6)
    if text.startswith("6"):
        return f"{text}.SH"
    if text.startswith(("0", "3")):
        return f"{text}.SZ"
    return f"{text}.BJ"


def _digits_equal(series: pd.Series, digits: str) -> pd.Series:
    return series.astype(str).str.strip().str.zfill(6) == digits


def _index_arg(value: Any) -> tuple[str, dict[str, str]]:
    """Accept a whitelist name, NNNNNN or NNNNNN.SH/SZ; return canonical code and metadata."""
    if not isinstance(value, str):
        raise ArgumentError("index must be a string")
    text = value.strip()
    if text in _INDEX_BY_NAME:
        canonical = _INDEX_BY_NAME[text]
        return canonical, INDEX_UNIVERSE[canonical]
    upper = text.upper()
    if upper.startswith(("SH", "SZ")) and upper[2:].isdigit() and len(upper) == 8:
        upper = f"{upper[2:]}.{upper[:2]}"
    if upper.isdigit() and len(upper) == 6:
        canonical = _INDEX_BY_DIGITS.get(upper)
    else:
        canonical = upper
    if canonical not in INDEX_UNIVERSE:
        allowed = ", ".join(f"{spec['name']} ({code})" for code, spec in INDEX_UNIVERSE.items())
        raise ArgumentError(f"index must be one of: {allowed}")
    return canonical, INDEX_UNIVERSE[canonical]


def _bond_codes_arg(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ArgumentError("bond_codes must be an array of 1-20 six-digit strings")
    if not 1 <= len(value) <= CB_QUOTE_MAX_CODES:
        raise ArgumentError(f"bond_codes must contain 1-{CB_QUOTE_MAX_CODES} codes")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or BOND_CODE_RE.match(item.strip()) is None:
            raise ArgumentError("every bond code must be a six-digit string")
        codes.append(item.strip())
    return codes


def _code_digits(value: Any) -> str | None:
    text = calc.ftext(value)
    if text is None:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else None


def _bond_code(value: Any) -> str | None:
    digits = _code_digits(value)
    return digits if digits is not None and len(digits) == 6 else None


def _market_of(exchange: Any, canonical: str | None) -> str | None:
    text = calc.ftext(exchange) or ""
    if "北京" in text or (canonical or "").endswith(".BJ"):
        return "bj"
    if "深圳" in text or (canonical or "").endswith(".SZ"):
        return "sz"
    if "上海" in text or (canonical or "").endswith(".SH"):
        return "sh"
    return None


def _sort_desc_by_date(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    keys = pd.to_datetime(frame[column], errors="coerce")
    order = keys.sort_values(ascending=False, kind="mergesort", na_position="last").index
    return frame.loc[order]


class ResearchService:
    def __init__(
        self,
        sources: Any | None = None,
        client: UpstreamClient | None = None,
        cache: TTLCache | None = None,
        today: Callable[[], date_type] | None = None,
        index_names: tuple[str, ...] | None = None,
        now: Callable[[], datetime] | None = None,
        index_units_confirmed: bool = INDEX_UNITS_CONFIRMED,
    ) -> None:
        self.sources = sources if sources is not None else Sources()
        self.client = client or UpstreamClient()
        self.cache = cache or TTLCache()
        self._today = today or (lambda: datetime.now(_CN_TZ).date())
        self._now = now or (lambda: datetime.now(_CN_TZ))
        self.index_units_confirmed = index_units_confirmed
        self.index_names = (
            index_names if index_names is not None else supported_index_names(INDEX_CANDIDATES)
        )
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing
    def _load(self, method: str, args: tuple = (), *, ttl: float, timeout: float) -> pd.DataFrame:
        key = (method, *args)
        with self._lock:
            hit, value = self.cache.get(key)
            if hit:
                return value
            endpoint = ENDPOINTS[method]
            fetch = getattr(self.sources, method)
            frame = self.client.call(endpoint.host, lambda: fetch(*args), timeout)
            if not isinstance(frame, pd.DataFrame):
                raise UpstreamError("upstream_error", "upstream returned a non-table payload")
            self.cache.set(key, frame, ttl)
            return frame

    def _load_stamped(
        self, method: str, args: tuple = (), *, ttl: float, timeout: float
    ) -> tuple[pd.DataFrame, datetime]:
        """Load a table and the wall-clock time it was fetched (cached alongside the table)."""
        stamp_key = ("_fetched_at", method, *args)
        with self._lock:
            hit, stamp = self.cache.get(stamp_key)
        frame = self._load(method, args, ttl=ttl, timeout=timeout)
        if not hit or not isinstance(stamp, datetime):
            stamp = self._now()
            self.cache.set(stamp_key, stamp, ttl)
        return frame, stamp

    def _run(self, source: str, body: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return body()
        except ArgumentError as exc:
            return envelope(source=source, status="error", error_code="invalid_argument", error_message=str(exc))
        except _Unsupported as exc:
            return envelope(source=source, status="error", error_code="unsupported_market", error_message=str(exc))
        except UpstreamError as exc:
            return envelope(source=source, status="error", error_code=exc.code, error_message=exc.message)
        except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
            logger.warning("unexpected upstream shape: %s", type(exc).__name__)
            return envelope(
                source=source,
                status="error",
                error_code="upstream_error",
                error_message=f"unexpected upstream data shape ({type(exc).__name__})",
            )

    # ------------------------------------------------------------------ 1. consensus
    def cn_get_consensus(self, code: Any) -> dict[str, Any]:
        source = SOURCE_LABELS["consensus"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            table = self._load("profit_forecast_em", ttl=BIG_TTL, timeout=BIG_TABLE_TIMEOUT)
            _need(table, ["代码", "名称", "研报数", *[f"机构投资评级(近六个月)-{v}" for v in RATING_KEYS.values()]])
            rows = table[_digits_equal(table["代码"], sym.digits)]
            if rows.empty:
                return envelope(source=source, status="empty", data={"code": sym.canonical, "reason": "no_coverage"})
            row = rows.iloc[0]
            eps: list[dict[str, Any]] = []
            for column in table.columns:
                match = YEAR_EPS_RE.match(str(column))
                value = calc.fnum(row[column]) if match else None
                if match and value is not None:
                    eps.append({"year": int(match.group(1)), "eps_yuan": value, "source": "eastmoney"})
            eps.sort(key=lambda item: item["year"])
            report_count = calc.fint(row["研报数"]) or 0
            if report_count == 0 and not eps:
                return envelope(source=source, status="empty", data={"code": sym.canonical, "reason": "no_coverage"})
            counts = {key: calc.fint(row[f"机构投资评级(近六个月)-{zh}"]) for key, zh in RATING_KEYS.items()}
            warnings: list[str] = []
            cross = self._ths_cross_check(sym)
            if cross is None:
                warnings.append("cross_check_unavailable")
            elif _sources_disagree(eps, cross["years"]):
                warnings.append("consensus_sources_disagree")
            data = {
                "code": sym.canonical,
                "name": calc.ftext(row["名称"]),
                "eps_forecast": eps,
                "rating_counts": counts,
                "report_count": report_count,
                "cross_check": cross,
                "disclaimer": "consensus is an aggregate of sell-side forecasts, not a fact",
            }
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)

    def _ths_cross_check(self, sym: Symbol) -> dict[str, Any] | None:
        try:
            table = self._load("profit_forecast_ths", (sym,), ttl=STOCK_TTL, timeout=DEFAULT_TIMEOUT)
            _need(table, ["年度", "预测机构数", "最小值", "均值", "最大值"])
            years: list[dict[str, Any]] = []
            for _, row in table.iterrows():
                year = calc.fint(row["年度"])
                if year is None:
                    continue
                years.append(
                    {
                        "year": year,
                        "analysts": calc.fint(row["预测机构数"]),
                        "min": calc.fnum(row["最小值"]),
                        "mean": calc.fnum(row["均值"]),
                        "max": calc.fnum(row["最大值"]),
                    }
                )
        except (UpstreamError, KeyError, ValueError, TypeError, AttributeError, IndexError):
            return None
        if not years:
            return None
        years.sort(key=lambda item: item["year"])
        return {"source": "ths", "years": years}

    # ------------------------------------------------------------------ 2. ratings
    def cn_get_ratings(self, code: Any, limit: Any = DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["ratings"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            count = _int_arg("limit", limit, 1, MAX_LIMIT)
            table = self._load("institute_recommend", (sym,), ttl=STOCK_TTL, timeout=DEFAULT_TIMEOUT)
            if table.empty:
                return envelope(source=source, status="empty", data={"code": sym.canonical, "ratings": []})
            _need(table, ["评级日期", "评级机构", "分析师", "最新评级", "目标价"])
            ordered = _sort_desc_by_date(table, "评级日期")
            items = [
                {
                    "date": calc.fdate(row["评级日期"]),
                    "org": calc.ftext(row["评级机构"]),
                    "analyst": calc.ftext(row["分析师"]),
                    "rating": calc.ftext(row["最新评级"]),
                    "target_price_yuan": calc.fnum(row["目标价"]),
                }
                for _, row in ordered.head(count).iterrows()
            ]
            data = {"code": sym.canonical, "ratings": items, "total_available": int(len(table))}
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 3. research reports
    def cn_get_research_reports(self, code: Any, limit: Any = DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["reports"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            count = _int_arg("limit", limit, 1, MAX_LIMIT)
            table = self._load("research_report", (sym,), ttl=STOCK_TTL, timeout=DEFAULT_TIMEOUT)
            if table.empty:
                return envelope(
                    source=source,
                    status="empty",
                    data={"code": sym.canonical, "reports": [], "untrusted_text": True},
                )
            _need(table, ["日期", "报告名称", "机构", "东财评级", "报告PDF链接"])
            ordered = _sort_desc_by_date(table, "日期")
            items = [
                {
                    "date": calc.fdate(row["日期"]),
                    "title": calc.ftext(row["报告名称"]),
                    "org": calc.ftext(row["机构"]),
                    "rating": calc.ftext(row["东财评级"]),
                    "link": calc.ftext(row["报告PDF链接"]),
                }
                for _, row in ordered.head(count).iterrows()
            ]
            data = {
                "code": sym.canonical,
                "reports": items,
                "total_available": int(len(table)),
                "untrusted_text": True,
            }
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 4. valuation
    def cn_get_valuation(self, code: Any, years: Any = VALUATION_DEFAULT_YEARS) -> dict[str, Any]:
        source = SOURCE_LABELS["valuation"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            window_years = _int_arg("years", years, 1, VALUATION_MAX_YEARS)
            table = self._load("stock_value", (sym,), ttl=STOCK_TTL, timeout=DEFAULT_TIMEOUT)
            if table.empty:
                return envelope(source=source, status="empty", data={"code": sym.canonical})
            _need(table, ["数据日期", "PE(TTM)", "PE(静)", "市净率", "总市值", "流通市值"])
            frame = table.copy()
            frame["_d"] = pd.to_datetime(frame["数据日期"], errors="coerce")
            frame = frame.dropna(subset=["_d"]).sort_values("_d", kind="mergesort")
            if frame.empty:
                return envelope(source=source, status="empty", data={"code": sym.canonical})
            latest = frame.iloc[-1]
            current = {
                "date": calc.fdate(latest["_d"]),
                "pe_ttm": calc.fnum(latest["PE(TTM)"]),
                "pe_static": calc.fnum(latest["PE(静)"]),
                "pb": calc.fnum(latest["市净率"]),
                "market_cap_yuan": calc.fnum(latest["总市值"]),
                "float_cap_yuan": calc.fnum(latest["流通市值"]),
            }
            window = calc.in_window(frame, "_d", window_years)
            pe_block = calc.percentile_block([calc.fnum(v) for v in window["PE(TTM)"]], current["pe_ttm"])
            pb_block = calc.percentile_block([calc.fnum(v) for v in window["市净率"]], current["pb"])
            reasons = {k: b["reason"] for k, b in (("pe_ttm", pe_block), ("pb", pb_block)) if "reason" in b}
            percentile: dict[str, Any] = {
                "pe_ttm_pct": pe_block["pct"],
                "pb_pct": pb_block["pct"],
                "window_years": window_years,
                "samples": int(len(window)),
                "samples_pe_ttm": pe_block["samples"],
                "samples_pb": pb_block["samples"],
                "excluded_nonpositive": {
                    "pe_ttm": pe_block["excluded_nonpositive"],
                    "pb": pb_block["excluded_nonpositive"],
                },
                "definition": "share of window samples <= current value, in percent; non-positive values excluded",
            }
            if reasons:
                percentile["reason"] = next(iter(reasons.values()))
                percentile["reasons"] = reasons
            weekly = calc.last_per_group(window, "_d", "week")
            sampled, step = calc.cap_points(weekly)
            series = [
                {"date": calc.fdate(row["_d"]), "pe_ttm": calc.fnum(row["PE(TTM)"]), "pb": calc.fnum(row["市净率"])}
                for _, row in sampled.iterrows()
            ]
            warnings: list[str] = []
            if (self._today() - latest["_d"].date()).days > STALE_DAYS:
                warnings.append("stale_data")
            data = {
                "code": sym.canonical,
                "current": current,
                "percentile": percentile,
                "series": series,
                "series_step_weeks": step,
            }
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)

    # ------------------------------------------------------------------ 5. industry valuation
    def cn_get_industry_valuation(self, date: Any = None, limit: Any = INDUSTRY_DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["industry"]

        def body() -> dict[str, Any]:
            count = _int_arg("limit", limit, 1, INDUSTRY_MAX_LIMIT)
            if date is not None:
                requested = [_date_arg("date", date)]
            else:
                today = self._today()
                requested = [today - timedelta(days=i) for i in range(INDUSTRY_FALLBACK_DAYS + 1)]
            table: pd.DataFrame | None = None
            used: date_type | None = None
            last_error: UpstreamError | None = None
            for day in requested:
                try:
                    candidate = self._load(
                        "industry_pe", (_yyyymmdd(day.isoformat()),), ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT
                    )
                except UpstreamError as exc:
                    # For 2026-11-16 (no data yet) cninfo raised ValueError instead of returning no
                    # rows, so a failed day is skipped during look-back; timeouts and limits stop it.
                    if date is not None or exc.code != "upstream_error":
                        raise
                    last_error = exc
                    continue
                if not candidate.empty:
                    table, used = candidate, day
                    break
            if table is None and last_error is not None:
                raise last_error
            if table is None or used is None:
                return envelope(
                    source=source,
                    status="empty",
                    data={"requested_dates": [d.isoformat() for d in requested], "rows": []},
                )
            _need(
                table,
                ["变动日期", "行业分类", "行业层级", "行业编码", "行业名称", "公司数量", "纳入计算公司数量",
                 "总市值-静态", "净利润-静态", "静态市盈率-加权平均", "静态市盈率-中位数", "静态市盈率-算术平均"],
            )
            rows = []
            for _, row in table.head(count).iterrows():
                cap = calc.fnum(row["总市值-静态"])
                profit = calc.fnum(row["净利润-静态"])
                rows.append(
                    {
                        "industry_code": calc.ftext(row["行业编码"]),
                        "industry_name": calc.ftext(row["行业名称"]),
                        "level": calc.fint(row["行业层级"]),
                        "company_count": calc.fint(row["公司数量"]),
                        "included_company_count": calc.fint(row["纳入计算公司数量"]),
                        "total_market_cap_yuan": None if cap is None else cap * 1e8,
                        "net_profit_yuan": None if profit is None else profit * 1e8,
                        "pe_static_weighted": calc.fnum(row["静态市盈率-加权平均"]),
                        "pe_static_median": calc.fnum(row["静态市盈率-中位数"]),
                        "pe_static_mean": calc.fnum(row["静态市盈率-算术平均"]),
                    }
                )
            data = {
                "date": calc.fdate(table.iloc[0]["变动日期"]) or used.isoformat(),
                "requested_date": used.isoformat(),
                "classification": calc.ftext(table.iloc[0]["行业分类"]),
                "total_rows": int(len(table)),
                "rows": rows,
                "note": "only static PE is published by this upstream; no TTM PE column exists",
            }
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 6. index valuation
    def cn_get_index_valuation(self, index: Any = "沪深300") -> dict[str, Any]:
        source = SOURCE_LABELS["index"]

        def body() -> dict[str, Any]:
            if not isinstance(index, str) or index not in self.index_names:
                raise ArgumentError(f"index must be one of: {', '.join(self.index_names)}")
            if index == "全A":
                table = self._load("a_ttm_lyr", ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT)
                spec = _ALL_A_FIELDS
            else:
                table = self._load("index_pe", (index,), ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT)
                spec = _INDEX_FIELDS
            if table.empty:
                return envelope(source=source, status="empty", data={"index": index})
            date_col = spec["date"]
            _need(table, [date_col, *spec["values"].values()])
            frame = table.copy()
            frame["_d"] = pd.to_datetime(frame[date_col], errors="coerce")
            frame = frame.dropna(subset=["_d"]).sort_values("_d", kind="mergesort")
            if frame.empty:
                return envelope(source=source, status="empty", data={"index": index})
            latest = frame.iloc[-1]
            current: dict[str, Any] = {"date": calc.fdate(latest["_d"])}
            for name, column in spec["values"].items():
                current[name] = calc.fnum(latest[column])
            window = calc.in_window(frame, "_d", INDEX_WINDOW_YEARS)
            percentile: dict[str, Any] = {"window_years": INDEX_WINDOW_YEARS, "samples": int(len(window))}
            for name in spec["percentile"]:
                block = calc.percentile_block([calc.fnum(v) for v in window[spec["values"][name]]], current[name])
                percentile[f"{name}_pct"] = block["pct"]
                percentile[f"{name}_excluded_nonpositive"] = block["excluded_nonpositive"]
                if "reason" in block:
                    percentile[f"{name}_reason"] = block["reason"]
            percentile["definition"] = (
                "share of the 10-year window samples (monthly points plus the latest point) <= current value, in percent"
            )
            monthly = calc.last_per_group(window, "_d", "month")
            series = []
            for _, row in monthly.iterrows():
                point: dict[str, Any] = {"date": calc.fdate(row["_d"])}
                for name in spec["series"]:
                    point[name] = calc.fnum(row[spec["values"][name]])
                if spec.get("close"):
                    point["index_close"] = calc.fnum(row[spec["close"]])
                series.append(point)
            data = {
                "index": index,
                "current": current,
                "percentile": percentile,
                "series": series,
                "upstream_labels": spec["labels"],
            }
            if spec.get("close"):
                data["current"]["index_close"] = calc.fnum(latest[spec["close"]])
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 7. earnings events
    def cn_get_earnings_events(
        self, period: Any, kind: Any, code: Any = None, limit: Any = EVENT_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["earnings"]

        def body() -> dict[str, Any]:
            text = _period_arg(period)
            if not isinstance(kind, str) or kind not in EARNINGS_KINDS:
                raise ArgumentError(f"kind must be one of: {', '.join(EARNINGS_KINDS)}")
            sym = _symbol_arg(code) if code is not None else None
            count = _int_arg("limit", limit, 1, EVENT_MAX_LIMIT)
            method = {"forecast": "yjyg", "express": "yjkb", "report": "yjbb"}[kind]
            table = self._load(method, (_yyyymmdd(text),), ttl=BIG_TTL, timeout=BIG_TABLE_TIMEOUT)
            base = {"period": text, "kind": kind, "events": []}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            date_col = "最新公告日期" if kind == "report" else "公告日期"
            _need(table, ["股票代码", "股票简称", date_col])
            subset = table[_digits_equal(table["股票代码"], sym.digits)] if sym else table
            if subset.empty:
                return envelope(source=source, status="empty", data=base)
            ordered = _sort_desc_by_date(subset, date_col)
            builder = {"forecast": _forecast_event, "express": _express_event, "report": _report_event}[kind]
            events = [builder(row) for _, row in ordered.head(count).iterrows()]
            data: dict[str, Any] = {
                "period": text,
                "kind": kind,
                "total_matching": int(len(subset)),
                "events": events,
            }
            if kind == "forecast":
                data["untrusted_text"] = True
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 8. disclosure schedule
    def cn_get_disclosure_schedule(
        self, period: Any, code: Any = None, limit: Any = EVENT_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["schedule"]

        def body() -> dict[str, Any]:
            text = _period_arg(period)
            sym = _symbol_arg(code) if code is not None else None
            count = _int_arg("limit", limit, 1, EVENT_MAX_LIMIT)
            table = self._load("yysj", (_yyyymmdd(text),), ttl=BIG_TTL, timeout=BIG_TABLE_TIMEOUT)
            base = {"period": text, "items": []}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["股票代码", "股票简称", "首次预约时间", "一次变更日期", "二次变更日期", "三次变更日期", "实际披露时间"])
            subset = table[_digits_equal(table["股票代码"], sym.digits)] if sym else table
            if subset.empty:
                return envelope(source=source, status="empty", data=base)
            items = []
            for _, row in subset.iterrows():
                first = calc.fdate(row["首次预约时间"])
                changes = [d for d in (calc.fdate(row[c]) for c in ("一次变更日期", "二次变更日期", "三次变更日期")) if d]
                items.append(
                    {
                        "code": _canonical(row["股票代码"]),
                        "name": calc.ftext(row["股票简称"]),
                        "first_scheduled_date": first,
                        "change_dates": changes,
                        "current_scheduled_date": changes[-1] if changes else first,
                        "actual_disclosure_date": calc.fdate(row["实际披露时间"]),
                    }
                )
            items.sort(key=lambda item: (item["current_scheduled_date"] is None, item["current_scheduled_date"] or "", item["code"] or ""))
            data = {"period": text, "total_matching": len(items), "items": items[:count]}
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 9. stock news
    def cn_get_stock_news(self, code: Any, limit: Any = STOCK_NEWS_DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["stock_news"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            count = _int_arg("limit", limit, 1, STOCK_NEWS_MAX_LIMIT)
            table = self._load("stock_news", (sym,), ttl=NEWS_TTL, timeout=DEFAULT_TIMEOUT)
            base = {"code": sym.canonical, "items": [], "untrusted_text": True}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"])
            warnings: list[str] = []
            entries: list[dict[str, Any]] = []
            for _, row in table.iterrows():
                title, _ = textproc.clean_text(row["新闻标题"])
                summary, truncated = textproc.clean_text(row["新闻内容"], SUMMARY_MAX)
                source_name, _ = textproc.clean_text(row["文章来源"])
                if title is None and summary is None:
                    continue
                item: dict[str, Any] = {
                    "published_at": _parse_time_field(row["发布时间"], warnings),
                    "title": title or "",
                    "summary": summary or "",
                    "source_name": source_name,
                    "link": textproc.clean_link(row["新闻链接"]),
                }
                if truncated:
                    item["truncated"] = True
                entries.append(item)
            entries = _dedupe_exact(entries)
            entries.sort(key=lambda item: _timestamp(item["published_at"]), reverse=True)
            total = len(entries)
            items = entries[:count]
            if not items:
                return envelope(source=source, status="empty", data=base)
            data = {"code": sym.canonical, "items": items, "total_available": total, "untrusted_text": True}
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)

    # ------------------------------------------------------------------ 10. flash news
    def cn_get_flash_news(
        self, source: Any = "cls", limit: Any = FLASH_DEFAULT_LIMIT, keyword: Any = None, since: Any = None
    ) -> dict[str, Any]:
        label = SOURCE_LABELS["flash_cls"] if source == "cls" else SOURCE_LABELS["flash_em"]

        def body() -> dict[str, Any]:
            if not isinstance(source, str) or source not in FLASH_SOURCES:
                raise ArgumentError(f"source must be one of: {', '.join(FLASH_SOURCES)}")
            count = _int_arg("limit", limit, 1, FLASH_MAX_LIMIT)
            keyword_text = _keyword_arg(keyword)
            since_dt = _since_arg(since)
            method = "flash_cls" if source == "cls" else "flash_em"
            table = self._load(method, (), ttl=FLASH_TTL, timeout=DEFAULT_TIMEOUT)
            base = {"source": source, "items": [], "untrusted_text": True}
            if table.empty:
                return envelope(source=label, status="empty", data=base)
            warnings: list[str] = []
            entries: list[dict[str, Any]] = []
            if source == "cls":
                _need(table, ["标题", "内容", "发布日期", "发布时间"])
                for _, row in table.iterrows():
                    title, _ = textproc.clean_text(row["标题"])
                    body_full, _ = textproc.clean_text(row["内容"])
                    body_text, truncated = textproc.clean_text(row["内容"], BODY_MAX)
                    if title is None and body_text is None:
                        continue
                    published = textproc.combine_date_time(row["发布日期"], row["发布时间"])
                    if published is None:
                        _warn_once(warnings, "time_unparsed")
                    item: dict[str, Any] = {
                        "published_at": published,
                        "title": title or "",
                        "body": body_text or "",
                        "link": None,
                        "_search_text": body_full or "",
                    }
                    if truncated:
                        item["truncated"] = True
                    entries.append(item)
            else:
                _need(table, ["标题", "摘要", "发布时间", "链接"])
                for _, row in table.iterrows():
                    title, _ = textproc.clean_text(row["标题"])
                    body_full, _ = textproc.clean_text(row["摘要"])
                    body_text, truncated = textproc.clean_text(row["摘要"], BODY_MAX)
                    if title is None and body_text is None:
                        continue
                    item = {
                        "published_at": _parse_time_field(row["发布时间"], warnings),
                        "title": title or "",
                        "body": body_text or "",
                        "link": textproc.clean_link(row["链接"]),
                        "_search_text": body_full or "",
                    }
                    if truncated:
                        item["truncated"] = True
                    entries.append(item)
            entries = _dedupe_exact(entries)
            entries.sort(key=lambda item: _timestamp(item["published_at"]), reverse=True)
            if keyword_text is not None:
                needle = keyword_text.casefold()
                entries = [
                    item
                    for item in entries
                    if needle in item["title"].casefold() or needle in item["_search_text"].casefold()
                ]
            if since_dt is not None:
                entries = [
                    item
                    for item in entries
                    if item["published_at"] is not None and _timestamp(item["published_at"]) >= since_dt.timestamp()
                ]
            total = len(entries)
            items = [{key: value for key, value in item.items() if key != "_search_text"} for item in entries[:count]]
            if not items:
                return envelope(source=label, status="empty", data=base)
            data = {"source": source, "items": items, "total_available": total, "untrusted_text": True}
            return envelope(source=label, status="ready", data=data, warnings=warnings)

        return self._run(label, body)

    # ------------------------------------------------------------------ 11. economic calendar
    def cn_get_econ_calendar(
        self, date: Any = None, region: Any = None, min_importance: Any = None
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["calendar"]

        def body() -> dict[str, Any]:
            requested = _date_arg("date", date) if date is not None else self._today()
            region_text = _text_arg("region", region) if region is not None else None
            threshold = _importance_arg(min_importance)
            table = self._load(
                "econ_calendar", (_yyyymmdd(requested.isoformat()),), ttl=EVENT_TTL, timeout=DEFAULT_TIMEOUT
            )
            base = {"date": requested.isoformat(), "items": [], "untrusted_text": True}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["日期", "时间", "地区", "事件", "公布", "预期", "前值", "重要性"])
            warnings: list[str] = []
            items: list[dict[str, Any]] = []
            for _, row in table.iterrows():
                if region_text is not None and not _region_matches(region_text, row):
                    continue
                if threshold is not None:
                    importance_number = textproc.to_number(row["重要性"])
                    if importance_number is None or importance_number < threshold:
                        continue
                day_value = _get(row, "日期")
                if textproc.is_missing(day_value):
                    day_value = requested
                moment = textproc.combine_date_time(day_value, row["时间"])
                if moment is None:
                    _warn_once(warnings, "time_unparsed")
                event, _ = textproc.clean_text(row["事件"])
                region_value, _ = textproc.clean_text(_get(row, "地区"))
                if region_value is None:
                    region_value, _ = textproc.clean_text(_get(row, "国家"))
                items.append(
                    {
                        "time": moment,
                        "region": region_value,
                        "event": event or "",
                        "actual": textproc.raw_value(row["公布"]),
                        "forecast": textproc.raw_value(row["预期"]),
                        "previous": textproc.raw_value(row["前值"]),
                        "importance": textproc.raw_value(row["重要性"]),
                    }
                )
            if not items:
                return envelope(source=source, status="empty", data=base)
            data = {
                "date": requested.isoformat(),
                "region": region_text,
                "min_importance": threshold,
                "items": items,
                "total_available": len(items),
                "untrusted_text": True,
            }
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)

    # ------------------------------------------------------------------ 12. suspensions
    def cn_get_suspensions(self, date: Any = None) -> dict[str, Any]:
        source = SOURCE_LABELS["suspensions"]

        def body() -> dict[str, Any]:
            requested = _date_arg("date", date) if date is not None else self._today()
            table = self._load(
                "suspensions", (_yyyymmdd(requested.isoformat()),), ttl=EVENT_TTL, timeout=DEFAULT_TIMEOUT
            )
            base = {"date": requested.isoformat(), "items": [], "dropped": 0, "untrusted_text": True}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["代码", "名称", "停牌时间", "停牌截止时间", "停牌原因", "预计复牌时间"])
            warnings: list[str] = []
            items: list[dict[str, Any]] = []
            dropped = 0
            for _, row in table.iterrows():
                canonical = _suspend_code(row["代码"])
                if canonical is None:
                    dropped += 1
                    continue
                name, _ = textproc.clean_text(row["名称"], SUSPENSION_NAME_MAX)
                reason, truncated = textproc.clean_text(row["停牌原因"], SUSPENSION_REASON_MAX)
                item: dict[str, Any] = {
                    "code": canonical,
                    "name": name,
                    "suspend_from": _parse_date_field(row["停牌时间"], warnings),
                    "suspend_to": _parse_date_field(row["停牌截止时间"], warnings),
                    "resume_at": _parse_date_field(row["预计复牌时间"], warnings),
                    "reason": reason,
                }
                if truncated:
                    item["truncated"] = True
                items.append(item)
            if not items:
                return envelope(
                    source=source,
                    status="empty",
                    data={"date": requested.isoformat(), "items": [], "dropped": dropped, "untrusted_text": True},
                )
            data = {
                "date": requested.isoformat(),
                "items": items,
                "dropped": dropped,
                "total_available": len(items),
                "untrusted_text": True,
            }
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)

    # ------------------------------------------------------------------ 13. investor Q&A
    def cn_get_irm_qa(self, code: Any, limit: Any = IRM_DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["irm"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            count = _int_arg("limit", limit, 1, IRM_MAX_LIMIT)
            table = self._load("irm_qa", (sym,), ttl=NEWS_TTL, timeout=DEFAULT_TIMEOUT)
            base = {"code": sym.canonical, "items": [], "untrusted_text": True}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["问题", "提问时间"])
            warnings: list[str] = []
            entries: list[dict[str, Any]] = []
            for _, row in table.iterrows():
                question, question_truncated = textproc.clean_text(row["问题"], QUESTION_MAX)
                answer_value = _get(row, "回答内容")
                if textproc.is_missing(answer_value):
                    answer_value = _get(row, "回答")
                answer, answer_truncated = textproc.clean_text(answer_value, ANSWER_MAX)
                if question is None and answer is None:
                    continue
                answered: str | None = None
                if answer is not None:
                    update_value = _get(row, "更新时间")
                    if not textproc.is_missing(update_value):
                        answered = _parse_time_field(update_value, warnings)
                item: dict[str, Any] = {
                    "asked_at": _parse_time_field(row["提问时间"], warnings),
                    "question": question or "",
                    "answer": answer,
                    "answered_at": answered,
                }
                if question_truncated or answer_truncated:
                    item["truncated"] = True
                entries.append(item)
            entries.sort(key=lambda item: _timestamp(item["asked_at"]), reverse=True)
            total = len(entries)
            items = entries[:count]
            if not items:
                return envelope(source=source, status="empty", data=base)
            data = {"code": sym.canonical, "items": items, "total_available": total, "untrusted_text": True}
            return envelope(source=source, status="ready", data=data, warnings=warnings)

        return self._run(source, body)


    # ------------------------------------------------------------------ 14. convertible bond list
    def cn_get_cb_list(self, underlying: Any = None, limit: Any = CB_LIST_DEFAULT_LIMIT) -> dict[str, Any]:
        source = SOURCE_LABELS["cb_list"]

        def body() -> dict[str, Any]:
            count = _int_arg("limit", limit, 1, CB_LIST_MAX_LIMIT)
            sym = _symbol_arg(underlying) if underlying is not None else None
            table = self._load("cb_list", ttl=BIG_TTL, timeout=BIG_TABLE_TIMEOUT)
            base: dict[str, Any] = {
                "underlying": None if sym is None else sym.canonical,
                "rows": [],
                "dropped_unlisted": 0,
                "dropped_delisted": 0,
            }
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(
                table,
                [
                    "债券代码",
                    "债券简称",
                    "正股代码",
                    "正股简称",
                    "正股价",
                    "转股价",
                    "转股价值",
                    "转股溢价率",
                    "上市时间",
                    "信用评级",
                ],
            )
            today = self._today()
            rows: list[dict[str, Any]] = []
            dropped = 0
            delisted = 0
            invalid = 0
            for _, row in table.iterrows():
                bond_code = _bond_code(row["债券代码"])
                if bond_code is None:
                    invalid += 1
                    continue
                listed = calc.fdate(row["上市时间"])
                if listed is None or listed > today.isoformat():
                    dropped += 1
                    continue
                bond_name = calc.ftext(row["债券简称"])
                if bond_code.startswith("404") or (bond_name is not None and "退" in bond_name):
                    delisted += 1
                    continue
                underlying_digits = _code_digits(row["正股代码"])
                if sym is not None and underlying_digits != sym.digits:
                    continue
                conversion_price = calc.fnum(row["转股价"])
                underlying_price = calc.fnum(row["正股价"])
                conversion_value = calc.fnum(row["转股价值"])
                conversion_computed = False
                if conversion_value is None:
                    conversion_value = calc.bond_conversion_value(conversion_price, underlying_price)
                    conversion_computed = conversion_value is not None
                premium = calc.fnum(row["转股溢价率"])
                has_market_link = underlying_price is not None
                item: dict[str, Any] = {
                    "bond_code": bond_code,
                    "bond_name": bond_name,
                    "underlying_code": _canonical(underlying_digits) if underlying_digits else None,
                    "underlying_name": calc.ftext(row["正股简称"]),
                    "underlying_price_yuan": underlying_price,
                    "conversion_price_yuan": conversion_price,
                    "conversion_value_yuan": conversion_value,
                    "premium_pct": premium,
                    "credit_rating": calc.ftext(row["信用评级"]),
                    "listing_date": listed,
                    "listing_status": "listed" if has_market_link else "unknown",
                }
                if conversion_computed:
                    item["conversion_value_computed"] = True
                rows.append(item)
            rows.sort(key=lambda item: item["bond_code"])
            rows.sort(key=lambda item: item["listing_date"] or "", reverse=True)
            available = len(rows)
            data = {
                "underlying": None if sym is None else sym.canonical,
                "total_available": available,
                "returned": min(available, count),
                "rows": rows[:count],
                "dropped_unlisted": dropped,
                "dropped_delisted": delisted,
                "dropped_invalid_code": invalid,
                "listing_status_note": (
                    "listing_status is 'listed' when the upstream row has a non-null 正股价, and 'unknown' "
                    "otherwise. Rows whose 上市时间 is missing/future are dropped as "
                    "unlisted; rows whose 债券简称 contains 退 or whose code starts with 404 are dropped as "
                    "delisted. The upstream table has no explicit delisting date or trading flag, so a "
                    "retained 'listed' row is still an inference from those fields."
                ),
                "underlying_price_note": (
                    "underlying_price_yuan is the eastmoney terms-table field 正股价, not a real-time quote; "
                    "the table has no per-field date."
                ),
            }
            if not rows:
                return envelope(source=source, status="empty", data=data)
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 15. convertible bond quote
    def cn_get_cb_quote(self, bond_codes: Any) -> dict[str, Any]:
        source = SOURCE_LABELS["cb_quote"]

        def body() -> dict[str, Any]:
            codes = _bond_codes_arg(bond_codes)
            terms, terms_stamp = self._load_stamped(
                "cb_list", ttl=BIG_TTL, timeout=BIG_TABLE_TIMEOUT
            )
            spot = self._load("cb_spot", ttl=CB_QUOTE_TTL, timeout=BIG_TABLE_TIMEOUT)
            base: dict[str, Any] = {"bond_codes": codes, "rows": []}
            if spot.empty and terms.empty:
                return envelope(source=source, status="empty", data=base)
            spot_by_code: dict[str, pd.Series] = {}
            if not spot.empty:
                _need(spot, ["symbol", "name", "trade", "changepercent", "code", "ticktime"])
                for _, row in spot.iterrows():
                    code = _bond_code(row["code"])
                    if code is not None:
                        spot_by_code.setdefault(code, row)
            terms_by_code: dict[str, pd.Series] = {}
            if not terms.empty:
                _need(
                    terms,
                    ["债券代码", "债券简称", "正股代码", "正股价", "转股价"],
                )
                for _, row in terms.iterrows():
                    code = _bond_code(row["债券代码"])
                    if code is not None:
                        terms_by_code.setdefault(code, row)
            quote_day = self._now().date()
            terms_day = terms_stamp.date()
            warnings: list[str] = []
            if terms_day != quote_day:
                _warn_once(warnings, "price_time_mismatch")
            terms_note = (
                f"underlying_price and conversion_price come from the eastmoney bond_zh_cov terms table, "
                f"not a real-time quote; table fetched {terms_stamp.isoformat(timespec='seconds')} "
                f"(upstream has no per-field date, so the table fetch time is used as its data date)"
            )
            rows: list[dict[str, Any]] = []
            any_quote = False
            for code in codes:
                s = spot_by_code.get(code)
                t = terms_by_code.get(code)
                price = calc.fnum(s["trade"]) if s is not None else None
                change = calc.fnum(s["changepercent"]) if s is not None else None
                if price is not None and price > 0:
                    any_quote = True
                name = calc.ftext(s["name"]) if s is not None else None
                if name is None and t is not None:
                    name = calc.ftext(t["债券简称"])
                underlying_digits = _code_digits(t["正股代码"]) if t is not None else None
                conversion_price = calc.fnum(t["转股价"]) if t is not None else None
                underlying_price = calc.fnum(t["正股价"]) if t is not None else None
                conversion_value = calc.bond_conversion_value(conversion_price, underlying_price)
                premium = calc.bond_premium_pct(price, conversion_value)
                reasons: dict[str, str] = {}
                if s is None:
                    reasons["quote"] = "bond_not_in_spot_snapshot"
                if t is None:
                    reasons["terms"] = "bond_not_in_terms_table"
                if conversion_price is None:
                    reasons["conversion_price"] = "missing_or_non_numeric"
                elif conversion_price <= 0:
                    reasons["conversion_price"] = "nonpositive"
                if underlying_price is None:
                    reasons["underlying_price"] = "missing_or_non_numeric"
                if price is None:
                    reasons["price"] = "missing_or_non_numeric"
                elif price <= 0:
                    reasons["price"] = "nonpositive"
                if conversion_value is None:
                    if conversion_price is None or conversion_price <= 0:
                        reasons["conversion_value"] = "conversion_price_unusable"
                    elif underlying_price is None:
                        reasons["conversion_value"] = "underlying_price_missing"
                    else:
                        reasons["conversion_value"] = "inputs_incomplete"
                if premium is None:
                    if price is None or price <= 0:
                        reasons["premium_pct"] = "price_unusable"
                    elif conversion_value is None:
                        reasons["premium_pct"] = "conversion_value_missing"
                ticktime = calc.ftext(s["ticktime"]) if s is not None else None
                quote_note = (
                    f"{'sina spot ticktime ' + ticktime if ticktime else 'no sina spot ticktime'}; "
                    f"{terms_note if t is not None else 'no eastmoney terms row for this bond'}; "
                    "conversion_value_yuan and premium_pct are computed by this server"
                )
                item: dict[str, Any] = {
                    "bond_code": code,
                    "name": name,
                    "price_yuan": price,
                    "change_pct": change,
                    "underlying_code": _canonical(underlying_digits) if underlying_digits else None,
                    "underlying_price_yuan": underlying_price,
                    "conversion_price_yuan": conversion_price,
                    "conversion_value_yuan": None if conversion_value is None else round(conversion_value, 4),
                    "premium_pct": None if premium is None else round(premium, 4),
                    "quote_note": quote_note,
                }
                if reasons:
                    item["reasons"] = reasons
                rows.append(item)
            data = {
                "bond_codes": codes,
                "quote_source": "sina",
                "terms_source": "eastmoney",
                "quote_date": quote_day.isoformat(),
                "terms_fetched_at": terms_stamp.isoformat(timespec="seconds"),
                "computed": True,
                "rows": rows,
            }
            status = "ready" if any_quote else "empty"
            return envelope(source=source, status=status, data=data, warnings=warnings)

        return self._run(source, body)

    # ------------------------------------------------------------------ 16. index bars
    def cn_get_index_bars(
        self, index: Any = "沪深300", start: Any = None, end: Any = None, limit: Any = INDEX_BARS_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["index_bars"]

        def body() -> dict[str, Any]:
            canonical, spec = _index_arg(index)
            count = _int_arg("limit", limit, 1, INDEX_BARS_MAX_LIMIT)
            start_day = _date_arg("start", start) if start is not None else None
            end_day = _date_arg("end", end) if end is not None else None
            if start_day is not None and end_day is not None and start_day > end_day:
                raise ArgumentError("start must not be after end")
            if end_day is None:
                end_day = self._today()
            if start_day is None:
                start_day = end_day - timedelta(days=count * 2 + 30)
            table = self._load(
                "index_bars",
                (spec["symbol"], _yyyymmdd(start_day.isoformat()), _yyyymmdd(end_day.isoformat())),
                ttl=BIG_TTL,
                timeout=DEFAULT_TIMEOUT,
            )
            base = {
                "index": canonical,
                "index_name": spec["name"],
                "requested_start": start_day.isoformat(),
                "requested_end": end_day.isoformat(),
                "bars": [],
            }
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["date", "open", "close", "high", "low", "volume", "amount"])
            frame = table.copy()
            frame["_d"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["_d"])
            frame = frame[(frame["_d"] >= pd.Timestamp(start_day)) & (frame["_d"] <= pd.Timestamp(end_day))]
            frame = frame.sort_values("_d", kind="mergesort").tail(count)
            if frame.empty:
                return envelope(source=source, status="empty", data=base)
            confirmed = self.index_units_confirmed
            bars: list[dict[str, Any]] = []
            for _, row in frame.iterrows():
                volume = calc.fnum(row["volume"])
                amount = calc.fnum(row["amount"])
                bar: dict[str, Any] = {
                    "date": calc.fdate(row["_d"]),
                    "open": calc.fnum(row["open"]),
                    "close": calc.fnum(row["close"]),
                    "high": calc.fnum(row["high"]),
                    "low": calc.fnum(row["low"]),
                    "volume": volume,
                    "amount": amount,
                }
                if confirmed:
                    bar["volume_unit"] = "lot"
                    bar["amount_unit"] = "yuan"
                    bar["volume_shares"] = None if volume is None else volume * INDEX_VOLUME_LOT_SIZE
                    bar["amount_yuan"] = amount
                else:
                    bar["volume_unit"] = "unconfirmed"
                    bar["amount_unit"] = "unconfirmed"
                bars.append(bar)
            units: dict[str, Any] = {
                "volume": {
                    "upstream": "lot" if confirmed else "unconfirmed",
                    "output": "shares" if confirmed else None,
                    "factor": INDEX_VOLUME_LOT_SIZE if confirmed else None,
                    "confirmed": confirmed,
                },
                "amount": {
                    "upstream": "yuan" if confirmed else "unconfirmed",
                    "output": "yuan" if confirmed else None,
                    "factor": 1 if confirmed else None,
                    "confirmed": confirmed,
                },
                "evidence": INDEX_UNITS_EVIDENCE,
            }
            if not confirmed:
                units["note"] = "upstream units were not independently verified; raw values are returned unchanged"
            data = {
                "index": canonical,
                "index_name": spec["name"],
                "requested_start": start_day.isoformat(),
                "requested_end": end_day.isoformat(),
                "start": bars[0]["date"],
                "end": bars[-1]["date"],
                "count": len(bars),
                "bars": bars,
                "units": units,
            }
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 17. index constituents
    def cn_get_index_constituents(
        self, index: Any = "沪深300", limit: Any = INDEX_CONS_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["index_constituents"]

        def body() -> dict[str, Any]:
            canonical, spec = _index_arg(index)
            count = _int_arg("limit", limit, 1, INDEX_CONS_MAX_LIMIT)
            if canonical in CONSTITUENTS_UNSUPPORTED:
                return envelope(
                    source=source,
                    status="empty",
                    data={
                        "index": canonical,
                        "index_name": spec["name"],
                        "as_of": None,
                        "count": 0,
                        "returned": 0,
                        "rows": [],
                        "reason": CONSTITUENTS_UNSUPPORTED[canonical],
                    },
                )
            table = self._load(
                "index_constituents", (spec["digits"],), ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT
            )
            base = {
                "index": canonical,
                "index_name": spec["name"],
                "as_of": None,
                "count": 0,
                "returned": 0,
                "rows": [],
            }
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["日期", "成分券代码", "成分券名称", "交易所"])
            dates = [calc.fdate(value) for value in table["日期"]]
            dates = [value for value in dates if value is not None]
            rows_all: list[dict[str, Any]] = []
            dropped = 0
            for _, row in table.iterrows():
                code = _canonical(_code_digits(row["成分券代码"]))
                if code is None:
                    dropped += 1
                    continue
                rows_all.append(
                    {
                        "code": code,
                        "name": calc.ftext(row["成分券名称"]),
                        "market": _market_of(row["交易所"], code),
                    }
                )
            data = {
                "index": canonical,
                "index_name": spec["name"],
                "as_of": max(dates) if dates else None,
                "count": len(rows_all),
                "returned": min(len(rows_all), count),
                "dropped": dropped,
                "rows": rows_all[:count],
            }
            if not rows_all:
                return envelope(source=source, status="empty", data=data)
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 18. holders
    def cn_get_holders(
        self, code: Any, period: Any = None, view: Any = "top10_float", limit: Any = FUNDS_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        if not isinstance(view, str) or view not in HOLDER_VIEWS:
            return envelope(
                source="cn_research",
                status="error",
                error_code="invalid_argument",
                error_message=f"view must be one of: {', '.join(HOLDER_VIEWS)}",
            )
        source = SOURCE_LABELS["holders_top10"] if view == "top10_float" else SOURCE_LABELS["holders_funds"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            count = _int_arg("limit", limit, 1, FUNDS_MAX_LIMIT)
            requested = _period_arg(period) if period is not None else None
            candidates = [requested] if requested is not None else calc.recent_report_periods(
                self._today(), HOLDER_PERIOD_LOOKBACK
            )
            if view == "top10_float":
                table: pd.DataFrame | None = None
                used: str | None = None
                last_error: UpstreamError | None = None
                for candidate in candidates:
                    try:
                        frame = self._load(
                            "holders_top10",
                            (sym, _yyyymmdd(candidate)),
                            ttl=BIG_TTL,
                            timeout=DEFAULT_TIMEOUT,
                        )
                    except UpstreamError as exc:
                        if requested is not None or exc.code != "upstream_error":
                            raise
                        last_error = exc
                        continue
                    if not frame.empty:
                        table, used = frame, candidate
                        break
                if table is None:
                    if last_error is not None:
                        raise last_error
                    return envelope(
                        source=source,
                        status="empty",
                        data={
                            "code": sym.canonical,
                            "view": view,
                            "period": requested,
                            "tried_periods": candidates,
                            "rows": [],
                        },
                    )
                _need(table, ["名次", "股东名称", "股东性质", "股份类型", "持股数", "占总流通股本持股比例", "增减", "变动比率"])
                rows: list[dict[str, Any]] = []
                for _, row in table.head(10).iterrows():
                    change_value = calc.fnum(row["增减"])
                    item: dict[str, Any] = {
                        "rank": calc.fint(row["名次"]),
                        "name": calc.ftext(row["股东名称"]),
                        "holder_type": calc.ftext(row["股东性质"]),
                        "share_type": calc.ftext(row["股份类型"]),
                        "shares": calc.fnum(row["持股数"]),
                        "float_ratio_pct": calc.fnum(row["占总流通股本持股比例"]),
                        "change_shares": change_value,
                        "change_pct": calc.fnum(row["变动比率"]),
                    }
                    if change_value is None:
                        item["change_raw"] = calc.ftext(row["增减"])
                    rows.append(item)
                data = {
                    "code": sym.canonical,
                    "view": view,
                    "period": used,
                    "count": len(rows),
                    "rows": rows,
                }
                return envelope(source=source, status="ready", data=data)

            table = self._load("fund_holders", (sym,), ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT)
            base = {"code": sym.canonical, "view": view, "period": None, "rows": []}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(table, ["基金名称", "基金代码", "持仓数量", "占流通股比例", "持股市值", "截止日期"])
            frame = table.copy()
            frame["_period"] = frame["截止日期"].map(calc.fdate)
            available = {
                value for value in frame["_period"].tolist() if value is not None and value <= self._today().isoformat()
            }
            target: str | None = None
            for candidate in candidates:
                if candidate in available:
                    target = candidate
                    break
            if target is None:
                return envelope(
                    source=source,
                    status="empty",
                    data={
                        **base,
                        "period": requested,
                        "tried_periods": candidates,
                        "available_periods": sorted(available, reverse=True),
                    },
                )
            subset = frame[frame["_period"] == target].copy()
            subset["_mv"] = subset["持股市值"].map(calc.fnum)
            subset = subset.sort_values("_mv", ascending=False, na_position="last", kind="mergesort")
            all_rows = [
                {
                    "fund_name": calc.ftext(row["基金名称"]),
                    "fund_code": _code_digits(row["基金代码"]),
                    "shares": calc.fnum(row["持仓数量"]),
                    "float_ratio_pct": calc.fnum(row["占流通股比例"]),
                    "market_value_yuan": calc.fnum(row["持股市值"]),
                    "period": target,
                }
                for _, row in subset.iterrows()
            ]
            ratio_total = sum(
                item["float_ratio_pct"] for item in all_rows if item["float_ratio_pct"] is not None
            )
            data = {
                "code": sym.canonical,
                "view": view,
                "period": target,
                "fund_count": len(all_rows),
                "returned": min(len(all_rows), count),
                "total_float_ratio_pct": round(ratio_total, 4),
                "total_float_ratio_pct_computed": True,
                "computed": True,
                "computed_scope": "sum of 占流通股比例 over all funds in the period, before limit",
                "rows": all_rows[:count],
            }
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)

    # ------------------------------------------------------------------ 19. business segments
    def cn_get_business_segments(
        self, code: Any, period: Any = None, by: Any = "product"
    ) -> dict[str, Any]:
        source = SOURCE_LABELS["business_segments"]

        def body() -> dict[str, Any]:
            sym = _symbol_arg(code)
            if not isinstance(by, str) or by not in SEGMENT_BY:
                raise ArgumentError(f"by must be one of: {', '.join(SEGMENT_BY)}")
            requested = _period_arg(period) if period is not None else None
            table = self._load("business_segments", (sym,), ttl=BIG_TTL, timeout=DEFAULT_TIMEOUT)
            base = {"code": sym.canonical, "by": by, "period": requested, "rows": []}
            if table.empty:
                return envelope(source=source, status="empty", data=base)
            _need(
                table,
                ["报告日期", "分类类型", "主营构成", "主营收入", "收入比例", "主营成本", "主营利润", "毛利率"],
            )
            frame = table.copy()
            frame["_d"] = pd.to_datetime(frame["报告日期"], errors="coerce")
            frame = frame.dropna(subset=["_d"])
            frame = frame[frame["分类类型"] == SEGMENT_BY[by]]
            if frame.empty:
                return envelope(source=source, status="empty", data=base)
            if requested is not None:
                subset = frame[frame["_d"] == pd.Timestamp(requested)]
            else:
                eligible = frame[frame["_d"] <= pd.Timestamp(self._today())]
                if eligible.empty:
                    eligible = frame
                latest = eligible["_d"].max()
                subset = eligible[eligible["_d"] == latest]
            if subset.empty:
                return envelope(source=source, status="empty", data=base)
            used = calc.fdate(subset.iloc[0]["_d"])
            rows: list[dict[str, Any]] = []
            any_computed = False
            for _, row in subset.iterrows():
                revenue = calc.fnum(row["主营收入"])
                revenue_share = calc.fnum(row["收入比例"])
                cost = calc.fnum(row["主营成本"])
                gross_profit = calc.fnum(row["主营利润"])
                upstream_margin = calc.fnum(row["毛利率"])
                gross_margin = None if upstream_margin is None else upstream_margin * 100.0
                profit_computed = False
                margin_computed = False
                if gross_profit is None and revenue is not None and cost is not None:
                    gross_profit = revenue - cost
                    profit_computed = True
                if gross_margin is None and revenue not in (None, 0) and cost is not None:
                    gross_margin = (revenue - cost) / revenue * 100.0
                    margin_computed = True
                item: dict[str, Any] = {
                    "name": calc.ftext(row["主营构成"]),
                    "revenue_yuan": revenue,
                    "revenue_share_pct": None if revenue_share is None else revenue_share * 100.0,
                    "cost_yuan": cost,
                    "gross_profit_yuan": gross_profit,
                    "gross_margin_pct": gross_margin,
                }
                if profit_computed:
                    item["gross_profit_computed"] = True
                    any_computed = True
                if margin_computed:
                    item["gross_margin_computed"] = True
                    any_computed = True
                rows.append(item)
            rows.sort(
                key=lambda item: (
                    item["revenue_yuan"] is None,
                    -(item["revenue_yuan"] or 0.0),
                    item["name"] or "",
                )
            )
            data = {
                "code": sym.canonical,
                "period": used,
                "by": by,
                "classification": SEGMENT_BY[by],
                "count": len(rows),
                "rows": rows,
            }
            if any_computed:
                data["computed"] = True
            return envelope(source=source, status="ready", data=data)

        return self._run(source, body)


# ---------------------------------------------------------------------- helpers
_INDEX_FIELDS: dict[str, Any] = {
    "date": "日期",
    "close": "指数",
    "values": {
        "pe_static": "静态市盈率",
        "pe_static_median": "静态市盈率中位数",
        "pe_static_equal_weight": "等权静态市盈率",
        "pe_ttm": "滚动市盈率",
        "pe_ttm_median": "滚动市盈率中位数",
        "pe_ttm_equal_weight": "等权滚动市盈率",
    },
    "percentile": ("pe_ttm", "pe_ttm_median", "pe_static"),
    "series": ("pe_ttm", "pe_ttm_median", "pe_static"),
    "labels": {
        "pe_static": "静态市盈率",
        "pe_static_median": "静态市盈率中位数",
        "pe_static_equal_weight": "等权静态市盈率",
        "pe_ttm": "滚动市盈率",
        "pe_ttm_median": "滚动市盈率中位数",
        "pe_ttm_equal_weight": "等权滚动市盈率",
    },
}
_ALL_A_FIELDS: dict[str, Any] = {
    "date": "date",
    "close": None,
    "values": {
        "pe_static_median": "middlePELYR",
        "pe_static_average": "averagePELYR",
        "pe_ttm_median": "middlePETTM",
        "pe_ttm_average": "averagePETTM",
    },
    "percentile": ("pe_ttm_median", "pe_ttm_average"),
    "series": ("pe_ttm_median", "pe_ttm_average", "pe_static_median"),
    "labels": {
        "pe_static_median": "middlePELYR",
        "pe_static_average": "averagePELYR",
        "pe_ttm_median": "middlePETTM",
        "pe_ttm_average": "averagePETTM",
    },
}


def _sources_disagree(eps: list[dict[str, Any]], ths_years: list[dict[str, Any]]) -> bool:
    primary = {item["year"]: item["eps_yuan"] for item in eps}
    for item in ths_years:
        mean = item.get("mean")
        base = primary.get(item["year"])
        if mean is None or base is None:
            continue
        if base == 0:
            if mean != 0:
                return True
            continue
        if abs(base - mean) / abs(base) > DISAGREE_THRESHOLD:
            return True
    return False


def _parse_change_range(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    match = CHANGE_RANGE_RE.search(text)
    if match is None:
        return None, None
    sign = -1.0 if match.group(1) in ("下降", "降低") else 1.0
    first = sign * float(match.group(2))
    second = sign * float(match.group(3)) if match.group(3) is not None else first
    return min(first, second), max(first, second)


def _forecast_event(row: pd.Series) -> dict[str, Any]:
    summary = calc.ftext(row["业绩变动"]) if "业绩变动" in row.index else None
    low, high = _parse_change_range(summary)
    metric = calc.ftext(row["预测指标"]) if "预测指标" in row.index else None
    value = calc.fnum(row["预测数值"]) if "预测数值" in row.index else None
    prior = calc.fnum(row["上年同期值"]) if "上年同期值" in row.index else None
    per_share = metric == "每股收益"
    return {
        "code": _canonical(row["股票代码"]),
        "name": calc.ftext(row["股票简称"]),
        "metric": metric,
        "forecast_type": calc.ftext(row["预告类型"]) if "预告类型" in row.index else None,
        "change_pct_mid": calc.fnum(row["业绩变动幅度"]) if "业绩变动幅度" in row.index else None,
        "change_pct_min": low,
        "change_pct_max": high,
        "forecast_mid_yuan": None if per_share else value,
        "prior_year_yuan": None if per_share else prior,
        "forecast_mid_eps_yuan": value if per_share else None,
        "prior_year_eps_yuan": prior if per_share else None,
        "summary": summary,
        "reason": calc.ftext(row["业绩变动原因"]) if "业绩变动原因" in row.index else None,
        "announce_date": calc.fdate(row["公告日期"]),
    }


def _get(row: pd.Series, column: str) -> Any:
    return row[column] if column in row.index else None


def _express_event(row: pd.Series) -> dict[str, Any]:
    return {
        "code": _canonical(row["股票代码"]),
        "name": calc.ftext(row["股票简称"]),
        "eps_yuan": calc.fnum(_get(row, "每股收益")),
        "revenue_yuan": calc.fnum(_get(row, "营业收入-营业收入")),
        "revenue_prior_yuan": calc.fnum(_get(row, "营业收入-去年同期")),
        "revenue_yoy_pct": calc.fnum(_get(row, "营业收入-同比增长")),
        "net_profit_yuan": calc.fnum(_get(row, "净利润-净利润")),
        "net_profit_prior_yuan": calc.fnum(_get(row, "净利润-去年同期")),
        "net_profit_yoy_pct": calc.fnum(_get(row, "净利润-同比增长")),
        "bps_yuan": calc.fnum(_get(row, "每股净资产")),
        "roe_pct": calc.fnum(_get(row, "净资产收益率")),
        "industry": calc.ftext(_get(row, "所处行业")),
        "announce_date": calc.fdate(row["公告日期"]),
        "unconfirmed_upstream": {
            "营业收入-季度环比增长": calc.fnum(_get(row, "营业收入-季度环比增长")),
            "净利润-季度环比增长": calc.fnum(_get(row, "净利润-季度环比增长")),
        },
    }


def _report_event(row: pd.Series) -> dict[str, Any]:
    return {
        "code": _canonical(row["股票代码"]),
        "name": calc.ftext(row["股票简称"]),
        "eps_yuan": calc.fnum(_get(row, "每股收益")),
        "revenue_yuan": calc.fnum(_get(row, "营业总收入-营业总收入")),
        "revenue_yoy_pct": calc.fnum(_get(row, "营业总收入-同比增长")),
        "net_profit_yuan": calc.fnum(_get(row, "净利润-净利润")),
        "net_profit_yoy_pct": calc.fnum(_get(row, "净利润-同比增长")),
        "bps_yuan": calc.fnum(_get(row, "每股净资产")),
        "roe_pct": calc.fnum(_get(row, "净资产收益率")),
        "industry": calc.ftext(_get(row, "所处行业")),
        "announce_date": calc.fdate(row["最新公告日期"]),
        "unconfirmed_upstream": {
            "营业总收入-季度环比增长": calc.fnum(_get(row, "营业总收入-季度环比增长")),
            "净利润-季度环比增长": calc.fnum(_get(row, "净利润-季度环比增长")),
            "每股经营现金流量": calc.fnum(_get(row, "每股经营现金流量")),
            "销售毛利率": calc.fnum(_get(row, "销售毛利率")),
        },
    }
