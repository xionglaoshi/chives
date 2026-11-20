"""cninfo announcement URL allowlist and PDF text extraction."""

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
PDF_URL_TEMPLATE = "http://static.cninfo.com.cn/finalpage/{day}/{announcement_id}.PDF"

PDFTOTEXT_ENV = "CN_EXTRA_PDFTOTEXT"
MIN_CHARS_PER_PAGE = 30
DEFAULT_MAX_CHARS = 20_000
MIN_MAX_CHARS = 500
MAX_MAX_CHARS = 200_000

_PDF_PATH_RE = re.compile(
    r"^/finalpage/(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})/(?P<announcement_id>[0-9]+)\.(?i:pdf)$"
)
_ID_RE = re.compile(r"^[0-9]+$")
_DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_UNSAFE_RE = re.compile(r"[\s\\\x00-\x1f\x7f]")


class InvalidAnnouncementUrl(ValueError):
    """The URL is not one of the two whitelisted cninfo forms."""


class PdfExtractionError(Exception):
    """Text extraction failure carrying the envelope error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PdfText:
    text: str
    pages_total: int
    pages_returned: list[int]


def _require_day(value: str) -> str:
    if not _DAY_RE.match(value):
        raise InvalidAnnouncementUrl("announcementTime must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidAnnouncementUrl("announcementTime is not a real calendar date") from exc
    return value


def _detail_pdf_url(query: str) -> str:
    params = parse_qs(query, keep_blank_values=True)
    ids = params.get("announcementId", [])
    days = params.get("announcementTime", [])
    if len(ids) != 1 or not _ID_RE.match(ids[0]):
        raise InvalidAnnouncementUrl("detail URL must carry exactly one numeric announcementId")
    if len(days) != 1:
        raise InvalidAnnouncementUrl("detail URL must carry exactly one announcementTime")
    day = _require_day(days[0])
    return PDF_URL_TEMPLATE.format(day=day, announcement_id=ids[0])


def resolve_pdf_url(url: object) -> str:
    """Return the canonical cninfo PDF URL for a whitelisted detail page or PDF link."""
    if not isinstance(url, str) or not url:
        raise InvalidAnnouncementUrl("url must be a non-empty string")
    if url != url.strip() or _UNSAFE_RE.search(url):
        raise InvalidAnnouncementUrl("url must not contain whitespace or control characters")

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidAnnouncementUrl("url scheme must be http or https")
    if parts.fragment:
        raise InvalidAnnouncementUrl("url must not contain a fragment")
    if parts.username is not None or parts.password is not None:
        raise InvalidAnnouncementUrl("url must not contain userinfo")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidAnnouncementUrl("url has an invalid port") from exc
    default_port = 443 if parts.scheme == "https" else 80
    if port is not None and port != default_port:
        raise InvalidAnnouncementUrl("url must use the default port")
    if "\\" in parts.netloc:
        raise InvalidAnnouncementUrl("url must not contain backslashes")

    host = parts.hostname
    path = unquote(parts.path)
    if ".." in path:
        raise InvalidAnnouncementUrl("url path must not contain '..'")

    if host == DETAIL_HOST:
        if path != DETAIL_PATH:
            raise InvalidAnnouncementUrl(f"detail pages must use the path {DETAIL_PATH}")
        return _detail_pdf_url(parts.query)
    if host == PDF_HOST:
        if parts.query or parts.fragment:
            raise InvalidAnnouncementUrl("PDF links must not carry a query or fragment")
        match = _PDF_PATH_RE.match(path)
        if match is None:
            raise InvalidAnnouncementUrl("PDF links must look like /finalpage/YYYY-MM-DD/<id>.PDF")
        day = _require_day(match.group("day"))
        return PDF_URL_TEMPLATE.format(day=day, announcement_id=match.group("announcement_id"))
    raise InvalidAnnouncementUrl("host is not an allowed cninfo host")


def pdftotext_path() -> str | None:
    override = os.environ.get(PDFTOTEXT_ENV)
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        return None
    return shutil.which("pdftotext")


def _run(argv: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PdfExtractionError(
            "pdftotext_not_found", "pdftotext is not installed; please brew install poppler"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PdfExtractionError("extraction_failed", "pdftotext timed out") from exc


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
        raise PdfExtractionError("extraction_failed", "could not determine the PDF page count")
    pages = len(re.findall(rb"<page\b", result.stdout))
    if pages < 1:
        raise PdfExtractionError("extraction_failed", "could not determine the PDF page count")
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
) -> PdfText:
    """Extract text with pdftotext; temporary files live in the system temp dir."""
    with tempfile.TemporaryDirectory(prefix="cn-extra-pdf-") as tmp:
        pdf_path = Path(tmp) / "announcement.pdf"
        pdf_path.write_bytes(pdf)
        total = _page_count(pdf_path, executable)
        if total < 1:
            raise PdfExtractionError("extraction_failed", "PDF reports no pages")
        last = total if end_page is None else end_page
        if start_page > total or last > total:
            raise PdfExtractionError(
                "invalid_argument",
                f"page range {start_page}-{last} is outside the document (1-{total})",
            )
        result = _run(pdftotext_argv(executable, pdf_path, start_page, last, layout))
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise PdfExtractionError(
                "extraction_failed", f"pdftotext failed ({detail[:200] or 'no stderr'})"
            )
        text = result.stdout.decode("utf-8", errors="replace")

    pages = last - start_page + 1
    if len(text.strip()) / pages < MIN_CHARS_PER_PAGE:
        raise PdfExtractionError(
            "no_text_layer",
            "the PDF has too little extractable text (probably a scan); OCR is not supported",
        )
    return PdfText(text=text, pages_total=total, pages_returned=[start_page, last])
