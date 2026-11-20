from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from cn_research_mcp import calc


def test_fnum_variants():
    assert calc.fnum(1) == 1.0
    assert calc.fnum("2.5") == 2.5
    assert calc.fnum(np.float64(3.5)) == 3.5
    for bad in (None, float("nan"), float("inf"), "abc", pd.NaT, True):
        assert calc.fnum(bad) is None


def test_fint_rounds():
    assert calc.fint(3.0) == 3
    assert calc.fint(float("nan")) is None


def test_ftext_strips_and_nulls():
    assert calc.ftext("  a ") == "a"
    assert calc.ftext("  ") is None
    assert calc.ftext(float("nan")) is None
    assert calc.ftext(None) is None


def test_fdate_forms():
    assert calc.fdate(date(2026, 1, 2)) == "2026-01-02"
    assert calc.fdate(pd.Timestamp("2026-01-02 10:00")) == "2026-01-02"
    assert calc.fdate("2026-01-02 00:00:00") == "2026-01-02"
    assert calc.fdate(pd.NaT) is None
    assert calc.fdate(None) is None


def test_percentile_rank_counts_less_or_equal():
    assert calc.percentile_rank([1, 2, 3, 4], 3) == 75.0
    assert calc.percentile_rank([1, 2, 3, 4], 4) == 100.0
    assert calc.percentile_rank([1, 2, 3, 4], 0.5) == 0.0
    assert calc.percentile_rank([5, 5, 5], 5) == 100.0


def test_percentile_rank_empty():
    with pytest.raises(ValueError):
        calc.percentile_rank([], 1)


def test_positive_samples_drops_nonpositive_and_none():
    kept, dropped = calc.positive_samples([1, -2, 0, None, 3])
    assert kept == [1, 3] and dropped == 2


def test_percentile_block_ok():
    values = [float(i) for i in range(1, 101)]
    block = calc.percentile_block(values, 50.0)
    assert block["pct"] == 50.0 and block["samples"] == 100 and "reason" not in block


def test_percentile_block_excludes_nonpositive():
    values = [-5.0] * 10 + [float(i) for i in range(1, 81)]
    block = calc.percentile_block(values, 40.0)
    assert block["excluded_nonpositive"] == 10 and block["samples"] == 80 and block["pct"] == 50.0


def test_percentile_block_insufficient_samples():
    block = calc.percentile_block([1.0] * 59, 1.0)
    assert block["pct"] is None and block["reason"] == "insufficient_samples"
    assert calc.percentile_block([1.0] * 60, 1.0)["pct"] == 100.0


def test_percentile_block_current_missing_or_nonpositive():
    assert calc.percentile_block([1.0] * 80, None)["reason"] == "current_value_missing"
    assert calc.percentile_block([1.0] * 80, -3.0)["reason"] == "current_value_nonpositive"


def _frame(dates):
    return pd.DataFrame({"_d": pd.to_datetime(dates), "v": range(len(dates))})


def test_last_per_week_takes_last_trading_day():
    frame = _frame(["2026-11-02", "2026-11-03", "2026-11-06", "2026-11-09", "2026-11-10"])
    out = calc.last_per_group(frame, "_d", "week")
    assert out["v"].tolist() == [2, 4]


def test_last_per_month():
    frame = _frame(["2026-09-29", "2026-09-30", "2026-10-15", "2026-10-30", "2026-11-13"])
    assert calc.last_per_group(frame, "_d", "month")["v"].tolist() == [1, 3, 4]


def test_last_per_group_rejects_unknown_freq():
    with pytest.raises(ValueError):
        calc.last_per_group(_frame(["2026-01-01"]), "_d", "day")


def test_cap_points_noop_when_small():
    frame = _frame([f"2026-01-{d:02d}" for d in range(1, 11)])
    out, step = calc.cap_points(frame, 160)
    assert len(out) == 10 and step == 1


def test_cap_points_keeps_last_and_limit():
    frame = pd.DataFrame({"_d": pd.date_range("2018-01-01", periods=416, freq="7D"), "v": range(416)})
    out, step = calc.cap_points(frame, 160)
    assert len(out) <= 160 and out["v"].iloc[-1] == 415 and step == math.ceil(416 / 160)
    assert set(out["v"]).issubset(set(range(416)))


def test_in_window_boundary_excludes_start():
    frame = _frame(["2023-11-13", "2023-11-14", "2026-11-13"])
    out = calc.in_window(frame, "_d", 3)
    assert out["v"].tolist() == [1, 2]
