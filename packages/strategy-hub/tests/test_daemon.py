from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from strategy_hub.daemon import HubDaemon

from .support import build_service


def get_json(base: str, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_daemon_endpoints(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    daemon = HubDaemon(service, port=0).start()
    base = f"http://127.0.0.1:{daemon.port}"
    try:
        status, payload = get_json(base, "/v1/strategies")
        assert status == 200
        assert payload["strategies"][0]["id"] == "zhushenglang"

        status, payload = get_json(base, "/v1/zhushenglang/pools")
        assert status == 200
        assert payload["pools"]["first"][0]["code"] == "600519.SH"

        status, payload = get_json(base, "/v1/zhushenglang/round?code=600519.SH")
        assert status == 200
        assert payload["round"]["round_id"] == 1

        status, payload = get_json(
            base, "/v1/zhushenglang/events?start=2026-11-17&end=2026-11-17&kinds=" + urllib.parse.quote("优先级一确定")
        )
        assert status == 200
        assert payload["count"] == 1
        assert payload["events"][0]["level"] == "important"

        status, payload = get_json(base, "/v1/zhushenglang/levels?code=600519.SH")
        assert status == 200
        assert {item["key"] for item in payload["levels"]} == {"hb", "p_star", "s1", "s2", "ma10"}

        service.ingest_events("2026-11-17")
        status, payload = get_json(base, "/alerts?since_id=0&limit=2")
        assert status == 200
        assert len(payload["alerts"]) == 2
        assert payload["next_id"] == 2

        status, payload = get_json(base, "/health")
        assert status == 200
        assert payload["ok"] is True
        assert payload["alerts_latest_id"] == 3
    finally:
        daemon.stop()


def test_daemon_returns_chinese_errors(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    daemon = HubDaemon(service, port=0).start()
    base = f"http://127.0.0.1:{daemon.port}"
    try:
        with urllib.request.urlopen(base + "/v1/nope/pools", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200  # urllib raises on 4xx, checked below instead
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        assert exc.code == 404
    assert "没有这个策略" in payload["message"]

    try:
        urllib.request.urlopen(base + "/v1/zhushenglang/pools?date=2026/11/17", timeout=5)
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        assert exc.code == 400
        assert "YYYY-MM-DD" in payload["message"]
    else:  # pragma: no cover - assertion helper
        raise AssertionError("expected HTTP 400")
