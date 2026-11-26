"""Announcement URL allowlist and PDF text extraction (ported from cn-extra-mcp)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

DETAIL_HOST = "www.cninfo.com.cn"
DETAIL_PATH = "/new/disclosure/detail"
PDF_HOST = "static.cninfo.com.cn"
PDF_URL_TEMPLATE = "https://static.cninfo.com.cn/finalpage/{day}/{announcement_id}.PDF"

PDFTOTEXT_ENV = "CN_MARKET_GATEWAY_PDFTOTEXT"
MIN_CHARS_PER_PAGE = 30
DEFAULT_MAX_CHARS = 20_000
MIN_MAX_CHARS = 500
MAX_MAX_CHARS = 200_000
MAX_PDF_BYTES = 25 * 1024 * 1024
PDF_TIMEOUT = 25.0
PDFTOTEXT_TIMEOUT = 30.0

_PDF_PATH_RE = re.compile(
    r"^/finalpage/(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})/(?P<announcement_id>[0-9]+)\.(?i:pdf)$"
)
_ID_RE = re.compile(r"^[0-9]+$")
_DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_UNSAFE_RE = re.compile(r"[\s\\\x00-\x1f\x7f]")


class InvalidAnnouncementUrl(ValueError):
    """The URL is not one of the two whitelisted announcement forms."""


class PdfExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PdfText:
    text: str
    pages_total: int
    pages_returned: list[int]
    truncated: bool


def _require_day(value: str) -> str:
    if not _DAY_RE.match(value):
        raise InvalidAnnouncementUrl("公告日期必须是 YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidAnnouncementUrl("公告日期不是真实日期") from exc
    return value


def _detail_pdf_url(query: str) -> str:
    params = parse_qs(query, keep_blank_values=True)
    ids = params.get("announcementId", [])
    days = params.get("announcementTime", [])
    if len(ids) != 1 or not _ID_RE.match(ids[0]):
        raise InvalidAnnouncementUrl("详情页链接必须带一个数字型 announcementId")
    if len(days) != 1:
        raise InvalidAnnouncementUrl("详情页链接必须带一个 announcementTime")
    day = _require_day(days[0][:10])
    return PDF_URL_TEMPLATE.format(day=day, announcement_id=ids[0])


def resolve_pdf_url(url: object) -> str:
    """Return the canonical PDF URL for a whitelisted detail page or PDF link."""
    if not isinstance(url, str) or not url:
        raise InvalidAnnouncementUrl("url 必须是非空字符串")
    if url != url.strip() or _UNSAFE_RE.search(url):
        raise InvalidAnnouncementUrl("url 不能包含空白或控制字符")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidAnnouncementUrl("url 只接受网页链接（file:// 等协议一律拒绝）")
    if parts.fragment:
        raise InvalidAnnouncementUrl("url 不能带 fragment")
    if parts.username is not None or parts.password is not None:
        raise InvalidAnnouncementUrl("url 不能带用户名或密码")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidAnnouncementUrl("url 的端口不合法") from exc
    default_port = 443 if parts.scheme == "https" else 80
    if port is not None and port != default_port:
        raise InvalidAnnouncementUrl("url 必须使用默认端口")
    if "\\" in parts.netloc:
        raise InvalidAnnouncementUrl("url 不能包含反斜杠")

    host = parts.hostname
    path = unquote(parts.path)
    if ".." in path:
        raise InvalidAnnouncementUrl("url 路径不能包含 ..")
    if host == DETAIL_HOST:
        if path != DETAIL_PATH:
            raise InvalidAnnouncementUrl(f"详情页必须是 {DETAIL_PATH} 路径")
        return _detail_pdf_url(parts.query)
    if host == PDF_HOST:
        if parts.query:
            raise InvalidAnnouncementUrl("PDF 链接不能带 query")
        match = _PDF_PATH_RE.match(path)
        if match is None:
            raise InvalidAnnouncementUrl("PDF 链接必须形如 /finalpage/YYYY-MM-DD/<数字>.PDF")
        day = _require_day(match.group("day"))
        return PDF_URL_TEMPLATE.format(day=day, announcement_id=match.group("announcement_id"))
    raise InvalidAnnouncementUrl("只接受公告站点的详情页或 PDF 链接")


def pdftotext_path() -> str | None:
    override = os.environ.get(PDFTOTEXT_ENV)
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        return None
    return shutil.which("pdftotext")


def _run(argv: list[str], timeout: float = PDFTOTEXT_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PdfExtractionError("pdftotext_not_found", "系统没有安装 pdftotext，无法读取公告原文") from exc
    except subprocess.TimeoutExpired as exc:
        raise PdfExtractionError("extraction_failed", "提取公告原文超时") from exc


def _page_count(pdf_path: Path, executable: str) -> int:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        result = _run([pdfinfo, str(pdf_path)])
        if result.returncode == 0:
            match = re.search(rb"^Pages:\s*(\d+)", result.stdout, re.MULTILINE)
            if match is not None:
                return int(match.group(1))
    result = _run([executable, "-bbox", str(pdf_path), "-"])
    if result.returncode != 0:
        raise PdfExtractionError("extraction_failed", "无法确定公告 PDF 的页数")
    pages = len(re.findall(rb"<page\b", result.stdout))
    if pages < 1:
        raise PdfExtractionError("extraction_failed", "无法确定公告 PDF 的页数")
    return pages


def pdftotext_argv(
    executable: str, pdf_path: Path, start_page: int, end_page: int, layout: bool
) -> list[str]:
    argv = [executable, "-enc", "UTF-8"]
    if layout:
        argv.append("-layout")
    argv.extend(["-f", str(start_page), "-l", str(end_page), str(pdf_path), "-"])
    return argv


def extract_pdf_text(
    pdf: bytes,
    *,
    executable: str,
    start_page: int = 1,
    end_page: int | None = None,
    layout: bool = True,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> PdfText:
    """Extract text with pdftotext (argv, never a shell); temp files stay in the system temp dir."""
    with tempfile.TemporaryDirectory(prefix="cn-market-pdf-") as tmp:
        pdf_path = Path(tmp) / "announcement.pdf"
        pdf_path.write_bytes(pdf)
        total = _page_count(pdf_path, executable)
        if total < 1:
            raise PdfExtractionError("extraction_failed", "公告 PDF 没有页")
        last = total if end_page is None else end_page
        if start_page > total or last > total:
            raise PdfExtractionError(
                "invalid_argument", f"页码 {start_page}-{last} 超出文档范围（共 {total} 页）"
            )
        result = _run(pdftotext_argv(executable, pdf_path, start_page, last, layout))
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise PdfExtractionError("extraction_failed", f"提取公告原文失败（{detail[:200] or '无错误输出'}）")
        raw = result.stdout.decode("utf-8", errors="replace")

    pages = last - start_page + 1
    if len(raw.strip()) / pages < MIN_CHARS_PER_PAGE:
        raise PdfExtractionError("no_text_layer", "该公告 PDF 没有可提取的文字层（可能是扫描件），不支持 OCR")
    truncated = len(raw) > max_chars
    return PdfText(
        text=raw[:max_chars] if truncated else raw,
        pages_total=total,
        pages_returned=[start_page, last],
        truncated=truncated,
    )
