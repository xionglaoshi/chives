from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest

from chives_signals.emergency import evaluate, is_limit_down, is_suspended, market_session
from chives_signals.models import CN_TZ
from tests.support import adopt_setting, at, build_engine

THRESHOLD_INDEX = "emergency_index_drop_pct"
THRESHOLD_COUNT = "emergency_limit_down_count"


def _engine(tmp_path: Path, **kwargs):
    engine, clock, sources, portfolio = build_engine(tmp_path, **kwargs)
    return engine, clock, sources, portfolio


def _trigger_rows(engine):
    return engine.store.list_triggers()


def _signals(engine):
    return [row for row in engine.store.list_signals(status="all") if row["kind"] == "emergency"]


def test_no_thresholds_never_fires(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    sources.overview_payload["indexes"][0]["change_pct"] = -9.0
    sources.overview_payload["breadth"]["limit_down"] = 500
    sources.state["quotes"]["600519.SH"] = {"price": 80.0, "prev_close": 98.0, "suspended": True}
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []
    assert _signals(engine) == []


@pytest.mark.parametrize(
    "key,value", [(THRESHOLD_INDEX, 1), (THRESHOLD_COUNT, 5)]
)
def test_suggestion_alone_never_fires(tmp_path: Path, key: str, value: float) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    engine.setting_suggest(key, {"value": value, "basis": "建议"})
    sources.overview_payload["indexes"][0]["change_pct"] = -9.0
    sources.overview_payload["breadth"]["limit_down"] = 500
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_index_drop_below_threshold_does_not_fire(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -1.99
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_index_drop_at_threshold_fires(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -2.0
    engine._maybe_emergency(at(10))
    rows = _trigger_rows(engine)
    assert [row["kind"] for row in rows] == ["emergency"]
    assert rows[0]["reason"].startswith("上证指数")
    assert "2.00%" in rows[0]["reason"]


def test_index_drop_only_core_indexes(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"] = [
        {"code": "999999.SH", "name": "非核心", "change_pct": -9.0}
    ]
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_index_drop_picks_worst_core_index(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -2.1
    sources.overview_payload["indexes"][2]["change_pct"] = -5.5
    engine._maybe_emergency(at(10))
    assert "创业板指" in _trigger_rows(engine)[0]["reason"]


def test_limit_down_count_below_threshold_does_not_fire(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_COUNT, 6)
    sources.overview_payload["breadth"]["limit_down"] = 5
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_limit_down_count_at_threshold_fires(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_COUNT, 5)
    engine._maybe_emergency(at(10))
    rows = _trigger_rows(engine)
    assert len(rows) == 1
    assert "跌停 5 家" in rows[0]["reason"]


def test_limit_down_count_falls_back_to_pool(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_COUNT, 6)
    sources.overview_payload["breadth"].pop("limit_down")
    sources.pool_payloads["dt"]["count"] = 7
    engine._maybe_emergency(at(10))
    assert "跌停 7 家" in _trigger_rows(engine)[0]["reason"]


def test_holding_limit_down_explicit_price(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"].update(
        {"price": 88.2, "prev_close": 98.0, "limit_down": 88.2}
    )
    engine._maybe_emergency(at(10))
    rows = _trigger_rows(engine)
    assert [row["kind"] for row in rows] == ["emergency"]
    assert "持仓 1 只跌停" in rows[0]["reason"]


def test_holding_limit_down_derived_ten_percent(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"].update({"price": 88.2, "prev_close": 98.0})
    engine._maybe_emergency(at(10))
    assert "持仓 1 只跌停" in _trigger_rows(engine)[0]["reason"]


def test_holding_limit_down_derived_twenty_percent(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(
        tmp_path,
        positions=[{"code": "300750.SZ", "name": "宁德时代", "weight_pct": 10.0, "industry": "电力设备"}],
    )
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["300750.SZ"] = {"price": 80.0, "prev_close": 100.0}
    engine._maybe_emergency(at(10))
    assert "持仓 1 只跌停" in _trigger_rows(engine)[0]["reason"]


def test_holding_not_at_limit_does_not_fire(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"].update({"price": 90.0, "prev_close": 98.0})
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_holding_suspended_fires(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"]["suspended"] = True
    engine._maybe_emergency(at(10))
    assert "持仓 1 只停牌" in _trigger_rows(engine)[0]["reason"]


def test_holding_missing_quote_does_not_fire(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"].pop("600519.SH")
    engine._maybe_emergency(at(10))
    assert _trigger_rows(engine) == []


def test_emergency_signal_contract(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    signal = _signals(engine)[0]
    assert signal["severity"] == "L3"
    assert signal["decide"] is True
    assert signal["primary"]["action"] == "ack"
    assert signal["kind"] == "emergency"


def test_emergency_signal_brief_is_the_chain(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    signal = _signals(engine)[0]
    assert signal["brief"] == "暂停新增风险→核实行情/成交/公告→查组合敞口与现金→按既定规则处理→记录事件与偏差"
    assert signal["context"]["steps"] == [
        "暂停新增风险",
        "核实行情/成交/公告",
        "查组合敞口与现金",
        "按既定规则处理",
        "记录事件与偏差",
    ]


def test_emergency_signal_does_not_name_holdings(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"].update({"price": 88.2, "prev_close": 98.0})
    engine._maybe_emergency(at(10))
    signal = _signals(engine)[0]
    for field in ("title", "conclusion", "brief"):
        assert "600519" not in signal[field]


def test_emergency_trigger_context_carries_values(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    row = _trigger_rows(engine)[0]
    context = engine.trigger_context(row["id"])["context"]
    assert context["emergency"]["reason"] == "index_drop"
    assert context["emergency"]["values"]["change_pct"] == -3.0


def test_emergency_trigger_context_is_private(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    row = _trigger_rows(engine)[0]
    assert engine.trigger_context(row["id"])["private"] is True


def test_emergency_same_reason_once_per_day(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    engine._maybe_emergency(at(10, 0, 31))
    assert len(_trigger_rows(engine)) == 1
    assert len(_signals(engine)) == 1


def test_emergency_different_reasons_both_fire(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    adopt_setting(engine, THRESHOLD_COUNT, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    rows = _trigger_rows(engine)
    assert len(rows) == 2
    assert {row["reason"].split(" ")[0] for row in rows} == {"上证指数", "跌停"}


def test_emergency_fires_again_next_day(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(10))
    engine._maybe_emergency(datetime(2026, 11, 5, 10, 0, tzinfo=CN_TZ))
    assert len(_trigger_rows(engine)) == 2


def test_emergency_not_on_weekend(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ))
    assert _trigger_rows(engine) == []


@pytest.mark.parametrize("hour,minute", [(9, 29), (15, 1), (20, 0)])
def test_emergency_outside_session(tmp_path: Path, hour: int, minute: int) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(hour, minute))
    assert _trigger_rows(engine) == []


@pytest.mark.parametrize("hour,minute", [(9, 30), (15, 0)])
def test_emergency_session_boundaries(tmp_path: Path, hour: int, minute: int) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine._maybe_emergency(at(hour, minute))
    assert len(_trigger_rows(engine)) == 1


def test_emergency_does_not_log_holdings(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 5)
    sources.overview_payload["indexes"][0]["change_pct"] = 0.5
    sources.overview_payload["breadth"]["limit_down"] = 0
    sources.state["quotes"]["600519.SH"].update({"price": 88.2, "prev_close": 98.0})
    with caplog.at_level(logging.DEBUG, logger="chives_signals"):
        engine._maybe_emergency(at(10))
    assert "600519" not in caplog.text
    assert "贵州茅台" not in caplog.text


def test_market_session_helper(tmp_path: Path) -> None:
    engine, _, _, _ = _engine(tmp_path)
    assert market_session(at(9, 29), engine.calendar) is False
    assert market_session(at(9, 30), engine.calendar) is True
    assert market_session(at(15, 0), engine.calendar) is True
    assert market_session(at(15, 1), engine.calendar) is False
    assert market_session(datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ), engine.calendar) is False


@pytest.mark.parametrize(
    "quote,suspended",
    [
        ({"status": "suspended"}, True),
        ({"status": "halt"}, True),
        ({"status": "停牌"}, True),
        ({"suspended": True}, True),
        ({"status": "trading"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_is_suspended(quote, suspended: bool) -> None:
    assert is_suspended(quote) is suspended


def test_evaluate_without_thresholds_returns_empty() -> None:
    hits = evaluate(
        thresholds={},
        overview={"indexes": [{"code": "000001.SH", "change_pct": -9.0}]},
        quotes={},
        positions=[],
    )
    assert hits == []


def test_tick_runs_emergency_detection(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"][0]["change_pct"] = -3.0
    engine.tick(force=True)
    assert [row["kind"] for row in _trigger_rows(engine)] == ["emergency"]


def test_index_drop_derived_from_price_and_prev_close(tmp_path: Path) -> None:
    engine, _, sources, _ = _engine(tmp_path)
    adopt_setting(engine, THRESHOLD_INDEX, 2)
    sources.overview_payload["indexes"] = [
        {"code": "000001.SH", "name": "上证指数", "price": 2940.0, "prev_close": 3000.0}
    ]
    engine._maybe_emergency(at(10))
    assert len(_trigger_rows(engine)) == 1
