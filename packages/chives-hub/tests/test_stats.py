from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chives_hub.stats import build_outcome, stats_payload
from tests.support import NOW, at, build_engine


def make_card(store, *, tags=None, outcome=None, now=NOW, code="600519.SH", review_date="2026-11-04"):
    card = {
        "code": code,
        "name": "贵州茅台",
        "status": "closed",
        "state": "exit",
        "review_date": review_date,
        "thesis": "",
        "tags": tags or {},
        "market_conditions": [],
        "sector_conditions": [],
        "stock_conditions": [],
        "confirm_policy": "all",
        "giveup": [],
        "risk": {"stop_price": 90.0},
        "sizing": None,
        "proposed_by": "user",
        "created_at": now,
        "expires_at": now + timedelta(days=1),
        "locked_at": None,
        "late": False,
        "judgement": None,
        "last_price": None,
        "outcome": outcome,
    }
    card_id = store.insert_card(card, now)
    if outcome is not None:
        store.update_card(card_id, outcome=outcome, now=now)
    return card_id


def outcome(**overrides):
    base = {
        "date": "2026-11-04",
        "triggered_execute": True,
        "reached_states": ["execute"],
        "open_pct": 1.0,
        "high_pct": 2.0,
        "close_pct": 3.0,
        "stop_hit": False,
    }
    base.update(overrides)
    return base


def test_build_outcome_percentages() -> None:
    result = build_outcome(
        {"risk": {"stop_price": 94.0}},
        {"prev_close": 100.0, "open": 102.0, "high": 105.0, "low": 95.0, "price": 103.0},
        history=[{"to": "execute"}, {"to": "observe"}],
        now=NOW,
    )
    assert result["open_pct"] == pytest.approx(2.0)
    assert result["high_pct"] == pytest.approx(5.0)
    assert result["close_pct"] == pytest.approx(3.0)
    assert result["stop_hit"] is False
    assert result["triggered_execute"] is True
    assert result["reached_states"] == ["execute", "observe"]
    assert result["date"] == "2026-11-04"


def test_build_outcome_stop_hit_from_low() -> None:
    result = build_outcome(
        {"risk": {"stop_price": 96.0}},
        {"prev_close": 100.0, "open": 100.0, "high": 101.0, "low": 95.0, "price": 99.0},
        history=[],
        now=NOW,
    )
    assert result["stop_hit"] is True


def test_build_outcome_missing_quote_is_null() -> None:
    result = build_outcome({"risk": {"stop_price": 90.0}}, None, history=[], now=NOW)
    assert result["open_pct"] is None
    assert result["high_pct"] is None
    assert result["close_pct"] is None
    assert result["stop_hit"] is None
    assert result["triggered_execute"] is False


def test_stats_empty_sample(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    payload = engine.candidates_stats()
    assert payload["n"] == 0
    assert payload["sample_insufficient"] is True
    assert payload["trigger_rate_pct"] is None
    assert payload["by_env"] == {}
    assert payload["by_streak"] == {}


def test_stats_hand_computed(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    make_card(engine.store, tags={"env": "strong", "streak": 2}, outcome=outcome())
    make_card(
        engine.store,
        tags={"env": "strong", "streak": 2},
        outcome=outcome(triggered_execute=False, open_pct=-1.0, high_pct=0.0, close_pct=-2.0),
        code="000001.SZ",
    )
    make_card(
        engine.store,
        tags={"env": "weak", "streak": 1},
        outcome=outcome(
            date="2026-11-03",
            triggered_execute=False,
            open_pct=None,
            high_pct=None,
            close_pct=None,
            stop_hit=None,
        ),
        code="600000.SH",
    )
    payload = stats_payload(engine.store, days=20, now=NOW)
    assert payload["n"] == 3
    assert payload["trigger_rate_pct"] == pytest.approx(33.3333)
    assert payload["avg_open_pct"] == pytest.approx(0.0)
    assert payload["avg_high_pct"] == pytest.approx(1.0)
    assert payload["avg_close_pct"] == pytest.approx(0.5)
    assert payload["win_ratio_pct"] == pytest.approx(50.0)
    assert payload["by_env"]["strong"]["n"] == 2
    assert payload["by_env"]["strong"]["trigger_rate_pct"] == pytest.approx(50.0)
    assert payload["by_env"]["strong"]["avg_close_pct"] == pytest.approx(0.5)
    assert payload["by_env"]["weak"]["avg_close_pct"] is None
    assert payload["by_streak"]["2"]["n"] == 2
    assert payload["by_streak"]["1"]["n"] == 1


def test_stats_days_filter(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    make_card(engine.store, outcome=outcome())
    make_card(
        engine.store,
        outcome=outcome(date="2026-11-02", close_pct=1.0),
        code="000001.SZ",
    )
    assert stats_payload(engine.store, days=1, now=NOW)["n"] == 1
    assert stats_payload(engine.store, days=3, now=NOW)["n"] == 2


def test_stats_sample_insufficient_threshold(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    for index in range(29):
        make_card(engine.store, outcome=outcome(), code=f"60{index:04d}.SH")
    assert stats_payload(engine.store, days=20, now=NOW)["sample_insufficient"] is True
    make_card(engine.store, outcome=outcome(), code="600099.SH")
    payload = stats_payload(engine.store, days=20, now=NOW)
    assert payload["n"] == 30
    assert payload["sample_insufficient"] is False
    assert payload["note"].startswith("样本 n≥30")


def test_outcome_written_at_close(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(15, 6))
    card = engine.create_card(
        {
            "code": "600519.SH",
            "thesis": "x",
            "risk": {"stop_price": 90.0},
            "proposed_by": "user",
            "review_date": "2026-11-04",
        }
    )["card"]
    engine._maybe_outcomes(clock())
    stored = engine.store.get_card(card["id"])
    assert stored["outcome"]["open_pct"] == pytest.approx(1.0204)
    assert stored["outcome"]["high_pct"] == pytest.approx(3.0612)
    assert stored["outcome"]["close_pct"] == pytest.approx(2.0408)
    assert stored["outcome"]["stop_hit"] is False


def test_outcome_not_written_before_close(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(14, 0))
    card = engine.create_card(
        {
            "code": "600519.SH",
            "thesis": "x",
            "risk": {"stop_price": 90.0},
            "proposed_by": "user",
            "review_date": "2026-11-04",
        }
    )["card"]
    engine._maybe_outcomes(clock())
    assert engine.store.get_card(card["id"])["outcome"] is None


def test_outcome_marker_prevents_rewrite(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path, now=at(15, 6))
    card = engine.create_card(
        {
            "code": "600519.SH",
            "thesis": "x",
            "risk": {"stop_price": 90.0},
            "proposed_by": "user",
            "review_date": "2026-11-04",
        }
    )["card"]
    engine._maybe_outcomes(clock())
    first = engine.store.get_card(card["id"])["outcome"]
    sources.state["quotes"]["600519.SH"]["price"] = 90.0
    engine._maybe_outcomes(clock())
    assert engine.store.get_card(card["id"])["outcome"] == first


def test_outcome_not_written_on_holiday(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(
        tmp_path, now=datetime(2026, 11, 7, 15, 6, tzinfo=NOW.tzinfo)
    )
    card = engine.create_card(
        {
            "code": "600519.SH",
            "thesis": "x",
            "risk": {"stop_price": 90.0},
            "proposed_by": "user",
            "review_date": "2026-11-07",
        }
    )["card"]
    engine._maybe_outcomes(clock())
    assert engine.store.get_card(card["id"])["outcome"] is None
