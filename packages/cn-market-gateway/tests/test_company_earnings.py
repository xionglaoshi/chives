from __future__ import annotations

import pytest

from fakes import FakeCompanySources, company_fixture, make_service


def _service() -> tuple:
    company = FakeCompanySources()
    company.earnings_rows["forecast"] = company_fixture("yjyg.json")
    company.earnings_rows["express"] = company_fixture("yjkb.json")
    company.earnings_rows["report"] = company_fixture("yjbb.json")
    company.schedule_rows = company_fixture("yysj.json")
    return make_service(company_sources=company), company


def test_forecast_events_keep_the_original_range_and_are_untrusted():
    service, _ = _service()
    payload = service.call(
        "company_earnings", {"kind": "forecast", "period": "2026-09-30", "code": "688827", "limit": 2}
    )
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["untrusted_text"] is True
    first = data["events"][0]
    assert first["code"] == "688827.SH"
    assert first["change_pct_mid"] == pytest.approx(47.77)
    assert first["change_pct_min"] == pytest.approx(37.65)
    assert first["change_pct_max"] == pytest.approx(57.89)
    assert first["forecast_mid_yuan"] == pytest.approx(73_000_000.0)
    assert payload["basis"][0]["field"] == "change_pct_mid"


def test_express_and_report_events_use_yuan_and_percent():
    service, _ = _service()
    express = service.call(
        "company_earnings", {"kind": "express", "period": "2026-09-30", "code": "688235"}
    )
    assert express["status"] == "ok"
    row = express["data"]["events"][0]
    assert row["revenue_yuan"] == pytest.approx(34_993_317_000.0)
    assert row["net_profit_yoy_pct"] == pytest.approx(431.805, abs=0.01)

    report = service.call(
        "company_earnings", {"kind": "report", "period": "2026-09-30", "code": "874923"}
    )
    assert report["status"] == "ok"
    row = report["data"]["events"][0]
    assert row["code"] == "874923.BJ"
    assert row["revenue_yuan"] == pytest.approx(1_189_688_332.77)


def test_schedule_returns_the_current_planned_date():
    service, _ = _service()
    payload = service.call(
        "company_earnings", {"kind": "schedule", "period": "2026-09-30", "code": "002107"}
    )
    assert payload["status"] == "ok"
    row = payload["data"]["items"][0]
    assert row["first_scheduled_date"] == "2026-10-10"
    assert row["current_scheduled_date"] == "2026-10-10"
    assert row["actual_disclosure_date"] == "2026-10-10"


def test_missing_code_or_failed_table_is_unavailable():
    service, company = _service()
    payload = service.call(
        "company_earnings", {"kind": "forecast", "period": "2026-09-30", "code": "600519"}
    )
    assert payload["status"] == "unavailable"
    company.earnings_error = RuntimeError("boom")
    assert service.call("company_earnings", {"kind": "report", "period": "2026-09-30"})["status"] == "unavailable"


def test_earnings_argument_errors():
    service, _ = _service()
    for args in (
        {"kind": "xx"},
        {"kind": "forecast", "period": "2026-02-30"},
        {"kind": "forecast", "limit": 0},
        {"kind": "forecast", "code": "AAPL"},
    ):
        payload = service.call("company_earnings", args)
        assert payload["status"] == "unavailable", args
        assert payload["message"]
