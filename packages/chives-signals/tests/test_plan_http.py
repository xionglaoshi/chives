from __future__ import annotations

import json
from pathlib import Path

import pytest

from chives_signals.engine import HubEngine
from chives_signals.sources import SourceError, Sources, UpstreamRejection
from tests.fake_cnwatch_http import FakeCnWatch
from tests.support import FakeClock, FakePortfolio, at, make_config

PLAN = {
    "id": "card-1",
    "code": "600519.SH",
    "market": [{"type": "regime", "values": ["strong"]}],
    "sector": [],
    "stock": [{"type": "price_cross", "direction": "up", "level": 99.0}],
    "policy": "all",
    "giveup": [],
    "stop_price": 90.0,
    "held": True,
    "expires_at": "2026-11-05T15:00:00+08:00",
    "label": "贵州茅台 作战卡",
}


@pytest.fixture
def fake():
    server = FakeCnWatch().start()
    try:
        yield server
    finally:
        server.stop()


def _sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeCnWatch) -> Sources:
    monkeypatch.setenv("CHIVES_HUB_TEST_MODE", "1")
    monkeypatch.setenv("CHIVES_HUB_CN_WATCH_BASE", fake.base)
    return Sources(make_config(tmp_path))


def test_http_upsert_sends_actor_and_plan(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    result = sources.upsert_plan(PLAN, now=at(10))
    assert result["ok"] is True
    assert fake.actors[-1] == "chives-hub"
    assert fake.upserts[-1] == PLAN


def test_http_get_plans(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    sources.upsert_plan(PLAN, now=at(10))
    payload = sources.plans(now=at(10))
    assert payload["ok"] is True
    assert [item["id"] for item in payload["plans"]] == ["card-1"]


def test_http_remove_sends_id(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    sources.upsert_plan(PLAN, now=at(10))
    sources.remove_plan("card-1", now=at(10))
    assert fake.removes[-1] == {"id": "card-1"}
    assert fake.states == {}


def test_http_rejection_is_typed(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    fake.reject = ("watchlist_full", "自选股数量已达上限")
    with pytest.raises(UpstreamRejection) as exc:
        sources.upsert_plan(PLAN, now=at(10))
    assert exc.value.code == "watchlist_full"
    assert exc.value.field == "code"


def test_http_unreachable_is_source_error(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    fake.stop()
    with pytest.raises(SourceError):
        sources.plans(now=at(10))


def test_http_server_error_is_source_error(tmp_path, monkeypatch, fake) -> None:
    sources = _sources(tmp_path, monkeypatch, fake)
    fake.down = True
    with pytest.raises(SourceError):
        sources.plans(now=at(10))


def test_http_hub_pushes_and_mirrors_end_to_end(tmp_path, monkeypatch, fake) -> None:
    monkeypatch.setenv("CHIVES_HUB_TEST_MODE", "1")
    monkeypatch.setenv("CHIVES_HUB_CN_WATCH_BASE", fake.base)
    config = make_config(tmp_path)
    clock = FakeClock(at(10))
    portfolio = FakePortfolio()
    portfolio.overview_payload["positions"] = [
        {"code": "600519.SH", "name": "贵州茅台", "weight_pct": 20.0}
    ]
    engine = HubEngine(config, clock=clock, sources=Sources(config), portfolio=portfolio)
    created = engine.create_card(
        {
            "code": "600519.SH",
            "name": "贵州茅台",
            "thesis": "端到端",
            "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99.0}],
            "risk": {"stop_price": 90.0},
            "proposed_by": "user",
        }
    )
    card_id = created["card"]["id"]
    assert [item["id"] for item in fake.upserts] == [f"card-{card_id}"]
    assert fake.upserts[0]["held"] is True
    engine._sync_cards(at(10))
    fake.set_state(
        f"card-{card_id}", "execute", price=100.0, ts="2026-11-04T10:00:03+08:00"
    )
    engine._sync_cards(at(10, 0, 3))
    assert engine.store.get_card(card_id)["state"] == "execute"
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "card_state"]
    assert len(rows) == 1
    assert engine.trigger_context(engine.store.list_triggers()[0]["id"])["context"]["card"][
        "state"
    ] == "execute"
