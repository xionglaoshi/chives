from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from chives_signals.cards import CONDITION_TYPES, is_locked, validate_condition
from chives_signals.validation import ApiError
from tests.support import NOW, at, build_engine, set_plan_state

CARD = {
    "id": 1,
    "code": "600519.SH",
    "name": "贵州茅台",
    "status": "active",
    "state": "observe",
    "thesis": "x",
    "risk": {"stop_price": 90.0},
    "giveup": [],
    "market_conditions": [],
    "sector_conditions": [],
    "stock_conditions": [],
    "confirm_policy": "all",
    "created_at": NOW,
    "expires_at": at(15, 0),
}


# -- condition validation ------------------------------------------------
VALID_CONDITIONS = [
    {"type": "regime", "values": ["strong", "neutral"]},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 0.5},
    {"type": "sector_change", "sector_code": "BK0433", "op": "<=", "value": -1},
    {"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 3},
    {"type": "price_cross", "direction": "up", "level": 10.5},
    {"type": "price_in_range", "lo": 9.5, "hi": 11.5},
    {"type": "pct_change", "direction": "down", "threshold_pct": 3.0},
    {"type": "open_pct", "op": ">=", "value": 2.0},
    {"type": "volume_ratio", "op": ">=", "value": 1.5},
]


@pytest.mark.parametrize("raw", VALID_CONDITIONS)
def test_valid_condition_roundtrip(raw: dict) -> None:
    assert validate_condition(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "bogus"},
        {"type": "regime", "values": []},
        {"type": "regime", "values": ["hot"]},
        {"type": "index_pct", "code": "000002.SH", "op": ">=", "value": 1},
        {"type": "index_pct", "code": "000001.SH", "op": ">", "value": 1},
        {"type": "sector_change", "sector_code": "0433", "op": ">=", "value": 1},
        {"type": "sector_rank", "sector_code": "BK0433", "op": ">=", "value": 0},
        {"type": "price_cross", "direction": "sideways", "level": 1},
        {"type": "price_cross", "direction": "up", "level": 0},
        {"type": "price_in_range", "lo": 2, "hi": 1},
        {"type": "pct_change", "direction": "up", "threshold_pct": 101},
        {"type": "open_pct", "op": ">=", "value": 101},
        {"type": "volume_ratio", "op": "<=", "value": -1},
    ],
)
def test_invalid_condition_rejected(raw: dict) -> None:
    with pytest.raises(ApiError) as exc:
        validate_condition(raw)
    assert exc.value.code == "bad_condition"


def test_condition_extra_field_rejected() -> None:
    with pytest.raises(ApiError):
        validate_condition({"type": "price_cross", "direction": "up", "level": 1, "extra": 1})


def test_condition_type_whitelist_is_complete() -> None:
    assert CONDITION_TYPES == {
        "regime",
        "index_pct",
        "sector_change",
        "sector_rank",
        "price_cross",
        "price_in_range",
        "pct_change",
        "open_pct",
        "volume_ratio",
    }


# -- creation ------------------------------------------------------------
def _create(engine, **overrides):
    payload = {
        "code": "600519.SH",
        "thesis": "测试作战卡",
        "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99.0}],
        "risk": {"stop_price": 90.0},
        "proposed_by": "user",
    }
    payload.update(overrides)
    return engine.create_card(payload)


def test_create_user_card_is_active(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    result = _create(engine)
    assert result["card"]["status"] == "active"
    assert result["card"]["state"] == "observe"
    assert result["card"]["proposed_by"] == "user"


def test_create_agent_card_is_proposed_and_signals(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    result = _create(engine, proposed_by="agent")
    assert result["card"]["status"] == "proposed"
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_proposal"]
    assert len(rows) == 1
    assert rows[0]["decide"] is True
    assert rows[0]["primary"]["action"] == "confirm_card"


def test_create_rejects_bj(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, code="430047.BJ")
    assert exc.value.code == "invalid_code"


def test_create_rejects_bad_proposed_by(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, proposed_by="robot")


def test_create_rejects_long_thesis(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, thesis="字" * 201)


def test_create_rejects_too_many_conditions(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(
            engine,
            stock_conditions=[{"type": "price_cross", "direction": "up", "level": 1}] * 7,
        )
    assert exc.value.code == "too_many_conditions"


def test_create_rejects_bad_condition(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, stock_conditions=[{"type": "magic"}])
    assert exc.value.code == "bad_condition"


def test_create_rejects_unknown_field(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, extra=1)
    assert exc.value.code == "unexpected_field"


def test_create_rejects_missing_stop(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, risk={})


def test_create_rejects_stop_above_entry(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, risk={"stop_price": 120})
    assert exc.value.code == "bad_stop"


def test_create_rejects_stop_distance_over_30(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, risk={"stop_price": 50})
    assert exc.value.code == "bad_stop"


def test_create_rejects_exit_rules_over_three(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, risk={"stop_price": 90, "exit_rules": ["a", "b", "c", "d"]})


def test_create_default_expiry_next_trading_day(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    assert card["expires_at"] == "2026-11-05T15:00:00+08:00"


def test_create_rejects_expiry_beyond_five_days(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError) as exc:
        _create(engine, expires_at="2026-11-20T15:00:00+08:00")
    assert exc.value.code == "invalid_expiry"


def test_create_rejects_past_expiry(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, expires_at="2026-11-03T15:00:00+08:00")


def test_card_code_day_limit(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _create(engine)
    _create(engine)
    with pytest.raises(ApiError) as exc:
        _create(engine)
    assert exc.value.code == "card_code_limit"


def test_card_live_limit(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    for index in range(15):
        card = _create(engine, code=f"60{index:04d}.SH")["card"]
        engine.store.update_card(card["id"], status="active", now=NOW)
    with pytest.raises(ApiError) as exc:
        _create(engine, code="600000.SH")
    assert exc.value.code == "card_limit"


def test_create_confirm_policy_default_all(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert _create(engine)["card"]["confirm_policy"] == "all"


def test_create_rejects_bad_confirm_policy(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    with pytest.raises(ApiError):
        _create(engine, confirm_policy="most")


# -- sizing --------------------------------------------------------------
def _adopt(engine, key, value):
    engine.settings.action(key, {"action": "set", "value": value}, now=engine.now())


def test_sizing_risk_budget(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    sizing = _create(engine)["card"]["sizing"]
    assert sizing["risk_budget_cny"] == 10000.0
    assert sizing["stop_distance_pct"] == pytest.approx(9.0909)
    assert sizing["raw_position_cny"] == pytest.approx(110000.0)
    assert sizing["final_position_cny"] == pytest.approx(110000.0)
    assert sizing["final_qty_shares"] == 1100
    assert sizing["capped_by"] == "risk_budget"


def test_sizing_single_stock_cap(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 5)
    _adopt(engine, "single_stock_cap_pct", 5)
    sizing = _create(engine)["card"]["sizing"]
    assert sizing["raw_position_cny"] == pytest.approx(550000.0)
    assert sizing["final_position_cny"] == 50000.0
    assert sizing["final_qty_shares"] == 500
    assert sizing["capped_by"] == "single_stock_cap"


def test_sizing_total_cap_room(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 2)
    _adopt(engine, "total_cap_strong_pct", 25)
    sizing = _create(engine)["card"]["sizing"]
    assert sizing["raw_position_cny"] == pytest.approx(220000.0)
    assert sizing["final_position_cny"] == 50000.0
    assert sizing["capped_by"] == "total_cap"
    assert "position_cap" not in sizing["note"]


def test_sizing_position_cap(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 2)
    sizing = _create(engine, risk={"stop_price": 90.0, "position_cap_pct": 2})["card"]["sizing"]
    assert sizing["final_position_cny"] == 20000.0
    assert sizing["final_qty_shares"] == 200
    assert sizing["capped_by"] == "none"
    assert "position_cap_pct" in sizing["note"]


def test_sizing_rounds_down_to_100_shares(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    engine.sources.state = {
        "quotes": {"600519.SH": {"price": 33.33, "prev_close": 32.0, "change_pct": 4.0, "name": "贵州茅台"}}
    }
    sizing = _create(
        engine,
        stock_conditions=[{"type": "price_cross", "direction": "up", "level": 33.33}],
        risk={"stop_price": 30.0},
    )["card"]["sizing"]
    assert sizing["final_qty_shares"] % 100 == 0
    assert sizing["final_qty_shares"] == 3000


def test_sizing_requires_per_trade_risk(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    result = _create(engine)
    assert result["card"]["sizing"] is None
    assert "sizing_needs_per_trade_risk_pct" in result["warnings"]


def test_sizing_requires_portfolio(tmp_path: Path) -> None:
    engine, clock, _, portfolio = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    portfolio.overview_payload["totals"] = {}
    result = _create(engine)
    assert result["card"]["sizing"] is None
    assert "sizing_needs_portfolio" in result["warnings"]


def test_sizing_requires_entry_price(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    sources.state = {"quotes": {}}
    sources.quotes = {}
    result = _create(engine, stock_conditions=[])
    assert result["card"]["sizing"] is None
    assert "sizing_needs_price" in result["warnings"]


def test_sizing_uses_price_range_lower_bound(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    sizing = _create(
        engine,
        stock_conditions=[{"type": "price_in_range", "lo": 50.0, "hi": 60.0}],
        risk={"stop_price": 45.0},
    )["card"]["sizing"]
    assert "价格区间下沿" in sizing["note"]
    assert sizing["stop_distance_pct"] == pytest.approx(10.0)


def test_sizing_uses_latest_price(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _adopt(engine, "per_trade_risk_pct", 1)
    sizing = _create(engine, stock_conditions=[])["card"]["sizing"]
    assert "最新价" in sizing["note"]


# -- actions -------------------------------------------------------------
def test_confirm_proposed(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    result = engine.card_action(card["id"], {"action": "confirm"})
    assert result["card"]["status"] == "active"
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_proposal"]
    assert rows[0]["status"] == "done"


def test_confirm_active_rejected(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    with pytest.raises(ApiError):
        engine.card_action(card["id"], {"action": "confirm"})


def test_cancel_active(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "cancel"})
    assert result["card"]["status"] == "cancelled"


def test_cancel_after_lock_allowed(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    assert card["locked_at"] is not None
    assert engine.card_action(card["id"], {"action": "cancel"})["card"]["status"] == "cancelled"


def test_tighten_stop_updates_risk(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "tighten_stop", "stop": 94.0})
    assert result["card"]["risk"]["stop_price"] == 94.0


def test_tighten_stop_lower_rejected(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    with pytest.raises(ApiError) as exc:
        engine.card_action(card["id"], {"action": "tighten_stop", "stop": 85.0})
    assert exc.value.code == "loosen_not_allowed"


def test_tighten_stop_equal_rejected(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    with pytest.raises(ApiError) as exc:
        engine.card_action(card["id"], {"action": "tighten_stop", "stop": 90.0})
    assert exc.value.code == "loosen_not_allowed"


def test_set_state_before_lock_allowed(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    assert card["locked_at"] is None
    result = engine.card_action(card["id"], {"action": "set_state", "state": "execute"})
    assert result["card"]["state"] == "execute"
    history = engine.store.list_card_history(card["id"])
    assert history[-1]["to"] == "execute"
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_state"]
    assert len(rows) == 1


def test_set_state_upgrade_after_lock_rejected(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    with pytest.raises(ApiError) as exc:
        engine.card_action(card["id"], {"action": "set_state", "state": "execute"})
    assert exc.value.code == "locked"


@pytest.mark.parametrize("state", ["abandon", "exit"])
def test_set_state_downgrade_after_lock_allowed(tmp_path: Path, state: str) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "set_state", "state": state})
    assert result["card"]["state"] == state


def test_action_rejects_extra_field(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    with pytest.raises(ApiError):
        engine.card_action(card["id"], {"action": "cancel", "stop": 1})


# -- locking -------------------------------------------------------------
def test_card_created_before_open_is_not_late(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    assert card["late"] is False
    assert card["locked_at"] is None
    assert is_locked(engine.store.get_card(card["id"]), at(9, 0), engine.calendar) is False


def test_card_locks_at_0925_on_tick(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    engine._sync_cards(at(9, 26))
    stored = engine.store.get_card(card["id"])
    assert stored["locked_at"] == at(9, 25)


def test_card_created_after_open_is_late_and_locked(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    assert card["late"] is True
    assert card["locked_at"] == "2026-11-04T10:00:00+08:00"


def test_weekend_card_locks_next_trading_day(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=datetime(2026, 11, 7, 10, 0, tzinfo=NOW.tzinfo))
    card = _create(engine)["card"]
    assert card["late"] is False
    assert card["locked_at"] is None
    engine._sync_cards(datetime(2026, 11, 9, 9, 26, tzinfo=NOW.tzinfo))
    stored = engine.store.get_card(card["id"])
    assert stored["locked_at"] == datetime(2026, 11, 9, 9, 25, tzinfo=NOW.tzinfo)


# -- cn-watch mirror -----------------------------------------------------
def test_sync_mirrors_execute_and_history(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    set_plan_state(engine, card["id"], "execute", price=100.0)
    engine._sync_cards(clock())
    stored = engine.store.get_card(card["id"])
    assert stored["state"] == "execute"
    assert stored["last_price"] == 100.0
    history = engine.store.list_card_history(card["id"])
    assert history[-1]["from"] == "observe"
    assert history[-1]["to"] == "execute"
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_state"]
    assert len(rows) == 1


def test_sync_await_confirm(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    set_plan_state(engine, card["id"], "await_confirm")
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["state"] == "await_confirm"


def test_sync_giveup_abandons(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    set_plan_state(engine, card["id"], "abandon")
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["state"] == "abandon"


def test_sync_exit_when_held_and_stop_hit(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    set_plan_state(engine, card["id"], "exit", price=88.0)
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["state"] == "exit"


def test_sync_expires_card(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    clock.set(datetime(2026, 11, 6, 15, 1, tzinfo=NOW.tzinfo))
    engine._sync_cards(clock())
    assert engine.store.get_card(card["id"])["status"] == "expired"
    assert engine.sources.plan_rules.states == {}


def test_sync_skips_proposed(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine, proposed_by="agent")["card"]
    engine._sync_cards(clock())
    stored = engine.store.get_card(card["id"])
    assert stored["state"] == "observe"
    assert stored["last_price"] is None
    assert engine.sources.plan_rules.upserts() == []


def test_sync_repeated_state_keeps_one_signal_and_history(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    set_plan_state(engine, card["id"], "execute")
    engine._sync_cards(clock())
    engine._sync_cards(clock())
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_state"]
    assert len(rows) == 1
    assert len(engine.store.list_card_history(card["id"])) == 1


def test_paused_create_and_confirm_warn(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    engine.settings.action("pause_loss_streak", {"action": "set", "value": 1}, now=clock())
    from chives_signals import discipline

    discipline.apply_loss_streak(engine.store, {"action": "add"}, now=clock())
    created = _create(engine, proposed_by="agent")
    assert "paused" in created["warnings"]
    confirmed = engine.card_action(created["card"]["id"], {"action": "confirm"})
    assert "paused" in confirmed["warnings"]


def test_card_counts_use_terminal_bucket(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    first = _create(engine)["card"]
    engine.card_action(first["id"], {"action": "cancel"})
    payload = engine.cards_payload(status="closed")
    assert [card["id"] for card in payload["cards"]] == [first["id"]]
    assert payload["counts"]["closed"] == 1


def test_tighten_stop_after_lock_allowed(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "tighten_stop", "stop": 95.0})
    assert result["card"]["risk"]["stop_price"] == 95.0
    assert result["card"]["locked_at"] is not None


def test_tighten_stop_after_lock_lower_rejected(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    with pytest.raises(ApiError) as exc:
        engine.card_action(card["id"], {"action": "tighten_stop", "stop": 89.0})
    assert exc.value.code == "loosen_not_allowed"


def test_set_state_same_state_writes_nothing(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(8))
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "set_state", "state": "observe"})
    assert engine.store.list_card_history(card["id"]) == []
    assert result["card"]["state"] == "observe"


def test_cancel_after_lock_keeps_state(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine)["card"]
    result = engine.card_action(card["id"], {"action": "cancel"})
    assert result["card"]["status"] == "cancelled"
    assert engine.store.list_card_history(card["id"]) == []


def test_confirm_after_open_allowed_and_locks(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path, now=at(10))
    card = _create(engine, proposed_by="agent")["card"]
    result = engine.card_action(card["id"], {"action": "confirm"})
    assert result["card"]["status"] == "active"
    assert result["card"]["locked_at"] is not None
    assert result["card"]["late"] is True


def test_card_payload_has_conds_and_engine(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = _create(engine)["card"]
    assert card["conds"] == {"market": [], "sector": [], "stock": [], "giveup": []}
    assert set(card["engine"]) == {"ok", "error", "synced_at"}
    assert engine.cards_payload()["engine"] == {"ok": True}
