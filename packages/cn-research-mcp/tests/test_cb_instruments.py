from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from cn_research_mcp import calc, service as service_module
from helpers import load, make_service

CB = load("cb_list")
SPOT = load("cb_spot")
CN = timezone(timedelta(hours=8))
NOON = datetime(2026, 11, 16, 11, 35, tzinfo=CN)


def _svc(**kw):
    kw.setdefault("cb_list", CB)
    kw.setdefault("cb_spot", SPOT)
    kw.setdefault("now", lambda: NOON)
    return make_service(**kw)


def _row(out, code):
    return next(item for item in out["data"]["rows"] if item["bond_code"] == code)


# ---------------------------------------------------------------- formula
def test_conversion_value_formula_exact():
    assert calc.bond_conversion_value(15.0, 18.0) == pytest.approx(120.0, abs=1e-12)


def test_premium_formula_exact():
    assert calc.bond_premium_pct(125.0, 120.0) == pytest.approx(4.1666666667, abs=1e-9)


@pytest.mark.parametrize(
    "conversion_price,underlying_price",
    [(None, 18.0), (15.0, None), (0, 18.0), (-1, 18.0), (15.0, float("nan")), ("bad", 18.0)],
)
def test_conversion_value_missing_inputs_return_none(conversion_price, underlying_price):
    assert calc.bond_conversion_value(conversion_price, underlying_price) is None


@pytest.mark.parametrize(
    "price,value",
    [(None, 120.0), (125.0, None), (125.0, 0), (125.0, -1), ("bad", 120.0), (125.0, float("nan"))],
)
def test_premium_missing_inputs_return_none(price, value):
    assert calc.bond_premium_pct(price, value) is None


@pytest.mark.parametrize(
    "today,expected",
    [
        (datetime(2026, 11, 16).date(), ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]),
        (datetime(2026, 9, 30).date(), ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]),
        (datetime(2026, 1, 15).date(), ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"]),
    ],
)
def test_recent_report_periods(today, expected):
    assert calc.recent_report_periods(today, 5) == expected


def test_recent_report_periods_rejects_zero():
    with pytest.raises(ValueError):
        calc.recent_report_periods(datetime(2026, 11, 16).date(), 0)


# ---------------------------------------------------------------- cb list
def test_cb_list_success_and_values():
    svc, _ = _svc()
    out = svc.cn_get_cb_list()
    assert out["status"] == "ready" and out["ok"] is True and out["source"] == "eastmoney"
    row = _row(out, "113643")
    assert row["bond_name"] == "风语转债"
    assert row["underlying_code"] == "603466.SH"
    assert row["conversion_price_yuan"] == pytest.approx(11.8)
    assert row["underlying_price_yuan"] == pytest.approx(15.86)
    assert row["conversion_value_yuan"] == pytest.approx(134.4068)
    assert row["premium_pct"] == pytest.approx(12.38)
    assert row["listing_status"] == "listed"
    assert row["listing_date"] == "2022-04-22"


def test_cb_list_drops_unlisted_row():
    svc, _ = _svc()
    out = svc.cn_get_cb_list(limit=500)
    assert "111027" not in {item["bond_code"] for item in out["data"]["rows"]}
    assert out["data"]["dropped_unlisted"] >= 1


def test_cb_list_drops_delisted_row():
    svc, _ = _svc()
    out = svc.cn_get_cb_list(limit=500)
    assert "404002" not in {item["bond_code"] for item in out["data"]["rows"]}
    assert out["data"]["dropped_delisted"] >= 1


@pytest.mark.parametrize("code", ["128044", "118065"])
def test_cb_list_unknown_status_without_underlying_price(code):
    svc, _ = _svc()
    out = svc.cn_get_cb_list(limit=500)
    assert _row(out, code)["listing_status"] == "unknown"


@pytest.mark.parametrize("underlying", ["603466", "603466.SH", "sh603466"])
def test_cb_list_underlying_filter(underlying):
    svc, _ = _svc()
    out = svc.cn_get_cb_list(underlying=underlying)
    assert [item["bond_code"] for item in out["data"]["rows"]] == ["113643"]


def test_cb_list_underlying_no_match_is_empty():
    svc, _ = _svc()
    out = svc.cn_get_cb_list(underlying="600519")
    assert out["status"] == "empty" and out["data"]["rows"] == []


@pytest.mark.parametrize("underlying,err", [("bad", "invalid_argument"), ("920418", "unsupported_market"), (600519, "invalid_argument")])
def test_cb_list_bad_underlying_never_reaches_upstream(underlying, err):
    svc, fake = _svc()
    out = svc.cn_get_cb_list(underlying=underlying)
    assert out["error"]["code"] == err and fake.calls == []


@pytest.mark.parametrize("limit", [0, -1, 501, 1.5, "5", True])
def test_cb_list_bad_limit(limit):
    svc, fake = _svc()
    out = svc.cn_get_cb_list(limit=limit)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_cb_list_limit_and_totals():
    svc, _ = _svc()
    out = svc.cn_get_cb_list(limit=3)
    assert len(out["data"]["rows"]) == 3
    assert out["data"]["returned"] == 3
    assert out["data"]["total_available"] > 3


def test_cb_list_upstream_error():
    svc, _ = _svc(cb_list=ValueError("bad"))
    assert svc.cn_get_cb_list()["error"]["code"] == "upstream_error"


def test_cb_list_rate_limited():
    svc, _ = _svc(cb_list=RuntimeError("429 Too Many Requests"))
    assert svc.cn_get_cb_list()["error"]["code"] == "rate_limited"


def test_cb_list_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "BIG_TABLE_TIMEOUT", 0.1)
    svc, _ = _svc(cb_list=lambda: time.sleep(1))
    assert svc.cn_get_cb_list()["error"]["code"] == "upstream_timeout"


def test_cb_list_empty_table():
    svc, _ = _svc(cb_list=CB.iloc[0:0])
    out = svc.cn_get_cb_list()
    assert out["status"] == "empty" and out["data"]["rows"] == []


def test_cb_list_missing_columns():
    svc, _ = _svc(cb_list=CB.drop(columns=["转股价"]))
    assert svc.cn_get_cb_list()["error"]["code"] == "upstream_error"


def test_cb_list_computes_missing_conversion_value_only():
    table = CB.copy()
    mask = table["债券代码"].astype(str).str.zfill(6) == "113643"
    table.loc[mask, "转股价值"] = float("nan")
    table.loc[mask, "转股溢价率"] = float("nan")
    svc, _ = _svc(cb_list=table)
    row = _row(svc.cn_get_cb_list(limit=500), "113643")
    assert row["conversion_value_yuan"] == pytest.approx(134.4068, abs=1e-4)
    assert row["premium_pct"] is None
    assert row["conversion_value_computed"] is True and "premium_computed" not in row


# ---------------------------------------------------------------- cb quote
def test_cb_quote_success_computes_values():
    svc, _ = _svc()
    out = svc.cn_get_cb_quote(["113643"])
    assert out["status"] == "ready" and out["source"] == "sina" and out["data"]["computed"] is True
    row = _row(out, "113643")
    assert row["name"] == "风语转债"
    assert row["price_yuan"] == pytest.approx(151.042)
    assert row["change_pct"] == pytest.approx(-4.421)
    assert row["underlying_code"] == "603466.SH"
    assert row["conversion_price_yuan"] == pytest.approx(11.8)
    assert row["underlying_price_yuan"] == pytest.approx(15.86)
    assert row["conversion_value_yuan"] == pytest.approx(134.4068, abs=1e-4)
    assert row["premium_pct"] == pytest.approx(12.3766, abs=1e-3)
    assert "not a real-time quote" in row["quote_note"]
    assert "computed by this server" in row["quote_note"]
    assert "2026-11-16T11:35:00+08:00" in row["quote_note"]
    assert "warnings" not in out


def test_cb_quote_multiple_codes_order_preserved():
    svc, _ = _svc()
    out = svc.cn_get_cb_quote(["123291", "113643"])
    assert [row["bond_code"] for row in out["data"]["rows"]] == ["123291", "113643"]


def test_cb_quote_missing_terms_row_keeps_quote():
    svc, _ = _svc()
    out = svc.cn_get_cb_quote(["999999", "113643"])
    missing = _row(out, "999999")
    assert missing["price_yuan"] is None and missing["conversion_value_yuan"] is None
    assert missing["reasons"] == {
        "quote": "bond_not_in_spot_snapshot",
        "terms": "bond_not_in_terms_table",
        "conversion_price": "missing_or_non_numeric",
        "underlying_price": "missing_or_non_numeric",
        "price": "missing_or_non_numeric",
        "conversion_value": "conversion_price_unusable",
        "premium_pct": "price_unusable",
    }
    assert out["status"] == "ready"


def test_cb_quote_all_missing_is_empty():
    svc, _ = _svc()
    out = svc.cn_get_cb_quote(["999999"])
    assert out["status"] == "empty" and out["data"]["rows"][0]["price_yuan"] is None


def test_cb_quote_zero_price_is_empty_and_flagged():
    svc, _ = _svc()
    out = svc.cn_get_cb_quote(["810011"])
    row = out["data"]["rows"][0]
    assert out["status"] == "empty"
    assert row["price_yuan"] == 0.0 and row["premium_pct"] is None
    assert row["reasons"]["price"] == "nonpositive"


def test_cb_quote_missing_conversion_price_returns_null():
    svc, _ = _svc()
    row = _row(svc.cn_get_cb_quote(["110072"]), "110072")
    assert row["price_yuan"] == pytest.approx(44.267)
    assert row["conversion_price_yuan"] is None
    assert row["conversion_value_yuan"] is None and row["premium_pct"] is None
    assert row["reasons"]["conversion_price"] == "missing_or_non_numeric"
    assert row["reasons"]["conversion_value"] == "conversion_price_unusable"
    assert row["reasons"]["premium_pct"] == "conversion_value_missing"


def test_cb_quote_empty_terms_still_returns_price():
    svc, _ = _svc(cb_list=CB.iloc[0:0])
    out = svc.cn_get_cb_quote(["113643"])
    row = out["data"]["rows"][0]
    assert out["status"] == "ready" and row["price_yuan"] == pytest.approx(151.042)
    assert row["conversion_value_yuan"] is None
    assert row["reasons"]["terms"] == "bond_not_in_terms_table"


def test_cb_quote_empty_spot_is_empty():
    svc, _ = _svc(cb_spot=SPOT.iloc[0:0])
    out = svc.cn_get_cb_quote(["113643"])
    assert out["status"] == "empty"
    assert out["data"]["rows"][0]["conversion_price_yuan"] == pytest.approx(11.8)


def test_cb_quote_price_time_mismatch_warning():
    clock = [NOON]
    svc, _ = make_service(cb_list=CB, cb_spot=SPOT, now=lambda: clock[0])
    assert "warnings" not in svc.cn_get_cb_quote(["113643"])
    clock[0] = NOON + timedelta(days=1)
    out = svc.cn_get_cb_quote(["113643"])
    assert out["warnings"] == ["price_time_mismatch"]


def test_cb_quote_caches_both_tables():
    svc, fake = _svc()
    svc.cn_get_cb_quote(["113643"])
    svc.cn_get_cb_quote(["123291"])
    assert fake.count("cb_list") == 1 and fake.count("cb_spot") == 1


@pytest.mark.parametrize(
    "codes",
    [[], ["1"], ["113643"] * 21, ["abcdef"], [113643], "113643", None, ["113643", 123291]],
)
def test_cb_quote_bad_codes_never_reach_upstream(codes):
    svc, fake = _svc()
    out = svc.cn_get_cb_quote(codes)
    assert out["error"]["code"] == "invalid_argument" and fake.calls == []


def test_cb_quote_upstream_error():
    svc, _ = _svc(cb_spot=ValueError("bad"))
    assert svc.cn_get_cb_quote(["113643"])["error"]["code"] == "upstream_error"


def test_cb_quote_rate_limited():
    svc, _ = _svc(cb_spot=RuntimeError("请求过于频繁"))
    assert svc.cn_get_cb_quote(["113643"])["error"]["code"] == "rate_limited"


def test_cb_quote_timeout(monkeypatch):
    monkeypatch.setattr(service_module, "BIG_TABLE_TIMEOUT", 0.1)
    svc, _ = _svc(cb_spot=lambda: time.sleep(1))
    assert svc.cn_get_cb_quote(["113643"])["error"]["code"] == "upstream_timeout"


def test_cb_quote_missing_spot_columns():
    svc, _ = _svc(cb_spot=SPOT.drop(columns=["trade"]))
    assert svc.cn_get_cb_quote(["113643"])["error"]["code"] == "upstream_error"
