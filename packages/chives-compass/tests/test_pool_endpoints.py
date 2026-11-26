from __future__ import annotations

from datetime import date, datetime

import pytest

from chives_compass.models import CN_TZ
from tests.support import FakeClient, pool_payload, pool_stock
from tests.test_engine import OPEN, make_engine

DAY = date(2026, 11, 3)
PREV = date(2026, 11, 2)
OLDER = date(2026, 10, 30)


def norm(code, name, streak=1, seal="09:30:00", broken=0, amount=1e8, industry="行业A"):
    return {
        "code": code,
        "name": name,
        "price": 10.0,
        "change_pct": 10.0,
        "amount_yuan": amount,
        "turnover_pct": 2.0,
        "streak": streak,
        "first_seal_time": seal,
        "broken_times": broken,
        "industry": industry,
        "seal_amount_yuan": 1e7,
    }


def seed(engine, day, zt=None, zb=None, dt=None, *, available=True, reason=None):
    for kind, rows in (("zt", zt), ("zb", zb), ("dt", dt)):
        if rows is None:
            continue
        engine.store.save_pool_day(
            day, kind, count=len(rows), rows=rows, fetched_at=OPEN,
            available=available, reason=reason,
        )


def engine_with_days(tmp_path, *, promotions=True):
    engine = make_engine(tmp_path)
    zt_prev = [norm("600000.SH", "浦发银行", 1), norm("000001.SZ", "平安银行", 2),
               norm("600001.SH", "邯郸钢铁", 1)]
    zt_today = [norm("600000.SH", "浦发银行", 2), norm("000001.SZ", "平安银行", 3),
                norm("600001.SH", "邯郸钢铁", 1)]
    seed(engine, PREV, zt=zt_prev, zb=[norm("600002.SH", "齐鲁石化", broken=2)],
         dt=[norm("600003.SH", "东北高速")])
    seed(engine, DAY, zt=zt_today, zb=[norm("600004.SH", "白云机场", broken=1),
                                        norm("600005.SH", "武钢股份", broken=3)],
         dt=[norm("600006.SH", "东风汽车")])
    if not promotions:
        engine.store.save_pool_day(PREV, "zt", count=len(zt_prev), rows=zt_prev,
                                   fetched_at=OPEN, available=False, reason="no_data_from_source")
    return engine


def test_pool_default_today_sorted_and_count(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_dict("zt")
    assert payload["ok"] is True
    assert payload["date"] == DAY.isoformat()
    assert payload["count"] == 3
    assert [row["streak"] for row in payload["rows"]] == [3, 2, 1]
    assert payload["definition"].startswith("网关涨停")


def test_pool_limit_truncates_rows_but_not_count(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_dict("zt", limit=1)
    assert len(payload["rows"]) == 1 and payload["count"] == 3


def test_pool_rows_have_contract_fields(tmp_path):
    engine = engine_with_days(tmp_path)
    row = engine.pool_dict("zt")["rows"][0]
    assert set(row) == {
        "code", "name", "price", "change_pct", "amount_yuan", "turnover_pct",
        "streak", "first_seal_time", "broken_times", "industry", "seal_amount_yuan",
    }


def test_pool_explicit_historical_date_from_store(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_dict("zt", PREV.isoformat())
    assert payload["date"] == PREV.isoformat()
    assert payload["count"] == 3
    assert payload["as_of"].startswith(PREV.isoformat())


def test_pool_zb_sorted_by_broken_times(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_dict("zb")
    assert [row["broken_times"] for row in payload["rows"]] == [3, 1]


def test_pool_dt_sorted_by_amount(tmp_path):
    engine = engine_with_days(tmp_path)
    engine.store.save_pool_day(
        DAY, "dt", count=2,
        rows=[norm("600006.SH", "A", amount=1.0), norm("600007.SH", "B", amount=5.0)],
        fetched_at=OPEN,
    )
    payload = engine.pool_dict("dt")
    assert [row["code"] for row in payload["rows"]] == ["600007.SH", "600006.SH"]


def test_pool_unavailable_reason_and_empty_rows(tmp_path):
    engine = engine_with_days(tmp_path)
    seed(engine, OLDER, zt=[], zb=[], dt=[], available=False, reason="no_data_from_source")
    payload = engine.pool_dict("zt", OLDER.isoformat())
    assert payload["ok"] is True and payload["rows"] == []
    assert payload["count"] == 0
    assert payload["reason"] == "no_data_from_source"


def test_pool_on_demand_historical_fetch(tmp_path):
    engine = make_engine(tmp_path)
    client = engine.client
    client.routes.insert(0, (
        "eastmoney_ex", "/getTopicZTPool",
        lambda path, params: pool_payload(
            [pool_stock("000001", "平安银行", market=0)],
            qdate="20261103",
        ),
    ))
    payload = engine.pool_dict("zt", PREV.isoformat())
    assert payload["count"] == 1
    assert payload["rows"][0]["code"] == "000001.SZ"
    record = engine.store.load_pool_day(PREV, "zt")
    assert record is not None and record["available"] is True


def test_pool_today_on_demand_accepts_gateway_rows(tmp_path):
    engine = make_engine(tmp_path)
    engine.client.routes.insert(0, (
        "eastmoney_ex", "/getTopicZTPool",
        lambda path, params: pool_payload([pool_stock("000001", "A")], qdate="20261030"),
    ))
    payload = engine.pool_dict("zt")
    assert payload["rows"][0]["code"] == "000001.SZ"


def test_pool_today_ignores_qdate_for_historical(tmp_path):
    engine = make_engine(tmp_path)
    engine.client.routes.insert(0, (
        "eastmoney_ex", "/getTopicZTPool",
        lambda path, params: pool_payload([pool_stock("000001", "A")], qdate="20261103"),
    ))
    payload = engine.pool_dict("zt", PREV.isoformat())
    assert payload["count"] == 1 and "reason" not in payload


@pytest.mark.parametrize("text", ["2026/11/02", "20261102", "2026-13-01", "bad"])
def test_pool_bad_date_format(tmp_path, text):
    engine = make_engine(tmp_path)
    payload = engine.pool_dict("zt", text)
    assert payload["ok"] is False and payload["error"]["code"] == "bad_request"


def test_pool_non_trading_day(tmp_path):
    engine = make_engine(tmp_path)
    payload = engine.pool_dict("zt", "2026-10-31")
    assert payload["error"]["code"] == "not_trading_day"


def test_pool_future_date(tmp_path):
    engine = make_engine(tmp_path)
    payload = engine.pool_dict("zt", "2026-11-04")
    assert payload["error"]["code"] == "bad_request"


@pytest.mark.parametrize("kind", ["xx", "", "ZT"])
def test_pool_bad_kind(tmp_path, kind):
    engine = make_engine(tmp_path)
    assert engine.pool_dict(kind)["error"]["code"] == "bad_request"


@pytest.mark.parametrize("limit", [0, -1, 501, True])
def test_pool_bad_limit(tmp_path, limit):
    engine = make_engine(tmp_path)
    assert engine.pool_dict("zt", limit=limit)["error"]["code"] == "bad_request"


def test_ladder_tiers(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_ladder_dict()
    assert payload["max_streak"] == 3
    assert payload["first_board_count"] == 1
    assert [tier["streak"] for tier in payload["tiers"]] == [3, 2, 1]
    assert "rows" not in payload["tiers"][-1]


def test_ladder_caps_each_tier_rows(tmp_path):
    engine = make_engine(tmp_path)
    rows = [norm(f"6000{index:02d}.SH", f"S{index}", 2, f"09:3{index % 10}:00")
            for index in range(10)]
    seed(engine, DAY, zt=rows, zb=[], dt=[])
    tier = engine.pool_ladder_dict()["tiers"][0]
    assert tier["count"] == 10 and len(tier["rows"]) == 8


def test_ladder_unavailable(tmp_path):
    engine = make_engine(tmp_path)
    seed(engine, DAY, zt=[], zb=[], dt=[], available=False, reason="no_data_from_source")
    payload = engine.pool_ladder_dict()
    assert payload["tiers"] == [] and payload["max_streak"] is None
    assert payload["reason"] == "no_data_from_source"


def test_history_ascending_and_metrics(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_history_dict(10)
    assert payload["ok"] is True
    dates = [row["date"] for row in payload["days"]]
    assert dates == sorted(dates)
    today = next(row for row in payload["days"] if row["date"] == DAY.isoformat())
    assert today["zt"] == 3 and today["zb"] == 2 and today["dt"] == 1
    assert today["seal_ratio_pct"] == pytest.approx(60.0)


def test_history_promotion_hand_calc(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_history_dict(10)
    today = next(row for row in payload["days"] if row["date"] == DAY.isoformat())
    assert today["promote_1to2_pct"] == pytest.approx(50.0)
    assert today["promote_2to3_pct"] == pytest.approx(100.0)
    assert today["promote_3up_pct"] is None


def test_history_missing_previous_has_null_promotions(tmp_path):
    engine = engine_with_days(tmp_path, promotions=False)
    payload = engine.pool_history_dict(10)
    today = next(row for row in payload["days"] if row["date"] == DAY.isoformat())
    assert today["promote_1to2_pct"] is None
    assert today["available"] is True


def test_history_unavailable_day_not_interpolated(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_history_dict(10)
    older = next(row for row in payload["days"] if row["date"] == OLDER.isoformat())
    assert older["available"] is False
    assert older["zt"] is None and older["seal_ratio_pct"] is None
    assert older["promote_1to2_pct"] is None


@pytest.mark.parametrize("days", [9, 31, 0, True])
def test_history_days_range(tmp_path, days):
    engine = make_engine(tmp_path)
    assert engine.pool_history_dict(days)["error"]["code"] == "bad_request"


def test_by_industry_counts(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_by_industry_dict()
    assert payload["ok"] is True
    assert payload["definition"].startswith("行业口径")
    industry = next(row for row in payload["rows"] if row["industry"] == "行业A")
    assert industry["zt_count"] == 3 and industry["zb_count"] == 2


def test_by_industry_leaders_capped(tmp_path):
    engine = engine_with_days(tmp_path)
    industry = next(row for row in engine.pool_by_industry_dict()["rows"]
                    if row["industry"] == "行业A")
    assert len(industry["leaders"]) <= 3
    assert industry["leaders"][0]["streak"] == 3


def test_pool_history_backfill_state_present(tmp_path):
    engine = engine_with_days(tmp_path)
    payload = engine.pool_history_dict(10)
    assert set(payload["backfill"]) >= {"running", "done", "total"}
