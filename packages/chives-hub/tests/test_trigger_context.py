from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tests.support import (
    active_card,
    adopt_setting,
    at,
    build_engine,
)


def _trigger(engine, card=None, kind="card_execute", reason="条件成立"):
    card = card or active_card(engine)
    trigger_id = engine.store.insert_trigger(
        {
            "kind": kind,
            "card_id": card["id"],
            "code": card["code"],
            "name": card["name"],
            "from_state": "observe",
            "to_state": "execute",
            "reason": reason,
        },
        at(10),
    )
    return card, trigger_id


def _context(engine, trigger_id):
    payload = engine.trigger_context(trigger_id)
    assert payload is not None
    return payload


def test_context_response_is_private(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    payload = _context(engine, trigger_id)
    assert payload["private"] is True
    assert payload["ok"] is True


def test_context_contract_keys(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert {
        "trigger",
        "card",
        "review",
        "snapshot",
        "holdings_relation",
        "discipline",
        "thresholds",
        "today",
        "missing",
    }.issubset(context)


def test_context_is_frozen_between_reads(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    first = _context(engine, trigger_id)
    sources.state["quotes"]["600519.SH"]["price"] = 120.0
    sources.overview_payload["breadth"]["limit_up"] = 99
    second = _context(engine, trigger_id)
    assert first["context"] == second["context"]


def test_context_trigger_matches_queue_row(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    payload = _context(engine, trigger_id)
    assert payload["trigger"]["id"] == trigger_id
    assert payload["trigger"]["kind"] == "card_execute"
    assert payload["context"]["trigger"]["id"] == trigger_id


def test_context_card_is_full_card(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card, trigger_id = _trigger(engine)
    block = _context(engine, trigger_id)["context"]["card"]
    assert block["id"] == card["id"]
    assert block["code"] == "600519.SH"
    assert block["stock_conditions"] == card["stock_conditions"]
    assert block["risk"] == card["risk"]
    assert block["sizing"] == card["sizing"]


def test_context_review_summary(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(
        {
            "date": "2026-11-03",
            "kind": "evening",
            "env": {"label": "strong", "evidence": ["宽度走强", "成交额放大"], "differs_from_rule": False},
            "mainline": {"name": "机器人", "note": "主线延续"},
            "candidates": [
                {"code": "600519.SH", "reason": "龙头", "tags": {}},
                {"code": "300750.SZ", "reason": "跟风", "tags": {}},
            ],
            "data_cutoff": "19:45",
            "body_markdown": "x",
        }
    )
    card, trigger_id = _trigger(engine)
    review = _context(engine, trigger_id)["context"]["review"]
    assert review["date"] == "2026-11-03"
    assert review["env_label"] == "strong"
    assert review["evidence"] == ["宽度走强", "成交额放大"]
    assert review["mainline"]["name"] == "机器人"
    assert review["thesis_from_candidates"] == "龙头"


def test_context_review_missing_is_null_and_listed(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert context["review"] is None
    assert "review" in context["missing"]


def test_context_quote_math(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.state["quotes"]["600519.SH"].update({"vwap": 99.0, "limit_up": 105.0, "limit_down": 90.0})
    _, trigger_id = _trigger(engine)
    quote = _context(engine, trigger_id)["context"]["snapshot"]["quote"]
    assert quote["price"] == 100.0
    assert quote["change_pct"] == 2.04
    assert quote["vwap_dev_pct"] == pytest.approx(1.01, abs=0.01)
    assert quote["limit_distance_pct"] == pytest.approx(5.0, abs=0.01)


def test_context_limit_distance_derived_from_prev_close(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    quote = _context(engine, trigger_id)["context"]["snapshot"]["quote"]
    assert quote["limit_distance_pct"] == pytest.approx(7.8, abs=0.01)


def test_context_limit_distance_uses_twenty_percent_for_chinext(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.state["quotes"]["300750.SZ"] = {
        "price": 80.0,
        "prev_close": 100.0,
        "change_pct": -20.0,
        "name": "宁德时代",
    }
    card = active_card(engine, code="300750.SZ")
    _, trigger_id = _trigger(engine, card=card)
    quote = _context(engine, trigger_id)["context"]["snapshot"]["quote"]
    assert quote["limit_distance_pct"] == pytest.approx(0.0, abs=0.01)


def test_context_sector_matched_from_card_condition(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card = active_card(
        engine,
        sector_conditions=[{"type": "sector_change", "sector_code": "BK0433", "op": ">=", "value": -100}],
    )
    _, trigger_id = _trigger(engine, card=card)
    sector = _context(engine, trigger_id)["context"]["snapshot"]["sector"]
    assert sector["code"] == "BK0433"
    assert sector["name"] == "农林牧渔"
    assert sector["rank"] == 1
    assert sector["change_pct"] == 3.2


def test_context_sector_matched_by_holding_industry(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.sectors_payload["rows"].append(
        {"code": "BK0999", "name": "食品饮料", "change_pct": 1.1, "rank": 6}
    )
    _, trigger_id = _trigger(engine)
    sector = _context(engine, trigger_id)["context"]["snapshot"]["sector"]
    assert sector["code"] == "BK0999"


def test_context_market_block(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    market = _context(engine, trigger_id)["context"]["snapshot"]["market"]
    assert market["regime"] == "strong"
    assert market["breadth"]["limit_up"] == 60
    assert market["breadth"]["limit_down"] == 5
    assert market["amount_yuan"] == pytest.approx(9e11)


def test_context_holdings_relation_held(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    adopt_setting(engine, "single_stock_cap_pct", 25)
    adopt_setting(engine, "total_cap_strong_pct", 60)
    _, trigger_id = _trigger(engine)
    relation = _context(engine, trigger_id)["context"]["holdings_relation"]
    assert relation["held"] is True
    assert relation["weight_pct"] == 20.0
    assert relation["single_cap_pct"] == 25.0
    assert relation["total_room_pct"] == pytest.approx(40.0)


def test_context_holdings_relation_not_held(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(
        tmp_path,
        positions=[{"code": "300750.SZ", "name": "宁德时代", "weight_pct": 10.0, "industry": "电力设备"}],
    )
    _, trigger_id = _trigger(engine)
    relation = _context(engine, trigger_id)["context"]["holdings_relation"]
    assert relation["held"] is False
    assert relation["weight_pct"] is None


def test_context_thresholds_only_adopted(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.setting_suggest("theme_cap_pct", {"value": 30, "basis": "建议"})
    adopt_setting(engine, "single_stock_cap_pct", 25)
    _, trigger_id = _trigger(engine)
    thresholds = _context(engine, trigger_id)["context"]["thresholds"]
    assert thresholds == {"single_stock_cap_pct": 25.0}


def test_context_discipline_mood_and_pause(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    adopt_setting(engine, "pause_day_drawdown_pct", 1)
    engine.store.insert_snapshot(
        day=at(0).date().replace(day=3),
        market_value_cny=1_500_000.0,
        total_assets_cny=2_000_000.0,
        pnl_cny=0.0,
        day_pnl_cny=0.0,
        quote_time="2026-11-03 15:00:00",
        now=at(0),
    )
    engine.discipline_mood({"slot": "mid", "level": "volatile"})
    _, trigger_id = _trigger(engine)
    discipline = _context(engine, trigger_id)["context"]["discipline"]
    assert discipline["paused"] is True
    assert discipline["mood_today"]["mid"] == "volatile"


def test_context_today_counts(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card, trigger_id = _trigger(engine)
    engine.store.insert_trigger(
        {
            "kind": "card_abandon",
            "card_id": card["id"],
            "code": card["code"],
            "name": card["name"],
            "from_state": "execute",
            "to_state": "abandon",
            "reason": "放弃",
        },
        at(10, 5),
    )
    today = _context(engine, trigger_id)["context"]["today"]
    assert today["trigger_count"] == 2
    assert today["fast_judgements_used"] == 0


def test_context_missing_quote_when_upstreams_down(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.fail_state = True
    sources.quotes = {}
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert context["snapshot"]["quote"] is None
    assert "snapshot.quote" in context["missing"]


def test_context_missing_market_when_overview_down(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.fail_overview = True
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert context["snapshot"]["market"] is None
    assert "snapshot.market" in context["missing"]


def test_context_missing_sector_when_rows_empty(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.sectors_payload = {"ok": True, "rows": []}
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert context["snapshot"]["sector"] is None
    assert "snapshot.sector" in context["missing"]


def test_context_missing_lists_every_unavailable_block(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.fail_overview = True
    sources.fail_state = True
    sources.quotes = {}
    sources.sectors_payload = {"ok": True, "rows": []}
    _, trigger_id = _trigger(engine)
    missing = _context(engine, trigger_id)["context"]["missing"]
    for part in ("review", "snapshot.quote", "snapshot.sector", "snapshot.market"):
        assert part in missing


def test_context_size_under_twelve_kilobytes(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    card, _ = _trigger(engine)
    for index in range(120):
        engine.store.append_card_history(
            card["id"],
            from_state=f"observe{index}",
            to_state=f"execute{index}",
            reason="很长的状态说明" * 12,
            now=at(9, index % 60),
        )
    trigger_id = engine.store.insert_trigger(
        {
            "kind": "card_execute",
            "card_id": card["id"],
            "code": card["code"],
            "name": card["name"],
            "from_state": "observe",
            "to_state": "execute",
            "reason": "超大上下文",
        },
        at(10),
    )
    payload = _context(engine, trigger_id)
    raw = json.dumps(payload["context"], ensure_ascii=False).encode("utf-8")
    assert len(raw) <= 12 * 1024
    assert payload["context"]["trimmed"]


def test_context_trimming_keeps_card_and_snapshot(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(
        {
            "date": "2026-11-03",
            "kind": "evening",
            "env": {
                "label": "strong",
                "evidence": ["证" * 80 for _ in range(8)],
                "differs_from_rule": False,
            },
            "mainline": {"name": "机器人", "note": "主线"},
            "candidates": [],
            "data_cutoff": "19:45",
            "body_markdown": "x",
        }
    )
    card, _ = _trigger(engine)
    for index in range(120):
        engine.store.append_card_history(
            card["id"],
            from_state="observe",
            to_state=f"s{index}",
            reason="状态说明" * 300,
            now=at(9),
        )
    trigger_id = engine.store.insert_trigger(
        {"kind": "card_execute", "card_id": card["id"], "code": card["code"], "name": card["name"], "reason": "r"},
        at(10),
    )
    context = _context(engine, trigger_id)["context"]
    assert context["card"] is not None
    assert context["snapshot"]["quote"] is not None
    assert "review" in context["trimmed"] or "review.evidence" in context["trimmed"]


def test_context_never_contains_nan(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.state["quotes"]["600519.SH"]["change_pct"] = float("nan")
    _, trigger_id = _trigger(engine)
    payload = _context(engine, trigger_id)
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_context_does_not_log_holdings(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    with caplog.at_level(logging.DEBUG, logger="chives_hub"):
        _context(engine, trigger_id)
    assert "600519" not in caplog.text
    assert "食品饮料" not in caplog.text
    assert "贵州茅台" not in caplog.text


def test_health_does_not_expose_context(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    _context(engine, trigger_id)
    text = json.dumps(engine.health_dict(), ensure_ascii=False)
    assert "600519" not in text
    assert "food" not in text
    assert "context" not in text


def test_context_unknown_trigger_returns_none(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert engine.trigger_context(999) is None


def test_context_embedded_trigger_is_marked_ready(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    _, trigger_id = _trigger(engine)
    context = _context(engine, trigger_id)["context"]
    assert context["trigger"]["context_ready"] is True
    assert context["trigger"]["judged"] is False
