"""External market-data calls. Kept in one module so tests can inject fakes."""

from __future__ import annotations

import http.client
from typing import Sequence
from urllib.parse import urlsplit

import pandas as pd
from urllib.request import Request, urlopen

TENCENT_URL = "https://qt.gtimg.cn/q={symbols}"
SINA_HOST = "hq.sinajs.cn"
SINA_URL = "https://hq.sinajs.cn/list={symbols}"
SINA_REFERER = "https://finance.sina.com.cn"
_UA = "Mozilla/5.0 (compatible; cn-extra-mcp/0.1; +https://gu.qq.com/)"

PDF_TIMEOUT = 20.0
MAX_PDF_BYTES = 25 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PdfDownloadError(Exception):
    """PDF download failure carrying the envelope error code."""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _pdf_connection(parts, timeout: float) -> http.client.HTTPConnection:
    port = parts.port or (443 if parts.scheme == "https" else 80)
    factory = (
        http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    )
    return factory(parts.hostname or "", port, timeout=timeout)


def fetch_pdf_bytes(
    url: str,
    *,
    timeout: float = PDF_TIMEOUT,
    max_bytes: int = MAX_PDF_BYTES,
) -> tuple[bytes, str]:
    """Download one PDF from an already whitelisted cninfo URL.

    allow_redirects=False: every 3xx is reported as download_failed and never followed,
    because following a redirect could leave the cninfo allowlist (SSRF).
    """
    parts = urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    connection = _pdf_connection(parts, timeout)
    try:
        connection.request(
            "GET",
            target,
            headers={
                "User-Agent": _UA,
                "Accept": PDF_CONTENT_TYPE,
                "Referer": "https://www.cninfo.com.cn/",
            },
        )
        response = connection.getresponse()
        status = response.status
        if status in _REDIRECT_STATUSES:
            raise PdfDownloadError(
                "download_failed",
                f"refused redirect to another host (HTTP {status})",
                status=status,
            )
        if status != 200:
            raise PdfDownloadError("download_failed", f"HTTP {status}", status=status)
        content_type = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != PDF_CONTENT_TYPE:
            raise PdfDownloadError(
                "not_pdf",
                f"Content-Type is {content_type or 'missing'}, expected {PDF_CONTENT_TYPE}",
            )
        declared = (response.getheader("Content-Length") or "").strip()
        if declared.isdigit() and int(declared) > max_bytes:
            raise PdfDownloadError(
                "too_large", f"Content-Length {declared} exceeds the {max_bytes} byte limit"
            )
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise PdfDownloadError("too_large", f"response body exceeds the {max_bytes} byte limit")
        return body, content_type
    except PdfDownloadError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise PdfDownloadError(
            "download_failed", f"download failed ({type(exc).__name__})"
        ) from exc
    finally:
        connection.close()


def fetch_minute_frame(sina_symbol: str, period: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_a_minute(symbol=sina_symbol, period=period, adjust="")


def fetch_announcements_frame(
    symbol: str,
    market: str,
    category: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_a_disclosure_report_cninfo(
        symbol=symbol,
        market=market,
        category=category,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_tencent_text(sina_symbols: Sequence[str], timeout: float = 8.0) -> str:
    url = TENCENT_URL.format(symbols=",".join(sina_symbols))
    request = Request(url, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("gbk", errors="replace")


def fetch_sina_text(symbols: Sequence[str], timeout: float = 8.0, referer: str | None = SINA_REFERER) -> str:
    """GET hq.sinajs.cn/list=...; only this one host, Referer required by the upstream."""
    url = SINA_URL.format(symbols=",".join(symbols))
    if urlsplit(url).hostname != SINA_HOST:
        raise ValueError("sina fetch is restricted to hq.sinajs.cn")
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("gbk", errors="replace")


def fetch_bond_frame(start_date: str) -> pd.DataFrame:
    import akshare as ak

    return ak.bond_zh_us_rate(start_date=start_date)


def fetch_daily_frame(sina_symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_zh_a_daily(symbol=sina_symbol, start_date=start_date, end_date=end_date, adjust=adjust)
