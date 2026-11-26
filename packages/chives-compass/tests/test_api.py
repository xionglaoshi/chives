from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from chives_compass.server import make_server, start_server, stop_server
from tests.test_engine import OPEN, board_code, make_engine
from tests.support import CN_TZ


@pytest.fixture()
def api(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, engine
    finally:
        stop_server(httpd, thread)


def get_json(base, path, method="GET"):
    request = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get_content_type() == "application/json"
        return json.loads(response.read().decode("utf-8"))


def test_health_shape(api):
    base, _ = api
    payload = get_json(base, "/health")
    assert payload["ok"] is True
    assert set(payload["sources"]) == {
        "index", "breadth", "limit_pool", "industry", "movers", "flows",
        "themes", "pool_history", "breadth_series", "daily_spark"
    }
    assert payload["backfill"]["running"] is False
    assert payload["backfill"]["total"] == 0
    assert payload["sources"]["index"]["ok"] is True
    assert payload["sources"]["movers"]["ok"] is True
    assert payload["sources"]["flows"]["ok"] is True
    assert payload["sources"]["daily_spark"]["ok"] is True
    assert payload["rules"]["enabled"] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert payload["limits"]["alerts"]["max_per_hour"] == 10
    assert payload["trading_state"] == "open"


def test_overview_contract(api):
    base, _ = api
    payload = get_json(base, "/overview")
    assert payload["ok"] is True
    assert [row["code"] for row in payload["indexes"]] == [
        "000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000852.SH", "000688.SH"
    ]
    row = payload["indexes"][0]
    for key in ("code", "name", "price", "prev_close", "change_pct", "amount_yuan", "spark",
                "as_of", "fetched_at", "source", "stale"):
        assert key in row
    assert isinstance(row["spark"], list)
    assert isinstance(row["stale"], bool)
    breadth = payload["breadth"]
    for key in ("up", "down", "flat", "up_ratio", "limit_up", "limit_down", "broken",
                "seal_ratio", "max_streak", "amount_yuan", "as_of", "stale"):
        assert key in breadth
    assert payload["regime"]["label"] in {"risk_on", "neutral", "risk_off"}
    assert isinstance(payload["regime"]["reasons"], list)


def test_sectors_contract(api):
    base, _ = api
    payload = get_json(base, "/sectors?level=sw1")
    assert payload["ok"] is True
    assert payload["level"] == "sw1"
    assert payload["sort"] == "change_pct"
    assert len(payload["rows"]) == 31
    row = payload["rows"][0]
    for key in ("code", "name", "change_pct", "amount_yuan", "amount_share_ratio", "rel_300_pct",
                "up_count", "down_count", "limit_up_count", "member_count", "rank",
                "rank_change_30m", "rank_30m_ago", "leaders", "laggards", "as_of", "fetched_at",
                "source", "stale"):
        assert key in row
    assert row["rank"] == 1


def test_sectors_default_level(api):
    base, _ = api
    assert get_json(base, "/sectors")["level"] == "sw1"


def test_sectors_invalid_level(api):
    base, _ = api
    payload = get_json(base, "/sectors?level=sw2")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_level"


def test_sector_detail_contract(api):
    base, _ = api
    payload = get_json(base, f"/sectors/{board_code(10)}")
    assert payload["ok"] is True
    assert payload["code"] == board_code(10)
    assert isinstance(payload["trend"], list)
    assert set(payload["history"]) >= {"ret_5d_pct", "ret_20d_pct", "rank_5d", "rank_20d"}


def test_unknown_sector(api):
    base, _ = api
    payload = get_json(base, "/sectors/BK9999")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_sector"


def test_members_contract(api):
    base, _ = api
    payload = get_json(base, f"/sectors/{board_code(10)}/members")
    assert payload["ok"] is True
    assert payload["rows"] == []
    assert payload["reason"]


def test_alerts_contract_and_pagination(api):
    base, engine = api
    engine.store.insert_alert(
        ts=OPEN, rule_id="R1", object_type="index", object_code="000001.SH",
        object_name="上证指数", severity="L2", title="t", detail="d", payload={"objects": []},
    )
    payload = get_json(base, "/alerts?since_id=0&limit=50")
    assert payload["ok"] is True
    assert len(payload["alerts"]) == 1
    assert payload["next_id"] == 1
    alert = payload["alerts"][0]
    assert alert["status"] == "new"
    assert set(alert) >= {"id", "ts", "rule_id", "object", "severity", "title", "detail", "payload", "status"}
    assert alert["object"]["type"] == "index"
    assert get_json(base, "/alerts?since_id=1")["alerts"] == []


def test_alerts_invalid_param(api):
    base, _ = api
    payload = get_json(base, "/alerts?since_id=abc")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_param"


def test_rules_contract(api):
    base, _ = api
    payload = get_json(base, "/rules")
    assert payload["ok"] is True
    assert len(payload["rules"]) == 6
    rule = payload["rules"][0]
    assert set(rule) == {"id", "name", "enabled", "params", "confirm", "cooldown_minutes", "level"}


def test_unknown_path_404(api):
    base, _ = api
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get_json(base, "/nope")
    assert excinfo.value.code == 404
    body = json.loads(excinfo.value.read().decode("utf-8"))
    assert body["ok"] is False


def test_post_method_rejected(api):
    base, _ = api
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get_json(base, "/health", method="POST")
    assert excinfo.value.code == 405
    assert excinfo.value.headers["Allow"] == "GET"


def test_make_server_forces_loopback(tmp_path):
    engine = make_engine(tmp_path)
    httpd = make_server(engine, "0.0.0.0", 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


def test_upstream_error_does_not_500(tmp_path):
    from chives_compass.gateway import SourceError
    from chives_compass.server import start_server, stop_server
    from tests.test_engine import make_config
    from chives_compass.engine import Engine
    from chives_compass.store import AlertStore

    cfg = make_config(tmp_path)
    client = __import__("tests.support", fromlist=["FakeClient"]).FakeClient()

    def boom(path, params):
        raise SourceError("upstream_http", "down")

    client.add("eastmoney", "/api/qt/clist/get", boom)
    engine = Engine(
        cfg, clock=lambda: OPEN, client=client, store=AlertStore(cfg.runtime.db_path),
        member_min_interval=0.0,
    )
    engine.tick(OPEN)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        payload = get_json(base, "/sectors?level=industry")
        assert payload["ok"] is True
        assert payload["rows"] == []
        assert "down" in payload["reason"]
    finally:
        stop_server(httpd, thread)
