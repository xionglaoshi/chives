from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from chives_hub.models import CN_TZ
from tests.support import (
    active_card,
    at,
    build_engine,
    set_plan_state,
    signals_of,
    triggers,
)


def _execute(engine, now=at(10)):
    engine._sync_cards(now)


def test_execute_transition_writes_card_execute_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    _execute(engine)
    rows = triggers(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "card_execute"
    assert row["card_id"] == card["id"]
    assert row["from_state"] == "observe"
    assert row["to_state"] == "execute"
    assert row["context_ready"] is True
    assert row["judgement"] is None


def test_execute_transition_writes_card_state_signal(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    _execute(engine)
    rows = signals_of(engine, "card_state")
    assert len(rows) == 1
    assert rows[0]["context"]["to_state"] == "execute"
    assert triggers(engine)[0]["signal_id"] == rows[0]["id"]


def test_abandon_transition_writes_card_abandon_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(
        engine,
        plan_state="abandon",
        giveup=[{"type": "price_cross", "direction": "down", "level": 101}],
    )
    _execute(engine)
    rows = triggers(engine)
    assert [row["kind"] for row in rows] == ["card_abandon"]
    assert rows[0]["card_id"] == card["id"]
    assert rows[0]["to_state"] == "abandon"


def test_exit_transition_writes_card_exit_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(
        engine,
        plan_state="exit",
        stock_conditions=[{"type": "price_in_range", "lo": 105, "hi": 110}],
        risk={"stop_price": 103},
    )
    _execute(engine)
    rows = triggers(engine)
    assert [row["kind"] for row in rows] == ["card_exit"]
    assert rows[0]["to_state"] == "exit"


def test_await_confirm_creates_signal_but_no_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(
        engine,
        plan_state="await_confirm",
        stock_conditions=[{"type": "price_cross", "direction": "up", "level": 101}],
        market_conditions=[{"type": "regime", "values": ["strong"]}],
    )
    _execute(engine)
    assert triggers(engine) == []
    rows = signals_of(engine, "card_state")
    assert len(rows) == 1
    assert rows[0]["context"]["to_state"] == "await_confirm"


def test_back_to_observe_creates_signal_but_no_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(
        engine,
        plan_state="await_confirm",
        stock_conditions=[{"type": "price_cross", "direction": "up", "level": 101}],
        market_conditions=[{"type": "regime", "values": ["weak"]}],
    )
    engine._sync_cards(at(9, 50))
    set_plan_state(engine, card["id"], "observe", now=at(9, 50, 3))
    engine._sync_cards(at(9, 50, 3))
    rows = signals_of(engine, "card_state")
    assert sorted(row["context"]["to_state"] for row in rows) == ["await_confirm", "observe"]
    assert triggers(engine) == []


def test_trigger_payload_matches_contract(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    _execute(engine)
    payload = engine.triggers_payload()["triggers"][0]
    assert set(payload) == {
        "id",
        "ts",
        "kind",
        "card_id",
        "code",
        "name",
        "from_state",
        "to_state",
        "reason",
        "context_ready",
        "judged",
    }
    assert payload["card_id"] == card["id"]
    assert payload["code"] == "600519.SH"
    assert payload["kind"] == "card_execute"
    assert payload["context_ready"] is True
    assert payload["judged"] is False
    assert payload["ts"].endswith("+08:00")


def test_triggers_payload_next_id_advances(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    _execute(engine)
    first = engine.triggers_payload()
    assert first["next_id"] == first["triggers"][0]["id"]
    second = engine.triggers_payload(since_id=first["next_id"])
    assert second["triggers"] == []
    assert second["next_id"] == first["next_id"]


def test_triggers_pagination_limit(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    for index in range(3):
        engine.store.insert_trigger(
            {"kind": "regime", "to_state": f"s{index}", "reason": "test"},
            at(9, index),
        )
    page = engine.triggers_payload(since_id=0, limit=2)
    assert [row["to_state"] for row in page["triggers"]] == ["s0", "s1"]
    rest = engine.triggers_payload(since_id=page["next_id"], limit=2)
    assert [row["to_state"] for row in rest["triggers"]] == ["s2"]


def test_triggers_pagination_since_id_skips_earlier(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    for index in range(3):
        engine.store.insert_trigger(
            {"kind": "regime", "to_state": f"s{index}", "reason": "test"},
            at(9, index),
        )
    page = engine.triggers_payload(since_id=2, limit=10)
    assert [row["id"] for row in page["triggers"]] == [3]


def test_trigger_debounce_within_five_minutes(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    _execute(engine)
    engine.store.update_card(card["id"], state="observe", now=at(10, 1))
    _execute(engine, at(10, 2))
    assert len(triggers(engine)) == 1
    assert len(signals_of(engine, "card_state")) == 1


def test_trigger_after_debounce_window(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    _execute(engine)
    engine.store.update_card(card["id"], state="observe", now=at(10, 1))
    _execute(engine, at(10, 7))
    assert len(triggers(engine)) == 2
    assert len(signals_of(engine, "card_state")) == 2


def test_trigger_dedupe_key_identifies_card_and_state(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    _execute(engine)
    row = triggers(engine)[0]
    assert row["dedupe_key"] == f"card_execute|{card['id']}|execute"


def test_transition_is_atomic_when_trigger_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)

    def boom(*args, **kwargs):
        raise RuntimeError("trigger insert failed")

    monkeypatch.setattr(engine.store, "_insert_trigger_conn", boom)
    with pytest.raises(RuntimeError):
        _execute(engine)
    assert engine.store.get_card(card["id"])["state"] == "observe"
    assert engine.store.list_card_history(card["id"]) == []
    assert signals_of(engine, "card_state") == []
    assert triggers(engine) == []


def test_transition_is_atomic_when_signal_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)

    def boom(*args, **kwargs):
        raise RuntimeError("signal insert failed")

    monkeypatch.setattr(engine.store, "_insert_signal_conn", boom)
    with pytest.raises(RuntimeError):
        _execute(engine)
    assert engine.store.get_card(card["id"])["state"] == "observe"
    assert triggers(engine) == []


def test_regime_change_without_active_cards_writes_nothing(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    engine._maybe_regime(at(9, 40))
    sources.overview_payload["regime"]["label"] = "risk_off"
    engine._maybe_regime(at(9, 41))
    assert triggers(engine) == []


def test_regime_change_with_active_card_writes_regime_trigger(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_regime(at(9, 40))
    sources.overview_payload["regime"]["label"] = "risk_off"
    engine._maybe_regime(at(9, 41))
    rows = triggers(engine)
    assert [row["kind"] for row in rows] == ["regime"]
    assert rows[0]["from_state"] == "strong"
    assert rows[0]["to_state"] == "weak"
    assert rows[0]["card_id"] is None
    assert rows[0]["code"] is None


def test_first_regime_observation_is_silent(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_regime(at(9, 40))
    assert triggers(engine) == []


def test_regime_debounce_same_target_within_five_minutes(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_regime(at(9, 40))
    sources.overview_payload["regime"]["label"] = "risk_off"
    engine._maybe_regime(at(9, 41))
    sources.overview_payload["regime"]["label"] = "neutral"
    engine._maybe_regime(at(9, 42))
    sources.overview_payload["regime"]["label"] = "risk_off"
    engine._maybe_regime(at(9, 43))
    rows = triggers(engine)
    assert [row["to_state"] for row in rows] == ["weak", "neutral"]


def test_regime_trigger_reason_and_dedupe(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_regime(at(9, 40))
    sources.overview_payload["regime"]["label"] = "neutral"
    engine._maybe_regime(at(9, 41))
    row = triggers(engine)[0]
    assert row["reason"] == "环境标签 strong→neutral"
    assert row["dedupe_key"] == "regime|-|neutral"


def test_regime_trigger_has_frozen_context(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_regime(at(9, 40))
    sources.overview_payload["regime"]["label"] = "risk_off"
    engine._maybe_regime(at(9, 41))
    row = triggers(engine)[0]
    assert row["context_ready"] is True
    assert row["context"]["card"] is None
    assert "card" in row["context"]["missing"]


def test_card_action_set_state_abandon_creates_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(
        engine,
        plan_state=None,
        stock_conditions=[{"type": "price_cross", "direction": "up", "level": 200}],
        risk={"stop_price": 180},
        market_conditions=[{"type": "regime", "values": ["strong"]}],
    )
    engine.card_action(card["id"], {"action": "set_state", "state": "abandon"})
    rows = triggers(engine)
    assert [row["kind"] for row in rows] == ["card_abandon"]
    assert rows[0]["from_state"] == "observe"


def test_card_action_set_state_observe_creates_no_trigger(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(8))
    card = active_card(
        engine,
        plan_state=None,
        stock_conditions=[{"type": "price_cross", "direction": "up", "level": 200}],
        risk={"stop_price": 180},
        market_conditions=[{"type": "regime", "values": ["strong"]}],
    )
    engine.card_action(card["id"], {"action": "set_state", "state": "await_confirm"})
    engine.card_action(card["id"], {"action": "set_state", "state": "observe"})
    assert triggers(engine) == []


def test_trigger_ts_uses_transition_time(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine, plan_state=None)
    set_plan_state(engine, card["id"], "execute", now=at(10, 3))
    _execute(engine, at(10, 3))
    row = triggers(engine)[0]
    assert row["ts"] == at(10, 3)
    assert row["ts"].tzinfo == CN_TZ


def test_trigger_context_retry_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    original = engine.store.set_trigger_context
    calls = {"n": 0}

    def flaky(trigger_id, context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk busy")
        return original(trigger_id, context)

    monkeypatch.setattr(engine.store, "set_trigger_context", flaky)
    with pytest.raises(RuntimeError):
        _execute(engine)
    assert triggers(engine)[0]["context_ready"] is False
    engine._flush_pending_contexts(at(10, 0, 5))
    assert triggers(engine)[0]["context_ready"] is True
