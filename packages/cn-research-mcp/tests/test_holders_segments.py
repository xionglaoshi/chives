from __future__ import annotations

import time

import pandas as pd
import pytest

from cn_research_mcp import service as service_module
from helpers import load, make_service

HOLDERS = load("holders_top10")
FUNDS = load("fund_holders")
SEGMENTS = load("business_segments")


def _svc(**kw):
    kw.setdefault("holders_top10", HOLDERS)
    kw.setdefault("fund_holders", FUNDS)
    kw.setdefault("business_segments", SEGMENTS)
    return make_service(**kw)


def _period(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    return frame[frame["截止日期"].astype(str).str.startswith(value)]


# ---------------------------------------------------------------- top10 float holders
def test_holders_top10_success():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519")
    assert out["status"] == "ready" and out["source"] == "eastmoney"
    data = out["data"]
    assert data["view"] == "top10_float" and data["period"] == "2026-09-30"
    assert data["count"] == 10 and len(data["rows"]) == 10
    first = data["rows"][0]
    assert first["rank"] == 1
    assert first["name"].startswith("中国贵州茅台酒厂")
    assert first["float_ratio_pct"] == pytest.approx(54.499077)
    assert first["change_shares"] is None and first["change_raw"] == "不变"


def test_holders_top10_ignores_funds_only_limit():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519", limit=3)
    assert len(out["data"]["rows"]) == 10


def test_holders_top10_numeric_change():
    svc, _ = _svc()
    row = next(item for item in svc.cn_get_holders("600519")["data"]["rows"] if item["rank"] == 3)
    assert row["change_shares"] == pytest.approx(1552026)
    assert row["change_pct"] == pytest.approx(2.889552)


def test_holders_top10_falls_back_one_period():
    seen: list[str] = []

    def fetch(symbol, date):
        seen.append(date)
        return HOLDERS.iloc[0:0] if date == "20260930" else HOLDERS

    svc, _ = _svc(holders_top10=fetch)
    out = svc.cn_get_holders("600519")
    assert out["data"]["period"] == "2026-06-30"
    assert seen == ["20260930", "20260630"]


def test_holders_top10_falls_back_through_four_periods():
    seen: list[str] = []

    def fetch(symbol, date):
        seen.append(date)
        return HOLDERS if date == "20250930" else HOLDERS.iloc[0:0]

    svc, _ = _svc(holders_top10=fetch)
    out = svc.cn_get_holders("600519")
    assert out["data"]["period"] == "2025-09-30"
    assert seen == ["20260930", "20260630", "20260331", "20251231", "20250930"]


def test_holders_top10_all_periods_empty():
    svc, _ = _svc(holders_top10=HOLDERS.iloc[0:0])
    out = svc.cn_get_holders("600519")
    assert out["status"] == "empty" and len(out["data"]["tried_periods"]) == 5


def test_holders_top10_skips_upstream_error_during_lookback():
    seen: list[str] = []

    def fetch(symbol, date):
        seen.append(date)
        if date == "20260930":
            raise ValueError("bad period")
        return HOLDERS

    svc, _ = _svc(holders_top10=fetch)
    out = svc.cn_get_holders("600519")
    assert out["data"]["period"] == "2026-06-30" and seen == ["20260930", "20260630"]


def test_holders_top10_rate_limit_stops_lookback():
    def fetch(symbol, date):
        raise RuntimeError("429 Too Many Requests")

    svc, _ = _svc(holders_top10=fetch)
    out = svc.cn_get_holders("600519")
    assert out["error"]["code"] == "rate_limited"


def test_holders_top10_explicit_period_does_not_fall_back():
    seen: list[str] = []

    def fetch(symbol, date):
        seen.append(date)
        return HOLDERS

    svc, _ = _svc(holders_top10=fetch)
    out = svc.cn_get_holders("600519", period="2026-06-30")
    assert out["data"]["period"] == "2026-06-30" and seen == ["20260630"]


def test_holders_top10_explicit_period_empty_is_empty():
    svc, fake = _svc(holders_top10=HOLDERS.iloc[0:0])
    out = svc.cn_get_holders("600519", period="2026-06-30")
    assert out["status"] == "empty" and fake.count("holders_top10") == 1


@pytest.mark.parametrize("period", ["2026-1-1", "2026-02-30", "2026-05-31", "bad", 20260930])
def test_holders_bad_period(period):
    svc, fake = _svc()
    out = svc.cn_get_holders("600519", period=period)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("code,err", [("bad", "invalid_argument"), ("920418", "unsupported_market"), (600519, "invalid_argument")])
def test_holders_bad_code(code, err):
    svc, fake = _svc()
    out = svc.cn_get_holders(code)
    assert out["error"]["code"] == err and fake.calls == []


@pytest.mark.parametrize("limit", [0, 51, -1, 1.5, "20", True])
def test_holders_bad_limit(limit):
    svc, fake = _svc()
    out = svc.cn_get_holders("600519", limit=limit)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_holders_bad_view_never_reaches_upstream():
    svc, fake = _svc()
    out = svc.cn_get_holders("600519", view="nope")
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_holders_top10_upstream_error_and_timeout(monkeypatch):
    svc, _ = _svc(holders_top10=ValueError("bad"))
    assert svc.cn_get_holders("600519", period="2026-09-30")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = _svc(holders_top10=lambda *args: time.sleep(1))
    assert svc.cn_get_holders("600519", period="2026-09-30")["error"]["code"] == "upstream_timeout"


def test_holders_top10_missing_columns():
    svc, _ = _svc(holders_top10=HOLDERS.drop(columns=["持股数"]))
    assert svc.cn_get_holders("600519", period="2026-09-30")["error"]["code"] == "upstream_error"


# ---------------------------------------------------------------- fund holders
def test_holders_funds_success_sorted_and_computed():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519", view="funds")
    assert out["status"] == "ready" and out["source"] == "sina"
    data = out["data"]
    assert data["period"] == "2026-09-30" and data["fund_count"] == len(FUNDS)
    assert data["computed"] is True and data["total_float_ratio_pct_computed"] is True
    values = [row["market_value_yuan"] for row in data["rows"]]
    assert values == sorted(values, reverse=True)
    expected = round(sum(FUNDS["占流通股比例"].dropna().tolist()), 4)
    assert data["total_float_ratio_pct"] == pytest.approx(expected)


def test_holders_funds_limit_does_not_change_totals():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519", view="funds", limit=5)
    assert out["data"]["returned"] == 5 and len(out["data"]["rows"]) == 5
    assert out["data"]["fund_count"] == len(FUNDS)
    assert out["data"]["total_float_ratio_pct"] == pytest.approx(
        round(sum(FUNDS["占流通股比例"].dropna().tolist()), 4)
    )


def test_holders_funds_explicit_period():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519", period="2026-09-30", view="funds")
    assert out["data"]["period"] == "2026-09-30"


def test_holders_funds_missing_period_is_empty():
    svc, _ = _svc()
    out = svc.cn_get_holders("600519", period="2026-06-30", view="funds")
    assert out["status"] == "empty" and out["data"]["rows"] == []


def test_holders_funds_falls_back_to_latest_available_period():
    old = FUNDS.copy()
    old["截止日期"] = pd.Timestamp("2026-06-30").date()
    svc, _ = _svc(fund_holders=old)
    out = svc.cn_get_holders("600519", view="funds")
    assert out["data"]["period"] == "2026-06-30"


def test_holders_funds_empty_table():
    svc, _ = _svc(fund_holders=FUNDS.iloc[0:0])
    out = svc.cn_get_holders("600519", view="funds")
    assert out["status"] == "empty"


def test_holders_funds_missing_columns():
    svc, _ = _svc(fund_holders=FUNDS.drop(columns=["持股市值"]))
    assert svc.cn_get_holders("600519", view="funds")["error"]["code"] == "upstream_error"


def test_holders_funds_upstream_error_and_timeout(monkeypatch):
    svc, _ = _svc(fund_holders=ValueError("bad"))
    assert svc.cn_get_holders("600519", view="funds")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = _svc(fund_holders=lambda *args: time.sleep(1))
    assert svc.cn_get_holders("600519", view="funds")["error"]["code"] == "upstream_timeout"


# ---------------------------------------------------------------- business segments
def test_segments_default_product_period():
    svc, _ = _svc()
    out = svc.cn_get_business_segments("600519")
    assert out["status"] == "ready" and out["source"] == "eastmoney"
    data = out["data"]
    assert data["by"] == "product" and data["period"] == "2026-09-30"
    assert data["count"] == 2 and data["classification"] == "按产品分类"
    assert data["rows"][0]["name"] == "茅台酒"
    assert data["rows"][0]["revenue_yuan"] == pytest.approx(1.129255e11)
    assert data["rows"][0]["revenue_share_pct"] == pytest.approx(86.2219)
    assert data["rows"][0]["gross_margin_pct"] is None


def test_segments_upstream_margin_is_converted_to_percent():
    svc, _ = _svc()
    out = svc.cn_get_business_segments("600519", period="2026-06-30", by="product")
    row = next(item for item in out["data"]["rows"] if item["name"] == "茅台酒")
    assert row["gross_margin_pct"] == pytest.approx(92.2793)
    assert "gross_margin_computed" not in row


def test_segments_computes_margin_and_profit_when_absent():
    table = SEGMENTS.iloc[0:0].copy().astype(object)
    table.loc[0] = {
        "股票代码": "600519",
        "报告日期": pd.Timestamp("2026-09-30").date(),
        "分类类型": "按产品分类",
        "主营构成": "测试产品",
        "主营收入": 100.0,
        "收入比例": 1.0,
        "主营成本": 60.0,
        "成本比例": 1.0,
        "主营利润": float("nan"),
        "利润比例": float("nan"),
        "毛利率": float("nan"),
    }
    svc, _ = _svc(business_segments=table)
    out = svc.cn_get_business_segments("600519")
    row = out["data"]["rows"][0]
    assert row["gross_profit_yuan"] == pytest.approx(40.0)
    assert row["gross_margin_pct"] == pytest.approx(40.0)
    assert row["gross_profit_computed"] is True and row["gross_margin_computed"] is True
    assert out["data"]["computed"] is True


def test_segments_region_and_industry_mapping():
    svc, _ = _svc()
    region = svc.cn_get_business_segments("600519", period="2026-06-30", by="region")
    assert region["data"]["classification"] == "按地区分类"
    assert {row["name"] for row in region["data"]["rows"]} == {"国内", "国外"}
    industry = svc.cn_get_business_segments("600519", period="2025-12-31", by="industry")
    assert industry["data"]["classification"] == "按行业分类"
    assert industry["data"]["rows"][0]["name"] == "酒类"


def test_segments_sorted_by_revenue_descending():
    svc, _ = _svc()
    out = svc.cn_get_business_segments("600519", period="2025-12-31", by="product")
    values = [row["revenue_yuan"] for row in out["data"]["rows"]]
    assert values == sorted(values, reverse=True)


def test_segments_ignores_future_report_dates():
    table = SEGMENTS.copy()
    future = table.iloc[0].copy()
    future["报告日期"] = pd.Timestamp("2027-03-31").date()
    future["主营构成"] = "未来分类"
    table = pd.concat([table, pd.DataFrame([future])], ignore_index=True)
    svc, _ = _svc(business_segments=table)
    out = svc.cn_get_business_segments("600519")
    assert out["data"]["period"] == "2026-09-30"


@pytest.mark.parametrize("by", ["nope", "", None, 1])
def test_segments_bad_by(by):
    svc, fake = _svc()
    out = svc.cn_get_business_segments("600519", by=by)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("period", ["2026-1-1", "2026-02-30", "2026-05-31", 20260930])
def test_segments_bad_period(period):
    svc, fake = _svc()
    out = svc.cn_get_business_segments("600519", period=period)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("code,err", [("bad", "invalid_argument"), ("920418", "unsupported_market"), (600519, "invalid_argument")])
def test_segments_bad_code(code, err):
    svc, fake = _svc()
    out = svc.cn_get_business_segments(code)
    assert out["error"]["code"] == err and fake.calls == []


def test_segments_missing_period_is_empty():
    svc, _ = _svc()
    out = svc.cn_get_business_segments("600519", period="2024-03-31")
    assert out["status"] == "empty" and out["data"]["rows"] == []


def test_segments_empty_table_and_missing_classification():
    svc, _ = _svc(business_segments=SEGMENTS.iloc[0:0])
    assert svc.cn_get_business_segments("600519")["status"] == "empty"
    svc, _ = _svc(business_segments=SEGMENTS[SEGMENTS["分类类型"] == "按地区分类"])
    assert svc.cn_get_business_segments("600519", by="industry")["status"] == "empty"


def test_segments_upstream_error_and_timeout(monkeypatch):
    svc, _ = _svc(business_segments=ValueError("bad"))
    assert svc.cn_get_business_segments("600519")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = _svc(business_segments=lambda *args: time.sleep(1))
    assert svc.cn_get_business_segments("600519")["error"]["code"] == "upstream_timeout"


def test_segments_missing_columns():
    svc, _ = _svc(business_segments=SEGMENTS.drop(columns=["毛利率"]))
    assert svc.cn_get_business_segments("600519")["error"]["code"] == "upstream_error"
