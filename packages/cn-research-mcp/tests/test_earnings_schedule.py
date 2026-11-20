from __future__ import annotations

import json
import time

import pandas as pd
import pytest

from cn_research_mcp import service as service_module
from cn_research_mcp.service import _parse_change_range
from helpers import load, make_service

YJYG = load("yjyg")
YJKB = load("yjkb")
YJBB = load("yjbb")
YYSJ = load("yysj")


def _svc(**kw):
    kw.setdefault("yjyg", YJYG)
    kw.setdefault("yjkb", YJKB)
    kw.setdefault("yjbb", YJBB)
    kw.setdefault("yysj", YYSJ)
    return make_service(**kw)


@pytest.mark.parametrize(
    "text,low,high",
    [
        ("预计2026年1-9月归属于上市公司股东的净利润盈利:6,800万元至7,800万元,同比上年增长:37.65%至57.89%。", 37.65, 57.89),
        ("预计2026年1-9月营业收入:10,500万元至11,500万元,同比上年下降:36%至42%。", -42.0, -36.0),
        ("预计2026年1-9月净利润盈利:8,573.78万元至10,064.88万元,同比上年变动:-13.73%至1.27%。", -13.73, 1.27),
        ("预计2026年1-9月净利润亏损:6,593万元至7,287万元,同比上年下降:281.29%至300.37%,同比上年降低10,229.77万元。", -300.37, -281.29),
        ("预计2026年1-9月净利润盈利约:27,300万元,同比上年增长:116%左右,同比上年增长14,700万元左右。", 116.0, 116.0),
        ("预计2026年1-9月净利润盈利约:33,600万元。", None, None),
        (None, None, None),
    ],
)
def test_parse_change_range(text, low, high):
    assert _parse_change_range(text) == (low, high)


def test_forecast_success_fields_and_units():
    svc, fake = _svc()
    out = svc.cn_get_earnings_events("2026-09-30", "forecast", limit=200)
    assert out["status"] == "ready" and out["source"] == "eastmoney" and out["data"]["untrusted_text"] is True
    assert fake.calls == [("yjyg", ("20260930",))]
    first = next(e for e in out["data"]["events"] if e["code"] == "688827.SH" and e["metric"] == "归属于上市公司股东的净利润")
    assert first["forecast_type"] == "预增" and first["announce_date"] == "2026-11-04"
    assert first["forecast_mid_yuan"] == 73000000.0 and first["prior_year_yuan"] == 49401300.0
    assert first["change_pct_mid"] == pytest.approx(47.77)
    assert (first["change_pct_min"], first["change_pct_max"]) == (37.65, 57.89)
    # midpoint of 6,800万..7,800万 is 7,300万 = 73,000,000 yuan, mid % is the midpoint of the range
    assert first["forecast_mid_yuan"] == (68_000_000 + 78_000_000) / 2
    assert first["change_pct_mid"] == pytest.approx((37.65 + 57.89) / 2)
    assert first["forecast_mid_yuan"] / first["prior_year_yuan"] - 1 == pytest.approx(first["change_pct_mid"] / 100, abs=1e-4)


def test_forecast_eps_rows_use_per_share_fields():
    svc, _ = _svc()
    events = svc.cn_get_earnings_events("2026-09-30", "forecast", limit=200)["data"]["events"]
    eps = [e for e in events if e["metric"] == "每股收益"]
    assert eps
    for event in eps:
        assert event["forecast_mid_yuan"] is None and event["forecast_mid_eps_yuan"] is not None


def test_forecast_loss_rows_negative_values():
    svc, _ = _svc()
    events = svc.cn_get_earnings_events("2026-09-30", "forecast", limit=200)["data"]["events"]
    loss = [e for e in events if e["forecast_type"] in ("减亏", "首亏")]
    assert loss and all(e["forecast_mid_yuan"] is None or e["forecast_mid_yuan"] < 0 for e in loss)


def test_forecast_sorted_by_announce_date_desc():
    svc, _ = _svc()
    dates = [e["announce_date"] for e in svc.cn_get_earnings_events("2026-09-30", "forecast", limit=200)["data"]["events"]]
    assert dates == sorted(dates, reverse=True)


def test_forecast_filter_by_code_only_that_stock():
    svc, _ = _svc()
    out = svc.cn_get_earnings_events("2026-09-30", "forecast", code="688827")
    events = out["data"]["events"]
    assert events and {e["code"] for e in events} == {"688827.SH"}
    assert len(events) == out["data"]["total_matching"]


def test_forecast_code_without_rows_is_empty():
    svc, _ = _svc()
    assert svc.cn_get_earnings_events("2026-09-30", "forecast", code="600519")["status"] == "empty"


def test_forecast_limit():
    svc, _ = _svc()
    assert len(svc.cn_get_earnings_events("2026-09-30", "forecast", limit=2)["data"]["events"]) == 2


def test_express_fields():
    svc, fake = _svc()
    out = svc.cn_get_earnings_events("2026-09-30", "express")
    assert fake.calls == [("yjkb", ("20260930",))]
    event = next(e for e in out["data"]["events"] if e["code"] == "688235.SH")
    assert event["revenue_yuan"] == pytest.approx(34993317000.0) and event["eps_yuan"] == 4.16
    assert event["net_profit_yuan"] == pytest.approx(6055116000.0)
    assert event["revenue_yoy_pct"] == pytest.approx(26.809283)
    assert "营业收入-季度环比增长" in event["unconfirmed_upstream"]


def test_express_yoy_recomputes_from_prior_year_column():
    svc, _ = _svc()
    for event in svc.cn_get_earnings_events("2026-09-30", "express")["data"]["events"]:
        if event["revenue_yuan"] and event["revenue_prior_yuan"]:
            calc = (event["revenue_yuan"] / event["revenue_prior_yuan"] - 1) * 100
            assert calc == pytest.approx(event["revenue_yoy_pct"], abs=0.01)


def test_report_fields_and_cross_checks():
    svc, fake = _svc()
    out = svc.cn_get_earnings_events("2026-09-30", "report", code="600519.SH")
    assert fake.calls == [("yjbb", ("20260930",))]
    event = out["data"]["events"][0]
    assert event["code"] == "600519.SH" and event["announce_date"] == "2026-10-31"
    assert event["net_profit_yuan"] == pytest.approx(64467425981.95, rel=1e-9)
    # EPS * total shares (1,250,081,601 from valuation data) approximates net profit in yuan
    assert event["eps_yuan"] * 1250081601 == pytest.approx(event["net_profit_yuan"], rel=0.01)
    assert event["bps_yuan"] == pytest.approx(216.94963)
    assert set(event["unconfirmed_upstream"]) == {
        "营业总收入-季度环比增长", "净利润-季度环比增长", "每股经营现金流量", "销售毛利率"
    }


def test_report_event_has_no_untrusted_flag():
    svc, _ = _svc()
    assert "untrusted_text" not in svc.cn_get_earnings_events("2026-09-30", "report")["data"]


@pytest.mark.parametrize("kind", ["forecast", "express", "report"])
def test_events_empty_table(kind):
    svc, _ = _svc(yjyg=YJYG.iloc[0:0], yjkb=YJKB.iloc[0:0], yjbb=YJBB.iloc[0:0])
    assert svc.cn_get_earnings_events("2026-09-30", kind)["status"] == "empty"


@pytest.mark.parametrize("kind", ["forecast", "express", "report"])
def test_events_upstream_error(kind):
    err = ConnectionResetError()
    svc, _ = _svc(yjyg=err, yjkb=err, yjbb=err)
    out = svc.cn_get_earnings_events("2026-09-30", kind)
    assert out["status"] == "error" and out["error"]["code"] == "upstream_error"


@pytest.mark.parametrize("kind", ["forecast", "express", "report"])
def test_events_timeout(kind, monkeypatch):
    monkeypatch.setattr(service_module, "BIG_TABLE_TIMEOUT", 0.1)
    slow = lambda d: time.sleep(1)  # noqa: E731
    svc, _ = _svc(yjyg=slow, yjkb=slow, yjbb=slow)
    assert svc.cn_get_earnings_events("2026-09-30", kind)["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("period", ["2026-09-29", "2026-9-30", "20260930", "2026-10-31", "2026-03-30", "", None, 2026, "1999-12-31", "2101-03-31"])
def test_events_bad_period_rejected_locally(period):
    svc, fake = _svc()
    out = svc.cn_get_earnings_events(period, "forecast")
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("period", ["2026-03-31", "2026-06-30", "2026-09-30", "2025-12-31"])
def test_events_valid_periods(period):
    svc, fake = _svc()
    svc.cn_get_earnings_events(period, "forecast")
    assert fake.calls[0][1] == (period.replace("-", ""),)


@pytest.mark.parametrize("kind", ["", "forecasts", None, "REPORT", 1])
def test_events_bad_kind(kind):
    svc, fake = _svc()
    assert svc.cn_get_earnings_events("2026-09-30", kind)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


@pytest.mark.parametrize("limit", [0, 201, "3", 1.5, True])
def test_events_bad_limit(limit):
    svc, fake = _svc()
    assert svc.cn_get_earnings_events("2026-09-30", "forecast", None, limit)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def test_events_bad_and_bj_code():
    svc, fake = _svc()
    assert svc.cn_get_earnings_events("2026-09-30", "forecast", "xx")["error"]["code"] == "invalid_argument"
    assert svc.cn_get_earnings_events("2026-09-30", "forecast", "920107")["error"]["code"] == "unsupported_market"
    assert fake.calls == []


def test_events_many_codes_hit_upstream_once():
    svc, fake = _svc()
    for code in ["688827", "688235", "600519", "000001", "300107", "603092", "600882", "000856", "688662", "002107"]:
        svc.cn_get_earnings_events("2026-09-30", "report", code=code)
    assert fake.count("yjbb") == 1


def test_events_report_strict_json():
    svc, _ = _svc()
    for kind in ("forecast", "express", "report"):
        json.dumps(svc.cn_get_earnings_events("2026-09-30", kind, limit=200), allow_nan=False)


def test_events_missing_column_is_upstream_error():
    svc, _ = _svc(yjbb=YJBB.drop(columns=["最新公告日期"]))
    assert svc.cn_get_earnings_events("2026-09-30", "report")["error"]["code"] == "upstream_error"


# ------------------------------------------------------------- schedule
def test_schedule_success_fields():
    svc, fake = _svc()
    out = svc.cn_get_disclosure_schedule("2026-09-30", code="600519.SH")
    assert fake.calls == [("yysj", ("20260930",))]
    item = out["data"]["items"][0]
    assert item == {
        "code": "600519.SH",
        "name": "贵州茅台",
        "first_scheduled_date": "2026-10-31",
        "change_dates": [],
        "current_scheduled_date": "2026-10-31",
        "actual_disclosure_date": "2026-10-31",
    }


def test_schedule_change_dates_and_current_date():
    svc, _ = _svc()
    items = svc.cn_get_disclosure_schedule("2026-09-30", limit=200)["data"]["items"]
    changed = [i for i in items if i["change_dates"]]
    assert changed
    for item in changed:
        assert item["current_scheduled_date"] == item["change_dates"][-1]


def test_schedule_actual_date_null_when_not_disclosed():
    frame = YYSJ.copy()
    frame.loc[frame["股票代码"] == "600519", "实际披露时间"] = None
    svc, _ = _svc(yysj=frame)
    item = svc.cn_get_disclosure_schedule("2026-09-30", code="600519")["data"]["items"][0]
    assert item["actual_disclosure_date"] is None


def test_schedule_sorted_by_current_date_ascending():
    svc, _ = _svc()
    dates = [i["current_scheduled_date"] for i in svc.cn_get_disclosure_schedule("2026-09-30", limit=200)["data"]["items"]]
    assert dates == sorted(dates)


def test_schedule_accepts_date_objects_and_nat():
    frame = pd.DataFrame(
        {
            "股票代码": ["600519"],
            "股票简称": ["贵州茅台"],
            "首次预约时间": [pd.Timestamp("2026-10-31").date()],
            "一次变更日期": [pd.NaT],
            "二次变更日期": [None],
            "三次变更日期": [pd.NaT],
            "实际披露时间": [pd.Timestamp("2026-10-31").date()],
        }
    )
    svc, _ = _svc(yysj=frame)
    item = svc.cn_get_disclosure_schedule("2026-09-30")["data"]["items"][0]
    assert item["first_scheduled_date"] == "2026-10-31" and item["change_dates"] == []


def test_schedule_limit_and_total():
    svc, _ = _svc()
    out = svc.cn_get_disclosure_schedule("2026-09-30", limit=5)
    assert len(out["data"]["items"]) == 5 and out["data"]["total_matching"] == len(YYSJ)


def test_schedule_code_absent_empty_and_table_empty():
    svc, _ = _svc()
    assert svc.cn_get_disclosure_schedule("2026-09-30", code="601398")["status"] == "empty"
    svc, _ = _svc(yysj=YYSJ.iloc[0:0])
    assert svc.cn_get_disclosure_schedule("2026-09-30")["status"] == "empty"


def test_schedule_error_and_timeout(monkeypatch):
    svc, _ = _svc(yysj=ConnectionResetError())
    assert svc.cn_get_disclosure_schedule("2026-09-30")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "BIG_TABLE_TIMEOUT", 0.1)
    svc, _ = _svc(yysj=lambda d: time.sleep(1))
    assert svc.cn_get_disclosure_schedule("2026-09-30")["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("period", ["2026-09-29", None, "20260930", ""])
def test_schedule_bad_period(period):
    svc, fake = _svc()
    assert svc.cn_get_disclosure_schedule(period)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


@pytest.mark.parametrize("limit", [0, 201, "2", True])
def test_schedule_bad_limit(limit):
    svc, fake = _svc()
    assert svc.cn_get_disclosure_schedule("2026-09-30", None, limit)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def test_schedule_ten_codes_one_upstream_call():
    svc, fake = _svc()
    for code in ["600519", "002107", "000856", "688981", "600036", "000001", "300750", "601318", "000333", "600900"]:
        svc.cn_get_disclosure_schedule("2026-09-30", code=code)
    assert fake.count("yysj") == 1
