"""Overnight / overseas market snapshot: Tencent (us/hk), Sina (futures, fx, HXC) and AKShare rates."""

from __future__ import annotations

import logging
import math
import re
import socket
import threading
import time
from collections.abc import Callable, Iterable
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from cn_extra_mcp import overseas_map, sources
from cn_extra_mcp.envelope import envelope
from cn_extra_mcp.symbols import InvalidSymbol, normalize_overseas_symbol

logger = logging.getLogger(__name__)

SNAPSHOT_SOURCE = "qt.gtimg.cn+hq.sinajs.cn+akshare.bond_zh_us_rate"
QUOTE_SOURCE = "qt.gtimg.cn"
SINA_SOURCE = "hq.sinajs.cn"
TENCENT_SOURCE = "qt.gtimg.cn"
RATES_SOURCE = "akshare.bond_zh_us_rate"

GROUPS = ("us_index", "hk_index", "a50", "fx", "commodity", "rates", "leaders")
STALE_AFTER_DAYS = 4
QUOTE_TTL = 30.0
RATES_TTL = 1800.0
UPSTREAM_GAP = 1.0
AKSHARE_TIMEOUT = 20.0
MAX_OVERSEAS_SYMBOLS = 10

NY, HK, SH = "America/New_York", "Asia/Hong_Kong", "Asia/Shanghai"

# (key, upstream symbol, display name)
TENCENT_SPECS: dict[str, list[tuple[str, str, str]]] = {
    "us_index": [("dji", "usDJI", "道琼斯"), ("ixic", "usIXIC", "纳斯达克"), ("spx", "usINX", "标普500")],
    "hk_index": [("hsi", "hkHSI", "恒生指数"), ("hstech", "hkHSTECH", "恒生科技指数")],
}
SINA_SPECS: dict[str, list[tuple[str, str, str]]] = {
    "us_index": [("hxc", "gb_hxc", "纳斯达克中国金龙")],
    "a50": [("a50", "hf_CHA50CFD", "富时中国A50期货")],
    "fx": [("usdcnh", "fx_susdcnh", "离岸人民币"), ("dxy", "DINIW", "美元指数")],
    "commodity": [("crude_oil", "hf_CL", "纽约原油"), ("gold", "hf_GC", "纽约黄金"), ("copper", "hf_HG", "美铜")],
}

_TENCENT_LINE = re.compile(r'^v_([A-Za-z0-9.]+)="(.*)";?$')
_SINA_LINE = re.compile(r'^var hq_str_([A-Za-z0-9_.]+)="(.*)";?$')

# injectable clock / throttling / cache, so tests stay offline and instant
_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
_sleep: Callable[[float], None] = time.sleep
_monotonic: Callable[[], float] = time.monotonic
_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, Any]] = {}
_LAST_CALL: dict[str, float] = {}


def clear_cache() -> None:
    _CACHE.clear()
    _LAST_CALL.clear()


def _cached_fetch(upstream: str, key: tuple[str, ...], ttl: float, fn: Callable[[], Any]) -> Any:
    entry = _CACHE.get((upstream, key))
    if entry is not None and _monotonic() < entry[0]:
        return entry[1]
    last = _LAST_CALL.get(upstream)
    if last is not None:
        wait = UPSTREAM_GAP - (_monotonic() - last)
        if wait > 0:
            _sleep(wait)
    try:
        value = fn()
    finally:
        _LAST_CALL[upstream] = _monotonic()
    _CACHE[(upstream, key)] = (_monotonic() + ttl, value)
    return value


def _failure(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower():
        return "upstream_timeout", f"upstream timed out ({type(exc).__name__})"
    return "upstream_error", f"upstream failed ({type(exc).__name__})"


def _run_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"akshare call exceeded {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _float(text: Any) -> float | None:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _localize(naive: datetime, tz_name: str) -> datetime:
    return naive.replace(tzinfo=ZoneInfo(tz_name))


def _parse_time(text: str, tz_name: str) -> datetime | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return _localize(datetime.strptime(text, fmt), tz_name)
        except ValueError:
            continue
    return None


def _item(
    key: str,
    name: str,
    *,
    price: float | None,
    prev_close: float | None,
    change_pct: float | None,
    quote_time: datetime | date_type | None,
    quote_tz: str,
    source: str,
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

    now = _now()
    stale = True
    shown: str | None = None
    if isinstance(quote_time, datetime):
        shown = quote_time.isoformat(timespec="seconds")
        stale = now - quote_time > timedelta(days=STALE_AFTER_DAYS)
    elif isinstance(quote_time, date_type):
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


def _missing(key: str, name: str, tz: str, source: str, reason: str, **extra: Any) -> dict[str, Any]:
    return _item(key, name, price=None, prev_close=None, change_pct=None, quote_time=None,
                 quote_tz=tz, source=source, reason=reason, **extra)


# --------------------------------------------------------------------------- Tencent

def _tencent_rows(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _TENCENT_LINE.match(line.strip())
        if match is not None:
            rows[match.group(1)] = match.group(2).split("~")
    return rows


def _tencent_item(key: str, name: str | None, symbol: str, fields: list[str] | None, **extra: Any) -> dict[str, Any]:
    tz = HK if symbol.startswith("hk") else NY
    label = name or symbol
    if fields is None or len(fields) < 33:
        return _missing(key, label, tz, TENCENT_SOURCE, "not_found_upstream", **extra)
    price = _float(fields[3])
    if price is None or price <= 0:
        return _missing(key, name or fields[1].strip() or symbol, tz, TENCENT_SOURCE, "no_price", **extra)
    prev = _float(fields[4])
    if prev is not None and prev <= 0:
        prev = None
    return _item(
        key,
        name or fields[1].strip() or symbol,
        price=price,
        prev_close=prev,
        change_pct=_float(fields[32]),
        quote_time=_parse_time(fields[30], tz),
        quote_tz=tz,
        source=TENCENT_SOURCE,
        **extra,
    )


# --------------------------------------------------------------------------- Sina

def _sina_rows(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _SINA_LINE.match(line.strip())
        if match is not None and match.group(2).strip():
            rows[match.group(1)] = match.group(2).split(",")
    return rows


def _cell(fields: list[str], index: int) -> str:
    return fields[index] if index < len(fields) else ""


def _sina_hf(key: str, name: str, fields: list[str]) -> dict[str, Any]:
    # 0 price, 4 high, 5 low, 6 time, 7 prev settle, 8 open, 12 date. 7 vs 8 was settled on the
    # 2026-11-16/17 samples: field 7 sits outside the day's high-low range (hf_CL, hf_HG), so it cannot
    # be the open; field 8 always sits inside it.
    price = _float(_cell(fields, 0))
    if len(fields) < 13 or price is None or price <= 0:
        return _missing(key, name, SH, SINA_SOURCE, "no_price")
    quote_time = _parse_time(f"{_cell(fields, 12)} {_cell(fields, 6)}", SH)
    high, low = _float(_cell(fields, 4)), _float(_cell(fields, 5))
    settle, open_ = _float(_cell(fields, 7)), _float(_cell(fields, 8))
    if (high is None or low is None or settle is None or open_ is None
            or settle <= 0 or not low <= open_ <= high):
        return _item(key, name, price=price, prev_close=None, change_pct=None, quote_time=quote_time,
                     quote_tz=SH, source=SINA_SOURCE, reason="field_check_failed")
    return _item(key, name, price=price, prev_close=settle, change_pct=None, quote_time=quote_time,
                 quote_tz=SH, source=SINA_SOURCE, prev_close_kind="settle")


def _consistent(price: float, prev: float | None, change: float | None, pct: float | None) -> bool:
    """Cross-field guard: price - change == prev and change/prev ~= pct (as the recorded samples satisfy)."""
    if prev is None or prev <= 0 or change is None or pct is None:
        return False
    return abs(price - change - prev) <= max(1e-4, abs(prev) * 1e-5) and abs(change / prev * 100 - pct) <= 0.02


def _sina_fx(key: str, name: str, fields: list[str]) -> dict[str, Any]:
    # 0 time, 3 prev close, 8 price, 10 change %, 11 change abs, 17 date (checked on the recorded sample)
    price = _float(_cell(fields, 8))
    if len(fields) < 18 or price is None or price <= 0:
        return _missing(key, name, SH, SINA_SOURCE, "no_price")
    prev = _float(_cell(fields, 3))
    pct = _float(_cell(fields, 10))
    change = _float(_cell(fields, 11))
    reason = None
    if not _consistent(price, prev, change, pct):
        prev, pct, reason = None, None, "field_check_failed"
    quote_time = _parse_time(f"{_cell(fields, 17)} {_cell(fields, 0)}", SH)
    return _item(key, name, price=price, prev_close=prev, change_pct=pct, quote_time=quote_time,
                 quote_tz=SH, source=SINA_SOURCE, reason=reason)


def _sina_dxy(key: str, name: str, fields: list[str]) -> dict[str, Any]:
    # Same layout as fx_ (whose index 3 is cross-checked against its change fields):
    # 0 time, 3 prev close, 4 range in 1e-4 units, 5 open, 6 high, 7 low, 8 price, 10 date.
    # DINIW has no change fields, so the layout itself is the check: 4 == (6 - 7) * 1e4, open/price in range.
    price = _float(_cell(fields, 8))
    if len(fields) < 11 or price is None or price <= 0:
        return _missing(key, name, SH, SINA_SOURCE, "no_price")
    quote_time = _parse_time(f"{_cell(fields, 10)} {_cell(fields, 0)}", SH)
    prev, span = _float(_cell(fields, 3)), _float(_cell(fields, 4))
    open_, high, low = _float(_cell(fields, 5)), _float(_cell(fields, 6)), _float(_cell(fields, 7))
    layout_ok = (
        None not in (prev, span, open_, high, low)
        and prev > 0  # type: ignore[operator]
        and abs((high - low) * 10000 - span) <= 1.5  # type: ignore[operator]
        and low <= open_ <= high  # type: ignore[operator]
        and low <= price <= high  # type: ignore[operator]
    )
    if not layout_ok:
        return _item(key, name, price=price, prev_close=None, change_pct=None, quote_time=quote_time,
                     quote_tz=SH, source=SINA_SOURCE, reason="field_check_failed")
    return _item(key, name, price=price, prev_close=prev, change_pct=None, quote_time=quote_time,
                 quote_tz=SH, source=SINA_SOURCE, caveat="prev_close_by_layout")


def _parse_est(text: str) -> datetime | None:
    match = re.match(r"^([A-Z][a-z]{2} \d{1,2} \d{1,2}:\d{2}[AP]M) E[SD]T$", text.strip())
    if match is None:
        return None
    now_ny = _now().astimezone(ZoneInfo(NY))
    for year in (now_ny.year, now_ny.year - 1):
        try:
            candidate = _localize(datetime.strptime(f"{year} {match.group(1)}", "%Y %b %d %I:%M%p"), NY)
        except ValueError:
            continue
        if candidate <= now_ny + timedelta(days=2):
            return candidate
    return None


def _sina_hxc(key: str, name: str, fields: list[str]) -> dict[str, Any]:
    # 1 price, 2 change %, 4 change abs, 24 quote time (US Eastern text), 26 prev close
    price = _float(_cell(fields, 1))
    if len(fields) < 27 or price is None or price <= 0:
        return _missing(key, name, NY, SINA_SOURCE, "no_price")
    prev = _float(_cell(fields, 26))
    pct = _float(_cell(fields, 2))
    change = _float(_cell(fields, 4))
    reason = None
    if not _consistent(price, prev, change, pct):
        prev, pct, reason = None, None, "field_check_failed"
    return _item(key, name, price=price, prev_close=prev, change_pct=pct,
                 quote_time=_parse_est(_cell(fields, 24)), quote_tz=NY, source=SINA_SOURCE,
                 reason=reason, caveat="instrument_identity_unverified")


def _sina_item(key: str, name: str, symbol: str, fields: list[str] | None) -> dict[str, Any]:
    tz = NY if symbol.startswith("gb_") else SH
    if fields is None:
        return _missing(key, name, tz, SINA_SOURCE, "not_found_upstream")
    if symbol.startswith("hf_"):
        return _sina_hf(key, name, fields)
    if symbol.startswith("fx_"):
        return _sina_fx(key, name, fields)
    if symbol == "DINIW":
        return _sina_dxy(key, name, fields)
    if symbol.startswith("gb_"):
        return _sina_hxc(key, name, fields)
    return _missing(key, name, tz, SINA_SOURCE, "unsupported_symbol")


# --------------------------------------------------------------------------- rates

def _series(frame: pd.DataFrame, column: str) -> dict[date_type, float]:
    out: dict[date_type, float] = {}
    for stamp, value in zip(frame["日期"], frame[column]):
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(number):
            continue
        out[pd.to_datetime(stamp).date()] = float(number)
    return out


def _rate_item(key: str, name: str, tz: str, series: dict[date_type, float] | None, *,
               computed: bool = False, unit: str = "pct") -> dict[str, Any]:
    if not series:
        return _missing(key, name, tz, RATES_SOURCE, "series_unavailable", unit=unit)
    days = sorted(series)
    last = days[-1]
    price = round(series[last], 4)
    prev = round(series[days[-2]], 4) if len(days) > 1 else None
    entry = _item(
        key, name, price=price, prev_close=None, change_pct=None, quote_time=last,
        quote_tz=tz, source=RATES_SOURCE, reason="yield_change_in_bp", unit=unit,
    )
    entry["prev_close"] = prev
    entry["change_bp"] = round((price - prev) * 100.0, 1) if prev is not None else None
    if computed:
        entry["computed"] = True
    return entry


def _rates_items(frame: pd.DataFrame) -> list[dict[str, Any]]:
    us2 = _series(frame, "美国国债收益率2年") if "美国国债收益率2年" in frame.columns else None
    us10 = _series(frame, "美国国债收益率10年") if "美国国债收益率10年" in frame.columns else None
    cn10 = _series(frame, "中国国债收益率10年") if "中国国债收益率10年" in frame.columns else None
    items = [
        _rate_item("us2y", "美债2年收益率", NY, us2),
        _rate_item("us10y", "美债10年收益率", NY, us10),
        _rate_item("cn10y", "中债10年收益率", SH, cn10),
    ]
    if us10 and cn10:
        common = sorted(set(us10) & set(cn10))
        spread = {d: us10[d] - cn10[d] for d in common}
        entry = _rate_item("cn_us_10y_spread", "中美10年利差(美-中,百分点)", NY, spread,
                           computed=True, unit="pct_points")
        if not spread:
            entry["reason"] = "no_common_date"
        items.append(entry)
    else:
        items.append(_missing("cn_us_10y_spread", "中美10年利差(美-中,百分点)", NY, RATES_SOURCE,
                              "series_unavailable", unit="pct_points"))
    return items


# --------------------------------------------------------------------------- snapshot

def _group_result(items: list[dict[str, Any]], errors: list[tuple[str, str]]) -> dict[str, Any]:
    if errors:
        code, message = errors[0]
        return {"ok": False, "status": "error", "error": {"code": code, "message": message}, "items": items}
    return {"ok": True, "status": "ready" if items else "empty", "items": items}


def _invalid(message: str) -> dict[str, Any]:
    return envelope(source=SNAPSHOT_SOURCE, status="error", error_code="invalid_argument", error_message=message)


def cn_get_global_snapshot(groups: Iterable[str] | None = None) -> dict[str, Any]:
    if groups is None:
        selected = list(GROUPS)
    else:
        if isinstance(groups, (str, bytes)) or not isinstance(groups, Iterable):
            return _invalid("groups must be a list of group names")
        selected = []
        for group in groups:
            if not isinstance(group, str) or group not in GROUPS:
                return _invalid(f"unknown group {group!r}; allowed: {', '.join(GROUPS)}")
            if group not in selected:
                selected.append(group)
        if not selected:
            return _invalid("groups must contain at least one group")

    leaders: list[dict[str, Any]] | None = None
    leader_error: tuple[str, str] | None = None
    if "leaders" in selected:
        try:
            leaders = overseas_map.load_map()
        except overseas_map.MapError as exc:
            leader_error = ("invalid_overseas_map", "; ".join(exc.errors[:10]))

    tencent_symbols: list[str] = []
    sina_symbols: list[str] = []
    for group in selected:
        tencent_symbols += [s for _, s, _ in TENCENT_SPECS.get(group, [])]
        sina_symbols += [s for _, s, _ in SINA_SPECS.get(group, [])]
    if leaders:
        tencent_symbols += [leader["symbol"] for leader in leaders]
    tencent_symbols = list(dict.fromkeys(tencent_symbols))
    sina_symbols = list(dict.fromkeys(sina_symbols))

    tencent_rows: dict[str, list[str]] = {}
    tencent_err: tuple[str, str] | None = None
    if tencent_symbols:
        try:
            text = _cached_fetch("tencent", tuple(tencent_symbols), QUOTE_TTL,
                                 lambda: sources.fetch_tencent_text(tencent_symbols))
            tencent_rows = _tencent_rows(text)
        except Exception as exc:  # external source boundary
            logger.error("tencent fetch failed: %s", type(exc).__name__)
            tencent_err = _failure(exc)

    sina_rows: dict[str, list[str]] = {}
    sina_err: tuple[str, str] | None = None
    if sina_symbols:
        try:
            text = _cached_fetch("sina", tuple(sina_symbols), QUOTE_TTL,
                                 lambda: sources.fetch_sina_text(sina_symbols))
            sina_rows = _sina_rows(text)
        except Exception as exc:
            logger.error("sina fetch failed: %s", type(exc).__name__)
            sina_err = _failure(exc)

    result: dict[str, dict[str, Any]] = {}
    for group in selected:
        if group == "rates":
            result[group] = _rates_group()
            continue
        if group == "leaders":
            result[group] = _leaders_group(leaders, leader_error, tencent_rows, tencent_err)
            continue
        items: list[dict[str, Any]] = []
        errors: list[tuple[str, str]] = []
        specs_t = TENCENT_SPECS.get(group, [])
        specs_s = SINA_SPECS.get(group, [])
        for key, symbol, name in specs_t:
            if tencent_err:
                items.append(_missing(key, name, HK if symbol.startswith("hk") else NY,
                                      TENCENT_SOURCE, "upstream_failed"))
            else:
                items.append(_tencent_item(key, name, symbol, tencent_rows.get(symbol)))
        for key, symbol, name in specs_s:
            if sina_err:
                items.append(_missing(key, name, NY if symbol.startswith("gb_") else SH,
                                      SINA_SOURCE, "upstream_failed"))
            else:
                items.append(_sina_item(key, name, symbol, sina_rows.get(symbol)))
        if specs_t and tencent_err:
            errors.append(tencent_err)
        if specs_s and sina_err:
            errors.append(sina_err)
        result[group] = _group_result(items, errors)

    failed = [g for g in selected if not result[g]["ok"]]
    warnings = [f"group_failed:{g}" for g in failed]
    if all(not result[g]["ok"] for g in selected):
        first = result[selected[0]]["error"]
        payload = envelope(
            source=SNAPSHOT_SOURCE, status="error", data={"groups": result, "stale_after_days": STALE_AFTER_DAYS},
            error_code=first["code"], error_message=first["message"], warnings=warnings,
        )
        return payload
    return envelope(
        source=SNAPSHOT_SOURCE,
        status="ready",
        data={"groups": result, "stale_after_days": STALE_AFTER_DAYS},
        warnings=warnings,
    )


def _rates_group() -> dict[str, Any]:
    start = (_now().astimezone(ZoneInfo(SH)) - timedelta(days=30)).strftime("%Y%m%d")
    try:
        frame = _cached_fetch("akshare", ("bond_zh_us_rate", start), RATES_TTL,
                              lambda: _run_with_timeout(lambda: sources.fetch_bond_frame(start), AKSHARE_TIMEOUT))
        if frame is None or len(frame) == 0 or "日期" not in frame.columns:
            return _group_result([], [("upstream_error", "rates source returned no usable rows")])
        return _group_result(_rates_items(frame), [])
    except Exception as exc:
        logger.error("rates fetch failed: %s", type(exc).__name__)
        return _group_result([], [_failure(exc)])


def _leaders_group(
    leaders: list[dict[str, Any]] | None,
    leader_error: tuple[str, str] | None,
    rows: dict[str, list[str]],
    tencent_err: tuple[str, str] | None,
) -> dict[str, Any]:
    if leader_error:
        return _group_result([], [leader_error])
    if leaders is None:
        return {"ok": True, "status": "empty", "reason": "map_not_configured", "items": []}
    if not leaders:
        return {"ok": True, "status": "empty", "reason": "map_has_no_leaders", "items": []}
    items = []
    for leader in leaders:
        extra = {"a_share_sectors": leader["a_share_sectors"], "note": leader["note"]}
        symbol = leader["symbol"]
        if tencent_err:
            items.append(_missing(symbol, leader["name"], HK if symbol.startswith("hk") else NY,
                                  TENCENT_SOURCE, "upstream_failed", **extra))
        else:
            items.append(_tencent_item(symbol, leader["name"], symbol, rows.get(symbol), **extra))
    return _group_result(items, [tencent_err] if tencent_err else [])


def cn_get_overseas_quote(symbols: Any) -> dict[str, Any]:
    def bad(message: str) -> dict[str, Any]:
        return envelope(source=QUOTE_SOURCE, status="error", error_code="invalid_argument", error_message=message)

    if isinstance(symbols, (str, bytes)) or not isinstance(symbols, Iterable):
        return bad("symbols must be a list of overseas symbols")
    listed = list(symbols)
    if not listed:
        return bad("symbols must contain at least one symbol")
    if len(listed) > MAX_OVERSEAS_SYMBOLS:
        return bad(f"at most {MAX_OVERSEAS_SYMBOLS} symbols per request")
    clean: list[str] = []
    for item in listed:
        try:
            symbol = normalize_overseas_symbol(item)
        except InvalidSymbol as exc:
            return bad(str(exc))
        if symbol not in clean:
            clean.append(symbol)
    try:
        text = _cached_fetch("tencent", tuple(clean), QUOTE_TTL, lambda: sources.fetch_tencent_text(clean))
    except Exception as exc:
        logger.error("overseas quote fetch failed: %s", type(exc).__name__)
        code, message = _failure(exc)
        return envelope(source=QUOTE_SOURCE, status="error", error_code=code, error_message=message)
    rows = _tencent_rows(text)
    items = [_tencent_item(symbol, None, symbol, rows.get(symbol)) for symbol in clean]
    return envelope(source=QUOTE_SOURCE, status="ready", data=items)
