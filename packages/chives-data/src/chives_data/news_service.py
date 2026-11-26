"""Capability layer for news, announcements and convertible bonds (T143)."""

from __future__ import annotations

from datetime import date, datetime, time as time_type, timedelta
from typing import Any, Callable

from . import config
from . import announcement as pdfmod
from .codes import Code, InvalidCode, normalize_code
from .envelope import basis, envelope, missing, now_iso, unavailable
from .news_parse import (
    bond_code,
    clean_text,
    conversion_value,
    fnum,
    merge_flash,
    normalize_calendar,
    normalize_flash_cls,
    normalize_flash_em,
    normalize_irm,
    normalize_stock_news,
    normalize_suspensions,
    parse_date,
    positive,
    premium_pct,
    text,
)
from .news_sources import ANNOUNCEMENT_CATEGORIES, ANNOUNCEMENT_DEFAULT_DAYS, ANNOUNCEMENT_DEFAULT_LIMIT
from .transport import UpstreamError

NEWS_KINDS = ("stock", "flash", "irm", "calendar", "suspensions")
CHANNELS = ("all", "important")
CB_KINDS = ("list", "quote")
DATE_FORMAT = "%Y-%m-%d"


class NewsError(Exception):
    """A user-facing failure; the message is already a Chinese instruction."""


class NewsTools:
    def __init__(self, service: Any, sources: Any) -> None:
        self.service = service
        self.sources = sources

    # ------------------------------------------------------------------ shared
    def _event(self, tool: str, source: str, *, ok: bool, error: str | None = None) -> None:
        try:
            self.service._event(tool, source, ok=ok, error=error)
        except Exception:
            pass

    def _cached(self, key: str, ttl: float, fallback: float, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        return self.service._cached(key, ttl, fallback, compute)

    def _now(self) -> datetime:
        return self.service.now()

    def _int(self, args: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
        value = args.get(name)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise NewsError(f"{name} 必须是 {low} 到 {high} 的整数")
        return value

    def _date(self, args: dict[str, Any], name: str, default: date) -> date:
        value = args.get(name)
        if value is None:
            return default
        if not isinstance(value, str):
            raise NewsError(f"{name} 必须是 YYYY-MM-DD 格式的日期")
        try:
            return datetime.strptime(value, DATE_FORMAT).date()
        except ValueError:
            raise NewsError(f"{name} 必须是 YYYY-MM-DD 格式的日期") from None

    @staticmethod
    def _stock_code(value: Any, field: str = "code") -> Code:
        if value is None:
            raise NewsError(f"请提供 {field}，例如 000528 或 600519.SH")
        try:
            code = normalize_code(value)
        except InvalidCode as exc:
            raise NewsError(str(exc)) from None
        if code.is_index:
            raise NewsError(f"{field} 需要个股代码，不能是指数")
        return code

    # ------------------------------------------------------------------ news
    def news(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind")
        if kind not in NEWS_KINDS:
            raise NewsError("kind 必须是 stock、flash、irm、calendar、suspensions 之一")
        if kind == "stock":
            return self._stock_news(args)
        if kind == "flash":
            return self._flash_news(args)
        if kind == "irm":
            return self._irm(args)
        if kind == "calendar":
            return self._calendar(args)
        return self._suspensions(args)

    def _stock_news(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._stock_code(args.get("code"))
        limit = self._int(args, "limit", 1, config.MAX_NEWS_LIMIT, config.DEFAULT_NEWS_LIMIT)
        key = f"news|stock|{code.canonical}|{limit}"
        return self._cached(
            key, config.NEWS_STOCK_TTL, config.NEWS_STOCK_FALLBACK, lambda: self._stock_compute(code, limit)
        )

    def _stock_compute(self, code: Code, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.stock_news(code.digits)
            self._event("news", "search-api-web.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("news", "search-api-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise NewsError("个股新闻暂时取不到，稍后再试") from None
        entries = normalize_stock_news(rows)
        for item in entries:
            item["code"] = code.canonical
        items = entries[:limit]
        as_of = items[0]["time"] if items and items[0].get("time") else now_iso(self._now())
        return envelope(
            "ok",
            data={
                "kind": "stock",
                "code": code.canonical,
                "count": len(items),
                "total_available": len(entries),
                "items": items,
                "untrusted_text": True,
            },
            as_of=str(as_of),
        )

    def _flash_news(self, args: dict[str, Any]) -> dict[str, Any]:
        channel = args.get("channel") or "all"
        if channel not in CHANNELS:
            raise NewsError("channel 只能是 all 或 important")
        limit = self._int(args, "limit", 1, config.MAX_NEWS_LIMIT, config.DEFAULT_FLASH_LIMIT)
        key = f"news|flash|{channel}|{limit}"
        return self._cached(
            key, config.NEWS_FLASH_TTL, config.NEWS_FLASH_FALLBACK, lambda: self._flash_compute(channel, limit)
        )

    def _flash_compute(self, channel: str, limit: int) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        failures = 0
        try:
            entries.extend(normalize_flash_cls(self.sources.flash_cls(), channel))
            self._event("news", "www.cls.cn", ok=True)
        except Exception as exc:
            failures += 1
            self._event("news", "www.cls.cn", ok=False, error=type(exc).__name__)
        try:
            entries.extend(normalize_flash_em(self.sources.flash_em()))
            self._event("news", "np-weblist.eastmoney.com", ok=True)
        except Exception as exc:
            failures += 1
            self._event("news", "np-weblist.eastmoney.com", ok=False, error=type(exc).__name__)
        if failures >= 2:
            raise NewsError("快讯暂时取不到，稍后再试")
        merged = merge_flash(entries)
        items = merged[:limit]
        as_of = items[0]["time"] if items and items[0].get("time") else now_iso(self._now())
        gaps = [missing("items", "部分快讯暂时取不到")] if failures else []
        return envelope(
            "partial" if gaps else "ok",
            data={
                "kind": "flash",
                "channel": channel,
                "count": len(items),
                "total_available": len(merged),
                "items": items,
                "untrusted_text": True,
            },
            as_of=str(as_of),
            missing_items=gaps,
        )

    def _irm(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._stock_code(args.get("code"))
        limit = self._int(args, "limit", 1, config.MAX_NEWS_LIMIT, config.DEFAULT_NEWS_LIMIT)
        key = f"news|irm|{code.canonical}|{limit}"
        return self._cached(
            key, config.NEWS_IRM_TTL, config.NEWS_IRM_FALLBACK, lambda: self._irm_compute(code, limit)
        )

    def _irm_compute(self, code: Code, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.irm(code.digits)
            self._event("news", "irm.cninfo.com.cn", ok=True)
        except Exception as exc:
            self._event("news", "irm.cninfo.com.cn", ok=False, error=type(exc).__name__)
            raise NewsError("问答数据暂时取不到，稍后再试") from None
        entries = normalize_irm(rows)
        for item in entries:
            item["code"] = code.canonical
            item.setdefault("url", None)
        items = entries[:limit]
        as_of = items[0]["time"] if items and items[0].get("time") else now_iso(self._now())
        return envelope(
            "ok",
            data={
                "kind": "irm",
                "code": code.canonical,
                "count": len(items),
                "total_available": len(entries),
                "items": items,
                "untrusted_text": True,
            },
            as_of=str(as_of),
        )

    def _calendar(self, args: dict[str, Any]) -> dict[str, Any]:
        day = self._date(args, "date", self._now().date())
        limit = self._int(args, "limit", 1, config.MAX_NEWS_LIMIT, config.MAX_NEWS_LIMIT)
        key = f"news|calendar|{day}|{limit}"
        return self._cached(
            key, config.NEWS_CALENDAR_TTL, config.NEWS_CALENDAR_FALLBACK, lambda: self._calendar_compute(day, limit)
        )

    def _calendar_compute(self, day: date, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.calendar(day.strftime("%Y%m%d"))
            self._event("news", "finance.pae.baidu.com", ok=True)
        except Exception as exc:
            self._event("news", "finance.pae.baidu.com", ok=False, error=type(exc).__name__)
            raise NewsError("财经日历暂时取不到，稍后再试") from None
        entries = normalize_calendar(rows, day.isoformat())
        items = entries[:limit]
        as_of = max((item["time"] for item in items if item.get("time")), default=None) or now_iso(self._now())
        return envelope(
            "ok",
            data={
                "kind": "calendar",
                "date": day.isoformat(),
                "count": len(items),
                "total_available": len(entries),
                "items": items,
                "untrusted_text": True,
            },
            as_of=str(as_of),
        )

    def _suspensions(self, args: dict[str, Any]) -> dict[str, Any]:
        day = self._date(args, "date", self._now().date())
        limit = self._int(args, "limit", 1, config.MAX_NEWS_LIMIT, config.MAX_NEWS_LIMIT)
        key = f"news|suspensions|{day}|{limit}"
        return self._cached(
            key,
            config.NEWS_SUSPENSIONS_TTL,
            config.NEWS_SUSPENSIONS_FALLBACK,
            lambda: self._suspensions_compute(day, limit),
        )

    def _suspensions_compute(self, day: date, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.suspensions(day.strftime("%Y%m%d"))
            self._event("news", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("news", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise NewsError("停复牌数据暂时取不到，稍后再试") from None
        entries, dropped = normalize_suspensions(rows)
        items = entries[:limit]
        as_of = max((item["time"] for item in items if item.get("time")), default=None) or now_iso(self._now())
        return envelope(
            "ok",
            data={
                "kind": "suspensions",
                "date": day.isoformat(),
                "count": len(items),
                "total_available": len(entries),
                "dropped": dropped,
                "items": items,
                "untrusted_text": True,
            },
            as_of=str(as_of),
        )

    # ------------------------------------------------------------------ announcements
    def company_announcements(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("url") is not None:
            return self._read_announcement(args)
        return self._search_announcements(args)

    def _search_announcements(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._stock_code(args.get("code"))
        end = self._date(args, "end", self._now().date())
        start = self._date(args, "start", end - timedelta(days=ANNOUNCEMENT_DEFAULT_DAYS))
        if start > end:
            raise NewsError("start 不能晚于 end")
        category = args.get("category")
        if category is None:
            category = ""
        if not isinstance(category, str) or (category and category not in ANNOUNCEMENT_CATEGORIES):
            raise NewsError("category 必须是公告类别之一，例如 年报、半年报、业绩预告；留空表示全部")
        limit = self._int(
            args, "limit", 1, config.MAX_ANNOUNCEMENTS_LIMIT, ANNOUNCEMENT_DEFAULT_LIMIT
        )
        offset = self._int(args, "offset", 0, config.MAX_ANNOUNCEMENT_OFFSET, 0)
        key = f"announcements|{code.canonical}|{start}|{end}|{category}|{limit}|{offset}"
        return self._cached(
            key,
            config.ANNOUNCEMENTS_TTL,
            config.ANNOUNCEMENTS_FALLBACK,
            lambda: self._announcements_compute(code, start, end, category, limit, offset),
        )

    def _announcements_compute(
        self, code: Code, start: date, end: date, category: str, limit: int, offset: int
    ) -> dict[str, Any]:
        try:
            name, rows, total = self.sources.announcements(
                code.digits, category=category, start=start, end=end, limit=limit, offset=offset
            )
            self._event("company_announcements", "www.cninfo.com.cn", ok=True)
        except Exception as exc:
            self._event("company_announcements", "www.cninfo.com.cn", ok=False, error=type(exc).__name__)
            raise NewsError("公告检索暂时不可用，稍后再试") from None
        bias = []
        if not category:
            bias.append(basis("category", "未指定 category 时接口不返回逐条类别，category 字段为 null"))
        return envelope(
            "ok",
            data={
                "code": code.canonical,
                "name": name,
                "count": total,
                "total": total,
                "offset": offset,
                "returned": len(rows),
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
                "range": [start.isoformat(), end.isoformat()],
                "truncated": offset + len(rows) < total,
                "untrusted_text": True,
                "announcements": rows,
            },
            as_of=now_iso(self._now()),
            basis_items=bias,
        )

    def _read_announcement(self, args: dict[str, Any]) -> dict[str, Any]:
        for name in ("code", "start", "end", "category", "limit", "offset"):
            if args.get(name) is not None:
                raise NewsError("读公告原文时只给 url、start_page、end_page、max_chars、layout，不要再给检索参数")
        try:
            pdf_url = pdfmod.resolve_pdf_url(args.get("url"))
        except pdfmod.InvalidAnnouncementUrl as exc:
            raise NewsError(str(exc)) from None
        start_page = self._int(args, "start_page", 1, 10_000, 1)
        end_page = args.get("end_page")
        if end_page is not None:
            end_page = self._int(args, "end_page", start_page, 10_000, start_page)
        max_chars = self._int(
            args, "max_chars", pdfmod.MIN_MAX_CHARS, pdfmod.MAX_MAX_CHARS, pdfmod.DEFAULT_MAX_CHARS
        )
        layout = args.get("layout", True)
        if not isinstance(layout, bool):
            raise NewsError("layout 必须是 true 或 false")
        executable = pdfmod.pdftotext_path()
        if executable is None:
            return unavailable(
                now_iso(self._now()),
                "系统没有安装 pdftotext（poppler），无法读取公告原文；请安装后重试",
            )
        try:
            body = self.sources.download_pdf(pdf_url)
            self._event("company_announcements", "static.cninfo.com.cn", ok=True)
        except UpstreamError as exc:
            self._event("company_announcements", "static.cninfo.com.cn", ok=False, error=exc.code)
            if exc.code == "redirect_refused":
                raise NewsError("该公告链接跳转到了别处，已拒绝下载") from None
            raise NewsError("公告原文暂时下载不到，稍后再试") from None
        except pdfmod.PdfExtractionError as exc:
            self._event("company_announcements", "static.cninfo.com.cn", ok=False, error=exc.code)
            raise NewsError(exc.message) from None
        try:
            extracted = pdfmod.extract_pdf_text(
                body,
                executable=executable,
                start_page=start_page,
                end_page=end_page,
                layout=layout,
                max_chars=max_chars,
            )
            self._event("company_announcements", "pdftotext", ok=True)
        except pdfmod.PdfExtractionError as exc:
            self._event("company_announcements", "pdftotext", ok=False, error=exc.code)
            raise NewsError(exc.message) from None
        return envelope(
            "ok",
            data={
                "url": args.get("url"),
                "pages_total": extracted.pages_total,
                "pages_returned": extracted.pages_returned,
                "chars": len(extracted.text),
                "truncated": extracted.truncated,
                "text": extracted.text,
                "untrusted_text": True,
            },
            as_of=now_iso(self._now()),
        )

    # ------------------------------------------------------------------ convertible bonds
    def convertible_bonds(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind")
        if kind not in CB_KINDS:
            raise NewsError("kind 必须是 list 或 quote")
        if kind == "list":
            return self._cb_list(args)
        return self._cb_quote(args)

    @staticmethod
    def _canonical(digits: str | None) -> str | None:
        if digits is None or not digits.isdigit() or len(digits) != 6:
            return None
        if digits.startswith("6"):
            return f"{digits}.SH"
        if digits.startswith(("0", "3")):
            return f"{digits}.SZ"
        return f"{digits}.BJ"

    @staticmethod
    def _row_digits(value: Any) -> str | None:
        raw = text(value)
        if raw is None:
            return None
        if raw.endswith(".0") and raw[:-2].isdigit():
            raw = raw[:-2]
        return raw.zfill(6) if raw.isdigit() and len(raw) <= 6 else None

    def _cb_list(self, args: dict[str, Any]) -> dict[str, Any]:
        underlying = None
        if args.get("underlying") is not None:
            underlying = self._stock_code(args.get("underlying"), "underlying")
        limit = self._int(
            args, "limit", 1, config.MAX_CB_LIST_LIMIT, config.DEFAULT_CB_LIST_LIMIT
        )
        key = f"cb|list|{underlying.canonical if underlying else 'all'}|{limit}"
        return self._cached(
            key, config.CB_LIST_TTL, config.CB_LIST_FALLBACK, lambda: self._cb_list_compute(underlying, limit)
        )

    def _cb_list_compute(self, underlying: Code | None, limit: int) -> dict[str, Any]:
        try:
            raw = self.sources.cb_terms()
            self._event("convertible_bonds", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            self._event("convertible_bonds", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise NewsError("可转债列表暂时取不到，稍后再试") from None
        today = self._now().date()
        rows: list[dict[str, Any]] = []
        dropped_unlisted = 0
        dropped_delisted = 0
        dropped_invalid = 0
        for item in raw:
            code = bond_code(item.get("SECURITY_CODE"))
            if code is None:
                dropped_invalid += 1
                continue
            listing = parse_date(item.get("LISTING_DATE"))
            if listing is None or listing > today.isoformat():
                dropped_unlisted += 1
                continue
            name, _ = clean_text(item.get("SECURITY_NAME_ABBR"))
            delisted = parse_date(item.get("DELIST_DATE"))
            if (delisted is not None and delisted <= today.isoformat()) or code.startswith("404") or (
                name is not None and "退" in name
            ):
                dropped_delisted += 1
                continue
            underlying_digits = self._row_digits(item.get("CONVERT_STOCK_CODE"))
            if underlying is not None and underlying_digits != underlying.digits:
                continue
            conversion_price = positive(item.get("TRANSFER_PRICE"))
            underlying_price = positive(item.get("CONVERT_STOCK_PRICE"))
            bond_price = positive(item.get("CURRENT_BOND_PRICE"))
            value = conversion_value(conversion_price, underlying_price)
            premium = premium_pct(bond_price, value)
            issue_scale = fnum(item.get("ACTUAL_ISSUE_SCALE"))
            underlying_name, _ = clean_text(item.get("SECURITY_SHORT_NAME"))
            rows.append(
                {
                    "bond_code": code,
                    "bond_name": name,
                    "underlying_code": self._canonical(underlying_digits),
                    "underlying_name": underlying_name,
                    "bond_price_yuan": None if bond_price is None else round(bond_price, 4),
                    "change_pct": None if fnum(item.get("CURRENT_BOND_CHANGE_PCT")) is None else round(
                        float(item["CURRENT_BOND_CHANGE_PCT"]), 4
                    ),
                    "amount_yuan": None if fnum(item.get("CURRENT_BOND_AMOUNT")) is None else round(
                        float(item["CURRENT_BOND_AMOUNT"]), 2
                    ),
                    "underlying_price_yuan": None if underlying_price is None else round(underlying_price, 4),
                    "conversion_price_yuan": None if conversion_price is None else round(conversion_price, 4),
                    "conversion_value_yuan": None if value is None else round(value, 4),
                    "premium_pct": None if premium is None else round(premium, 4),
                    "maturity_date": parse_date(item.get("EXPIRE_DATE")),
                    "credit_rating": text(item.get("RATING")),
                    "issue_size_yuan": None if issue_scale is None else round(issue_scale * 100_000_000.0, 2),
                    "listing_date": listing,
                    "transfer_start_date": parse_date(item.get("TRANSFER_START_DATE")),
                    "listing_status": "listed" if underlying_price is not None else "unknown",
                    "remaining_size_yuan": None,
                    "remaining_size_computed": False,
                }
            )
        rows.sort(key=lambda row: row["bond_code"])
        rows.sort(key=lambda row: row["listing_date"] or "", reverse=True)
        total = len(rows)
        selected = rows[:limit]
        gaps: list[dict[str, Any]] = []
        codes = [row["bond_code"] for row in selected]
        remaining: dict[str, dict[str, Any]] = {}
        needs_remaining = any(
            (row["transfer_start_date"] or "") <= today.isoformat() for row in selected
        )
        if codes and needs_remaining:
            try:
                remaining = self.sources.cb_remaining(codes)
                self._event("convertible_bonds", "datacenter-web.eastmoney.com", ok=True)
            except Exception as exc:
                self._event(
                    "convertible_bonds", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__
                )
                gaps.append(missing("remaining_size_yuan", "剩余规模暂时取不到"))
        for row in selected:
            hit = remaining.get(row["bond_code"])
            if hit is not None:
                row["remaining_size_yuan"] = round(float(hit["size_yuan"]), 2)
                row["remaining_size_date"] = hit.get("date")
            elif (row["transfer_start_date"] or "") > today.isoformat() and row["issue_size_yuan"] is not None:
                # Before the conversion period starts, no conversion can have happened.
                row["remaining_size_yuan"] = row["issue_size_yuan"]
                row["remaining_size_computed"] = True
            elif not any(item["field"] == "remaining_size_yuan" for item in gaps):
                gaps.append(missing("remaining_size_yuan", "该转债的剩余规模暂时取不到", item=row["bond_code"]))
            if row["conversion_value_yuan"] is None:
                gaps.append(
                    missing("conversion_value_yuan", "正股价或转股价暂时取不到，无法计算转股价值", item=row["bond_code"])
                )
            if row["premium_pct"] is None:
                gaps.append(missing("premium_pct", "转债价或转股价值取不到，无法计算转股溢价率", item=row["bond_code"]))
        if not selected:
            return envelope(
                "ok",
                data={
                    "kind": "list",
                    "underlying": None if underlying is None else underlying.canonical,
                    "total_available": 0,
                    "returned": 0,
                    "rows": [],
                    "dropped_unlisted": dropped_unlisted,
                    "dropped_delisted": dropped_delisted,
                    "dropped_invalid_code": dropped_invalid,
                },
                as_of=now_iso(self._now()),
            )
        return envelope(
            "partial" if gaps else "ok",
            data={
                "kind": "list",
                "underlying": None if underlying is None else underlying.canonical,
                "total_available": total,
                "returned": len(selected),
                "rows": selected,
                "dropped_unlisted": dropped_unlisted,
                "dropped_delisted": dropped_delisted,
                "dropped_invalid_code": dropped_invalid,
                "listing_status_note": (
                    "listing_status=listed 表示条款表里有正股价；unknown 表示没有。"
                    "上市时间缺失或在未来的按未上市剔除；简称含“退”或代码以 404 开头的按退市剔除。"
                ),
                "underlying_price_note": "underlying_price_yuan 与 conversion_price_yuan 是条款表字段，不是实时行情。",
                "formula": (
                    "conversion_value_yuan = 100 / conversion_price_yuan * underlying_price_yuan; "
                    "premium_pct = (bond_price_yuan / conversion_value_yuan - 1) * 100"
                ),
            },
            as_of=now_iso(self._now()),
            missing_items=gaps,
        )

    def _cb_quote(self, args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("codes")
        if not isinstance(raw, list) or isinstance(raw, (str, bytes)) or not raw:
            raise NewsError("codes 必须是 1 到 20 只可转债代码的列表，例如 [\"127056\"]")
        if len(raw) > config.MAX_CB_CODES:
            raise NewsError("codes 最多 20 只")
        codes: list[str] = []
        for item in raw:
            code = bond_code(item)
            if code is None:
                raise NewsError("可转债代码必须是 6 位数字字符串")
            if code not in codes:
                codes.append(code)
        key = "cb|quote|" + ",".join(codes)
        return self._cached(
            key, config.CB_QUOTE_TTL, config.CB_QUOTE_FALLBACK, lambda: self._cb_quote_compute(codes)
        )

    def _cb_quote_compute(self, codes: list[str]) -> dict[str, Any]:
        spot_rows: list[dict[str, Any]] = []
        spot_ok = True
        try:
            spot_rows = self.sources.cb_spot()
            self._event("convertible_bonds", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            spot_ok = False
            self._event(
                "convertible_bonds", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__
            )
        terms: dict[str, dict[str, Any]] = {}
        terms_ok = True
        try:
            terms = self.sources.cb_terms_by_codes(codes)
            self._event("convertible_bonds", "datacenter-web.eastmoney.com", ok=True)
        except Exception as exc:
            terms_ok = False
            self._event(
                "convertible_bonds", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__
            )
        if not spot_ok and not terms_ok:
            raise NewsError("可转债行情暂时不可用，稍后再试")
        spot_by_code: dict[str, dict[str, Any]] = {}
        for row in spot_rows:
            code = bond_code(row.get("code"))
            if code is not None:
                spot_by_code.setdefault(code, row)
        today = self._now().date()
        rows: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        stamps: list[str] = []
        for code in codes:
            spot = spot_by_code.get(code)
            term = terms.get(code)
            price = positive(spot.get("trade")) if spot is not None else None
            change = fnum(spot.get("changepercent")) if spot is not None else None
            amount = fnum(spot.get("amount")) if spot is not None else None
            name, _ = clean_text(spot.get("name")) if spot is not None else (None, False)
            if name is None and term is not None:
                name, _ = clean_text(term.get("SECURITY_NAME_ABBR"))
            underlying_digits = self._row_digits(term.get("CONVERT_STOCK_CODE")) if term is not None else None
            conversion_price = positive(term.get("TRANSFER_PRICE")) if term is not None else None
            underlying_price = positive(term.get("CONVERT_STOCK_PRICE")) if term is not None else None
            value = conversion_value(conversion_price, underlying_price)
            premium = premium_pct(price, value)
            quote_time = None
            if spot is not None and spot.get("ticktime"):
                try:
                    quote_time = datetime.combine(
                        today, time_type.fromisoformat(str(spot["ticktime"])), tzinfo=config.CN_TZ
                    ).isoformat(timespec="seconds")
                    stamps.append(quote_time)
                except ValueError:
                    quote_time = None
            row: dict[str, Any] = {
                "bond_code": code,
                "name": name,
                "bond_price_yuan": None if price is None else round(price, 4),
                "change_pct": None if change is None else round(change, 4),
                "amount_yuan": None if amount is None else round(amount, 2),
                "underlying_code": self._canonical(underlying_digits),
                "underlying_price_yuan": None if underlying_price is None else round(underlying_price, 4),
                "conversion_price_yuan": None if conversion_price is None else round(conversion_price, 4),
                "conversion_value_yuan": None if value is None else round(value, 4),
                "premium_pct": None if premium is None else round(premium, 4),
                "maturity_date": parse_date(term.get("EXPIRE_DATE")) if term is not None else None,
                "credit_rating": text(term.get("RATING")) if term is not None else None,
                "quote_time": quote_time,
            }
            if spot is None:
                gaps.append(missing("quote", "该转债暂时取不到行情", item=code))
            if term is None:
                gaps.append(missing("terms", "该转债暂时取不到条款", item=code))
            if row["conversion_value_yuan"] is None:
                gaps.append(missing("conversion_value_yuan", "正股价或转股价暂时取不到，无法计算转股价值", item=code))
            if row["premium_pct"] is None:
                gaps.append(missing("premium_pct", "转债价或转股价值取不到，无法计算转股溢价率", item=code))
            rows.append(row)
        as_of = max(stamps) if stamps else now_iso(self._now())
        return envelope(
            "partial" if gaps else "ok",
            data={
                "kind": "quote",
                "bond_codes": codes,
                "quote_date": today.isoformat(),
                "computed": True,
                "rows": rows,
                "formula": (
                    "conversion_value_yuan = 100 / conversion_price_yuan * underlying_price_yuan; "
                    "premium_pct = (bond_price_yuan / conversion_value_yuan - 1) * 100"
                ),
            },
            as_of=as_of,
            missing_items=gaps,
        )

