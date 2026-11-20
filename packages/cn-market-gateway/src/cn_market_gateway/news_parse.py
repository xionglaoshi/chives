"""Pure parsing for news, announcements and convertible bonds (T143).

No I/O here: the module turns upstream records into the gateway's row shapes,
normalizes third-party text/timestamps and applies the documented truncation.
"""

from __future__ import annotations

import html
import math
import re
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta, timezone
from typing import Any, Callable, Iterable

from . import config

CN_TZ = timezone(timedelta(hours=8))

_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")
_MISSING_TEXT = {"nan", "nat", "none", "null", "-", "--"}
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
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_TEXT
    return False


def clean_text(value: Any, limit: int | None = None) -> tuple[str | None, bool]:
    """Strip HTML/control chars, collapse whitespace, then truncate (never rewritten)."""
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


def text(value: Any, limit: int | None = None) -> str | None:
    return clean_text(value, limit)[0]


def fnum(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        raw = str(value).strip().replace(",", "")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
    return number if math.isfinite(number) else None


def positive(value: Any) -> float | None:
    number = fnum(value)
    return number if number is not None and number > 0 else None


def to_datetime(value: Any) -> datetime | None:
    """Parse a datetime/date/ISO-like string/epoch milliseconds into +08:00."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date_type):
        moment = datetime(value.year, value.month, value.day, tzinfo=CN_TZ)
    elif isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10**11:
            stamp /= 1000.0
        try:
            moment = datetime.fromtimestamp(stamp, tz=CN_TZ)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        raw = str(value).strip()
        if not raw:
            return None
        candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            moment = None  # type: ignore[assignment]
            for fmt in _DATETIME_FORMATS:
                try:
                    moment = datetime.strptime(raw, fmt)
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
    moment = to_datetime(value)
    return None if moment is None else moment.isoformat(timespec="seconds")


def parse_date(value: Any) -> str | None:
    moment = to_datetime(value)
    return None if moment is None else moment.date().isoformat()


def combine_date_time(date_value: Any, time_value: Any) -> str | None:
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
        raw = str(time_value).strip()
        try:
            moment = time_type.fromisoformat(raw)
        except ValueError:
            for fmt in _TIME_FORMATS:
                try:
                    moment = datetime.strptime(raw, fmt).time()
                    break
                except ValueError:
                    continue
        if moment is None:
            return None
    return datetime.combine(day.date(), moment, tzinfo=CN_TZ).isoformat(timespec="seconds")


def _stamp(value: str | None) -> float:
    moment = to_datetime(value)
    return moment.timestamp() if moment is not None else float("-inf")


def _dedupe(entries: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    result: list[dict[str, Any]] = []
    for item in entries:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_stock_news(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        title, _ = clean_text(row.get("新闻标题"))
        summary, truncated = clean_text(row.get("新闻内容"), config.NEWS_SUMMARY_MAX)
        if title is None and summary is None:
            continue
        item: dict[str, Any] = {
            "time": parse_time(row.get("发布时间")),
            "title": title or "",
            "summary": summary or "",
            "url": text(row.get("新闻链接")),
        }
        if truncated:
            item["truncated"] = True
        entries.append(item)
    entries = _dedupe(entries, lambda item: (item.get("title"), item.get("time")))
    entries.sort(key=lambda item: _stamp(item.get("time")), reverse=True)
    return entries


def normalize_flash_cls(rows: Iterable[dict[str, Any]], channel: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        level = text(row.get("等级"))
        if channel == "important" and level not in {"A", "B"}:
            continue
        title, _ = clean_text(row.get("标题"))
        content, truncated = clean_text(row.get("内容"), config.NEWS_BODY_MAX)
        if title is None and content is None:
            continue
        item: dict[str, Any] = {
            "time": combine_date_time(row.get("发布日期"), row.get("发布时间")),
            "title": title or "",
            "content": content or "",
            "url": None,
        }
        if truncated:
            item["truncated"] = True
        entries.append(item)
    return entries


def normalize_flash_em(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        title, _ = clean_text(row.get("标题"))
        content, truncated = clean_text(row.get("摘要"), config.NEWS_BODY_MAX)
        if title is None and content is None:
            continue
        item: dict[str, Any] = {
            "time": parse_time(row.get("发布时间")),
            "title": title or "",
            "content": content or "",
            "url": clean_link(row.get("链接")),
        }
        if truncated:
            item["truncated"] = True
        entries.append(item)
    return entries


def clean_link(value: Any) -> str | None:
    raw = text(value)
    if raw is None or not raw.lower().startswith(("http://", "https://")):
        return None
    return raw


def merge_flash(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = _dedupe(
        entries,
        lambda item: str(item.get("title") or "").strip().casefold()
        or f"{item.get('title')}|{item.get('content')}",
    )
    merged.sort(key=lambda item: _stamp(item.get("time")), reverse=True)
    return merged


def normalize_irm(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        question, question_cut = clean_text(row.get("问题"), config.NEWS_QUESTION_MAX)
        answer_value = row.get("回答内容")
        if is_missing(answer_value):
            answer_value = row.get("回答")
        answer, answer_cut = clean_text(answer_value, config.NEWS_ANSWER_MAX)
        if question is None and answer is None:
            continue
        answered = None
        if answer is not None:
            update_value = row.get("更新时间")
            if not is_missing(update_value):
                answered = parse_time(update_value)
        item: dict[str, Any] = {
            "time": parse_time(row.get("提问时间")),
            "title": question or "",
            "content": answer,
            "answered_time": answered,
        }
        if question_cut or answer_cut:
            item["truncated"] = True
        entries.append(item)
    entries.sort(key=lambda item: _stamp(item.get("time")), reverse=True)
    return entries


def normalize_calendar(rows: Iterable[dict[str, Any]], requested: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        day_value = row.get("日期")
        if is_missing(day_value):
            day_value = requested
        moment = combine_date_time(day_value, row.get("时间"))
        event, _ = clean_text(row.get("事件"))
        region, _ = clean_text(row.get("地区"))
        if region is None:
            region, _ = clean_text(row.get("国家"))
        items.append(
            {
                "time": moment,
                "title": event or "",
                "region": region,
                "actual": row.get("公布") if not is_missing(row.get("公布")) else None,
                "forecast": row.get("预期") if not is_missing(row.get("预期")) else None,
                "previous": row.get("前值") if not is_missing(row.get("前值")) else None,
                "importance": row.get("重要性") if not is_missing(row.get("重要性")) else None,
                "summary": None,
                "url": None,
            }
        )
    items.sort(key=lambda item: _stamp(item.get("time")))
    return items


def suspension_code(value: Any) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    digits = raw[:-2] if raw.endswith(".0") and raw[:-2].isdigit() else raw
    if not digits.isdigit() or len(digits) > 6:
        return None
    digits = digits.zfill(6)
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("0", "3")):
        return f"{digits}.SZ"
    if digits.startswith(("4", "8", "9")):
        return f"{digits}.BJ"
    return None


def normalize_suspensions(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        code = suspension_code(row.get("代码"))
        if code is None:
            dropped += 1
            continue
        name, _ = clean_text(row.get("名称"), config.SUSPENSION_NAME_MAX)
        reason, truncated = clean_text(row.get("停牌原因"), config.SUSPENSION_REASON_MAX)
        start = parse_date(row.get("停牌时间"))
        item: dict[str, Any] = {
            "time": None if start is None else f"{start}T00:00:00+08:00",
            "title": name or "",
            "code": code,
            "reason": reason,
            "summary": reason,
            "suspend_to": parse_date(row.get("停牌截止时间")),
            "resume_at": parse_date(row.get("预计复牌时间")),
            "url": None,
        }
        if truncated:
            item["truncated"] = True
        items.append(item)
    return items, dropped


def bond_code(value: Any) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    digits = raw[:-2] if raw.endswith(".0") and raw[:-2].isdigit() else raw
    return digits if digits.isdigit() and len(digits) == 6 else None


def conversion_value(conversion_price: Any, underlying_price: Any) -> float | None:
    """100 / conversion price * underlying price; None when an input is unusable."""
    price = fnum(conversion_price)
    underlying = fnum(underlying_price)
    if price is None or underlying is None or price <= 0:
        return None
    return 100.0 / price * underlying


def premium_pct(bond_price: Any, value: Any) -> float | None:
    """(bond price / conversion value - 1) * 100; None when an input is unusable."""
    price = fnum(bond_price)
    conversion = fnum(value)
    if price is None or conversion is None or price <= 0 or conversion <= 0:
        return None
    return (price / conversion - 1.0) * 100.0
