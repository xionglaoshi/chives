from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from cn_watch.engine import Engine
from cn_watch.server import make_server, stop_server
from support import MemoryStore, ScriptedSource, StepClock, config


def start(engine):
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def test_read_only_api_shapes_and_codes():
    alerts = [
        {"id": 1, "rule_id": "r1"},
        {"id": 2, "rule_id": "r2"},
        {"id": 3, "rule_id": "r3"},
    ]
    store = MemoryStore(alerts=alerts)
    cfg = config(
        rules=[
            {
                "id": "r1",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 3.0,
                "symbols": ["002553.SZ"],
            },
            {"id": "r2", "type": "pct_change", "direction": "down", "threshold_pct": 3.0},
        ]
    )
    engine = Engine(cfg, ScriptedSource([{}]), StepClock(), store)
    engine.poll()
    httpd, thread = start(engine)
    port = httpd.server_address[1]
    try:
        assert httpd.server_address[0] == "127.0.0.1"

        status, ctype, body = get(port, "/health")
        health = json.loads(body)
        assert status == 200
        assert ctype == "application/json; charset=utf-8"
        assert health["status"] in {"ok", "degraded", "down", "stale"}
        assert {"mode", "next_interval", "consecutive_failures", "last_poll_ts"} <= set(health)

        status, _, body = get(port, "/state")
        state = json.loads(body)
        assert status == 200 and "updated_at" in state and "rules" in state

        status, _, body = get(port, "/rules")
        rules = json.loads(body)
        assert status == 200 and len(rules["rules"]) == 2
        assert rules["rules"][0]["symbols"] == ["002553.SZ"]
        assert rules["rules"][1]["symbols"] is None

        status, _, body = get(port, "/alerts")
        listing = json.loads(body)
        assert status == 200 and [a["id"] for a in listing["alerts"]] == [1, 2, 3]

        status, _, body = get(port, "/alerts?after_id=1&limit=1")
        listing = json.loads(body)
        assert [a["id"] for a in listing["alerts"]] == [2]

        status, _, body = get(port, "/alerts?limit=99999")
        assert status == 200
        assert len(json.loads(body)["alerts"]) == 3

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            get(port, "/nope")
        assert excinfo.value.code == 404

        for method in ("POST", "PUT", "DELETE", "PATCH"):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/alerts", data=b"{}", method=method
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)
            assert excinfo.value.code == 405
    finally:
        stop_server(httpd, thread)


def test_localhost_config_still_binds_loopback():
    cfg = config(api={"host": "localhost", "port": 8865})
    engine = Engine(cfg, ScriptedSource([{}]), StepClock(), MemoryStore())
    httpd = make_server(engine, "localhost", 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()
