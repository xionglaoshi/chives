from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

import pytest

from market_watch.models import CN_TZ
from market_watch.store import AlertStore, StoredMember

NOW = datetime(2026, 11, 3, 10, 30, tzinfo=CN_TZ)


def test_insert_and_list_alert(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    alert_id = store.insert_alert(
        ts=NOW,
        rule_id="R1",
        object_type="index",
        object_code="000001.SH",
        object_name="上证指数",
        severity="L2",
        title="指数放量下跌",
        detail="详情",
        payload={"count": 1, "objects": [{"code": "000001.SH"}], "名称": "中文"},
    )
    assert alert_id > 0
    rows = store.list_alerts(0, 50)
    assert len(rows) == 1
    assert rows[0]["id"] == alert_id
    assert rows[0]["status"] == "new"
    assert rows[0]["object"] == {"type": "index", "code": "000001.SH", "name": "上证指数"}
    assert rows[0]["payload"]["名称"] == "中文"


def test_list_alerts_since_and_limit(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    for index in range(3):
        store.insert_alert(
            ts=NOW + timedelta(seconds=index),
            rule_id="R2",
            object_type="index",
            object_code="000300.SH",
            object_name="市场宽度",
            severity="L2",
            title=f"t{index}",
            detail="d",
            payload={},
        )
    rows = store.list_alerts(1, 1)
    assert len(rows) == 1 and rows[0]["id"] == 2
    assert store.last_alert_id() == 3


def test_count_alerts_since(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.insert_alert(ts=NOW - timedelta(hours=2), rule_id="R1", object_type="index",
                       object_code="a", object_name="a", severity="L1", title="t", detail="d", payload={})
    store.insert_alert(ts=NOW - timedelta(minutes=5), rule_id="R1", object_type="index",
                       object_code="b", object_name="b", severity="L1", title="t", detail="d", payload={})
    assert store.count_alerts_since(NOW - timedelta(hours=1)) == 1


def test_daily_amount_upsert_and_mean(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.record_daily_amount("idx:000001.SH", date(2026, 10, 30), 100.0)
    store.record_daily_amount("idx:000001.SH", date(2026, 10, 30), 120.0)
    store.record_daily_amount("idx:000001.SH", date(2026, 11, 2), 80.0)
    store.record_daily_amount("idx:000001.SH", date(2026, 11, 3), 999.0)
    mean, count = store.mean_daily_amount("idx:000001.SH", date(2026, 11, 3), 5)
    assert count == 2
    assert mean == pytest.approx(100.0)


def test_daily_amount_limit_five(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    for day in range(1, 11):
        store.record_daily_amount("k", date(2026, 10, day), float(day))
    mean, count = store.mean_daily_amount("k", date(2026, 11, 3), 5)
    assert count == 5
    assert mean == pytest.approx((6 + 7 + 8 + 9 + 10) / 5)


def test_daily_amount_missing(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    assert store.mean_daily_amount("nope", date(2026, 11, 3)) == (None, 0)


def test_members_roundtrip_and_freshness(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    members = [StoredMember("000505", "京粮控股", 0.29), StoredMember("000592", "平潭发展", 1.85)]
    store.save_members("801010", members, NOW)
    loaded = store.load_members("801010", NOW + timedelta(hours=1))
    assert loaded is not None and len(loaded) == 2
    assert loaded[0].weight_pct == pytest.approx(1.85)
    assert store.load_members("801010", NOW + timedelta(hours=30)) is None
    assert store.member_sector_map(NOW) == {"000505": "801010", "000592": "801010"}


def test_members_replace_on_save(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.save_members("801010", [StoredMember("000505", "a", 1.0)], NOW)
    store.save_members("801010", [StoredMember("000592", "b", 2.0)], NOW)
    loaded = store.load_members("801010", NOW)
    assert [member.code for member in loaded] == ["000592"]


def test_kv_roundtrip(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    store.set_kv("x", {"a": [1, 2]})
    assert store.get_kv("x") == {"a": [1, 2]}
    assert store.get_kv("missing") is None


def test_concurrent_reads_and_writes(tmp_path):
    store = AlertStore(tmp_path / "m.db")
    errors: list[BaseException] = []

    def writer(offset: int):
        try:
            for index in range(15):
                store.insert_alert(
                    ts=NOW + timedelta(seconds=offset * 100 + index),
                    rule_id="R3",
                    object_type="sector",
                    object_code=f"8010{offset:02d}",
                    object_name="sector",
                    severity="L1",
                    title="t",
                    detail="d",
                    payload={"i": index},
                )
        except BaseException as exc:  # pragma: no cover - diagnostic
            errors.append(exc)

    def reader():
        try:
            for _ in range(30):
                store.list_alerts(0, 100)
                store.count_alerts_since(NOW - timedelta(hours=1))
        except BaseException as exc:  # pragma: no cover - diagnostic
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(store.list_alerts(0, 100)) == 45
