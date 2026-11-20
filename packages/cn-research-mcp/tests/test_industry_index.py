from __future__ import annotations

import json
import time
from datetime import date

import pandas as pd
import pytest

from cn_research_mcp import service as service_module
from helpers import business_days, load, make_service

IND = load("industry")
I300 = load("idx300")
ALLA = load("allA")


def test_industry_success_unit_conversion():
    svc, fake = make_service(industry_pe=IND)
    out = svc.cn_get_industry_valuation("2026-11-13", 40)
    assert out["status"] == "ready" and out["source"] == "cninfo"
    rows = out["data"]["rows"]
    first = rows[0]
    assert first["industry_name"] == "农、林、牧、渔业" and first["level"] == 1
    assert first["total_market_cap_yuan"] == pytest.approx(5327.1978e8)
    assert first["net_profit_yuan"] == pytest.approx(248.1094e8)
    assert first["company_count"] == 43 and first["included_company_count"] == 29
    assert first["pe_static_weighted"] == 21.47
    assert fake.calls[0] == ("industry_pe", ("20261113",))


def test_industry_cap_over_profit_equals_pe():
    svc, _ = make_service(industry_pe=IND)
    for row in svc.cn_get_industry_valuation("2026-11-13", 20)["data"]["rows"]:
        if row["total_market_cap_yuan"] and row["net_profit_yuan"] and row["pe_static_weighted"]:
            ratio = row["total_market_cap_yuan"] / row["net_profit_yuan"]
            assert ratio == pytest.approx(row["pe_static_weighted"], rel=0.01)


def test_industry_limit_applies():
    svc, _ = make_service(industry_pe=IND)
    assert len(svc.cn_get_industry_valuation("2026-11-13", 3)["data"]["rows"]) == 3


def test_industry_default_date_uses_today():
    svc, fake = make_service(industry_pe=IND)
    svc.cn_get_industry_valuation()
    assert fake.calls[0][1] == ("20261116",)


def test_industry_falls_back_to_earlier_day():
    def respond(day):
        return IND if day == "20261113" else IND.iloc[0:0]

    svc, fake = make_service(industry_pe=respond)
    out = svc.cn_get_industry_valuation()
    assert out["status"] == "ready" and out["data"]["requested_date"] == "2026-11-13"
    assert [c[1][0] for c in fake.calls] == ["20261116", "20261115", "20261114", "20261113"]


def test_industry_fallback_at_most_five_days_back():
    svc, fake = make_service(industry_pe=lambda day: IND.iloc[0:0])
    out = svc.cn_get_industry_valuation()
    assert out["status"] == "empty"
    assert [c[1][0] for c in fake.calls] == [
        "20261116", "20261115", "20261114", "20261113", "20261112", "20261111"
    ]


def test_industry_explicit_date_does_not_fall_back():
    svc, fake = make_service(industry_pe=lambda day: IND.iloc[0:0])
    assert svc.cn_get_industry_valuation("2026-11-01")["status"] == "empty"
    assert len(fake.calls) == 1


@pytest.mark.parametrize("bad", ["2026/11/13", "20261113", "2026-02-30", "x", 20261113])
def test_industry_bad_date_local_reject(bad):
    svc, fake = make_service(industry_pe=IND)
    assert svc.cn_get_industry_valuation(bad)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


@pytest.mark.parametrize("limit", [0, 201, "5", True])
def test_industry_bad_limit(limit):
    svc, fake = make_service(industry_pe=IND)
    assert svc.cn_get_industry_valuation("2026-11-13", limit)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def test_industry_error_and_timeout(monkeypatch):
    svc, _ = make_service(industry_pe=RuntimeError("x"))
    assert svc.cn_get_industry_valuation("2026-11-13")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = make_service(industry_pe=lambda d: time.sleep(1))
    assert svc.cn_get_industry_valuation("2026-11-13")["error"]["code"] == "upstream_timeout"


def test_industry_cached_by_date():
    svc, fake = make_service(industry_pe=IND)
    svc.cn_get_industry_valuation("2026-11-13", 5)
    svc.cn_get_industry_valuation("2026-11-13", 10)
    assert fake.count("industry_pe") == 1


# ------------------------------------------------------------------ index
@pytest.mark.parametrize("name", ["上证50", "沪深300", "中证500", "中证1000", "创业板50"])
def test_index_names_route_to_index_pe(name):
    svc, fake = make_service(index_pe=I300)
    out = svc.cn_get_index_valuation(name)
    assert out["status"] == "ready" and out["source"] == "legulegu"
    assert fake.calls == [("index_pe", (name,))]


def test_index_current_values():
    svc, _ = make_service(index_pe=I300)
    data = svc.cn_get_index_valuation("沪深300")["data"]
    cur = data["current"]
    assert cur["date"] == "2026-11-13" and cur["index_close"] == 4016.29
    assert cur["pe_static"] == 13.18 and cur["pe_ttm"] == 12.62
    assert cur["pe_ttm_median"] == 17.73 and cur["pe_static_median"] == 20.38


def test_index_all_a_uses_ttm_lyr():
    svc, fake = make_service(a_ttm_lyr=ALLA)
    out = svc.cn_get_index_valuation("全A")
    assert fake.calls == [("a_ttm_lyr", ())]
    cur = out["data"]["current"]
    assert cur["pe_ttm_median"] == 33.69 and cur["pe_ttm_average"] == 54.3
    assert "index_close" not in cur and "index_close" not in out["data"]["series"][-1]


def test_index_default_is_hs300_via_dispatch():
    from cn_research_mcp import server

    svc, fake = make_service(index_pe=I300)
    server.dispatch("cn_get_index_valuation", {}, svc)
    assert fake.calls == [("index_pe", ("沪深300",))]


@pytest.mark.parametrize("bad", ["纳斯达克", "", None, 300, "沪深300 "])
def test_index_invalid_name_rejected_locally(bad):
    svc, fake = make_service(index_pe=I300)
    assert svc.cn_get_index_valuation(bad)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def test_index_index_name_removed_when_unsupported():
    svc, fake = make_service(index_pe=I300, index_names=("全A", "沪深300"))
    assert svc.cn_get_index_valuation("创业板50")["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def _index_frame(n_months=130):
    dates = pd.date_range(end="2026-11-13", periods=n_months, freq="ME")
    dates = [d.strftime("%Y-%m-%d") for d in dates[:-1]] + ["2026-11-13"]
    ttm = [float(10 + (i % 23)) for i in range(n_months)]
    return pd.DataFrame(
        {
            "日期": [date.fromisoformat(d) for d in dates],
            "指数": [3000.0 + i for i in range(n_months)],
            "等权静态市盈率": ttm,
            "静态市盈率": ttm,
            "静态市盈率中位数": ttm,
            "等权滚动市盈率": ttm,
            "滚动市盈率": ttm,
            "滚动市盈率中位数": ttm,
        }
    ), dates, ttm


def test_index_percentile_ten_year_window_independent():
    frame, dates, ttm = _index_frame()
    svc, _ = make_service(index_pe=frame)
    data = svc.cn_get_index_valuation("沪深300")["data"]
    last = pd.Timestamp(dates[-1])
    start = last - pd.DateOffset(years=10)
    window = [v for d, v in zip(dates, ttm) if pd.Timestamp(d) > start]
    expect = round(sum(1 for v in window if v <= ttm[-1]) / len(window) * 100, 2)
    assert data["percentile"]["pe_ttm_pct"] == expect
    assert data["percentile"]["samples"] == len(window) and data["percentile"]["window_years"] == 10


def test_index_percentile_insufficient_samples_with_reason():
    svc, _ = make_service(index_pe=I300)
    pct = svc.cn_get_index_valuation("沪深300")["data"]["percentile"]
    assert pct["pe_ttm_pct"] is None and pct["pe_ttm_reason"] == "insufficient_samples"


def test_index_series_monthly_ends_with_latest_and_no_duplicates():
    frame, dates, _ = _index_frame()
    svc, _ = make_service(index_pe=frame)
    series = svc.cn_get_index_valuation("沪深300")["data"]["series"]
    months = [p["date"][:7] for p in series]
    assert len(months) == len(set(months)) and series[-1]["date"] == "2026-11-13"


def test_index_series_collapses_daily_rows_to_month_end():
    frame, dates, _ = _index_frame()
    extra = frame.iloc[[-1]].copy()
    extra["日期"] = date(2026, 11, 12)
    extra["滚动市盈率"] = 99.0
    svc, _ = make_service(index_pe=pd.concat([frame, extra], ignore_index=True))
    series = svc.cn_get_index_valuation("沪深300")["data"]["series"]
    assert series[-1]["date"] == "2026-11-13" and series[-1]["pe_ttm"] != 99.0


def test_index_empty_error_timeout(monkeypatch):
    svc, _ = make_service(index_pe=I300.iloc[0:0])
    assert svc.cn_get_index_valuation("沪深300")["status"] == "empty"
    svc, _ = make_service(index_pe=KeyError("symbol"))
    assert svc.cn_get_index_valuation("沪深300")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = make_service(index_pe=lambda n: time.sleep(1))
    assert svc.cn_get_index_valuation("沪深300")["error"]["code"] == "upstream_timeout"


def test_index_output_is_strict_json():
    svc, _ = make_service(index_pe=I300, a_ttm_lyr=ALLA)
    json.dumps(svc.cn_get_index_valuation("沪深300"), allow_nan=False)
    json.dumps(svc.cn_get_index_valuation("全A"), allow_nan=False)


def test_index_cache_per_name():
    svc, fake = make_service(index_pe=I300)
    svc.cn_get_index_valuation("沪深300")
    svc.cn_get_index_valuation("沪深300")
    svc.cn_get_index_valuation("上证50")
    assert fake.count("index_pe") == 2


def test_industry_fallback_skips_days_where_upstream_raises():
    def respond(day):
        if day == "20261113":
            return IND
        raise ValueError("no data for this day")

    svc, fake = make_service(industry_pe=respond)
    out = svc.cn_get_industry_valuation()
    assert out["status"] == "ready" and out["data"]["requested_date"] == "2026-11-13"
    assert len(fake.calls) == 4


def test_industry_fallback_all_days_failing_returns_last_error():
    svc, fake = make_service(industry_pe=ValueError("nope"))
    out = svc.cn_get_industry_valuation()
    assert out["status"] == "error" and out["error"]["code"] == "upstream_error"
    assert len(fake.calls) == 6


def test_industry_fallback_stops_on_rate_limit():
    svc, fake = make_service(industry_pe=RuntimeError("429 Too Many Requests"))
    out = svc.cn_get_industry_valuation()
    assert out["error"]["code"] == "rate_limited" and len(fake.calls) == 1


def test_industry_explicit_date_error_is_reported_not_skipped():
    svc, fake = make_service(industry_pe=ValueError("nope"))
    assert svc.cn_get_industry_valuation("2026-11-13")["error"]["code"] == "upstream_error"
    assert len(fake.calls) == 1
