"""Upstream adapters: Tencent daily K-line, SSE/SZSE security lists, gateway pool.

Only the hosts in :mod:`cn_daily_store.http` are reachable.  Nothing here reads
or writes credentials, and the gateway is called on loopback only.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from .db import meta_set, now_iso
from .http import FetchError, HttpClient

TENCENT_HOST = "https://web.ifzq.gtimg.cn"
TENCENT_NEW_KLINE = "/appstock/app/newfqkline/get"
TENCENT_KLINE = "/appstock/app/fqkline/get"
SSE_URL = "http://query.sse.com.cn/sseQuery/commonQuery.do"
SZSE_URL = "http://www.szse.cn/api/report/ShowReport/data"
SSE_HEADERS = {"Referer": "http://www.sse.com.cn/"}
SZSE_HEADERS = {"Referer": "https://www.szse.cn/"}
GATEWAY_URL = "http://127.0.0.1:8868/v1/call"

_SSE_PAGE_SIZE = 2000
_NAME_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class RawBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None


@dataclass(frozen=True)
class SecurityRow:
    code: str
    name: str
    board: str
    list_date: str | None
    delist_date: str | None


def tencent_symbol(code: str) -> str:
    digits, _, suffix = code.partition(".")
    if suffix == "SH":
        return f"sh{digits}"
    if suffix == "SZ":
        return f"sz{digits}"
    raise ValueError(f"unsupported code: {code}")


def board_for_digits(digits: str) -> str | None:
    if digits.startswith(("688", "689")):
        return "star"
    if digits.startswith(("300", "301")):
        return "chinext"
    if digits.startswith("6"):
        return "sh_main"
    if digits.startswith(("000", "001", "002", "003")):
        return "sz_main"
    return None


def split_code(code: str) -> tuple[str, str]:
    digits, _, suffix = code.partition(".")
    return digits, suffix


def _float(value: Any) -> float | None:
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    return None if number is None else int(round(number))


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


class TencentKlineSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def _fetch_rows(self, symbol: str, *, path: str, count: int, start: str, end: str, adjust: str) -> list[list[Any]]:
        param = f"{symbol},day,{start},{end},{count},{adjust}"
        url = f"{TENCENT_HOST}{path}?param={urllib.parse.quote(param, safe=',:-')}"
        payload = self.client.get_json(url)
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise FetchError("upstream_error", f"kline source error for {symbol}")
        data = payload.get("data")
        node = data.get(symbol) if isinstance(data, dict) else None
        if not isinstance(node, dict):
            raise FetchError("kline_missing", f"kline source has no data for {symbol}")
        key = "day" if adjust in ("", "none") else f"{adjust}day"
        rows = node.get(key)
        if not rows and adjust == "qfq":
            # Some STAR names have no corporate action yet: Tencent returns the
            # unadjusted series under ``day`` even when qfq was requested.
            rows = node.get("day")
        if rows is None and key == "day":
            rows = node.get("qfqday")
        if not isinstance(rows, list):
            raise FetchError("kline_missing", f"kline source has no {key} rows for {symbol}")
        return rows

    def fetch_stock(self, code: str, *, adjust: str = "none", count: int = 2000) -> list[RawBar]:
        """Fetch unadjusted (``none``) or forward-adjusted (``qfq``) daily rows."""
        return self.fetch_stock_range(code, adjust=adjust, count=count)

    def fetch_stock_range(
        self, code: str, *, start: str = "", end: str = "", count: int = 640, adjust: str = "none"
    ) -> list[RawBar]:
        symbol = tencent_symbol(code)
        rows = self._fetch_rows(
            symbol, path=TENCENT_NEW_KLINE, count=count, start=start, end=end, adjust=adjust
        )
        # Tencent publishes main-board/ChiNext volume in lots (手) but STAR
        # (688/689) volume in shares; normalise everything to shares.
        volume_multiplier = 1 if symbol.startswith(("sh688", "sh689")) else 100
        bars: list[RawBar] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            day = _parse_day(row[0])
            open_ = _float(row[1])
            close = _float(row[2])
            high = _float(row[3])
            low = _float(row[4])
            volume = _float(row[5])
            if day is None or None in (open_, close, high, low, volume):
                continue
            if open_ <= 0 or close <= 0 or high <= 0 or low <= 0:
                continue
            amount = _float(row[8]) if len(row) > 8 else None
            bars.append(
                RawBar(
                    date=day,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(round(volume * volume_multiplier)),
                    amount=None if amount is None else round(amount * 10000.0, 2),
                )
            )
        bars.sort(key=lambda item: item.date)
        return bars

    def fetch_calendar_year(self, year: int, today: date) -> list[date]:
        start = date(year, 1, 1)
        end = min(date(year, 12, 31), today)
        if start > end:
            return []
        rows = self._fetch_rows(
            "sh000001", path=TENCENT_KLINE, count=400,
            start=start.isoformat(), end=end.isoformat(), adjust="",
        )
        days: list[date] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or not row:
                continue
            day = _parse_day(row[0])
            if day is not None:
                days.append(day)
        return days

    def fetch_calendar_latest(self, days: int = 30) -> list[date]:
        rows = self._fetch_rows(
            "sh000001", path=TENCENT_KLINE, count=days, start="", end="", adjust=""
        )
        out: list[date] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or not row:
                continue
            day = _parse_day(row[0])
            if day is not None:
                out.append(day)
        return out


def _clean_name(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(_NAME_TAG.sub("", str(raw)))
    return _SPACE.sub(" ", text).strip()


def _sse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_sse_rows(rows: Iterable[dict[str, Any]]) -> list[SecurityRow]:
    out: list[SecurityRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        digits = str(row.get("A_STOCK_CODE") or "").strip()
        board = board_for_digits(digits)
        if board is None:
            continue
        name = _clean_name(row.get("COMPANY_ABBR")) or _clean_name(row.get("SEC_NAME_CN"))
        if not name:
            continue
        out.append(
            SecurityRow(
                code=f"{digits}.SH",
                name=name,
                board=board,
                list_date=_sse_date(row.get("LIST_DATE")),
                delist_date=_sse_date(row.get("DELIST_DATE")),
            )
        )
    return out


def parse_szse_rows(rows: Iterable[dict[str, Any]]) -> list[SecurityRow]:
    out: list[SecurityRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        digits = str(row.get("agdm") or "").strip()
        board = board_for_digits(digits)
        if board is None:
            continue
        name = _clean_name(row.get("agjc"))
        if not name:
            continue
        raw_date = str(row.get("agssrq") or "").strip()
        try:
            list_date = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            list_date = None
        out.append(
            SecurityRow(
                code=f"{digits}.SZ",
                name=name,
                board=board,
                list_date=list_date,
                delist_date=None,
            )
        )
    return out


class ExchangeListSource:
    """SSE + SZSE public stock lists (current names, listing and delisting dates)."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch_sse(self) -> list[SecurityRow]:
        rows: list[SecurityRow] = []
        page = 1
        page_count = 1
        while page <= page_count:
            query = urllib.parse.urlencode(
                {
                    "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
                    "isPagination": "true",
                    "pageHelp.cacheSize": "1",
                    "pageHelp.beginPage": str(page),
                    "pageHelp.pageSize": str(_SSE_PAGE_SIZE),
                    "pageHelp.pageNo": str(page),
                }
            )
            payload = self.client.get_json(f"{SSE_URL}?{query}", headers=SSE_HEADERS)
            page_help = payload.get("pageHelp") if isinstance(payload, dict) else None
            if not isinstance(page_help, dict):
                raise FetchError("invalid_json", "SSE list has no pageHelp")
            rows.extend(parse_sse_rows(page_help.get("data") or []))
            page_count = max(1, int(page_help.get("pageCount") or 1))
            page += 1
        return rows

    def fetch_szse(self) -> list[SecurityRow]:
        rows: list[SecurityRow] = []
        page = 1
        page_count = 1
        while page <= page_count:
            query = urllib.parse.urlencode(
                {"SHOWTYPE": "JSON", "CATALOGID": "1110", "TABKEY": "tab1", "PAGENO": str(page)}
            )
            payload = self.client.get_json(f"{SZSE_URL}?{query}", headers=SZSE_HEADERS)
            if not isinstance(payload, list) or not payload:
                raise FetchError("invalid_json", "SZSE list has no tab")
            first = payload[0] if isinstance(payload[0], dict) else {}
            meta = first.get("metadata") or {}
            rows.extend(parse_szse_rows(first.get("data") or []))
            page_count = max(1, int(meta.get("pagecount") or 1))
            page += 1
        return rows

    def refresh(self, conn: sqlite3.Connection) -> dict[str, int]:
        rows = self.fetch_sse() + self.fetch_szse()
        stamp = now_iso()
        conn.executemany(
            "INSERT INTO securities(code, name, board, list_date, delist_date, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, board=excluded.board, "
            "list_date=excluded.list_date, delist_date=excluded.delist_date, "
            "updated_at=excluded.updated_at",
            [(row.code, row.name, row.board, row.list_date, row.delist_date, stamp) for row in rows],
        )
        conn.executemany(
            "INSERT INTO names(code, start_date, name) VALUES(?, ?, ?) "
            "ON CONFLICT(code, start_date) DO UPDATE SET name=excluded.name",
            [
                (row.code, row.list_date or "1990-01-01", row.name)
                for row in rows
                if row.name
            ],
        )
        meta_set(conn, "securities_source", "sse; szse (current abbreviation only)")
        meta_set(conn, "securities_refreshed_at", stamp)
        conn.commit()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.board] = counts.get(row.board, 0) + 1
        return counts


class GatewayClient:
    """Read-only loopback client for ``http://127.0.0.1:8868/v1/call``."""

    def __init__(self, url: str = GATEWAY_URL, *, timeout: float = 40.0) -> None:
        self.url = url
        self.timeout = timeout
        self.calls = 0

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"tool": tool, "args": args}).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}
        )
        self.calls += 1
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise FetchError("invalid_json", "gateway returned a non-object")
        return payload

    def limit_pool(self, day: date) -> tuple[str, list[str], int]:
        payload = self.call(
            "market_limit_pool",
            {"kind": "zt", "date": day.isoformat(), "limit": 200},
        )
        status = str(payload.get("status") or "unavailable")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        codes: list[str] = []
        for row in data.get("rows") or []:
            if isinstance(row, dict) and row.get("code"):
                codes.append(str(row["code"]))
        return status, codes, int(data.get("count") or 0)


SINA_FACTOR_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/qfq.js"
SINA_FACTOR_HEADERS = {"Referer": "https://finance.sina.com.cn"}


class SinaFactorSource:
    """Sina forward-adjustment factor history (a fallback for long qfq series).

    Tencent caps a single qfq response at 640 rows, which is shorter than the
    2019-to-date range.  Sina publishes the full qfq divisor history in one small
    JS file: ``qfq = raw / f``, so the stored factor is ``1 / f``.
    """

    def __init__(self, client: HttpClient) -> None:
        self.client = client
        self.errors = 0

    def fetch(self, code: str) -> list[tuple[date, float]]:
        symbol = tencent_symbol(code)
        url = SINA_FACTOR_URL.format(symbol=symbol)
        try:
            text = self.client.get_text(url, headers=SINA_FACTOR_HEADERS)
        except FetchError:
            self.errors += 1
            return []
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(text[start : end + 1])
        except (TypeError, ValueError):
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        points: list[tuple[date, float]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            day = _parse_day(item.get("d"))
            factor = _float(item.get("f"))
            if day is None or factor is None or factor <= 0:
                continue
            points.append((day, round(1.0 / factor, 8)))
        points.sort(key=lambda pair: pair[0])
        return points
