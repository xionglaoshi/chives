from __future__ import annotations

import http.client
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from chives_hub.server import start_server, stop_server
from tests.support import NOW, at, build_engine


@contextmanager
def hub(tmp_path: Path, **kwargs):
    engine, clock, sources, portfolio = build_engine(tmp_path, **kwargs)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        yield engine, clock, sources, portfolio, port
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


CARD_BODY = {
    "code": "600519.SH",
    "thesis": "测试",
    "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99}],
    "risk": {"stop_price": 90},
    "proposed_by": "user",
}


def test_settings_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/settings")
    assert status == 200
    assert payload["ok"] is True
    assert len(payload["settings"]) == 11


def test_setting_suggest_and_adopt_over_http(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, suggested = post(port, "/settings/theme_cap_pct/suggest", {"value": 30, "basis": "测试"})
        assert status == 200
        assert suggested["setting"]["value"] is None
        _, adopted = post(port, "/settings/theme_cap_pct/action", {"action": "adopt"})
        assert adopted["setting"]["value"] == 30
        assert adopted["setting"]["source"] == "adopted"


def test_setting_action_errors_are_business_errors(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = post(port, "/settings/theme_cap_pct/action", {"action": "adopt"})
        assert status == 200
        assert payload["ok"] is False
        assert payload["error"]["code"] == "no_suggestion"


def test_setting_unknown_key(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = post(port, "/settings/bogus/action", {"action": "clear"})
    assert payload["ok"] is False


def test_setting_out_of_range(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = post(port, "/settings/per_trade_risk_pct/action", {"action": "set", "value": 99})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_value"


def test_discipline_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/discipline")
    assert status == 200
    assert set(payload) == {"ok", "paused", "reasons", "metrics", "thresholds", "mood_today", "headroom"}
    assert payload["paused"] is False


def test_discipline_loss_streak_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, first = post(port, "/discipline/loss-streak", {"action": "add"})
        assert first["loss_streak"] == 1
        _, reset = post(port, "/discipline/loss-streak", {"action": "reset"})
        assert reset["loss_streak"] == 0


def test_discipline_mood_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = post(port, "/discipline/mood", {"slot": "pre", "level": "calm"})
        assert payload["mood_today"]["pre"] == "calm"
        _, payload = post(port, "/discipline/mood", {"slot": "pre", "level": "unfit"})
        assert payload["mood_today"]["pre"] == "unfit"


def test_review_data_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/review-data")
    assert status == 200
    assert payload["trading_day"] is True
    assert payload["holdings"]["private"] is True
    assert "missing" in payload


def test_review_data_holiday_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path, now=datetime(2026, 11, 7, 10, 0, tzinfo=NOW.tzinfo)) as (_, _, _, _, port):
        _, payload = get(port, "/review-data")
    assert payload == {
        "ok": True,
        "trading_day": False,
        "date": "2026-11-07",
        "next_trading_day": "2026-11-09",
    }


def test_save_review_and_read_back(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        body = {"date": "2026-11-04", "kind": "evening", "env": {"label": "strong", "evidence": ["a"]}}
        status, saved = post(port, "/reviews", body)
        assert status == 200
        assert saved["revision"] == 1
        _, listing = get(port, "/reviews")
        assert listing["count"] == 1
        _, detail = get(port, "/reviews/2026-11-04?kind=evening")
        assert detail["untrusted_text"] is True


def test_save_review_rejects_extra_field(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = post(
            port,
            "/reviews",
            {"date": "2026-11-04", "kind": "evening", "env": {"label": "strong", "evidence": []}, "extra": 1},
        )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unexpected_field"


def test_save_review_rejects_too_many_candidates(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        body = {
            "date": "2026-11-04",
            "kind": "evening",
            "env": {"label": "strong", "evidence": []},
            "candidates": [
                {"code": "600519.SH", "reason": "x", "card_id": None, "tags": {}}
            ]
            * 6,
        }
        _, payload = post(port, "/reviews", body)
    assert payload["error"]["code"] == "too_many_candidates"


def test_review_detail_not_found(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/reviews/2026-11-04?kind=evening")
    assert status == 404
    assert payload["ok"] is False


def test_cards_endpoint_empty(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/cards")
    assert status == 200
    assert payload["cards"] == []
    assert "counts" in payload


def test_create_card_over_http(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = post(port, "/cards", CARD_BODY)
        assert status == 200
        assert payload["card"]["status"] == "active"
        card_id = payload["card"]["id"]
        _, detail = get(port, f"/cards/{card_id}")
        assert detail["card"]["id"] == card_id


def test_agent_card_over_http_and_confirm(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        body = dict(CARD_BODY, proposed_by="agent")
        _, created = post(port, "/cards", body)
        card_id = created["card"]["id"]
        _, confirmed = post(port, f"/cards/{card_id}/action", {"action": "confirm"})
        assert confirmed["card"]["status"] == "active"


def test_card_action_tighten_stop_over_http(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, created = post(port, "/cards", CARD_BODY)
        _, payload = post(
            port, f"/cards/{created['card']['id']}/action", {"action": "tighten_stop", "stop": 94}
        )
    assert payload["card"]["risk"]["stop_price"] == 94


def test_card_action_loosen_rejected(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, created = post(port, "/cards", CARD_BODY)
        _, payload = post(
            port, f"/cards/{created['card']['id']}/action", {"action": "tighten_stop", "stop": 80}
        )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "loosen_not_allowed"


def test_card_action_locked_rejected(tmp_path: Path) -> None:
    with hub(tmp_path, now=at(10)) as (_, _, _, _, port):
        _, created = post(port, "/cards", CARD_BODY)
        _, payload = post(
            port, f"/cards/{created['card']['id']}/action", {"action": "set_state", "state": "execute"}
        )
    assert payload["error"]["code"] == "locked"


def test_card_not_found(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/cards/999")
    assert status == 404


def test_cards_status_filter(tmp_path: Path) -> None:
    with hub(tmp_path, now=at(10)) as (_, _, _, _, port):
        _, created = post(port, "/cards", CARD_BODY)
        post(port, f"/cards/{created['card']['id']}/action", {"action": "cancel"})
        _, active = get(port, "/cards?status=active")
        _, closed = get(port, "/cards?status=closed")
    assert active["cards"] == []
    assert len(closed["cards"]) == 1


def test_candidates_stats_endpoint(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/candidates/stats?days=20")
    assert status == 200
    assert payload["n"] == 0
    assert payload["sample_insufficient"] is True


def test_candidates_stats_rejects_bad_days(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = get(port, "/candidates/stats?days=0")
    assert payload["ok"] is False


def test_portfolio_overview_has_limits(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = get(port, "/portfolio/overview")
    assert "limits" in payload
    assert payload["limits"]["position_ratio_pct"] == 20.0


def test_health_does_not_leak_private_fields(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        _, payload = get(port, "/health")
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("mood", "settings", "positions", "discipline"):
        assert forbidden not in text


def test_signals_kind_label_for_new_kind(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        post(port, "/cards", dict(CARD_BODY, proposed_by="agent"))
        _, payload = get(port, "/signals?status=all")
    kinds = {item["kind"]: item for item in payload["signals"]}
    assert kinds["card_proposal"]["kind_label"] == "待确认作战卡"
    assert kinds["card_proposal"]["primary"]["action"] == "confirm_card"


def test_unknown_path_and_method(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = get(port, "/nope")
        assert status == 404
        status2, _ = request(port, "PUT", "/settings")
    assert status2 == 405


def test_review_data_not_reachable_from_post(tmp_path: Path) -> None:
    with hub(tmp_path) as (_, _, _, _, port):
        status, payload = post(port, "/review-data", {})
    assert status == 404
