from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta

import pytest

from chives_compass.gateway import SourceError
from chives_compass.models import CN_TZ
from tests.support import pool_payload, pool_stock
from tests.test_engine import OPEN, make_engine

DAY = date(2026, 11, 3)
PREV = date(2026, 11, 2)
FRI = date(2026, 11, 6)
THU = date(2026, 11, 5)


def quote_row(code, name="股票", price=10.8, prev=10.0, open_=10.5, high=11.2, low=9.8,
              amount=1e8, time_text="20261103103000"):
    prefix = "sh" if code.endswith(".SH") else "bj" if code.endswith(".BJ") else "sz"
    digits = code.split(".")[0]
    fields = [""] * 88
    fields[1] = name
    fields[3] = f"{price:.2f}"
    fields[4] = f"{prev:.2f}"
    fields[5] = f"{open_:.2f}"
    fields[6] = "100000"
    fields[30] = time_text
    fields[32] = f"{(price / prev - 1) * 100:.2f}"
    fields[33] = f"{high:.2f}"
    fields[34] = f"{low:.2f}"
    fields[35] = f"{price:.2f}/100000/{amount:.0f}"
    fields[37] = f"{amount / 10000:.0f}"
    fields[47] = "-1"
    fields[48] = "-1"
    return f'v_{prefix}{digits}="' + "~".join(fields) + '";'


def quote_feed(mapping, calls=None, gate=None):
    def reader(path, params):
        if gate is not None:
            gate.wait(timeout=3)
        if calls is not None:
            calls.append(path)
        symbols = path.split("=", 1)[1].split(",")
        lines = []
        for symbol in symbols:
            prefix, digits = symbol[:2], symbol[2:]
            suffix = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[prefix]
            code = f"{digits}.{suffix}"
            row = mapping.get(code)
            if row:
                lines.append(quote_row(code, **row))
        return "\n".join(lines)

    return reader


def norm(code, name, streak=1):
    return {
        "code": code, "name": name, "price": 10.0, "change_pct": 10.0,
        "amount_yuan": 1e8, "turnover_pct": 1.0, "streak": streak,
        "first_seal_time": "09:30:00", "broken_times": 0, "industry": "行业A",
        "seal_amount_yuan": 1e7,
    }


def seed(engine, day, rows):
    engine.store.save_pool_day(day, "zt", count=len(rows), rows=rows, fetched_at=OPEN)


def test_yesterday_basic_percentages(tmp_path):
    feed = quote_feed({"600000.SH": {"open_": 10.5, "high": 11.2, "low": 9.8, "price": 10.8,
                                     "prev": 10.0}})
    engine = make_engine(tmp_path, feed=feed)
    engine._trading_state = "open"
    seed(engine, PREV, [norm("600000.SH", "浦发银行", 2)])
    payload = engine.pool_yesterday_dict()
    row = payload["rows"][0]
    assert row["open_pct"] == pytest.approx(5.0)
    assert row["high_pct"] == pytest.approx(12.0)
    assert row["low_pct"] == pytest.approx(-2.0)
    assert row["now_pct"] == pytest.approx(8.0)
    assert row["prev_streak"] == 2


def test_yesterday_averages_and_win_ratio(tmp_path):
    feed = quote_feed({
        "600000.SH": {"open_": 10.0, "high": 10.5, "low": 9.5, "price": 10.2, "prev": 10.0},
        "600001.SH": {"open_": 10.0, "high": 10.2, "low": 9.4, "price": 9.8, "prev": 10.0},
    })
    engine = make_engine(tmp_path, feed=feed)
    engine._trading_state = "open"
    seed(engine, PREV, [norm("600000.SH", "A"), norm("600001.SH", "B")])
    payload = engine.pool_yesterday_dict()
    assert payload["avg_open_pct"] == pytest.approx(0.0)
    assert payload["avg_high_pct"] == pytest.approx(3.5)
    assert payload["avg_close_pct"] == pytest.approx(0.0)
    assert payload["win_ratio_pct"] == pytest.approx(50.0)


def test_yesterday_dates(tmp_path):
    feed = quote_feed({"600000.SH": {"prev": 10.0}})
    engine = make_engine(tmp_path, feed=feed)
    engine._trading_state = "open"
    seed(engine, PREV, [norm("600000.SH", "A")])
    payload = engine.pool_yesterday_dict()
    assert payload["date"] == DAY.isoformat()
    assert payload["prev_date"] == PREV.isoformat()


def test_yesterday_pre_open_returns_empty(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "pre_open"
    payload = engine.pool_yesterday_dict()
    assert payload["rows"] == []
    assert "尚未开盘" in payload["reason"]


def test_yesterday_missing_previous_pool(tmp_path):
    engine = make_engine(tmp_path, feed=quote_feed({}))
    engine._trading_state = "open"
    engine.client.routes.insert(0, (
        "eastmoney_ex", "/getTopicZTPool",
        lambda path, params: pool_payload([], tc=0, qdate="20261103"),
    ))
    payload = engine.pool_yesterday_dict()
    assert payload["rows"] == []
    assert "涨停池不可用" in payload["reason"]


def test_yesterday_no_snapshot_returns_empty(tmp_path):
    engine = make_engine(tmp_path, feed=quote_feed({}))
    engine._trading_state = "open"
    seed(engine, PREV, [norm("600000.SH", "A")])
    payload = engine.pool_yesterday_dict()
    assert payload["rows"] == [] and "快照" in payload["reason"]


def test_yesterday_holiday_uses_last_trading_day(tmp_path):
    feed = quote_feed({"600000.SH": {"prev": 10.0, "price": 10.5}})
    saturday = datetime(2026, 11, 7, 10, 30, tzinfo=CN_TZ)
    holder, clock = (None, lambda: saturday)
    engine = make_engine(tmp_path, feed=feed, clock=(holder, clock))
    engine._trading_state = "holiday"
    seed(engine, THU, [norm("600000.SH", "A")])
    payload = engine.pool_yesterday_dict()
    assert payload["date"] == FRI.isoformat()
    assert payload["prev_date"] == THU.isoformat()
    assert payload["state_note"] == "休市，显示上一交易时段最后值"


def test_yesterday_batches_by_gateway_limit(tmp_path):
    calls = []
    mapping = {f"60{index:04d}.SH": {"prev": 10.0} for index in range(100)}
    feed = quote_feed(mapping, calls=calls)
    engine = make_engine(tmp_path, feed=feed)
    engine._trading_state = "open"
    seed(engine, PREV, [norm(code, code) for code in mapping])
    payload = engine.pool_yesterday_dict()
    assert len(payload["rows"]) == 100
    assert len(calls) == 5


def test_yesterday_definition(tmp_path):
    engine = make_engine(tmp_path, feed=quote_feed({}))
    engine._trading_state = "open"
    assert engine.pool_yesterday_dict()["definition"].startswith("昨日涨停股今日表现")


def test_yesterday_cache_reuses_result(tmp_path):
    calls = []
    feed = quote_feed({"600000.SH": {"prev": 10.0}}, calls=calls)
    engine = make_engine(tmp_path, feed=feed)
    engine._trading_state = "open"
    seed(engine, PREV, [norm("600000.SH", "A")])
    engine.pool_yesterday_dict()
    engine.pool_yesterday_dict()
    assert len(calls) == 1


# -- backfill -------------------------------------------------------------

def install_backfill_routes(engine, *, fail_date=None, tc_zero_date=None,
                            qdate_override=None, gate=None, calls=None):
    clock = {"now": 0.0}

    def reader(kind):
        path = { "zt": "/getTopicZTPool", "zb": "/getTopicZBPool",
                 "dt": "/getTopicDTPool"}[kind]

        def read(request_path, params):
            if gate is not None:
                gate.wait(timeout=3)
            if calls is not None:
                calls.append((params["date"], kind, clock["now"]))
            date_text = params["date"]
            if fail_date and date_text == fail_date:
                raise SourceError("upstream_http", "down")
            if tc_zero_date and date_text == tc_zero_date:
                return pool_payload([], tc=0, qdate=qdate_override or "20261103")
            return pool_payload(
                [pool_stock("000001", "平安银行", market=0, streak=1 + len(kind))],
                qdate=qdate_override or "20261103",
            )

        return path, read

    for kind in ("zt", "zb", "dt"):
        path, read = reader(kind)
        engine.client.routes.insert(0, ("eastmoney_ex", path, read))
    return clock


def run_backfill(engine, clock, **kwargs):
    return engine.start_backfill(
        background=False,
        monotonic=lambda: clock["now"],
        sleep=lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
        min_interval=1.0,
        **kwargs,
    )


def test_backfill_total_days_and_done(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine)
    state = run_backfill(engine, clock)
    assert state["total"] == 30
    assert state["done"] == 30
    assert state["running"] is False


def test_backfill_requests_at_most_one_per_second(tmp_path):
    engine = make_engine(tmp_path)
    calls = []
    clock = install_backfill_routes(engine, calls=calls)
    run_backfill(engine, clock)
    stamps = [item[2] for item in calls]
    assert len(stamps) == 90
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(gap >= 1.0 for gap in gaps)


def test_backfill_persists_all_three_pools(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine)
    run_backfill(engine, clock, days=5)
    for day in engine._last_trading_days(OPEN, 5):
        assert engine.store.pool_day_kinds(day) == {"zt", "zb", "dt"}


def test_backfill_repeat_start_does_no_requests(tmp_path):
    engine = make_engine(tmp_path)
    calls = []
    clock = install_backfill_routes(engine, calls=calls)
    run_backfill(engine, clock, days=5)
    count = len(calls)
    state = run_backfill(engine, clock, days=5)
    assert len(calls) == count
    assert state["total"] == 0 and state["done"] == 0


def test_backfill_failed_date_marked_unavailable(tmp_path):
    engine = make_engine(tmp_path)
    fail = "20261030"
    clock = install_backfill_routes(engine, fail_date=fail)
    state = run_backfill(engine, clock, days=5)
    assert state["failed"] == 1
    record = engine.store.load_pool_day(date(2026, 10, 30), "zt")
    assert record["available"] is False and record["reason"] == "upstream_http"


def test_backfill_failed_date_not_retried_on_next_start(tmp_path):
    engine = make_engine(tmp_path)
    fail = "20261030"
    calls = []
    clock = install_backfill_routes(engine, fail_date=fail, calls=calls)
    run_backfill(engine, clock, days=5)
    count = len(calls)
    run_backfill(engine, clock, days=5)
    assert len(calls) == count


def test_backfill_tc_zero_marked_no_data(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine, tc_zero_date="20261015")
    run_backfill(engine, clock, days=20)
    record = engine.store.load_pool_day(date(2026, 10, 15), "zt")
    assert record["available"] is False and record["reason"] == "no_data_from_source"


def test_backfill_today_uses_gateway_rows(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine, qdate_override="20261030")
    run_backfill(engine, clock, days=2)
    record = engine.store.load_pool_day(DAY, "zt")
    assert record["available"] is True


def test_backfill_history_available_after_run(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine)
    run_backfill(engine, clock, days=10)
    payload = engine.pool_history_dict(10)
    assert all(row["available"] for row in payload["days"])
    assert payload["backfill"]["running"] is False


def test_backfill_health_not_blocked(tmp_path):
    engine = make_engine(tmp_path)
    gate = threading.Event()
    clock = install_backfill_routes(engine, gate=gate)
    state = engine.start_backfill(background=True, days=5, min_interval=0.01)
    assert state["running"] is True
    started = time.monotonic()
    health = engine.health_dict()
    elapsed = time.monotonic() - started
    assert health["ok"] is True
    assert health["backfill"]["running"] is True
    assert elapsed < 2.0
    gate.set()
    if engine._backfill_thread is not None:
        engine._backfill_thread.join(timeout=5)
    assert engine.health_dict()["backfill"]["running"] is False


def test_backfill_state_shape(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine)
    state = run_backfill(engine, clock, days=3)
    assert set(state) == {"running", "done", "total", "failed", "started_at", "finished_at"}


def test_pool_history_health_after_backfill(tmp_path):
    engine = make_engine(tmp_path)
    clock = install_backfill_routes(engine)
    run_backfill(engine, clock, days=3)
    health = engine.health_dict()
    assert health["sources"]["pool_history"]["ok"] is True
    assert health["sources"]["pool_history"]["days"] >= 3
