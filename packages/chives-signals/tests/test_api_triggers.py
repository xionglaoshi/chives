from __future__ import annotations

import http.client
import json
from contextlib import contextmanager
from pathlib import Path

from chives_signals.server import start_server, stop_server
from tests.support import active_card, at, build_engine


@contextmanager
def hub(tmp_path: Path, **kwargs):
    engine, clock, sources, portfolio = build_engine(tmp_path, **kwargs)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        yield engine, sources, port
    finally:
        stop_server(httpd, thread)


def request(port: int, method: str, path: str, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        return response.status, json.loads(raw) if raw else None
    finally:
        conn.close()


def get(port: int, path: str):
    return request(port, "GET", path)


def post(port: int, path: str, body):
    return request(port, "POST", path, body)


def _make_trigger(engine):
    card = active_card(engine)
    engine._sync_cards(at(10))
    return card, engine.store.list_triggers()[0]


def test_get_triggers_empty(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers")
    assert status == 200
    assert payload == {"ok": True, "triggers": [], "next_id": 0}


def test_get_triggers_contract(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        card, trigger = _make_trigger(engine)
        status, payload = get(port, "/triggers")
    assert status == 200
    assert payload["next_id"] == trigger["id"]
    row = payload["triggers"][0]
    assert row["kind"] == "card_execute"
    assert row["card_id"] == card["id"]
    assert row["context_ready"] is True
    assert row["judged"] is False


def test_get_triggers_since_id_and_limit(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _make_trigger(engine)
        for index in range(3):
            engine.store.insert_trigger(
                {"kind": "regime", "to_state": f"s{index}", "reason": "test"}, at(9, index)
            )
        _, first = get(port, "/triggers?since_id=0&limit=2")
        assert len(first["triggers"]) == 2
        _, rest = get(port, f"/triggers?since_id={first['next_id']}&limit=2")
        assert len(rest["triggers"]) == 2
        assert rest["triggers"][0]["id"] > first["triggers"][-1]["id"]


def test_get_triggers_rejects_extra_param(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers?kind=card_execute")
    assert status == 200
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_param"


def test_get_triggers_rejects_bad_limit(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers?limit=0")
    assert status == 200
    assert payload["error"]["code"] == "invalid_param"


def test_get_triggers_rejects_bad_since_id(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers?since_id=x")
    assert status == 200
    assert payload["error"]["code"] == "invalid_param"


def test_get_trigger_context_private(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = get(port, f"/triggers/{trigger['id']}/context")
    assert status == 200
    assert payload["ok"] is True
    assert payload["private"] is True
    assert payload["trigger"]["id"] == trigger["id"]
    assert payload["context"]["card"] is not None


def test_get_trigger_context_unknown_404(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers/999/context")
    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_get_trigger_context_is_stable_over_http(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        _, first = get(port, f"/triggers/{trigger['id']}/context")
        _, second = get(port, f"/triggers/{trigger['id']}/context")
    assert first["context"] == second["context"]


def test_post_judgement_ok(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "await_confirm", "reason": "量能不足", "next_check": "10:30", "risk": "跌破 95"},
        )
    assert status == 200
    assert payload["ok"] is True
    assert payload["private"] is True
    assert payload["diverges_from_state"] is True
    assert payload["judgement"]["reason"] == "量能不足"


def test_post_judgement_twice_returns_already_judged(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "execute", "reason": "量能确认", "next_check": "10:30", "risk": "跌破 95"},
        )
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "observe", "reason": "再等", "next_check": "10:40", "risk": "跌破 95"},
        )
    assert status == 200
    assert payload["ok"] is False
    assert payload["error"]["code"] == "already_judged"


def test_post_judgement_unknown_trigger_404(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = post(
            port,
            "/triggers/999/judgement",
            {"action": "observe", "reason": "看", "next_check": "10:30", "risk": "无"},
        )
    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_post_judgement_bad_action(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "buy", "reason": "看", "next_check": "10:30", "risk": "无"},
        )
    assert status == 200
    assert payload["error"]["code"] == "invalid_action"


def test_post_judgement_extra_field(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "observe", "reason": "看", "next_check": "10:30", "risk": "无", "price": 1},
        )
    assert status == 200
    assert payload["error"]["code"] == "unexpected_field"


def test_post_judgement_too_long_text(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "observe", "reason": "字" * 61, "next_check": "10:30", "risk": "无"},
        )
    assert status == 200
    assert payload["error"]["code"] == "invalid_value"


def test_post_judgement_missing_field_then_complete(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "execute", "reason": "条件满足", "next_check": "10:30"},
        )
        assert status == 200
        assert payload["ok"] is False
        assert payload["error"]["code"]
        assert engine.store.get_trigger(trigger["id"])["judgement"] is None
        status, payload = post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "execute", "reason": "条件满足", "next_check": "10:30", "risk": "跌破 95"},
        )
        assert status == 200
        assert payload["ok"] is True
        assert payload["trigger"]["judged"] is True
        assert engine.store.fast_judgements_used("2026-11-04") == 1


def test_post_judgement_requires_json(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _make_trigger(engine)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request("POST", "/triggers/1/judgement", body=b"action=observe")
            response = conn.getresponse()
            payload = json.loads(response.read())
        finally:
            conn.close()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_content_type"


def test_get_guidance_empty(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/guidance")
    assert status == 200
    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["guidance"] == []


def test_get_guidance_lists_generated(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        active_card(engine)
        engine._maybe_guidance(at(10))
        status, payload = get(port, "/guidance?date=2026-11-04")
    assert status == 200
    assert payload["count"] == 1
    assert payload["guidance"][0]["slot"] == "10:00"
    assert payload["guidance"][0]["context"]["type"] == "guidance"


def test_get_guidance_rejects_bad_date(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/guidance?date=2026-1-1")
    assert status == 200
    assert payload["error"]["code"] == "invalid_param"


def test_get_guidance_rejects_extra_param(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/guidance?date=2026-11-04&slot=10:00")
    assert status == 200
    assert payload["error"]["code"] == "invalid_param"


def test_health_has_no_trigger_or_context_keys(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _make_trigger(engine)
        _, payload = get(port, "/health")
    text = json.dumps(payload, ensure_ascii=False)
    assert "triggers" not in text
    assert "context" not in text
    assert "600519" not in text


def test_trigger_paths_do_not_expose_other_methods(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        status, _ = request(port, "PUT", f"/triggers/{trigger['id']}/judgement", {"action": "observe"})
    assert status == 405


def test_unknown_trigger_path_still_404(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, port):
        status, payload = get(port, "/triggers/1/context/extra")
    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_context_ready_flips_after_context_request(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        card = active_card(engine)
        trigger_id = engine.store.insert_trigger(
            {
                "kind": "card_execute",
                "card_id": card["id"],
                "code": card["code"],
                "name": card["name"],
                "from_state": "observe",
                "to_state": "execute",
                "reason": "手动插入",
            },
            at(10),
        )
        _, before = get(port, "/triggers")
        _, context = get(port, f"/triggers/{trigger_id}/context")
        _, after = get(port, "/triggers")
    assert before["triggers"][0]["context_ready"] is False
    assert context["trigger"]["context_ready"] is True
    assert after["triggers"][0]["context_ready"] is True


def test_judged_flag_flips_after_judgement(tmp_path: Path) -> None:
    with hub(tmp_path) as (engine, _, port):
        _, trigger = _make_trigger(engine)
        post(
            port,
            f"/triggers/{trigger['id']}/judgement",
            {"action": "observe", "reason": "看", "next_check": "10:30", "risk": "无"},
        )
        _, payload = get(port, "/triggers")
    assert payload["triggers"][0]["judged"] is True
