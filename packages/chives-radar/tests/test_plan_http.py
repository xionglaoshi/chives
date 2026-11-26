from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from chives_radar.engine import Engine
from chives_radar.server import make_server, stop_server
from chives_radar.storage import FileStore
from support import FakeMarket, ScriptedSource, StepClock, config, plan, quote

ALL = ["002553.SZ", "601099.SH"]


def quotes(now):
    return {
        code: quote(16.0, code=code, prev_close=15.0, exch=now)
        for code in ALL
    }


def start(engine):
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def request(port: int, path: str, *, method: str = "GET", payload=None, raw: bytes | None = None, headers=None):
    data = raw if raw is not None else (
        json.dumps(payload).encode("utf-8") if payload is not None else None
    )
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def make(tmp_path: Path, *, max_watchlist: int = 3, steps=None):
    cfg = config(limits={"max_watchlist": max_watchlist}, rules=[])
    engine = Engine(
        cfg,
        ScriptedSource(steps or [quotes]),
        StepClock(),
        FileStore(tmp_path / "out"),
        market_client=FakeMarket(),
    )
    httpd, thread = start(engine)
    return engine, httpd, thread


def test_upsert_list_get_and_remove(tmp_path):
    engine, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/upsert", method="POST", payload=plan(code="601099.SH", label="A"))
        assert status == 200
        assert body["ok"] is True
        assert body["plan"]["id"] == "plan-1"
        assert body["plan"]["state"] == "observe"

        status, listing = request(port, "/plans")
        assert status == 200
        assert listing["ok"] is True
        assert listing["as_of"].endswith("+08:00")
        assert set(listing["market_context"]) == {"ok", "age_s", "regime"}
        assert [item["id"] for item in listing["plans"]] == ["plan-1"]

        status, single = request(port, "/plans?id=plan-1")
        assert status == 200
        assert single["id"] == "plan-1"
        assert single["plan"]["id"] == "plan-1"

        status, removed = request(port, "/plans/remove", method="POST", payload={"id": "plan-1"})
        assert status == 200
        assert removed["status"] == "removed"
        assert engine.plans_payload()["plans"] == []
        assert [row["code"] for row in engine.watchlist_dict()["watchlist"]] == ["002553.SZ"]
    finally:
        stop_server(httpd, thread)


def test_get_missing_plan_is_404(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans?id=missing")
        assert status == 404
        assert body["ok"] is False
        assert body["code"] == "not_found"
    finally:
        stop_server(httpd, thread)


def test_remove_missing_plan_is_404(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/remove", method="POST", payload={"id": "missing"})
        assert status == 404
        assert body["code"] == "not_found"
    finally:
        stop_server(httpd, thread)


def test_remove_without_id_is_400(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/remove", method="POST", payload={})
        assert status == 400
        assert body["ok"] is False
        assert body["code"] == "invalid_plan"
        assert body["field"] == "id"
    finally:
        stop_server(httpd, thread)


def test_invalid_condition_returns_400_with_field(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(
            port,
            "/plans/upsert",
            method="POST",
            payload=plan(market=[{"type": "price_in_range", "lo": 2, "hi": 1}]),
        )
        assert status == 400
        assert body["ok"] is False
        assert body["code"] == "invalid_condition"
        assert body["field"] == "market[0].lo"
        assert "message" in body
    finally:
        stop_server(httpd, thread)


def test_invalid_symbol_returns_400(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/upsert", method="POST", payload=plan(code="920001"))
        assert status == 400
        assert body["code"] == "invalid_symbol"
        assert body["field"] == "code"
    finally:
        stop_server(httpd, thread)


def test_unknown_field_returns_400(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        payload = plan()
        payload["position_size"] = 100
        status, body = request(port, "/plans/upsert", method="POST", payload=payload)
        assert status == 400
        assert body["code"] == "invalid_plan"
        assert body["field"] == "plan.position_size"
    finally:
        stop_server(httpd, thread)


def test_too_many_conditions_returns_400(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        payload = plan(stock=[{"type": "regime", "values": ["strong"]}] * 7)
        status, body = request(port, "/plans/upsert", method="POST", payload=payload)
        assert status == 400
        assert body["code"] == "too_many_conditions"
        assert body["field"] == "stock"
    finally:
        stop_server(httpd, thread)


def test_watchlist_full_returns_400_and_no_side_effects(tmp_path):
    engine, httpd, thread = make(tmp_path, max_watchlist=1)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/upsert", method="POST", payload=plan(code="601099.SH"))
        assert status == 400
        assert body["ok"] is False
        assert body["code"] == "watchlist_full"
        assert engine.plans_payload()["plans"] == []
        assert [row["code"] for row in engine.watchlist_dict()["watchlist"]] == ["002553.SZ"]
    finally:
        stop_server(httpd, thread)


def test_nested_plan_wrapper_is_accepted(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/plans/upsert", method="POST", payload={"plan": plan()})
        assert status == 200
        assert body["plan"]["id"] == "plan-1"
    finally:
        stop_server(httpd, thread)


@pytest.mark.parametrize("path", ["/plans/upsert", "/plans/remove"])
def test_get_on_write_paths_is_405(tmp_path, path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, path)
        assert status == 405
        assert body["error"] == "method not allowed"
    finally:
        stop_server(httpd, thread)


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_other_methods_on_plans_are_405(tmp_path, method):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, _ = request(port, "/plans", method=method, payload={})
        assert status == 405
    finally:
        stop_server(httpd, thread)


def test_bad_json_and_non_object_bodies(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, _ = request(port, "/plans/upsert", method="POST", raw=b"{bad json")
        assert status == 400
        status, _ = request(port, "/plans/upsert", method="POST", raw=b"[]")
        assert status == 400
    finally:
        stop_server(httpd, thread)


def test_plan_transition_alert_is_visible_on_alerts(tmp_path):
    engine, httpd, thread = make(
        tmp_path,
        steps=[lambda now: {code: quote(16.0, code=code, prev_close=15.0, exch=now) for code in ALL}],
    )
    port = httpd.server_address[1]
    try:
        request(
            port,
            "/plans/upsert",
            method="POST",
            payload=plan(stock=[{"type": "price_cross", "direction": "up", "level": 16.0}]),
        )
        engine.poll()
        status, listing = request(port, "/alerts")
        assert status == 200
        plan_alerts = [item for item in listing["alerts"] if item["rule_type"] == "plan"]
        assert len(plan_alerts) == 1
        assert plan_alerts[0]["rule_id"] == "plan:plan-1"
        assert plan_alerts[0]["detail"]["to"] == "execute"

        status, after = request(port, f"/alerts?after_id={plan_alerts[0]['id']}")
        assert status == 200
        assert after["alerts"] == []
    finally:
        stop_server(httpd, thread)


def test_health_exposes_market_context(tmp_path):
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/health")
        assert status == 200
        assert set(body["market_context"]) == {"ok", "age_s", "regime"}
        assert "plan_count" in body
    finally:
        stop_server(httpd, thread)


def test_state_exposes_watchlist_source(tmp_path):
    engine, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        request(port, "/plans/upsert", method="POST", payload=plan(code="601099.SH"))
        status, body = request(port, "/state")
        assert status == 200
        rows = {row["code"]: row for row in body["watchlist"]}
        assert rows["601099.SH"]["source"] == "plan"
        assert body["plan_count"] == 1
    finally:
        stop_server(httpd, thread)


def test_plan_upsert_does_not_modify_config_file(tmp_path):
    target = tmp_path / "watch.yaml"
    target.write_text("watchlist: [002553.SZ]\n", encoding="utf-8")
    before = target.read_bytes()
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        request(port, "/plans/upsert", method="POST", payload=plan())
    finally:
        stop_server(httpd, thread)
    assert target.read_bytes() == before
