from __future__ import annotations

import pytest

from chives_data.company_parse import normalize_consensus_ths
import time

from chives_data import config
from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.forecast_em = company_fixture("forecast_em.json")
    company.forecast_ths = {
        "预测年报每股收益": company_fixture("forecast_ths_eps_600519.json"),
        "预测年报净利润": company_fixture("forecast_ths_np_600519.json"),
    }
    company.rating_rows = company_fixture("ratings_600519.json")
    return make_service(company_sources=company), company


def test_consensus_and_rating_distribution():
    service, _ = _service()
    payload = service.call("company_consensus", {"code": "600519", "limit": 3})
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["report_count"] == 43
    assert data["rating_counts"]["buy"] == 34
    assert data["rating_counts"]["overweight"] == 9
    assert data["eps_forecast"][-1]["year"] == 2028
    assert data["eps_cross_check"][0]["analysts"] == 44
    profit = data["net_profit_forecast"][0]
    assert profit["mean"] == pytest.approx(83_523_000_000.0)
    assert profit["max"] == pytest.approx(88_497_000_000.0)
    assert data["ratings"]["count"] == 3
    assert data["ratings"]["total_available"] == 6


def test_two_calibers_more_than_five_percent_apart_add_basis():
    service, company = _service()
    company.forecast_ths["预测年报每股收益"][0]["均值"] = 80.0
    payload = service.call("company_consensus", {"code": "600519"})
    assert payload["status"] == "ok"
    assert any(item["field"] == "eps_forecast" for item in payload["basis"])
    assert "5%" in payload["basis"][0]["note"]


def test_cross_check_unavailable_keeps_the_primary_result():
    service, company = _service()
    company.forecast_ths_error = RuntimeError("boom")
    payload = service.call("company_consensus", {"code": "600519"})
    assert payload["status"] == "partial"
    assert payload["data"]["eps_forecast"]
    assert payload["data"]["eps_cross_check"] is None
    assert {item["field"] for item in payload["missing"]} == {"net_profit_forecast"}


def test_ratings_only_still_returns_a_partial_result():
    company = FakeCompanySources()
    company.forecast_em = []
    company.forecast_ths = {}
    company.rating_rows = company_fixture("ratings_002553.json")
    service = make_service(company_sources=company)
    payload = service.call("company_consensus", {"code": "002553"})
    assert payload["status"] == "partial"
    assert payload["data"]["ratings"]["count"] == 2
    assert {item["field"] for item in payload["missing"]} == {"eps_forecast", "net_profit_forecast"}


def test_all_failures_and_bad_arguments_are_unavailable():
    company = FakeCompanySources()
    company.forecast_em_error = RuntimeError("boom")
    company.forecast_ths_error = RuntimeError("boom")
    company.rating_error = RuntimeError("boom")
    service = make_service(company_sources=company)
    payload = service.call("company_consensus", {"code": "600519"})
    assert payload["status"] == "unavailable"
    assert payload["message"]
    for args in ({}, {"code": "600519", "limit": 0}):
        assert service.call("company_consensus", args)["status"] == "unavailable"


def test_first_call_prepares_in_background_and_second_hits_cache(monkeypatch):
    company = FakeCompanySources()
    company.forecast_ths = {
        "预测年报每股收益": company_fixture("forecast_ths_eps_600519.json"),
        "预测年报净利润": company_fixture("forecast_ths_np_600519.json"),
    }
    company.rating_rows = company_fixture("ratings_600519.json")
    release = __import__("threading").Event()

    def slow_forecast():
        release.wait(2)
        return company_fixture("forecast_em.json")

    company.profit_forecast_em = slow_forecast
    monkeypatch.setattr(config, "CALL_BUDGET_SECONDS", 0.05)
    service = make_service(company_sources=company)
    first = service.call("company_consensus", {"code": "600519"})
    assert first["status"] == "unavailable"
    assert "正在准备" in first["message"]
    release.set()
    for _ in range(100):
        if service.cache.get_fresh("company_consensus|600519.SH|20") is not None:
            break
        time.sleep(0.01)
    second = service.call("company_consensus", {"code": "600519"})
    assert second["status"] == "ok"


def test_net_profit_is_converted_from_yi_yuan_to_yuan():
    rows = normalize_consensus_ths(company_fixture("forecast_ths_np_600519.json"), "profit")
    assert rows[0]["mean"] == pytest.approx(835.23 * 1e8)
