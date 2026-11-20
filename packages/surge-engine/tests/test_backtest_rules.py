"""Offline tests for the frozen T159 trading rules (hand-made bars)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from surge_engine.backtest import (
    INITIAL_CAPITAL,
    PriceBar,
    SecurityInfo,
    Signal,
    commission,
    evaluate_signal,
    find_buy,
    per_trade_row,
    run_portfolio,
    stamp_tax,
)

D = [date(2020, 1, day) for day in range(1, 21)]


class FakeSource:
    def __init__(self, bars, limit_up=None, limit_down=None, securities=None):
        self.calendar = list(D)
        self.index = {day: offset for offset, day in enumerate(self.calendar)}
        self.bars = bars
        self.limit_up = limit_up or {}
        self.limit_down = limit_down or {}
        self.securities = securities or {}

    def bar(self, code, day):
        raw = self.bars.get(code, {}).get(day)
        return None if raw is None else PriceBar(day=day, open=raw[0], close=raw[1], adj_factor=raw[2])

    def security(self, code):
        return self.securities.get(code) or SecurityInfo(code=code, name=code, board="sh_main")

    def limit_up_price(self, code, day):
        return self.limit_up.get((code, day))

    def limit_down_price(self, code, day):
        return self.limit_down.get((code, day))


def signal(code="600000.SH", signal_day=D[0], out_day=None, rank=1, scheme="p1"):
    return Signal(
        scheme=scheme,
        code=code,
        round_id=1,
        signal_date=signal_day,
        rank=rank,
        score=85,
        base_score=80,
        gain=0.1,
        main_out_date=out_day,
        main_out_reason="ma10_unrepaired" if out_day else None,
    )


def test_buy_is_next_trading_day_open_with_slippage():
    bars = {"600000.SH": {D[0]: (10, 10, 1.0), D[1]: (11, 12, 1.0), D[2]: (12.5, 12, 1.0), D[3]: (13, 14, 1.0)}}
    source = FakeSource(bars)
    plan = evaluate_signal(source, signal(out_day=D[2]), end_index=4, cutoff=D[4])
    assert plan.status == "ok"
    assert plan.buy_day == D[1]
    assert plan.buy_open == 11
    assert plan.buy_exec == pytest.approx(11.011)
    assert plan.sell_day == D[3]
    assert plan.sell_open == 13
    assert plan.sell_exec == pytest.approx(12.987)
    assert plan.buy_index > source.index[D[0]]
    assert plan.sell_index > plan.buy_index


def test_one_word_limit_up_at_open_cannot_buy():
    bars = {"600000.SH": {D[0]: (10, 10, 1.0), D[1]: (11, 11, 1.0)}}
    source = FakeSource(bars, limit_up={("600000.SH", D[1]): Decimal("11.00")})
    plan = evaluate_signal(source, signal(), end_index=4, cutoff=D[4])
    assert plan.status == "unfilled_limit_up"
    assert per_trade_row(plan)["return_pct"] == ""


def test_suspension_rolls_up_to_five_days_then_abandons():
    bars = {"600000.SH": {D[0]: (10, 10, 1.0), D[5]: (11, 11, 1.0)}}
    source = FakeSource(bars)
    plan = evaluate_signal(source, signal(), end_index=10, cutoff=D[10])
    assert plan.status == "ok"
    assert plan.buy_day == D[5]
    assert plan.delay_days == 5

    bars_late = {"600000.SH": {D[0]: (10, 10, 1.0), D[6]: (11, 11, 1.0)}}
    late = evaluate_signal(FakeSource(bars_late), signal(), end_index=10, cutoff=D[10])
    assert late.status == "suspension_abandoned"


def test_limit_down_at_open_delays_sell():
    bars = {
        "600000.SH": {
            D[0]: (10, 10, 1.0),
            D[1]: (11, 11, 1.0),
            D[2]: (11, 11, 1.0),
            D[3]: (10, 10, 1.0),
            D[4]: (10.2, 10.2, 1.0),
        }
    }
    source = FakeSource(bars, limit_down={("600000.SH", D[3]): Decimal("10.00")})
    plan = evaluate_signal(source, signal(out_day=D[2]), end_index=5, cutoff=D[5])
    assert plan.status == "ok"
    assert plan.sell_day == D[4]
    assert plan.sell_open == pytest.approx(10.2)


def test_ex_rights_factor_prevents_fake_loss():
    bars = {
        "600000.SH": {
            D[0]: (10, 10, 1.0),
            D[1]: (10, 10, 1.0),
            D[2]: (5, 5, 2.0),
            D[3]: (5, 5, 2.0),
        }
    }
    source = FakeSource(bars)
    plan = evaluate_signal(source, signal(out_day=D[2]), end_index=4, cutoff=D[4])
    row = per_trade_row(plan)
    assert plan.sell_open == 5
    assert plan.buy_factor == 1.0
    assert plan.sell_factor == 2.0
    assert float(row["return_pct"]) > -2.0, "除权日不应出现约 -50% 的假亏损"


def test_stamp_tax_switch_min_commission_and_slippage_direction():
    assert stamp_tax(100_000, date(2023, 8, 25)) == pytest.approx(100.0)
    assert stamp_tax(100_000, date(2023, 8, 28)) == pytest.approx(50.0)
    assert commission(1_000) == 5.0
    assert commission(100_000) == 25.0

    bars = {"600000.SH": {D[0]: (10, 10, 1.0), D[1]: (10, 10, 1.0), D[2]: (10, 10, 1.0), D[3]: (10, 10, 1.0)}}
    plan = evaluate_signal(FakeSource(bars), signal(out_day=D[1]), end_index=4, cutoff=D[4])
    assert plan.buy_exec > plan.buy_open
    assert plan.sell_exec < plan.sell_open


def test_unclosed_position_is_valued_at_cutoff_close():
    bars = {
        "600000.SH": {
            D[0]: (10, 10, 1.0),
            D[1]: (10, 10, 1.0),
            D[2]: (11, 12, 1.0),
        }
    }
    plan = evaluate_signal(FakeSource(bars), signal(out_day=None), end_index=2, cutoff=D[2])
    row = per_trade_row(plan)
    assert plan.unclosed is True
    assert row["valuation_date"] == D[2].isoformat()
    assert row["sell_net"] != ""
    assert float(row["return_pct"]) > 15.0


def test_full_slots_use_rank_and_skip_the_rest():
    codes = [f"60000{index}.SH" for index in range(12)]
    bars = {}
    for index, code in enumerate(codes):
        bars[code] = {
            D[0]: (10, 10, 1.0),
            D[1]: (10, 10, 1.0),
            D[2]: (10, 10, 1.0),
            D[3]: (10, 10, 1.0),
        }
    source = FakeSource(bars)
    plans = [
        evaluate_signal(source, signal(code=code, out_day=D[2], rank=index + 1), end_index=4, cutoff=D[4])
        for index, code in enumerate(codes)
    ]
    result = run_portfolio(plans, source, 0, 3, initial_capital=INITIAL_CAPITAL)
    assert [row["code"] for row in result["skipped"]] == codes[10:]
    assert {row["reason"] for row in result["skipped"]} == {"仓位已满跳过"}
    assert result["equity_rows"][0]["positions"] == 0
    assert result["equity_rows"][1]["positions"] == 10


def test_find_buy_never_returns_signal_day():
    bars = {"600000.SH": {D[0]: (10, 10, 1.0), D[1]: (11, 11, 1.0)}}
    source = FakeSource(bars)
    status, index, bar = find_buy(source, signal(), end_index=2)
    assert status == "ok"
    assert index is not None and index > source.index[D[0]]
    assert bar is not None and bar.day == D[1]
