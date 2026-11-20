"""Deterministic data services behind the three MCP tools."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from cn_extra_mcp import announcement, sources
from cn_extra_mcp.envelope import envelope
from cn_extra_mcp.symbols import InvalidSymbol, Symbol, normalize_symbol

logger = logging.getLogger(__name__)

PERIODS = ("1", "5", "15", "30", "60")
UNITS = {"volume": "shares", "amount": "CNY"}
MINUTE_SOURCE = "akshare.sina.stock_zh_a_minute"
QUOTE_SOURCE = "qt.gtimg.cn"
ANNOUNCEMENT_SOURCE = "akshare.cninfo.stock_zh_a_disclosure_report_cninfo"
ANNOUNCEMENT_PDF_SOURCE = "cninfo.static.announcement_pdf"
ANNOUNCEMENT_MARKET = "沪深京"
ANNOUNCEMENT_CATEGORIES = (
    "年报",
    "半年报",
    "一季报",
    "三季报",
    "业绩预告",
    "权益分派",
    "董事会",
    "监事会",
    "股东大会",
    "日常经营",
    "公司治理",
    "中介报告",
    "首发",
    "增发",
    "股权激励",
    "配股",
    "解禁",
    "公司债",
    "可转债",
    "其他融资",
    "股权变动",
    "补充更正",
    "澄清致歉",
    "风险提示",
    "特别处理和退市",
    "退市整理期",
)
LEGACY_BJ_WARNING = "legacy_bj_code"
LEGACY_BJ_MESSAGE = "北交所代码已迁移为 92xxxx，旧代码数据可能停更，请改用新代码"
ANNOUNCEMENT_DEFAULT_DAYS = 90
ANNOUNCEMENT_DEFAULT_LIMIT = 20
ANNOUNCEMENT_MAX_LIMIT = 100
_CN_TZ = timezone(timedelta(hours=8))
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFINITIONS: dict[str, str] = {
    "open": "open of the first bar of the day",
    "close": "close of the last bar of the day",
    "high": "max(high) over all bars of the day",
    "low": "min(low) over all bars of the day",
    "high_time": "HH:MM of the first bar that printed the day's high",
    "low_time": "HH:MM of the first bar that printed the day's low",
    "vwap": "sum(amount) / sum(volume), rounded to 4 decimals; amount in CNY and volume in shares",
    "close_vs_vwap_pct": "(vwap - close) / vwap * 100, rounded to 2 decimals; a positive value means close is below VWAP",
    "first_30min_volume_share_pct": "sum(volume of bars stamped 09:31..10:00 inclusive) / total volume * 100, rounded to 1 decimal",
    "volume_share_from_high_bar_pct": "sum(volume from the high_time bar inclusive through the close) / total volume * 100, rounded to 1 decimal",
    "complete": "true when last_bar_time >= 15:00",
    "bars": "number of one-minute bars with data on the requested date",
}


def _error(source: str, code: str, message: str) -> dict[str, Any]:
    return envelope(source=source, status="error", error_code=code, error_message=message)


def _warning_fields(symbols: Iterable[Symbol]) -> dict[str, Any]:
    """Envelope fields for pre-migration Beijing codes; empty for SH/SZ and 92xxxx."""
    if any(symbol.legacy_bj for symbol in symbols):
        return {"warnings": [LEGACY_BJ_WARNING], "warning_message": LEGACY_BJ_MESSAGE}
    return {}


def _parse_date(value: str, field: str) -> date_type:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return datetime.strptime(value, "%Y-%m-%d").date()


def _prepare_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["ts", "open", "high", "low", "close", "volume", "amount"]
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=columns)
    if "day" not in frame.columns:
        raise ValueError("minute source returned no 'day' column")

    out = frame.copy()
    out["ts"] = pd.to_datetime(out["day"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        out[column] = pd.to_numeric(out.get(column), errors="coerce")
    out = out.dropna(subset=columns)
    return out.sort_values("ts").reset_index(drop=True)


def _available_range(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    days = frame["ts"].dt.strftime("%Y-%m-%d")
    return [str(days.min()), str(days.max())]


def _number(value: Any) -> float:
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValueError("non-finite number")
    return number


def _shares(value: Any) -> int:
    return int(round(_number(value)))


def _iso_bar_time(stamp: pd.Timestamp) -> str:
    return stamp.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _bar(row: pd.Series) -> dict[str, Any]:
    return {
        "time": _iso_bar_time(row["ts"]),
        "open": _number(row["open"]),
        "high": _number(row["high"]),
        "low": _number(row["low"]),
        "close": _number(row["close"]),
        "volume": _shares(row["volume"]),
        "amount": _number(row["amount"]),
    }


def _minute_data(
    symbol: Any,
    period: str,
    frame: pd.DataFrame,
    available: list[str],
    requested: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    dates = sorted({str(x) for x in frame["ts"].dt.strftime("%Y-%m-%d")}) if not frame.empty else []
    data: dict[str, Any] = {
        "code": symbol.canonical,
        "period": period,
        "count": int(len(frame)),
        "dates": dates,
        "available_range": available,
        "units": UNITS,
        "bars": [_bar(row) for _, row in frame.iterrows()],
    }
    if requested is not None:
        data["requested_range"] = requested
    return data


def cn_get_minute_bars(
    code: str,
    period: str = "1",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(code)
    except InvalidSymbol as exc:
        return _error(MINUTE_SOURCE, "invalid_symbol", str(exc))

    if period not in PERIODS:
        return _error(MINUTE_SOURCE, "invalid_argument", f"period must be one of {list(PERIODS)}")

    try:
        start = _parse_date(start_date, "start_date") if start_date is not None else None
        end = _parse_date(end_date, "end_date") if end_date is not None else None
    except ValueError as exc:
        return _error(MINUTE_SOURCE, "invalid_argument", str(exc))
    if start is not None and end is not None and start > end:
        return _error(MINUTE_SOURCE, "invalid_argument", "start_date must not be after end_date")

    try:
        frame = _prepare_frame(sources.fetch_minute_frame(symbol.sina, period))
    except Exception as exc:  # external source boundary
        logger.error("minute fetch failed for %s: %s", symbol.canonical, type(exc).__name__)
        return _error(MINUTE_SOURCE, "upstream_error", f"minute source failed ({type(exc).__name__})")

    available = _available_range(frame)
    warning_fields = _warning_fields([symbol])
    if frame.empty:
        return envelope(
            source=MINUTE_SOURCE,
            status="empty",
            data=_minute_data(symbol, period, frame, available),
            **warning_fields,
        )

    days = frame["ts"].dt.date
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= days >= start
    if end is not None:
        mask &= days <= end
    selected = frame[mask]

    requested = {
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
    }
    status = "empty" if selected.empty else "ready"
    return envelope(
        source=MINUTE_SOURCE,
        status=status,
        data=_minute_data(symbol, period, selected, available, requested),
        **warning_fields,
    )


def _parse_tencent_line(line: str) -> dict[str, Any] | None:
    match = re.match(r'^v_([a-z]{2}\d{6})="(.*)";?$', line.strip())
    if match is None:
        return None
    fields = match.group(2).split("~")
    if len(fields) < 38:
        return None

    def num(index: int) -> float | None:
        text = fields[index].strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def limit(index: int) -> float | None:
        # Tencent uses -1 (or an empty field) when no limit price is published.
        value = num(index) if len(fields) > index else None
        return value if value is not None and value > 0 else None

    raw_time = fields[30].strip()
    time_text: str | None = None
    if len(raw_time) == 14 and raw_time.isdigit():
        try:
            time_text = datetime.strptime(raw_time, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            time_text = raw_time
    elif raw_time:
        time_text = raw_time

    return {
        "name": fields[1].strip(),
        "digits": fields[2].strip(),
        "price": num(3),
        "prev_close": num(4),
        "open": num(5),
        "high": num(33),
        "low": num(34),
        "change_pct": num(32),
        "volume_lots": num(6),
        "amount_wan": num(37),
        "time": time_text,
        "limit_up": limit(47),
        "limit_down": limit(48),
    }


def cn_get_quote_snapshot(codes: Iterable[str]) -> dict[str, Any]:
    if isinstance(codes, str) or not isinstance(codes, Iterable):
        return _error(QUOTE_SOURCE, "invalid_argument", "codes must be a list of stock codes")
    items = list(codes)
    if not items:
        return _error(QUOTE_SOURCE, "invalid_argument", "codes must contain at least one stock code")
    if len(items) > 20:
        return _error(QUOTE_SOURCE, "invalid_argument", "at most 20 codes per request")

    symbols = []
    seen: set[str] = set()
    for item in items:
        try:
            symbol = normalize_symbol(item)
        except InvalidSymbol as exc:
            return _error(QUOTE_SOURCE, "invalid_symbol", str(exc))
        if symbol.canonical not in seen:
            seen.add(symbol.canonical)
            symbols.append(symbol)

    try:
        text = sources.fetch_tencent_text([symbol.sina for symbol in symbols])
    except Exception as exc:  # external source boundary
        logger.error("quote fetch failed: %s", type(exc).__name__)
        return _error(QUOTE_SOURCE, "upstream_error", f"quote source failed ({type(exc).__name__})")

    parsed: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        row = _parse_tencent_line(line)
        if row is not None:
            parsed[row["digits"]] = row

    quotes: list[dict[str, Any]] = []
    for symbol in symbols:
        row = parsed.get(symbol.digits)
        if row is None:
            logger.warning("quote missing for %s", symbol.canonical)
            continue
        quotes.append(
            {
                "code": symbol.canonical,
                "name": row["name"],
                "price": row["price"],
                "prev_close": row["prev_close"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "change_pct": row["change_pct"],
                "volume_lots": row["volume_lots"],
                "amount_wan": row["amount_wan"],
                "time": row["time"],
                "limit_up": row["limit_up"],
                "limit_down": row["limit_down"],
            }
        )

    if not quotes:
        return _error(QUOTE_SOURCE, "upstream_error", "quote source returned no usable rows")
    return envelope(
        source=QUOTE_SOURCE,
        status="ready",
        data=quotes,
        **_warning_fields(symbols),
    )


def cn_intraday_summary(code: str, date: str) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(code)
    except InvalidSymbol as exc:
        return _error(MINUTE_SOURCE, "invalid_symbol", str(exc))

    try:
        day = _parse_date(date, "date")
    except ValueError as exc:
        return _error(MINUTE_SOURCE, "invalid_argument", str(exc))

    try:
        frame = _prepare_frame(sources.fetch_minute_frame(symbol.sina, "1"))
    except Exception as exc:  # external source boundary
        logger.error("minute fetch failed for %s: %s", symbol.canonical, type(exc).__name__)
        return _error(MINUTE_SOURCE, "upstream_error", f"minute source failed ({type(exc).__name__})")

    available = _available_range(frame)
    day_text = day.isoformat()
    warning_fields = _warning_fields([symbol])
    bars = frame[frame["ts"].dt.strftime("%Y-%m-%d") == day_text] if not frame.empty else frame
    if bars.empty:
        return envelope(
            source=MINUTE_SOURCE,
            status="empty",
            data={
                "code": symbol.canonical,
                "date": day_text,
                "bars": 0,
                "available_range": available,
                "definitions": DEFINITIONS,
            },
            **warning_fields,
        )

    times = [stamp.strftime("%H:%M") for stamp in bars["ts"]]
    high = max(_number(value) for value in bars["high"])
    low = min(_number(value) for value in bars["low"])
    high_index = next(index for index, value in enumerate(bars["high"]) if _number(value) == high)
    low_index = next(index for index, value in enumerate(bars["low"]) if _number(value) == low)

    volume_total = _shares(bars["volume"].sum())
    amount_total = round(sum(_number(value) for value in bars["amount"]), 4)
    close = _number(bars["close"].iloc[-1])

    vwap: float | None = None
    close_vs_vwap: float | None = None
    first_share: float | None = None
    from_high_share: float | None = None
    if volume_total > 0:
        raw_vwap = amount_total / volume_total
        vwap = round(raw_vwap, 4)
        close_vs_vwap = round((raw_vwap - close) / raw_vwap * 100.0, 2)
        first_30 = sum(
            _number(volume)
            for stamp, volume in zip(times, bars["volume"])
            if "09:31" <= stamp <= "10:00"
        )
        from_high = sum(_number(volume) for volume in bars["volume"].iloc[high_index:])
        first_share = round(first_30 / volume_total * 100.0, 1)
        from_high_share = round(from_high / volume_total * 100.0, 1)

    data = {
        "code": symbol.canonical,
        "date": day_text,
        "bars": int(len(bars)),
        "first_bar_time": times[0],
        "last_bar_time": times[-1],
        "complete": times[-1] >= "15:00",
        "open": _number(bars["open"].iloc[0]),
        "high": high,
        "low": low,
        "close": close,
        "high_time": times[high_index],
        "low_time": times[low_index],
        "volume_total_shares": volume_total,
        "amount_total_cny": amount_total,
        "vwap": vwap,
        "close_vs_vwap_pct": close_vs_vwap,
        "first_30min_volume_share_pct": first_share,
        "volume_share_from_high_bar_pct": from_high_share,
        "available_range": available,
        "units": UNITS,
        "definitions": DEFINITIONS,
    }
    return envelope(source=MINUTE_SOURCE, status="ready", data=data, **warning_fields)


def _today_cn() -> date_type:
    return datetime.now(_CN_TZ).date()


def _announcement_rows(
    frame: pd.DataFrame | None,
    start: date_type,
    end: date_type,
) -> tuple[str | None, list[dict[str, Any]]]:
    columns = ["代码", "简称", "公告标题", "公告时间", "公告链接"]
    if frame is None or len(frame) == 0:
        return None, []
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"announcement source missing columns: {missing}")

    name: str | None = None
    for value in frame["简称"]:
        if not pd.isna(value) and str(value).strip():
            name = str(value).strip()
            break

    stamps = [
        pd.to_datetime(value, errors="coerce") if not pd.isna(value) else pd.NaT
        for value in frame["公告时间"]
    ]
    announcements: list[dict[str, Any]] = []
    for stamp, title, url in zip(stamps, frame["公告标题"], frame["公告链接"]):
        if pd.isna(stamp) or pd.isna(title) or pd.isna(url):
            continue
        day = stamp.date()
        if day < start or day > end:
            continue
        announcements.append(
            {
                "date": day.isoformat(),
                "title": str(title).strip(),
                "url": str(url).strip(),
            }
        )
    announcements.sort(key=lambda item: item["date"], reverse=True)
    return name, announcements


def cn_get_announcements(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    limit: int = ANNOUNCEMENT_DEFAULT_LIMIT,
) -> dict[str, Any]:
    try:
        symbol = normalize_symbol(code)
    except InvalidSymbol as exc:
        return _error(ANNOUNCEMENT_SOURCE, "invalid_symbol", str(exc))

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= ANNOUNCEMENT_MAX_LIMIT
    ):
        return _error(
            ANNOUNCEMENT_SOURCE,
            "invalid_argument",
            f"limit must be an integer between 1 and {ANNOUNCEMENT_MAX_LIMIT}",
        )

    category_text = "" if category is None else category
    if not isinstance(category_text, str) or (
        category_text and category_text not in ANNOUNCEMENT_CATEGORIES
    ):
        return _error(
            ANNOUNCEMENT_SOURCE,
            "invalid_argument",
            f"category must be empty or one of {list(ANNOUNCEMENT_CATEGORIES)}",
        )

    try:
        start = _parse_date(start_date, "start_date") if start_date is not None else None
        end = _parse_date(end_date, "end_date") if end_date is not None else None
    except ValueError as exc:
        return _error(ANNOUNCEMENT_SOURCE, "invalid_argument", str(exc))
    if end is None:
        end = _today_cn()
    if start is None:
        start = end - timedelta(days=ANNOUNCEMENT_DEFAULT_DAYS)
    if start > end:
        return _error(ANNOUNCEMENT_SOURCE, "invalid_argument", "start_date must not be after end_date")

    try:
        frame = sources.fetch_announcements_frame(
            symbol=symbol.digits,
            market=ANNOUNCEMENT_MARKET,
            category=category_text,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        name, announcements = _announcement_rows(frame, start, end)
    except Exception as exc:  # external source boundary
        logger.error("announcement fetch failed for %s: %s", symbol.canonical, type(exc).__name__)
        return _error(
            ANNOUNCEMENT_SOURCE,
            "upstream_error",
            f"announcement source failed ({type(exc).__name__})",
        )

    total = len(announcements)
    selected = announcements[:limit]
    data: dict[str, Any] = {
        "code": symbol.canonical,
        "name": name,
        "count": total,
        "range": [start.isoformat(), end.isoformat()],
        "truncated": total > limit,
        "untrusted_text": True,
        "announcements": selected,
    }
    return envelope(
        source=ANNOUNCEMENT_SOURCE,
        status="ready" if selected else "empty",
        data=data,
        **_warning_fields([symbol]),
    )


def _page_argument(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if value < 1:
        raise ValueError(f"{field} must be >= 1")
    return value


def cn_read_announcement(
    url: str,
    start_page: int = 1,
    end_page: int | None = None,
    max_chars: int = announcement.DEFAULT_MAX_CHARS,
    layout: bool = True,
) -> dict[str, Any]:
    try:
        pdf_url = announcement.resolve_pdf_url(url)
    except announcement.InvalidAnnouncementUrl as exc:
        return _error(ANNOUNCEMENT_PDF_SOURCE, "invalid_url", str(exc))

    try:
        start = _page_argument(start_page, "start_page")
        end = None if end_page is None else _page_argument(end_page, "end_page")
        if end is not None and end < start:
            raise ValueError("end_page must not be before start_page")
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or not announcement.MIN_MAX_CHARS <= max_chars <= announcement.MAX_MAX_CHARS
        ):
            raise ValueError(
                "max_chars must be an integer between "
                f"{announcement.MIN_MAX_CHARS} and {announcement.MAX_MAX_CHARS}"
            )
        if not isinstance(layout, bool):
            raise ValueError("layout must be a boolean")
    except ValueError as exc:
        return _error(ANNOUNCEMENT_PDF_SOURCE, "invalid_argument", str(exc))

    executable = announcement.pdftotext_path()
    if executable is None:
        return _error(
            ANNOUNCEMENT_PDF_SOURCE,
            "pdftotext_not_found",
            "pdftotext is not installed; 请安装 poppler（brew install poppler）",
        )

    try:
        body, _content_type = sources.fetch_pdf_bytes(pdf_url)
    except sources.PdfDownloadError as exc:
        return _error(ANNOUNCEMENT_PDF_SOURCE, exc.code, exc.message)
    except Exception as exc:  # defensive boundary: any transport bug becomes an envelope
        logger.error("announcement download failed: %s", type(exc).__name__)
        return _error(
            ANNOUNCEMENT_PDF_SOURCE, "download_failed", f"download failed ({type(exc).__name__})"
        )
    if not body.startswith(b"%PDF-"):
        return _error(ANNOUNCEMENT_PDF_SOURCE, "not_pdf", "response body does not start with %PDF-")
    if len(body) > sources.MAX_PDF_BYTES:
        return _error(
            ANNOUNCEMENT_PDF_SOURCE,
            "too_large",
            f"PDF exceeds the {sources.MAX_PDF_BYTES} byte limit",
        )

    try:
        extracted = announcement.extract_pdf_text(
            body,
            executable=executable,
            start_page=start,
            end_page=end,
            layout=layout,
        )
    except announcement.PdfExtractionError as exc:
        return _error(ANNOUNCEMENT_PDF_SOURCE, exc.code, exc.message)

    text = extracted.text
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    data: dict[str, Any] = {
        "url": url,
        "pdf_url": pdf_url,
        "pages_total": extracted.pages_total,
        "pages_returned": extracted.pages_returned,
        "chars": len(text),
        "truncated": truncated,
        "text": text,
        "untrusted_text": True,
    }
    return envelope(source=ANNOUNCEMENT_PDF_SOURCE, status="ready", data=data)
