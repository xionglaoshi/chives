from __future__ import annotations

from pathlib import Path

import pytest

from cn_extra_mcp import announcement, service, sources
from pdf_fixtures import build_pdf

DETAIL = (
    "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=002553"
    "&announcementId=1225619566&orgId=9900018065&announcementTime=2026-10-26"
)
DETAIL_HTTPS = (
    "https://www.cninfo.com.cn/new/disclosure/detail?announcementTime=2026-10-26"
    "&announcementId=1225619566"
)
DIRECT = "http://static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF"

BAD_URLS = [
    "file:///etc/passwd",
    "https://example.com/a.pdf",
    "http://static.cninfo.com.cn.evil.com/finalpage/2026-10-26/1225619566.PDF",
    "http://user:pw@static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF",
    "http://static.cninfo.com.cn/finalpage/../x.PDF",
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8865/health",
    "http://localhost/x.pdf",
    "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=002553",
    "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=abc&announcementTime=2026-10-26",
    "http://www.cninfo.com.cn/other/page?announcementId=1&announcementTime=2026-10-26",
    "ftp://static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF",
    "http://static.cninfo.com.cn/finalpage/2026-10-26/abc.PDF",
    "",
    "not a url",
    "http://[::1]/x.pdf",
    "http://static.cninfo.com.cn:8080/finalpage/2026-10-26/1225619566.PDF",
    "http://static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF?x=1",
    "http://static.cninfo.com.cn/finalpage/2026-13-40/1225619566.PDF",
    "http://static.cninfo.com.cn/finalpage/%2e%2e/x.PDF",
    "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=1&announcementId=2&announcementTime=2026-10-26",
    "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=1&announcementTime=2026-10-26#frag",
    "//static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF",
    "javascript:alert(1)",
    " http://static.cninfo.com.cn/finalpage/2026-10-26/1225619566.PDF",
]


def two_page_pdf() -> bytes:
    return build_pdf(["PAGE ONE " * 8, "PAGE TWO " * 8])


def long_pdf() -> bytes:
    lines = "\n".join(f"LINE {index:03d} " + "x" * 20 for index in range(40))
    return build_pdf([lines])


@pytest.fixture
def downloaded(monkeypatch):
    calls: list[str] = []
    payload = {"body": two_page_pdf(), "content_type": "application/pdf"}

    def fake(url: str, **kwargs):
        calls.append(url)
        return payload["body"], payload["content_type"]

    monkeypatch.setattr(service.sources, "fetch_pdf_bytes", fake)
    return calls, payload


def test_detail_url_is_reconstructed_to_pdf() -> None:
    assert announcement.resolve_pdf_url(DETAIL) == DIRECT
    assert announcement.resolve_pdf_url(DETAIL_HTTPS) == DIRECT


def test_direct_pdf_url_is_normalised() -> None:
    assert announcement.resolve_pdf_url(DIRECT) == DIRECT
    assert (
        announcement.resolve_pdf_url("https://static.cninfo.com.cn/finalpage/2026-10-26/1.pdf")
        == "http://static.cninfo.com.cn/finalpage/2026-10-26/1.PDF"
    )


@pytest.mark.parametrize("url", BAD_URLS)
def test_invalid_urls_never_download(url, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched for an invalid URL")

    monkeypatch.setattr(service.sources, "fetch_pdf_bytes", boom)
    payload = service.cn_read_announcement(url)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_url"


def test_reads_detail_url(downloaded) -> None:
    calls, _ = downloaded
    payload = service.cn_read_announcement(DETAIL)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["source"] == service.ANNOUNCEMENT_PDF_SOURCE
    data = payload["data"]
    assert data["url"] == DETAIL
    assert data["pdf_url"] == DIRECT
    assert data["pages_total"] == 2
    assert data["pages_returned"] == [1, 2]
    assert "PAGE ONE" in data["text"]
    assert "PAGE TWO" in data["text"]
    assert data["chars"] == len(data["text"])
    assert data["truncated"] is False
    assert data["untrusted_text"] is True
    assert calls == [DIRECT]


def test_reads_direct_url(downloaded) -> None:
    calls, _ = downloaded
    payload = service.cn_read_announcement(DIRECT)
    assert payload["ok"] is True
    assert payload["data"]["pdf_url"] == DIRECT
    assert calls == [DIRECT]


def test_page_range_selection(downloaded) -> None:
    payload = service.cn_read_announcement(DETAIL, start_page=2)
    data = payload["data"]
    assert data["pages_returned"] == [2, 2]
    assert "PAGE TWO" in data["text"]
    assert "PAGE ONE" not in data["text"]


def test_end_page_equal_to_total_is_fine(downloaded) -> None:
    payload = service.cn_read_announcement(DETAIL, start_page=1, end_page=2)
    assert payload["ok"] is True
    assert payload["data"]["pages_returned"] == [1, 2]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_page": 0},
        {"start_page": -1},
        {"start_page": 3, "end_page": 2},
        {"start_page": 3},
        {"end_page": 3},
        {"start_page": "1"},
        {"start_page": 1.0},
        {"start_page": True},
        {"end_page": False},
    ],
)
def test_invalid_page_arguments(downloaded, kwargs) -> None:
    payload = service.cn_read_announcement(DETAIL, **kwargs)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize("max_chars", [100, 300000, 499, 200001, True, "500", 500.5])
def test_invalid_max_chars(downloaded, max_chars) -> None:
    payload = service.cn_read_announcement(DETAIL, max_chars=max_chars)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"


def test_max_chars_bounds_are_accepted(downloaded) -> None:
    _, payload = downloaded
    payload["body"] = long_pdf()
    low = service.cn_read_announcement(DETAIL, max_chars=500)
    assert low["data"]["truncated"] is True
    assert len(low["data"]["text"]) == 500
    assert low["data"]["chars"] == 500
    high = service.cn_read_announcement(DETAIL, max_chars=200000)
    assert high["ok"] is True
    assert high["data"]["truncated"] is False


def test_truncation_keeps_prefix(downloaded) -> None:
    _, payload = downloaded
    payload["body"] = long_pdf()
    full = service.cn_read_announcement(DETAIL, max_chars=200000)["data"]["text"]
    cut = service.cn_read_announcement(DETAIL, max_chars=600)["data"]["text"]
    assert cut == full[:600]
    assert len(cut) == 600


def test_not_pdf_body(downloaded) -> None:
    _, payload = downloaded
    payload["body"] = b"<html>not a pdf</html>"
    result = service.cn_read_announcement(DETAIL)
    assert result["ok"] is False
    assert result["error"]["code"] == "not_pdf"


def test_too_large_body(downloaded, monkeypatch) -> None:
    _, payload = downloaded
    monkeypatch.setattr(service.sources, "MAX_PDF_BYTES", 1024)
    payload["body"] = b"%PDF-" + b"0" * 1025
    result = service.cn_read_announcement(DETAIL)
    assert result["ok"] is False
    assert result["error"]["code"] == "too_large"


def test_no_text_layer(monkeypatch, downloaded) -> None:
    _, payload = downloaded
    payload["body"] = build_pdf(["x"])
    result = service.cn_read_announcement(DETAIL)
    assert result["ok"] is False
    assert result["error"]["code"] == "no_text_layer"


def test_pdftotext_not_found(monkeypatch) -> None:
    monkeypatch.setenv(announcement.PDFTOTEXT_ENV, "/nonexistent/pdftotext")

    def boom(*args, **kwargs):
        raise AssertionError("must not download without pdftotext")

    monkeypatch.setattr(service.sources, "fetch_pdf_bytes", boom)
    result = service.cn_read_announcement(DETAIL)
    assert result["ok"] is False
    assert result["error"]["code"] == "pdftotext_not_found"
    assert "brew install poppler" in result["error"]["message"]


def test_layout_flag_in_argv() -> None:
    with_layout = announcement.pdftotext_argv(
        "/opt/homebrew/bin/pdftotext", Path("/tmp/x.pdf"), 1, 2, True
    )
    without_layout = announcement.pdftotext_argv(
        "/opt/homebrew/bin/pdftotext", Path("/tmp/x.pdf"), 1, 2, False
    )
    assert "-layout" in with_layout
    assert "-layout" not in without_layout
    assert without_layout[without_layout.index("-f") + 1] == "1"
    assert without_layout[without_layout.index("-l") + 1] == "2"


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status = status
        self._headers = headers
        self._body = body

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)

    def read(self, amount: int = -1) -> bytes:
        return self._body if amount < 0 else self._body[:amount]


class _FakeConnection:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str]] = []
        self.closed = False

    def request(self, method: str, target: str, headers: dict | None = None) -> None:
        self.requests.append((method, target))

    def getresponse(self) -> _FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_redirect_is_not_followed(monkeypatch) -> None:
    connection = _FakeConnection(
        _FakeResponse(302, {"Location": "http://static.cninfo.com.cn.evil.com/x.PDF"})
    )
    monkeypatch.setattr(sources, "_pdf_connection", lambda parts, timeout: connection)
    with pytest.raises(sources.PdfDownloadError) as info:
        sources.fetch_pdf_bytes(DIRECT)
    assert info.value.code == "download_failed"
    assert info.value.status == 302
    assert len(connection.requests) == 1
    assert connection.closed is True


def test_download_rejects_html_content_type(monkeypatch) -> None:
    connection = _FakeConnection(
        _FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"}, b"<html></html>")
    )
    monkeypatch.setattr(sources, "_pdf_connection", lambda parts, timeout: connection)
    with pytest.raises(sources.PdfDownloadError) as info:
        sources.fetch_pdf_bytes(DIRECT)
    assert info.value.code == "not_pdf"


def test_download_rejects_declared_oversize(monkeypatch) -> None:
    connection = _FakeConnection(
        _FakeResponse(
            200,
            {"Content-Type": "application/pdf", "Content-Length": "4096"},
            b"%PDF-" + b"0" * 4090,
        )
    )
    monkeypatch.setattr(sources, "_pdf_connection", lambda parts, timeout: connection)
    with pytest.raises(sources.PdfDownloadError) as info:
        sources.fetch_pdf_bytes(DIRECT, max_bytes=1024)
    assert info.value.code == "too_large"


def test_download_rejects_streamed_oversize(monkeypatch) -> None:
    connection = _FakeConnection(
        _FakeResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-" + b"0" * 2000)
    )
    monkeypatch.setattr(sources, "_pdf_connection", lambda parts, timeout: connection)
    with pytest.raises(sources.PdfDownloadError) as info:
        sources.fetch_pdf_bytes(DIRECT, max_bytes=1024)
    assert info.value.code == "too_large"


def test_download_failure_has_status(monkeypatch) -> None:
    connection = _FakeConnection(_FakeResponse(404, {}))
    monkeypatch.setattr(sources, "_pdf_connection", lambda parts, timeout: connection)
    with pytest.raises(sources.PdfDownloadError) as info:
        sources.fetch_pdf_bytes(DIRECT)
    assert info.value.code == "download_failed"
    assert info.value.status == 404
