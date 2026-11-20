from __future__ import annotations

import json
import urllib.request
from datetime import date

import pytest

from market_watch.server import start_server, stop_server
from tests.support import board_list_payload, board_row
from tests.test_engine import OPEN, make_engine

DAY = date(2026, 11, 3)
PREV = date(2026, 11, 2)


def row(code, name, streak=1):
    return {
        "code": code, "name": name, "price": 10.0, "change_pct": 10.0,
        "amount_yuan": 1e8, "turnover_pct": 1.0, "streak": streak,
        "first_seal_time": "09:30:00", "broken_times": 0, "industry": "行业A",
        "seal_amount_yuan": 1e7,
    }


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture()
def api(tmp_path):
    engine = make_engine(tmp_path)
    engine._trading_state = "open"
    for day, rows in ((DAY, [row("600000.SH", "A", 2), row("600001.SH", "B", 1)]),
                      (PREV, [row("600000.SH", "A", 1)])):
        for kind, payload in (("zt", rows), ("zb", []), ("dt", [])):
            engine.store.save_pool_day(day, kind, count=len(payload), rows=payload,
                                       fetched_at=OPEN)
    engine.store.save_breadth_point(DAY, "09:30", up=10, down=20, flat=1,
                                    limit_up=3, limit_down=1)
    engine.client.routes.insert(0, (
        "eastmoney", "/api/qt/clist/get",
        lambda path, params: board_list_payload([
            board_row("BK1001", "人工智能", 2.0, 1e9, 10, 2, leader_code="600000",
                      leader_name="A", leader_change_pct=5.0, stamp=1793691570),
            board_row("BK1002", "昨日涨停", 1.0, 1e9, 10, 2, stamp=1793691570),
        ]),
    ))
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, engine
    finally:
        stop_server(httpd, thread)


def test_api_pool(api):
    base, _ = api
    status, payload = get_json(base, "/pool?kind=zt&limit=1")
    assert status == 200 and payload["ok"] is True
    assert payload["count"] == 2 and len(payload["rows"]) == 1


def test_api_pool_bad_limit_still_200(api):
    base, _ = api
    status, payload = get_json(base, "/pool?limit=abc")
    assert status == 200 and payload["error"]["code"] == "bad_request"


def test_api_pool_ladder(api):
    base, _ = api
    status, payload = get_json(base, "/pool/ladder")
    assert status == 200 and payload["max_streak"] == 2


def test_api_pool_history(api):
    base, _ = api
    status, payload = get_json(base, "/pool/history?days=10")
    assert status == 200 and len(payload["days"]) == 10


def test_api_pool_history_bad_days(api):
    base, _ = api
    status, payload = get_json(base, "/pool/history?days=8")
    assert status == 200 and payload["error"]["code"] == "bad_request"


def test_api_pool_by_industry(api):
    base, _ = api
    status, payload = get_json(base, "/pool/by-industry")
    assert status == 200 and payload["rows"][0]["industry"] == "行业A"


def test_api_breadth_series(api):
    base, _ = api
    status, payload = get_json(base, "/breadth/series")
    assert status == 200 and payload["points"][0]["t"] == "09:30"


def test_api_themes(api):
    base, _ = api
    status, payload = get_json(base, "/themes?kind=concept&limit=5&sort=change")
    assert status == 200
    assert [item["name"] for item in payload["rows"]] == ["人工智能"]


def test_api_themes_bad_sort(api):
    base, _ = api
    status, payload = get_json(base, "/themes?sort=up")
    assert status == 200 and payload["error"]["code"] == "bad_request"


def test_api_health_has_v14_sources(api):
    base, _ = api
    _, payload = get_json(base, "/health")
    assert {"pool_history", "breadth_series", "themes"} <= set(payload["sources"])
    assert "backfill" in payload
