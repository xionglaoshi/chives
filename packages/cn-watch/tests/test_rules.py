from __future__ import annotations

from datetime import timedelta

import pytest

from cn_watch.config import parse_config
from cn_watch.rules import compute_metrics, hot_distance, retreated, trigger, window_amounts
from support import BASE_CONFIG, DAY0, config, quote, rule


def build(**fields):
    cfg = parse_config({**BASE_CONFIG, "rules": [fields]})
    return cfg.rules[0]


def pct_quote(change_pct: float, **kwargs):
    price = 15.0 * (1.0 + change_pct / 100.0)
    return quote(price=price, **kwargs)


# ------------------------------------------------------------------ metrics
def test_metrics_change_vwap_and_deviation():
    q = quote(price=15.4, prev_close=15.0, volume_lots=10000, amount_yuan=15_000_000.0)
    metrics = compute_metrics(q)
    assert metrics.change_pct == pytest.approx(2.6666666, abs=1e-6)
    assert metrics.vwap == pytest.approx(15.0)
    assert metrics.vwap_dev_pct == pytest.approx(2.6666666, abs=1e-6)


def test_metrics_skip_vwap_without_volume():
    metrics = compute_metrics(quote(volume_lots=0, amount_yuan=0.0))
    assert metrics.vwap is None
    assert metrics.vwap_dev_pct is None


# --------------------------------------------------------------- pct_change
@pytest.mark.parametrize(
    ("direction", "change", "fires"),
    [
        ("up", 3.0, True),
        ("up", 2.999, False),
        ("down", -3.0, True),
        ("down", -2.999, False),
        ("up", -5.0, False),
        ("down", 5.0, False),
    ],
)
def test_pct_change_boundaries(direction, change, fires):
    spec = build(id="r", type="pct_change", direction=direction, threshold_pct=3.0)
    q = pct_quote(change)
    result = trigger(spec, q, compute_metrics(q), None, [], DAY0)
    assert (result is not None) is fires
    if fires:
        assert result[0] == direction


# ----------------------------------------------------------- vwap deviation
def test_vwap_gate_and_direction():
    spec = build(
        id="v", type="vwap_deviation", threshold_pct=2.0, min_amount_yuan=20_000_000
    )
    q = quote(price=15.4, volume_lots=13333, amount_yuan=19_999_999.0)
    assert trigger(spec, q, compute_metrics(q), None, [], DAY0) is None
    q = quote(price=15.4, volume_lots=13333, amount_yuan=20_000_000.0)
    result = trigger(spec, q, compute_metrics(q), None, [], DAY0)
    assert result is not None and result[0] == "up"
    q = quote(price=14.6, volume_lots=13333, amount_yuan=20_000_000.0)
    result = trigger(spec, q, compute_metrics(q), None, [], DAY0)
    assert result is not None and result[0] == "down"


def test_vwap_exact_threshold_and_below():
    spec = build(id="v", type="vwap_deviation", threshold_pct=2.0, min_amount_yuan=0)
    at = quote(price=15.3, volume_lots=10000, amount_yuan=15_000_000.0)
    assert trigger(spec, at, compute_metrics(at), None, [], DAY0) is not None
    below = quote(price=15.29, volume_lots=10000, amount_yuan=15_000_000.0)
    assert trigger(spec, below, compute_metrics(below), None, [], DAY0) is None


# -------------------------------------------------------- limit proximity
def test_limit_proximity_boundaries():
    up = build(id="u", type="limit_proximity", side="up", within_pct=0.5)
    at = quote(price=16.4175, limit_up=16.5)
    assert trigger(up, at, compute_metrics(at), None, [], DAY0) is not None
    below = quote(price=16.41, limit_up=16.5)
    assert trigger(up, below, compute_metrics(below), None, [], DAY0) is None
    disabled = quote(price=16.5, limit_up=0)
    assert trigger(up, disabled, compute_metrics(disabled), None, [], DAY0) is None

    down = build(id="d", type="limit_proximity", side="down", within_pct=0.5)
    at = quote(price=13.5675, limit_down=13.5)
    result = trigger(down, at, compute_metrics(at), None, [], DAY0)
    assert result is not None and result[0] == "down"
    above = quote(price=13.57, limit_down=13.5)
    assert trigger(down, above, compute_metrics(above), None, [], DAY0) is None


# ------------------------------------------------------------ price cross
def test_price_cross_requires_previous_snapshot():
    up = build(id="c", type="price_cross", level=16.0, direction="up")
    q = quote(price=16.5)
    assert trigger(up, q, compute_metrics(q), None, [], DAY0) is None
    assert trigger(up, q, compute_metrics(q), 16.0, [], DAY0) is None
    assert trigger(up, q, compute_metrics(q), 15.99, [], DAY0) is not None

    down = build(id="cd", type="price_cross", level=16.0, direction="down")
    lower = quote(price=15.9)
    assert trigger(down, lower, compute_metrics(lower), 16.01, [], DAY0) is not None
    assert trigger(down, lower, compute_metrics(lower), 15.99, [], DAY0) is None


# ----------------------------------------------------------- volume surge
def history(prices_amounts):
    return [(DAY0 + timedelta(seconds=second), amount) for second, amount in prices_amounts]


def test_volume_surge_requires_two_windows():
    spec = build(
        id="s",
        type="volume_surge",
        window_seconds=60,
        multiple=3.0,
        min_window_amount_yuan=5_000_000,
    )
    samples = [(second, 100_000.0 * (second / 3)) for second in range(0, 61, 3)]
    now = DAY0 + timedelta(seconds=samples[-1][0])
    assert window_amounts(history(samples), now, 60) is None
    assert trigger(spec, quote(), compute_metrics(quote()), None, history(samples), now) is None


def test_volume_surge_triggers_on_acceleration_and_rearms():
    spec = build(
        id="s",
        type="volume_surge",
        window_seconds=60,
        multiple=3.0,
        min_window_amount_yuan=5_000_000,
    )
    samples = []
    for second in range(0, 181, 3):
        samples.append((second, 100_000.0 * (second / 3)))
    for second in range(183, 301, 3):
        samples.append((second, 6_000_000.0 + 400_000.0 * ((second - 180) / 3)))
    q = quote()
    metrics = compute_metrics(q)

    fired = []
    for second, amount in samples:
        now = DAY0 + timedelta(seconds=second)
        result = trigger(spec, q, metrics, None, history(samples[: samples.index((second, amount)) + 1]), now)
        if result is not None:
            fired.append(second)
    assert fired[0] == 222
    assert all(second >= 222 for second in fired)

    # A calm window after the burst satisfies the volume re-arm line.
    calm = samples + [(303, samples[-1][1] + 100_000.0)]
    now = DAY0 + timedelta(seconds=303)
    assert retreated(spec, q, metrics, None, history(calm), now, 0.5) is True


# ------------------------------------------------------------------ re-arm
def test_pct_rearm_lines():
    spec = build(id="r", type="pct_change", direction="up", threshold_pct=3.0)
    q = pct_quote(2.4)
    assert retreated(spec, q, compute_metrics(q), None, [], DAY0, 0.5) is True
    q = pct_quote(2.6)
    assert retreated(spec, q, compute_metrics(q), None, [], DAY0, 0.5) is False

    down = build(id="d", type="pct_change", direction="down", threshold_pct=3.0)
    q = pct_quote(-2.4)
    assert retreated(down, q, compute_metrics(q), None, [], DAY0, 0.5) is True
    q = pct_quote(-2.6)
    assert retreated(down, q, compute_metrics(q), None, [], DAY0, 0.5) is False


def test_limit_and_cross_rearm_lines():
    up = build(id="u", type="limit_proximity", side="up", within_pct=0.5)
    assert retreated(up, quote(price=16.335, limit_up=16.5), compute_metrics(quote()), None, [], DAY0, 0.5)
    assert not retreated(up, quote(price=16.34, limit_up=16.5), compute_metrics(quote()), None, [], DAY0, 0.5)

    cross = build(id="c", type="price_cross", level=16.0, direction="up")
    assert retreated(cross, quote(price=15.92), compute_metrics(quote()), None, [], DAY0, 0.5)
    assert not retreated(cross, quote(price=15.93), compute_metrics(quote()), None, [], DAY0, 0.5)


def test_vwap_rearm_line():
    spec = build(id="v", type="vwap_deviation", threshold_pct=2.0, min_amount_yuan=0)
    q = quote(price=15.15, volume_lots=10000, amount_yuan=15_000_000.0)
    assert retreated(spec, q, compute_metrics(q), None, [], DAY0, 0.5)
    q = quote(price=15.24, volume_lots=10000, amount_yuan=15_000_000.0)
    assert not retreated(spec, q, compute_metrics(q), None, [], DAY0, 0.5)


# ------------------------------------------------------------------- hot
def test_hot_distance_pct_and_cross():
    spec = build(id="r", type="pct_change", direction="up", threshold_pct=3.0)
    q = pct_quote(2.8)
    assert hot_distance(spec, q, compute_metrics(q), None) == pytest.approx(0.2)
    cross = build(id="c", type="price_cross", level=16.0, direction="up")
    assert hot_distance(cross, quote(price=15.98), compute_metrics(quote()), None) == pytest.approx(
        0.125
    )
    surge = build(
        id="s",
        type="volume_surge",
        window_seconds=60,
        multiple=3.0,
        min_window_amount_yuan=1,
    )
    assert hot_distance(surge, quote(), compute_metrics(quote()), None) is None


# ------------------------------------------------- surge: no false alarm at session opens
def _surge_spec():
    return build(id="s", type="volume_surge", window_seconds=60, multiple=3.0, min_window_amount_yuan=5_000_000)


def test_surge_never_fires_in_the_opening_minute():
    spec = _surge_spec()
    open_ = DAY0  # 09:30:00
    # pre-open sample with nothing traded, then a first print that is 6M within 5 seconds
    hist = [(open_ - timedelta(minutes=5), 0.0), (open_ + timedelta(seconds=5), 6_000_000.0)]
    now = open_ + timedelta(seconds=5)
    assert window_amounts(hist, now, 60) is None
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist, now) is None
    # still inside the first two windows (09:31:59): the earlier window began before the open
    now = open_ + timedelta(seconds=119)
    hist = [(open_ - timedelta(minutes=5), 0.0), (open_ + timedelta(seconds=60), 100_000.0), (now, 6_100_000.0)]
    assert window_amounts(hist, now, 60) is None
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist, now) is None


def test_surge_is_comparable_once_both_windows_are_inside_the_session():
    spec = _surge_spec()
    open_ = DAY0
    now = open_ + timedelta(seconds=120)  # 09:32:00 -> windows 09:30-09:31 and 09:31-09:32
    hist = [(open_, 0.0), (open_ + timedelta(seconds=60), 1_000_000.0), (now, 7_000_000.0)]
    assert window_amounts(hist, now, 60) == (6_000_000.0, 1_000_000.0)
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist, now) is not None


def test_surge_does_not_fire_right_after_the_lunch_break():
    spec = _surge_spec()
    afternoon = DAY0.replace(hour=13, minute=0, second=0)
    now = afternoon + timedelta(seconds=30)
    hist = [(DAY0.replace(hour=11, minute=29), 50_000_000.0), (afternoon + timedelta(seconds=5), 50_000_000.0), (now, 58_000_000.0)]
    assert window_amounts(hist, now, 60) is None
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist, now) is None
    later = afternoon + timedelta(seconds=120)
    hist2 = [(afternoon, 50_000_000.0), (afternoon + timedelta(seconds=60), 51_000_000.0), (later, 57_000_000.0)]
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist2, later) is not None


@pytest.mark.parametrize("hour,minute", [(9, 0), (9, 29), (11, 31), (12, 30), (15, 5), (16, 14)])
def test_surge_never_fires_outside_continuous_sessions(hour, minute):
    spec = _surge_spec()
    now = DAY0.replace(hour=hour, minute=minute, second=0)
    hist = [(now - timedelta(seconds=120), 0.0), (now - timedelta(seconds=60), 0.0), (now, 20_000_000.0)]
    assert window_amounts(hist, now, 60) is None
    assert trigger(spec, quote(), compute_metrics(quote()), None, hist, now) is None
