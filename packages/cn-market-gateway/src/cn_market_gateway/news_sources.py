"""Upstream fetchers for news, announcements and convertible bonds (T143)."""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

from . import config
from .announcement import MAX_PDF_BYTES, PDF_TIMEOUT, PdfExtractionError
from .news_parse import CN_TZ, clean_text
from .transport import HostGovernor, UpstreamError

EASTMONEY_SEARCH = "search-api-web.eastmoney.com"
EASTMONEY_DC_WEB = "datacenter-web.eastmoney.com"
CLS = "www.cls.cn"
EASTMONEY_FAST = "np-weblist.eastmoney.com"
BAIDU_CALENDAR = "finance.pae.baidu.com"
CNINFO_IRM = "irm.cninfo.com.cn"
CNINFO_WEB = "www.cninfo.com.cn"
CNINFO_STATIC = "static.cninfo.com.cn"
SINA_BOND = "vip.stock.finance.sina.com.cn"

ANNOUNCEMENT_MARKET = "沪深京"
ANNOUNCEMENT_CATEGORIES = (
    "年报", "半年报", "一季报", "三季报", "业绩预告", "权益分派", "董事会", "监事会",
    "股东大会", "日常经营", "公司治理", "中介报告", "首发", "增发", "股权激励", "配股",
    "解禁", "公司债", "可转债", "其他融资", "股权变动", "补充更正", "澄清致歉",
    "风险提示", "特别处理和退市", "退市整理期",
)
ANNOUNCEMENT_DEFAULT_DAYS = 90
ANNOUNCEMENT_DEFAULT_LIMIT = 20
ANNOUNCEMENT_MAX_LIMIT = 100
ANNOUNCEMENT_PAGE_SIZE = 30

CB_QUOTE_COLUMNS = (
    "f2~10~SECURITY_CODE~CURRENT_BOND_PRICE,f3~10~SECURITY_CODE~CURRENT_BOND_CHANGE_PCT,"
    "f5~10~SECURITY_CODE~CURRENT_BOND_VOLUME,f6~10~SECURITY_CODE~CURRENT_BOND_AMOUNT,"
    "f235~10~SECURITY_CODE~TRANSFER_PRICE,f236~10~SECURITY_CODE~TRANSFER_VALUE,"
    "f237~10~SECURITY_CODE~TRANSFER_PREMIUM_RATIO,"
    "f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE"
)
CB_PAGE_SIZE = 100


def records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    to_dict = getattr(frame, "to_dict", None)
    if to_dict is None:
        return list(frame) if isinstance(frame, list) else []
    if getattr(frame, "empty", False):
        return []
    return list(to_dict(orient="records"))


class AkShareNewsAdapter:
    """The AKShare entry points used by this task, one method per endpoint."""

    def __init__(self, governor: HostGovernor) -> None:
        self.governor = governor

    def _call(self, host: str, name: str, **kwargs: Any) -> list[dict[str, Any]]:
        import akshare as ak

        fn: Callable[..., Any] = getattr(ak, name)

        def call() -> Any:
            return fn(**kwargs)

        return records(self.governor.run_external(host, call, timeout=config.AKSHARE_TIMEOUT))

    def stock_news(self, digits: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_SEARCH, "stock_news_em", symbol=digits)

    def flash_cls(self) -> list[dict[str, Any]]:
        return self._call(CLS, "stock_news_global_cls", symbol="全部")

    def flash_em(self) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_FAST, "stock_news_global_em")

    def calendar(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self._call(BAIDU_CALENDAR, "macro_calendar_baidu", date=date_yyyymmdd)

    def suspensions(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self._call(EASTMONEY_DC_WEB, "stock_tfp_em", date=date_yyyymmdd)

    def irm(self, digits: str) -> list[dict[str, Any]]:
        return self._call(CNINFO_IRM, "stock_irm_cninfo", symbol=digits)

    def cb_spot(self) -> list[dict[str, Any]]:
        return self._call(SINA_BOND, "bond_cb_realtime_sina")


class NewsSources:
    """Facade used by NewsTools; tests inject a fake with the same methods."""

    def __init__(
        self,
        governor: HostGovernor,
        akshare: AkShareNewsAdapter | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.governor = governor
        self.akshare = akshare or AkShareNewsAdapter(governor)
        self._clock = clock
        self._lock = threading.Lock()
        self._org_cache: dict[str, str] | None = None
        self._org_at = 0.0

    # -- news -------------------------------------------------------------
    def stock_news(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.stock_news(digits)

    def flash_cls(self) -> list[dict[str, Any]]:
        return self.akshare.flash_cls()

    def flash_em(self) -> list[dict[str, Any]]:
        return self.akshare.flash_em()

    def calendar(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self.akshare.calendar(date_yyyymmdd)

    def suspensions(self, date_yyyymmdd: str) -> list[dict[str, Any]]:
        return self.akshare.suspensions(date_yyyymmdd)

    def irm(self, digits: str) -> list[dict[str, Any]]:
        return self.akshare.irm(digits)

    # -- announcements ----------------------------------------------------
    def org_map(self) -> dict[str, str]:
        with self._lock:
            if self._org_cache is not None and self._clock() - self._org_at < config.COMPANY_NAMES_TTL:
                return self._org_cache
        text = self.governor.request(CNINFO_WEB, "/new/data/szse_stock.json")
        payload = json.loads(text)
        rows = payload.get("stockList") if isinstance(payload, dict) else None
        mapping: dict[str, str] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            org = str(row.get("orgId") or "").strip()
            if code.isdigit() and org:
                mapping[code.zfill(6)] = org
        with self._lock:
            self._org_cache = mapping
            self._org_at = self._clock()
        return mapping

    def announcements(
        self,
        digits: str,
        *,
        category: str,
        start: date,
        end: date,
        limit: int,
        offset: int = 0,
    ) -> tuple[str | None, list[dict[str, Any]], int]:
        org_id = self.org_map().get(digits)
        if not org_id:
            raise UpstreamError("not_found", circuit=False)
        name: str | None = None
        rows: list[dict[str, Any]] = []
        total = 0
        # Jump straight to the upstream page that contains `offset`; earlier pages are not read.
        page = offset // ANNOUNCEMENT_PAGE_SIZE + 1
        skip = offset % ANNOUNCEMENT_PAGE_SIZE
        first_page = True
        pages: int | None = None
        # At most the pages needed for this slice (plus one tolerance page) are read.
        max_pages = max(1, (skip + limit + ANNOUNCEMENT_PAGE_SIZE - 1) // ANNOUNCEMENT_PAGE_SIZE) + 1
        fetched = 0
        while (pages is None or page <= pages) and len(rows) < limit and fetched < max_pages:
            form = {
                "pageNum": str(page),
                "pageSize": str(ANNOUNCEMENT_PAGE_SIZE),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{digits},{org_id}",
                "searchkey": "",
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": f"{start.isoformat()}~{end.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            text = self.governor.request_form(CNINFO_WEB, "/new/hisAnnouncement/query", form=form)
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise UpstreamError("upstream_error", circuit=False)
            total = int(payload.get("totalAnnouncement") or 0)
            pages = max(1, (total + ANNOUNCEMENT_PAGE_SIZE - 1) // ANNOUNCEMENT_PAGE_SIZE)
            if offset >= total:
                return name, [], total
            items = payload.get("announcements") or []
            if first_page:
                items = items[skip:]
                first_page = False
            for item in items:
                parsed = self._announcement_item(item, category)
                if parsed is None:
                    continue
                if name is None:
                    name, _ = clean_text(item.get("secName"))
                rows.append(parsed)
            page += 1
            fetched += 1
        return name, rows[:limit], total

    @staticmethod
    def _announcement_item(item: Any, category: str) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title, _ = clean_text(item.get("announcementTitle"))
        stamp = item.get("announcementTime")
        code = str(item.get("secCode") or "").strip()
        announcement_id = str(item.get("announcementId") or "").strip()
        org_id = str(item.get("orgId") or "").strip()
        if title is None or not code or not announcement_id or not org_id or not isinstance(stamp, (int, float)):
            return None
        moment = datetime.fromtimestamp(float(stamp) / 1000.0, tz=CN_TZ)
        naive = moment.replace(tzinfo=None).isoformat(sep=" ")
        query = urlencode(
            {
                "stockCode": code,
                "announcementId": announcement_id,
                "orgId": org_id,
                "announcementTime": naive,
            }
        )
        url = f"http://www.cninfo.com.cn/new/disclosure/detail?{query}"
        return {
            "date": moment.date().isoformat(),
            "title": title,
            "category": category or None,
            "url": url,
        }

    # -- convertible bonds ------------------------------------------------
    def cb_spot(self) -> list[dict[str, Any]]:
        return self.akshare.cb_spot()

    def cb_terms(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        pages = 1
        while page <= pages:
            text = self.governor.request(
                EASTMONEY_DC_WEB,
                "/api/data/v1/get",
                params={
                    "sortColumns": "PUBLIC_START_DATE",
                    "sortTypes": "-1",
                    "pageSize": str(CB_PAGE_SIZE),
                    "pageNumber": str(page),
                    "reportName": "RPT_BOND_CB_LIST",
                    "columns": "ALL",
                    "quoteColumns": CB_QUOTE_COLUMNS,
                    "source": "WEB",
                    "client": "WEB",
                },
            )
            payload = json.loads(text)
            result = payload.get("result") if isinstance(payload, dict) else None
            data = result.get("data") if isinstance(result, dict) else None
            pages = int(result.get("pages") or 1) if isinstance(result, dict) else 1
            rows.extend(item for item in (data or []) if isinstance(item, dict))
            page += 1
        return rows

    def cb_terms_by_codes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        expr = '(SECURITY_CODE in (' + ",".join(f'"{code}"' for code in codes) + "))"
        text = self.governor.request(
            EASTMONEY_DC_WEB,
            "/api/data/v1/get",
            params={
                "reportName": "RPT_BOND_CB_LIST",
                "columns": "ALL",
                "quoteColumns": CB_QUOTE_COLUMNS,
                "pageSize": "100",
                "pageNumber": "1",
                "source": "WEB",
                "client": "WEB",
                "filter": expr,
            },
        )
        payload = json.loads(text)
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        mapping: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            if isinstance(row, dict):
                mapping.setdefault(str(row.get("SECURITY_CODE") or ""), row)
        return mapping

    def cb_remaining(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        """Latest unconverted balance (SYFE, yuan) per bond; missing bonds stay absent."""
        result: dict[str, dict[str, Any]] = {}
        for index in range(0, len(codes), 100):
            batch = codes[index : index + 100]
            expr = "(zcode in (" + ",".join(f'"{code}"' for code in batch) + "))"
            text = self.governor.request(
                EASTMONEY_DC_WEB,
                "/api/data/v1/get",
                params={
                    "columns": "ALL",
                    "sortColumns": "date",
                    "sortTypes": "-1",
                    "source": "WEB",
                    "reportName": "RPTA_WEB_KZZ_LS",
                    "pageNumber": "1",
                    "pageSize": "3000",
                    "filter": expr,
                },
            )
            payload = json.loads(text)
            node = payload.get("result") if isinstance(payload, dict) else None
            rows = node.get("data") if isinstance(node, dict) else None
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("ZCODE") or "")
                size = row.get("SYFE")
                if code in result or not isinstance(size, (int, float)):
                    continue
                stamp = str(row.get("DATE") or "")[:10]
                result[code] = {"date": stamp or None, "size_yuan": float(size)}
        return result

    # -- announcement PDF -------------------------------------------------
    def download_pdf(self, pdf_url: str) -> bytes:
        parts = urlsplit(pdf_url)
        host = parts.hostname or ""
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        status, headers, body = self.governor.request_bytes(
            host,
            path,
            headers={"Accept": "application/pdf", "Referer": "https://www.cninfo.com.cn/"},
            timeout=PDF_TIMEOUT,
            max_bytes=MAX_PDF_BYTES,
        )
        content_type = str(headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if status != 200:
            raise PdfExtractionError("download_failed", f"下载公告原文失败（状态码 {status}）")
        if content_type != "application/pdf":
            raise PdfExtractionError("not_pdf", "下载到的内容不是 PDF")
        if not body.startswith(b"%PDF-"):
            raise PdfExtractionError("not_pdf", "下载到的内容不是 PDF")
        return body
