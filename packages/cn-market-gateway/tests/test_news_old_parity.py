"""T143 parity: the same recorded samples through the old cn_research/cn_extra tools."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote_plus

import pandas as pd
import pytest

from cn_market_gateway.news_sources import NewsSources
from fakes import FakeNewsSources, make_service, news_fixture, news_fixture_bytes

RESEARCH_SRC = Path(__file__).resolve().parents[2] / "cn-research-mcp" / "src"
EXTRA_SRC = Path(__file__).resolve().parents[2] / "cn-extra-mcp" / "src"
for path in (RESEARCH_SRC, EXTRA_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cn_research_mcp.infra import RateLimiter, TTLCache, UpstreamClient  # noqa: E402
from cn_research_mcp.service import ResearchService  # noqa: E402

import cn_extra_mcp.service as extra_service  # noqa: E402
import cn_extra_mcp.sources as extra_sources  # noqa: E402


def _frame(name: str) -> pd.DataFrame:
    return pd.DataFrame(news_fixture(name))


def _old_cb_frame() -> pd.DataFrame:
    rows = []
    for row in news_fixture("cb_terms.json"):
        listing = row.get("LISTING_DATE")
        rows.append(
            {
                "债券代码": row.get("SECURITY_CODE"),
                "债券简称": row.get("SECURITY_NAME_ABBR"),
                "正股代码": row.get("CONVERT_STOCK_CODE"),
                "正股简称": row.get("SECURITY_SHORT_NAME"),
                "正股价": row.get("CONVERT_STOCK_PRICE"),
                "转股价": row.get("TRANSFER_PRICE"),
                "转股价值": row.get("TRANSFER_VALUE"),
                "转股溢价率": row.get("TRANSFER_PREMIUM_RATIO"),
                "上市时间": pd.to_datetime(listing).date() if listing else None,
                "信用评级": row.get("RATING"),
            }
        )
    return pd.DataFrame(rows)


class _OldSources:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def __getattr__(self, name: str):
        if name not in self.frames:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.frames[name]


def _old_service() -> ResearchService:
    frames = {
        "stock_news": _frame("stock_news_000528.json"),
        "flash_cls": _frame("flash_cls.json"),
        "flash_em": _frame("flash_em.json"),
        "econ_calendar": _frame("calendar_20261117.json"),
        "suspensions": _frame("suspensions_20261117.json"),
        "irm_qa": _frame("irm_000528.json"),
        "cb_list": _old_cb_frame(),
        "cb_spot": _frame("cb_spot.json"),
    }
    return ResearchService(
        sources=_OldSources(frames),
        client=UpstreamClient(RateLimiter(min_interval=0, sleep=lambda _s: None)),
        cache=TTLCache(),
        today=lambda: date(2026, 11, 17),
        index_names=(),
        now=lambda: pd.Timestamp("2026-11-17T16:00:00+08:00").to_pydatetime(),
    )


def _new_service() -> tuple:
    news = FakeNewsSources()
    news.stock_rows = news_fixture("stock_news_000528.json")
    news.flash_cls_rows = news_fixture("flash_cls.json")
    news.flash_em_rows = news_fixture("flash_em.json")
    news.calendar_rows = news_fixture("calendar_20261117.json")
    news.suspension_rows = news_fixture("suspensions_20261117.json")
    news.irm_rows = news_fixture("irm_000528.json")
    news.term_rows = news_fixture("cb_terms.json")
    news.spot_rows = news_fixture("cb_spot.json")
    return make_service(news_sources=news), news


def test_stock_news_parity():
    old = _old_service().cn_get_stock_news("000528", limit=5)
    new = _new_service()[0].call("news", {"kind": "stock", "code": "000528", "limit": 5})
    old_rows = [(row["published_at"], row["title"], row["summary"]) for row in old["data"]["items"]]
    new_rows = [(row["time"], row["title"], row["summary"]) for row in new["data"]["items"]]
    assert new_rows == old_rows


def test_flash_parity_is_a_subset_of_the_merged_feed():
    old_service = _old_service()
    new = _new_service()[0].call("news", {"kind": "flash", "limit": 50})
    merged = {(row["time"], row["title"], row["content"]) for row in new["data"]["items"]}
    merged_titles = {row["title"] for row in new["data"]["items"]}
    for source in ("cls", "em"):
        old = old_service.cn_get_flash_news(source=source, limit=50)
        exact = 0
        for row in old["data"]["items"]:
            # Merge dedupes by normalized title, so an older duplicate may be dropped;
            # every surviving source row must still be present verbatim.
            assert row["title"] in merged_titles
            exact += (row["published_at"], row["title"], row["body"]) in merged
        assert exact > 0


def test_irm_calendar_suspension_parity():
    old = _old_service()
    new_service = _new_service()[0]

    old_irm = old.cn_get_irm_qa("000528", limit=5)
    new_irm = new_service.call("news", {"kind": "irm", "code": "000528", "limit": 5})
    assert [(r["asked_at"], r["question"], r["answer"]) for r in old_irm["data"]["items"]] == [
        (r["time"], r["title"], r["content"]) for r in new_irm["data"]["items"]
    ]

    old_cal = old.cn_get_econ_calendar("2026-11-17")
    new_cal = new_service.call("news", {"kind": "calendar", "date": "2026-11-17", "limit": 50})
    old_rows = [
        (r["time"], r["region"], r["event"], r["actual"], r["forecast"], r["previous"], r["importance"])
        for r in old_cal["data"]["items"]
    ]
    new_rows = [
        (r["time"], r["region"], r["title"], r["actual"], r["forecast"], r["previous"], r["importance"])
        for r in new_cal["data"]["items"]
    ]
    assert len(new_rows) == 50
    assert set(new_rows) <= set(old_rows)

    old_sus = old.cn_get_suspensions("2026-11-17")
    new_sus = new_service.call("news", {"kind": "suspensions", "date": "2026-11-17"})
    old_rows = [(r["code"], r["name"], r["reason"], r["suspend_from"], r["resume_at"]) for r in old_sus["data"]["items"]]
    new_rows = [
        (r["code"], r["title"], r["reason"], (r["time"] or "")[:10], r["resume_at"]) for r in new_sus["data"]["items"]
    ]
    old_codes = {row[0] for row in old_rows}
    assert [row for row in new_rows if row[0] in old_codes] == old_rows
    # The old package refuses Beijing codes; the gateway keeps them instead of dropping rows.
    assert "920309.BJ" in {row[0] for row in new_rows}


def test_cb_list_parity():
    old = _old_service().cn_get_cb_list(limit=20)
    new = _new_service()[0].call("convertible_bonds", {"kind": "list", "limit": 20})
    old_rows = {row["bond_code"]: row for row in old["data"]["rows"]}
    new_rows = {row["bond_code"]: row for row in new["data"]["rows"]}
    assert set(new_rows) == set(old_rows)
    for code, old_row in old_rows.items():
        new_row = new_rows[code]
        assert new_row["bond_name"] == old_row["bond_name"]
        assert new_row["underlying_code"] == old_row["underlying_code"]
        assert new_row["underlying_price_yuan"] == pytest.approx(old_row["underlying_price_yuan"])
        assert new_row["conversion_price_yuan"] == pytest.approx(old_row["conversion_price_yuan"])
        assert new_row["credit_rating"] == old_row["credit_rating"]
        assert new_row["listing_date"] == old_row["listing_date"]
        if old_row["conversion_value_yuan"] is not None and new_row["conversion_value_yuan"] is not None:
            assert new_row["conversion_value_yuan"] == pytest.approx(old_row["conversion_value_yuan"], abs=0.01)
        if old_row["premium_pct"] is not None and new_row["premium_pct"] is not None:
            assert new_row["premium_pct"] == pytest.approx(old_row["premium_pct"], abs=0.05)


def test_cb_quote_parity():
    spot = news_fixture("cb_spot.json")
    code = "110081"
    spot_row = next(row for row in spot if row["code"] == code)
    term = {
        "SECURITY_CODE": code,
        "SECURITY_NAME_ABBR": spot_row["name"],
        "CONVERT_STOCK_CODE": "600745",
        "SECURITY_SHORT_NAME": "闻泰科技",
        "CONVERT_STOCK_PRICE": 40.0,
        "TRANSFER_PRICE": 45.0,
        "TRANSFER_VALUE": 88.8889,
        "TRANSFER_PREMIUM_RATIO": -4.17,
        "LISTING_DATE": "2020-08-07 00:00:00",
        "RATING": "AA",
    }
    old_frame = pd.DataFrame(
        [
            {
                "债券代码": code,
                "债券简称": term["SECURITY_NAME_ABBR"],
                "正股代码": term["CONVERT_STOCK_CODE"],
                "正股简称": term["SECURITY_SHORT_NAME"],
                "正股价": term["CONVERT_STOCK_PRICE"],
                "转股价": term["TRANSFER_PRICE"],
                "转股价值": term["TRANSFER_VALUE"],
                "转股溢价率": term["TRANSFER_PREMIUM_RATIO"],
                "上市时间": pd.Timestamp(term["LISTING_DATE"]).date(),
                "信用评级": term["RATING"],
            }
        ]
    )
    frames = {"cb_list": old_frame, "cb_spot": _frame("cb_spot.json")}
    old_service = ResearchService(
        sources=_OldSources(frames),
        client=UpstreamClient(RateLimiter(min_interval=0, sleep=lambda _s: None)),
        cache=TTLCache(),
        today=lambda: date(2026, 11, 17),
        index_names=(),
        now=lambda: pd.Timestamp("2026-11-17T16:00:00+08:00").to_pydatetime(),
    )
    old = old_service.cn_get_cb_quote([code])
    new_service, news = _new_service()
    news.term_rows = [term]
    new = new_service.call("convertible_bonds", {"kind": "quote", "codes": [code]})
    old_row = old["data"]["rows"][0]
    new_row = new["data"]["rows"][0]
    assert new_row["name"] == old_row["name"]
    assert new_row["bond_price_yuan"] == pytest.approx(old_row["price_yuan"])
    assert new_row["change_pct"] == pytest.approx(old_row["change_pct"])
    assert new_row["underlying_price_yuan"] == pytest.approx(old_row["underlying_price_yuan"])
    assert new_row["conversion_price_yuan"] == pytest.approx(old_row["conversion_price_yuan"])
    assert new_row["conversion_value_yuan"] == pytest.approx(old_row["conversion_value_yuan"], abs=0.01)
    assert new_row["premium_pct"] == pytest.approx(old_row["premium_pct"], abs=0.05)


def test_announcements_and_pdf_parity(monkeypatch):
    raw = news_fixture("announcements_000528.json")
    frame = pd.DataFrame(
        [
            {
                "代码": row["secCode"],
                "简称": row["secName"],
                "公告标题": row["announcementTitle"],
                "公告时间": pd.Timestamp(row["announcementTime"], unit="ms", tz="Asia/Shanghai").tz_localize(None),
                "公告链接": NewsSources._announcement_item(row, "")["url"].replace(
                    "+", "%20"
                ),
            }
            for row in raw["announcements"]
        ]
    )
    monkeypatch.setattr(extra_sources, "fetch_announcements_frame", lambda **kwargs: frame)
    old = extra_service.cn_get_announcements("000528", "2026-10-18", "2026-11-17", limit=20)

    news = FakeNewsSources()
    news.announcement_total = raw["totalAnnouncement"]
    news.announcement_rows = [
        NewsSources._announcement_item(row, "") for row in raw["announcements"]
    ]
    new_service = make_service(news_sources=news)
    new = new_service.call(
        "company_announcements", {"code": "000528", "start": "2026-10-18", "end": "2026-11-17", "limit": 20}
    )
    old_rows = [(row["date"], row["title"], unquote_plus(row["url"])) for row in old["data"]["announcements"]]
    new_rows = [(row["date"], row["title"], unquote_plus(row["url"])) for row in new["data"]["announcements"]]
    assert new_rows == old_rows

    url = (
        "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000528"
        "&announcementId=1225621247&orgId=gssz0000528&announcementTime=2026-10-24"
    )
    pdf = news_fixture_bytes("announcement_small.pdf")
    monkeypatch.setattr(extra_sources, "fetch_pdf_bytes", lambda pdf_url: (pdf, "application/pdf"))
    old_pdf = extra_service.cn_read_announcement(url, end_page=1, max_chars=5000)
    news.pdf_bytes = pdf
    new_pdf = new_service.call("company_announcements", {"url": url, "end_page": 1, "max_chars": 5000})
    assert new_pdf["status"] == "ok" and old_pdf["status"] == "ready"
    assert new_pdf["data"]["pages_total"] == old_pdf["data"]["pages_total"]
    assert new_pdf["data"]["pages_returned"] == old_pdf["data"]["pages_returned"]
    assert new_pdf["data"]["text"] == old_pdf["data"]["text"]
