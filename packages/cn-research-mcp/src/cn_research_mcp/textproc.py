"""Cleaning and validation for third-party text, links and timestamps. Pure functions, no I/O."""

from __future__ import annotations

import html
import math
import re
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta, timezone
from numbers import Integral, Number, Real
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

CN_TZ = timezone(timedelta(hours=8))
LINK_DOMAINS = ("eastmoney.com", "cls.cn", "cninfo.com.cn", "10jqka.com.cn")

_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")
_MISSING_TEXT = {"nan", "nat", "none", "null"}
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)
_TIME_FORMATS = ("%H:%M:%S", "%H:%M")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_TEXT
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_text(value: Any, limit: int | None = None) -> tuple[str | None, bool]:
    """Strip HTML tags/control chars, collapse whitespace, then truncate to `limit` chars incl. the ellipsis.

    Content is never rewritten or summarised. Returns (text_or_none, truncated).
    """
    if is_missing(value):
        return None, False
    text = html.unescape(str(value))
    previous = None
    while text != previous:
        previous = text
        text = _TAG_RE.sub("", text)
    text = _CONTROL_RE.sub("", text).replace("\u200b", "").replace("\ufeff", "")
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return None, False
    if limit is not None and len(text) > limit:
        if limit <= 1:
            return "…", True
        return text[: limit - 1].rstrip() + "…", True
    return text, False


def clean_link(value: Any) -> str | None:
    """Keep only http(s) links whose host is one of LINK_DOMAINS or a subdomain of it; else None."""
    text, _ = clean_text(value)
    if not text:
        return None
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").rstrip(".").lower()
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not host:
        return None
    if any(host == domain or host.endswith(f".{domain}") for domain in LINK_DOMAINS):
        return text
    return None


def to_datetime(value: Any) -> datetime | None:
    """Parse a datetime/date/ISO-like string into an aware +08:00 datetime; None if impossible."""
    if is_missing(value):
        return None
    moment: datetime
    if isinstance(value, pd.Timestamp):
        moment = value.to_pydatetime()
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, date_type):
        moment = datetime(value.year, value.month, value.day, tzinfo=CN_TZ)
    else:
        text = str(value).strip()
        if not text:
            return None
        candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            moment = None  # type: ignore[assignment]
            for fmt in _DATETIME_FORMATS:
                try:
                    moment = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if moment is None:
                return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CN_TZ)
    try:
        return moment.astimezone(CN_TZ)
    except (OverflowError, ValueError):
        return None


def parse_time(value: Any) -> str | None:
    """ISO8601 with +08:00, or None. Never substitutes the fetch time."""
    moment = to_datetime(value)
    return None if moment is None else moment.isoformat(timespec="seconds")


def parse_date(value: Any) -> str | None:
    moment = to_datetime(value)
    return None if moment is None else moment.date().isoformat()


def combine_date_time(date_value: Any, time_value: Any) -> str | None:
    """Combine an upstream date column and time column (time may be a time object or 'HH:MM[:SS]')."""
    day = to_datetime(date_value)
    if day is None:
        return parse_time(time_value)
    if is_missing(time_value):
        return datetime.combine(day.date(), time_type(0, 0), tzinfo=CN_TZ).isoformat(timespec="seconds")
    moment: time_type | None = None
    if isinstance(time_value, time_type):
        moment = time_value.replace(tzinfo=None)
    elif isinstance(time_value, datetime):
        moment = time_value.timetz().replace(tzinfo=None)
    else:
        text = str(time_value).strip()
        try:
            moment = time_type.fromisoformat(text)
        except ValueError:
            for fmt in _TIME_FORMATS:
                try:
                    moment = datetime.strptime(text, fmt).time()
                    break
                except ValueError:
                    continue
        if moment is None:
            parsed = to_datetime(text)
            if parsed is None:
                return None
            moment = parsed.timetz().replace(tzinfo=None)
    return datetime.combine(day.date(), moment, tzinfo=CN_TZ).isoformat(timespec="seconds")


def raw_value(value: Any) -> Any:
    """Keep an upstream value as-is (number or text); no unit conversion, no rounding."""
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    text, _ = clean_text(value)
    return text


def to_number(value: Any) -> float | None:
    if is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, Number):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
