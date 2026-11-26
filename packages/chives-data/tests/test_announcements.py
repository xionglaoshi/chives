from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from chives_data import announcement as pdfmod
from chives_data import config
from chives_data.news_sources import NewsSources
from chives_data.transport import UpstreamError
from fakes import FakeNewsSources, make_service, news_fixture, news_fixture_bytes


class _Governor:
    def __init__(self, org_payload: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        self.org_payload = org_payload
        self.pages = pages
        self.forms: list[dict[str, Any]] = []

    def request(self, host, path, *, params=None, headers=None, encoding="utf-8"):
        return json.dumps(self.org_payload)

    def request_form(self, host, path, *, form, params=None, headers=None, encoding="utf-8"):
        self.forms.append(dict(form))
        page = int(form["pageNum"])
        return json.dumps(self.pages[page - 1])


def _raw_announcement() -> dict[str, Any]:
    rows = news_fixture("announcements_000528.json")["announcements"]
    return next(row for row in rows if row["announcementId"] == "1225621247")


def _detail_url() -> str:
    row = _raw_announcement()
    item = NewsSources._announcement_item(row, "")
    assert item is not None
    return item["url"]


def _service() -> tuple:
    news = FakeNewsSources()
    news.announcement_total = 3
    news.announcement_rows = [
        {
            "date": "2026-11-17",
            "title": "关于召开2026年第四次临时股东会的提示性公告",
            "category": None,
            "url": _detail_url(),
        },
        {
            "date": "2026-11-14",
            "title": "关于2026年限制性股票激励计划内幕信息知情人买卖公司股票情况的自查报告",
            "category": None,
            "url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528&announcementId=1225671389&orgId=gssz0000528&announcementTime=2026-11-14 00:00:00",
        },
    ]
    news.pdf_bytes = news_fixture_bytes("announcement_small.pdf")
    return make_service(news_sources=news), news


def test_announcement_item_parses_recorded_row():
    item = NewsSources._announcement_item(_raw_announcement(), "")
    assert item is not None
    assert item["date"] == "2026-10-24"
    assert item["category"] is None
    assert item["url"].startswith("http://www.cninfo.com.cn/new/disclosure/detail?")
    assert "announcementTime=2026-10-24+00%3A00%3A00" in item["url"]


def test_announcements_pagination_uses_recorded_pages():
    raw = news_fixture("announcements_000528.json")
    org = {"stockList": [{"code": "000528", "orgId": "gssz0000528"}]}
    governor = _Governor(org, [raw, {"totalAnnouncement": raw["totalAnnouncement"], "announcements": []}])
    sources = NewsSources(governor)  # type: ignore[arg-type]
    name, rows, total = sources.announcements(
        "000528", category="", start=date(2026, 10, 18), end=date(2026, 11, 17), limit=30, offset=0
    )
    assert total == 25
    assert name == "柳 工"
    assert len(rows) == 25
    assert governor.forms[0]["stock"] == "000528,gssz0000528"
    assert governor.forms[0]["seDate"] == "2026-10-18~2026-11-17"


def test_announcements_search_and_empty():
    service, _ = _service()
    payload = service.call("company_announcements", {"code": "000528", "start": "2026-10-18", "end": "2026-11-17", "limit": 2})
    assert payload["status"] == "ok"
    assert payload["data"]["count"] == 3
    assert payload["data"]["truncated"] is True
    assert payload["data"]["untrusted_text"] is True
    assert payload["data"]["announcements"][0]["category"] is None
    assert payload["basis"][0]["field"] == "category"

    service, news = _service()
    news.announcement_rows = []
    news.announcement_total = 0
    payload = service.call("company_announcements", {"code": "000528"})
    assert payload["status"] == "ok"
    assert payload["data"]["announcements"] == []


def test_announcements_failure_and_arguments():
    service, news = _service()
    news.error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("company_announcements", {"code": "000528"})
    assert payload["status"] == "unavailable"
    assert "公告" in payload["message"]

    service, _ = _service()
    for args in (
        {},
        {"code": "000528", "start": "2026-11-18", "end": "2026-11-17"},
        {"code": "000528", "category": "不存在的类别"},
        {"code": "000528", "limit": 0},
        {"code": "000300.SH"},
    ):
        payload = service.call("company_announcements", args)
        assert payload["status"] == "unavailable", args


def test_read_announcement_from_recorded_pdf():
    service, _ = _service()
    payload = service.call("company_announcements", {"url": _detail_url(), "end_page": 1, "max_chars": 5000})
    assert payload["status"] == "ok", payload
    assert payload["data"]["pages_total"] >= 1
    assert payload["data"]["pages_returned"] == [1, 1]
    assert payload["data"]["untrusted_text"] is True
    assert payload["data"]["chars"] <= 5000
    assert "独立董事" in payload["data"]["text"]
    assert "pdf_url" not in payload["data"]


def test_read_announcement_truncates_and_rejects_bad_pages():
    service, _ = _service()
    payload = service.call("company_announcements", {"url": _detail_url(), "end_page": 1, "max_chars": 500})
    assert payload["status"] == "ok"
    assert payload["data"]["truncated"] is True
    assert payload["data"]["chars"] == 500

    bad = service.call("company_announcements", {"url": _detail_url(), "start_page": 9999})
    assert bad["status"] == "unavailable"
    assert "页码" in bad["message"]


def test_read_announcement_without_pdftotext(monkeypatch):
    service, _ = _service()
    monkeypatch.setattr(pdfmod, "pdftotext_path", lambda: None)
    payload = service.call("company_announcements", {"url": _detail_url()})
    assert payload["status"] == "unavailable"
    assert "pdftotext" in payload["message"]
    assert "poppler" in payload["message"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a.pdf",
        "https://example.invalid/a.pdf",
        "https://static.cninfo.com.cn/finalpage/2026-10-24/1225621247.PDF?x=1",
        "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528",
        "https://static.cninfo.com.cn/finalpage/../2026-10-24/1225621247.PDF",
        "https://user:pass@static.cninfo.com.cn/finalpage/2026-10-24/1225621247.PDF",
    ],
)
def test_announcement_url_whitelist_rejects(url):
    service, _ = _service()
    payload = service.call("company_announcements", {"url": url})
    assert payload["status"] == "unavailable"
    assert payload["message"]


def test_read_announcement_refuses_redirect():
    service, news = _service()

    def redirect(pdf_url):
        raise UpstreamError("redirect_refused", circuit=False)

    news.download_pdf = redirect  # type: ignore[method-assign]
    payload = service.call("company_announcements", {"url": _detail_url()})
    assert payload["status"] == "unavailable"
    assert "跳转" in payload["message"]


def test_announcement_payload_has_no_http_outside_url():
    service, _ = _service()
    payload = service.call("company_announcements", {"code": "000528"})
    strings = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() == "url":
                    continue
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            strings.append(value)

    walk(payload.get("data"))
    text = " ".join(strings).lower()
    assert "http" not in text
    for word in config.FORBIDDEN_OUTPUT:
        assert word.lower() not in text, word


def _pdf_governor(status=200, headers=None, body=b"%PDF-1.7"):
    class _G:
        def request_bytes(self, host, path, **kwargs):
            return status, headers or {"Content-Type": "application/pdf"}, body

    return _G()


def test_download_pdf_accepts_pdf_and_rejects_wrong_type():
    sources = NewsSources(_pdf_governor())  # type: ignore[arg-type]
    assert sources.download_pdf("https://static.cninfo.com.cn/finalpage/2026-10-24/1.PDF") == b"%PDF-1.7"

    bad = NewsSources(_pdf_governor(headers={"Content-Type": "text/html"}, body=b"<html>"))  # type: ignore[arg-type]
    with pytest.raises(pdfmod.PdfExtractionError) as excinfo:
        bad.download_pdf("https://static.cninfo.com.cn/finalpage/2026-10-24/1.PDF")
    assert excinfo.value.code == "not_pdf"

    failed = NewsSources(_pdf_governor(status=500))  # type: ignore[arg-type]
    with pytest.raises(pdfmod.PdfExtractionError) as excinfo:
        failed.download_pdf("https://static.cninfo.com.cn/finalpage/2026-10-24/1.PDF")
    assert excinfo.value.code == "download_failed"


def test_static_pdf_url_is_accepted():
    resolved = pdfmod.resolve_pdf_url(
        "https://static.cninfo.com.cn/finalpage/2026-10-24/1225621247.PDF"
    )
    assert resolved == "https://static.cninfo.com.cn/finalpage/2026-10-24/1225621247.PDF"


class _PagedGovernor(_Governor):
    def request_form(self, host, path, *, form, params=None, headers=None, encoding="utf-8"):
        self.forms.append(dict(form))
        return json.dumps(self.pages[int(form["pageNum"]) - 1])


def _raw_page(start: int, count: int) -> dict[str, Any]:
    rows = []
    for index in range(start, start + count):
        rows.append(
            {
                "announcementTitle": f"公告 {index}",
                "announcementTime": 1762000000000 + index * 60_000,
                "secCode": "000528",
                "secName": "柳工",
                "announcementId": str(1225600000 + index),
                "orgId": "gssz0000528",
            }
        )
    return {"totalAnnouncement": 120, "announcements": rows}


def test_announcement_offset_jumps_to_the_upstream_page():
    org = {"stockList": [{"code": "000528", "orgId": "gssz0000528"}]}
    governor = _PagedGovernor(org, [_raw_page(0, 30), _raw_page(30, 30), _raw_page(60, 30), _raw_page(90, 30)])
    sources = NewsSources(governor)  # type: ignore[arg-type]
    name, rows, total = sources.announcements(
        "000528", category="", start=date(2026, 10, 18), end=date(2026, 11, 17), limit=5, offset=35
    )
    assert name == "柳工"
    assert total == 120
    assert [row["title"] for row in rows] == ["公告 35", "公告 36", "公告 37", "公告 38", "公告 39"]
    assert [form["pageNum"] for form in governor.forms] == ["2"]


def test_announcement_offset_and_next_offset_in_the_envelope():
    service, news = _service()
    news.announcement_total = 12
    news.announcement_rows = [
        {"date": "2026-11-17", "title": f"公告 {index}", "category": None,
         "url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528&announcementId=1&orgId=x&announcementTime=2026-11-17 00:00:00"}
        for index in range(12)
    ]
    payload = service.call(
        "company_announcements",
        {"code": "000528", "start": "2026-10-18", "end": "2026-11-17", "limit": 5, "offset": 5},
    )
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["total"] == 12
    assert data["offset"] == 5
    assert data["returned"] == 5
    assert data["next_offset"] == 10
    assert data["truncated"] is True
    assert data["announcements"][0]["title"] == "公告 5"

    last = service.call(
        "company_announcements",
        {"code": "000528", "start": "2026-10-18", "end": "2026-11-17", "limit": 5, "offset": 10},
    )
    assert last["data"]["returned"] == 2
    assert last["data"]["next_offset"] is None
    assert last["data"]["truncated"] is False

    beyond = service.call(
        "company_announcements",
        {"code": "000528", "start": "2026-10-18", "end": "2026-11-17", "limit": 5, "offset": 20},
    )
    assert beyond["status"] == "ok"
    assert beyond["data"]["announcements"] == []
    assert beyond["data"]["total"] == 12
    assert beyond["data"]["next_offset"] is None


def test_announcement_offset_rejects_bad_values_and_url_mode():
    service, _ = _service()
    for args in (
        {"code": "000528", "offset": -1},
        {"code": "000528", "offset": 10001},
        {"code": "000528", "offset": "1"},
        {"url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528&announcementId=1&orgId=x&announcementTime=2026-11-17 00:00:00", "offset": 1},
    ):
        payload = service.call("company_announcements", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]


def test_announcement_offset_beyond_total_returns_empty_after_one_request():
    org = {"stockList": [{"code": "000528", "orgId": "gssz0000528"}]}
    page = _raw_page(0, 25)
    page["totalAnnouncement"] = 25
    governor = _PagedGovernor(org, [page, page])
    sources = NewsSources(governor)  # type: ignore[arg-type]
    name, rows, total = sources.announcements(
        "000528", category="", start=date(2026, 10, 18), end=date(2026, 11, 17), limit=5, offset=40
    )
    assert rows == []
    assert total == 25
    assert [form["pageNum"] for form in governor.forms] == ["2"]
