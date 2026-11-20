"""Pure rule evaluation. No clock, network or I/O access lives here."""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional, Sequence

from .models import Metrics, Quote, Rule

History = Sequence[tuple[datetime, float]]

# Absorbs binary floating-point noise at exact decimal boundaries (e.g.
# 13.5 * 1.005 == 13.567499999999999) without blurring meaningful differences.
_EPS = 1e-9


def _ge(left: float, right: float) -> bool:
    return left >= right - _EPS * max(1.0, abs(left), abs(right))


def _le(left: float, right: float) -> bool:
    return left <= right + _EPS * max(1.0, abs(left), abs(right))


def compute_metrics(quote: Quote) -> Metrics:
    change_pct: Optional[float] = None
    if quote.prev_close > 0:
        change_pct = (quote.price / quote.prev_close - 1.0) * 100.0

    vwap: Optional[float] = None
    if quote.volume_lots > 0 and quote.amount_yuan is not None and quote.amount_yuan > 0:
        vwap = quote.amount_yuan / (quote.volume_lots * 100.0)

    vwap_dev_pct: Optional[float] = None
    if vwap is not None and vwap > 0:
        vwap_dev_pct = (quote.price - vwap) / vwap * 100.0

    return Metrics(change_pct=change_pct, vwap=vwap, vwap_dev_pct=vwap_dev_pct)


_CN_TZ = timezone(timedelta(hours=8))
_SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))


def _same_continuous_session(start: datetime, end: datetime) -> bool:
    """True when ``start`` and ``end`` (naive times are taken as Asia/Shanghai) fall in the same morning or afternoon session."""
    a = start.astimezone(_CN_TZ).timetz().replace(tzinfo=None) if start.tzinfo else start.time()
    b = end.astimezone(_CN_TZ).timetz().replace(tzinfo=None) if end.tzinfo else end.time()
    return any(lo <= a <= hi and lo <= b <= hi for lo, hi in _SESSIONS)


def window_amounts(
    history: History, now: datetime, window_seconds: float
) -> Optional[tuple[float, float]]:
    """Return (W, P) for the two consecutive windows ending at ``now``.

    ``history`` must be chronological and end with the current sample.  ``W`` is
    the amount traded in the most recent window, ``P`` the amount traded in the
    window immediately before it.
    """
    if not history or window_seconds <= 0:
        return None
    # Both windows must lie inside one continuous-auction session. Otherwise the
    # earlier window is the pre-open or lunch gap (nothing trades), its amount is
    # 0, and any first prints "surge" against it: the opening-second false alarm.
    if not _same_continuous_session(now - timedelta(seconds=2 * window_seconds), now):
        return None
    times = [sample[0] for sample in history]
    amounts = [sample[1] for sample in history]
    first_ref = now - timedelta(seconds=2 * window_seconds)
    second_ref = now - timedelta(seconds=window_seconds)
    first_index = bisect_right(times, first_ref) - 1
    second_index = bisect_right(times, second_ref) - 1
    if first_index < 0 or second_index < 0:
        return None
    current = amounts[-1]
    traded_now = current - amounts[second_index]
    traded_before = amounts[second_index] - amounts[first_index]
    return traded_now, max(traded_before, 0.0)


def trigger(
    rule: Rule,
    quote: Quote,
    metrics: Metrics,
    prev_price: Optional[float],
    history: History,
    now: datetime,
) -> Optional[tuple[Optional[str], dict[str, Any]]]:
    """Return (direction, detail) when the rule condition holds, else None."""
    if rule.type == "pct_change":
        change = metrics.change_pct
        if change is None:
            return None
        threshold = float(rule.threshold_pct or 0.0)
        if rule.direction == "up" and _ge(change, threshold):
            return "up", {"threshold_pct": threshold, "change_pct": change}
        if rule.direction == "down" and _le(change, -threshold):
            return "down", {"threshold_pct": threshold, "change_pct": change}
        return None

    if rule.type == "vwap_deviation":
        dev = metrics.vwap_dev_pct
        if dev is None or quote.amount_yuan is None:
            return None
        gate = float(rule.min_amount_yuan or 0.0)
        if quote.amount_yuan < gate:
            return None
        threshold = float(rule.threshold_pct or 0.0)
        if _ge(abs(dev), threshold):
            return (
                "up" if dev > 0 else "down",
                {
                    "threshold_pct": threshold,
                    "vwap_dev_pct": dev,
                    "vwap": metrics.vwap,
                    "amount_yuan": quote.amount_yuan,
                    "min_amount_yuan": gate,
                },
            )
        return None

    if rule.type == "limit_proximity":
        within = float(rule.within_pct or 0.0)
        if rule.side == "up":
            if quote.limit_up > 0 and _ge(
                quote.price, quote.limit_up * (1.0 - within / 100.0)
            ):
                trigger_price = quote.limit_up * (1.0 - within / 100.0)
                return "up", {
                    "within_pct": within,
                    "limit_up": quote.limit_up,
                    "trigger_price": trigger_price,
                    "distance_pct": (quote.price - trigger_price) / trigger_price * 100.0,
                }
        else:
            if quote.limit_down > 0 and _le(
                quote.price, quote.limit_down * (1.0 + within / 100.0)
            ):
                trigger_price = quote.limit_down * (1.0 + within / 100.0)
                return "down", {
                    "within_pct": within,
                    "limit_down": quote.limit_down,
                    "trigger_price": trigger_price,
                    "distance_pct": (trigger_price - quote.price) / trigger_price * 100.0,
                }
        return None

    if rule.type == "price_cross":
        level = float(rule.level or 0.0)
        if prev_price is None or level <= 0:
            return None
        if rule.direction == "up" and prev_price < level and _ge(quote.price, level):
            return "up", {"level": level, "prev_price": prev_price}
        if rule.direction == "down" and prev_price > level and _le(quote.price, level):
            return "down", {"level": level, "prev_price": prev_price}
        return None

    if rule.type == "volume_surge":
        amounts = window_amounts(history, now, float(rule.window_seconds or 0.0))
        if amounts is None:
            return None
        current, previous = amounts
        multiple = float(rule.multiple or 0.0)
        minimum = float(rule.min_window_amount_yuan or 0.0)
        if _ge(current, multiple * previous) and _ge(current, minimum):
            return None, {
                "window_seconds": rule.window_seconds,
                "multiple": multiple,
                "window_amount": current,
                "prior_window_amount": previous,
                "min_window_amount_yuan": minimum,
            }
    return None


def retreated(
    rule: Rule,
    quote: Quote,
    metrics: Metrics,
    prev_price: Optional[float],
    history: History,
    now: datetime,
    rearm_pct: float,
) -> bool:
    """True when price/flow has crossed the rule-specific re-arm line."""
    if rule.type == "pct_change":
        change = metrics.change_pct
        if change is None:
            return False
        threshold = float(rule.threshold_pct or 0.0)
        if rule.direction == "up":
            return _le(change, threshold - rearm_pct)
        return _ge(change, -threshold + rearm_pct)

    if rule.type == "vwap_deviation":
        dev = metrics.vwap_dev_pct
        if dev is None:
            return False
        threshold = float(rule.threshold_pct or 0.0)
        return _le(abs(dev), threshold - rearm_pct)

    if rule.type == "limit_proximity":
        within = float(rule.within_pct or 0.0)
        if rule.side == "up":
            return quote.limit_up > 0 and _le(
                quote.price, quote.limit_up * (1.0 - (within + rearm_pct) / 100.0)
            )
        return quote.limit_down > 0 and _ge(
            quote.price, quote.limit_down * (1.0 + (within + rearm_pct) / 100.0)
        )

    if rule.type == "price_cross":
        level = float(rule.level or 0.0)
        if level <= 0:
            return False
        if rule.direction == "up":
            return _le(quote.price, level * (1.0 - rearm_pct / 100.0))
        return _ge(quote.price, level * (1.0 + rearm_pct / 100.0))

    if rule.type == "volume_surge":
        amounts = window_amounts(history, now, float(rule.window_seconds or 0.0))
        if amounts is None:
            return False
        current, previous = amounts
        return current < float(rule.multiple or 0.0) * previous * 0.8 - _EPS
    return False


def hot_distance(
    rule: Rule,
    quote: Quote,
    metrics: Metrics,
    prev_price: Optional[float],
) -> Optional[float]:
    """Percentage-point distance to the trigger line, or None if not applicable."""
    if rule.type == "pct_change":
        change = metrics.change_pct
        if change is None:
            return None
        threshold = float(rule.threshold_pct or 0.0)
        if rule.direction == "up":
            return threshold - change
        return threshold + change

    if rule.type == "vwap_deviation":
        dev = metrics.vwap_dev_pct
        if dev is None or quote.amount_yuan is None:
            return None
        if quote.amount_yuan < float(rule.min_amount_yuan or 0.0):
            return None
        return float(rule.threshold_pct or 0.0) - abs(dev)

    if rule.type == "limit_proximity":
        within = float(rule.within_pct or 0.0)
        if rule.side == "up":
            if quote.limit_up <= 0:
                return None
            trigger_price = quote.limit_up * (1.0 - within / 100.0)
            return (trigger_price - quote.price) / trigger_price * 100.0
        if quote.limit_down <= 0:
            return None
        trigger_price = quote.limit_down * (1.0 + within / 100.0)
        return (quote.price - trigger_price) / trigger_price * 100.0

    if rule.type == "price_cross":
        level = float(rule.level or 0.0)
        if level <= 0 or quote.price <= 0:
            return None
        return abs(quote.price - level) / level * 100.0

    return None
