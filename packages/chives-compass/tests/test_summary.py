"""Contract v1.2: deterministic /summary headlines and number traceability."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from chives_compass.calc.summary import build_summary, fmt_pct
from chives_compass.models import CN_TZ
from tests.support import board_row, mover_row
from tests.test_engine import INDEXES, OPEN, board_code, make_engine

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def token_values(*texts):
    return [float(match) for text in texts for match in NUMBER.findall(text)]


def summary_engine(tmp_path, **kwargs):
    boards = [
        board_row(
            board_code(index),
            f"行业{chr(0x4E00 + index)}",
            (index - 25) * 0.2,
            1e10,
            up=15,
            down=5,
            flat=0,
            leader_code=f"60{index:02d}00",
            leader_name=f"领涨{chr(0x4E00 + index)}",
            leader_change_pct=5.0,
            price=1000.0 + index,
        )
        for index in INDEXES
    ]
    universe = [
        {"code": board_code(index), "name": f"行业{chr(0x4E00 + index)}"} for index in INDEXES
    ]
    movers = [
        mover_row("600519", "甲股", 10.0, 2.50, 1.2e9),
        mover_row("300750", "乙股", 20.0, 1.10, 9.0e8),
        mover_row("000001", "丙股", 5.0, -1.30, 4.0e8),
    ]
    return make_engine(
        tmp_path, boards=boards, movers=movers, sector_universe=universe, **kwargs
    )


def headline_by_id(summary, headline_id):
    return next(item for item in summary["headlines"] if item["id"] == headline_id)


def candidates(headline_id, overview, sectors, movers):
    breadth = overview.get("breadth") or {}
    if headline_id == "indexes":
        return [
            round(float(row["change_pct"]), 2)
            for row in overview["indexes"]
            if row["code"] in {"000001.SH", "399001.SZ", "399006.SZ"}
            and row.get("change_pct") is not None
        ]
    if headline_id == "breadth":
        values = [float(breadth["up"]), float(breadth["down"])]
        if breadth.get("up_ratio") is not None:
            values.append(round(float(breadth["up_ratio"]), 2))
        if breadth.get("limit_up") is not None:
            values.append(float(breadth["limit_up"]))
        if breadth.get("amount_yuan") is not None:
            values.append(round(float(breadth["amount_yuan"]) / 1e8, 2))
        return values
    if headline_id == "sectors":
        return [
            round(float(row["change_pct"]), 2)
            for row in sectors["rows"]
            if row.get("change_pct") is not None and row.get("member_count", 0) >= 10
        ]
    rows = movers.get("rows") or []
    values = [
        float(breadth.get(key))
        for key in ("limit_up", "limit_down", "broken", "max_streak")
        if breadth.get(key) is not None
    ]
    if rows and rows[0].get("change_pct") is not None:
        values.append(round(float(rows[0]["change_pct"]), 2))
    return values


def overview_payload():
    return {
        "ok": True,
        "indexes": [
            {"code": "000001.SH", "name": "上证指数", "change_pct": -0.5},
            {"code": "399001.SZ", "name": "深证成指", "change_pct": -0.8},
            {"code": "399006.SZ", "name": "创业板指", "change_pct": -1.0},
        ],
        "breadth": {
            "up": 1800,
            "down": 2200,
            "up_ratio": 0.45,
            "limit_up": 30,
            "limit_down": 5,
            "broken": 10,
            "max_streak": 4,
            "amount_yuan": 8.2e11,
        },
    }


def sectors_payload():
    return {
        "ok": True,
        "rows": [
            {"code": "BK0001", "name": "电子", "change_pct": 2.1, "member_count": 20},
            {"code": "BK0002", "name": "银行", "change_pct": -1.3, "member_count": 20},
            {"code": "BK0003", "name": "小板块", "change_pct": 9.9, "member_count": 3},
        ],
    }


def movers_payload():
    return {
        "ok": True,
        "rows": [{"code": "600519.SH", "name": "甲股", "change_pct": 10.01}],
    }


def test_build_summary_full_data():
    summary = build_summary(
        overview=overview_payload(),
        sectors=sectors_payload(),
        movers=movers_payload(),
        previous_day={"amount_yuan": 9.5e11, "limit_up": 25},
    )
    assert summary["generated_by"] == "engine"
    assert 3 <= len(summary["headlines"]) <= 5
    assert [item["id"] for item in summary["headlines"]] == [
        "indexes",
        "breadth",
        "sectors",
        "limit",
    ]


def test_build_summary_three_headlines_without_alerts():
    summary = build_summary(
        overview=overview_payload(), sectors=sectors_payload(), movers=movers_payload()
    )
    assert len(summary["headlines"]) == 4


def test_build_summary_omits_missing_blocks():
    summary = build_summary(overview={}, sectors={}, movers={})
    assert summary["headlines"] == []


def test_build_summary_index_only():
    summary = build_summary(
        overview={"indexes": [{"code": "000001.SH", "name": "上证指数", "change_pct": 1.2}]},
        sectors={},
        movers={},
    )
    assert [item["id"] for item in summary["headlines"]] == ["indexes"]
    assert "+1.20%" in summary["headlines"][0]["body"]


def test_build_summary_omits_breadth_without_counts():
    summary = build_summary(
        overview={"breadth": {"up_ratio": 0.4}}, sectors={}, movers={}
    )
    assert summary["headlines"] == []


def test_build_summary_omits_limit_without_limit_up():
    overview = overview_payload()
    overview["breadth"]["limit_up"] = None
    summary = build_summary(overview=overview, sectors=sectors_payload(), movers=movers_payload())
    assert "limit" not in [item["id"] for item in summary["headlines"]]


def test_build_summary_sectors_need_ten_members():
    sectors = {
        "rows": [
            {"code": "BK0001", "name": "电子", "change_pct": 2.1, "member_count": 9},
            {"code": "BK0002", "name": "银行", "change_pct": -1.3, "member_count": 3},
        ]
    }
    summary = build_summary(overview={}, sectors=sectors, movers={})
    assert "sectors" not in [item["id"] for item in summary["headlines"]]


def test_build_summary_previous_day_comparison():
    summary = build_summary(
        overview=overview_payload(),
        sectors=sectors_payload(),
        movers=movers_payload(),
        previous_day={"amount_yuan": 9.5e11, "limit_up": 25},
    )
    body = headline_by_id(summary, "breadth")["body"]
    assert "上一交易日全天 9500.00 亿元" in body
    assert "上一交易日 25 家" in body


def test_build_summary_no_previous_day_no_comparison():
    summary = build_summary(
        overview=overview_payload(), sectors=sectors_payload(), movers=movers_payload()
    )
    body = headline_by_id(summary, "breadth")["body"]
    assert "上一交易日" not in body


def test_build_summary_alert_headline_has_no_digits():
    alerts = [
        {"rule_id": "R2", "object": {"type": "index", "code": "000001.SH", "name": "上证指数"}},
    ]
    summary = build_summary(
        overview=overview_payload(),
        sectors=sectors_payload(),
        movers=movers_payload(),
        alerts=alerts,
    )
    risk = headline_by_id(summary, "risk")
    assert risk["tone"] == "warn"
    assert token_values(risk["title"], risk["body"]) == []
    assert risk["refs"] == [{"type": "index", "code": "000001.SH", "name": "上证指数"}]


def test_build_summary_alert_refs_deduplicated():
    alerts = [
        {"rule_id": "R2", "object": {"type": "index", "code": "000001.SH", "name": "上证指数"}},
        {"rule_id": "R1", "object": {"type": "index", "code": "000001.SH", "name": "上证指数"}},
        {"rule_id": "R1", "object": {"type": "sector", "code": "BK0001", "name": "电子"}},
    ]
    summary = build_summary(overview={}, sectors={}, movers={}, alerts=alerts)
    refs = headline_by_id(summary, "risk")["refs"]
    assert refs == [
        {"type": "index", "code": "000001.SH", "name": "上证指数"},
        {"type": "sector", "code": "BK0001", "name": "电子"},
    ]


def test_build_summary_unknown_alert_rule_is_omitted():
    summary = build_summary(
        overview={}, sectors={}, movers={}, alerts=[{"rule_id": "R9", "object": {}}]
    )
    assert summary["headlines"] == []


def test_build_summary_never_exceeds_five():
    summary = build_summary(
        overview=overview_payload(),
        sectors=sectors_payload(),
        movers=movers_payload(),
        alerts=[{"rule_id": "R1", "object": {"type": "index", "code": "000001.SH", "name": "上证指数"}}],
    )
    assert len(summary["headlines"]) == 5


def test_build_summary_tone_values():
    summary = build_summary(
        overview=overview_payload(), sectors=sectors_payload(), movers=movers_payload()
    )
    tones = {item["id"]: item["tone"] for item in summary["headlines"]}
    assert tones["indexes"] == "down"
    assert tones["breadth"] == "down"
    assert tones["sectors"] == "neutral"
    assert tones["limit"] == "neutral"


def test_fmt_pct():
    assert fmt_pct(-0.5) == "-0.50%"
    assert fmt_pct(0) == "+0.00%"
    assert fmt_pct(None) == ""


# ---------------------------------------------------------------------------
# engine-level traceability
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headline_id", ["indexes", "breadth", "sectors", "limit"])
def test_summary_numbers_traceable(tmp_path, headline_id):
    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    overview = engine.overview_dict()
    sectors = engine.sectors_dict()
    movers = engine.movers_dict("gainers", 10)
    summary = engine.summary_dict()
    headline = headline_by_id(summary, headline_id)
    expected = candidates(headline_id, overview, sectors, movers)
    assert expected
    for value in token_values(headline["title"], headline["body"]):
        assert any(abs(value - candidate) <= 0.011 for candidate in expected), (
            value,
            expected,
            headline,
        )


def test_summary_covers_required_numbers(tmp_path):
    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    overview = engine.overview_dict()
    sectors = engine.sectors_dict()
    summary = engine.summary_dict()
    index_values = token_values(headline_by_id(summary, "indexes")["body"])
    for row in overview["indexes"][:3]:
        assert round(float(row["change_pct"]), 2) in index_values
    breadth_values = token_values(
        headline_by_id(summary, "breadth")["title"],
        headline_by_id(summary, "breadth")["body"],
    )
    assert float(overview["breadth"]["limit_up"]) in breadth_values
    assert round(float(overview["breadth"]["amount_yuan"]) / 1e8, 2) in breadth_values
    sector_values = token_values(
        headline_by_id(summary, "sectors")["title"],
        headline_by_id(summary, "sectors")["body"],
    )
    eligible = [
        row for row in sectors["rows"] if row["member_count"] >= 10 and row["change_pct"] is not None
    ]
    assert round(max(row["change_pct"] for row in eligible), 2) in sector_values
    assert round(min(row["change_pct"] for row in eligible), 2) in sector_values


def test_day_stats_not_recorded_before_open(tmp_path):
    engine = summary_engine(tmp_path)
    engine.tick(datetime(2026, 11, 3, 9, 0, tzinfo=CN_TZ))
    assert engine.store.load_day_stats(date(2026, 11, 3)) is None


def test_summary_uses_previous_day_snapshot(tmp_path):
    engine = summary_engine(tmp_path)
    engine.store.save_day_stats(
        date(2026, 11, 2), amount_yuan=9.5e11, limit_up=25, updated_at=OPEN
    )
    engine.tick(OPEN)
    overview = engine.overview_dict()
    previous = overview["breadth"]["previous_day"]
    assert previous["amount_yuan"] == 9.5e11
    assert previous["limit_up"] == 25
    summary = engine.summary_dict()
    body = headline_by_id(summary, "breadth")["body"]
    assert "上一交易日全天 9500.00 亿元" in body
    assert "上一交易日 25 家" in body


def test_summary_alert_present_from_store(tmp_path):
    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    engine.store.insert_alert(
        ts=OPEN,
        rule_id="R2",
        object_type="index",
        object_code="000001.SH",
        object_name="上证指数",
        severity="L2",
        title="宽度恶化/背离：上涨家数占比 0.45",
        detail="测试告警",
        payload={},
    )
    summary = engine.summary_dict()
    risk = headline_by_id(summary, "risk")
    assert risk["tone"] == "warn"
    assert token_values(risk["title"], risk["body"]) == []


def test_summary_has_no_advice_words(tmp_path):
    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    summary = engine.summary_dict()
    text = " ".join(item["title"] + item["body"] for item in summary["headlines"])
    assert "买入" not in text and "卖出" not in text and "建议" not in text


def test_summary_contract_fields(tmp_path):
    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    payload = engine.summary_dict()
    assert payload["ok"] is True
    assert payload["generated_by"] == "engine"
    assert isinstance(payload["as_of"], str)
    assert isinstance(payload["note"], str)
    for item in payload["headlines"]:
        assert set(item) == {"id", "tone", "title", "body", "refs"}
        assert item["tone"] in {"up", "down", "neutral", "warn"}
        assert isinstance(item["refs"], list)


def test_summary_http_endpoint(tmp_path):
    import json
    import urllib.request

    from chives_compass.server import start_server, stop_server

    engine = summary_engine(tmp_path)
    engine.tick(OPEN)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/summary", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        stop_server(httpd, thread)
    assert payload["ok"] is True and payload["generated_by"] == "engine"
    assert 3 <= len(payload["headlines"]) <= 5
