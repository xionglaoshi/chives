from __future__ import annotations

import json

import pytest

from chives_data import config, schemas
from chives_data.envelope import authored_leaks
from chives_data.transport import (
    HostGovernor,
    HostNotAllowed,
    ResponseTooLarge,
    UpstreamError,
)
from fakes import FakeNewsSources, make_service, news_fixture, news_fixture_bytes


def _service() -> tuple:
    news = FakeNewsSources()
    news.stock_rows = news_fixture("stock_news_000528.json")
    news.flash_cls_rows = news_fixture("flash_cls.json")
    news.flash_em_rows = news_fixture("flash_em.json")
    news.calendar_rows = news_fixture("calendar_20261117.json")
    news.suspension_rows = news_fixture("suspensions_20261117.json")
    news.irm_rows = news_fixture("irm_000528.json")
    news.term_rows = news_fixture("cb_terms.json")
    news.remaining = {"118078": {"date": "2026-11-16", "size_yuan": 6_000_000_000.0}}
    news.announcement_rows = [
        {
            "date": "2026-11-17",
            "title": "公告",
            "category": None,
            "url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528",
        }
    ]
    news.announcement_total = 1
    news.pdf_bytes = news_fixture_bytes("announcement_small.pdf")
    return make_service(news_sources=news), news


def _calls() -> list[tuple[str, dict]]:
    return [
        ("news", {"kind": "stock", "code": "000528"}),
        ("news", {"kind": "flash"}),
        ("news", {"kind": "irm", "code": "000528"}),
        ("news", {"kind": "calendar", "date": "2026-11-17"}),
        ("news", {"kind": "suspensions", "date": "2026-11-17"}),
        ("company_announcements", {"code": "000528"}),
        ("company_announcements", {"url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528&announcementId=1225621247&orgId=gssz0000528&announcementTime=2026-10-24", "end_page": 1}),
        ("convertible_bonds", {"kind": "list", "limit": 3}),
        ("convertible_bonds", {"kind": "quote", "codes": ["127120"]}),
    ]


def _scan(value, *, in_url: bool = False, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, child in value.items():
            _scan(child, in_url=in_url or str(key).lower() == "url", found=found)
    elif isinstance(value, list):
        for child in value:
            _scan(child, in_url=in_url, found=found)
    elif isinstance(value, str) and not in_url:
        found.append(value)
    return found


def test_new_tools_emit_clean_contract_envelopes():
    service, _ = _service()
    for tool, args in _calls():
        payload = service.call(tool, args)
        assert set(payload) >= {"status", "as_of", "data", "stale"}, (tool, payload)
        assert payload["status"] in {"ok", "partial", "unavailable"}, (tool, payload)
        if payload["status"] == "unavailable":
            assert payload.get("message")
        assert not authored_leaks(json.dumps({k: payload.get(k) for k in ("basis", "missing", "message")}, ensure_ascii=False))
        keys = set()

        def walk(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    keys.add(str(key).lower())
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(payload)
        assert "source" not in keys


def test_empty_results_are_ok_not_errors():
    service, news = _service()
    news.stock_rows = []
    news.flash_cls_rows = []
    news.flash_em_rows = []
    news.irm_rows = []
    news.calendar_rows = []
    news.suspension_rows = []
    news.announcement_rows = []
    news.announcement_total = 0
    news.term_rows = []
    for tool, args in [
        ("news", {"kind": "stock", "code": "000528"}),
        ("news", {"kind": "flash"}),
        ("news", {"kind": "irm", "code": "000528"}),
        ("news", {"kind": "calendar", "date": "2026-11-17"}),
        ("news", {"kind": "suspensions", "date": "2026-11-17"}),
        ("company_announcements", {"code": "000528"}),
        ("convertible_bonds", {"kind": "list"}),
    ]:
        payload = service.call(tool, args)
        assert payload["status"] == "ok", (tool, payload)
        data = payload["data"]
        assert data.get("items", data.get("announcements", data.get("rows"))) == [], (tool, data)


def test_new_tool_descriptions_have_no_authored_leaks():
    names = {tool["name"] for tool in schemas.TOOLS}
    assert {"news", "company_announcements", "convertible_bonds"} <= names
    for tool in schemas.TOOLS[-3:]:
        assert not authored_leaks(tool["description"]), tool["name"]


def test_url_fields_are_the_only_scan_exception():
    payload = {
        "data": {
            "items": [
                {"url": "http://allowed.example/a", "summary": "正文里出现 http://bad.example"},
            ]
        }
    }
    texts = _scan(payload)
    assert "http://allowed.example/a" not in texts
    assert any("http://bad.example" in text for text in texts)


def _governor(fetch):
    return HostGovernor(
        clock=lambda: 1000.0,
        sleep=lambda _s: None,
        bytes_fetch_fn=fetch,
    )


def test_request_bytes_returns_body_and_counts_health():
    governor = _governor(lambda url, headers, timeout, max_bytes: (200, {"Content-Type": "application/pdf"}, b"%PDF-1.7"))
    status, headers, body = governor.request_bytes("static.cninfo.com.cn", "/finalpage/2026-10-24/1.PDF", max_bytes=100)
    assert status == 200
    assert headers["Content-Type"] == "application/pdf"
    assert body.startswith(b"%PDF-")
    assert governor.health(1000.0)["upstreams"]["static.cninfo.com.cn"]["requests_total"] == 1


def test_request_bytes_rejects_oversize_and_foreign_hosts():
    governor = _governor(lambda url, headers, timeout, max_bytes: (200, {}, b"x" * 101))
    with pytest.raises(ResponseTooLarge):
        governor.request_bytes("static.cninfo.com.cn", "/a.PDF", max_bytes=100)
    with pytest.raises(HostNotAllowed):
        governor.request_bytes("evil.example", "/a.PDF")


def test_request_bytes_propagates_redirect_refusal():
    def fetch(url, headers, timeout, max_bytes):
        raise UpstreamError("redirect_refused", circuit=False)

    governor = _governor(fetch)
    with pytest.raises(UpstreamError) as excinfo:
        governor.request_bytes("static.cninfo.com.cn", "/a.PDF")
    assert excinfo.value.code == "redirect_refused"
