from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from chives_hub.engine import HubEngine
from chives_hub.server import start_server, stop_server
from tests.support import (
    NOW,
    FakeClock,
    FakePortfolio,
    FakeSources,
    SimpleQuote,
    cn_alert,
    make_config,
    market_alert,
)


@contextmanager
def running_hub(tmp_path: Path, *, seed: bool = True, portfolio: FakePortfolio | None = None):
    config = make_config(tmp_path)
    clock = FakeClock(NOW)
    sources = FakeSources()
    sources.state = {"quotes": {"601099.SH": {"price": 3.44, "prev_close": 3.58, "change_pct": -3.91, "name": "太平洋"}}}
    sources.quotes = {
        "601099.SH": SimpleQuote("601099.SH", "太平洋", 3.44, 3.58, -3.91),
        "002553.SZ": SimpleQuote("002553.SZ", "南方精工", 15.52, 15.33, 1.24),
    }
    if seed:
        sources.cn = [cn_alert(1), cn_alert(2, code="002553.SZ", name="南方精工", rule_id="pct_up_3", rule_type="pct_change", direction="up", change_pct=3.2)]
        sources.market = [market_alert(1, rule="R3")]
    engine = HubEngine(config, clock=clock, sources=sources, portfolio=portfolio or FakePortfolio())
    engine.bootstrap()
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        yield engine, port, clock, sources
    finally:
        stop_server(httpd, thread)


def request(port: int, method: str, path: str, *, body=None, raw: bytes | None = None,
            headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        if raw is not None:
            payload = raw
            send_headers = {"Content-Type": "application/json", **(headers or {})}
        elif body is not None:
            payload = json.dumps(body).encode("utf-8")
            send_headers = {"Content-Type": "application/json", **(headers or {})}
        else:
            payload = None
            send_headers = headers or {}
        conn.request(method, path, body=payload, headers=send_headers)
        response = conn.getresponse()
        raw_body = response.read()
        return response.status, json.loads(raw_body) if raw_body else None
    finally:
        conn.close()


def get(port: int, path: str, headers=None):
    return request(port, "GET", path, headers=headers)


def post(port: int, path: str, body, headers=None):
    return request(port, "POST", path, body=body, headers=headers)


def test_health_shape(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/health")
    assert status == 200
    assert payload["ok"] is True
    assert set(payload["sources"]) >= {"cn_watch", "market_watch", "analyses"}
    assert "counts" in payload
    assert "db" in payload


def test_signals_default_active(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/signals")
    assert status == 200
    assert payload["ok"] is True
    assert payload["signals"]
    assert all(signal["status"] in {"new", "seen"} for signal in payload["signals"])
    assert "merged_today" in payload
    assert "next_id" in payload


def test_signals_shape(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, payload = get(port, "/signals?status=all&limit=10")
    signal = payload["signals"][0]
    for key in (
        "id", "ts", "kind", "kind_label", "decide", "severity", "status", "snooze_until",
        "object", "title", "direction", "direction_label", "conclusion", "brief",
        "context", "source", "merged_count", "primary", "detail_available",
    ):
        assert key in signal
    assert signal["object"]["type"] in {"stock", "sector", "market", "index"}


def test_signals_decide_filter(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, payload = get(port, "/signals?status=all&decide=1")
    assert all(signal["decide"] is True for signal in payload["signals"])


def test_signals_object_filter(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, payload = get(port, "/signals?status=all&object=sector")
    assert all(signal["object"]["type"] == "sector" for signal in payload["signals"])


def test_signals_invalid_status(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/signals?status=bogus")
    assert status == 200
    assert payload["ok"] is False


def test_signals_invalid_decide(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/signals?decide=2")
    assert status == 200


def test_signals_invalid_limit(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/signals?limit=0")
    assert status == 200


def test_signal_detail(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="all")[0]["id"]
        status, payload = get(port, f"/signals/{signal_id}")
    assert status == 200
    assert payload["ok"] is True
    assert payload["id"] == signal_id
    assert "signal" not in payload
    assert "analysis" in payload


def test_signal_detail_404(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/signals/9999")
    assert status == 404
    assert payload["ok"] is False


def test_action_ack(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "ack"})
    assert status == 200
    assert payload["signal"]["status"] == "seen"


def test_action_ignore(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "ignore"})
    assert payload["signal"]["status"] == "done"


def test_action_done(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        _, payload = post(port, f"/signals/{signal_id}/action", {"action": "done"})
    assert payload["signal"]["status"] == "done"


def test_action_snooze_and_unsnooze(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        _, payload = post(port, f"/signals/{signal_id}/action", {"action": "snooze", "until": "30m"})
        assert payload["signal"]["status"] == "snoozed"
        assert payload["signal"]["snooze_until"] is not None
        _, payload = post(port, f"/signals/{signal_id}/action", {"action": "unsnooze"})
        assert payload["signal"]["status"] == "new"


def test_action_snooze_close(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        _, payload = post(port, f"/signals/{signal_id}/action", {"action": "snooze", "until": "close"})
    assert payload["signal"]["snooze_until"].endswith("15:00:00+08:00")


def test_action_snooze_auto_restore(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, clock, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        post(port, f"/signals/{signal_id}/action", {"action": "snooze", "until": "2026-11-04T10:05:00+08:00"})
        clock.set(NOW.replace(minute=6))
        _, payload = get(port, "/signals?status=all")
    restored = [signal for signal in payload["signals"] if signal["id"] == signal_id][0]
    assert restored["status"] == "new"


def test_action_reopen(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        post(port, f"/signals/{signal_id}/action", {"action": "done"})
        _, payload = post(port, f"/signals/{signal_id}/action", {"action": "reopen"})
    assert payload["signal"]["status"] == "new"


def test_action_unknown_signal(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = post(port, "/signals/9999/action", {"action": "ack"})
    assert status == 404


def test_invalid_content_type(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(port, "POST", "/signals/1/action", raw=b'{"action":"ack"}', headers={"Content-Type": "text/plain"})
    assert status == 400


def test_malformed_json(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(port, "POST", "/signals/1/action", raw=b"{")
    assert status == 400


def test_non_object_json(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(port, "POST", "/signals/1/action", raw=b"[]")
    assert status == 400


def test_nan_json(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(port, "POST", "/signals/1/action", raw=b'{"action": NaN}')
    assert status == 400


def test_body_too_large(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(
            port, "POST", "/signals/1/action", raw=b"{}",
            headers={"Content-Length": "70000"},
        )
    assert status == 413


def test_unknown_field(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "ack", "x": 1})
    assert status == 400


def test_invalid_action(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "buy"})
    assert status == 400


def test_ack_with_until_rejected(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "ack", "until": "30m"})
    assert status == 400


def test_snooze_missing_until(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "snooze"})
    assert status == 400


def test_snooze_invalid_until(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {"action": "snooze", "until": "tomorrow"})
    assert status == 400


def test_create_user_plan(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "突破跟进", "proposed_by": "user",
        })
    assert status == 200
    assert payload["plan"]["status"] == "active"
    assert payload["plan"]["code"] == "601099.SH"


def test_create_agent_plan_proposed_and_signal(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        _, payload = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "突破跟进", "proposed_by": "agent",
        })
        plan_id = payload["plan"]["id"]
        _, signals = get(port, "/signals?status=active&decide=1")
    assert payload["plan"]["status"] == "proposed"
    assert any(signal["kind"] == "plan_proposal" and signal["source"]["plan_id"] == plan_id for signal in signals["signals"])


def test_plans_filter(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "user",
        })
        _, payload = get(port, "/plans?status=active")
    assert all(plan["status"] == "active" for plan in payload["plans"])


def test_plan_confirm(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, created = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "agent",
        })
        plan_id = created["plan"]["id"]
        status, payload = post(port, f"/plans/{plan_id}/action", {"action": "confirm"})
    assert status == 200
    assert payload["plan"]["status"] == "active"


def test_plan_cancel(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, created = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "user",
        })
        plan_id = created["plan"]["id"]
        _, payload = post(port, f"/plans/{plan_id}/action", {"action": "cancel"})
    assert payload["plan"]["status"] == "cancelled"


def test_plan_extend(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, created = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "user",
        })
        plan_id = created["plan"]["id"]
        _, payload = post(port, f"/plans/{plan_id}/action", {
            "action": "extend", "expires_at": "2026-11-20T15:00:00+08:00"
        })
    assert payload["plan"]["expires_at"].startswith("2026-11-20")


def test_plan_404(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = post(port, "/plans/9999/action", {"action": "confirm"})
    assert status == 404


def test_plan_invalid_kind(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = post(port, "/plans", {
            "code": "601099", "kind": "buy",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "user",
        })
    assert status == 400


def test_plan_sensitive_rejected(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "password = hunter2", "proposed_by": "user",
        })
    assert status == 400


def test_portfolio_overview_private(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/portfolio/overview")
    assert status == 200
    assert payload["private"] is True


def test_portfolio_history_private(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/portfolio/history?days=30")
    assert status == 200
    assert payload["private"] is True
    assert payload["points"] == []


def test_host_header_rejected(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/health", headers={"Host": "evil.example.com"})
    assert status == 403


def test_unknown_path(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/nope")
    assert status == 404


def test_put_method_rejected(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = request(port, "PUT", "/plans", body={})
    assert status == 405


def test_plans_invalid_status(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        status, payload = get(port, "/plans?status=bogus")
    assert status == 200


def test_concurrent_actions(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        results = []

        def worker():
            results.append(post(port, f"/signals/{signal_id}/action", {"action": "ack"})[0])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert results and all(status == 200 for status in results)


def test_signals_counts_exact_keys(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (_, port, _, _):
        _, payload = get(port, "/signals?status=all")
    assert set(payload["counts"]) == {"decide", "active", "snoozed", "done"}


def test_confirm_closes_proposal_card(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        _, created = post(port, "/plans", {
            "code": "601099", "kind": "entry",
            "condition": {"type": "price_cross", "direction": "up", "level": 3.5},
            "rationale": "x", "proposed_by": "agent",
        })
        plan_id = created["plan"]["id"]
        post(port, f"/plans/{plan_id}/action", {"action": "confirm"})
        rows = [row for row in engine.store.list_signals(status="all") if row["source"].get("plan_id") == plan_id]
    assert rows and all(row["status"] == "done" for row in rows if row["kind"] == "plan_proposal")


def test_snooze_past_iso_rejected(tmp_path: Path) -> None:
    with running_hub(tmp_path) as (engine, port, _, _):
        signal_id = engine.store.list_signals(status="active")[0]["id"]
        status, payload = post(port, f"/signals/{signal_id}/action", {
            "action": "snooze", "until": "2026-11-04T09:00:00+08:00"
        })
    assert status == 400
    assert payload["ok"] is False
