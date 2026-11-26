from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from chives_radar.config import load_config
from chives_radar.engine import Engine
from chives_radar.server import make_server, stop_server
from chives_radar.storage import FileStore
from support import BASE_CONFIG, StepClock, quote

class AllSource:
    def fetch(self, codes, now):
        return {
            code: quote(code=code, name="南方精工", price=10.0, prev_close=10.0)
            for code in codes
        }


def start(engine: Engine):
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def request(port: int, path: str, *, method: str = "GET", payload=None, raw: bytes | None = None):
    data = raw if raw is not None else (
        json.dumps(payload).encode("utf-8") if payload is not None else None
    )
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def make(tmp_path: Path):
    cfg = load_config(tmp_path / "watch.yaml")
    engine = Engine(cfg, AllSource(), StepClock(), FileStore(tmp_path / "out"))
    httpd, thread = start(engine)
    return engine, httpd, thread


def write_config(tmp_path: Path, limit: int = 3) -> Path:
    raw = json.loads(json.dumps(BASE_CONFIG))
    raw["watchlist"] = ["002553.SZ"]
    raw["limits"] = {"max_watchlist": limit}
    target = tmp_path / "watch.yaml"
    target.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return target


def test_watchlist_http_contract(tmp_path: Path):
    cfg_path = write_config(tmp_path)
    digest_before = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    engine, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        status, body = request(port, "/watchlist")
        assert status == 200
        assert body["count"] == 1
        assert body["limit"] == 3
        assert body["watchlist"] == [{"code": "002553.SZ", "name": None, "source": "config"}]

        status, added = request(port, "/watchlist/add", method="POST", payload={"code": "601099"})
        assert status == 200
        assert added["ok"] is True
        assert added["status"] == "added"
        assert added["code"] == "601099.SH"
        assert added["source"] == "runtime"
        assert added["name"] == "南方精工"

        status, again = request(port, "/watchlist/add", method="POST", payload={"code": "601099.SH"})
        assert status == 200
        assert again["status"] == "already_present"

        status, body = request(port, "/watchlist")
        assert [row["code"] for row in body["watchlist"]] == ["002553.SZ", "601099.SH"]

        status, error = request(port, "/watchlist/add", method="POST", payload={"code": "600000.XX"})
        assert status == 400
        assert error["ok"] is False
        assert error["code"] == "invalid_symbol"

        status, error = request(port, "/watchlist/add", method="POST", payload={"code": "920001"})
        assert status == 400
        assert error["code"] == "unsupported_market"
        assert "北交所" in error["message"]

        request(port, "/watchlist/add", method="POST", payload={"code": "600000"})
        status, error = request(port, "/watchlist/add", method="POST", payload={"code": "000001"})
        assert status == 409
        assert error["code"] == "watchlist_full"

        status, error = request(port, "/watchlist/remove", method="POST", payload={"code": "002553"})
        assert status == 409
        assert error["code"] == "protected_symbol"

        status, removed = request(port, "/watchlist/remove", method="POST", payload={"code": "601099"})
        assert status == 200
        assert removed["status"] == "removed"
        assert removed["count"] == 2

        status, removed = request(port, "/watchlist/remove", method="POST", payload={"code": "601099"})
        assert status == 200
        assert removed["status"] == "not_present"

        assert engine.alerts()["alerts"] == []
    finally:
        stop_server(httpd, thread)
    assert hashlib.sha256(cfg_path.read_bytes()).hexdigest() == digest_before


def test_watchlist_http_validation_and_methods(tmp_path: Path):
    write_config(tmp_path)
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        for path in ("/watchlist/add", "/watchlist/remove"):
            status, body = request(port, path)
            assert status == 405 and body["error"] == "method not allowed"

            status, body = request(port, path, method="POST", payload={})
            assert status == 400

            status, body = request(port, path, method="POST", raw=b"{bad json")
            assert status == 400

            status, body = request(port, path, method="POST", payload={"code": "../etc/passwd"})
            assert status == 400 and body["code"] == "invalid_symbol"

        status, body = request(port, "/watchlist/add", method="POST", payload={"code": "399975"})
        assert status == 400
        assert body["code"] == "unsupported_instrument"
        assert "指数" in body["message"]

        status, body = request(port, "/alerts", method="POST", payload={"code": "601099"})
        assert status == 405

        status, body = request(port, "/nope", method="POST", payload={"code": "601099"})
        assert status == 404

        status, body = request(
            port, "/watchlist/add", method="POST", raw=b"x" * 9000
        )
        assert status == 413
    finally:
        stop_server(httpd, thread)
