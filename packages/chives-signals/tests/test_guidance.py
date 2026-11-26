from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from chives_signals.guidance import (
    current_action,
    due_slot,
    market_state,
    next_check,
    risk_bound,
    theme_state,
)
from chives_signals.models import CN_TZ
from tests.support import active_card, adopt_setting, at, build_engine


def _day(hour: int, minute: int = 0, day: int = 4) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=CN_TZ)


@pytest.mark.parametrize(
    "hour,minute,slot",
    [(9, 30, "09:30"), (10, 0, "10:00"), (11, 30, "11:30"), (13, 0, "13:00"), (14, 30, "14:30")],
)
def test_due_slot_each_slot(tmp_path: Path, hour: int, minute: int, slot: str) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(_day(hour, minute), engine.calendar) == slot


def test_due_slot_inside_grace_window(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(_day(10, 4), engine.calendar) == "10:00"


def test_due_slot_after_grace_is_missed(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(_day(10, 5), engine.calendar) is None


def test_due_slot_between_slots(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(_day(9, 35), engine.calendar) is None


def test_due_slot_before_open(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(_day(9, 29), engine.calendar) is None


def test_due_slot_non_trading_day(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert due_slot(datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ), engine.calendar) is None


def test_guidance_not_generated_without_active_card(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine._maybe_guidance(at(10))
    assert engine.store.list_guidance("2026-11-04") == []
    assert [row for row in engine.store.list_signals(status="all") if row["kind"] == "guidance"] == []


def test_guidance_generation_creates_row_and_signal(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    rows = engine.store.list_guidance("2026-11-04")
    assert len(rows) == 1
    assert rows[0]["slot"] == "10:00"
    signals = [row for row in engine.store.list_signals(status="all") if row["kind"] == "guidance"]
    assert len(signals) == 1
    assert signals[0]["id"] == rows[0]["signal_id"]


def test_guidance_signal_contract(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    signal = [row for row in engine.store.list_signals(status="all") if row["kind"] == "guidance"][0]
    assert signal["severity"] == "L1"
    assert signal["decide"] is False
    assert signal["primary"]["action"] == "open"
    assert signal["object_type"] == "market"
    assert len(signal["conclusion"]) <= 60
    assert len(signal["brief"]) <= 140


def test_guidance_each_slot_once_per_day(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    for slot, moment in (
        ("09:30", at(9, 30)),
        ("10:00", at(10)),
        ("11:30", at(11, 30)),
        ("13:00", at(13)),
        ("14:30", at(14, 30)),
    ):
        engine._maybe_guidance(moment)
        engine._maybe_guidance(moment)
    assert [row["slot"] for row in engine.store.list_guidance("2026-11-04")] == [
        "09:30",
        "10:00",
        "11:30",
        "13:00",
        "14:30",
    ]


def test_guidance_restart_does_not_duplicate(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    second, _, _, _ = build_engine(tmp_path)
    second._maybe_guidance(at(10))
    assert len(second.store.list_guidance("2026-11-04")) == 1
    assert len([row for row in second.store.list_signals(status="all") if row["kind"] == "guidance"]) == 1


def test_guidance_missed_slot_not_backfilled(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10, 6))
    assert engine.store.list_guidance("2026-11-04") == []


def test_guidance_non_trading_day_not_generated(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ))
    assert engine.store.list_guidance("2026-11-07") == []


def test_guidance_context_contract(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    context = engine.store.list_guidance("2026-11-04")[0]["context"]
    assert {
        "type",
        "slot",
        "data_time",
        "market_state",
        "theme_state",
        "cards",
        "current_action",
        "next_check",
        "risk_bound",
    } == set(context)
    assert context["type"] == "guidance"
    assert context["data_time"] == "10:00"


def test_guidance_cards_block(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine)
    engine._maybe_guidance(at(10))
    cards = engine.store.list_guidance("2026-11-04")[0]["context"]["cards"]
    assert cards == [
        {"id": card["id"], "code": "600519.SH", "name": "600519.SH", "state": "observe"}
    ]


def test_guidance_first_slot_theme_state_continuation(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(9, 30))
    assert engine.store.list_guidance("2026-11-04")[0]["context"]["theme_state"] == "延续"


def test_guidance_theme_state_weakens_after_rank_slip(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(9, 30))
    sources.sectors_payload["rows"][0]["rank"] = 2
    engine._maybe_guidance(at(10))
    rows = engine.store.list_guidance("2026-11-04")
    assert rows[1]["context"]["theme_state"] == "走弱"


def test_guidance_theme_state_weakens_after_limit_drop(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(9, 30))
    sources.overview_payload["breadth"]["limit_up"] = 48
    engine._maybe_guidance(at(10))
    rows = engine.store.list_guidance("2026-11-04")
    assert rows[1]["context"]["theme_state"] == "走弱"


def test_guidance_theme_state_unknown_without_sector_rows(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    active_card(engine)
    sources.sectors_payload = {"ok": True, "rows": []}
    engine._maybe_guidance(at(10))
    context = engine.store.list_guidance("2026-11-04")[0]["context"]
    assert context["theme_state"] == "未知"


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        (None, None, "未知"),
        ({}, {}, "未知"),
        (None, {"rank": 1}, "延续"),
        (None, {"rank": 8}, "分歧"),
        ({"rank": 4}, {"rank": 2}, "延续"),
        ({"rank": 2}, {"rank": 2, "change_pct": 3.0}, "延续"),
        ({"rank": 2, "change_pct": 3.0}, {"rank": 2, "change_pct": 1.0}, "分歧"),
        ({"rank": 2}, {"rank": 3}, "走弱"),
        ({"rank": 2, "limit_up_count": 60}, {"rank": 2, "limit_up_count": 48}, "走弱"),
        ({"rank": 2, "limit_up_count": 20}, {"rank": 2, "limit_up_count": 14}, "走弱"),
        ({"rank": 2, "limit_up_count": 20}, {"rank": 2, "limit_up_count": 16}, "延续"),
        ({"rank": 10}, {"rank": 8}, "分歧"),
        ({"rank": 2, "change_pct": 3.0}, {"rank": 2, "change_pct": 3.2}, "延续"),
    ],
)
def test_theme_state_rules(previous, current, expected: str) -> None:
    assert theme_state(previous, current) == expected


@pytest.mark.parametrize(
    "label,expected",
    [("risk_on", "偏强"), ("neutral", "中性"), ("risk_off", "偏弱"), ("weird", "未知")],
)
def test_market_state_labels(label: str, expected: str) -> None:
    overview = {"regime": {"label": label, "reasons": ["宽度走强"]}}
    assert market_state(overview)["label"] == expected


def test_market_state_unknown_without_overview() -> None:
    assert market_state(None) == {"label": "未知", "basis": "市场环境取不到"}


def test_market_state_basis_from_reasons() -> None:
    overview = {"regime": {"label": "risk_on", "reasons": ["宽度走强", "成交额放大"]}}
    assert market_state(overview)["basis"] == "宽度走强；成交额放大"


@pytest.mark.parametrize(
    "state,expected",
    [
        ("observe", "观察"),
        ("await_confirm", "等待确认"),
        ("execute", "按预案执行"),
        ("abandon", "放弃"),
        ("exit", "按计划退出"),
    ],
)
def test_current_action_mapping(state: str, expected: str) -> None:
    assert current_action([{"state": state}]) == expected


def test_current_action_without_cards() -> None:
    assert current_action([]) == "无预案"


def test_current_action_priority() -> None:
    cards = [{"state": "observe"}, {"state": "execute"}, {"state": "await_confirm"}]
    assert current_action(cards) == "按预案执行"


@pytest.mark.parametrize(
    "slot,expected",
    [
        ("09:30", "10:00"),
        ("10:00", "11:30"),
        ("11:30", "13:00"),
        ("13:00", "14:30"),
        ("14:30", "15:00"),
    ],
)
def test_next_check_slots(slot: str, expected: str) -> None:
    assert next_check(slot) == expected


def test_risk_bound_unset(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert risk_bound(engine.settings, "strong") == "未设置"


def test_risk_bound_uses_only_adopted_values(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    adopt_setting(engine, "total_cap_strong_pct", 60)
    adopt_setting(engine, "single_stock_cap_pct", 25)
    adopt_setting(engine, "per_trade_risk_pct", 2)
    engine.setting_suggest("theme_cap_pct", {"value": 30, "basis": "建议"})
    assert risk_bound(engine.settings, "strong") == "总仓位≤60%；单票≤25%；单笔风险≤2%"


def test_guidance_payload_lists_rows(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    payload = engine.guidance_payload()
    assert payload["ok"] is True
    assert payload["date"] == "2026-11-04"
    assert payload["count"] == 1
    assert payload["guidance"][0]["slot"] == "10:00"


def test_guidance_payload_other_date_empty(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    payload = engine.guidance_payload("2026-10-30")
    assert payload["count"] == 0
    assert payload["guidance"] == []


def test_guidance_saved_once_per_slot_in_store(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    assert engine.store.get_guidance("2026-11-04", "10:00") is not None
    assert engine.store.get_guidance("2026-11-04", "10:00")["slot"] == "10:00"


def test_tick_generates_guidance_automatically(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine.tick(force=True)
    assert [row["slot"] for row in engine.store.list_guidance("2026-11-04")] == ["10:00"]


def test_guidance_skips_proposed_card(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine, proposed_by="agent")
    engine._maybe_guidance(at(10))
    assert engine.store.list_guidance("2026-11-04") == []


def test_guidance_ignores_expired_card(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(engine, expires_at="2026-11-04T10:00:03+08:00")
    engine.store.update_card(card["id"], status="expired", now=at(10))
    engine._maybe_guidance(at(10))
    assert engine.store.list_guidance("2026-11-04") == []


def test_store_guidance_duplicate_returns_none(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    active_card(engine)
    engine._maybe_guidance(at(10))
    row = engine.store.get_guidance("2026-11-04", "10:00")
    signal = engine.store.get_signal(row["signal_id"])
    from chives_signals.signals import guidance_signal

    assert (
        engine.store.save_guidance(
            day="2026-11-04",
            slot="10:00",
            signal=guidance_signal(row["context"], day="2026-11-04", slot="10:00", now=at(10)),
            context=row["context"],
            theme=None,
            now=at(10),
        )
        is None
    )
