from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chives_hub.cards import card_payload, normalize_conds, normalize_engine
from chives_hub.models import CN_TZ
from chives_hub.plan_sync import (
    LIVE_CARD_STATES,
    card_id_for,
    is_live_card,
    plan_id_for,
    plan_label,
    plan_payload,
)
from tests.support import (
    NOW,
    active_card,
    at,
    build_engine,
    set_plan_state,
    signals_of,
    triggers,
)


def _create(engine, **overrides):
    body = {
        "code": "600519.SH",
        "thesis": "测试作战卡",
        "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99.0}],
        "risk": {"stop_price": 90.0},
        "proposed_by": "user",
    }
    body.update(overrides)
    return engine.create_card(body)


def _plan_of(engine, card_id: int) -> dict:
    state = engine.sources.plan_rules.states[f"card-{card_id}"]
    return state


def _reset_calls(engine) -> None:
    engine.sources.plan_rules.calls.clear()


# -- payload mapping -----------------------------------------------------
def test_plan_id_uses_card_prefix() -> None:
    assert plan_id_for(42) == "card-42"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("card-7", 7), ("card-001", 1), ("card-x", None), ("other-7", None), (None, None)],
)
def test_card_id_for_plan(raw, expected) -> None:
    assert card_id_for(raw) == expected


def test_plan_payload_keys_are_exactly_the_plan_schema(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine)["card"]["id"])
    payload = plan_payload(card, held=True)
    assert set(payload) == {
        "id",
        "code",
        "market",
        "sector",
        "stock",
        "policy",
        "giveup",
        "stop_price",
        "held",
        "expires_at",
        "label",
    }


def test_plan_payload_has_no_position_fields(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine)["card"]["id"])
    text = json.dumps(plan_payload(card, held=True))
    for banned in ("qty", "quantity", "cost", "cash", "market_value"):
        assert banned not in text


@pytest.mark.parametrize(
    ("field", "condition"),
    [
        ("market", {"type": "regime", "values": ["strong"]}),
        ("sector", {"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 1}),
        ("stock", {"type": "price_cross", "direction": "up", "level": 100.0}),
        ("giveup", {"type": "pct_change", "direction": "down", "threshold_pct": 3.0}),
    ],
)
def test_plan_payload_maps_each_condition_group(tmp_path: Path, field, condition) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    body = {"market_conditions": [], "sector_conditions": [], "stock_conditions": [], "giveup": []}
    body[f"{field}_conditions" if field != "giveup" else "giveup"] = [condition]
    card = engine.store.get_card(_create(engine, **body)["card"]["id"])
    payload = plan_payload(card, held=False)
    assert payload[field] == [condition]


@pytest.mark.parametrize("policy", ["all", "any"])
def test_plan_payload_maps_policy(tmp_path: Path, policy: str) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine, confirm_policy=policy)["card"]["id"])
    assert plan_payload(card, held=False)["policy"] == policy


def test_plan_payload_maps_stop_price(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine, risk={"stop_price": 91.5})["card"]["id"])
    assert plan_payload(card, held=False)["stop_price"] == 91.5


@pytest.mark.parametrize("held", [True, False])
def test_plan_payload_maps_held(tmp_path: Path, held: bool) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine)["card"]["id"])
    assert plan_payload(card, held=held)["held"] is held


def test_plan_payload_expiry_is_timezone_aware(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine)["card"]["id"])
    assert plan_payload(card, held=False)["expires_at"].endswith("+08:00")


def test_plan_payload_label_uses_name(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine, name="贵州茅台")["card"]["id"])
    assert plan_payload(card, held=False)["label"] == "贵州茅台 作战卡"


def test_plan_label_truncated_to_forty() -> None:
    label = plan_label({"name": "字" * 60, "code": "600519.SH"})
    assert len(label) <= 40
    assert label.endswith("作战卡")


def test_plan_label_falls_back_to_code(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine)["card"]["id"])
    card["name"] = ""
    assert plan_label(card).startswith("600519.SH")


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [
        ("active", "observe", True),
        ("active", "await_confirm", True),
        ("active", "execute", True),
        ("active", "abandon", False),
        ("active", "exit", False),
        ("proposed", "observe", False),
        ("cancelled", "observe", False),
        ("closed", "observe", False),
    ],
)
def test_is_live_card(status, state, expected) -> None:
    card = {"status": status, "state": state, "expires_at": at(15)}
    assert is_live_card(card, at(10)) is expected


def test_live_states_match_contract() -> None:
    assert LIVE_CARD_STATES == ("observe", "await_confirm", "execute")


def test_normalize_conds_drops_unknown_and_keeps_null() -> None:
    raw = {"market": [True, None, False], "sector": "bad", "stock": [1], "giveup": [None]}
    assert normalize_conds(raw) == {
        "market": [True, None, False],
        "sector": [],
        "stock": [None],
        "giveup": [None],
    }


def test_normalize_engine_defaults() -> None:
    assert normalize_engine(None) == {"ok": True, "error": None, "synced_at": None}


# -- push on lifecycle ---------------------------------------------------
def test_create_user_card_pushes_plan(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    upserts = sources.plan_rules.upserts()
    assert len(upserts) == 1
    assert upserts[0]["id"] == f"card-{card['id']}"
    assert upserts[0]["code"] == "600519.SH"


def test_create_agent_card_is_not_pushed(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    _create(engine, proposed_by="agent")
    assert sources.plan_rules.upserts() == []


def test_confirm_pushes_plan(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    engine.card_action(card["id"], {"action": "confirm"})
    assert [item["id"] for item in sources.plan_rules.upserts()] == [f"card-{card['id']}"]


def test_tighten_stop_re_pushes_new_stop(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    _reset_calls(engine)
    engine.card_action(card["id"], {"action": "tighten_stop", "stop": 95.0})
    upserts = sources.plan_rules.upserts()
    assert len(upserts) == 1
    assert upserts[0]["stop_price"] == 95.0


def test_tighten_stop_keeps_conditions(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    _reset_calls(engine)
    engine.card_action(card["id"], {"action": "tighten_stop", "stop": 95.0})
    payload = sources.plan_rules.upserts()[0]
    assert payload["stock"] == [{"type": "price_cross", "direction": "up", "level": 99.0}]


def test_cancel_removes_plan(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine.card_action(card["id"], {"action": "cancel"})
    assert sources.plan_rules.removes() == [{"id": f"card-{card['id']}"}]
    assert sources.plan_rules.states == {}


@pytest.mark.parametrize("state", ["abandon", "exit"])
def test_set_state_downgrade_removes_plan(tmp_path: Path, state: str) -> None:
    engine, _, sources, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "set_state", "state": state})
    assert result["card"]["state"] == state
    assert f"card-{card['id']}" not in sources.plan_rules.states
    assert sources.plan_rules.removes()[-1] == {"id": f"card-{card['id']}"}


def test_set_state_observe_keeps_plan(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    engine.card_action(card["id"], {"action": "set_state", "state": "execute"})
    assert f"card-{card['id']}" in sources.plan_rules.states


def test_expiry_removes_plan(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine, expires_at="2026-11-04T15:00:00+08:00")["card"]
    clock.set(datetime(2026, 11, 5, 15, 1, tzinfo=CN_TZ))
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["status"] == "expired"
    assert sources.plan_rules.states == {}


def test_closed_card_plan_is_removed(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine.store.update_card(card["id"], status="closed", now=clock())
    _reset_calls(engine)
    engine._sync_cards(clock())
    assert sources.plan_rules.states == {}
    assert {"id": f"card-{card['id']}"} in sources.plan_rules.removes()


def test_proposed_card_is_never_pushed_on_sync(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    engine._sync_cards(clock())
    assert sources.plan_rules.upserts() == []
    assert f"card-{card['id']}" not in sources.plan_rules.states


def test_abandon_card_is_not_pushed_on_sync(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine.store.update_card(card["id"], state="abandon", now=clock())
    sources.plan_rules.states.clear()
    _reset_calls(engine)
    engine._sync_cards(clock())
    assert sources.plan_rules.upserts() == []


def test_startup_re_pushes_every_active_card(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    first = _create(engine)["card"]
    second = _create(engine, code="300750.SZ")["card"]
    _reset_calls(engine)
    engine._sync_cards(clock())
    ids = {item["id"] for item in sources.plan_rules.upserts()}
    assert ids == {f"card-{first['id']}", f"card-{second['id']}"}


def test_second_sync_does_not_re_push(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    _create(engine)
    engine._sync_cards(clock())
    _reset_calls(engine)
    engine._sync_cards(clock())
    assert sources.plan_rules.upserts() == []


def test_held_true_when_position_exists(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    _create(engine)
    assert sources.plan_rules.upserts()[0]["held"] is True


def test_held_false_for_other_code(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    _create(engine, code="300750.SZ")
    assert sources.plan_rules.upserts()[0]["held"] is False


def test_held_change_re_pushes_after_refresh(tmp_path: Path) -> None:
    engine, clock, sources, portfolio = build_engine(tmp_path)
    card = _create(engine, code="300750.SZ")["card"]
    engine._sync_cards(clock())
    _reset_calls(engine)
    portfolio.overview_payload["positions"] = [
        {"code": "300750.SZ", "name": "宁德时代", "weight_pct": 10.0}
    ]
    clock.set(at(10, 0, 31))
    engine._sync_cards(clock())
    upserts = sources.plan_rules.upserts()
    assert len(upserts) == 1
    assert upserts[0]["held"] is True


def test_held_change_within_thirty_seconds_is_not_seen(tmp_path: Path) -> None:
    engine, clock, sources, portfolio = build_engine(tmp_path)
    _create(engine, code="300750.SZ")
    engine._sync_cards(clock())
    _reset_calls(engine)
    portfolio.overview_payload["positions"] = [
        {"code": "300750.SZ", "name": "宁德时代", "weight_pct": 10.0}
    ]
    clock.set(at(10, 0, 10))
    engine._sync_cards(clock())
    assert sources.plan_rules.upserts() == []


def test_remote_held_mismatch_re_pushes(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    _reset_calls(engine)
    sources.plan_rules.states[f"card-{card['id']}"]["held"] = False
    engine._sync_cards(at(10, 1))
    assert len(sources.plan_rules.upserts()) == 1


def test_missing_remote_plan_is_re_pushed(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states.clear()
    _reset_calls(engine)
    engine._sync_cards(at(10, 1))
    assert [item["id"] for item in sources.plan_rules.upserts()] == [f"card-{card['id']}"]


def test_remote_expiry_mismatch_re_pushes(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states[f"card-{card['id']}"]["expires_at"] = "2000-01-01T00:00:00+08:00"
    _reset_calls(engine)
    engine._sync_cards(at(10, 1))
    assert len(sources.plan_rules.upserts()) == 1


def test_inactive_remote_plan_re_pushes(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states[f"card-{card['id']}"]["active"] = False
    _reset_calls(engine)
    engine._sync_cards(at(10, 1))
    assert len(sources.plan_rules.upserts()) == 1


# -- rejection and backoff ----------------------------------------------
def test_rejection_keeps_card_active_and_records_error(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.plan_rules.reject = ("watchlist_full", "自选股数量已达上限")
    result = _create(engine)
    assert result["card"]["status"] == "active"
    assert result["card"]["engine"]["ok"] is False
    assert "watchlist_full" in result["card"]["engine"]["error"]


def test_rejection_adds_engine_rejected_warning(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.plan_rules.reject = ("watchlist_full", "自选股数量已达上限")
    assert "engine_rejected" in _create(engine)["warnings"]


def test_rejection_on_confirm_warns(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    sources.plan_rules.reject = ("watchlist_full", "满")
    result = engine.card_action(card["id"], {"action": "confirm"})
    assert "engine_rejected" in result["warnings"]
    assert result["card"]["status"] == "active"


def test_rejection_does_not_retry_within_backoff(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.plan_rules.reject = ("watchlist_full", "满")
    _create(engine)
    _reset_calls(engine)
    engine._sync_cards(at(10, 0, 1))
    assert sources.plan_rules.upserts() == []


def test_rejection_retries_after_backoff(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    sources.plan_rules.reject = ("watchlist_full", "满")
    _create(engine)
    _reset_calls(engine)
    engine._sync_cards(clock())
    sources.plan_rules.reject = None
    engine._sync_cards(at(10, 0, 4))
    assert len(sources.plan_rules.upserts()) == 1
    assert engine.store.get_card(1)["engine"]["ok"] is True


@pytest.mark.parametrize(
    ("failures", "expected_seconds"),
    [(1, 3.0), (2, 6.0), (3, 12.0), (5, 60.0), (9, 60.0)],
)
def test_backoff_schedule(tmp_path: Path, failures: int, expected_seconds: float) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    sync = engine.card_plans
    for index in range(failures):
        sync._note_failure("card-1", at(10) + timedelta(seconds=index))
    next_try = sync._next_try["card-1"]
    last = at(10) + timedelta(seconds=failures - 1)
    assert (next_try - last).total_seconds() == expected_seconds


def test_rejection_does_not_change_state(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "await_confirm")
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["state"] == "await_confirm"


# -- unreachable ---------------------------------------------------------
def test_unreachable_reports_engine_false(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    _create(engine)
    sources.plan_rules.fail = True
    engine._sync_cards(clock())
    assert engine.cards_payload()["engine"]["ok"] is False
    assert "upstream_network" in engine.cards_payload()["engine"]["reason"]


def test_unreachable_keeps_card_state(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._sync_cards(clock())
    before = engine.store.get_card(card["id"])["state"]
    sources.plan_rules.fail = True
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["state"] == before


def test_unreachable_does_not_append_history(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._sync_cards(clock())
    count = len(engine.store.list_card_history(card["id"]))
    sources.plan_rules.fail = True
    engine._sync_cards(at(10, 0, 3))
    assert len(engine.store.list_card_history(card["id"])) == count


def test_recovery_re_pushes_missing_plan(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.fail = True
    engine._sync_cards(at(10, 0, 3))
    sources.plan_rules.fail = False
    sources.plan_rules.states.clear()
    _reset_calls(engine)
    engine._sync_cards(at(10, 0, 6))
    assert [item["id"] for item in sources.plan_rules.upserts()] == [f"card-{card['id']}"]
    assert engine.cards_payload()["engine"] == {"ok": True}


def test_recovery_does_not_duplicate_signal(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._sync_cards(clock())
    sources.plan_rules.fail = True
    engine._sync_cards(at(10, 0, 3))
    sources.plan_rules.fail = False
    engine._sync_cards(at(10, 0, 6))
    assert len(signals_of(engine, "card_state")) == 1


# -- reconciliation ------------------------------------------------------
def test_orphan_card_plan_is_removed(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    _create(engine)
    sources.plan_rules.states["card-999"] = sources.plan_rules._plan_state(
        {"id": "card-999", "code": "600000.SH", "label": "孤儿"}, at(9)
    )
    engine._sync_cards(clock())
    assert "card-999" not in sources.plan_rules.states
    assert {"id": "card-999"} in sources.plan_rules.removes()


def test_non_card_plan_is_never_touched(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    _create(engine)
    sources.plan_rules.states["manual-1"] = sources.plan_rules._plan_state(
        {"id": "manual-1", "code": "600000.SH", "label": "手工"}, at(9)
    )
    engine._sync_cards(clock())
    assert "manual-1" in sources.plan_rules.states
    assert {"id": "manual-1"} not in sources.plan_rules.removes()


def test_active_card_plan_is_kept(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    assert f"card-{card['id']}" in sources.plan_rules.states


def test_stale_plan_of_proposed_card_is_removed(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    sources.plan_rules.states[f"card-{card['id']}"] = sources.plan_rules._plan_state(
        {"id": f"card-{card['id']}", "code": "600519.SH", "label": "旧"}, at(9)
    )
    engine._sync_cards(clock())
    assert sources.plan_rules.states == {}


def test_abandoned_card_plan_is_removed_and_not_re_added(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    engine.card_action(card["id"], {"action": "set_state", "state": "abandon"})
    _reset_calls(engine)
    engine._sync_cards(clock())
    assert sources.plan_rules.upserts() == []
    assert sources.plan_rules.states == {}


# -- mirror --------------------------------------------------------------
def test_mirror_state_and_price(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "execute", price=101.5)
    engine._sync_cards(at(10, 0, 3))
    stored = engine.store.get_card(card["id"])
    assert stored["state"] == "execute"
    assert stored["last_price"] == 101.5


@pytest.mark.parametrize(
    ("group", "flags"),
    [
        ("market", [True]),
        ("sector", [True, None]),
        ("stock", [False]),
        ("giveup", [None, False]),
    ],
)
def test_mirror_conds_per_group(tmp_path: Path, group, flags) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    payload = _plan_of(engine, card["id"])
    payload["conds"] = {"market": [], "sector": [], "stock": [], "giveup": []}
    payload["conds"][group] = flags
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["conds"][group] == flags


def test_mirror_conds_defaults_to_empty(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["conds"] == {
        "market": [],
        "sector": [],
        "stock": [None],
        "giveup": [],
    }


def test_mirror_history_merges_missed_transitions(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    payload = _plan_of(engine, card["id"])
    payload["history"] = [
        {"ts": "2026-11-04T10:00:03+08:00", "from": "observe", "to": "await_confirm", "reason": "等待确认"},
        {"ts": "2026-11-04T10:00:06+08:00", "from": "await_confirm", "to": "execute", "reason": "执行"},
    ]
    payload["state"] = "execute"
    payload["since"] = "2026-11-04T10:00:06+08:00"
    engine._sync_cards(at(10, 0, 7))
    history = engine.store.list_card_history(card["id"])
    assert [row["to"] for row in history] == ["await_confirm", "execute"]
    assert engine.store.get_card(card["id"])["state"] == "execute"


def test_mirror_history_dedupes_by_ts_and_to(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "execute")
    engine._sync_cards(at(10, 0, 3))
    engine._sync_cards(at(10, 0, 6))
    assert len(engine.store.list_card_history(card["id"])) == 1


def test_mirror_state_change_signal_once(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "execute")
    engine._sync_cards(at(10, 0, 3))
    engine._sync_cards(at(10, 0, 6))
    assert len(signals_of(engine, "card_state")) == 1


def test_mirror_execute_creates_trigger(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "execute")
    engine._sync_cards(at(10, 0, 3))
    rows = triggers(engine)
    assert [row["kind"] for row in rows] == ["card_execute"]
    assert rows[0]["from_state"] == "observe"
    assert rows[0]["to_state"] == "execute"


@pytest.mark.parametrize(
    ("state", "kind"),
    [("abandon", "card_abandon"), ("exit", "card_exit")],
)
def test_mirror_terminal_trigger_kind(tmp_path: Path, state: str, kind: str) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], state)
    engine._sync_cards(at(10, 0, 3))
    assert [row["kind"] for row in triggers(engine)] == [kind]


def test_mirror_await_confirm_signal_without_trigger(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "await_confirm")
    engine._sync_cards(at(10, 0, 3))
    assert triggers(engine) == []
    assert [row["context"]["to_state"] for row in signals_of(engine, "card_state")] == [
        "await_confirm"
    ]


def test_mirror_observe_signal_without_trigger(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "await_confirm")
    engine._sync_cards(at(10, 0, 3))
    set_plan_state(engine, card["id"], "observe")
    engine._sync_cards(at(10, 0, 6))
    assert triggers(engine) == []
    assert sorted(row["context"]["to_state"] for row in signals_of(engine, "card_state")) == [
        "await_confirm",
        "observe",
    ]


def test_mirror_reason_from_history(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "execute", reason="市场与板块成立")
    engine._sync_cards(at(10, 0, 3))
    stored = engine.store.get_card(card["id"])
    assert stored["state"] == "execute"
    assert engine.store.list_card_history(card["id"])[-1]["reason"] == "市场与板块成立"


def test_mirror_price_without_state_change_writes_no_signal(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    payload = _plan_of(engine, card["id"])
    payload["last_price"] = 102.0
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["last_price"] == 102.0
    assert signals_of(engine, "card_state") == []


def test_mirror_conds_without_state_change_writes_no_signal(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    _plan_of(engine, card["id"])["conds"] = {
        "market": [True],
        "sector": [],
        "stock": [True],
        "giveup": [],
    }
    engine._sync_cards(at(10, 0, 3))
    assert signals_of(engine, "card_state") == []


def test_mirror_sets_card_engine_synced_at(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    engine_state = engine.store.get_card(card["id"])["engine"]
    assert engine_state["ok"] is True
    assert engine_state["synced_at"] == at(10).isoformat()


def test_remote_expired_marks_card_expired(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states[f"card-{card['id']}"]["state"] = "expired"
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["status"] == "expired"
    assert sources.plan_rules.states == {}


def test_unknown_remote_state_is_ignored(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states[f"card-{card['id']}"]["state"] = "bogus"
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["state"] == "observe"


# -- API and payload -----------------------------------------------------
def test_cards_payload_has_engine(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    _create(engine)
    engine._sync_cards(clock())
    assert engine.cards_payload()["engine"] == {"ok": True}


def test_card_payload_has_conds_and_engine(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    payload = engine.card_detail(card["id"])["card"]
    assert set(payload["conds"]) == {"market", "sector", "stock", "giveup"}
    assert set(payload["engine"]) == {"ok", "error", "synced_at"}


def test_create_response_has_warnings_list(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert isinstance(_create(engine)["warnings"], list)


def test_confirm_response_has_warnings_list(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    assert isinstance(engine.card_action(card["id"], {"action": "confirm"})["warnings"], list)


def test_old_database_migration_keeps_active_state(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
            state TEXT NOT NULL, review_date TEXT, thesis TEXT NOT NULL,
            tags TEXT NOT NULL, market_conditions TEXT NOT NULL,
            sector_conditions TEXT NOT NULL, stock_conditions TEXT NOT NULL,
            confirm_policy TEXT NOT NULL, giveup TEXT NOT NULL, risk TEXT NOT NULL,
            sizing TEXT, proposed_by TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, locked_at TEXT, late INTEGER NOT NULL DEFAULT 0,
            judgement TEXT, last_price REAL, outcome TEXT,
            history TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO cards (code,name,status,state,thesis,tags,market_conditions,"
        "sector_conditions,stock_conditions,confirm_policy,giveup,risk,proposed_by,"
        "created_at,expires_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "600519.SH", "贵州茅台", "active", "execute", "x", "{}", "[]", "[]", "[]",
            "all", "[]", '{"stop_price": 90}', "user",
            at(9).isoformat(), at(15).isoformat(), at(9).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    from chives_hub.store import HubStore

    store = HubStore(db)
    card = store.get_card(1)
    assert card["state"] == "execute"
    assert card["status"] == "active"
    assert card["conds"] == {}
    assert card["engine"] is None
    payload = card_payload(card)
    assert payload["conds"] == {"market": [], "sector": [], "stock": [], "giveup": []}
    assert payload["engine"] == {"ok": True, "error": None, "synced_at": None}


def test_context_pack_frozen_and_private(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._sync_cards(clock())
    trigger = triggers(engine)[0]
    first = engine.trigger_context(trigger["id"])["context"]
    second = engine.trigger_context(trigger["id"])["context"]
    assert first == second
    assert first["trigger"]["context_ready"] is True


def test_context_pack_has_no_position_size_or_cost(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._sync_cards(clock())
    trigger = triggers(engine)[0]
    context = engine.trigger_context(trigger["id"])["context"]
    text = json.dumps(context, ensure_ascii=False)
    for banned in ("quantity", "qty", "cost_cny", "market_value_cny", "cost_basis", "shares"):
        assert banned not in text


def test_context_card_carries_mirrored_conds(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._sync_cards(clock())
    trigger = triggers(engine)[0]
    context = engine.trigger_context(trigger["id"])["context"]
    assert set(context["card"]["conds"]) == {"market", "sector", "stock", "giveup"}
    assert [row["to"] for row in context["card"]["history"]] == ["execute"]


# -- additional edge cases ----------------------------------------------
def test_confirm_rejection_records_engine_error_on_card(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    sources.plan_rules.reject = ("watchlist_full", "满")
    result = engine.card_action(card["id"], {"action": "confirm"})
    assert result["card"]["engine"]["ok"] is False
    assert "watchlist_full" in result["card"]["engine"]["error"]


def test_successful_create_records_engine_ok(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    assert card["engine"]["ok"] is True
    assert card["engine"]["error"] is None
    assert card["engine"]["synced_at"] is not None


def test_engine_stays_ok_after_mirror(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card["id"])["engine"]["ok"] is True


def test_two_cards_one_rejected_does_not_block_the_other(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    first = _create(engine)["card"]
    sources.plan_rules.reject = ("watchlist_full", "满")
    second = _create(engine, code="300750.SZ")["card"]
    sources.plan_rules.reject = None
    _reset_calls(engine)
    engine._sync_cards(at(10, 1))
    ids = {item["id"] for item in sources.plan_rules.upserts()}
    assert f"card-{first['id']}" in ids
    assert f"card-{second['id']}" in ids


def test_backoff_is_per_plan(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    sync = engine.card_plans
    sync._note_failure("card-1", at(10))
    assert sync._in_backoff("card-1", at(10, 0, 1)) is True
    assert sync._in_backoff("card-2", at(10, 0, 1)) is False


def test_remove_missing_plan_is_treated_as_success(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    assert engine.card_plans.remove_plan("card-404", at(10)) is True
    assert engine.card_plans.ok is not False


def test_remove_without_prefix_is_ignored(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    assert engine.card_plans.remove_plan("manual-1", at(10)) is False
    assert sources.plan_rules.removes() == []


def test_remove_network_failure_marks_engine_down(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    sources.plan_rules.fail = True
    engine.card_action(card["id"], {"action": "cancel"})
    assert engine.cards_payload()["engine"]["ok"] is False


def test_history_entry_with_expired_state_is_ignored(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    _plan_of(engine, card["id"])["history"] = [
        {"ts": "2026-11-04T10:00:03+08:00", "from": "observe", "to": "expired", "reason": "过期"}
    ]
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.list_card_history(card["id"]) == []


def test_history_entry_with_malformed_ts_is_ignored(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    _plan_of(engine, card["id"])["history"] = [
        {"ts": "not-a-time", "from": "observe", "to": "observe", "reason": "坏"}
    ]
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.list_card_history(card["id"]) == []


def test_history_merge_keeps_remote_order(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    payload = _plan_of(engine, card["id"])
    payload["history"] = [
        {"ts": "2026-11-04T10:00:03+08:00", "from": "observe", "to": "await_confirm", "reason": "1"},
        {"ts": "2026-11-04T10:00:06+08:00", "from": "await_confirm", "to": "execute", "reason": "2"},
    ]
    payload["state"] = "execute"
    engine._sync_cards(at(10, 0, 7))
    assert [row["from"] for row in engine.store.list_card_history(card["id"])] == [
        "observe",
        "await_confirm",
    ]


def test_await_confirm_to_execute_trigger_from_await_confirm(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    set_plan_state(engine, card["id"], "await_confirm")
    engine._sync_cards(at(10, 0, 3))
    set_plan_state(engine, card["id"], "execute")
    engine._sync_cards(at(10, 0, 6))
    assert triggers(engine)[-1]["from_state"] == "await_confirm"


def test_mirror_empty_conds_lists_stay_empty(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["conds"]["giveup"] == []


def test_engine_synced_at_advances(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    engine._sync_cards(clock())
    first = engine.store.get_card(card["id"])["engine"]["synced_at"]
    engine._sync_cards(at(10, 0, 3))
    second = engine.store.get_card(card["id"])["engine"]["synced_at"]
    assert first != second


def test_plan_payload_stop_is_float(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = engine.store.get_card(_create(engine, risk={"stop_price": 91})["card"]["id"])
    payload = plan_payload(card, held=False)
    assert payload["stop_price"] == 91.0
    assert isinstance(payload["stop_price"], float)


def test_normalize_engine_keeps_error_and_timestamp() -> None:
    assert normalize_engine({"ok": False, "error": "x", "synced_at": "2026-11-04T10:00:00+08:00"}) == {
        "ok": False,
        "error": "x",
        "synced_at": "2026-11-04T10:00:00+08:00",
    }


def test_plan_id_stays_within_forty_for_large_card_id() -> None:
    assert len(plan_id_for(10**9)) <= 40


def test_sync_expires_card_even_when_engine_is_down(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine, expires_at="2026-11-04T15:00:00+08:00")["card"]
    sources.plan_rules.fail = True
    clock.set(datetime(2026, 11, 5, 15, 1, tzinfo=CN_TZ))
    engine._sync_cards(clock())
    stored = engine.store.get_card(card["id"])
    assert stored["status"] == "expired"
    assert stored["state"] == "observe"


def test_sync_locks_card_even_when_engine_is_down(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    sources.plan_rules.fail = True
    engine._sync_cards(at(9, 26))
    assert engine.store.get_card(card["id"])["locked_at"] == at(9, 25)


def test_remote_plan_missing_label_re_pushes(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    card = _create(engine, name="贵州茅台")["card"]
    engine._sync_cards(clock())
    sources.plan_rules.states[f"card-{card['id']}"]["label"] = "旧标签"
    _reset_calls(engine)
    engine._sync_cards(at(10, 0, 3))
    assert len(sources.plan_rules.upserts()) == 1


def test_cancel_response_card_has_engine_status(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "cancel"})
    assert result["card"]["engine"]["ok"] is True
    assert result["card"]["status"] == "cancelled"
