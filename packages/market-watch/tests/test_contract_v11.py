"""Contract v1.1: cold start, persistence and the gateway-backed sector block."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from market_watch.config import parse_config
from market_watch.engine import Engine
from market_watch.gateway import SourceError
from market_watch.models import CN_TZ
from market_watch.store import AlertStore
from tests.support import FakeClient, breadth_payload
from tests.test_engine import (
    OPEN,
    board_code,
    make_config,
    make_engine,
    make_feed,
)

CLOSED = datetime(2026, 11, 3, 20, 0, tzinfo=CN_TZ)


def boom(path, params):
    raise SourceError("upstream_http", "down")


def failing_client() -> FakeClient:
    client = FakeClient()
    client.add("tencent", "/q=", boom)
    client.add("eastmoney", "/", boom)
    client.add("eastmoney_ex", "/", boom)
    client.add("eastmoney_hist", "/", boom)
    return client


def shared_store(tmp_path) -> AlertStore:
    return AlertStore(tmp_path / "market.db")


def zt_payload(rows):
    return json.dumps({"data": {"tc": len(rows), "qdate": "20261103", "pool": rows}})


def test_default_config_uses_gateway_only():
    config = parse_config({})
    assert config.gateway.url == "http://127.0.0.1:8868"
    assert not hasattr(config, "sources")


def test_gateway_url_must_be_loopback():
    from market_watch.config import ConfigError
    import pytest

    with pytest.raises(ConfigError):
        parse_config({"gateway": {"url": "http://10.0.0.1:8868"}})
    with pytest.raises(ConfigError):
        parse_config({"gateway": {"url": "ftp://127.0.0.1:8868"}})
    with pytest.raises(ConfigError):
        parse_config({"gateway": {"unknown": 1}})


def test_closed_cold_start_empty_db_has_values(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: CLOSED))
    engine.tick(CLOSED)
    overview = engine.overview_dict()
    assert overview["trading_state"] == "closed"
    assert overview["state_note"] == "休市，显示上一交易时段最后值"
    assert all(row["price"] is not None for row in overview["indexes"])
    assert overview["breadth"]["up"] == 1800
    sectors = engine.sectors_dict()
    assert sectors["ok"] is True
    assert len(sectors["rows"]) == 31
    assert sectors["state_note"] == "休市，显示上一交易时段最后值"


def test_closed_second_tick_does_not_refetch(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: CLOSED))
    engine.tick(CLOSED)
    calls = len(engine.client.calls)
    engine.tick(CLOSED + timedelta(minutes=1))
    assert len(engine.client.calls) == calls


def test_restart_loads_snapshot_before_poll(tmp_path):
    cfg = make_config(tmp_path)
    first = make_engine(tmp_path, clock=(None, lambda: CLOSED))
    first.tick(CLOSED)
    first_close = first.sectors_dict()["rows"][0]["change_pct"]
    second = Engine(
        cfg,
        clock=lambda: CLOSED,
        client=failing_client(),
        store=shared_store(tmp_path),
        member_min_interval=0.0,
    )
    overview = second.overview_dict()
    assert all(row["price"] is not None for row in overview["indexes"])
    sectors = second.sectors_dict()
    assert len(sectors["rows"]) == 31
    assert sectors["rows"][0]["change_pct"] == first_close
    assert sectors["state_note"] == "休市，显示上一交易时段最后值"


def test_stale_true_when_upstream_down_open(tmp_path):
    cfg = make_config(tmp_path)
    first = make_engine(tmp_path, clock=(None, lambda: OPEN))
    first.tick(OPEN)
    second = Engine(
        cfg,
        clock=lambda: OPEN + timedelta(minutes=30),
        client=failing_client(),
        store=shared_store(tmp_path),
        member_min_interval=0.0,
    )
    second.tick(OPEN + timedelta(minutes=30))
    overview = second.overview_dict()
    assert overview["indexes"][0]["price"] is not None
    assert overview["indexes"][0]["stale"] is True
    sectors = second.sectors_dict()
    assert len(sectors["rows"]) == 31
    assert sectors["rows"][0]["stale"] is True
    assert sectors["rows"][0]["reason"]


def test_upstream_down_no_snapshot_null_reason(tmp_path):
    engine = make_engine(
        tmp_path, clock=(None, lambda: CLOSED), client=failing_client()
    )
    engine.tick(CLOSED)
    overview = engine.overview_dict()
    assert all(row["price"] is None for row in overview["indexes"])
    assert overview["indexes"][0]["reason"]
    assert overview["breadth"]["up"] is None
    assert overview["breadth"]["reason"]
    sectors = engine.sectors_dict()
    assert sectors["rows"] == []
    assert sectors["reason"]
    assert engine.health_dict()["sources"]["index"]["ok"] is False


def test_cold_start_each_source_independent(tmp_path):
    client = FakeClient()
    client.add("tencent", "/q=", make_feed())
    client.add("eastmoney", "/api/qt/ulist.np/get", breadth_payload((900, 1100, 50), (900, 1100, 50)))
    client.add("eastmoney", "/api/qt/clist/get", boom)
    client.add("eastmoney_ex", "/getTopicZTPool", zt_payload([]))
    client.add("eastmoney_ex", "/getTopicZBPool", zt_payload([]))
    client.add("eastmoney_ex", "/getTopicDTPool", zt_payload([]))
    engine = make_engine(tmp_path, clock=(None, lambda: CLOSED), client=client)
    engine.tick(CLOSED)
    overview = engine.overview_dict()
    assert all(row["price"] is not None for row in overview["indexes"])
    assert overview["breadth"]["up"] == 1800
    assert engine.sectors_dict()["rows"] == []
    assert "down" in engine.sectors_dict()["reason"]


def test_persist_blocks_table_roundtrip(tmp_path):
    store = AlertStore(tmp_path / "x.db")
    store.save_block(
        "demo",
        value={"a": [1, 2]},
        as_of=OPEN,
        fetched_at=OPEN,
        source="gateway.market_quote",
        reason=None,
        updated_at=OPEN,
    )
    loaded = store.load_blocks()["demo"]
    assert loaded["value"] == {"a": [1, 2]}
    assert loaded["source"] == "gateway.market_quote"
    assert loaded["fetched_at"] == OPEN.isoformat()


def test_block_persist_after_poll(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: OPEN))
    engine.tick(OPEN)
    blocks = engine.store.load_blocks()
    for key in ("index", "breadth", "pool", "boards"):
        assert key in blocks


def test_sector_row_units_and_fields(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: OPEN))
    engine.tick(OPEN)
    row = next(item for item in engine.sectors_dict()["rows"] if item["code"] == board_code(40))
    assert row["change_pct"] is not None
    assert row["rank"] == 1
    assert row["member_count"] == 20
    assert row["up_count"] is not None


def test_unknown_sector_detail(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: OPEN))
    engine.tick(OPEN)
    assert engine.sector_dict("BK9999")["ok"] is False


def test_health_reports_taxonomy_suppression(tmp_path):
    engine = make_engine(tmp_path, clock=(None, lambda: OPEN))
    engine.tick(OPEN)
    health = engine.health_dict()
    assert health["sector_universe"]["source"] == "gateway.market_sectors"
    assert health["rules"]["suppressed"]["R3"] == "sector_taxonomy_changed"


def test_board_list_failure_keeps_old_rows(tmp_path):
    cfg = make_config(tmp_path)
    first = make_engine(tmp_path, clock=(None, lambda: OPEN))
    first.tick(OPEN)
    second = Engine(
        cfg,
        clock=lambda: OPEN,
        client=failing_client(),
        store=shared_store(tmp_path),
        member_min_interval=0.0,
    )
    second.tick(OPEN)
    assert len(second.sectors_dict()["rows"]) == 31
    assert second.health_dict()["sources"]["industry"]["ok"] is False
