"""Pure calculation helpers (no I/O, no clock, fully unit-tested)."""

from __future__ import annotations

import math
from datetime import datetime, time
from typing import Iterable, Mapping, Optional, Sequence

from ..models import CN_TZ

OPEN_AM = time(9, 30)
CLOSE_AM = time(11, 30)
OPEN_PM = time(13, 0)
CLOSE_PM = time(15, 0)
SESSION_MINUTES = 240.0
LIMIT_TOLERANCE = 0.005


def _finite(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pct_change(price: Optional[float], prev_close: Optional[float]) -> Optional[float]:
    """``(price / prev_close - 1) * 100``; ``None`` instead of inf/NaN."""
    current = _finite(price)
    base = _finite(prev_close)
    if current is None or base is None or base <= 0:
        return None
    return (current / base - 1.0) * 100.0


def rel_300_pct(sector_change_pct: Optional[float], hs300_change_pct: Optional[float]) -> Optional[float]:
    """Arithmetic excess return in percentage points (contract: ``r_b - r_300``)."""
    sector = _finite(sector_change_pct)
    benchmark = _finite(hs300_change_pct)
    if sector is None or benchmark is None:
        return None
    return sector - benchmark


def relative_strength_pct(
    sector_change_pct: Optional[float], hs300_change_pct: Optional[float]
) -> Optional[float]:
    """Geometric relative strength in percent; used for internal sorting only."""
    sector = _finite(sector_change_pct)
    benchmark = _finite(hs300_change_pct)
    if sector is None or benchmark is None:
        return None
    denominator = 1.0 + benchmark / 100.0
    if denominator <= 0:
        return None
    return ((1.0 + sector / 100.0) / denominator - 1.0) * 100.0


def amount_share_ratio(amount_yuan: Optional[float], market_amount_yuan: Optional[float]) -> Optional[float]:
    """Industry amount divided by the whole-market amount (ratio, not percent)."""
    amount = _finite(amount_yuan)
    market = _finite(market_amount_yuan)
    if amount is None or market is None or market <= 0 or amount < 0:
        return None
    return amount / market


def up_ratio(up: Optional[int], down: Optional[int]) -> Optional[float]:
    """``up / (up + down)``; flat and suspended stocks are excluded."""
    if up is None or down is None:
        return None
    total = int(up) + int(down)
    if total <= 0:
        return None
    return int(up) / total


def seal_ratio(limit_up: Optional[int], broken: Optional[int]) -> Optional[float]:
    """``ZT / (ZT + ZB)``; ``None`` when both counts are unavailable."""
    if limit_up is None or broken is None:
        return None
    total = int(limit_up) + int(broken)
    if total <= 0:
        return None
    return int(limit_up) / total


def minutes_elapsed(now: datetime) -> float:
    """Trading minutes elapsed in the 240-minute A-share session."""
    local = now.astimezone(CN_TZ)
    clock = local.time()
    if clock < OPEN_AM:
        return 0.0
    if clock < CLOSE_AM:
        return (local.hour * 60 + local.minute + local.second / 60.0) - (9 * 60 + 30)
    if clock < OPEN_PM:
        return 120.0
    if clock < CLOSE_PM:
        return 120.0 + (local.hour * 60 + local.minute + local.second / 60.0) - 13 * 60
    return SESSION_MINUTES


def time_fraction(now: datetime) -> float:
    """Elapsed share of the session, floored at one minute and capped at 1."""
    return min(max(minutes_elapsed(now) / SESSION_MINUTES, 1.0 / SESSION_MINUTES), 1.0)


def volume_ratio(
    amount_yuan: Optional[float],
    baseline_mean_yuan: Optional[float],
    fraction: float,
) -> Optional[float]:
    """Relative volume against a 5-day cumulative baseline projected by ``f(t)``."""
    amount = _finite(amount_yuan)
    baseline = _finite(baseline_mean_yuan)
    if amount is None or baseline is None or baseline <= 0:
        return None
    if fraction <= 0:
        return None
    return amount / (baseline * fraction)


def rank_desc(values: Mapping[str, Optional[float]]) -> dict[str, int]:
    """Dense 1..N ranking by descending value; ties break on code for determinism."""
    usable = [(code, value) for code, value in values.items() if value is not None]
    usable.sort(key=lambda item: (-float(item[1]), item[0]))
    return {code: position + 1 for position, (code, _) in enumerate(usable)}


def rank_change(now_rank: Optional[int], before_rank: Optional[int]) -> Optional[int]:
    """Positive means the object moved up (a smaller rank number) since ``before``."""
    if now_rank is None or before_rank is None:
        return None
    return int(before_rank) - int(now_rank)


def small_sector(member_count: Optional[int], threshold: int = 10) -> bool:
    return member_count is not None and member_count < threshold


def is_b_share(code: str) -> bool:
    digits = code.split(".")[0]
    return digits.startswith(("900", "200"))


def is_new_stock(name: str) -> bool:
    stripped = (name or "").strip()
    return stripped.startswith(("N", "C"))


def is_st_stock(name: str) -> bool:
    upper = (name or "").upper().replace(" ", "")
    return "ST" in upper


def is_limit_up(price: Optional[float], limit_up: Optional[float]) -> bool:
    current = _finite(price)
    limit = _finite(limit_up)
    if current is None or limit is None or limit <= 0:
        return False
    return current >= limit - LIMIT_TOLERANCE


def is_limit_down(price: Optional[float], limit_down: Optional[float]) -> bool:
    current = _finite(price)
    limit = _finite(limit_down)
    if current is None or limit is None or limit <= 0:
        return False
    return current <= limit + LIMIT_TOLERANCE


def register_change(name: str) -> bool:
    """Exclude level-II/III duplicates and level suffixes from board rankings."""
    return not (name.endswith("Ⅱ") or name.endswith("Ⅲ") or name.endswith("II") or name.endswith("III"))


def dedupe_boards(names: Iterable[str]) -> list[str]:
    """Collapse ``保险Ⅱ``/``保险Ⅲ`` into one base name, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        base = name
        for suffix in ("Ⅲ", "Ⅱ", "III", "II"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if base in seen:
            continue
        seen.add(base)
        result.append(name)
    return result


def downsample(points: Sequence[tuple[datetime, float]], max_points: int = 120) -> list[tuple[datetime, float]]:
    """Uniformly thin a series, always keeping the first and last point."""
    if max_points <= 0 or len(points) <= max_points:
        return list(points)
    if max_points == 1:
        return [points[-1]]
    step = (len(points) - 1) / (max_points - 1)
    indices: list[int] = []
    for position in range(max_points):
        index = int(round(position * step))
        if not indices or index != indices[-1]:
            indices.append(index)
    return [points[index] for index in indices]


def regime(
    up: Optional[float],
    main_index_changes: Sequence[Optional[float]],
    risk_off_reasons: Sequence[str],
    *,
    risk_on_up_ratio: float = 0.6,
) -> tuple[str, list[str]]:
    """Deterministic ``risk_on|neutral|risk_off`` label plus human-readable reasons."""
    if risk_off_reasons:
        return "risk_off", list(risk_off_reasons)
    valid = [value for value in main_index_changes if value is not None]
    if (
        up is not None
        and up >= risk_on_up_ratio
        and len(valid) == len(main_index_changes)
        and len(valid) > 0
        and all(value > 0 for value in valid)
    ):
        return "risk_on", [
            f"上涨家数占比 {up:.2f} ≥ {risk_on_up_ratio:.2f}",
            "上证/深证/沪深300 均为正",
        ]
    reasons = []
    if up is not None:
        reasons.append(f"上涨家数占比 {up:.2f}")
    reasons.append("未满足 risk-on 条件（宽度≥0.6 且主要指数全为正）")
    return "neutral", reasons
