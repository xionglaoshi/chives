from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from market_watch.config import parse_config
from market_watch.models import Breadth, CN_TZ, IndexQuote, StockQuote
from market_watch.rules import MarketView, RuleEvaluator, SectorView

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=CN_TZ)


def base_rules():
    return parse_config({"calendar": {"source": "weekdays"}}).rules


def evaluator(only=None, **overrides):
    rules = []
    for rule in base_rules():
        if only is not None and rule.id != only:
            rule = replace(rule, enabled=False)
        if overrides:
            rule = replace(rule, **overrides)
        rules.append(rule)
    ev = RuleEvaluator(rules)
    ev.configure_cap(10)
    ev.configure_suppression(False, 15, 5)
    return ev


def index(code, change, name=None, amount=1_000_000_000.0):
    return IndexQuote(
        code=code,
        name=name or code,
        price=100 * (1 + change / 100),
        prev_close=100.0,
        open=100.0,
        high=101.0,
        low=99.0,
        change_pct=change,
        amount_yuan=amount,
        volume_lots=1000,
        exch_time=NOW,
    )


def stock(code, change, name="测试股", amount=10_000_000.0, limit_up=None, limit_down=None):
    return StockQuote(
        code=code,
        name=name,
        price=100 * (1 + change / 100),
        prev_close=100.0,
        change_pct=change,
        amount_yuan=amount,
        volume_lots=100,
        exch_time=NOW,
        limit_up=limit_up,
        limit_down=limit_down,
    )


def sector(code="801010", name="农林牧渔", change=2.0, up_ratio=0.7, members=20,
           rank=3, rank_30m=20, zt=6, zt_30m=1, amount=1_000_000_000.0, small=False):
    return SectorView(
        code=code,
        name=name,
        change_pct=change,
        amount_yuan=amount,
        up_ratio=up_ratio,
        member_count=members,
        rank=rank,
        rank_30m_ago=rank_30m,
        limit_up_count=zt,
        limit_up_30m_ago=zt_30m,
        rel_300_pct=change - 0.5,
        small=small,
    )


def breadth(up_ratio=0.2):
    return Breadth(
        up=int(up_ratio * 1000),
        down=1000 - int(up_ratio * 1000),
        flat=10,
        up_ratio=up_ratio,
        amount_yuan=1e12,
        as_of=NOW,
        fetched_at=NOW,
        source="test",
    )


def view(**overrides):
    defaults = dict(
        now=NOW,
        indexes={"000001.SH": index("000001.SH", -1.2), "000300.SH": index("000300.SH", -0.1)},
        index_volume_ratios={"000001.SH": 2.0, "000300.SH": 1.0},
        breadth=breadth(),
        breadth_up_ratio_30m_ago=0.25,
        sectors=[sector()],
        stocks={},
        stock_volume_ratios={},
        stock_change_30m_ago={},
        sector_change_30m_ago={"801010": 0.0},
        stock_sector={},
        watchlist=(),
    )
    defaults.update(overrides)
    return MarketView(**defaults)


# -- R1 -------------------------------------------------------------------
def test_rules_payload_shape():
    payload = evaluator().payload()
    assert [item["id"] for item in payload] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert payload[0]["params"]["change_pct_max"] == -1.0


def test_r1_no_trigger_without_baseline():
    ev = evaluator(only="R1")
    assert ev.evaluate(view(index_volume_ratios={"000001.SH": None})) == []


def test_r1_no_trigger_when_change_small():
    ev = evaluator(only="R1")
    assert ev.evaluate(view(indexes={"000001.SH": index("000001.SH", -0.5)})) == []


def test_r1_confirms_twice_then_fires():
    ev = evaluator(only="R1")
    assert ev.evaluate(view()) == []
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=3)))
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.rule_id == "R1"
    assert draft.object_code == "000001.SH"
    assert draft.severity == "L2"
    assert draft.payload["count"] == 1
    assert draft.payload["objects"][0]["metrics"]["volume_ratio"] == 2.0


def test_r1_aggregates_multiple_indexes():
    ev = evaluator(only="R1")
    indexes = {
        "000001.SH": index("000001.SH", -1.5),
        "399001.SZ": index("399001.SZ", -1.8),
    }
    vr = {"000001.SH": 2.0, "399001.SZ": 1.8}
    ev.evaluate(view(indexes=indexes, index_volume_ratios=vr))
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=3), indexes=indexes, index_volume_ratios=vr))
    assert len(drafts) == 1
    assert drafts[0].payload["count"] == 2
    assert "2 个对象" in drafts[0].title


def test_r1_cooldown_blocks_repeat():
    ev = evaluator(only="R1")
    ev.evaluate(view())
    ev.evaluate(view(now=NOW + timedelta(seconds=3)))
    assert ev.evaluate(view(now=NOW + timedelta(minutes=10))) == []


def test_r1_rearms_after_condition_clears_and_cooldown():
    ev = evaluator(only="R1")
    ev.evaluate(view())
    ev.evaluate(view(now=NOW + timedelta(seconds=3)))
    ev.evaluate(view(now=NOW + timedelta(minutes=5), indexes={"000001.SH": index("000001.SH", 0.2)}))
    drafts = []
    for minute in range(6, 70):
        drafts.extend(ev.evaluate(view(now=NOW + timedelta(minutes=minute))))
    assert len(drafts) == 1


# -- R2 -------------------------------------------------------------------
def test_r2_weak_breadth_needs_three_confirmations():
    ev = evaluator(only="R2")
    assert ev.evaluate(view(breadth=breadth(0.2))) == []
    assert ev.evaluate(view(now=NOW + timedelta(seconds=20), breadth=breadth(0.2))) == []
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=40), breadth=breadth(0.2)))
    assert len(drafts) == 1
    assert drafts[0].rule_id == "R2"
    assert drafts[0].object_name == "市场宽度"


def test_r2_no_trigger_when_index_falls_hard():
    ev = evaluator(only="R2")
    indexes = {"000300.SH": index("000300.SH", -1.5)}
    for offset in (0, 20, 40):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), indexes=indexes)) == []


def test_r2_drop_branch():
    ev = evaluator(only="R2")
    drafts = []
    for offset in (0, 20, 40):
        drafts = ev.evaluate(
            view(now=NOW + timedelta(seconds=offset), breadth=breadth(0.5), breadth_up_ratio_30m_ago=0.7)
        )
    assert len(drafts) == 1
    assert drafts[0].payload["objects"][0]["metrics"]["up_ratio_drop"] == pytest.approx(0.2)


def test_r2_no_breadth_no_candidate():
    ev = evaluator(only="R2")
    for offset in (0, 20, 40):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), breadth=None)) == []


# -- R3 -------------------------------------------------------------------
def test_r3_triggers_on_rank_jump():
    ev = evaluator(only="R3")
    assert ev.evaluate(view()) == []
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=3)))
    assert len(drafts) == 1
    assert drafts[0].object_code == "801010"


def test_r3_rejects_small_sector():
    ev = evaluator(only="R3")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(members=5, small=True)])) == []


def test_r3_rejects_low_amount():
    ev = evaluator(only="R3")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(amount=1e7)])) == []


def test_r3_rejects_narrow_breadth():
    ev = evaluator(only="R3")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(up_ratio=0.4)])) == []


def test_r3_rejects_insufficient_rank_jump():
    ev = evaluator(only="R3")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(rank=3, rank_30m=8)])) == []


# -- R4 -------------------------------------------------------------------
def test_r4_triggers_on_limit_up_surge():
    ev = evaluator(only="R4")
    ev.evaluate(view())
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=3)))
    assert len(drafts) == 1
    assert drafts[0].payload["objects"][0]["metrics"]["increase"] == 5


def test_r4_rejects_small_increase():
    ev = evaluator(only="R4")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(zt=3, zt_30m=1)])) == []


def test_r4_rejects_unknown_baseline():
    ev = evaluator(only="R4")
    for offset in (0, 3):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(zt_30m=None)])) == []


# -- R5 -------------------------------------------------------------------
def test_r5_crossing_confirms_on_next_tick():
    ev = evaluator(only="R5")
    up = view(sectors=[sector(change=0.5)], indexes={"000300.SH": index("000300.SH", 0.0)})
    down = view(sectors=[sector(change=-2.0)], indexes={"000300.SH": index("000300.SH", 0.0)})
    assert ev.evaluate(up) == []
    drafts = ev.evaluate(down)
    assert len(drafts) == 1
    assert drafts[0].payload["objects"][0]["metrics"]["direction"] == "下穿"


def test_r5_requires_same_direction_as_sector_move():
    ev = evaluator(only="R5")
    first = view(sectors=[sector(change=0.5)], indexes={"000300.SH": index("000300.SH", 0.0)})
    ev.evaluate(first)
    irrelevant = view(
        sectors=[sector(change=-0.1)],
        indexes={"000300.SH": index("000300.SH", -1.0)},
    )
    for offset in (3, 6):
        assert ev.evaluate(view(now=NOW + timedelta(seconds=offset), **{key: getattr(irrelevant, key) for key in ("sectors", "indexes")})) == []


def test_r5_buffer_band_no_crossing():
    ev = evaluator(only="R5")
    ev.evaluate(view(sectors=[sector(change=0.1)], indexes={"000300.SH": index("000300.SH", 0.0)}))
    for offset in (3, 6):
        drafts = ev.evaluate(view(now=NOW + timedelta(seconds=offset), sectors=[sector(change=0.2)], indexes={"000300.SH": index("000300.SH", 0.0)}))
        assert drafts == []


# -- R6 -------------------------------------------------------------------
def test_r6_stock_sector_divergence():
    ev = evaluator(only="R6")
    market = view(
        sectors=[sector(change=1.0)],
        stocks={"002553.SZ": stock("002553.SZ", -5.0)},
        stock_volume_ratios={"002553.SZ": 2.5},
        stock_change_30m_ago={"002553.SZ": 0.0},
        sector_change_30m_ago={"801010": 0.0},
        stock_sector={"002553.SZ": "801010"},
        watchlist=("002553.SZ",),
    )
    assert ev.evaluate(market) == []
    drafts = ev.evaluate(replace(market, now=NOW + timedelta(seconds=3)))
    assert len(drafts) == 1
    assert drafts[0].object_code == "002553.SZ"
    assert drafts[0].payload["objects"][0]["metrics"]["divergence_pct"] == pytest.approx(-6.0)


def test_r6_skips_without_mapping():
    ev = evaluator(only="R6")
    market = view(
        stocks={"002553.SZ": stock("002553.SZ", -5.0)},
        stock_volume_ratios={"002553.SZ": 5.0},
        stock_change_30m_ago={"002553.SZ": 0.0},
        stock_sector={},
        watchlist=("002553.SZ",),
    )
    for offset in (0, 3):
        assert ev.evaluate(replace(market, now=NOW + timedelta(seconds=offset))) == []


def test_r6_skips_limit_up_stock():
    ev = evaluator(only="R6")
    market = view(
        sectors=[sector(change=1.0)],
        stocks={"002553.SZ": stock("002553.SZ", 10.0, limit_up=110.0)},
        stock_volume_ratios={"002553.SZ": 5.0},
        stock_change_30m_ago={"002553.SZ": 0.0},
        stock_sector={"002553.SZ": "801010"},
        watchlist=("002553.SZ",),
    )
    for offset in (0, 3):
        assert ev.evaluate(replace(market, now=NOW + timedelta(seconds=offset))) == []


def test_r6_requires_volume_spike():
    ev = evaluator(only="R6")
    market = view(
        sectors=[sector(change=1.0)],
        stocks={"002553.SZ": stock("002553.SZ", -5.0)},
        stock_volume_ratios={"002553.SZ": 1.0},
        stock_change_30m_ago={"002553.SZ": 0.0},
        stock_sector={"002553.SZ": "801010"},
        watchlist=("002553.SZ",),
    )
    for offset in (0, 3):
        assert ev.evaluate(replace(market, now=NOW + timedelta(seconds=offset))) == []


# -- suppression / storm / config ----------------------------------------
def test_suppression_window_records_but_does_not_emit():
    ev = evaluator(only="R1")
    ev.configure_suppression(True, 15, 5)
    early = datetime(2026, 11, 3, 9, 35, tzinfo=CN_TZ)
    ev.evaluate(replace(view(), now=early))
    assert ev.evaluate(replace(view(now=early + timedelta(seconds=3)), now=early + timedelta(seconds=3))) == []
    assert ev.suppressed_counts()["R1"] == 1
    assert ev.suppressed_total == 1


def test_suppression_disabled_allows_alert():
    ev = evaluator(only="R1")
    ev.configure_suppression(False, 15, 5)
    early = datetime(2026, 11, 3, 9, 35, tzinfo=CN_TZ)
    ev.evaluate(replace(view(), now=early))
    drafts = ev.evaluate(replace(view(), now=early + timedelta(seconds=3)))
    assert len(drafts) == 1


def test_storm_cap_limits_alerts_per_hour():
    ev = evaluator(only="R1")
    ev.configure_cap(1)
    indexes = {
        "000001.SH": index("000001.SH", -1.5),
        "399001.SZ": index("399001.SZ", -1.8),
    }
    vr = {"000001.SH": 2.0, "399001.SZ": 1.8}
    ev.evaluate(view(indexes=indexes, index_volume_ratios=vr))
    drafts = ev.evaluate(view(now=NOW + timedelta(seconds=3), indexes=indexes, index_volume_ratios=vr))
    assert len(drafts) == 1
    assert drafts[0].payload["count"] == 1
    assert ev.suppressed_total == 1


def test_recent_alert_count_consumes_budget():
    ev = evaluator(only="R1")
    ev.configure_cap(5)
    ev.evaluate(view())
    assert ev.evaluate(view(now=NOW + timedelta(seconds=3)), recent_alert_count=5) == []


def test_disabled_rule_not_evaluated():
    assert evaluator(only="R1").enabled_ids() == ["R1"]
    disabled = RuleEvaluator([replace(rule, enabled=False) for rule in base_rules()])
    disabled.configure_suppression(False, 15, 5)
    for offset in (0, 3, 6):
        assert disabled.evaluate(view(now=NOW + timedelta(seconds=offset))) == []


def test_update_config_keeps_state():
    ev = evaluator(only="R1")
    ev.evaluate(view())
    ev.update_config([replace(rule, confirm=5) for rule in base_rules()])
    assert ev.evaluate(view(now=NOW + timedelta(seconds=3))) == []


def test_conditions_flags_for_regime():
    ev = RuleEvaluator(base_rules())
    ev.configure_suppression(False, 15, 5)
    ev.evaluate(view())
    assert ev.conditions["R1"] is True
    assert ev.conditions["R2"] is True
