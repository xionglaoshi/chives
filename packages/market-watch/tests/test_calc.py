from __future__ import annotations

from datetime import datetime

import pytest

from market_watch.calc import metrics
from market_watch.models import CN_TZ


def at(hour, minute=0, second=0):
    return datetime(2026, 11, 3, hour, minute, second, tzinfo=CN_TZ)


@pytest.mark.parametrize(
    "price,prev,expected",
    [
        (110, 100, 10.0),
        (90, 100, -10.0),
        (100, 100, 0.0),
        (None, 100, None),
        (110, None, None),
        (110, 0, None),
        (110, -5, None),
        (float("nan"), 100, None),
    ],
)
def test_pct_change(price, prev, expected):
    result = metrics.pct_change(price, prev)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_rel_300_is_arithmetic_difference():
    assert metrics.rel_300_pct(2.5, 0.5) == pytest.approx(2.0)
    assert metrics.rel_300_pct(None, 0.5) is None
    assert metrics.rel_300_pct(2.5, None) is None


def test_relative_strength_geometric():
    assert metrics.relative_strength_pct(10.0, 10.0) == pytest.approx(0.0)
    assert metrics.relative_strength_pct(21.0, 10.0) == pytest.approx(10.0)
    assert metrics.relative_strength_pct(10.0, -100.0) is None


def test_amount_share_ratio():
    assert metrics.amount_share_ratio(50, 1000) == pytest.approx(0.05)
    assert metrics.amount_share_ratio(None, 1000) is None
    assert metrics.amount_share_ratio(50, 0) is None
    assert metrics.amount_share_ratio(-1, 1000) is None


@pytest.mark.parametrize(
    "up,down,expected",
    [(60, 40, 0.6), (0, 10, 0.0), (10, 0, 1.0), (0, 0, None), (None, 10, None), (10, None, None)],
)
def test_up_ratio(up, down, expected):
    result = metrics.up_ratio(up, down)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_seal_ratio():
    assert metrics.seal_ratio(48, 34) == pytest.approx(48 / 82)
    assert metrics.seal_ratio(0, 0) is None
    assert metrics.seal_ratio(None, 3) is None
    assert metrics.seal_ratio(3, None) is None


@pytest.mark.parametrize(
    "hour,minute,expected",
    [(9, 0, 0), (9, 30, 0), (10, 0, 30), (11, 30, 120), (12, 0, 120), (13, 0, 120), (13, 30, 150), (14, 57, 237), (15, 0, 240), (16, 0, 240)],
)
def test_minutes_elapsed(hour, minute, expected):
    assert metrics.minutes_elapsed(at(hour, minute)) == pytest.approx(expected)


def test_time_fraction_floor_and_cap():
    assert metrics.time_fraction(at(9, 30)) == pytest.approx(1 / 240)
    assert metrics.time_fraction(at(15, 0)) == pytest.approx(1.0)
    assert metrics.time_fraction(at(12, 0)) == pytest.approx(0.5)


def test_volume_ratio():
    assert metrics.volume_ratio(100, 100, 0.5) == pytest.approx(2.0)
    assert metrics.volume_ratio(100, None, 0.5) is None
    assert metrics.volume_ratio(100, 0, 0.5) is None
    assert metrics.volume_ratio(None, 100, 0.5) is None
    assert metrics.volume_ratio(100, 100, 0) is None


def test_rank_desc_and_ties():
    ranks = metrics.rank_desc({"a": 2.0, "b": 3.0, "c": None, "d": 2.0})
    assert ranks == {"b": 1, "a": 2, "d": 3}
    assert metrics.rank_desc({}) == {}


def test_rank_change_sign():
    assert metrics.rank_change(3, 15) == 12
    assert metrics.rank_change(15, 3) == -12
    assert metrics.rank_change(None, 3) is None


def test_small_sector():
    assert metrics.small_sector(9) is True
    assert metrics.small_sector(10) is False
    assert metrics.small_sector(None) is False


@pytest.mark.parametrize(
    "code,expected",
    [("900936.SH", True), ("200002.SZ", True), ("600000.SH", False), ("000001.SZ", False)],
)
def test_is_b_share(code, expected):
    assert metrics.is_b_share(code) is expected


@pytest.mark.parametrize(
    "name,expected", [("N皇冠", True), ("C三态", True), ("贵州茅台", False), ("ST中珠", False)]
)
def test_is_new_stock(name, expected):
    assert metrics.is_new_stock(name) is expected


@pytest.mark.parametrize(
    "name,expected", [("ST中珠", True), ("*ST海核", True), ("贵州茅台", False)]
)
def test_is_st_stock(name, expected):
    assert metrics.is_st_stock(name) is expected


def test_limit_flags():
    assert metrics.is_limit_up(11.0, 11.0) is True
    assert metrics.is_limit_up(10.999, 11.0) is True
    assert metrics.is_limit_up(10.9, 11.0) is False
    assert metrics.is_limit_up(None, 11.0) is False
    assert metrics.is_limit_up(11.0, None) is False
    assert metrics.is_limit_down(9.0, 9.0) is True
    assert metrics.is_limit_down(9.1, 9.0) is False


def test_dedupe_boards():
    names = ["保险Ⅱ", "保险Ⅲ", "银行", "游戏Ⅱ", "游戏Ⅲ"]
    assert metrics.dedupe_boards(names) == ["保险Ⅱ", "银行", "游戏Ⅱ"]


def test_register_change():
    assert metrics.register_change("保险Ⅱ") is False
    assert metrics.register_change("保险Ⅲ") is False
    assert metrics.register_change("银行") is True


def test_downsample_keeps_endpoints_and_limit():
    from datetime import timedelta

    start = at(9, 30)
    points = [(start + timedelta(seconds=index), float(index)) for index in range(1000)]
    thinned = metrics.downsample(points, 120)
    assert len(thinned) == 120
    assert thinned[0] == points[0]
    assert thinned[-1] == points[-1]
    assert metrics.downsample(points[:10], 120) == points[:10]
    assert metrics.downsample(points, 1) == [points[-1]]


def test_regime_risk_off_wins():
    label, reasons = metrics.regime(0.7, [1.0, 1.0, 1.0], ["R1 触发"])
    assert label == "risk_off"
    assert reasons == ["R1 触发"]


def test_regime_risk_on():
    label, reasons = metrics.regime(0.61, [0.2, 0.3, 0.1], [])
    assert label == "risk_on"
    assert any("0.61" in reason for reason in reasons)


def test_regime_neutral_when_index_missing():
    label, _ = metrics.regime(0.8, [0.2, None, 0.1], [])
    assert label == "neutral"


def test_regime_neutral_when_index_down():
    label, _ = metrics.regime(0.8, [0.2, -0.1, 0.1], [])
    assert label == "neutral"


def test_regime_neutral_without_breadth():
    label, _ = metrics.regime(None, [0.2, 0.1, 0.1], [])
    assert label == "neutral"
