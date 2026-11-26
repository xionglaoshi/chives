from __future__ import annotations

import pytest

from chives_radar.engine import Engine
from chives_radar.plans import (
    MAX_CONDITIONS,
    MAX_PLANS,
    PlanError,
    validate_condition,
    validate_plan_payload,
)
from chives_radar.storage import FileStore
from support import FakeMarket, ScriptedSource, StepClock, config, plan

VALID_CONDITIONS = [
    {"type": "regime", "values": ["strong", "neutral"]},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 0.5},
    {"type": "index_pct", "code": "399006.SZ", "op": "<=", "value": -1.0},
    {"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 2.0},
    {"type": "sector_rank", "sector_code": "BK0477", "op": "<=", "value": 5},
    {"type": "price_cross", "direction": "up", "level": 16.5},
    {"type": "price_in_range", "lo": 15.0, "hi": 16.0},
    {"type": "pct_change", "direction": "down", "threshold_pct": 3.0},
    {"type": "open_pct", "op": ">=", "value": 1.0},
    {"type": "volume_ratio", "op": ">=", "value": 1.5},
]


@pytest.mark.parametrize("condition", VALID_CONDITIONS)
def test_valid_conditions_roundtrip(condition):
    cleaned = validate_condition(condition)
    assert cleaned["type"] == condition["type"]
    assert set(cleaned) == set(condition)


INVALID_CONDITIONS = [
    None,
    [],
    "regime",
    {"type": "unknown"},
    {"type": "regime"},
    {"type": "regime", "values": []},
    {"type": "regime", "values": ["hot"]},
    {"type": "regime", "values": ["strong", "strong"]},
    {"type": "regime", "values": ["strong"], "extra": 1},
    {"type": "index_pct", "code": "000000.SH", "op": ">=", "value": 1},
    {"type": "index_pct", "code": "000001.SH", "op": "=", "value": 1},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": "1"},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 101},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": float("nan")},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 1, "x": 1},
    {"type": "sector_change", "sector_code": "BK33", "op": ">=", "value": 1},
    {"type": "sector_change", "sector_code": "bk0433", "op": ">=", "value": 1},
    {"type": "sector_change", "sector_code": "BK0433", "op": ">", "value": 1},
    {"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 101},
    {"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 0},
    {"type": "sector_rank", "sector_code": "BK0433", "op": "<", "value": 1},
    {"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 1001},
    {"type": "price_cross", "direction": "up", "level": 0},
    {"type": "price_cross", "direction": "up", "level": -1},
    {"type": "price_cross", "direction": "sideways", "level": 1},
    {"type": "price_cross", "direction": "up", "level": True},
    {"type": "price_cross", "direction": "up", "level": 1, "extra": 1},
    {"type": "price_in_range", "lo": 16, "hi": 16},
    {"type": "price_in_range", "lo": 17, "hi": 16},
    {"type": "price_in_range", "lo": 0, "hi": 16},
    {"type": "price_in_range", "lo": 15, "hi": -1},
    {"type": "pct_change", "direction": "up", "threshold_pct": 0},
    {"type": "pct_change", "direction": "up", "threshold_pct": 101},
    {"type": "pct_change", "direction": "flat", "threshold_pct": 1},
    {"type": "pct_change", "direction": "up", "threshold_pct": "1"},
    {"type": "open_pct", "op": ">=", "value": 101},
    {"type": "open_pct", "op": ">=", "value": -101},
    {"type": "open_pct", "op": "!=", "value": 1},
    {"type": "volume_ratio", "op": ">=", "value": 0},
    {"type": "volume_ratio", "op": ">=", "value": -1},
    {"type": "volume_ratio", "op": ">=", "value": 1001},
    {"type": "volume_ratio", "op": ">=", "value": 1, "lo": 1},
]


@pytest.mark.parametrize("condition", INVALID_CONDITIONS)
def test_invalid_conditions_are_rejected(condition):
    with pytest.raises(PlanError) as excinfo:
        validate_condition(condition, "market[0]")
    assert excinfo.value.code == "invalid_condition"
    assert excinfo.value.field is not None


def test_coerce_ints_to_floats():
    cleaned = validate_condition({"type": "price_cross", "direction": "up", "level": 16})
    assert isinstance(cleaned["level"], float)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("id", "", "invalid_plan"),
        ("id", "x" * 41, "invalid_plan"),
        ("id", "bad id", "invalid_plan"),
        ("id", "计划", "invalid_plan"),
        ("id", 7, "invalid_plan"),
        ("code", "920001", "invalid_symbol"),
        ("code", "920001.BJ", "invalid_symbol"),
        ("code", "430047", "invalid_symbol"),
        ("code", "400001", "invalid_symbol"),
        ("code", "830799", "invalid_symbol"),
        ("code", "000001.SH", "invalid_symbol"),
        ("code", "399001", "invalid_symbol"),
        ("code", "ABC", "invalid_symbol"),
        ("code", None, "invalid_symbol"),
        ("policy", "most", "invalid_plan"),
        ("policy", 1, "invalid_plan"),
        ("held", "yes", "invalid_plan"),
        ("held", 1, "invalid_plan"),
        ("stop_price", 0, "invalid_plan"),
        ("stop_price", -1, "invalid_plan"),
        ("stop_price", "1.5", "invalid_plan"),
        ("stop_price", True, "invalid_plan"),
        ("label", 1, "invalid_plan"),
        ("label", "x" * 41, "invalid_plan"),
        ("expires_at", "2026-11-05", "invalid_plan"),
        ("expires_at", "2026-11-05T10:00:00", "invalid_plan"),
        ("expires_at", "tomorrow", "invalid_plan"),
        ("expires_at", 123, "invalid_plan"),
    ],
)
def test_plan_scalar_validation(field, value, code):
    payload = plan()
    payload[field] = value
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload(payload)
    assert excinfo.value.code == code
    assert excinfo.value.field == field


@pytest.mark.parametrize(
    "field",
    ["market", "sector", "stock", "giveup"],
)
def test_condition_groups_must_be_arrays(field):
    payload = plan()
    payload[field] = {"type": "regime", "values": ["strong"]}
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload(payload)
    assert excinfo.value.code == "invalid_plan"
    assert excinfo.value.field == field


@pytest.mark.parametrize("field", ["market", "sector", "stock", "giveup"])
def test_condition_group_limit_is_six(field):
    payload = plan()
    payload[field] = [{"type": "regime", "values": ["strong"]}] * (MAX_CONDITIONS + 1)
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload(payload)
    assert excinfo.value.code == "too_many_conditions"
    assert excinfo.value.field == field


@pytest.mark.parametrize("extra", ["active", "name", "thesis", "market_conditions"])
def test_unknown_plan_fields_are_rejected(extra):
    payload = plan()
    payload[extra] = 1
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload(payload)
    assert excinfo.value.code == "invalid_plan"
    assert excinfo.value.field == f"plan.{extra}"


def test_expires_at_must_be_timezone_aware_and_normalized():
    parsed = validate_plan_payload(
        plan(expires_at="2026-11-05T10:00:00+08:00")
    )
    assert parsed.expires_at is not None
    assert parsed.expires_at.tzinfo is not None
    parsed_utc = validate_plan_payload(plan(expires_at="2026-11-05T02:00:00+00:00"))
    assert parsed_utc.expires_at.isoformat() == "2026-11-05T10:00:00+08:00"


def test_defaults_are_applied():
    parsed = validate_plan_payload({"id": "p", "code": "002553"})
    assert parsed.code == "002553.SZ"
    assert parsed.market == ()
    assert parsed.sector == ()
    assert parsed.stock == ()
    assert parsed.giveup == ()
    assert parsed.policy == "all"
    assert parsed.held is False
    assert parsed.stop_price is None
    assert parsed.expires_at is None
    assert parsed.label == ""


def test_label_is_trimmed():
    parsed = validate_plan_payload(plan(label="  计划 A  "))
    assert parsed.label == "计划 A"


def test_missing_id_and_code():
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload({"code": "002553.SZ"})
    assert excinfo.value.field == "id"
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload({"id": "p"})
    assert excinfo.value.code == "invalid_symbol"


def test_plan_must_be_object():
    with pytest.raises(PlanError) as excinfo:
        validate_plan_payload([])
    assert excinfo.value.code == "invalid_plan"


def build(tmp_path, *, overrides=None, source=None, market=None):
    store = FileStore(tmp_path / "data")
    engine = Engine(
        config(**(overrides or {})),
        source or ScriptedSource([{}]),
        StepClock(),
        store,
        market_client=market or FakeMarket(),
    )
    return engine, store


def test_plan_limit_is_enforced(tmp_path):
    engine, store = build(tmp_path)
    for index in range(MAX_PLANS):
        engine.upsert_plan(plan(id=f"p{index}"))
    with pytest.raises(PlanError) as excinfo:
        engine.upsert_plan(plan(id="overflow"))
    assert excinfo.value.code == "too_many_plans"
    assert len(engine.plans_payload()["plans"]) == MAX_PLANS
    assert "overflow" not in (store.out_dir / "plans.runtime.json").read_text()


def test_duplicate_upsert_does_not_count_toward_limit(tmp_path):
    engine, _ = build(tmp_path)
    for index in range(MAX_PLANS):
        engine.upsert_plan(plan(id=f"p{index}"))
    result = engine.upsert_plan(plan(id="p0", label="updated"))
    assert result["status"] == "replaced"
    assert len(engine.plans_payload()["plans"]) == MAX_PLANS


def test_watchlist_limit_rejects_upsert_without_side_effects(tmp_path):
    engine, store = build(tmp_path, overrides={"limits": {"max_watchlist": 1}})
    with pytest.raises(PlanError) as excinfo:
        engine.upsert_plan(plan(code="601099.SH"))
    assert excinfo.value.code == "watchlist_full"
    assert [row["code"] for row in engine.watchlist_dict()["watchlist"]] == ["002553.SZ"]
    assert engine.plans_payload()["plans"] == []
    assert not (store.out_dir / "plans.runtime.json").exists()
    assert not (store.out_dir / "watchlist.runtime.json").exists()


def test_replacement_to_new_code_checks_limit(tmp_path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 3}})
    engine.upsert_plan(plan(id="p1", code="601099.SH"))
    engine.upsert_plan(plan(id="p2", code="600000.SH"))
    with pytest.raises(PlanError) as excinfo:
        engine.upsert_plan(plan(id="p1", code="300750.SZ"))
    assert excinfo.value.code == "watchlist_full"
    assert {row["code"] for row in engine.watchlist_dict()["watchlist"]} == {
        "002553.SZ",
        "601099.SH",
        "600000.SH",
    }


def test_invalid_upsert_leaves_state_untouched(tmp_path):
    engine, _ = build(tmp_path)
    engine.upsert_plan(plan())
    with pytest.raises(PlanError):
        engine.upsert_plan(plan(id="bad", market=[{"type": "nope"}]))
    assert [item["id"] for item in engine.plans_payload()["plans"]] == ["plan-1"]
