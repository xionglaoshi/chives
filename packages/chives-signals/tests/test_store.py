from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from chives_signals.models import Plan, Signal
from chives_signals.store import HubStore
from tests.support import NOW, at


def make_signal(**overrides) -> Signal:
    data = dict(
        id=None,
        ts=NOW,
        kind="risk",
        decide=False,
        severity="L2",
        status="new",
        object_type="stock",
        object_code="601099.SH",
        object_name="太平洋",
        title="太平洋 成交额突增",
        direction="bear",
        conclusion="结论",
        brief="简析",
        context=None,
        source={"label": "cn-watch", "alert_ids": [1], "analysis_id": None, "plan_id": None, "rule_id": "r"},
        merged_count=1,
        primary={"label": "查看详情", "action": "open"},
        detail_available=False,
        rule_id="r",
        dedupe_key="stock|601099.SH|r",
    )
    data.update(overrides)
    return Signal(**data)


def test_insert_and_get(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    row = store.get_signal(signal_id)
    assert row is not None
    assert row["object_code"] == "601099.SH"
    assert row["merged_count"] == 1
    assert row["decide"] is False


def test_get_missing(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    assert store.get_signal(999) is None


def test_merge_increments_and_appends(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.merge_signal(signal_id, alert_id=2, analysis_id=None, now=NOW)
    row = store.get_signal(signal_id)
    assert row["merged_count"] == 2
    assert row["source"]["alert_ids"] == [1, 2]


def test_merge_does_not_duplicate_alert_id(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.merge_signal(signal_id, alert_id=1, analysis_id=None, now=NOW)
    assert store.get_signal(signal_id)["source"]["alert_ids"] == [1]


def test_merge_missing_signal(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    assert store.merge_signal(999, alert_id=1, analysis_id=None, now=NOW) is None


def test_update_status_and_snooze(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    row = store.update_signal(signal_id, status="snoozed", snooze_until=at(11), now=NOW)
    assert row["status"] == "snoozed"
    assert row["snooze_until"] == at(11)


def test_clear_snooze(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.update_signal(signal_id, status="snoozed", snooze_until=at(11), now=NOW)
    row = store.update_signal(signal_id, status="new", clear_snooze=True, now=NOW)
    assert row["snooze_until"] is None


def test_restore_snoozed(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.update_signal(signal_id, status="snoozed", snooze_until=at(9), now=NOW)
    assert store.restore_snoozed(at(10)) == 1
    assert store.get_signal(signal_id)["status"] == "new"


def test_restore_not_due(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.update_signal(signal_id, status="snoozed", snooze_until=at(12), now=NOW)
    assert store.restore_snoozed(at(10)) == 0


def test_list_active_excludes_done(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    first = store.insert_signal(make_signal(), NOW)
    store.insert_signal(make_signal(status="done"), NOW)
    rows = store.list_signals(status="active")
    assert [row["id"] for row in rows] == [first]


def test_list_snoozed_and_done(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_signal(make_signal(status="snoozed"), NOW)
    store.insert_signal(make_signal(status="done"), NOW)
    assert len(store.list_signals(status="snoozed")) == 1
    assert len(store.list_signals(status="done")) == 1


def test_list_decide_true_and_false(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_signal(make_signal(kind="plan_entry", dedupe_key="a"), NOW)
    store.insert_signal(make_signal(kind="risk", dedupe_key="b"), NOW)
    store.insert_signal(make_signal(kind="sector", severity="L1", dedupe_key="c"), NOW)
    store.insert_signal(make_signal(kind="sector", severity="L2", dedupe_key="d"), NOW)
    true_ids = [row["kind"] for row in store.list_signals(status="all", decide=True)]
    false_ids = [row["kind"] for row in store.list_signals(status="all", decide=False)]
    assert true_ids == ["sector", "plan_entry"]
    assert false_ids == ["sector", "risk"]


def test_list_object_market(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_signal(make_signal(object_type="market", dedupe_key="a"), NOW)
    store.insert_signal(make_signal(object_type="index", dedupe_key="b"), NOW)
    store.insert_signal(make_signal(object_type="stock", dedupe_key="c"), NOW)
    rows = store.list_signals(status="all", object_type="market")
    assert {row["object_type"] for row in rows} == {"market", "index"}


def test_since_id(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    first = store.insert_signal(make_signal(), NOW)
    store.insert_signal(make_signal(dedupe_key="x"), NOW)
    rows = store.list_signals(status="all", since_id=first)
    assert len(rows) == 1


def test_counts(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.insert_signal(make_signal(), NOW)
    store.insert_signal(make_signal(status="snoozed", dedupe_key="b"), NOW)
    store.insert_signal(make_signal(status="done", dedupe_key="c"), NOW)
    counts = store.signal_counts()
    assert counts == {"signals": 3, "active": 1, "snoozed": 1, "done": 1, "decide": 0}


def test_merged_today(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    store.merge_signal(signal_id, alert_id=2, analysis_id=None, now=NOW)
    assert store.merged_today(NOW.replace(hour=0, minute=0, second=0)) == 1


def test_merged_today_resets_by_day(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(ts=at(10, day=3)), at(10, day=3))
    store.merge_signal(signal_id, alert_id=2, analysis_id=None, now=at(10, 1, day=3))
    store.merge_signal(signal_id, alert_id=3, analysis_id=None, now=at(10, 2, day=3))
    assert store.merged_today(at(0, day=3)) == 2
    assert store.merged_today(at(0, day=4)) == 0


def test_max_signal_id(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    assert store.max_signal_id() == 0
    signal_id = store.insert_signal(make_signal(), NOW)
    assert store.max_signal_id() == signal_id


def test_update_signal_content(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    row = store.update_signal_content(
        signal_id,
        kind="info",
        status="done",
        conclusion="误报",
        direction="neutral",
        analysis_id=1,
        detail_available=True,
        now=NOW,
    )
    assert row["kind"] == "info"
    assert row["status"] == "done"
    assert row["analysis_id"] == 1
    assert row["detail_available"] is True


def test_plan_roundtrip(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    plan = Plan(
        id=None,
        code="601099.SH",
        name="太平洋",
        kind="entry",
        status="active",
        condition={"type": "price_cross", "direction": "up", "level": 4.0},
        stop=3.5,
        rationale="突破",
        source={"analysis_id": None, "label": "user"},
        proposed_by="user",
        created_at=NOW,
        expires_at=at(15, day=11),
    )
    plan_id = store.insert_plan(plan, NOW)
    row = store.get_plan(plan_id)
    assert row["condition"]["level"] == 4.0
    assert row["status"] == "active"


def test_plan_update_triggered(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    plan = Plan(
        id=None,
        code="601099.SH",
        name="太平洋",
        kind="entry",
        status="active",
        condition={"type": "price_cross", "direction": "up", "level": 4.0},
        stop=None,
        rationale="",
        source={"analysis_id": None, "label": "user"},
        proposed_by="user",
        created_at=NOW,
        expires_at=at(15, day=11),
    )
    plan_id = store.insert_plan(plan, NOW)
    row = store.update_plan(
        plan_id, status="triggered", triggered_at=NOW, last_price=4.1, now=NOW
    )
    assert row["status"] == "triggered"
    assert row["triggered_at"] == NOW
    assert row["last_price"] == 4.1


def test_count_active_plans(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    plan = Plan(
        id=None,
        code="601099.SH",
        name="太平洋",
        kind="entry",
        status="active",
        condition={"type": "price_cross", "direction": "up", "level": 4.0},
        stop=None,
        rationale="",
        source={"analysis_id": None, "label": "user"},
        proposed_by="user",
        created_at=NOW,
        expires_at=at(15, day=11),
    )
    store.insert_plan(plan, NOW)
    assert store.count_active_plans() == 1


def test_snapshot_idempotent(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    day = date(2026, 11, 4)
    assert store.insert_snapshot(
        day=day,
        market_value_cny=1.0,
        total_assets_cny=2.0,
        pnl_cny=0.5,
        day_pnl_cny=0.1,
        quote_time=None,
        now=NOW,
    )
    assert not store.insert_snapshot(
        day=day,
        market_value_cny=9.0,
        total_assets_cny=9.0,
        pnl_cny=9.0,
        day_pnl_cny=9.0,
        quote_time=None,
        now=NOW,
    )
    assert store.get_snapshot(day)["market_value_cny"] == 1.0


def test_snapshot_order(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    for offset in (1, 2, 3):
        store.insert_snapshot(
            day=date(2026, 11, offset),
            market_value_cny=float(offset),
            total_assets_cny=float(offset),
            pnl_cny=0.0,
            day_pnl_cny=0.0,
            quote_time=None,
            now=NOW,
        )
    rows = store.list_snapshots(10)
    assert [row["day"] for row in rows] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert store.count_snapshots() == 3


def test_processed_alerts(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    assert not store.is_processed("cn_watch", 1)
    store.mark_processed("cn_watch", 1, status="signal", reason=None, signal_id=5, ts=NOW)
    assert store.is_processed("cn_watch", 1)
    assert store.max_alert_id("cn_watch") == 1
    assert store.processed_signal_id("cn_watch", 1) == 5


def test_processed_ignore_duplicate(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    store.mark_processed("cn_watch", 1, status="signal", reason=None, signal_id=5, ts=NOW)
    store.mark_processed("cn_watch", 1, status="signal", reason=None, signal_id=6, ts=NOW)
    assert store.processed_signal_id("cn_watch", 1) == 5


def test_kv(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    assert store.get_kv("x") is None
    store.set_kv("x", {"a": 1})
    assert store.get_kv("x") == {"a": 1}


def test_concurrent_writes(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")

    def write(index: int) -> int:
        return store.insert_signal(make_signal(dedupe_key=f"k{index}"), NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(write, range(40)))
    assert len(set(ids)) == 40
    assert len(store.list_signals(status="all", limit=100)) == 40


def test_find_merge_candidate(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    signal_id = store.insert_signal(make_signal(), NOW)
    found = store.find_merge_candidate("stock|601099.SH|r", NOW - timedelta(minutes=30))
    assert found is not None and found["id"] == signal_id
    assert store.find_merge_candidate("other", NOW - timedelta(minutes=30)) is None


def test_plan_list_filters(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    plan = Plan(
        id=None,
        code="601099.SH",
        name="太平洋",
        kind="entry",
        status="proposed",
        condition={"type": "price_cross", "direction": "up", "level": 4.0},
        stop=None,
        rationale="",
        source={"analysis_id": None, "label": "agent"},
        proposed_by="agent",
        created_at=NOW,
        expires_at=at(15, day=11),
    )
    store.insert_plan(plan, NOW)
    assert len(store.list_plans("proposed")) == 1
    assert store.list_plans("active") == []


def test_close_plan_proposals(tmp_path: Path) -> None:
    store = HubStore(tmp_path / "hub.db")
    source = {"label": "hub", "alert_ids": [], "analysis_id": None, "plan_id": 7, "rule_id": None}
    signal_id = store.insert_signal(
        make_signal(kind="plan_proposal", source=source, dedupe_key="plan|7"), NOW
    )
    assert store.close_plan_proposals(7, NOW) == 1
    assert store.get_signal(signal_id)["status"] == "done"
