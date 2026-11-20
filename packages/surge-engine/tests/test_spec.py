from __future__ import annotations

from decimal import Decimal

import pytest

from surge_engine.spec import (
    WindowBar,
    base_score,
    check_first_board,
    convergence_satisfied,
    drawdown_deduction,
    first_pool_sort_key,
    is_converged,
    limit_price,
    main_pool_sort_key,
    round_half_up,
    time_score,
    total_score,
    volume_score,
)


def _window(closes: list[float], *, f_index: int = 11, limit_days: set[int] | None = None) -> list[WindowBar]:
    limit_days = limit_days or set()
    start = f_index - len(closes)
    return [
        WindowBar(start + offset, close, close, start + offset in limit_days)
        for offset, close in enumerate(closes)
    ]


def test_time_score_samples() -> None:
    assert time_score(1) == pytest.approx(100.0)
    assert time_score(23) == pytest.approx(50.0)
    assert time_score(45) == pytest.approx(0.0)
    assert time_score(2) == pytest.approx(100 - 100 / 44)


def test_base_score_samples() -> None:
    cases = {
        0.10: 80,
        0.15: 100,
        0.25: 100,
        0.2501: 90,
        0.30: 90,
        0.3001: 80,
        0.75: 0,
        0.80: 0,
    }
    for gain, expected in cases.items():
        assert base_score(gain) == expected, gain


def test_drawdown_deduction_samples() -> None:
    assert drawdown_deduction(0.0299) == 0
    assert drawdown_deduction(0.03) == 10
    assert drawdown_deduction(0.0599) == 10
    assert drawdown_deduction(0.06) == 20
    assert drawdown_deduction(0.0) == 0
    assert drawdown_deduction(-0.01) == 0


def test_volume_score_samples() -> None:
    assert volume_score(0.99) == 0
    assert volume_score(1.0) == 50
    assert volume_score(1.49) == 50
    assert volume_score(1.5) == 100
    assert volume_score(None) == 0


def test_total_score_rounding_and_floor() -> None:
    assert total_score(100, 0, 50, 0) == 53  # 52.5 -> 53 (half up)
    assert total_score(100, 0, 50, 0, floor_active=True) == 60
    assert total_score(100, 100, 50, 0, floor_active=True) == 68
    assert round_half_up(0.5) == 1
    assert round_half_up(2.5) == 3
    assert round_half_up(52.5) == 53


def test_limit_price_samples() -> None:
    assert limit_price(9.99, Decimal("0.10")) == Decimal("10.99")
    assert limit_price(9.99, Decimal("0.05")) == Decimal("10.49")


def test_first_board_spec_sample() -> None:
    closes = [10, 10.5, 10.2, 9.9, 9.8, 10.1, 10.0, 9.95, 10.3, 10.4]
    result = check_first_board(f_day_index=11, today_limit_up=True, window=_window(closes))
    assert result.ok, result.reason
    assert result.M == 10.5
    assert result.m == 9.8
    assert result.G == 9.8
    assert result.drawdown == pytest.approx((10.5 - 9.8) / 10.5, abs=1e-9)


def test_first_board_drawdown_boundaries() -> None:
    def closes_for(drawdown: float) -> list[float]:
        low = 10 * (1 - drawdown)
        # max on the first day, low on day 9, day 10 slightly above the low so
        # the golden-pit condition (low not on F-1) still holds.
        return [10.0, 9.95, 9.9, 9.85, 9.8, 9.75, low + 0.05, low + 0.04, low, low + 0.01]

    for drawdown, expected in [(0.029, False), (0.03, True), (0.15, True), (0.151, False)]:
        result = check_first_board(f_day_index=11, today_limit_up=True, window=_window(closes_for(drawdown)))
        assert result.ok is expected, (drawdown, result)
        if result.ok:
            assert result.drawdown == pytest.approx(drawdown, abs=1e-9)


def test_first_board_excludes_prior_limit_up() -> None:
    closes = [10, 10.5, 10.2, 9.9, 9.8, 10.1, 10.0, 9.95, 10.3, 10.4]
    result = check_first_board(
        f_day_index=11, today_limit_up=True, window=_window(closes, limit_days={4})
    )
    assert not result.ok and result.reason == "limit_up_in_window"


def test_first_board_low_on_previous_day_excluded() -> None:
    closes = [10, 9.95, 9.9, 9.85, 9.8, 9.75, 9.72, 9.71, 9.73, 9.7]
    result = check_first_board(f_day_index=11, today_limit_up=True, window=_window(closes))
    assert not result.ok and result.reason == "low_on_last_day"


def test_first_board_max_on_previous_day_excluded() -> None:
    closes = [9.7, 9.72, 9.71, 9.7, 9.69, 9.72, 9.73, 9.75, 9.8, 10.0]
    result = check_first_board(f_day_index=11, today_limit_up=True, window=_window(closes))
    assert not result.ok and result.reason == "max_on_last_day"


def test_first_board_needs_six_valid_bars() -> None:
    closes = [10.0, 9.7, 9.71, 9.72, 9.73]
    result = check_first_board(f_day_index=11, today_limit_up=True, window=_window(closes))
    assert not result.ok and result.reason == "too_few_bars"


def test_first_board_requires_limit_up_and_no_active_round() -> None:
    closes = [10, 10.5, 10.2, 9.9, 9.8, 10.1, 10.0, 9.95, 10.3, 10.4]
    assert check_first_board(f_day_index=11, today_limit_up=False, window=_window(closes)).reason == "not_limit_up"
    assert (
        check_first_board(
            f_day_index=11, today_limit_up=True, window=_window(closes), has_active_round=True
        ).reason
        == "active_round"
    )


def test_convergence() -> None:
    assert is_converged(10.0, 10.1, 10.0)
    assert is_converged(10.4, 10.0, 10.0)  # exactly 4%
    assert not is_converged(10.41, 10.0, 10.0)
    assert not is_converged(None, 10.0, 10.0)
    assert convergence_satisfied([True, False, True])
    assert not convergence_satisfied([True, False, False])
    assert not convergence_satisfied([True, True])


def test_first_pool_sorting_rules() -> None:
    rows = [
        {"code": "B", "priority": "normal", "priority_date": None, "score": 70, "t_star": "2020-01-05", "vr": 1.2},
        {"code": "A", "priority": "normal", "priority_date": None, "score": 70, "t_star": "2020-01-05", "vr": 1.2},
        {"code": "C", "priority": "normal", "priority_date": None, "score": 70, "t_star": None, "vr": 2.0},
        {"code": "D", "priority": "p2", "priority_date": "2020-02-01", "score": 10, "t_star": "2020-01-10", "vr": 1.0},
        {"code": "E", "priority": "p1", "priority_date": "2020-02-01", "score": 10, "t_star": "2020-01-10", "vr": 1.5},
        {"code": "F", "priority": "p1", "priority_date": "2020-02-01", "score": 10, "t_star": "2020-01-10", "vr": 2.0},
        {"code": "G", "priority": "p1", "priority_date": "2020-01-20", "score": 10, "t_star": "2020-01-10", "vr": 0.5},
    ]
    ordered = sorted(rows, key=first_pool_sort_key)
    assert [row["code"] for row in ordered] == ["G", "F", "E", "D", "A", "B", "C"]


def test_main_pool_sorting_rules() -> None:
    rows = [
        {"code": "A", "score": 90, "entry_date": "2020-01-10"},
        {"code": "B", "score": 90, "entry_date": "2020-01-11"},
        {"code": "C", "score": 100, "entry_date": "2020-01-01"},
        {"code": "D", "score": 80, "entry_date": "2020-01-20"},
    ]
    ordered = sorted(rows, key=main_pool_sort_key)
    assert [row["code"] for row in ordered] == ["C", "B", "A", "D"]
