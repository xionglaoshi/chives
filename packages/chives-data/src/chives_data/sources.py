"""Upstream adapters and parsers.

Every parser works on a recorded fixture in ``tests/fixtures``; network access is
only through :class:`HostGovernor` (fixed hosts, no redirects, no proxies).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import config
from .transport import HostGovernor, UpstreamError

TENCENT_QUOTE_HOST = "qt.gtimg.cn"
TENCENT_KLINE_HOST = "web.ifzq.gtimg.cn"
SINA_QUOTE_HOST = "hq.sinajs.cn"
SINA_MINUTE_HOST = "quotes.sina.cn"
SINA_DAILY_HOST = "finance.sina.com.cn"
EASTMONEY_DATA_HOST = "datacenter.eastmoney.com"

TENCENT_QUOTE_URL = "/q={symbols}"
TENCENT_KLINE_PATH = "/appstock/app/fqkline/get"
TENCENT_MINUTE_PATH = "/appstock/app/minute/query"
SINA_QUOTE_URL = "/list={symbols}"
SINA_REFERER = "https://finance.sina.com.cn"
TENCENT_REFERER = "https://gu.qq.com/"
NY, HK, SH = "America/New_York", "Asia/Hong_Kong", "Asia/Shanghai"
STALE_AFTER_DAYS = 4

_CN_TZ = timezone(timedelta(hours=8))
_TENCENT_LINE = re.compile(r'^v_([A-Za-z0-9.]+)="(.*)";?$')
_SINA_LINE = re.compile(r'^var hq_str_([A-Za-z0-9_.]+)="(.*)";?$')


# --------------------------------------------------------------------------- helpers


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, list):
        return [dict(item) for item in frame if isinstance(item, dict)]
    if isinstance(frame, dict) and isinstance(frame.get("records"), list):
        return [dict(item) for item in frame["records"] if isinstance(item, dict)]
    to_dict = getattr(frame, "to_dict", None)
    if callable(to_dict):
        return [dict(item) for item in to_dict("records")]
    return []


def _localize(naive: datetime, tz_name: str) -> datetime:
    return naive.replace(tzinfo=ZoneInfo(tz_name))


def _parse_time(text: str, tz_name: str) -> datetime | None:
    text = str(text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return _localize(datetime.strptime(text, fmt), tz_name)
        except ValueError:
            continue
    return None


def _iso(stamp: datetime | date | None) -> str | None:
    if stamp is None:
        return None
    if isinstance(stamp, datetime):
        return stamp.isoformat(timespec="seconds")
    return stamp.isoformat()


# --------------------------------------------------------------------------- A-share quote


def parse_tencent_quotes(text: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        match = _TENCENT_LINE.match(line.strip())
        if match is None:
            continue
        fields = match.group(2).split("~")
        if len(fields) < 38:
            continue
        digits = fields[2].strip()
        if len(digits) != 6 or not digits.isdigit():
            continue
        symbol_key = match.group(1).lower()
        price = _number(fields[3])
        prev = _number(fields[4])
        change = _number(fields[32])
        if price is not None and prev not in (None, 0):
            computed = round((price / prev - 1.0) * 100.0, 4)
            if change is None or abs(computed - change) > 0.05:
                change = computed
        raw_time = fields[30].strip()
        quote_time: datetime | None = None
        if len(raw_time) == 14 and raw_time.isdigit():
            try:
                quote_time = datetime.strptime(raw_time, "%Y%m%d%H%M%S").replace(tzinfo=_CN_TZ)
            except ValueError:
                quote_time = None
        limit_up = _number(fields[47]) if len(fields) > 47 else None
        limit_down = _number(fields[48]) if len(fields) > 48 else None
        rows[symbol_key] = {
            "name": "".join(fields[1].split()),
            "price": price,
            "prev_close": prev,
            "open": _number(fields[5]),
            "high": _number(fields[33]),
            "low": _number(fields[34]),
            "change_pct": change,
            "volume_lots": _number(fields[6]),
            "amount_wan": _number(fields[37]),
            "turnover_pct": _number(fields[38]) if len(fields) > 38 else None,
            "pe": _number(fields[39]) if len(fields) > 39 else None,
            "pb": _number(fields[46]) if len(fields) > 46 else None,
            "volume_ratio": _number(fields[49]) if len(fields) > 49 else None,
            "limit_up": limit_up if limit_up is not None and limit_up > 0 else None,
            "limit_down": limit_down if limit_down is not None and limit_down > 0 else None,
            "quote_time": quote_time,
        }
    return rows


def parse_sina_quotes(text: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        match = _SINA_LINE.match(line.strip())
        if match is None or not match.group(2).strip():
            continue
        symbol = match.group(1)
        if not re.fullmatch(r"(sh|sz|bj)\d{6}", symbol):
            continue
        fields = match.group(2).split(",")
        if len(fields) < 32:
            continue
        price = _number(fields[3])
        prev = _number(fields[2])
        change = None
        if price is not None and prev not in (None, 0):
            change = round((price / prev - 1.0) * 100.0, 4)
        stamp = _parse_time(f"{fields[30]} {fields[31]}", SH)
        rows[symbol] = {
            "name": "".join(fields[0].split()),
            "price": price,
            "prev_close": prev,
            "open": _number(fields[1]),
            "high": _number(fields[4]),
            "low": _number(fields[5]),
            "change_pct": change,
            "volume_shares": _int(fields[8]),
            "amount_yuan": _number(fields[9]),
            "quote_time": stamp,
        }
    return rows


# --------------------------------------------------------------------------- daily / minute


def _sina_daily_rows(frame: Any, start: date, end: date) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for row in _records(frame):
        raw_date = row.get("date")
        if raw_date is None:
            continue
        try:
            day = datetime.fromisoformat(str(raw_date)[:10]).date()
        except ValueError:
            continue
        if day < start or day > end:
            continue
        prices = [_number(row.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None for value in prices):
            continue
        volume = _number(row.get("volume"))
        amount = _number(row.get("amount"))
        turnover = _number(row.get("turnover"))
        float_shares = _number(row.get("outstanding_share"))
        bars.append(
            {
                "date": day.isoformat(),
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume_shares": None if volume is None else int(round(volume)),
                "amount_yuan": None if amount is None else round(amount, 2),
                "turnover_pct": None if turnover is None else round(turnover * 100.0, 4),
                "float_shares": None if float_shares is None else int(round(float_shares)),
            }
        )
    bars.sort(key=lambda item: item["date"])
    return bars


def parse_sina_index_daily(frame: Any) -> list[dict[str, Any]]:
    """Index daily history. Frames that carry an amount column keep the legacy lot unit."""
    bars: list[dict[str, Any]] = []
    for row in _records(frame):
        raw_date = row.get("date")
        try:
            day = datetime.fromisoformat(str(raw_date)[:10]).date()
        except (TypeError, ValueError):
            continue
        prices = [_number(row.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None for value in prices):
            continue
        volume = _number(row.get("volume"))
        amount = _number(row.get("amount"))
        if volume is not None and amount is not None:
            volume = volume * 100  # legacy index source publishes lots
        bars.append(
            {
                "date": day.isoformat(),
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume_shares": None if volume is None else int(round(volume)),
                "amount_yuan": None if amount is None else round(amount, 2),
                "turnover_pct": None,
            }
        )
    bars.sort(key=lambda item: item["date"])
    return bars


def parse_tencent_kline(payload: Any, symbol: str, *, start: date, end: date, adjust: str | None = None) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    node = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(node, dict):
        raise UpstreamError("parse_empty", circuit=False)
    lines = (node.get("day") or node.get("qfqday") or node.get("hfqday")) if adjust is None else node.get({"none":"day","qfq":"qfqday","hfq":"hfqday"}[adjust])
    if not isinstance(lines, list) or not lines:
        raise UpstreamError("parse_empty", circuit=False)
    bars: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, (list, tuple)) or len(line) < 6:
            continue
        try:
            day = datetime.fromisoformat(str(line[0]).strip()[:10]).date()
        except ValueError:
            continue
        if day < start or day > end:
            continue
        open_ = _number(line[1])
        close = _number(line[2])
        high = _number(line[3])
        low = _number(line[4])
        volume = _number(line[5])
        if any(value is None for value in (open_, close, high, low)):
            continue
        if close is not None and high is not None and low is not None and not low <= close <= high:
            continue
        bars.append(
            {
                "date": day.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume_shares": None if volume is None else int(round(volume if symbol.startswith(("sh688", "sh689")) else volume * 100)),
                "amount_yuan": None,
                "turnover_pct": None,
            }
        )
    bars.sort(key=lambda item: item["date"])
    return bars


def parse_sina_minutes(frame: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in _records(frame):
        stamp = record.get("day")
        if stamp is None:
            continue
        try:
            moment = datetime.fromisoformat(str(stamp).replace(" ", "T"))
        except ValueError:
            continue
        prices = [_number(record.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None for value in prices):
            continue
        volume = _number(record.get("volume"))
        amount = _number(record.get("amount"))
        rows.append(
            {
                "ts": moment.replace(tzinfo=_CN_TZ),
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume_shares": None if volume is None else int(round(volume)),
                "amount_yuan": amount,
            }
        )
    rows.sort(key=lambda item: item["ts"])
    return rows


def parse_tencent_minutes(payload: Any, symbol: str) -> tuple[date | None, list[dict[str, Any]]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    node = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(node, dict):
        raise UpstreamError("parse_empty", circuit=False)
    body = node.get("data") if isinstance(node.get("data"), dict) else None
    lines = body.get("data") if isinstance(body, dict) else None
    raw_date = body.get("date") if isinstance(body, dict) else None
    if not isinstance(lines, list) or not lines:
        raise UpstreamError("parse_empty", circuit=False)
    day: date | None = None
    if isinstance(raw_date, str) and len(raw_date) >= 8 and raw_date[:8].isdigit():
        try:
            day = datetime.strptime(raw_date[:8], "%Y%m%d").date()
        except ValueError:
            day = None
    rows: list[dict[str, Any]] = []
    previous_volume = 0
    previous_amount = 0.0
    previous_price: float | None = None
    for line in lines:
        parts = str(line).split()
        if len(parts) < 4:
            continue
        raw_time, raw_price, raw_volume, raw_amount = parts[:4]
        if len(raw_time) != 4 or not raw_time.isdigit():
            continue
        price = _number(raw_price)
        cumulative_volume = _number(raw_volume)
        cumulative_amount = _number(raw_amount)
        if price is None or cumulative_volume is None or cumulative_amount is None:
            continue
        moment = datetime.strptime(raw_time, "%H%M").replace(tzinfo=_CN_TZ)
        open_ = previous_price if previous_price is not None else price
        rows.append(
            {
                "ts": moment,
                "open": open_,
                "high": max(open_, price),
                "low": min(open_, price),
                "close": price,
                "volume_shares": max(0, int(round((cumulative_volume - previous_volume) * 100))),
                "amount_yuan": max(0.0, round(cumulative_amount - previous_amount, 2)),
            }
        )
        previous_price = price
        previous_volume = int(round(cumulative_volume))
        previous_amount = cumulative_amount
    return day, rows


# --------------------------------------------------------------------------- global parsers


def _tencent_rows(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _TENCENT_LINE.match(line.strip())
        if match is not None:
            rows[match.group(1)] = match.group(2).split("~")
    return rows


def _sina_rows(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _SINA_LINE.match(line.strip())
        if match is not None and match.group(2).strip():
            rows[match.group(1)] = match.group(2).split(",")
    return rows


def _cell(fields: list[str], index: int) -> str:
    return fields[index] if index < len(fields) else ""


def _item(
    key: str,
    name: str,
    *,
    price: float | None,
    prev_close: float | None,
    change_pct: float | None,
    quote_time: datetime | date | None,
    quote_tz: str,
    source: str,
    now: datetime,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    computed = False
    if price is not None and prev_close not in (None, 0):
        calc = round((price / prev_close - 1.0) * 100.0, 4)
        if change_pct is None:
            change_pct, computed = calc, True
        elif abs(calc - change_pct) > 0.05:
            change_pct, computed = calc, True
            reason = reason or "source_change_pct_mismatch"
    if price is not None and change_pct is None and reason is None:
        reason = "change_pct_unavailable"

    stale = True
    shown: str | None = None
    if isinstance(quote_time, datetime):
        shown = quote_time.isoformat(timespec="seconds")
        stale = now - quote_time > timedelta(days=STALE_AFTER_DAYS)
    elif isinstance(quote_time, date):
        shown = quote_time.isoformat()
        stale = (now.astimezone(ZoneInfo(quote_tz)).date() - quote_time).days > STALE_AFTER_DAYS
    elif reason is None:
        reason = "quote_time_unavailable"

    entry: dict[str, Any] = {
        "key": key,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "quote_time": shown,
        "quote_tz": quote_tz,
        "source": source,
        "stale": stale,
    }
    if computed:
        entry["computed"] = True
    if reason:
        entry["reason"] = reason
    entry.update(extra)
    return entry


def _missing(key: str, name: str, tz: str, source: str, reason: str, now: datetime, **extra: Any) -> dict[str, Any]:
    return _item(
        key,
        name,
        price=None,
        prev_close=None,
        change_pct=None,
        quote_time=None,
        quote_tz=tz,
        source=source,
        now=now,
        reason=reason,
        **extra,
    )


def parse_global_tencent(text: str, *, now: datetime) -> dict[str, list[str]]:
    return _tencent_rows(text)


def parse_global_sina(text: str, *, now: datetime) -> dict[str, list[str]]:
    return _sina_rows(text)


def tencent_item(key: str, name: str | None, symbol: str, fields: list[str] | None, *, now: datetime, **extra: Any) -> dict[str, Any]:
    tz = HK if symbol.startswith("hk") else NY
    label = name or symbol
    if fields is None or len(fields) < 33:
        return _missing(key, label, tz, TENCENT_QUOTE_HOST, "not_found_upstream", now, **extra)
    price = _number(fields[3])
    if price is None or price <= 0:
        return _missing(key, name or fields[1].strip() or symbol, tz, TENCENT_QUOTE_HOST, "no_price", now, **extra)
    prev = _number(fields[4])
    if prev is not None and prev <= 0:
        prev = None
    return _item(
        key,
        name or fields[1].strip() or symbol,
        price=price,
        prev_close=prev,
        change_pct=_number(fields[32]),
        quote_time=_parse_time(fields[30], tz),
        quote_tz=tz,
        source=TENCENT_QUOTE_HOST,
        now=now,
        **extra,
    )


def sina_item(key: str, name: str, symbol: str, fields: list[str] | None, *, now: datetime) -> dict[str, Any]:
    tz = NY if symbol.startswith("gb_") else SH
    if fields is None:
        return _missing(key, name, tz, SINA_QUOTE_HOST, "not_found_upstream", now)
    if symbol.startswith("hf_"):
        price = _number(_cell(fields, 0))
        if len(fields) < 13 or price is None or price <= 0:
            return _missing(key, name, SH, SINA_QUOTE_HOST, "no_price", now)
        quote_time = _parse_time(f"{_cell(fields, 12)} {_cell(fields, 6)}", SH)
        high, low = _number(_cell(fields, 4)), _number(_cell(fields, 5))
        settle, open_ = _number(_cell(fields, 7)), _number(_cell(fields, 8))
        if high is None or low is None or settle is None or open_ is None or settle <= 0 or not low <= open_ <= high:
            return _item(
                key, name, price=price, prev_close=None, change_pct=None, quote_time=quote_time,
                quote_tz=SH, source=SINA_QUOTE_HOST, now=now, reason="field_check_failed",
            )
        return _item(
            key, name, price=price, prev_close=settle, change_pct=None, quote_time=quote_time,
            quote_tz=SH, source=SINA_QUOTE_HOST, now=now, prev_close_kind="settle",
        )
    if symbol.startswith("fx_"):
        price = _number(_cell(fields, 8))
        if len(fields) < 18 or price is None or price <= 0:
            return _missing(key, name, SH, SINA_QUOTE_HOST, "no_price", now)
        prev = _number(_cell(fields, 3))
        pct = _number(_cell(fields, 10))
        change = _number(_cell(fields, 11))
        reason = None
        if not _consistent(price, prev, change, pct):
            prev, pct, reason = None, None, "field_check_failed"
        return _item(
            key, name, price=price, prev_close=prev, change_pct=pct,
            quote_time=_parse_time(f"{_cell(fields, 17)} {_cell(fields, 0)}", SH),
            quote_tz=SH, source=SINA_QUOTE_HOST, now=now, reason=reason,
        )
    if symbol == "DINIW":
        price = _number(_cell(fields, 8))
        if len(fields) < 11 or price is None or price <= 0:
            return _missing(key, name, SH, SINA_QUOTE_HOST, "no_price", now)
        quote_time = _parse_time(f"{_cell(fields, 10)} {_cell(fields, 0)}", SH)
        prev, span = _number(_cell(fields, 3)), _number(_cell(fields, 4))
        open_, high, low = _number(_cell(fields, 5)), _number(_cell(fields, 6)), _number(_cell(fields, 7))
        layout_ok = (
            None not in (prev, span, open_, high, low)
            and prev > 0  # type: ignore[operator]
            and abs((high - low) * 10000 - span) <= 1.5  # type: ignore[operator]
            and low <= open_ <= high  # type: ignore[operator]
            and low <= price <= high  # type: ignore[operator]
        )
        if not layout_ok:
            return _item(
                key, name, price=price, prev_close=None, change_pct=None, quote_time=quote_time,
                quote_tz=SH, source=SINA_QUOTE_HOST, now=now, reason="field_check_failed",
            )
        return _item(
            key, name, price=price, prev_close=prev, change_pct=None, quote_time=quote_time,
            quote_tz=SH, source=SINA_QUOTE_HOST, now=now, caveat="prev_close_by_layout",
        )
    if symbol.startswith("gb_"):
        price = _number(_cell(fields, 1))
        if len(fields) < 27 or price is None or price <= 0:
            return _missing(key, name, NY, SINA_QUOTE_HOST, "no_price", now)
        prev = _number(_cell(fields, 26))
        pct = _number(_cell(fields, 2))
        change = _number(_cell(fields, 4))
        reason = None
        if not _consistent(price, prev, change, pct):
            prev, pct, reason = None, None, "field_check_failed"
        return _item(
            key, name, price=price, prev_close=prev, change_pct=pct,
            quote_time=_parse_est(_cell(fields, 24), now), quote_tz=NY, source=SINA_QUOTE_HOST,
            now=now, reason=reason, caveat="instrument_identity_unverified",
        )
    return _missing(key, name, tz, SINA_QUOTE_HOST, "unsupported_symbol", now)


def _consistent(price: float, prev: float | None, change: float | None, pct: float | None) -> bool:
    if prev is None or prev <= 0 or change is None or pct is None:
        return False
    return abs(price - change - prev) <= max(1e-4, abs(prev) * 1e-5) and abs(change / prev * 100 - pct) <= 0.02


def _parse_est(text: str, now: datetime) -> datetime | None:
    match = re.match(r"^([A-Z][a-z]{2} \d{1,2} \d{1,2}:\d{2}[AP]M) E[SD]T$", str(text).strip())
    if match is None:
        return None
    now_ny = now.astimezone(ZoneInfo(NY))
    for year in (now_ny.year, now_ny.year - 1):
        try:
            candidate = _localize(datetime.strptime(f"{year} {match.group(1)}", "%Y %b %d %I:%M%p"), NY)
        except ValueError:
            continue
        if candidate <= now_ny + timedelta(days=2):
            return candidate
    return None


def parse_bond_frame(frame: Any) -> dict[str, dict[date, float]]:
    series: dict[str, dict[date, float]] = {}
    columns = {
        "us2y": "美国国债收益率2年",
        "us10y": "美国国债收益率10年",
        "cn10y": "中国国债收益率10年",
    }
    for key, column in columns.items():
        values: dict[date, float] = {}
        for row in _records(frame):
            if column not in row:
                continue
            try:
                day = datetime.fromisoformat(str(row.get("日期"))[:10]).date()
            except (TypeError, ValueError):
                continue
            number = _number(row.get(column))
            if number is not None:
                values[day] = number
        series[key] = values
    return series


def rate_items(series: dict[str, dict[date, float]], *, now: datetime) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, name, tz in (
        ("us2y", "美债2年收益率", NY),
        ("us10y", "美债10年收益率", NY),
        ("cn10y", "中债10年收益率", SH),
    ):
        values = series.get(key) or {}
        if not values:
            items.append(_missing(key, name, tz, EASTMONEY_DATA_HOST, "series_unavailable", now, unit="pct"))
            continue
        days = sorted(values)
        last = days[-1]
        price = round(values[last], 4)
        prev = round(values[days[-2]], 4) if len(days) > 1 else None
        entry = _item(
            key, name, price=price, prev_close=None, change_pct=None, quote_time=last,
            quote_tz=tz, source=EASTMONEY_DATA_HOST, now=now, reason="yield_change_in_bp", unit="pct",
        )
        entry["prev_close"] = prev
        entry["change_bp"] = round((price - prev) * 100.0, 1) if prev is not None else None
        items.append(entry)
    us10 = series.get("us10y") or {}
    cn10 = series.get("cn10y") or {}
    common = sorted(set(us10) & set(cn10))
    spread = {day: us10[day] - cn10[day] for day in common}
    if not spread:
        items.append(
            _missing("cn_us_10y_spread", "中美10年利差(美-中,百分点)", NY, EASTMONEY_DATA_HOST,
                     "series_unavailable", now, unit="pct_points")
        )
    else:
        last = sorted(spread)[-1]
        price = round(spread[last], 4)
        prev = round(spread[sorted(spread)[-2]], 4) if len(spread) > 1 else None
        entry = _item(
            "cn_us_10y_spread", "中美10年利差(美-中,百分点)", price=price, prev_close=None,
            change_pct=None, quote_time=last, quote_tz=NY, source=EASTMONEY_DATA_HOST, now=now,
            reason="yield_change_in_bp", unit="pct_points",
        )
        entry["prev_close"] = prev
        entry["change_bp"] = round((price - prev) * 100.0, 1) if prev is not None else None
        entry["computed"] = True
        items.append(entry)
    return items


# --------------------------------------------------------------------------- source facade


class AkShareAdapter:
    """All AKShare calls go through a worker thread with a hard timeout."""

    def __init__(self, governor: HostGovernor) -> None:
        self.governor = governor

    def stock_zh_a_daily(self, symbol: str, start_date: str, end_date: str, adjust: str) -> Any:
        import akshare as ak

        def call() -> Any:
            if hasattr(ak, "stock_zh_a_daily"):
                return ak.stock_zh_a_daily(
                    symbol=symbol, start_date=start_date, end_date=end_date, adjust=adjust
                )
            return ak.stock_zh_a_hist_sina(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

        return self.governor.run_external(SINA_DAILY_HOST, call)

    def stock_zh_a_minute(self, symbol: str, period: str) -> Any:
        import akshare as ak

        def call() -> Any:
            if hasattr(ak, "stock_zh_a_minute"):
                return ak.stock_zh_a_minute(symbol=symbol, period=period, adjust="")
            return ak.stock_zh_a_hist_min_sina(symbol=symbol, period=period, adjust="")

        return self.governor.run_external(SINA_MINUTE_HOST, call)

    def stock_zh_index_daily(self, symbol: str) -> Any:
        import akshare as ak

        def call() -> Any:
            if hasattr(ak, "stock_zh_index_daily"):
                return ak.stock_zh_index_daily(symbol=symbol)
            return ak.index_zh_daily_sina(symbol=symbol)

        return self.governor.run_external(SINA_DAILY_HOST, call)

    def bond_zh_us_rate(self, start_date: str) -> Any:
        import akshare as ak

        return self.governor.run_external(
            EASTMONEY_DATA_HOST,
            lambda: ak.bond_zh_us_rate(start_date=start_date),
        )


class Sources:
    def __init__(self, governor: HostGovernor, akshare: Any | None = None) -> None:
        self.governor = governor
        self.akshare = akshare or AkShareAdapter(governor)

    # -- quotes ---------------------------------------------------------
    def tencent_quotes(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        text = self.governor.request(
            TENCENT_QUOTE_HOST,
            TENCENT_QUOTE_URL.format(symbols=",".join(symbols)),
            headers={"Referer": TENCENT_REFERER},
            encoding="gbk",
        )
        return parse_tencent_quotes(text)

    def sina_quotes(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        text = self.governor.request(
            SINA_QUOTE_HOST,
            SINA_QUOTE_URL.format(symbols=",".join(symbols)),
            headers={"Referer": SINA_REFERER},
            encoding="gbk",
        )
        return parse_sina_quotes(text)

    # -- daily ----------------------------------------------------------
    def sina_daily(self, symbol: str, start: date, end: date, adjust: str) -> list[dict[str, Any]]:
        frame = self.akshare.stock_zh_a_daily(
            symbol,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            "" if adjust == "none" else adjust,
        )
        return _sina_daily_rows(frame, start, end)

    def sina_index_daily(self, symbol: str) -> list[dict[str, Any]]:
        frame = self.akshare.stock_zh_index_daily(symbol)
        return parse_sina_index_daily(frame)

    def tencent_daily(self, symbol: str, start: date, end: date, adjust: str, limit: int) -> list[dict[str, Any]]:
        count = min(1000, max(300, limit * 2))
        param = f"{symbol},day,{start.strftime('%Y-%m-%d')},{end.strftime('%Y-%m-%d')},{count},{'' if adjust == 'none' else adjust}"
        text = self.governor.request(
            TENCENT_KLINE_HOST,
            TENCENT_KLINE_PATH,
            params={"param": param},
            headers={"Referer": TENCENT_REFERER},
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpstreamError("invalid_json", circuit=False) from exc
        return parse_tencent_kline(payload, symbol, start=start, end=end, adjust=adjust)

    def sina_minutes(self, symbol: str, period: str) -> list[dict[str, Any]]:
        frame = self.akshare.stock_zh_a_minute(symbol, period)
        return parse_sina_minutes(frame)

    def tencent_minutes(self, symbol: str) -> tuple[date | None, list[dict[str, Any]]]:
        text = self.governor.request(
            TENCENT_KLINE_HOST,
            TENCENT_MINUTE_PATH,
            params={"code": symbol},
            headers={"Referer": TENCENT_REFERER},
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpstreamError("invalid_json", circuit=False) from exc
        return parse_tencent_minutes(payload, symbol)

    # -- global ---------------------------------------------------------
    def global_tencent(self, symbols: Iterable[str], *, now: datetime) -> dict[str, list[str]]:
        text = self.governor.request(
            TENCENT_QUOTE_HOST,
            TENCENT_QUOTE_URL.format(symbols=",".join(symbols)),
            headers={"Referer": TENCENT_REFERER},
            encoding="gbk",
        )
        return parse_global_tencent(text, now=now)

    def global_sina(self, symbols: Iterable[str], *, now: datetime) -> dict[str, list[str]]:
        text = self.governor.request(
            SINA_QUOTE_HOST,
            SINA_QUOTE_URL.format(symbols=",".join(symbols)),
            headers={"Referer": SINA_REFERER},
            encoding="gbk",
        )
        return parse_global_sina(text, now=now)

    # -- rates ----------------------------------------------------------
    def bond_rates(self, start: date) -> dict[str, dict[date, float]]:
        frame = self.akshare.bond_zh_us_rate(start.strftime("%Y%m%d"))
        return parse_bond_frame(frame)
