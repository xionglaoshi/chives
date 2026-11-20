from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from cn_extra_mcp import service

COLUMNS = ["代码", "简称", "公告标题", "公告时间", "公告链接"]

ROWS = [
    {
        "代码": "002553",
        "简称": "南方精工",
        "公告标题": "2026年半年度报告",
        "公告时间": "2026-08-29",
        "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=1",
    },
    {
        "代码": "002553",
        "简称": "南方精工",
        "公告标题": "区间外-早",
        "公告时间": "2026-07-01",
        "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=0",
    },
    {
        "代码": "002553",
        "简称": "南方精工",
        "公告标题": "2026年三季度报告",
        "公告时间": "2026-10-26 00:00:00",
        "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=3",
    },
    {
        "代码": "002553",
        "简称": "南方精工",
        "公告标题": "第七届董事会第六次会议决议公告",
        "公告时间": pd.Timestamp("2026-08-29"),
        "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=2",
    },
    {
        "代码": "002553",
        "简称": "南方精工",
        "公告标题": "区间外-晚",
        "公告时间": "2026-11-05",
        "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=4",
    },
]


def announcement_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_fetch(**kwargs) -> pd.DataFrame:
        calls.append(kwargs)
        return announcement_frame(ROWS)

    monkeypatch.setattr(service.sources, "fetch_announcements_frame", fake_fetch)
    return calls


def test_filters_to_range_and_sorts_desc(captured) -> None:
    payload = service.cn_get_announcements(
        "002553.SZ", start_date="2026-08-01", end_date="2026-11-02"
    )
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["source"] == service.ANNOUNCEMENT_SOURCE
    data = payload["data"]
    assert data["code"] == "002553.SZ"
    assert data["name"] == "南方精工"
    assert data["count"] == 3
    assert data["range"] == ["2026-08-01", "2026-11-02"]
    assert data["truncated"] is False
    assert data["untrusted_text"] is True

    assert [item["date"] for item in data["announcements"]] == [
        "2026-10-26",
        "2026-08-29",
        "2026-08-29",
    ]
    assert {item["title"] for item in data["announcements"]} == {
        "2026年半年度报告",
        "第七届董事会第六次会议决议公告",
        "2026年三季度报告",
    }
    assert all(item["url"].startswith("http") for item in data["announcements"])
    assert all("2026-08-01" <= item["date"] <= "2026-11-02" for item in data["announcements"])
    assert captured == [
        {
            "symbol": "002553",
            "market": "沪深京",
            "category": "",
            "start_date": "20260801",
            "end_date": "20261102",
        }
    ]


def test_default_range_is_last_90_days(captured, monkeypatch) -> None:
    today = date(2026, 11, 2)
    monkeypatch.setattr(service, "_today_cn", lambda: today)
    payload = service.cn_get_announcements("002553")
    expected_start = (today - timedelta(days=90)).strftime("%Y%m%d")
    assert captured[0]["start_date"] == expected_start
    assert captured[0]["end_date"] == "20261102"
    assert payload["data"]["range"] == [
        (today - timedelta(days=90)).isoformat(),
        today.isoformat(),
    ]


def test_limit_truncates_and_sets_flag(captured) -> None:
    payload = service.cn_get_announcements(
        "002553", start_date="2026-08-01", end_date="2026-11-02", limit=2
    )
    data = payload["data"]
    assert data["count"] == 3
    assert data["truncated"] is True
    assert len(data["announcements"]) == 2
    assert [item["date"] for item in data["announcements"]] == ["2026-10-26", "2026-08-29"]


def test_limit_equal_to_total_is_not_truncated(captured) -> None:
    data = service.cn_get_announcements(
        "002553", start_date="2026-08-01", end_date="2026-11-02", limit=3
    )["data"]
    assert data["count"] == 3
    assert data["truncated"] is False
    assert len(data["announcements"]) == 3


def test_range_without_announcements_is_empty(captured) -> None:
    payload = service.cn_get_announcements(
        "002553", start_date="2026-01-01", end_date="2026-01-05"
    )
    assert payload["ok"] is True
    assert payload["status"] == "empty"
    data = payload["data"]
    assert data["announcements"] == []
    assert data["count"] == 0
    assert data["truncated"] is False
    assert data["untrusted_text"] is True
    assert data["name"] == "南方精工"
    assert data["range"] == ["2026-01-01", "2026-01-05"]
    assert captured


def test_empty_upstream_frame_has_no_name(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources,
        "fetch_announcements_frame",
        lambda **kwargs: announcement_frame([]),
    )
    payload = service.cn_get_announcements("002553")
    assert payload["status"] == "empty"
    assert payload["data"]["name"] is None


def test_code_conversion(monkeypatch) -> None:
    seen: list[str] = []

    def fake_fetch(**kwargs) -> pd.DataFrame:
        seen.append(kwargs["symbol"])
        return announcement_frame(ROWS)

    monkeypatch.setattr(service.sources, "fetch_announcements_frame", fake_fetch)
    assert service.cn_get_announcements("600519")["data"]["code"] == "600519.SH"
    assert service.cn_get_announcements("SZ002553")["data"]["code"] == "002553.SZ"
    assert seen == ["600519", "002553"]


def test_bj_code_conversion_and_legacy_warning(monkeypatch) -> None:
    seen: list[str] = []

    def fake_fetch(**kwargs) -> pd.DataFrame:
        seen.append(kwargs["symbol"])
        return announcement_frame(ROWS)

    monkeypatch.setattr(service.sources, "fetch_announcements_frame", fake_fetch)

    current = service.cn_get_announcements(
        "920418.BJ", start_date="2026-08-01", end_date="2026-11-02"
    )
    assert current["ok"] is True
    assert current["data"]["code"] == "920418.BJ"
    assert "warnings" not in current
    assert "warning_message" not in current

    legacy = service.cn_get_announcements(
        "430418", start_date="2026-08-01", end_date="2026-11-02"
    )
    assert legacy["data"]["code"] == "430418.BJ"
    assert legacy["warnings"] == ["legacy_bj_code"]
    assert "北交所代码已迁移" in legacy["warning_message"]

    sh = service.cn_get_announcements("600519", start_date="2026-08-01", end_date="2026-11-02")
    assert "warnings" not in sh
    assert seen == ["920418", "430418", "600519"]


def test_invalid_symbol_does_not_call_source(captured) -> None:
    payload = service.cn_get_announcements("abc")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_symbol"
    assert captured == []


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026/08/01", None),
        (None, "20260801"),
        ("2026-11-02", "2026-08-01"),
    ],
)
def test_invalid_dates(captured, start, end) -> None:
    payload = service.cn_get_announcements("002553", start_date=start, end_date=end)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert captured == []


@pytest.mark.parametrize("limit", [0, 101, -1, True, 1.5, "20"])
def test_invalid_limit(captured, limit) -> None:
    payload = service.cn_get_announcements("002553", limit=limit)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert captured == []


def test_invalid_category_does_not_call_source(captured) -> None:
    payload = service.cn_get_announcements("002553", category="不存在的类别")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert "年报" in payload["error"]["message"]
    assert captured == []


def test_supported_category_is_passed_through(captured) -> None:
    payload = service.cn_get_announcements("002553", category="年报")
    assert payload["ok"] is True
    assert captured[0]["category"] == "年报"


def test_upstream_failure_is_envelope(monkeypatch) -> None:
    def boom(**kwargs) -> pd.DataFrame:
        raise TimeoutError("timed out")

    monkeypatch.setattr(service.sources, "fetch_announcements_frame", boom)
    payload = service.cn_get_announcements("002553")
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "upstream_error"


def test_unexpected_columns_are_upstream_error(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources,
        "fetch_announcements_frame",
        lambda **kwargs: pd.DataFrame([{"代码": "002553"}]),
    )
    payload = service.cn_get_announcements("002553")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "upstream_error"
