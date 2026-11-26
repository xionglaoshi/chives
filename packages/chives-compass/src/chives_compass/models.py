"""Shared value objects and China-time helpers.

Every timestamp handled by the engine is timezone aware and expressed in the
fixed UTC+8 zone used by the A-share market (no DST).  Nothing in this module
reads the wall clock; time always enters through the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

CN_TZ = timezone(timedelta(hours=8))


def to_cn(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(CN_TZ)


def parse_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected an ISO8601 timestamp")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        raise ValueError("ISO8601 timestamp must include a timezone offset")
    return to_cn(parsed)


def parse_exch_time(value: Any) -> datetime:
    """Accept Tencent's ``YYYYMMDDHHMMSS`` or an ISO8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing exchange time")
    text = value.strip()
    if len(text) == 14 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=CN_TZ)
    return parse_iso(text)


def fmt_iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else to_cn(value).isoformat()


def parse_date(value: Any) -> Optional[datetime]:
    """Parse ``YYYY-MM-DD`` (or a full ISO stamp) into midnight China time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()[:10]
    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=CN_TZ)


@dataclass(frozen=True)
class IndexQuote:
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    change_pct: float
    amount_yuan: Optional[float]
    volume_lots: int
    exch_time: datetime
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None


@dataclass(frozen=True)
class StockQuote:
    code: str
    name: str
    price: float
    prev_close: float
    change_pct: float
    amount_yuan: Optional[float]
    volume_lots: int
    exch_time: datetime
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None


@dataclass(frozen=True)
class MemberQuote:
    """One constituent of a Shenwan level-1 industry."""

    code: str
    name: str
    price: float
    change_pct: float
    amount_yuan: Optional[float]
    weight_pct: Optional[float]
    limit_up: bool
    limit_down: bool


@dataclass(frozen=True)
class LimitPool:
    as_of: datetime
    limit_up: Optional[int]
    limit_down: Optional[int]
    broken: Optional[int]
    seal_ratio: Optional[float]
    max_streak: Optional[int]
    zt_codes: tuple[str, ...] = ()
    zb_codes: tuple[str, ...] = ()
    dt_codes: tuple[str, ...] = ()
    stale: bool = False
    reason: Optional[str] = None
    #: v1.4: normalised row dicts per pool (``zt`` / ``zb`` / ``dt``).  Kept in
    #: the persisted block so the current day's detail survives a restart
    #: before sqlite ``pool_day`` is written.
    details: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Breadth:
    up: int
    down: int
    flat: int
    up_ratio: Optional[float]
    amount_yuan: Optional[float]
    as_of: Optional[datetime]
    fetched_at: Optional[datetime]
    source: str
    reason: Optional[str] = None

    @property
    def total(self) -> int:
        return self.up + self.down + self.flat


@dataclass(frozen=True)
class SectorQuote:
    """Realtime Shenwan level-1 industry row (units already converted)."""

    code: str
    name: str
    change_pct: float
    amount_yuan: Optional[float]
    prev_close: Optional[float] = None
    price: Optional[float] = None
    as_of: Optional[datetime] = None


@dataclass(frozen=True)
class MoverRow:
    """One row of the all-A gainers / losers / turnover list."""

    code: str
    name: str
    price: Optional[float]
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    turnover_pct: Optional[float] = None
    industry: Optional[str] = None


@dataclass(frozen=True)
class FlowRow:
    """One row of the main-net-inflow ranking (v1.3).

    ``main_net_yuan`` is the vendor value in yuan (``None`` when missing);
    ``main_net_pct`` is already a percentage of turnover.
    """

    code: str
    name: str
    main_net_yuan: Optional[float]
    main_net_pct: Optional[float]
    change_pct: Optional[float]
    amount_yuan: Optional[float]


@dataclass(frozen=True)
class BoardQuote:
    """One industry board row (units already converted)."""

    code: str
    name: str
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    up: Optional[int]
    down: Optional[int]
    flat: Optional[int]
    leader_code: Optional[str] = None
    leader_name: Optional[str] = None
    leader_change_pct: Optional[float] = None
    price: Optional[float] = None
    prev_close: Optional[float] = None
    as_of: Optional[datetime] = None
    #: Sina industry/concept strings carry the constituent count but no
    #: up/down/flat split; ``None`` falls back to ``up+down+flat``.
    member_total: Optional[int] = None

    @property
    def member_count(self) -> Optional[int]:
        if self.member_total is not None:
            return self.member_total
        if self.up is None or self.down is None or self.flat is None:
            return None
        return self.up + self.down + self.flat


@dataclass
class Block:
    """A data block plus the freshness metadata required by the contract."""

    value: Any = None
    as_of: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    source: str = ""
    reason: Optional[str] = None
    stale: bool = False
    #: T138: set when the block was served by a non-primary fallback source.
    fallback: bool = False
    fallback_reason: Optional[str] = None

    def age_seconds(self, now: datetime) -> Optional[float]:
        if self.fetched_at is None:
            return None
        return max(0.0, (now - self.fetched_at).total_seconds())


_DATETIME_FIELDS: dict[str, frozenset[str]] = {
    "IndexQuote": frozenset({"exch_time"}),
    "StockQuote": frozenset({"exch_time"}),
    "MemberQuote": frozenset(),
    "BoardQuote": frozenset({"as_of"}),
    "SectorQuote": frozenset({"as_of"}),
    "Breadth": frozenset({"as_of", "fetched_at"}),
    "LimitPool": frozenset({"as_of"}),
}
_TUPLE_FIELDS: dict[str, frozenset[str]] = {
    "LimitPool": frozenset({"zt_codes", "zb_codes", "dt_codes"}),
}


def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """JSON-safe representation of a quote/value object (datetimes as ISO)."""
    payload: dict[str, Any] = {}
    for item in fields(obj):
        value = getattr(obj, item.name)
        if isinstance(value, datetime):
            payload[item.name] = fmt_iso(value)
        elif isinstance(value, tuple):
            payload[item.name] = list(value)
        else:
            payload[item.name] = value
    return payload


def dataclass_from_dict(cls: type, data: Any) -> Any:
    """Rebuild one of the quote/value dataclasses from ``dataclass_to_dict``."""
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} snapshot must be a mapping")
    dt_fields = _DATETIME_FIELDS.get(cls.__name__, frozenset())
    tuple_fields = _TUPLE_FIELDS.get(cls.__name__, frozenset())
    kwargs: dict[str, Any] = {}
    for item in fields(cls):
        if item.name not in data:
            continue
        value = data[item.name]
        if item.name in dt_fields:
            value = None if value is None else parse_iso(value)
        elif item.name in tuple_fields:
            value = tuple(value or ())
        kwargs[item.name] = value
    return cls(**kwargs)
