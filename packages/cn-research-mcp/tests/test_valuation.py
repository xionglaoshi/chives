from __future__ import annotations

import time

import pandas as pd
import pytest

from cn_research_mcp import service as service_module
from helpers import business_days, load, make_service, value_frame

VAL = load("value")


def test_valuation_real_fixture_current():
    svc, _ = make_service(stock_value=VAL)
    out = svc.cn_get_valuation("600519")
    cur = out["data"]["current"]
    assert out["status"] == "ready" and out["source"] == "eastmoney"
    assert cur["date"] == "2026-11-13"
    assert cur["pe_ttm"] == pytest.approx(21.837583, abs=1e-6)
    assert cur["pe_static"] == pytest.approx(21.795319, abs=1e-6)
    assert cur["pb"] == pytest.approx(6.615637, abs=1e-6)
    assert cur["market_cap_yuan"] == pytest.approx(1.794192e12, rel=1e-6)
    # market cap = close * total shares: 1435.26 * 1250081601
    assert cur["market_cap_yuan"] == pytest.approx(1435.26 * 1250081601, rel=1e-4)


def test_valuation_small_fixture_has_insufficient_samples():
    svc, _ = make_service(stock_value=VAL)
    pct = svc.cn_get_valuation("600519")["data"]["percentile"]
    assert pct["pe_ttm_pct"] is None and pct["reason"] == "insufficient_samples"
    assert pct["samples"] == 50 and pct["window_years"] == 3


def _long_frame(n=900, end="2026-11-13"):
    dates = business_days(end, n)
    pe = [float(10 + (i % 37)) for i in range(n)]
    pb = [float(1 + (i % 11) * 0.5) for i in range(n)]
    return value_frame(dates, pe, pb), dates, pe, pb


def test_percentile_matches_independent_computation():
    frame, dates, pe, pb = _long_frame()
    svc, _ = make_service(stock_value=frame)
    out = svc.cn_get_valuation("600519", 3)
    last = pd.Timestamp(dates[-1])
    start = last - pd.DateOffset(years=3)
    window = [(d, p, b) for d, p, b in zip(dates, pe, pb) if pd.Timestamp(d) > start]
    cur_pe, cur_pb = pe[-1], pb[-1]
    expect_pe = round(sum(1 for _, p, _ in window if p <= cur_pe) / len(window) * 100, 2)
    expect_pb = round(sum(1 for _, _, b in window if b <= cur_pb) / len(window) * 100, 2)
    pct = out["data"]["percentile"]
    assert pct["pe_ttm_pct"] == expect_pe and pct["pb_pct"] == expect_pb
    assert pct["samples"] == len(window) and pct["excluded_nonpositive"] == {"pe_ttm": 0, "pb": 0}


def test_percentile_excludes_nonpositive_and_reports_count():
    frame, dates, pe, pb = _long_frame()
    frame.loc[frame.index[-120:-100], "PE(TTM)"] = -8.0
    svc, _ = make_service(stock_value=frame)
    pct = svc.cn_get_valuation("600519", 3)["data"]["percentile"]
    assert pct["excluded_nonpositive"]["pe_ttm"] == 20
    assert pct["samples_pe_ttm"] == pct["samples"] - 20


def test_percentile_null_when_current_pe_nonpositive():
    frame, *_ = _long_frame()
    frame.loc[frame.index[-1], "PE(TTM)"] = -3.0
    svc, _ = make_service(stock_value=frame)
    pct = svc.cn_get_valuation("600519")["data"]["percentile"]
    assert pct["pe_ttm_pct"] is None and pct["reasons"]["pe_ttm"] == "current_value_nonpositive"
    assert pct["pb_pct"] is not None


def test_percentile_threshold_exactly_sixty():
    dates = business_days("2026-11-13", 60)
    svc, _ = make_service(stock_value=value_frame(dates, [float(i + 1) for i in range(60)]))
    assert svc.cn_get_valuation("600519")["data"]["percentile"]["pe_ttm_pct"] == 100.0
    dates = business_days("2026-11-13", 59)
    svc, _ = make_service(stock_value=value_frame(dates, [float(i + 1) for i in range(59)]))
    assert svc.cn_get_valuation("600519")["data"]["percentile"]["pe_ttm_pct"] is None


def test_window_changes_with_years():
    frame, *_ = _long_frame(n=2200)
    svc, _ = make_service(stock_value=frame)
    one = svc.cn_get_valuation("600519", 1)["data"]["percentile"]["samples"]
    five = svc.cn_get_valuation("600519", 5)["data"]["percentile"]["samples"]
    assert one < five


def test_series_weekly_last_trading_day_no_interpolation():
    frame, dates, pe, pb = _long_frame()
    svc, _ = make_service(stock_value=frame)
    series = svc.cn_get_valuation("600519", 3)["data"]["series"]
    assert 0 < len(series) <= 160
    lookup = {d: (p, b) for d, p, b in zip(dates, pe, pb)}
    for point in series:
        assert point["date"] in lookup
        assert (point["pe_ttm"], point["pb"]) == lookup[point["date"]]
    assert series[-1]["date"] == dates[-1]
    weeks = {pd.Timestamp(p["date"]).isocalendar()[:2] for p in series}
    assert len(weeks) == len(series)


def test_series_cap_for_eight_years_keeps_last_point():
    frame, dates, *_ = _long_frame(n=2200)
    svc, _ = make_service(stock_value=frame)
    data = svc.cn_get_valuation("600519", 8)["data"]
    assert len(data["series"]) <= 160 and data["series_step_weeks"] > 1
    assert data["series"][-1]["date"] == dates[-1]


def test_series_weekly_picks_friday_when_present():
    frame, dates, *_ = _long_frame(n=300)
    svc, _ = make_service(stock_value=frame)
    series = svc.cn_get_valuation("600519", 1)["data"]["series"]
    for point in series[:-1]:
        assert pd.Timestamp(point["date"]).weekday() == 4


def test_valuation_stale_warning():
    frame = value_frame(business_days("2026-10-01", 80), [10.0 + i for i in range(80)])
    svc, _ = make_service(stock_value=frame)
    assert svc.cn_get_valuation("600519")["warnings"] == ["stale_data"]


def test_valuation_fresh_has_no_warning():
    svc, _ = make_service(stock_value=VAL)
    assert "warnings" not in svc.cn_get_valuation("600519")


def test_valuation_unsorted_input_uses_latest_date():
    shuffled = VAL.sample(frac=1, random_state=3)
    svc, _ = make_service(stock_value=shuffled)
    assert svc.cn_get_valuation("600519")["data"]["current"]["date"] == "2026-11-13"


def test_valuation_empty_table():
    svc, _ = make_service(stock_value=VAL.iloc[0:0])
    assert svc.cn_get_valuation("600519")["status"] == "empty"


def test_valuation_error_timeout(monkeypatch):
    svc, _ = make_service(stock_value=RuntimeError("x"))
    assert svc.cn_get_valuation("600519")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = make_service(stock_value=lambda *_: time.sleep(1))
    assert svc.cn_get_valuation("600519")["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("years", [0, 9, -1, "3", 2.0, True, None])
def test_valuation_bad_years_local_reject(years):
    svc, fake = make_service(stock_value=VAL)
    assert svc.cn_get_valuation("600519", years)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


@pytest.mark.parametrize("years", [1, 8])
def test_valuation_year_bounds(years):
    svc, _ = make_service(stock_value=VAL)
    assert svc.cn_get_valuation("600519", years)["status"] == "ready"


def test_valuation_missing_column():
    svc, _ = make_service(stock_value=VAL.drop(columns=["市净率"]))
    assert svc.cn_get_valuation("600519")["error"]["code"] == "upstream_error"


def test_valuation_cached_across_year_params():
    svc, fake = make_service(stock_value=VAL)
    svc.cn_get_valuation("600519", 1)
    svc.cn_get_valuation("600519", 5)
    assert fake.count("stock_value") == 1


def test_valuation_nan_pe_serializes():
    import json

    frame = VAL.copy()
    frame.loc[frame.index[-1], "PE(TTM)"] = float("nan")
    svc, _ = make_service(stock_value=frame)
    out = svc.cn_get_valuation("600519")
    json.dumps(out, allow_nan=False)
    assert out["data"]["current"]["pe_ttm"] is None
