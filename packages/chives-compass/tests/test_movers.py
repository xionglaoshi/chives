"""Contract v1.2: all-A mover lists (parse, filter, sort, cache, persistence)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from chives_compass.calc import movers as movers_calc
from chives_compass.engine import Engine
from chives_compass.gateway import SourceError
from chives_compass.models import CN_TZ, MoverRow
from chives_compass.server import start_server, stop_server
from chives_compass.sources.gateway import MoversSource
from tests.support import FakeClient, mover_row, movers_payload
from tests.test_engine import OPEN, make_engine

FAILED_STATE = datetime(2026, 11, 3, 22, 0, tzinfo=CN_TZ)


def payload(rows):
    return {"data": {"total": len(rows), "diff": rows}}


def row(code, name="测试股", price=10.0, change=1.0, amount=1e8, turnover=1.0, industry="行业"):
    return mover_row(code, name, price, change, amount, turnover, industry)


def movers_calls(engine):
    return [
        call
        for call in engine.client.calls
        if call[0] == "eastmoney"
        and call[1] == "/api/qt/clist/get"
        and str(call[2].get("fs", "")).startswith(("m:0+t:6", "m:1+t:2"))
    ]


@contextmanager
def serve(engine):
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        stop_server(httpd, thread)


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# parsing / code normalisation
# ---------------------------------------------------------------------------
def test_default_filters_exclude_st_and_new():
    rows = [
        row("600001", "正常股", change=1.0),
        row("600002", "ST摘帽", change=2.0),
        row("600003", "*ST退市", change=3.0),
        row("600004", "N新股", change=44.0),
        row("600005", "C次新", change=10.0),
        row("600006", "异常老股", change=50.0),
    ]
    kept = movers_calc.filter_movers(_rows(rows))
    assert [item.code for item in kept] == ["600001.SH"]


def _rows(rows):
    return [
        MoverRow(
            code=movers_calc.normalize_stock_code(str(item.get("f12"))) or str(item.get("f12")),
            name=str(item.get("f14") or ""),
            price=item.get("f2"),
            change_pct=item.get("f3"),
            amount_yuan=item.get("f6"),
            turnover_pct=item.get("f8"),
            industry=item.get("f100"),
        )
        for item in rows
    ]


def test_include_st_keeps_st_but_not_new():
    rows = _rows([row("600002", "ST摘帽", change=2.0), row("600004", "N新股", change=44.0)])
    kept = movers_calc.filter_movers(rows, include_st=True)
    assert [item.code for item in kept] == ["600002.SH"]


def test_include_new_keeps_name_prefix_and_abnormal_move():
    rows = _rows(
        [
            row("600004", "N新股", change=44.0),
            row("600005", "C次新", change=10.0),
            row("600006", "异常老股", change=50.0),
        ]
    )
    kept = movers_calc.filter_movers(rows, include_new=True)
    assert [item.code for item in kept] == ["600004.SH", "600005.SH", "600006.SH"]


def test_abnormal_move_on_wide_limit_board_is_not_new():
    rows = _rows([row("300006", "正常创业", change=44.0), row("688006", "正常科创", change=44.0)])
    kept = movers_calc.filter_movers(rows)
    assert [item.code for item in kept] == ["300006.SZ", "688006.SH"]


def test_beijing_excluded_by_default_and_kept_with_flag():
    rows = _rows([row("920627", "力王股份", change=17.5), row("600519", "贵州茅台", change=1.0)])
    assert [item.code for item in movers_calc.filter_movers(rows)] == ["600519.SH"]
    assert [item.code for item in movers_calc.filter_movers(rows, include_bj=True)] == [
        "920627.BJ",
        "600519.SH",
    ]


# ---------------------------------------------------------------------------
# sorting / limit
# ---------------------------------------------------------------------------
def test_sort_gainers_descending():
    rows = _rows([row("600001", change=1.0), row("600002", change=5.0), row("600003", change=-2.0)])
    assert [item.code for item in movers_calc.sort_movers(rows, "gainers")] == [
        "600002.SH",
        "600001.SH",
        "600003.SH",
    ]


def test_sort_losers_ascending():
    rows = _rows([row("600001", change=1.0), row("600002", change=5.0), row("600003", change=-2.0)])
    assert [item.code for item in movers_calc.sort_movers(rows, "losers")] == [
        "600003.SH",
        "600001.SH",
        "600002.SH",
    ]


def test_sort_active_by_amount_descending():
    rows = _rows(
        [
            row("600001", amount=5e8),
            row("600002", amount=5e9),
            row("600003", amount=1e9),
        ]
    )
    assert [item.code for item in movers_calc.sort_movers(rows, "active")] == [
        "600002.SH",
        "600003.SH",
        "600001.SH",
    ]


def test_sort_ties_break_on_code():
    rows = _rows([row("600003", change=1.0), row("600001", change=1.0), row("600002", change=1.0)])
    assert [item.code for item in movers_calc.sort_movers(rows, "gainers")] == [
        "600001.SH",
        "600002.SH",
        "600003.SH",
    ]


def test_select_applies_filters_then_limit():
    rows = _rows(
        [
            row("600001", "ST一", change=9.0),
            row("600002", "正常一", change=8.0),
            row("600003", "正常二", change=7.0),
            row("600004", "正常三", change=6.0),
        ]
    )
    selected = movers_calc.select_movers(rows, "gainers", 2)
    assert [item.code for item in selected] == ["600002.SH", "600003.SH"]


# ---------------------------------------------------------------------------
# engine endpoint
# ---------------------------------------------------------------------------
def test_engine_default_excludes_st_and_assigns_ranks(tmp_path):
    rows = [
        row("600001", "ST一", change=9.0),
        row("300750", "宁德时代", change=2.5, amount=2e9),
        row("600519", "贵州茅台", change=1.2, amount=1e9),
        row("600002", "N新股", change=44.0),
    ]
    engine = make_engine(tmp_path, movers=rows)
    engine.tick(OPEN)
    response = engine.movers_dict("gainers", 10)
    assert response["ok"] is True
    assert [item["code"] for item in response["rows"]] == ["300750.SZ", "600519.SH"]
    assert [item["rank"] for item in response["rows"]] == [1, 2]
    assert response["filters"] == {
        "include_st": False,
        "include_new": False,
        "include_bj": False,
    }
    assert all("turnover_pct" in item and "industry" in item for item in response["rows"])


def test_engine_include_flags_expand(tmp_path):
    rows = [
        row("600001", "ST一", change=9.0),
        row("920627", "力王股份", change=17.5),
        row("600002", "N新股", change=44.0),
        row("600519", "贵州茅台", change=1.2),
    ]
    engine = make_engine(tmp_path, movers=rows)
    engine.tick(OPEN)
    response = engine.movers_dict(
        "gainers", 20, include_st=True, include_new=True, include_bj=True
    )
    assert [item["code"] for item in response["rows"]] == [
        "600002.SH",
        "920627.BJ",
        "600001.SH",
        "600519.SH",
    ]
    assert response["filters"]["include_bj"] is True


def test_engine_kinds(tmp_path):
    rows = [
        row("600001", change=5.0, amount=1e9),
        row("600002", change=-5.0, amount=5e9),
    ]
    engine = make_engine(tmp_path, movers=rows)
    engine.tick(OPEN)
    assert [item["code"] for item in engine.movers_dict("gainers", 5)["rows"]] == [
        "600001.SH",
        "600002.SH",
    ]
    assert [item["code"] for item in engine.movers_dict("losers", 5)["rows"]] == [
        "600002.SH",
        "600001.SH",
    ]
    assert [item["code"] for item in engine.movers_dict("active", 5)["rows"]] == [
        "600002.SH",
        "600001.SH",
    ]


@pytest.mark.parametrize("kind", ["", "top", "GAINERS", "all"])
def test_engine_bad_kind(tmp_path, kind):
    engine = make_engine(tmp_path)
    response = engine.movers_dict(kind, 10)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


@pytest.mark.parametrize("limit", [0, 4, 21, 100, "10", 10.5, True])
def test_engine_bad_limit(tmp_path, limit):
    engine = make_engine(tmp_path)
    response = engine.movers_dict("gainers", limit)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_engine_limit_applied(tmp_path):
    rows = [row(f"6000{index:02d}", change=float(index)) for index in range(30)]
    engine = make_engine(tmp_path, movers=rows)
    engine.tick(OPEN)
    response = engine.movers_dict("gainers", 5)
    assert len(response["rows"]) == 5
    assert [item["rank"] for item in response["rows"]] == [1, 2, 3, 4, 5]


def test_engine_failed_source_returns_reason(tmp_path):
    engine = make_engine(tmp_path, movers_fail=True)
    engine.tick(OPEN)
    response = engine.movers_dict("gainers", 10)
    assert response["ok"] is True
    assert response["rows"] == []
    assert response["reason"]


def test_engine_keeps_last_value_on_failure(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    before = engine.movers_dict("gainers", 10)["rows"]

    def boom(*args, **kwargs):
        raise SourceError("upstream_http", "down")

    monkeypatch.setattr(engine.movers_source, "fetch", boom)
    engine.poll_movers(OPEN + timedelta(seconds=20))
    after = engine.movers_dict("gainers", 10)
    assert after["rows"] == before
    assert after["rows"]


def test_engine_persists_and_restores(tmp_path):
    first = make_engine(tmp_path)
    first.tick(OPEN)
    expected = first.movers_dict("gainers", 10)["rows"]
    second = make_engine(tmp_path, movers_fail=True)
    restored = second.movers_dict("gainers", 10)
    assert restored["rows"] == expected


def test_engine_cache_ttl(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    calls = len(movers_calls(engine))
    engine.poll_movers(OPEN + timedelta(seconds=10))
    assert len(movers_calls(engine)) == calls
    engine.poll_movers(OPEN + timedelta(seconds=16))
    assert len(movers_calls(engine)) == calls + 3


def test_engine_include_bj_queries_beijing_segment(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    before = len(movers_calls(engine))
    response = engine.movers_dict("gainers", 10, include_bj=True)
    assert response["ok"] is True
    added = movers_calls(engine)[before:]
    assert added and all("m:0+t:81" in str(call[2].get("fs")) for call in added)


def test_engine_closed_returns_last_value_and_state_note(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(FAILED_STATE)
    response = engine.movers_dict("gainers", 10)
    assert response["ok"] is True
    assert response["rows"]
    assert response["stale"] is False
    assert response["state_note"]


def test_movers_health_ok(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    health = engine.health_dict()
    assert health["sources"]["movers"]["ok"] is True
    assert health["sources"]["movers"]["age_s"] is not None


def test_movers_health_failure(tmp_path):
    engine = make_engine(tmp_path, movers_fail=True)
    engine.tick(OPEN)
    health = engine.health_dict()
    assert health["sources"]["movers"]["ok"] is False
    assert health["sources"]["movers"]["last_error"]


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------
def test_http_movers_default(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        response = get_json(base, "/movers")
    assert response["ok"] is True
    assert response["kind"] == "gainers"
    assert len(response["rows"]) == 3
    assert set(response["rows"][0]) >= {"rank", "code", "name", "price", "change_pct", "amount_yuan"}


@pytest.mark.parametrize(
    "query",
    [
        "?kind=top",
        "?limit=4",
        "?limit=21",
        "?limit=abc",
        "?include_st=2",
        "?include_bj=x",
    ],
)
def test_http_movers_bad_request(tmp_path, query):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        response = get_json(base, "/movers" + query)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_http_movers_flags(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        response = get_json(base, "/movers?kind=active&limit=5&include_st=1&include_new=1&include_bj=1")
    assert response["ok"] is True
    assert response["kind"] == "active"
    assert response["filters"] == {"include_st": True, "include_new": True, "include_bj": True}


def test_http_movers_unknown_path_not_shadowed(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(base + "/movers/extra", timeout=5)
    assert info.value.code == 404
