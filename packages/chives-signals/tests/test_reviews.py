from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from chives_signals.reviews import validate_review
from chives_signals.signals import signal_payload
from chives_signals.validation import ApiError
from tests.support import NOW, at, build_engine

BASE = {
    "date": "2026-11-04",
    "kind": "evening",
    "env": {"label": "strong", "evidence": ["宽度走强"]},
}


def test_minimal_review_valid() -> None:
    payload = validate_review(dict(BASE), now=NOW)
    assert payload["date"] == "2026-11-04"
    assert payload["kind"] == "evening"
    assert payload["env"]["differs_from_rule"] is False
    assert payload["candidates"] == []
    assert payload["themes"] == []
    assert payload["body_markdown"] == ""


def test_review_requires_date_kind_env() -> None:
    for missing in ("date", "kind", "env"):
        payload = dict(BASE)
        payload.pop(missing)
        with pytest.raises(ApiError):
            validate_review(payload, now=NOW)


def test_review_rejects_bad_date_and_kind() -> None:
    with pytest.raises(ApiError):
        validate_review(dict(BASE, date="2026/11/04"), now=NOW)
    with pytest.raises(ApiError):
        validate_review(dict(BASE, kind="noon"), now=NOW)


def test_review_rejects_extra_top_field() -> None:
    with pytest.raises(ApiError) as exc:
        validate_review(dict(BASE, extra=1), now=NOW)
    assert exc.value.code == "unexpected_field"


def test_review_rejects_env_extra_field() -> None:
    with pytest.raises(ApiError):
        validate_review(dict(BASE, env={"label": "strong", "evidence": [], "bogus": 1}), now=NOW)


def test_review_evidence_limit() -> None:
    with pytest.raises(ApiError):
        validate_review(
            dict(BASE, env={"label": "strong", "evidence": ["x"] * 9}), now=NOW
        )


def test_review_evidence_too_long() -> None:
    with pytest.raises(ApiError):
        validate_review(
            dict(BASE, env={"label": "strong", "evidence": ["字" * 81]}), now=NOW
        )


def test_review_candidates_limit() -> None:
    candidates = [
        {"code": "600519.SH", "reason": "x", "card_id": None, "tags": {}}
        for _ in range(6)
    ]
    with pytest.raises(ApiError) as exc:
        validate_review(dict(BASE, candidates=candidates), now=NOW)
    assert exc.value.code == "too_many_candidates"


def test_review_candidate_tags_validated() -> None:
    with pytest.raises(ApiError):
        validate_review(
            dict(BASE, candidates=[{"code": "600519.SH", "reason": "x", "card_id": None, "tags": {"env": "hot"}}]),
            now=NOW,
        )


def test_review_candidate_extra_field() -> None:
    with pytest.raises(ApiError):
        validate_review(
            dict(BASE, candidates=[{"code": "600519.SH", "reason": "x", "card_id": None, "tags": {}, "x": 1}]),
            now=NOW,
        )


def test_review_candidate_account_number_rejected() -> None:
    with pytest.raises(ApiError) as exc:
        validate_review(
            dict(BASE, candidates=[{"code": "600519.SH", "reason": "资金账号 1234567890123", "card_id": None, "tags": {}}]),
            now=NOW,
        )
    assert exc.value.code == "sensitive_text"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("themes", [{"name": "机器人", "note": "x"}] * 7),
        ("events", [{"date": "2026-11-05", "target": "x", "type": "y", "source": "z", "uncertain": False, "note": ""}] * 13),
        ("pending", ["待确认"] * 11),
        ("sources", ["x"] * 11),
        ("checklist", [{"item": "x", "ok": True}] * 13),
    ],
)
def test_review_list_limits(field: str, value) -> None:
    with pytest.raises(ApiError):
        validate_review(dict(BASE, **{field: value}), now=NOW)


def test_review_text_too_long() -> None:
    with pytest.raises(ApiError):
        validate_review(dict(BASE, ladder_note="字" * 201), now=NOW)
    with pytest.raises(ApiError):
        validate_review(dict(BASE, lhb_note="字" * 301), now=NOW)


def test_review_body_too_large() -> None:
    with pytest.raises(ApiError):
        validate_review(dict(BASE, body_markdown="x" * 20001), now=NOW)


def test_review_body_keeps_newlines_but_drops_controls() -> None:
    payload = validate_review(dict(BASE, body_markdown="# 标题\n\n正文\x00"), now=NOW)
    assert "\n" in payload["body_markdown"]
    assert "\x00" not in payload["body_markdown"]


def test_save_and_overwrite_increments_revision(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    first = engine.save_review(dict(BASE))
    assert first["revision"] == 1
    second = engine.save_review(dict(BASE, env={"label": "weak", "evidence": []}))
    assert second["revision"] == 2
    assert second["review"]["env"]["label"] == "weak"


def test_save_generates_review_ready_signal(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(dict(BASE))
    rows = [row for row in engine.store.list_signals(status="all") if row["kind"] == "review_ready"]
    assert len(rows) == 1
    assert rows[0]["decide"] is False
    assert rows[0]["primary"]["action"] == "open_review"
    assert signal_payload(rows[0])["kind_label"] == "复盘已生成"


def test_review_list_and_detail(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(dict(BASE, candidates=[{"code": "600519.SH", "reason": "强", "card_id": None, "tags": {"env": "strong"}}]))
    listing = engine.reviews_payload()
    assert listing["count"] == 1
    assert listing["reviews"][0]["candidate_count"] == 1
    detail = engine.review_detail("2026-11-04", "evening")
    assert detail["untrusted_text"] is True
    assert detail["review"]["untrusted_text"] is True
    assert detail["review"]["candidates"][0]["code"] == "600519.SH"


def test_review_list_kind_filter(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(dict(BASE))
    engine.save_review(dict(BASE, kind="premarket"))
    assert engine.reviews_payload(kind="premarket")["count"] == 1
    assert engine.reviews_payload(kind="evening")["count"] == 1


def test_review_detail_missing(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    assert engine.review_detail("2026-11-04", "evening") is None


def test_review_data_holiday_short_package(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, now=datetime(2026, 11, 7, 10, 0, tzinfo=NOW.tzinfo))
    payload = engine.review_data()
    assert set(payload) == {"ok", "trading_day", "date", "next_trading_day"}
    assert payload["trading_day"] is False
    assert payload["date"] == "2026-11-07"
    assert payload["next_trading_day"] == "2026-11-09"


def test_review_data_trading_day_blocks(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path)
    engine.save_review(dict(BASE))
    payload = engine.review_data()
    assert payload["trading_day"] is True
    assert payload["env"]["regime"] == "strong"
    assert payload["env"]["rule_label"] == "risk_on"
    assert len(payload["market"]["indexes"]) == 6
    assert payload["market"]["amount_yuan"] == 9e11
    assert payload["pool"]["counts"] == {"zt": 60, "zb": 20, "dt": 5}
    assert payload["pool"]["seal_ratio_pct"] == 75.0
    assert payload["pool"]["max_streak"] == 4
    assert payload["pool"]["ladder"][0]["top"][0]["code"] == "600001.SH"
    assert payload["pool"]["history"][0]["date"] == "2026-11-03"
    assert payload["themes"][0]["name"] == "机器人"
    assert payload["sectors"][0]["code"] == "BK0433"
    assert payload["flows"][0]["name"] == "农林牧渔"
    assert payload["holdings"]["private"] is True
    assert payload["holdings"]["positions"][0]["code"] == "600519.SH"
    assert payload["last_review"]["date"] == "2026-11-04"
    assert payload["last_review"]["candidates"] == []
    assert payload["missing"] == []
    assert payload["market"]["amount_vs_prev"] is None


def test_review_data_marks_dead_upstream_missing(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.fail_overview = True
    payload = engine.review_data()
    assert payload["env"]["regime"] is None
    assert any(item["part"] == "env.regime" for item in payload["missing"])
    assert any(item["part"] == "market.overview" for item in payload["missing"])


def test_review_data_marks_pool_missing(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)

    def boom(**kwargs):
        raise RuntimeError("down")

    sources.market_pool = boom
    payload = engine.review_data()
    assert payload["pool"]["counts"] == {"zt": None, "zb": None, "dt": None}
    assert {item["part"] for item in payload["missing"]} >= {"pool.zt", "pool.zb", "pool.dt"}


def test_review_data_holdings_empty(tmp_path: Path) -> None:
    engine, _, _, _ = build_engine(tmp_path, positions=[])
    payload = engine.review_data()
    assert payload["holdings"]["empty"] is True
    assert payload["holdings"]["positions"] == []


def test_review_data_settings_include_adopted_and_suggestions(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    engine.settings.action("single_stock_cap_pct", {"action": "set", "value": 20}, now=clock())
    engine.settings.suggest("theme_cap_pct", {"value": 30, "basis": "b"}, now=clock())
    payload = engine.review_data()
    values = {item["key"]: item for item in payload["settings"]}
    assert values["single_stock_cap_pct"]["value"] == 20
    assert values["theme_cap_pct"]["suggestion"]["value"] == 30


def test_review_data_cards_block(tmp_path: Path) -> None:
    engine, clock, _, _ = build_engine(tmp_path)
    card = engine.create_card(
        {
            "code": "600519.SH",
            "thesis": "测试",
            "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99}],
            "risk": {"stop_price": 90},
            "proposed_by": "user",
            "review_date": "2026-11-04",
        }
    )["card"]
    engine.store.update_card(
        card["id"],
        outcome={"date": "2026-11-04", "triggered_execute": True, "reached_states": ["execute"]},
        now=clock(),
    )
    payload = engine.review_data()
    assert [item["id"] for item in payload["cards"]["open"]] == [card["id"]]
    assert payload["cards"]["yesterday_cards"] == []


def test_review_data_private_error_is_not_leaked(tmp_path: Path) -> None:
    engine, _, _, portfolio = build_engine(tmp_path)
    portfolio.overview = lambda: (_ for _ in ()).throw(RuntimeError("secret holdings"))
    payload = engine.review_data()
    assert payload["holdings"]["empty"] is True
    assert any(item["part"] == "holdings" for item in payload["missing"])


def test_review_data_marks_upstream_business_error_missing(tmp_path: Path) -> None:
    engine, _, sources, _ = build_engine(tmp_path)
    sources.overview_payload = {"ok": False, "error": {"code": "bad_request"}}
    payload = engine.review_data()
    assert payload["env"]["regime"] is None
    assert any(item == {"part": "market.overview", "reason": "bad_request"} for item in payload["missing"])
