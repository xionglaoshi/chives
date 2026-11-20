from __future__ import annotations

from datetime import date

from cn_daily_store.limits import (
    is_st_name,
    limit_price_from,
    limit_ratio_for,
    round_half_up_to_cent,
)


def test_round_half_up_examples():
    assert float(round_half_up_to_cent("10.989")) == 10.99
    assert float(round_half_up_to_cent("10.485")) == 10.49
    assert float(round_half_up_to_cent("10.484")) == 10.48


def test_main_board_and_st_limits():
    ten = limit_ratio_for("sh_main", date(2021, 1, 4), False)
    st = limit_ratio_for("sh_main", date(2021, 1, 4), True)
    assert ten is not None and st is not None
    assert float(limit_price_from(9.99, ten)) == 10.99
    assert float(limit_price_from(9.99, st)) == 10.49


def test_chinext_switch_day():
    assert float(limit_ratio_for("chinext", date(2020, 8, 21), False)) == 0.10
    assert float(limit_ratio_for("chinext", date(2020, 8, 21), True)) == 0.05
    assert float(limit_ratio_for("chinext", date(2020, 8, 24), False)) == 0.20
    assert float(limit_ratio_for("chinext", date(2020, 8, 24), True)) == 0.20
    ratio = limit_ratio_for("chinext", date(2020, 8, 24), False)
    assert ratio is not None
    assert float(limit_price_from(9.99, ratio)) == 11.99


def test_star_and_unknown_board():
    assert float(limit_ratio_for("star", date(2021, 1, 4), False)) == 0.20
    assert float(limit_ratio_for("star", date(2021, 1, 4), True)) == 0.20
    assert limit_ratio_for("bse", date(2021, 1, 4), False) is None


def test_st_name_prefixes():
    for name in ("ST 天邦", "*ST 海核", "SST 前锋", "S*ST 长兴"):
        assert is_st_name(name) is True
    for name in ("贵州茅台", "柳工", "STAR", ""):
        assert is_st_name(name) is False
