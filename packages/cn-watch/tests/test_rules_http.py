from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from cn_watch.config import load_config
from cn_watch.engine import Engine
from cn_watch.server import make_server, stop_server
from cn_watch.storage import FileStore
from support import BASE_CONFIG, StepClock, quote


class AlwaysSource:
    def fetch(self, codes, now):
        return {
            code: quote(code=code, name="南方精工", price=15.0, prev_close=15.0)
            for code in codes
        }


def start(engine: Engine):
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def request(port: int, path: str, *, method: str = "GET", payload=None, raw=None, actor=None):
    data = raw if raw is not None else (
        json.dumps(payload).encode("utf-8") if payload is not None else None
    )
    headers = {"Content-Type": "application/json"}
    if actor is not None:
        headers["X-Actor"] = actor
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def make(tmp_path: Path, *, extra=None):
    raw = json.loads(json.dumps(BASE_CONFIG))
    raw["watchlist"] = ["002553.SZ"]
    raw["limits"] = {"max_watchlist": 5, "max_rules": 30}
    for key, value in (extra or {}).items():
        raw[key] = value
    target = tmp_path / "watch.yaml"
    target.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    engine = Engine(
        load_config(target),
        AlwaysSource(),
        StepClock(),
        FileStore(tmp_path / "out"),
        config_path=target,
    )
    httpd, thread = start(engine)
    return target, engine, httpd, thread


def by_id(port: int) -> dict:
    status, body = request(port, "/rules")
    assert status == 200
    return {row["id"]: row for row in body["rules"]}


def test_rule_http_contract_and_config_file_unchanged(tmp_path: Path):
    cfg_path, engine, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    digest = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    try:
        rows = by_id(port)
        assert rows["pct_up_3"]["source"] == "config"
        assert rows["pct_up_3"]["disabled"] is False

        status, created = request(
            port,
            "/rules/upsert",
            method="POST",
            actor="agent",
            payload={"id": "r2", "type": "pct_change", "direction": "up", "threshold_pct": 2.0},
        )
        assert status == 200
        assert created["status"] == "created"
        assert created["source"] == "runtime"
        assert created["before"] is None
        assert created["after"]["id"] == "r2"
        assert by_id(port)["r2"]["source"] == "runtime"

        status, overridden = request(
            port,
            "/rules/upsert",
            method="POST",
            actor="agent",
            payload={
                "id": "pct_up_3",
                "type": "pct_change",
                "direction": "up",
                "threshold_pct": 1.5,
                "symbols": None,
            },
        )
        assert status == 200
        assert overridden["status"] == "override"
        assert overridden["before"]["threshold_pct"] == 3.0
        assert overridden["after"]["source"] == "override"
        assert by_id(port)["pct_up_3"]["threshold_pct"] == 1.5

        status, disabled = request(
            port, "/rules/remove", method="POST", actor="human", payload={"id": "pct_up_3"}
        )
        assert status == 200
        assert disabled["status"] == "disabled"
        assert disabled["after"]["disabled"] is True
        row = by_id(port)["pct_up_3"]
        assert row["source"] == "override" and row["disabled"] is True

        status, reverted = request(
            port, "/rules/revert", method="POST", payload={"id": "pct_up_3"}
        )
        assert status == 200
        assert reverted["status"] == "reverted"
        row = by_id(port)["pct_up_3"]
        assert row["source"] == "config"
        assert row["disabled"] is False
        assert row["threshold_pct"] == 3.0

        status, removed = request(
            port, "/rules/remove", method="POST", actor="human", payload={"id": "r2"}
        )
        assert status == 200
        assert removed["status"] == "removed"
        assert "r2" not in by_id(port)

        status, history = request(port, "/rules/history?limit=2")
        assert status == 200
        assert history["count"] == 2
        assert [row["action"] for row in history["history"]] == ["remove", "revert"]
        assert history["history"][0]["actor"] == "human"
        assert set(history["history"][0]) == {
            "ts",
            "action",
            "rule_id",
            "before",
            "after",
            "actor",
        }

        assert hashlib.sha256(cfg_path.read_bytes()).hexdigest() == digest
        assert (tmp_path / "out" / "rules.runtime.json").exists()
    finally:
        stop_server(httpd, thread)


def test_rule_http_validation_and_methods(tmp_path: Path):
    _, engine, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        before = json.dumps(by_id(port), sort_keys=True)

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 30},
        )
        assert status == 400 and body["code"] == "out_of_bounds"
        assert body["field"] == "threshold_pct"
        assert body["allowed"] == {"min": 0.1, "max": 25}

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "../etc", "type": "pct_change", "direction": "up", "threshold_pct": 1},
        )
        assert status == 400 and body["code"] == "invalid_id"

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r", "type": "magic", "threshold_pct": 1},
        )
        assert status == 400 and body["code"] == "invalid_rule"

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": []},
        )
        assert status == 400 and body["code"] == "invalid_rule"

        assert json.dumps(by_id(port), sort_keys=True) == before

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r_ok", "type": "pct_change", "direction": "up", "threshold_pct": 1, "symbols": None},
        )
        assert status == 200 and "r_ok" in by_id(port)

        status, body = request(port, "/rules/upsert")
        assert status == 405
        status, body = request(port, "/rules/history", method="POST", payload={})
        assert status == 405
        status, body = request(port, "/rules/upsert", method="PUT", payload={})
        assert status == 405

        status, body = request(port, "/rules/remove", method="POST", payload={})
        assert status == 400 and body["code"] == "invalid_id"
        status, body = request(port, "/rules/remove", method="POST", payload={"id": "missing"})
        assert status == 404 and body["code"] == "rule_not_found"
        status, body = request(port, "/rules/revert", method="POST", payload={"id": "missing"})
        assert status == 404 and body["code"] == "rule_not_found"

        status, body = request(port, "/rules/upsert", method="POST", raw=b"{bad json")
        assert status == 400
        status, body = request(port, "/rules/upsert", method="POST", raw=b"[]")
        assert status == 400
        status, body = request(port, "/rules/upsert", method="POST", raw=b"x" * 9000)
        assert status == 413
    finally:
        stop_server(httpd, thread)


def test_rule_http_max_rules_and_actor_sanitising(tmp_path: Path):
    _, engine, httpd, thread = make(tmp_path, extra={"limits": {"max_watchlist": 5, "max_rules": 2}})
    port = httpd.server_address[1]
    try:
        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r2", "type": "pct_change", "direction": "up", "threshold_pct": 1},
        )
        assert status == 200
        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            payload={"id": "r3", "type": "pct_change", "direction": "up", "threshold_pct": 1},
        )
        assert status == 409 and body["code"] == "rules_full"

        status, body = request(
            port,
            "/rules/upsert",
            method="POST",
            actor="  agent<script>" + "x" * 100,
            payload={"id": "r2", "type": "pct_change", "direction": "up", "threshold_pct": 2},
        )
        assert status == 200
        status, history = request(port, "/rules/history?limit=1")
        assert history["history"][0]["actor"] == ("agent" + "script" + "x" * 100)[:64]
    finally:
        stop_server(httpd, thread)
