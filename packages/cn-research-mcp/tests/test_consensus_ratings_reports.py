from __future__ import annotations

import time

import pytest

from cn_research_mcp import service as service_module
from helpers import load, make_service

EM = load("em_forecast")
THS = load("ths")


def _svc(**kw):
    kw.setdefault("profit_forecast_em", EM)
    kw.setdefault("profit_forecast_ths", THS)
    return make_service(**kw)


def test_consensus_success_values():
    svc, _ = _svc()
    out = svc.cn_get_consensus("600519")
    assert out["status"] == "ready" and out["ok"] and out["source"] == "eastmoney"
    data = out["data"]
    assert data["code"] == "600519.SH" and data["name"] == "贵州茅台"
    eps = {e["year"]: e["eps_yuan"] for e in data["eps_forecast"]}
    assert eps[2026] == pytest.approx(66.807209, abs=1e-6)
    assert all(e["source"] == "eastmoney" for e in data["eps_forecast"])
    assert data["rating_counts"] == {"buy": 34, "overweight": 9, "neutral": 0, "underweight": 0, "sell": 0}
    assert data["report_count"] == 43
    assert data["cross_check"]["source"] == "ths"
    assert data["cross_check"]["years"][0] == {"year": 2026, "analysts": 44, "min": 64.62, "mean": 66.8, "max": 70.79}
    assert "warnings" not in out


def test_consensus_years_sorted_and_skip_missing():
    svc, _ = _svc()
    em = EM.copy()
    em.loc[em["代码"] == "600519", "2028预测每股收益"] = float("nan")
    svc, _ = _svc(profit_forecast_em=em)
    years = [e["year"] for e in svc.cn_get_consensus("600519")["data"]["eps_forecast"]]
    assert years == [2025, 2026, 2027]


def test_consensus_not_covered_is_empty():
    svc, fake = _svc()
    out = svc.cn_get_consensus("002594")
    assert out["status"] == "empty" and out["ok"] is True
    assert fake.count("profit_forecast_ths") == 0


def test_consensus_zero_reports_and_no_eps_is_empty():
    em = EM.copy()
    mask = em["代码"] == "600519"
    em.loc[mask, "研报数"] = 0
    for col in [c for c in em.columns if "预测每股收益" in c]:
        em.loc[mask, col] = float("nan")
    svc, _ = _svc(profit_forecast_em=em)
    assert svc.cn_get_consensus("600519")["status"] == "empty"


def test_consensus_cross_check_failure_keeps_primary():
    svc, _ = _svc(profit_forecast_ths=ConnectionResetError())
    out = svc.cn_get_consensus("600519")
    assert out["status"] == "ready" and out["data"]["cross_check"] is None
    assert out["warnings"] == ["cross_check_unavailable"]
    assert out["data"]["eps_forecast"]


def test_consensus_cross_check_empty_table_unavailable():
    svc, _ = _svc(profit_forecast_ths=THS.iloc[0:0])
    out = svc.cn_get_consensus("600519")
    assert out["data"]["cross_check"] is None and out["warnings"] == ["cross_check_unavailable"]


def test_consensus_cross_check_bad_shape_unavailable():
    svc, _ = _svc(profit_forecast_ths=THS.drop(columns=["均值"]))
    out = svc.cn_get_consensus("600519")
    assert out["status"] == "ready" and out["warnings"] == ["cross_check_unavailable"]


def test_consensus_sources_disagree_warns_and_keeps_both():
    ths = THS.copy()
    ths["均值"] = ths["均值"] * 1.2
    svc, _ = _svc(profit_forecast_ths=ths)
    out = svc.cn_get_consensus("600519")
    assert "consensus_sources_disagree" in out["warnings"]
    em2026 = {e["year"]: e["eps_yuan"] for e in out["data"]["eps_forecast"]}[2026]
    assert em2026 == pytest.approx(66.807209, abs=1e-6)
    assert out["data"]["cross_check"]["years"][0]["mean"] == pytest.approx(66.8 * 1.2)


def test_consensus_within_threshold_no_warning():
    ths = THS.copy()
    ths["均值"] = ths["均值"] * 1.05
    svc, _ = _svc(profit_forecast_ths=ths)
    assert "warnings" not in svc.cn_get_consensus("600519")


def test_consensus_eastmoney_error():
    svc, _ = _svc(profit_forecast_em=ValueError("bad"))
    out = svc.cn_get_consensus("600519")
    assert out["status"] == "error" and out["error"]["code"] == "upstream_error" and out["ok"] is False


def test_consensus_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "BIG_TABLE_TIMEOUT", 0.1)
    svc, _ = _svc(profit_forecast_em=lambda: time.sleep(1))
    assert svc.cn_get_consensus("600519")["error"]["code"] == "upstream_timeout"


def test_consensus_rate_limited():
    svc, _ = _svc(profit_forecast_em=RuntimeError("429 Too Many Requests"))
    assert svc.cn_get_consensus("600519")["error"]["code"] == "rate_limited"


def test_consensus_missing_columns_is_upstream_error():
    svc, _ = _svc(profit_forecast_em=EM.drop(columns=["研报数"]))
    assert svc.cn_get_consensus("600519")["error"]["code"] == "upstream_error"


@pytest.mark.parametrize("code,err", [("bad", "invalid_argument"), ("920418", "unsupported_market"), (None, "invalid_argument"), (600519, "invalid_argument")])
def test_consensus_bad_code_never_reaches_upstream(code, err):
    svc, fake = _svc()
    out = svc.cn_get_consensus(code)
    assert out["error"]["code"] == err and fake.calls == []


def test_consensus_ten_codes_hit_upstream_once():
    svc, fake = _svc()
    codes = ["600519", "000001", "600036", "601318", "000858", "300750", "002594", "600900", "601899", "000333"]
    for code in codes:
        svc.cn_get_consensus(code)
    assert fake.count("profit_forecast_em") == 1


def test_consensus_cache_expires():
    now = [0.0]
    svc, fake = _svc(clock=lambda: now[0])
    svc.cn_get_consensus("600519")
    now[0] = 29 * 60
    svc.cn_get_consensus("600519")
    assert fake.count("profit_forecast_em") == 1
    now[0] = 31 * 60
    svc.cn_get_consensus("600519")
    assert fake.count("profit_forecast_em") == 2


def test_consensus_uses_digits_for_ths():
    svc, fake = _svc()
    svc.cn_get_consensus("SH600519")
    name, args = next(c for c in fake.calls if c[0] == "profit_forecast_ths")
    assert args[0].digits == "600519"


# ----------------------------------------------------------------- ratings
REC = load("recommend")


def test_ratings_success_sorted_desc_and_units():
    svc, _ = make_service(institute_recommend=REC)
    out = svc.cn_get_ratings("600519", 5)
    items = out["data"]["ratings"]
    assert out["status"] == "ready" and out["source"] == "sina" and len(items) == 5
    dates = [i["date"] for i in items]
    assert dates == sorted(dates, reverse=True) and dates[0] == "2026-11-14"
    assert items[0] == {"date": "2026-11-14", "org": "东方证券", "analyst": "李耀,张玲玉", "rating": "买入", "target_price_yuan": None}
    third = items[2]
    assert third["target_price_yuan"] == pytest.approx(1670.98) and third["org"] == "中金公司"


def test_ratings_sorting_with_shuffled_input():
    shuffled = REC.sample(frac=1, random_state=1)
    svc, _ = make_service(institute_recommend=shuffled)
    dates = [i["date"] for i in svc.cn_get_ratings("600519", 50)["data"]["ratings"]]
    assert dates == sorted(dates, reverse=True)


def test_ratings_default_limit_twenty():
    svc, _ = make_service(institute_recommend=REC)
    assert len(svc.cn_get_ratings("600519")["data"]["ratings"]) == 20


def test_ratings_empty():
    svc, _ = make_service(institute_recommend=REC.iloc[0:0])
    assert svc.cn_get_ratings("600519")["status"] == "empty"


def test_ratings_error_and_timeout(monkeypatch):
    svc, _ = make_service(institute_recommend=RuntimeError("x"))
    assert svc.cn_get_ratings("600519")["error"]["code"] == "upstream_error"
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = make_service(institute_recommend=lambda *_: time.sleep(1))
    assert svc.cn_get_ratings("600519")["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("limit", [0, 51, -1, "5", 5.0, True, None])
def test_ratings_bad_limit_rejected_locally(limit):
    svc, fake = make_service(institute_recommend=REC)
    out = svc.cn_get_ratings("600519", limit)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


@pytest.mark.parametrize("limit", [1, 50])
def test_ratings_limit_bounds_accepted(limit):
    svc, _ = make_service(institute_recommend=REC)
    assert svc.cn_get_ratings("600519", limit)["status"] == "ready"


def test_ratings_cached_per_code():
    svc, fake = make_service(institute_recommend=REC)
    svc.cn_get_ratings("600519")
    svc.cn_get_ratings("600519", 3)
    assert fake.count("institute_recommend") == 1


# ----------------------------------------------------------------- reports
REP = load("reports")


def test_reports_success_untrusted_and_fields():
    svc, _ = make_service(research_report=REP)
    out = svc.cn_get_research_reports("600519", 3)
    assert out["status"] == "ready" and out["data"]["untrusted_text"] is True
    first = out["data"]["reports"][0]
    assert first == {
        "date": "2026-11-13",
        "title": "三季度业绩增速转正，市场化改革重塑渠道和价格体系",
        "org": "太平洋",
        "rating": "增持",
        "link": "https://pdf.dfcfw.com/pdf/H3_AP202611131831700667_1.pdf",
    }
    assert len(out["data"]["reports"]) == 3


def test_reports_missing_link_is_null():
    frame = REP.copy()
    frame.loc[0, "报告PDF链接"] = None
    svc, _ = make_service(research_report=frame)
    assert svc.cn_get_research_reports("600519")["data"]["reports"][0]["link"] is None


def test_reports_empty_still_flags_untrusted():
    svc, _ = make_service(research_report=REP.iloc[0:0])
    out = svc.cn_get_research_reports("600519")
    assert out["status"] == "empty" and out["data"]["untrusted_text"] is True


def test_reports_error():
    svc, _ = make_service(research_report=ConnectionResetError())
    out = svc.cn_get_research_reports("600519")
    assert out["error"]["code"] == "upstream_error"


def test_reports_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "DEFAULT_TIMEOUT", 0.1)
    svc, _ = make_service(research_report=lambda *_: time.sleep(1))
    assert svc.cn_get_research_reports("600519")["error"]["code"] == "upstream_timeout"


@pytest.mark.parametrize("limit", [0, 51, "x", 2.5])
def test_reports_bad_limit(limit):
    svc, fake = make_service(research_report=REP)
    assert svc.cn_get_research_reports("600519", limit)["error"]["code"] == "invalid_argument"
    assert fake.calls == []


def test_reports_bj_code_unsupported():
    svc, fake = make_service(research_report=REP)
    assert svc.cn_get_research_reports("920418")["error"]["code"] == "unsupported_market"
    assert fake.calls == []
