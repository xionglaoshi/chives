from __future__ import annotations

import json

import pytest

from cn_market_gateway import config
from cn_market_gateway.envelope import authored_leaks
from cn_market_gateway.transport import UpstreamError
from fakes import FakeNewsSources, make_service, news_fixture


def _service() -> tuple:
    news = FakeNewsSources()
    news.stock_rows = news_fixture("stock_news_000528.json")
    news.flash_cls_rows = news_fixture("flash_cls.json")
    news.flash_em_rows = news_fixture("flash_em.json")
    news.calendar_rows = news_fixture("calendar_20261117.json")
    news.suspension_rows = news_fixture("suspensions_20261117.json")
    news.irm_rows = news_fixture("irm_000528.json")
    service = make_service(news_sources=news)
    return service, news


def _authored(payload: dict) -> str:
    return json.dumps(
        {key: payload[key] for key in ("basis", "missing", "message") if key in payload},
        ensure_ascii=False,
    )


def _data_strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "url":
                continue
            yield from _data_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _data_strings(child)
    elif isinstance(value, str):
        yield value


def test_stock_news_normal():
    service, _ = _service()
    payload = service.call("news", {"kind": "stock", "code": "000528", "limit": 5})
    assert payload["status"] == "ok"
    assert payload["data"]["untrusted_text"] is True
    assert len(payload["data"]["items"]) == 5
    item = payload["data"]["items"][0]
    assert item["time"].endswith("+08:00")
    assert item["title"] and item["summary"]
    assert item["url"].startswith("http://finance.eastmoney.com/")
    assert item["time"] >= payload["data"]["items"][1]["time"]


def test_stock_news_empty_is_ok():
    service, news = _service()
    news.stock_rows = []
    payload = service.call("news", {"kind": "stock", "code": "000528"})
    assert payload["status"] == "ok"
    assert payload["data"]["items"] == []
    assert payload["data"]["total_available"] == 0


def test_stock_news_failure_is_unavailable():
    service, news = _service()
    news.error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("news", {"kind": "stock", "code": "000528"})
    assert payload["status"] == "unavailable"
    assert "新闻" in payload["message"]
    assert not authored_leaks(payload["message"])


def test_stock_news_truncates_and_marks_it():
    service, news = _service()
    news.stock_rows = [
        {
            "新闻标题": "很长的新闻",
            "新闻内容": "数" * 400,
            "发布时间": "2026-11-17 10:00:00",
            "新闻链接": "https://example.invalid/a",
        }
    ]
    payload = service.call("news", {"kind": "stock", "code": "000528"})
    item = payload["data"]["items"][0]
    assert item["truncated"] is True
    assert len(item["summary"]) == config.NEWS_SUMMARY_MAX


def test_flash_merges_and_dedupes_by_title():
    service, news = _service()
    news.flash_cls_rows = [
        {"标题": "同一条 快讯", "内容": "A", "发布日期": "2026-11-17", "发布时间": "10:00:00"},
        {"标题": "第一条", "内容": "B", "发布日期": "2026-11-17", "发布时间": "09:00:00"},
    ]
    news.flash_em_rows = [
        {"标题": "同一条  快讯 ", "摘要": "A2", "发布时间": "2026-11-17 10:00:00", "链接": "https://example.invalid/b"},
    ]
    payload = service.call("news", {"kind": "flash", "limit": 10})
    assert payload["status"] == "ok"
    titles = [item["title"] for item in payload["data"]["items"]]
    assert titles == ["同一条 快讯", "第一条"]
    assert payload["data"]["items"][0]["time"] == "2026-11-17T10:00:00+08:00"


def test_flash_single_source_failure_is_partial_without_source_name():
    service, news = _service()
    news.errors["flash_cls"] = UpstreamError("upstream_timeout", circuit=True)
    payload = service.call("news", {"kind": "flash", "limit": 5})
    assert payload["status"] == "partial"
    assert payload["missing"] == [{"field": "items", "reason": "部分快讯暂时取不到"}]
    assert payload["data"]["items"]
    assert not authored_leaks(_authored(payload))


def test_flash_both_sources_fail():
    service, news = _service()
    news.error = UpstreamError("upstream_timeout", circuit=True)
    payload = service.call("news", {"kind": "flash"})
    assert payload["status"] == "unavailable"
    assert "快讯" in payload["message"]


def test_flash_important_channel_keeps_graded_items_only():
    service, news = _service()
    news.flash_cls_rows = [
        {"标题": "重要", "内容": "A", "发布日期": "2026-11-17", "发布时间": "10:00:00", "等级": "A"},
        {"标题": "普通", "内容": "B", "发布日期": "2026-11-17", "发布时间": "09:00:00", "等级": "C"},
    ]
    news.flash_em_rows = []
    payload = service.call("news", {"kind": "flash", "channel": "important"})
    assert [item["title"] for item in payload["data"]["items"]] == ["重要"]


def test_irm_and_calendar_and_suspensions():
    service, _ = _service()
    irm = service.call("news", {"kind": "irm", "code": "000528", "limit": 3})
    assert irm["status"] == "ok" and len(irm["data"]["items"]) == 3
    assert irm["data"]["items"][0]["title"] and "content" in irm["data"]["items"][0]

    calendar = service.call("news", {"kind": "calendar", "date": "2026-11-17", "limit": 5})
    assert calendar["status"] == "ok" and len(calendar["data"]["items"]) == 5
    assert calendar["data"]["items"][0]["time"].endswith("+08:00")

    suspensions = service.call("news", {"kind": "suspensions", "date": "2026-11-17"})
    assert suspensions["status"] == "ok"
    assert suspensions["data"]["items"][0]["code"].startswith("920309")
    assert suspensions["data"]["items"][0]["time"] == "2026-11-17T00:00:00+08:00"


def test_news_parameter_errors_are_unavailable():
    service, _ = _service()
    cases = [
        {},
        {"kind": "nope"},
        {"kind": "stock"},
        {"kind": "stock", "code": "000300.SH"},
        {"kind": "stock", "code": "000528", "limit": 0},
        {"kind": "calendar", "date": "2026/11/17"},
        {"kind": "flash", "channel": "x"},
    ]
    for args in cases:
        payload = service.call("news", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]


def test_news_payload_has_no_forbidden_text_except_url_fields():
    service, _ = _service()
    payloads = [
        service.call("news", {"kind": "stock", "code": "000528", "limit": 3}),
        service.call("news", {"kind": "flash", "limit": 3}),
        service.call("news", {"kind": "irm", "code": "000528", "limit": 2}),
        service.call("news", {"kind": "calendar", "date": "2026-11-17", "limit": 2}),
        service.call("news", {"kind": "suspensions", "date": "2026-11-17"}),
    ]
    for payload in payloads:
        text = " ".join(_data_strings(payload.get("data"))).lower()
        for word in config.FORBIDDEN_OUTPUT:
            assert word.lower() not in text, (payload["data"].get("kind"), word)
    # tool descriptions are gateway-authored text too
    from cn_market_gateway import schemas

    for tool in schemas.TOOLS[-3:]:
        assert not authored_leaks(tool["description"])


@pytest.mark.parametrize(
    "args",
    [
        {"kind": "stock", "code": "000528"},
        {"kind": "flash"},
        {"kind": "irm", "code": "000528"},
        {"kind": "calendar", "date": "2026-11-17"},
        {"kind": "suspensions", "date": "2026-11-17"},
    ],
)
def test_each_news_kind_failure_is_unavailable(args):
    service, news = _service()
    news.error = UpstreamError("upstream_network", circuit=True)
    payload = service.call("news", args)
    assert payload["status"] == "unavailable", args
    assert payload["message"]
