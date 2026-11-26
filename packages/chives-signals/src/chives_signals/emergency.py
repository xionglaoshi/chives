"""Emergency rules driven only by adopted thresholds (no built-in defaults).

Three deterministic conditions:

* any core index falls at least ``emergency_index_drop_pct`` from yesterday's close;
* the market-watch limit-down count reaches ``emergency_limit_down_count``;
* a holding hits its limit-down price or is suspended (chives-radar state).

A missing threshold never fires: suggestions alone are inert.  One emergency per
``(day, reason)``; outside the 09:30-15:00 session on a trading day nothing fires.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping, Optional

from .calendar import TradingCalendar
from .models import CN_TZ

INDEX_CODES = {
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000852.SH",
    "000688.SH",
}
EMERGENCY_LABELS = {
    "index_drop": "核心指数盘中跌幅达线",
    "limit_down_count": "跌停家数达线",
    "holding_limit_down": "持仓股跌停",
    "holding_suspended": "持仓股停牌",
}
EMERGENCY_STEPS = (
    "暂停新增风险",
    "核实行情/成交/公告",
    "查组合敞口与现金",
    "按既定规则处理",
    "记录事件与偏差",
)
INDEX_THRESHOLD_KEY = "emergency_index_drop_pct"
LIMIT_DOWN_THRESHOLD_KEY = "emergency_limit_down_count"


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def market_session(now: datetime, calendar: TradingCalendar) -> bool:
    local = now.astimezone(CN_TZ)
    if not calendar.is_trading_day(local.date()):
        return False
    minutes = local.hour * 60 + local.minute
    return 9 * 60 + 30 <= minutes <= 15 * 60


def limit_ratio(code: str) -> float:
    if code.startswith(("300", "301", "688", "689")):
        return 0.2
    return 0.1


def is_suspended(quote: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(quote, Mapping):
        return False
    if quote.get("suspended") is True:
        return True
    return str(quote.get("status") or "").lower() in {"suspended", "halt", "halted", "停牌"}


def is_limit_down(code: str, quote: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(quote, Mapping):
        return False
    price = _num(quote.get("price"))
    if price is None or price <= 0:
        return False
    explicit = _num(quote.get("limit_down"))
    if explicit is not None:
        return price <= explicit + 0.005
    prev_close = _num(quote.get("prev_close"))
    if prev_close is not None and prev_close > 0:
        limit = round(prev_close * (1 - limit_ratio(code)), 2)
        return price <= limit + 0.005
    change = _num(quote.get("change_pct"))
    if change is None:
        return False
    return change <= -(limit_ratio(code) * 100.0 - 0.2)


def evaluate(
    *,
    thresholds: Mapping[str, Optional[float]],
    overview: Optional[Mapping[str, Any]],
    quotes: Mapping[str, Any],
    positions: list[Mapping[str, Any]],
    limit_down_count: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return the emergency hits that the adopted thresholds actually justify."""
    hits: list[dict[str, Any]] = []
    drop_threshold = _num(thresholds.get(INDEX_THRESHOLD_KEY))
    if drop_threshold is not None and drop_threshold > 0 and isinstance(overview, Mapping):
        worst: Optional[tuple[str, str, float]] = None
        indexes = overview.get("indexes")
        for item in indexes or []:
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("code") or "")
            if code not in INDEX_CODES:
                continue
            change = _num(item.get("change_pct"))
            if change is None:
                price = _num(item.get("price"))
                prev_close = _num(item.get("prev_close"))
                if price is not None and prev_close is not None and prev_close > 0:
                    change = (price / prev_close - 1.0) * 100.0
            if change is None or change > -drop_threshold:
                continue
            if worst is None or change < worst[2]:
                worst = (code, str(item.get("name") or code), change)
        if worst is not None:
            hits.append(
                {
                    "reason": "index_drop",
                    "detail": f"{worst[1]} 盘中 {worst[2]:.2f}%，达到应急线 {drop_threshold:g}%",
                    "values": {
                        "code": worst[0],
                        "change_pct": worst[2],
                        "threshold_pct": drop_threshold,
                    },
                }
            )
    count_threshold = _num(thresholds.get(LIMIT_DOWN_THRESHOLD_KEY))
    if count_threshold is not None and count_threshold > 0:
        count = limit_down_count
        if count is None and isinstance(overview, Mapping):
            breadth = overview.get("breadth")
            if isinstance(breadth, Mapping):
                value = _num(breadth.get("limit_down"))
                count = None if value is None else int(value)
        if count is not None and count >= count_threshold:
            hits.append(
                {
                    "reason": "limit_down_count",
                    "detail": f"跌停 {int(count)} 家，达到应急线 {count_threshold:g} 家",
                    "values": {"count": int(count), "threshold": count_threshold},
                }
            )
    suspended: list[str] = []
    limit_down: list[str] = []
    for position in positions:
        if not isinstance(position, Mapping):
            continue
        code = str(position.get("code") or "")
        if not code:
            continue
        quote = quotes.get(code) if isinstance(quotes, Mapping) else None
        if not isinstance(quote, Mapping):
            continue
        if is_suspended(quote):
            suspended.append(code)
        elif is_limit_down(code, quote):
            limit_down.append(code)
    if limit_down:
        hits.append(
            {
                "reason": "holding_limit_down",
                "detail": f"持仓 {len(limit_down)} 只跌停",
                "values": {"codes": limit_down},
            }
        )
    if suspended:
        hits.append(
            {
                "reason": "holding_suspended",
                "detail": f"持仓 {len(suspended)} 只停牌",
                "values": {"codes": suspended},
            }
        )
    return hits


def hit_label(reason: str) -> str:
    return EMERGENCY_LABELS.get(reason, "应急触发")
