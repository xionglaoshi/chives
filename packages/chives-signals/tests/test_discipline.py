from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from chives_signals import discipline
from chives_signals.settings import SettingsService
from chives_signals.store import HubStore
from chives_signals.validation import ApiError
from tests.support import DEFAULT_TOTALS, NOW, build_engine


def overview(**totals) -> dict:
    merged = dict(DEFAULT_TOTALS)
    merged.update(totals)
    return {
        "ok": True,
        "private": True,
        "empty": False,
        "positions": [
            {"code": "600519.SH", "name": "贵州茅台", "weight_pct": 20.0, "pnl_pct": 5.0, "industry": "食品饮料"},
            {"code": "000001.SZ", "name": "平安银行", "weight_pct": 10.0, "pnl_pct": -2.0, "industry": "银行"},
        ],
        "totals": merged,
    }


@pytest.fixture
def store(tmp_path: Path) -> HubStore:
    return HubStore(tmp_path / "hub.db")


@pytest.fixture
def settings(store: HubStore) -> SettingsService:
    return SettingsService(store)


def test_day_drawdown_uses_previous_snapshot(store: HubStore) -> None:
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=900000,
        total_assets_cny=1000000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    value = discipline.day_drawdown_pct(store, overview(total_assets_cny=950000), NOW)
    assert value == pytest.approx(5.0)


def test_day_drawdown_without_snapshot_is_null(store: HubStore) -> None:
    assert discipline.day_drawdown_pct(store, overview(), NOW) is None


def test_day_drawdown_never_negative(store: HubStore) -> None:
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=900000,
        total_assets_cny=900000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    assert discipline.day_drawdown_pct(store, overview(total_assets_cny=1000000), NOW) == 0.0


def test_day_drawdown_ignores_same_day_snapshot(store: HubStore) -> None:
    store.insert_snapshot(
        day=date(2026, 11, 4),
        market_value_cny=900000,
        total_assets_cny=900000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    assert discipline.day_drawdown_pct(store, overview(total_assets_cny=950000), NOW) is None


@pytest.mark.parametrize(
    ("pnl", "cost", "expected"),
    [(-10000, 100000, 10.0), (10000, 100000, 0.0), (0, 100000, 0.0), (-1, 0, None)],
)
def test_total_loss_pct(pnl: float, cost: float, expected: float | None) -> None:
    value = discipline.total_loss_pct(overview(pnl_cny=pnl, cost_cny=cost))
    if expected is None:
        assert value is None
    else:
        assert value == pytest.approx(expected)


def test_no_adopted_threshold_never_pauses(store: HubStore, settings: SettingsService) -> None:
    payload = discipline.discipline_payload(
        store=store, settings=settings, overview=overview(), now=NOW, regime="strong"
    )
    assert payload["paused"] is False
    assert payload["reasons"] == []
    assert payload["thresholds"] == {}


def test_thresholds_only_include_adopted(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_day_drawdown_pct", {"action": "set", "value": 5}, now=NOW)
    payload = discipline.discipline_payload(
        store=store, settings=settings, overview=overview(), now=NOW
    )
    assert payload["thresholds"] == {"pause_day_drawdown_pct": 5.0}


@pytest.mark.parametrize("value", [5.0, 5.4, 9.9])
def test_day_drawdown_boundary(store: HubStore, settings: SettingsService, value: float) -> None:
    settings.action("pause_day_drawdown_pct", {"action": "set", "value": 5}, now=NOW)
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=1000000,
        total_assets_cny=1000000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    payload = discipline.discipline_payload(
        store=store,
        settings=settings,
        overview=overview(total_assets_cny=1000000 * (1 - value / 100)),
        now=NOW,
    )
    assert payload["paused"] is True
    assert payload["reasons"][0]["rule"] == "day_drawdown"


def test_day_drawdown_below_threshold(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_day_drawdown_pct", {"action": "set", "value": 5}, now=NOW)
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=1000000,
        total_assets_cny=1000000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    payload = discipline.discipline_payload(
        store=store,
        settings=settings,
        overview=overview(total_assets_cny=960000),
        now=NOW,
    )
    assert payload["paused"] is False


def test_total_loss_triggers(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_total_loss_pct", {"action": "set", "value": 5}, now=NOW)
    payload = discipline.discipline_payload(
        store=store,
        settings=settings,
        overview=overview(pnl_cny=-6000, cost_cny=100000),
        now=NOW,
    )
    assert payload["paused"] is True
    assert payload["reasons"][0]["rule"] == "total_loss"


def test_total_loss_not_triggered_when_profitable(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_total_loss_pct", {"action": "set", "value": 5}, now=NOW)
    payload = discipline.discipline_payload(
        store=store, settings=settings, overview=overview(pnl_cny=6000), now=NOW
    )
    assert payload["paused"] is False


def test_loss_streak_add_and_reset(store: HubStore) -> None:
    assert discipline.apply_loss_streak(store, {"action": "add"}, now=NOW)["loss_streak"] == 1
    assert discipline.apply_loss_streak(store, {"action": "add"}, now=NOW)["loss_streak"] == 2
    assert discipline.loss_streak(store) == 2
    assert discipline.apply_loss_streak(store, {"action": "reset"}, now=NOW)["loss_streak"] == 0


def test_loss_streak_rejects_bad_action(store: HubStore) -> None:
    with pytest.raises(ApiError):
        discipline.apply_loss_streak(store, {"action": "bogus"}, now=NOW)


def test_loss_streak_threshold(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_loss_streak", {"action": "set", "value": 3}, now=NOW)
    for _ in range(2):
        discipline.apply_loss_streak(store, {"action": "add"}, now=NOW)
    payload = discipline.discipline_payload(
        store=store, settings=settings, overview=overview(), now=NOW
    )
    assert payload["paused"] is False
    discipline.apply_loss_streak(store, {"action": "add"}, now=NOW)
    payload = discipline.discipline_payload(
        store=store, settings=settings, overview=overview(), now=NOW
    )
    assert payload["paused"] is True
    assert payload["reasons"][0]["rule"] == "loss_streak"


def test_multiple_reasons(store: HubStore, settings: SettingsService) -> None:
    settings.action("pause_day_drawdown_pct", {"action": "set", "value": 1}, now=NOW)
    settings.action("pause_total_loss_pct", {"action": "set", "value": 1}, now=NOW)
    settings.action("pause_loss_streak", {"action": "set", "value": 1}, now=NOW)
    discipline.apply_loss_streak(store, {"action": "add"}, now=NOW)
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=1000000,
        total_assets_cny=1000000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    payload = discipline.discipline_payload(
        store=store,
        settings=settings,
        overview=overview(total_assets_cny=900000, pnl_cny=-10000, cost_cny=100000),
        now=NOW,
    )
    assert {reason["rule"] for reason in payload["reasons"]} == {
        "day_drawdown",
        "total_loss",
        "loss_streak",
    }


def test_unadopted_pause_threshold_not_evaluated(store: HubStore, settings: SettingsService) -> None:
    settings.suggest("pause_day_drawdown_pct", {"value": 1, "basis": "b"}, now=NOW)
    store.insert_snapshot(
        day=date(2026, 11, 3),
        market_value_cny=1000000,
        total_assets_cny=1000000,
        pnl_cny=0,
        day_pnl_cny=0,
        quote_time=None,
        now=NOW,
    )
    payload = discipline.discipline_payload(
        store=store,
        settings=settings,
        overview=overview(total_assets_cny=900000),
        now=NOW,
    )
    assert payload["paused"] is False
    assert payload["thresholds"] == {}


@pytest.mark.parametrize("slot", ["pre", "mid", "post"])
@pytest.mark.parametrize("level", ["calm", "volatile", "unfit"])
def test_mood_roundtrip(store: HubStore, slot: str, level: str) -> None:
    payload = discipline.apply_mood(
        store, {"slot": slot, "level": level, "note": "有点紧张"}, now=NOW
    )
    assert payload["mood_today"][slot] == level


def test_mood_invalid_slot_and_level(store: HubStore) -> None:
    with pytest.raises(ApiError):
        discipline.apply_mood(store, {"slot": "noon", "level": "calm"}, now=NOW)
    with pytest.raises(ApiError):
        discipline.apply_mood(store, {"slot": "pre", "level": "angry"}, now=NOW)


def test_mood_note_too_long(store: HubStore) -> None:
    with pytest.raises(ApiError):
        discipline.apply_mood(
            store, {"slot": "pre", "level": "calm", "note": "字" * 61}, now=NOW
        )


def test_mood_same_slot_overwrites(store: HubStore) -> None:
    discipline.apply_mood(store, {"slot": "pre", "level": "calm"}, now=NOW)
    payload = discipline.apply_mood(store, {"slot": "pre", "level": "unfit"}, now=NOW)
    assert payload["mood_today"] == {"pre": "unfit", "mid": None, "post": None}


def test_headroom_without_settings(store: HubStore, settings: SettingsService) -> None:
    result = discipline.headroom(overview(), settings, regime="strong")
    assert result["total_cap_pct"] is None
    assert result["total_room_pct"] is None
    assert result["single_room_pct"] is None
    assert result["theme_room_pct"] is None
    assert result["position_ratio_pct"] == 20.0
    assert result["top_weight_pct"] == 20.0
    assert result["top_theme"] == {"name": "食品饮料", "weight_pct": 20.0}
    assert result["theme_cap_pct"] is None


def test_headroom_picks_total_cap_by_regime(store: HubStore, settings: SettingsService) -> None:
    settings.action("total_cap_strong_pct", {"action": "set", "value": 80}, now=NOW)
    settings.action("total_cap_neutral_pct", {"action": "set", "value": 50}, now=NOW)
    strong = discipline.headroom(overview(), settings, regime="strong")
    neutral = discipline.headroom(overview(), settings, regime="neutral")
    assert strong["total_cap_pct"] == 80
    assert strong["total_room_pct"] == 60
    assert neutral["total_cap_pct"] == 50
    assert neutral["total_room_pct"] == 30


def test_headroom_rooms_never_negative(store: HubStore, settings: SettingsService) -> None:
    settings.action("total_cap_weak_pct", {"action": "set", "value": 10}, now=NOW)
    settings.action("single_stock_cap_pct", {"action": "set", "value": 5}, now=NOW)
    settings.action("theme_cap_pct", {"action": "set", "value": 5}, now=NOW)
    result = discipline.headroom(overview(), settings, regime="weak")
    assert result["total_room_pct"] == 0.0
    assert result["single_room_pct"] == 0.0
    assert result["theme_room_pct"] == 0.0


def test_headroom_aggregates_theme_weights(store: HubStore, settings: SettingsService) -> None:
    payload = overview()
    payload["positions"] = [
        {"code": "600519.SH", "name": "贵州茅台", "weight_pct": 20.0, "industry": "食品饮料"},
        {"code": "000858.SZ", "name": "五粮液", "weight_pct": 15.0, "industry": "食品饮料"},
        {"code": "000001.SZ", "name": "平安银行", "weight_pct": 10.0, "industry": "银行"},
    ]
    result = discipline.headroom(payload, settings, regime="strong")
    assert result["top_theme"] == {"name": "食品饮料", "weight_pct": 35.0}


def test_paused_reasons_ignore_missing_metric() -> None:
    assert discipline.paused_reasons(
        {"day_drawdown_pct": None, "total_loss_pct": None, "loss_streak": 0},
        {"day_drawdown": 1, "total_loss": 1, "loss_streak": 3},
    ) == []


def test_engine_discipline_pause_signal_is_daily_deduplicated(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    engine.settings.action("pause_loss_streak", {"action": "set", "value": 1}, now=clock())
    discipline.apply_loss_streak(engine.store, {"action": "add"}, now=clock())
    engine._evaluate_discipline(clock())
    engine._evaluate_discipline(clock())
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "discipline"]
    assert len(rows) == 1


def test_engine_discipline_no_signal_when_not_paused(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    engine._evaluate_discipline(clock())
    assert [row for row in engine.store.list_signals(status="all") if row["kind"] == "discipline"] == []


def test_portfolio_overview_includes_limits(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    engine.settings.action("total_cap_strong_pct", {"action": "set", "value": 80}, now=clock())
    payload = engine.overview()
    assert payload["limits"]["total_cap_pct"] == 80
    assert payload["limits"]["position_ratio_pct"] == 20.0


def test_portfolio_overview_limits_null_when_regime_unknown(tmp_path: Path) -> None:
    engine, clock, sources, _ = build_engine(tmp_path)
    sources.fail_overview = True
    payload = engine.overview()
    assert payload["limits"]["total_cap_pct"] is None


def test_total_loss_falls_back_to_positions() -> None:
    payload = {
        "positions": [
            {"code": "600519.SH", "qty": 100.0, "cost_price_cny": 100.0, "pnl_cny": -1000.0}
        ],
        "totals": {},
    }
    assert discipline.total_loss_pct(payload) == pytest.approx(10.0)
