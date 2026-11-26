from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from chives_signals.engine import HubEngine
from chives_signals.models import Analysis
from tests.support import (
    NOW,
    FakeClock,
    FakePortfolio,
    FakeSources,
    SimpleQuote,
    at,
    cn_alert,
    make_config,
    market_alert,
)


def build(tmp_path: Path, *, clock=None, portfolio=None, sources=None):
    config = make_config(tmp_path)
    sources = sources or FakeSources()
    sources.state = {"quotes": {"601099.SH": {"price": 4.1, "prev_close": 4.0, "change_pct": 2.5, "name": "太平洋"}}}
    sources.quotes = {"601099.SH": SimpleQuote("601099.SH", "太平洋", 4.1, 4.0, 2.5),
                      "002553.SZ": SimpleQuote("002553.SZ", "南方精工", 15.5, 15.3, 1.3)}
    engine = HubEngine(
        config,
        clock=clock or FakeClock(NOW),
        sources=sources,
        portfolio=portfolio or FakePortfolio(),
    )
    return engine, sources, engine._clock


def plan_payload(**overrides):
    data = {
        "code": "601099",
        "kind": "entry",
        "condition": {"type": "price_cross", "direction": "up", "level": 4.0},
        "rationale": "突破跟进",
        "proposed_by": "user",
    }
    data.update(overrides)
    return data


def test_ingest_cn_once(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    engine.tick(force=True)
    assert len(engine.store.list_signals(status="all")) == 1


def test_restart_idempotent(tmp_path: Path) -> None:
    first, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    first.bootstrap()
    second = HubEngine(first.config, clock=FakeClock(NOW), sources=sources, portfolio=FakePortfolio())
    second.bootstrap()
    assert len(second.store.list_signals(status="all")) == 1


def test_merge_same_rule(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1), cn_alert(2, ts="2026-11-04T09:40:05+08:00")]
    engine.bootstrap()
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 1
    assert rows[0]["merged_count"] == 2


def test_no_merge_outside_window(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1), cn_alert(2, ts="2026-11-04T11:00:05+08:00")]
    engine.bootstrap()
    assert len(engine.store.list_signals(status="all")) == 2


def test_skipped_alert_merges_into_recent(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1), cn_alert(2)]
    sources.analysis_map = {
        2: Analysis(alert_id=2, status="skipped", reason="dry_run", file=None)
    }
    engine.bootstrap()
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 1
    assert rows[0]["merged_count"] == 2
    assert engine.store.is_processed("cn_watch", 2)


def test_skipped_alert_without_candidate_no_signal(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    sources.analysis_map = {1: Analysis(alert_id=1, status="skipped", reason="dry_run", file=None)}
    engine.bootstrap()
    assert engine.store.list_signals(status="all") == []


def _fold_once(engine, sources, alert_id: int = 2, ts: str = "2026-11-04T09:30:05+08:00") -> None:
    sources.cn = [cn_alert(alert_id, ts=ts)]
    sources.analysis_map = {
        alert_id: Analysis(alert_id=alert_id, status="done", file=f"analysis-{alert_id}.md",
                           markdown="**结论：这是误报。**\n\n正文。")
    }
    engine.bootstrap()


def test_folded_card_accumulates_skipped_alerts(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    _fold_once(engine, sources)
    sources.cn += [cn_alert(3), cn_alert(4)]
    sources.analysis_map.update({
        3: Analysis(alert_id=3, status="skipped", reason="cooldown", file=None),
        4: Analysis(alert_id=4, status="skipped", reason="dry_run", file=None),
    })
    engine.tick(force=True)
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "info" and row["status"] == "done"
    assert row["folded"] is True
    assert row["merged_count"] == 3
    assert row["source"]["alert_ids"] == [2, 3, 4]


def test_merged_today_counts_alerts_merged_into_existing_cards(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    _fold_once(engine, sources)
    assert engine.signals_payload(status="all")["merged_today"] == 0
    sources.cn += [cn_alert(3), cn_alert(4)]
    sources.analysis_map.update({
        3: Analysis(alert_id=3, status="skipped", reason="cooldown", file=None),
        4: Analysis(alert_id=4, status="skipped", reason="dry_run", file=None),
    })
    engine.tick(force=True)
    assert engine.signals_payload(status="all")["merged_today"] == 2


def test_user_ignored_folded_card_is_not_merged_or_revived(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    _fold_once(engine, sources)
    sources.cn.append(cn_alert(3))
    sources.analysis_map[3] = Analysis(alert_id=3, status="skipped", reason="cooldown", file=None)
    engine.tick(force=True)
    signal_id = engine.store.list_signals(status="all")[0]["id"]
    assert engine.store.get_signal(signal_id)["merged_count"] == 2

    engine.action_signal(signal_id, "ignore", None)
    handled = engine.store.get_signal(signal_id)
    assert handled["status"] == "done" and handled["ignored"] is True
    assert handled["folded"] is False

    sources.cn.append(cn_alert(4))
    sources.analysis_map[4] = Analysis(alert_id=4, status="skipped", reason="dry_run", file=None)
    engine.tick(force=True)
    kept = engine.store.get_signal(signal_id)
    assert kept["status"] == "done" and kept["ignored"] is True
    assert kept["merged_count"] == 2

    sources.cn.append(cn_alert(5))
    sources.analysis_map[5] = Analysis(alert_id=5, status="done", file="analysis-5.md",
                                       markdown="**结论：这也是误报。**\n\n正文。")
    engine.tick(force=True)
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 2
    assert engine.store.get_signal(signal_id)["merged_count"] == 2
    newer = [row for row in rows if row["id"] != signal_id][0]
    assert newer["status"] == "done" and newer["folded"] is True


def test_user_done_card_is_not_remerged(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    signal_id = engine.store.list_signals(status="all")[0]["id"]
    engine.action_signal(signal_id, "done", None)
    sources.cn.append(cn_alert(2))
    engine.tick(force=True)
    old = engine.store.get_signal(signal_id)
    assert old["status"] == "done" and old["merged_count"] == 1
    assert len(engine.store.list_signals(status="all")) == 2


def test_folded_card_is_not_accumulated_next_day(tmp_path: Path) -> None:
    engine, sources, clock = build(tmp_path, clock=FakeClock(at(10, day=3)))
    _fold_once(engine, sources, ts="2026-11-03T09:30:05+08:00")
    clock.set(at(9, 30, day=5))
    sources.cn.append(cn_alert(3, ts="2026-11-05T09:30:05+08:00"))
    sources.analysis_map[3] = Analysis(alert_id=3, status="skipped", reason="cooldown", file=None)
    engine.tick(force=True)
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 1
    assert rows[0]["merged_count"] == 1
    assert engine.signals_payload(status="all")["merged_today"] == 0


def test_market_alert_ingest(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.market = [market_alert(1, rule="R3")]
    engine.bootstrap()
    rows = engine.store.list_signals(status="all")
    assert len(rows) == 1
    assert rows[0]["kind"] == "sector"


def test_market_skipped_not_signal(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    alert = market_alert(1, rule="R3")
    alert["status"] = "skipped"
    sources.market = [alert]
    engine.bootstrap()
    assert engine.store.list_signals(status="all") == []


def test_late_analysis_upgrade(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    sources.analysis_map = {
        1: Analysis(alert_id=1, status="done", file="analysis-1.md",
                    markdown="**结论：偏空，量能异常。**\n\n- 跌破 VWAP")
    }
    engine.tick(force=True)
    row = engine.store.list_signals(status="all")[0]
    assert row["analysis_id"] == 1
    assert row["direction"] == "bear"
    assert row["detail_available"] is True
    assert "跌破 VWAP" in row["brief"]


def test_late_false_positive_downgrade(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    sources.analysis_map = {
        1: Analysis(alert_id=1, status="done", file="analysis-1.md",
                    markdown="**结论：这是误报。**\n\n正文。")
    }
    engine.tick(force=True)
    row = engine.store.list_signals(status="all")[0]
    assert row["kind"] == "info"
    assert row["status"] == "done"
    assert row["decide"] is False


def test_upstream_down_health_and_signals_kept(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    sources.fail_cn = True
    sources.fail_market = True
    engine.tick(force=True)
    health = engine.health_dict()
    assert health["sources"]["cn_watch"]["ok"] is False
    assert health["sources"]["market_watch"]["ok"] is False
    assert len(engine.store.list_signals(status="all")) == 1


def test_plan_trigger_entry(tmp_path: Path) -> None:
    engine, _, _ = build(tmp_path)
    plan = engine.create_plan(plan_payload())
    engine.tick(force=True)
    stored = engine.store.get_plan(plan["id"])
    assert stored["status"] == "triggered"
    rows = engine.store.list_signals(status="all")
    assert any(row["kind"] == "plan_entry" and row["source"]["plan_id"] == plan["id"] for row in rows)


def test_plan_trigger_tencent_fallback(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.state = {"quotes": {}}
    plan = engine.create_plan(plan_payload(code="002553", condition={"type": "price_cross", "direction": "up", "level": 15.0}))
    engine.tick(force=True)
    assert engine.store.get_plan(plan["id"])["status"] == "triggered"


def test_plan_no_trigger_when_price_missing(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.state = {"quotes": {}}
    sources.quotes = {}
    plan = engine.create_plan(plan_payload(code="002553", condition={"type": "price_cross", "direction": "up", "level": 15.0}))
    engine.tick(force=True)
    assert engine.store.get_plan(plan["id"])["status"] == "active"


def test_plan_trigger_once(tmp_path: Path) -> None:
    engine, _, _ = build(tmp_path)
    plan = engine.create_plan(plan_payload())
    engine.tick(force=True)
    engine.tick(force=True)
    rows = [row for row in engine.store.list_signals(status="all") if row["source"].get("plan_id") == plan["id"]]
    assert len(rows) == 1


def test_plan_extend_rearms(tmp_path: Path) -> None:
    engine, _, clock = build(tmp_path)
    plan = engine.create_plan(plan_payload())
    engine.tick(force=True)
    clock.set(at(11))
    engine.plan_action(plan["id"], {"action": "extend", "expires_at": "2026-11-11T15:00:00+08:00"})
    engine.tick(force=True)
    rows = [row for row in engine.store.list_signals(status="all") if row["source"].get("plan_id") == plan["id"]]
    assert len(rows) == 2


def test_plan_expiry_info(tmp_path: Path) -> None:
    engine, _, clock = build(tmp_path)
    plan = engine.create_plan(plan_payload(condition={"type": "price_cross", "direction": "up", "level": 99.0},
                                           expires_at="2026-11-04T10:05:00+08:00"))
    clock.set(at(10, 10))
    engine.tick(force=True)
    assert engine.store.get_plan(plan["id"])["status"] == "expired"
    rows = [row for row in engine.store.list_signals(status="all") if row["source"].get("plan_id") == plan["id"]]
    assert any(row["kind"] == "info" for row in rows)


def test_proposed_plan_expiry_no_info(tmp_path: Path) -> None:
    engine, _, clock = build(tmp_path)
    plan = engine.create_plan(plan_payload(proposed_by="agent", expires_at="2026-11-04T10:05:00+08:00"))
    clock.set(at(10, 10))
    engine.tick(force=True)
    assert engine.store.get_plan(plan["id"])["status"] == "expired"
    rows = [row for row in engine.store.list_signals(status="all") if row["source"].get("plan_id") == plan["id"]]
    assert all(row["kind"] != "info" for row in rows)


def test_snapshot_catch_up(tmp_path: Path) -> None:
    portfolio = FakePortfolio()
    portfolio.snapshot = {
        "market_value_cny": 1000.0, "total_assets_cny": 2000.0,
        "pnl_cny": 100.0, "day_pnl_cny": 50.0, "quote_time": "2026-11-04 15:00:00",
    }
    engine, _, _ = build(tmp_path, clock=FakeClock(at(15, 10)), portfolio=portfolio)
    engine.bootstrap()
    assert engine.store.get_snapshot(date(2026, 11, 4)) is not None


def test_no_snapshot_before_close(tmp_path: Path) -> None:
    engine, _, _ = build(tmp_path, clock=FakeClock(at(14, 0)))
    engine.bootstrap()
    assert engine.store.count_snapshots() == 0


def test_health_counts(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    engine.bootstrap()
    engine.create_plan(plan_payload())
    health = engine.health_dict()
    assert health["counts"]["signals"] >= 1
    assert health["counts"]["plans"] == 1
    assert health["counts"]["plans_active"] == 1


def test_run_stops_immediately(tmp_path: Path) -> None:
    engine, _, _ = build(tmp_path)
    event = threading.Event()
    event.set()
    engine.run(event)


def test_analysis_skipped_marks_processed(tmp_path: Path) -> None:
    engine, sources, _ = build(tmp_path)
    sources.cn = [cn_alert(1)]
    sources.analysis_map = {1: Analysis(alert_id=1, status="skipped", reason="cooldown", file=None)}
    engine.bootstrap()
    assert engine.store.is_processed("cn_watch", 1)
    assert engine.store.list_signals(status="all") == []
