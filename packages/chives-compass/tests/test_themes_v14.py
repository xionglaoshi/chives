from __future__ import annotations

import json

import pytest

from chives_compass.gateway import SourceError
from tests.support import FakeClient, board_list_payload, board_row
from tests.test_engine import OPEN, make_engine


def concept_rows():
    return [
        board_row("BK1001", "人工智能", 5.0, 9e9, 50, 5, leader_code="600000",
                  leader_name="龙头A", leader_change_pct=10.0, stamp=1793691570),
        board_row("BK1002", "昨日涨停", 4.0, 8e9, 40, 10, leader_code="600001",
                  leader_name="龙头B", leader_change_pct=9.0, stamp=1793691570),
        board_row("BK1003", "机器人", 3.0, 7e9, 30, 20, leader_code="300001",
                  leader_name="龙头C", leader_change_pct=8.0, stamp=1793691570),
    ]


def concept_engine(tmp_path, rows=None, fail=False, sort_seen=None):
    engine = make_engine(tmp_path)
    rows = concept_rows() if rows is None else rows

    def reader(path, params):
        if fail:
            raise SourceError("upstream_http", "down")
        if sort_seen is not None:
            sort_seen.append((params.get("fs"), params.get("fid"), params.get("po")))
        return board_list_payload(rows)

    engine.client.routes.insert(0, ("eastmoney", "/api/qt/clist/get", reader))
    return engine


def test_themes_filters_yesterday_rows(tmp_path):
    engine = concept_engine(tmp_path)
    payload = engine.themes_dict("concept", 10, "change")
    assert payload["ok"] is True
    names = [row["name"] for row in payload["rows"]]
    assert names == ["人工智能", "机器人"]


def test_themes_rank_is_contiguous(tmp_path):
    engine = concept_engine(tmp_path)
    rows = engine.themes_dict("concept", 10, "change")["rows"]
    assert [row["rank"] for row in rows] == [1, 2]


def test_themes_row_fields(tmp_path):
    engine = concept_engine(tmp_path)
    row = engine.themes_dict("concept", 10, "change")["rows"][0]
    assert set(row) == {
        "rank", "code", "name", "change_pct", "amount_yuan", "up_count",
        "down_count", "leader",
    }
    assert row["leader"]["code"] == "600000.SH"


def test_themes_limit(tmp_path):
    engine = concept_engine(tmp_path)
    assert len(engine.themes_dict("concept", 5, "change")["rows"]) <= 5


def test_themes_definition(tmp_path):
    engine = concept_engine(tmp_path)
    assert engine.themes_dict()["definition"] == "新浪概念板块（厂商口径）"


def test_themes_amount_sort_uses_f6(tmp_path):
    seen = []
    engine = concept_engine(tmp_path, sort_seen=seen)
    engine.themes_dict("concept", 5, "amount")
    assert seen[0][0] == "m:90+t:3"


def test_themes_requests_concept_universe(tmp_path):
    seen = []
    engine = concept_engine(tmp_path, sort_seen=seen)
    engine.themes_dict("concept", 5, "change")
    assert seen[0][0] == "m:90+t:3"


@pytest.mark.parametrize("kind", ["industry", "concept2", ""])
def test_themes_bad_kind(tmp_path, kind):
    engine = make_engine(tmp_path)
    assert engine.themes_dict(kind)["error"]["code"] == "bad_request"


@pytest.mark.parametrize("limit", [4, 31, 0, True])
def test_themes_bad_limit(tmp_path, limit):
    engine = make_engine(tmp_path)
    assert engine.themes_dict("concept", limit)["error"]["code"] == "bad_request"


def test_themes_bad_sort(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.themes_dict("concept", 10, "up")["error"]["code"] == "bad_request"


def test_themes_upstream_failure_returns_reason(tmp_path):
    engine = concept_engine(tmp_path, fail=True)
    payload = engine.themes_dict("concept", 10, "change")
    assert payload["ok"] is True and payload["rows"] == []
    assert "reason" in payload


def test_themes_health_reports_block(tmp_path):
    engine = concept_engine(tmp_path)
    engine.themes_dict("concept", 10, "change")
    health = engine.health_dict()
    assert health["sources"]["themes"]["ok"] is True


def test_themes_frozen_state_note(tmp_path):
    engine = concept_engine(tmp_path)
    engine._trading_state = "closed"
    payload = engine.themes_dict("concept", 10, "change")
    assert payload["state_note"] == "休市，显示上一交易时段最后值"
