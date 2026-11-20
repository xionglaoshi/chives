"""Daily A-share bars with turnover (amount) from Sina via AKShare `stock_zh_a_daily`."""

from __future__ import annotations

import logging
import math
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from cn_extra_mcp import global_market, sources
from cn_extra_mcp.envelope import envelope
from cn_extra_mcp.symbols import InvalidSymbol, normalize_symbol

logger = logging.getLogger(__name__)

DAILY_SOURCE = "akshare.sina.stock_zh_a_daily"
ADJUSTS = ("none", "qfq", "hfq")
DEFAULT_DAYS = 60
MAX_DAYS = 1100
DAILY_TTL = 300.0
_CN_TZ = timezone(timedelta(hours=8))

UNITS = {
    "open/high/low/close": "CNY per share (adjusted when adjust != none)",
    "volume_shares": "shares, as traded (not adjusted)",
    "amount_yuan": "CNY, as traded (not adjusted)",
    "turnover_pct": "percent of float shares (0.85 = 0.85%)",
    "float_shares": "shares",
}
NOTE = "日线到上一交易日收盘为止；当日盘中成交额请用 cn_get_quote_snapshot。"

_today: Any = lambda: datetime.now(_CN_TZ).date()


def _error(code: str, message: str) -> dict[str, Any]:
    return envelope(source=DAILY_SOURCE, status="error", error_code=code, error_message=message)


def _parse(value: Any, field: str) -> date_type:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field} must be YYYY-MM-DD") from None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _bar(row: pd.Series) -> dict[str, Any] | None:
    prices = [_num(row.get(c)) for c in ("open", "high", "low", "close")]
    if any(p is None for p in prices):
        return None
    volume, amount = _num(row.get("volume")), _num(row.get("amount"))
    turnover, float_shares = _num(row.get("turnover")), _num(row.get("outstanding_share"))
    return {
        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        "open": prices[0],
        "high": prices[1],
        "low": prices[2],
        "close": prices[3],
        "volume_shares": None if volume is None else int(round(volume)),
        "amount_yuan": None if amount is None else round(amount, 2),
        "turnover_pct": None if turnover is None else round(turnover * 100, 4),
        "float_shares": None if float_shares is None else int(round(float_shares)),
    }


def cn_get_daily_bars(
    code: Any,
    start_date: Any = None,
    end_date: Any = None,
    adjust: Any = "none",
) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(code)
    except InvalidSymbol as exc:
        return _error("invalid_symbol", str(exc))
    if adjust not in ADJUSTS:
        return _error("invalid_argument", f"adjust must be one of {list(ADJUSTS)}")
    try:
        end = _parse(end_date, "end_date") if end_date is not None else _today()
        start = _parse(start_date, "start_date") if start_date is not None else end - timedelta(days=DEFAULT_DAYS)
    except ValueError as exc:
        return _error("invalid_argument", str(exc))
    if start > end:
        return _error("invalid_argument", "start_date must not be after end_date")
    if (end - start).days > MAX_DAYS:
        return _error("invalid_argument", f"date range must not exceed {MAX_DAYS} calendar days")

    key = (symbol.sina, start.isoformat(), end.isoformat(), adjust)
    try:
        frame = global_market._cached_fetch(
            "sina_daily", key, DAILY_TTL,
            lambda: global_market._run_with_timeout(
                lambda: sources.fetch_daily_frame(
                    symbol.sina, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
                    "" if adjust == "none" else adjust,
                ),
                global_market.AKSHARE_TIMEOUT,
            ),
        )
    except Exception as exc:  # external source boundary
        code_, message = global_market._failure(exc)
        logger.error("daily fetch failed for %s: %s", symbol.canonical, type(exc).__name__)
        return _error(code_, message)

    bars: list[dict[str, Any]] = []
    if frame is not None and len(frame) > 0 and "date" in frame.columns:
        for _, row in frame.iterrows():
            bar = _bar(row)
            if bar is not None and start.isoformat() <= bar["date"] <= end.isoformat():
                bars.append(bar)
    bars.sort(key=lambda b: b["date"])
    data: dict[str, Any] = {
        "code": symbol.canonical,
        "adjust": adjust,
        "requested_range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "count": len(bars),
        "latest_date": bars[-1]["date"] if bars else None,
        "units": UNITS,
        "note": NOTE,
        "bars": bars,
    }
    return envelope(source=DAILY_SOURCE, status="ready" if bars else "empty", data=data)
