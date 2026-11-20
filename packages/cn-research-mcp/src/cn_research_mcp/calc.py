"""Pure helpers: value coercion, percentile rank, windows and down-sampling. No I/O."""

from __future__ import annotations

import math
import re
from datetime import date as date_type
from typing import Any

import pandas as pd

MIN_PERCENTILE_SAMPLES = 60
MAX_SERIES_POINTS = 160


def fnum(value: Any) -> float | None:
    """float or None; NaN, inf, None, NaT and non-numeric text become None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fint(value: Any) -> int | None:
    number = fnum(value)
    return None if number is None else int(round(number))


def ftext(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def fdate(value: Any) -> str | None:
    """YYYY-MM-DD or None; accepts date, datetime, Timestamp and ISO-like text."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (date_type, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else (text or None)


def percentile_rank(values: list[float], current: float) -> float:
    """Share (0-100, 2 decimals) of samples that are <= current. Samples include current itself."""
    if not values:
        raise ValueError("no samples")
    return round(sum(1 for v in values if v <= current) / len(values) * 100.0, 2)


def positive_samples(values: list[float | None]) -> tuple[list[float], int]:
    """Drop None/NaN and non-positive values; return (kept, number of non-positive dropped)."""
    kept: list[float] = []
    nonpositive = 0
    for v in values:
        if v is None:
            continue
        if v <= 0:
            nonpositive += 1
        else:
            kept.append(v)
    return kept, nonpositive


def window_start(last: pd.Timestamp, years: int) -> pd.Timestamp:
    return last - pd.DateOffset(years=years)


def in_window(frame: pd.DataFrame, date_col: str, years: int) -> pd.DataFrame:
    """Rows with date_col in (last - years, last]; frame must carry datetime64 dates."""
    last = frame[date_col].max()
    return frame[frame[date_col] > window_start(last, years)]


def percentile_block(values: list[float | None], current: float | None) -> dict[str, Any]:
    """Percentile of `current` in the positive samples; null + reason when not computable."""
    kept, nonpositive = positive_samples(values)
    block: dict[str, Any] = {"pct": None, "samples": len(kept), "excluded_nonpositive": nonpositive}
    if current is None:
        block["reason"] = "current_value_missing"
    elif current <= 0:
        block["reason"] = "current_value_nonpositive"
    elif len(kept) < MIN_PERCENTILE_SAMPLES:
        block["reason"] = "insufficient_samples"
    else:
        block["pct"] = percentile_rank(kept, current)
    return block


def last_per_group(frame: pd.DataFrame, date_col: str, freq: str) -> pd.DataFrame:
    """Last row of each ISO week ('week') or calendar month ('month'); frame sorted ascending."""
    dates = frame[date_col]
    if freq == "week":
        iso = dates.dt.isocalendar()
        keys = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    elif freq == "month":
        keys = dates.dt.year * 100 + dates.dt.month
    else:
        raise ValueError(freq)
    return frame.groupby(keys.to_numpy(), sort=True).tail(1)


def cap_points(frame: pd.DataFrame, limit: int = MAX_SERIES_POINTS) -> tuple[pd.DataFrame, int]:
    """Keep every step-th row counting back from the final row so the last point is retained."""
    count = len(frame)
    if count <= limit:
        return frame, 1
    step = math.ceil(count / limit)
    positions = list(range(count - 1, -1, -step))[::-1]
    return frame.iloc[positions], step


def bond_conversion_value(conversion_price: Any, underlying_price: Any) -> float | None:
    """100 / conversion price * underlying price; None when an input is missing or non-positive."""
    price = fnum(conversion_price)
    underlying = fnum(underlying_price)
    if price is None or underlying is None or price <= 0:
        return None
    return 100.0 / price * underlying


def bond_premium_pct(bond_price: Any, conversion_value: Any) -> float | None:
    """(bond price / conversion value - 1) * 100; None when an input is missing or non-positive."""
    price = fnum(bond_price)
    value = fnum(conversion_value)
    if price is None or value is None or value <= 0:
        return None
    return (price / value - 1.0) * 100.0


_QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def recent_report_periods(today: date_type, count: int = 5) -> list[str]:
    """The `count` report periods ending on or before `today`, newest first (ISO dates)."""
    if count < 1:
        raise ValueError("count must be positive")
    candidates: list[date_type] = []
    year = today.year
    while len(candidates) < count:
        for month, day in reversed(_QUARTER_ENDS):
            candidate = date_type(year, month, day)
            if candidate <= today:
                candidates.append(candidate)
                if len(candidates) == count:
                    break
        year -= 1
    return [item.isoformat() for item in candidates]
