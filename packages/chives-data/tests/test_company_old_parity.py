"""T142 parity: the same recorded samples through the old cn_research tools.

The old package is imported read-only from its own source tree; no file there is modified.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from chives_data.company_parse import normalize_suggest
from fakes import FakeCompanySources, company_fixture, make_service

OLD_SRC = Path(__file__).resolve().parents[2] / "cn-research-mcp" / "src"
if str(OLD_SRC) not in sys.path:
    sys.path.insert(0, str(OLD_SRC))

from cn_research_mcp.infra import RateLimiter, TTLCache, UpstreamClient  # noqa: E402
from cn_research_mcp.service import ResearchService  # noqa: E402


def _frame(name: str) -> pd.DataFrame:
    return pd.DataFrame(company_fixture(name))


class _OldSources:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def __getattr__(self, name: str):
        if name not in self.frames:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.frames[name]


def _old_service() -> ResearchService:
    report = company_fixture("reports_600519.json")
    for row in report:
        row["报告PDF链接"] = "https://example.invalid/report.pdf"
    frames = {
        "profit_forecast_em": _frame("forecast_em.json"),
        "profit_forecast_ths": _frame("forecast_ths_eps_600519.json"),
        "institute_recommend": _frame("ratings_600519.json"),
        "research_report": pd.DataFrame(report),
        "stock_value": _frame("value_002553.json"),
        "yjyg": _frame("yjyg.json"),
        "yysj": _frame("yysj.json").replace("NaT", None),
        "holders_top10": _frame("top10_002553.json"),
        "business_segments": _frame("segments_002553.json"),
        "index_constituents": _frame("index_cons_300.json"),
    }
    return ResearchService(
        sources=_OldSources(frames),
        client=UpstreamClient(RateLimiter(min_interval=0, sleep=lambda _s: None)),
        cache=TTLCache(),
        today=lambda: date(2026, 11, 17),
        index_names=("沪深300",),
        index_units_confirmed=True,
    )


def _new_service() -> tuple:
    company = FakeCompanySources()
    company.forecast_em = company_fixture("forecast_em.json")
    company.forecast_ths = {
        "预测年报每股收益": company_fixture("forecast_ths_eps_600519.json"),
        "预测年报净利润": company_fixture("forecast_ths_np_600519.json"),
    }
    company.rating_rows = company_fixture("ratings_600519.json")
    company.report_rows = company_fixture("reports_600519.json")
    company.stock_values["002553"] = company_fixture("value_002553.json")
    company.earnings_rows["forecast"] = company_fixture("yjyg.json")
    company.schedule_rows = company_fixture("yysj.json")
    company.top10["20260930"] = company_fixture("top10_002553.json")
    company.segment_rows = company_fixture("segments_002553.json")
    company.org_rows = company_fixture("org_002553.json")
    company.concept_rows = company_fixture("concepts_002553.json")
    company.index_cons["000300"] = company_fixture("index_cons_300.json")
    return make_service(company_sources=company), company


def test_consensus_parity():
    old = _old_service().cn_get_consensus("600519")
    new = _new_service()[0].call("company_consensus", {"code": "600519", "limit": 10})
    assert old["status"] == "ready" and new["status"] == "ok"
    old_eps = {item["year"]: item["eps_yuan"] for item in old["data"]["eps_forecast"]}
    new_eps = {item["year"]: item["eps_yuan"] for item in new["data"]["eps_forecast"]}
    assert new_eps == pytest.approx(old_eps)
    assert new["data"]["rating_counts"] == old["data"]["rating_counts"]
    assert new["data"]["report_count"] == old["data"]["report_count"]
    old_cross = {item["year"]: item for item in old["data"]["cross_check"]["years"]}
    new_cross = {item["year"]: item for item in new["data"]["eps_cross_check"]}
    for year in old_cross:
        for field in ("analysts", "min", "mean", "max"):
            assert new_cross[year][field] == pytest.approx(old_cross[year][field])


def test_ratings_and_reports_parity():
    old_service = _old_service()
    new_service = _new_service()[0]
    old_ratings = old_service.cn_get_ratings("600519", limit=6)
    new_ratings = new_service.call("company_consensus", {"code": "600519", "limit": 6})
    old_rows = [
        (row["date"], row["org"], row["rating"], row["target_price_yuan"])
        for row in old_ratings["data"]["ratings"]
    ]
    new_rows = [
        (row["date"], row["org"], row["rating"], row["target_price_yuan"])
        for row in new_ratings["data"]["ratings"]["rows"]
    ]
    assert new_rows == old_rows

    old_reports = old_service.cn_get_research_reports("600519", limit=3)
    new_reports = new_service.call("company_reports", {"code": "600519", "limit": 3})
    old_meta = [(row["date"], row["title"], row["org"], row["rating"]) for row in old_reports["data"]["reports"]]
    new_meta = [(row["date"], row["title"], row["org"], row["rating"]) for row in new_reports["data"]["reports"]]
    assert new_meta == old_meta


def test_valuation_parity_after_percentile_definition():
    old = _old_service().cn_get_valuation("002553", years=3)
    new = _new_service()[0].call("company_valuation", {"scope": "stock", "code": "002553", "years": 3})
    assert old["status"] == "ready" and new["status"] == "ok"
    assert new["data"]["current"]["pe_ttm"] == pytest.approx(old["data"]["current"]["pe_ttm"])
    assert new["data"]["current"]["pb_mrq"] == pytest.approx(old["data"]["current"]["pb"])
    assert new["data"]["percentile"]["pe_ttm_pct"] == pytest.approx(old["data"]["percentile"]["pe_ttm_pct"])
    assert new["data"]["percentile"]["pb_mrq_pct"] == pytest.approx(old["data"]["percentile"]["pb_pct"])
    assert new["data"]["percentile"]["samples"] == old["data"]["percentile"]["samples"]


def test_holders_segments_and_index_parity():
    old_service = _old_service()
    new_service = _new_service()[0]
    old_holders = old_service.cn_get_holders("002553")
    new_holders = new_service.call("company_holders", {"code": "002553", "kind": "top10"})
    old_rows = [(row["rank"], row["shares"], row["float_ratio_pct"]) for row in old_holders["data"]["rows"]]
    new_rows = [(row["rank"], row["shares"], row["float_ratio_pct"]) for row in new_holders["data"]["rows"]]
    assert new_rows == old_rows

    old_segments = old_service.cn_get_business_segments("002553", by="product")
    new_segments = new_service.call("company_profile", {"code": "002553", "by": "product"})
    old_rows = [
        (row["name"], row["revenue_yuan"], row["revenue_share_pct"], row["gross_margin_pct"])
        for row in old_segments["data"]["rows"]
    ]
    new_rows = [
        (row["name"], row["revenue_yuan"], row["revenue_share_pct"], row["gross_margin_pct"])
        for row in new_segments["data"]["segments"]["rows"]
    ]
    assert new_rows == old_rows

    old_index = old_service.cn_get_index_constituents("沪深300", limit=5)
    new_index = new_service.call("company_profile", {"index": "000300.SH", "limit": 5})
    old_rows = [(row["code"], row["name"]) for row in old_index["data"]["rows"]]
    new_rows = [(row["code"], row["name"]) for row in new_index["data"]["index"]["rows"]]
    assert new_rows == old_rows


def test_earnings_and_schedule_parity():
    old_service = _old_service()
    new_service = _new_service()[0]
    old_forecast = old_service.cn_get_earnings_events("2026-09-30", "forecast", code="688827")
    new_forecast = new_service.call(
        "company_earnings", {"kind": "forecast", "period": "2026-09-30", "code": "688827"}
    )
    old_row = old_forecast["data"]["events"][0]
    new_row = new_forecast["data"]["events"][0]
    for field in ("change_pct_mid", "change_pct_min", "change_pct_max", "forecast_mid_yuan", "prior_year_yuan"):
        assert new_row[field] == pytest.approx(old_row[field])
    assert new_row["summary"] == old_row["summary"]

    old_schedule = old_service.cn_get_disclosure_schedule("2026-09-30", code="002107")
    new_schedule = new_service.call(
        "company_earnings", {"kind": "schedule", "period": "2026-09-30", "code": "002107"}
    )
    old_row = old_schedule["data"]["items"][0]
    new_row = new_schedule["data"]["items"][0]
    assert new_row["first_scheduled_date"] == old_row["first_scheduled_date"]
    assert new_row["current_scheduled_date"] == old_row["current_scheduled_date"]
    assert new_row["actual_disclosure_date"] == old_row["actual_disclosure_date"]
