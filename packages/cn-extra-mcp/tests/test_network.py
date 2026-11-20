from __future__ import annotations

from datetime import date, timedelta

import pytest

from cn_extra_mcp import service


@pytest.mark.network
def test_live_minute_bars_and_quote() -> None:
    bars = service.cn_get_minute_bars("002553.SZ", "1")
    assert bars["ok"] is True
    assert bars["status"] == "ready"
    assert bars["data"]["count"] > 0

    quote = service.cn_get_quote_snapshot(["002553.SZ"])
    assert quote["ok"] is True
    assert quote["data"][0]["name"] == "南方精工"
    assert float(quote["data"][0]["price"]) > 0


@pytest.mark.network
def test_live_announcements() -> None:
    end = date.today()
    start = end - timedelta(days=120)
    payload = service.cn_get_announcements(
        "002553.SZ",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=100,
    )
    assert payload["ok"] is True
    assert payload["status"] in ("ready", "empty")
    data = payload["data"]
    assert data["untrusted_text"] is True
    assert data["range"] == [start.isoformat(), end.isoformat()]
    assert len(data["announcements"]) <= 100
    for item in data["announcements"]:
        assert start.isoformat() <= item["date"] <= end.isoformat()
        assert item["url"].startswith("http")


@pytest.mark.network
def test_live_read_announcement() -> None:
    url = (
        "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=002553"
        "&announcementId=1225619566&orgId=9900018065&announcementTime=2026-10-26"
    )
    payload = service.cn_read_announcement(url, max_chars=200000)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["pages_total"] == 16
    assert data["pages_returned"] == [1, 16]
    assert data["untrusted_text"] is True
    assert "227,699,460.56" in data["text"]
