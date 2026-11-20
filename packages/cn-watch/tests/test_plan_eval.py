from __future__ import annotations

from datetime import datetime

import pytest

from cn_watch.models import CN_TZ
from cn_watch.plans import EvalContext, evaluate_plan, eval_condition, plan_state_dict, step_state, make_runtime, validate_plan_payload
from support import quote

NOW = datetime(2026, 11, 3, 10, 0, 0, tzinfo=CN_TZ)
BASE_QUOTE = quote(
    price=16.0,
    prev_close=15.0,
    open_=15.3,
    volume_ratio=2.0,
    exch=NOW,
)
CONTEXT = EvalContext(
    now=NOW,
    quote=BASE_QUOTE,
    regime="strong",
    indexes={"000001.SH": 1.0, "399001.SZ": -0.5},
    sectors={
        "BK0433": {"change_pct": 2.0, "rank": 1},
        "BK0477": {"change_pct": -1.0, "rank": 28},
    },
)

CASES = [
    ({"type": "regime", "values": ["strong"]}, True),
    ({"type": "regime", "values": ["weak"]}, False),
    ({"type": "regime", "values": ["neutral", "strong"]}, True),
    ({"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 1.0}, True),
    ({"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 1.1}, False),
    ({"type": "index_pct", "code": "000001.SH", "op": "<=", "value": 1.0}, True),
    ({"type": "index_pct", "code": "399001.SZ", "op": "<=", "value": -0.5}, True),
    ({"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 2.0}, True),
    ({"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 2.1}, False),
    ({"type": "sector_change", "sector_code": "BK0477", "op": "<=", "value": -1.0}, True),
    ({"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 1}, True),
    ({"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 0}, False),
    ({"type": "sector_rank", "sector_code": "BK0477", "op": ">=", "value": 20}, True),
    ({"type": "sector_rank", "sector_code": "BK0477", "op": ">=", "value": 30}, False),
    ({"type": "price_cross", "direction": "up", "level": 16.0}, True),
    ({"type": "price_cross", "direction": "up", "level": 16.01}, False),
    ({"type": "price_cross", "direction": "down", "level": 16.0}, True),
    ({"type": "price_cross", "direction": "down", "level": 15.99}, False),
    ({"type": "price_in_range", "lo": 15.0, "hi": 16.0}, True),
    ({"type": "price_in_range", "lo": 16.01, "hi": 17.0}, False),
    ({"type": "pct_change", "direction": "up", "threshold_pct": 6.66}, True),
    ({"type": "pct_change", "direction": "up", "threshold_pct": 6.67}, False),
    ({"type": "pct_change", "direction": "down", "threshold_pct": 6.66}, False),
    ({"type": "open_pct", "op": ">=", "value": 2.0}, True),
    ({"type": "open_pct", "op": ">=", "value": 2.01}, False),
    ({"type": "volume_ratio", "op": ">=", "value": 2.0}, True),
    ({"type": "volume_ratio", "op": ">=", "value": 2.01}, False),
]


@pytest.mark.parametrize("condition,expected", CASES)
def test_condition_evaluation(condition, expected):
    assert eval_condition(condition, CONTEXT) is expected


UNKNOWN_CASES = [
    {"type": "regime", "values": ["strong"]},
    {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 0},
    {"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 0},
    {"type": "sector_rank", "sector_code": "BK0433", "op": "<=", "value": 5},
    {"type": "price_cross", "direction": "up", "level": 10},
    {"type": "price_in_range", "lo": 10, "hi": 20},
    {"type": "pct_change", "direction": "up", "threshold_pct": 1},
    {"type": "volume_ratio", "op": ">=", "value": 1},
]


@pytest.mark.parametrize("condition", UNKNOWN_CASES)
def test_missing_data_is_unknown(condition):
    empty = EvalContext(now=NOW)
    assert eval_condition(condition, empty) is None


@pytest.mark.parametrize(
    "condition",
    [
        {"type": "sector_rank", "sector_code": "BK0000", "op": "<=", "value": 5},
        {"type": "index_pct", "code": "000001.SH", "op": ">=", "value": 0},
    ],
)
def test_missing_keys_are_unknown(condition):
    context = EvalContext(
        now=NOW,
        quote=BASE_QUOTE,
        regime="neutral",
        indexes={},
        sectors={"BK0433": {"change_pct": None, "rank": None}},
    )
    assert eval_condition(condition, context) is None


def test_open_pct_is_unknown_before_0925():
    early = datetime(2026, 11, 3, 9, 24, 59, tzinfo=CN_TZ)
    context = EvalContext(now=early, quote=BASE_QUOTE)
    assert eval_condition({"type": "open_pct", "op": ">=", "value": 1}, context) is None


def test_open_pct_at_0925_is_evaluated():
    exact = datetime(2026, 11, 3, 9, 25, 0, tzinfo=CN_TZ)
    context = EvalContext(now=exact, quote=BASE_QUOTE)
    assert eval_condition({"type": "open_pct", "op": ">=", "value": 2.0}, context) is True


@pytest.mark.parametrize(
    "field,bad",
    [
        ("open", 0.0),
        ("prev_close", 0.0),
        ("price", 0.0),
    ],
)
def test_zero_quote_fields_are_unknown(field, bad):
    broken = quote(price=16.0, prev_close=15.0, open_=15.3, exch=NOW)
    broken = type(broken)(**{**broken.__dict__, field: bad})
    context = EvalContext(now=NOW, quote=broken)
    condition = {
        "open": {"type": "open_pct", "op": ">=", "value": 0},
        "prev_close": {"type": "pct_change", "direction": "up", "threshold_pct": 1},
        "price": {"type": "price_cross", "direction": "up", "level": 1},
    }[field]
    assert eval_condition(condition, context) is None


def parsed(**overrides):
    return validate_plan_payload(
        {
            "id": "p",
            "code": "002553.SZ",
            "market": [],
            "sector": [],
            "stock": [],
            "giveup": [],
            **overrides,
        }
    )


def test_empty_market_sector_and_stock_means_execute():
    target, reason, conds, unknown = evaluate_plan(parsed(), CONTEXT)
    assert target == "execute"
    assert conds == {"market": [], "sector": [], "stock": [], "giveup": []}
    assert unknown == 0


def test_market_and_sector_true_stock_false_is_await_confirm():
    plan = parsed(
        market=[{"type": "regime", "values": ["strong"]}],
        sector=[{"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": 2}],
        stock=[{"type": "price_cross", "direction": "up", "level": 99}],
    )
    target, _, conds, _ = evaluate_plan(plan, CONTEXT)
    assert target == "await_confirm"
    assert conds["market"] == [True]
    assert conds["sector"] == [True]
    assert conds["stock"] == [False]


def test_market_false_is_observe_even_when_stock_true():
    plan = parsed(
        market=[{"type": "regime", "values": ["weak"]}],
        stock=[{"type": "price_cross", "direction": "up", "level": 1}],
    )
    assert evaluate_plan(plan, CONTEXT)[0] == "observe"


def test_stock_policy_all_requires_every_condition():
    plan = parsed(
        stock=[
            {"type": "price_cross", "direction": "up", "level": 1},
            {"type": "price_cross", "direction": "up", "level": 99},
        ],
        policy="all",
    )
    assert evaluate_plan(plan, CONTEXT)[0] == "await_confirm"


def test_stock_policy_any_accepts_one_condition():
    plan = parsed(
        stock=[
            {"type": "price_cross", "direction": "up", "level": 1},
            {"type": "price_cross", "direction": "up", "level": 99},
        ],
        policy="any",
    )
    assert evaluate_plan(plan, CONTEXT)[0] == "execute"


def test_stock_policy_any_with_all_unknown_is_false():
    plan = parsed(stock=[{"type": "volume_ratio", "op": ">=", "value": 1}], policy="any")
    empty = EvalContext(now=NOW)
    assert evaluate_plan(plan, empty)[0] == "await_confirm"


def test_giveup_has_priority_and_unknown_giveup_does_not_hit():
    plan = parsed(
        giveup=[{"type": "volume_ratio", "op": ">=", "value": 2}],
        stock=[{"type": "price_cross", "direction": "up", "level": 1}],
    )
    target, reason, _, unknown = evaluate_plan(plan, CONTEXT)
    assert target == "abandon"
    assert unknown == 0
    assert "放弃条件" in reason

    empty = EvalContext(now=NOW)
    target, reason, _, unknown = evaluate_plan(plan, empty)
    assert target == "await_confirm"
    assert unknown == 1
    assert "unknown" in reason


def test_giveup_beats_exit_and_execute():
    plan = parsed(
        held=True,
        stop_price=20.0,
        giveup=[{"type": "price_cross", "direction": "up", "level": 1}],
        stock=[{"type": "price_cross", "direction": "up", "level": 1}],
    )
    assert evaluate_plan(plan, CONTEXT)[0] == "abandon"


def test_exit_requires_held_and_stop():
    held = parsed(held=True, stop_price=16.0)
    assert evaluate_plan(held, CONTEXT)[0] == "exit"
    not_held = parsed(held=False, stop_price=16.0)
    assert evaluate_plan(not_held, CONTEXT)[0] == "execute"
    no_stop = parsed(held=True, stop_price=None)
    assert evaluate_plan(no_stop, CONTEXT)[0] == "execute"
    above = parsed(held=True, stop_price=15.99)
    assert evaluate_plan(above, CONTEXT)[0] == "execute"


def test_exit_wins_over_giveup_unknown_and_await():
    plan = parsed(
        held=True,
        stop_price=16.0,
        market=[{"type": "regime", "values": ["weak"]}],
        giveup=[{"type": "volume_ratio", "op": ">=", "value": 99}],
    )
    assert evaluate_plan(plan, CONTEXT)[0] == "exit"


@pytest.mark.parametrize(
    "current,target,streak,pending,expected,changed",
    [
        ("observe", "execute", 0, None, "execute", True),
        ("observe", "await_confirm", 0, None, "await_confirm", True),
        ("observe", "abandon", 0, None, "abandon", True),
        ("observe", "exit", 0, None, "exit", True),
        ("await_confirm", "execute", 0, None, "execute", True),
        ("execute", "abandon", 0, None, "abandon", True),
        ("execute", "exit", 0, None, "exit", True),
        ("execute", "await_confirm", 0, None, "execute", False),
        ("execute", "await_confirm", 1, "await_confirm", "execute", False),
        ("execute", "await_confirm", 2, "await_confirm", "await_confirm", True),
        ("execute", "observe", 0, None, "execute", False),
        ("execute", "observe", 2, "observe", "observe", True),
        ("await_confirm", "observe", 0, None, "await_confirm", False),
        ("await_confirm", "observe", 2, "observe", "observe", True),
        ("abandon", "observe", 0, None, "abandon", False),
        ("abandon", "observe", 2, "observe", "observe", True),
        ("abandon", "execute", 2, "execute", "execute", True),
        ("exit", "await_confirm", 2, "await_confirm", "await_confirm", True),
        ("exit", "abandon", 0, None, "exit", False),
        ("abandon", "exit", 0, None, "abandon", False),
        ("execute", "execute", 2, "observe", "execute", False),
    ],
)
def test_step_state(current, target, streak, pending, expected, changed):
    state, new_streak, new_pending, did_change = step_state(
        current, target, streak, pending
    )
    assert state == expected
    assert did_change is changed
    if changed:
        assert new_streak == 0 and new_pending is None


def test_step_state_restarts_streak_when_target_changes():
    state, streak, pending, changed = step_state("execute", "await_confirm", 2, "observe")
    assert (state, streak, pending, changed) == ("execute", 1, "await_confirm", False)
    state, streak, pending, changed = step_state("execute", "await_confirm", 1, "await_confirm")
    assert (state, streak, pending, changed) == ("execute", 2, "await_confirm", False)


def test_make_runtime_shape():
    runtime = make_runtime(parsed(market=[{"type": "regime", "values": ["strong"]}]), NOW)
    payload = plan_state_dict(runtime)
    assert payload["state"] == "observe"
    assert payload["active"] is True
    assert payload["conds"] == {"market": [None], "sector": [], "stock": [], "giveup": []}
    assert payload["history"] == []
