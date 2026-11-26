from __future__ import annotations

from types import SimpleNamespace

import pytest

from chives_compass.calc import pools


def row(code, streak=1, seal="09:30:00", broken=0, amount=1e8, industry="行业A", **extra):
    item = {
        "code": code,
        "name": code,
        "streak": streak,
        "first_seal_time": seal,
        "broken_times": broken,
        "amount_yuan": amount,
        "industry": industry,
    }
    item.update(extra)
    return item


def test_sort_zt_by_streak_desc():
    rows = [row("a", 1), row("b", 3), row("c", 2)]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "zt")] == ["b", "c", "a"]


def test_sort_zt_ties_by_first_seal_asc():
    rows = [row("a", 2, "10:00:00"), row("b", 2, "09:31:00")]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "zt")] == ["b", "a"]


def test_sort_zt_final_tie_by_code():
    rows = [row("b", 2, "09:30:00"), row("a", 2, "09:30:00")]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "zt")] == ["a", "b"]


def test_sort_zt_missing_streak_last():
    rows = [row("a", None), row("b", 1)]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "zt")] == ["b", "a"]


def test_sort_zb_by_broken_desc():
    rows = [row("a", broken=1), row("b", broken=3), row("c", broken=2)]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "zb")] == ["b", "c", "a"]


def test_sort_dt_by_amount_desc():
    rows = [row("a", amount=1.0), row("b", amount=3.0), row("c", amount=2.0)]
    assert [item["code"] for item in pools.sort_pool_rows(rows, "dt")] == ["b", "c", "a"]


def test_sort_unknown_kind_raises():
    with pytest.raises(ValueError):
        pools.sort_pool_rows([row("a")], "xx")


def test_ladder_tiers_descending():
    rows = [row("a", 1), row("b", 2), row("c", 3), row("d", 3)]
    payload = pools.ladder_payload(rows)
    assert [tier["streak"] for tier in payload["tiers"]] == [3, 2, 1]
    assert payload["max_streak"] == 3


def test_ladder_first_board_only_count():
    payload = pools.ladder_payload([row("a", 1), row("b", 1)])
    tier = payload["tiers"][0]
    assert tier == {"streak": 1, "count": 2}
    assert payload["first_board_count"] == 2


def test_ladder_caps_rows_at_eight():
    rows = [row(f"c{index:02d}", 2) for index in range(10)]
    tier = pools.ladder_payload(rows)["tiers"][0]
    assert tier["count"] == 10
    assert len(tier["rows"]) == 8


def test_ladder_ignores_missing_streak():
    payload = pools.ladder_payload([row("a", None), row("b", 2)])
    assert payload["first_board_count"] == 0
    assert [tier["streak"] for tier in payload["tiers"]] == [2]


def test_ladder_empty():
    payload = pools.ladder_payload([])
    assert payload == {"max_streak": None, "tiers": [], "first_board_count": 0}


def test_seal_ratio_basic():
    assert pools.seal_ratio_pct(48, 34) == pytest.approx(58.54)


def test_seal_ratio_zero_denominator():
    assert pools.seal_ratio_pct(0, 0) is None


def test_seal_ratio_missing_side():
    assert pools.seal_ratio_pct(None, 3) is None
    assert pools.seal_ratio_pct(3, None) is None


def test_promotion_1to2():
    previous = [row("a", 1), row("b", 1), row("c", 1), row("d", 1)]
    today = [row("a", 2), row("b", 2), row("c", 1)]
    assert pools.promotion_pct(previous, today, "1to2") == pytest.approx(50.0)


def test_promotion_1to2_zero_denominator():
    assert pools.promotion_pct([row("a", 2)], [row("a", 3)], "1to2") is None


def test_promotion_2to3():
    previous = [row("a", 2), row("b", 2)]
    today = [row("a", 3), row("b", 2)]
    assert pools.promotion_pct(previous, today, "2to3") == pytest.approx(50.0)


def test_promotion_3up():
    previous = [row("a", 4), row("b", 3)]
    today = [row("a", 5), row("b", 3)]
    assert pools.promotion_pct(previous, today, "3up") == pytest.approx(50.0)


def test_promotion_3up_requires_increment():
    previous = [row("a", 5)]
    today = [row("a", 4)]
    assert pools.promotion_pct(previous, today, "3up") == pytest.approx(0.0)


def test_promotion_empty_previous():
    assert pools.promotion_pct([], [row("a", 2)], "1to2") is None


def test_promotion_unknown_rule():
    with pytest.raises(ValueError):
        pools.promotion_pct([row("a", 1)], [row("a", 2)], "9to10")


def test_by_industry_counts_both_pools():
    rows = pools.by_industry(
        [row("a", 1, industry="A"), row("b", 2, industry="A"), row("c", 1, industry="B")],
        [row("d", broken=1, industry="A")],
    )
    first = rows[0]
    assert first["industry"] == "A"
    assert (first["zt_count"], first["zb_count"], first["max_streak"]) == (2, 1, 2)


def test_by_industry_keeps_zb_only_row():
    rows = pools.by_industry([], [row("d", broken=1, industry="B")])
    assert rows[0]["zt_count"] == 0 and rows[0]["zb_count"] == 1


def test_by_industry_leaders_capped_and_ordered():
    rows = pools.by_industry(
        [row(code, streak, industry="A") for code, streak in
         (("a", 1), ("b", 3), ("c", 2), ("d", 4))],
        [],
    )
    leaders = rows[0]["leaders"]
    assert len(leaders) == 3
    assert [item["streak"] for item in leaders] == [4, 3, 2]


def test_by_industry_skips_blank_industry():
    assert pools.by_industry([row("a", 1, industry="")], []) == []


def test_filter_theme_rows_drops_yesterday_derivatives():
    rows = [{"name": "昨日涨停"}, {"name": "昨日连板"}, {"name": "人工智能"}]
    assert [item["name"] for item in pools.filter_theme_rows(rows)] == ["人工智能"]


def test_theme_rows_rank_and_limit():
    rows = [
        {"code": "BK0001", "name": "A", "change_pct": 3.0, "amount_yuan": 1.0,
         "up": 10, "down": 2},
        {"code": "BK0002", "name": "B", "change_pct": 2.0, "amount_yuan": 2.0,
         "up": 8, "down": 4},
    ]
    result = pools.theme_rows(rows, 1)
    assert len(result) == 1
    assert result[0]["rank"] == 1 and result[0]["code"] == "BK0001"


def test_theme_rows_leader_code_normalised():
    rows = [{"code": "BK0001", "name": "A", "leader_code": "600000",
             "leader_name": "浦发银行", "leader_change_pct": 5.0}]
    leader = pools.theme_rows(rows, 5)[0]["leader"]
    assert leader["code"] == "600000.SH"
    assert leader["name"] == "浦发银行"


def test_theme_rows_without_leader_is_null():
    rows = [{"code": "BK0001", "name": "A"}]
    assert pools.theme_rows(rows, 5)[0]["leader"] is None


def test_yesterday_payload_basic():
    quote = SimpleNamespace(open=11.0, high=11.5, low=10.2, price=10.8, prev_close=10.0)
    payload = pools.yesterday_payload([row("a", 2)], {"a": quote})
    item = payload["rows"][0]
    assert item["open_pct"] == pytest.approx(10.0)
    assert item["high_pct"] == pytest.approx(15.0)
    assert item["low_pct"] == pytest.approx(2.0)
    assert item["now_pct"] == pytest.approx(8.0)
    assert item["prev_streak"] == 2


def test_yesterday_payload_averages_and_win_ratio():
    quotes = {
        "a": SimpleNamespace(open=10.0, high=10.0, low=9.5, price=10.2, prev_close=10.0),
        "b": SimpleNamespace(open=10.0, high=10.0, low=9.0, price=9.8, prev_close=10.0),
    }
    payload = pools.yesterday_payload([row("a"), row("b")], quotes)
    assert payload["avg_open_pct"] == pytest.approx(0.0)
    assert payload["avg_close_pct"] == pytest.approx(0.0)
    assert payload["win_ratio_pct"] == pytest.approx(50.0)


def test_yesterday_payload_missing_quote_omitted():
    payload = pools.yesterday_payload([row("a")], {})
    assert payload["rows"] == []
    assert payload["avg_open_pct"] is None


def test_yesterday_payload_bad_prev_close():
    quote = SimpleNamespace(open=1.0, high=1.0, low=1.0, price=1.0, prev_close=0.0)
    item = pools.yesterday_payload([row("a")], {"a": quote})["rows"][0]
    assert item["open_pct"] is None and item["now_pct"] is None


def test_yesterday_payload_empty_previous():
    payload = pools.yesterday_payload([], {})
    assert payload["rows"] == [] and payload["win_ratio_pct"] is None
