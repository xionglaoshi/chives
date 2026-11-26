"""Contract v1.3: main-net-inflow rankings (/flows) and the northbound probe."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from chives_compass.calc import flows as flows_calc
from chives_compass.calc import movers as movers_calc
from chives_compass.config import ConfigError, parse_config
from chives_compass.models import CN_TZ, FlowRow
from chives_compass.server import start_server, stop_server
from chives_compass.sources.gateway import FlowSource
from chives_compass.gateway import SourceError
from tests.support import (
    FakeClient,
    flow_row,
    flows_payload,
    northbound_payload,
)
from tests.test_engine import (
    OPEN,
    board_code,
    board_name,
    default_flow_boards,
    make_engine,
)

CLOSED = datetime(2026, 11, 3, 22, 0, tzinfo=CN_TZ)
HOLIDAY = datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ)


FLOW_ORDER = {
    "sector_in": ("f62", 1),
    "sector_out": ("f62", 0),
    "stock_in": ("f62", 1),
    "stock_out": ("f62", 0),
}


def payload(rows):
    return {"data": {"total": len(rows), "diff": rows}}


def _flow_rows(rows, boards: bool = False):
    result = []
    for item in rows:
        raw = str(item.get("f12") or "")
        code = raw if boards or "." in raw else (movers_calc.normalize_stock_code(raw) or raw)
        result.append(
            FlowRow(
                code=code,
                name=str(item.get("f14") or ""),
                main_net_yuan=item.get("f62"),
                main_net_pct=item.get("f184"),
                change_pct=item.get("f3"),
                amount_yuan=item.get("f6"),
            )
        )
    return result


def sector_calls(engine):
    return [
        call
        for call in engine.client.calls
        if call[0] == "eastmoney"
        and call[1] == "/api/qt/clist/get"
        and call[2].get("fid") == "f62"
        and call[2].get("fs") == "m:90+t:2"
    ]


def stock_calls(engine, kind=None):
    return [
        call
        for call in engine.client.calls
        if call[0] == "eastmoney"
        and call[1] == "/api/qt/clist/get"
        and call[2].get("fid") == "f62"
        and str(call[2].get("fs", "")).startswith(("m:0+t:6", "m:1+t:2"))
        and (kind is None or (call[2].get("po") == FLOW_ORDER[kind][1]))
    ]


@contextmanager
def serve(engine):
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        stop_server(httpd, thread)


def get_json(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# parsing / units
# ---------------------------------------------------------------------------
def test_sort_sector_in_descending():
    rows = _flow_rows(
        [flow_row("BK1201", "电子", 3e8), flow_row("BK0478", "有色", 9e8), flow_row("BK0433", "农林", -1e8)],
        boards=True,
    )
    assert [row.code for row in flows_calc.sort_flows(rows, "sector_in")] == [
        "BK0478", "BK1201", "BK0433"
    ]


def test_sort_sector_out_ascending():
    rows = _flow_rows(
        [flow_row("BK1201", "电子", 3e8), flow_row("BK0478", "有色", -9e8), flow_row("BK0433", "农林", 1e7)],
        boards=True,
    )
    assert [row.code for row in flows_calc.sort_flows(rows, "sector_out")] == [
        "BK0478", "BK0433", "BK1201"
    ]


def test_sort_stock_in_puts_missing_value_last():
    rows = _flow_rows(
        [flow_row("600519", "贵州茅台", None), flow_row("600001", "正常", 5e7)]
    )
    assert [row.code for row in flows_calc.sort_flows(rows, "stock_in")] == ["600001.SH", "600519.SH"]


def test_sort_stock_out_puts_missing_value_last():
    rows = _flow_rows(
        [flow_row("600519", "贵州茅台", None), flow_row("600001", "正常", -5e7)]
    )
    assert [row.code for row in flows_calc.sort_flows(rows, "stock_out")] == ["600001.SH", "600519.SH"]


def test_sort_ties_break_on_code():
    rows = _flow_rows(
        [flow_row("600003", "丙", 1e8), flow_row("600001", "甲", 1e8), flow_row("600002", "乙", 1e8)]
    )
    assert [row.code for row in flows_calc.sort_flows(rows, "stock_in")] == [
        "600001.SH", "600002.SH", "600003.SH"
    ]


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        flows_calc.sort_flows([], "sector_sideways")


def test_select_applies_limit():
    rows = _flow_rows([flow_row(f"60000{index}", f"股{index}", float(index)) for index in range(10)])
    assert len(flows_calc.select_flows(rows, "stock_in", 5)) == 5


def test_select_stock_filters_default_exclusions():
    rows = _flow_rows(
        [
            flow_row("600001", "正常股", 1e8),
            flow_row("600002", "ST摘帽", 2e8),
            flow_row("600003", "*ST退市", 3e8),
            flow_row("600004", "N新股", 4e8),
            flow_row("920627", "力王股份", 5e8),
        ]
    )
    assert [row.code for row in flows_calc.select_flows(rows, "stock_in", 20)] == ["600001.SH"]


def test_select_stock_include_flags():
    rows = _flow_rows(
        [
            flow_row("600002", "ST摘帽", 2e8),
            flow_row("600004", "N新股", 4e8),
            flow_row("920627", "力王股份", 5e8),
            flow_row("600001", "正常股", 1e8),
        ]
    )
    selected = flows_calc.select_flows(
        rows, "stock_in", 20, include_st=True, include_new=True, include_bj=True
    )
    assert [row.code for row in selected] == ["920627.BJ", "600004.SH", "600002.SH", "600001.SH"]


def test_select_sector_ignores_stock_filters():
    rows = _flow_rows(
        [flow_row("BK1201", "ST板块", 1e8), flow_row("BK0478", "N板块", 2e8)],
        boards=True,
    )
    assert [row.code for row in flows_calc.select_flows(rows, "sector_in", 20)] == [
        "BK0478", "BK1201"
    ]


# ---------------------------------------------------------------------------
# engine endpoint
# ---------------------------------------------------------------------------
def test_engine_sector_in_forwards_gateway_taxonomy(tmp_path):
    boards = default_flow_boards() + [
        flow_row("BK8000", "杂行业", 9e9),
        flow_row("BK8001", "杂行业2", 8e9),
    ]
    engine = make_engine(tmp_path, flow_boards=boards)
    engine.tick(OPEN)
    response = engine.flows_dict("sector_in", 10)
    assert response["ok"] is True
    assert len(response["rows"]) == 10
    nets = [row["main_net_yuan"] for row in response["rows"]]
    assert nets == sorted(nets, reverse=True)
    assert response["rows"][0]["code"] == "BK8000"
    assert response["taxonomy"] == "gateway_industry"


def test_engine_sector_out_order(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    response = engine.flows_dict("sector_out", 5)
    nets = [row["main_net_yuan"] for row in response["rows"]]
    assert nets == sorted(nets)
    assert response["rows"][0]["code"] == board_code(10)
    assert [row["rank"] for row in response["rows"]] == [1, 2, 3, 4, 5]


def test_engine_stock_in_default_filters(tmp_path):
    rows = [
        flow_row("600001", "正常股", 9e8),
        flow_row("600002", "ST摘帽", 8e8),
        flow_row("600003", "N新股", 7e8),
        flow_row("920627", "力王股份", 6e8),
    ]
    engine = make_engine(tmp_path, flows=rows)
    engine.tick(OPEN)
    response = engine.flows_dict("stock_in", 20)
    assert [row["code"] for row in response["rows"]] == ["600001.SH"]
    assert response["filters"] == {
        "include_st": False,
        "include_new": False,
        "include_bj": False,
    }


def test_engine_stock_out_order(tmp_path):
    rows = [
        flow_row("600001", "正常一", 1e8),
        flow_row("600002", "正常二", -5e8),
        flow_row("600003", "正常三", -2e8),
    ]
    engine = make_engine(tmp_path, flows=rows)
    engine.tick(OPEN)
    response = engine.flows_dict("stock_out", 20)
    assert [row["code"] for row in response["rows"]] == ["600002.SH", "600003.SH", "600001.SH"]


def test_engine_include_bj_queries_beijing_segment(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    before = len(stock_calls(engine))
    response = engine.flows_dict("stock_in", 10, include_bj=True)
    added = stock_calls(engine)[before:]
    assert response["ok"] is True
    assert added and "m:0+t:81" in str(added[-1][2]["fs"])
    assert any(row["code"].endswith(".BJ") for row in response["rows"])


def test_engine_include_st_and_new(tmp_path):
    rows = [
        flow_row("600001", "ST摘帽", 9e8),
        flow_row("600002", "N新股", 8e8),
        flow_row("600003", "正常股", 7e8),
    ]
    engine = make_engine(tmp_path, flows=rows)
    engine.tick(OPEN)
    default = engine.flows_dict("stock_in", 20)
    assert [row["code"] for row in default["rows"]] == ["600003.SH"]
    expanded = engine.flows_dict("stock_in", 20, include_st=True, include_new=True)
    assert [row["code"] for row in expanded["rows"]] == [
        "600001.SH", "600002.SH", "600003.SH"
    ]


def test_engine_limit_applied(tmp_path):
    rows = [flow_row(f"6000{index:02d}", f"股{index}", float(index)) for index in range(30)]
    engine = make_engine(tmp_path, flows=rows)
    engine.tick(OPEN)
    response = engine.flows_dict("stock_in", 5)
    assert len(response["rows"]) == 5
    assert [row["rank"] for row in response["rows"]] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("kind", ["", "top", "SECTOR_IN", "sector", "gainers"])
def test_engine_bad_kind(tmp_path, kind):
    engine = make_engine(tmp_path)
    response = engine.flows_dict(kind, 10)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


@pytest.mark.parametrize("limit", [0, 4, 21, 100, "10", 10.5, True])
def test_engine_bad_limit(tmp_path, limit):
    engine = make_engine(tmp_path)
    response = engine.flows_dict("sector_in", limit)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_engine_definition_always_in_ok_payload(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    for kind in flows_calc.FLOW_KINDS:
        payload_ = engine.flows_dict(kind, 10)
        assert payload_["ok"] is True
        assert payload_["definition"] == "新浪资金流（个股主力=超大单 r0_net，行业/概念为净流入；厂商口径，仅作辅助参考）"


def test_engine_failed_source_returns_reason(tmp_path):
    engine = make_engine(tmp_path, flows_fail=True)
    engine.tick(OPEN)
    response = engine.flows_dict("sector_in", 10)
    assert response["ok"] is True
    assert response["rows"] == []
    assert response["reason"]
    assert "definition" in response


def test_engine_closed_returns_last_value(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    response = engine.flows_dict("stock_in", 10)
    assert response["rows"]
    assert response["stale"] is False
    assert response["state_note"]


def test_engine_holiday_cold_start_fetches(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(HOLIDAY)
    assert sector_calls(engine)
    assert len(stock_calls(engine)) == 2
    assert engine.flows_dict("sector_in", 10)["rows"]


def test_engine_persists_and_restores(tmp_path):
    first = make_engine(tmp_path)
    first.tick(OPEN)
    expected = first.flows_dict("stock_in", 10)["rows"]
    assert expected
    second = make_engine(tmp_path, flows_fail=True)
    restored = second.flows_dict("stock_in", 10)
    assert restored["rows"] == expected


def test_engine_cache_ttl(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    calls = len(sector_calls(engine))
    engine.poll_flows(OPEN + timedelta(seconds=10))
    assert len(sector_calls(engine)) == calls
    engine.poll_flows(OPEN + timedelta(seconds=21))
    assert len(sector_calls(engine)) == calls + 1


def test_engine_keeps_last_value_on_failure(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    before = engine.flows_dict("stock_in", 10)["rows"]
    assert before

    def boom(*args, **kwargs):
        raise SourceError("upstream_http", "down")

    monkeypatch.setattr(engine.flow_source, "fetch_stock_flows", boom)
    engine.poll_flows(OPEN + timedelta(seconds=25))
    after = engine.flows_dict("stock_in", 10)
    assert after["rows"] == before


def test_flows_health_ok(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    health = engine.health_dict()
    assert health["sources"]["flows"]["ok"] is True
    assert health["sources"]["flows"]["age_s"] is not None


def test_flows_health_failure(tmp_path):
    engine = make_engine(tmp_path, flows_fail=True)
    engine.tick(OPEN)
    health = engine.health_dict()
    assert health["sources"]["flows"]["ok"] is False
    assert health["sources"]["flows"]["last_error"]


# ---------------------------------------------------------------------------
# northbound probe
# ---------------------------------------------------------------------------
def test_engine_northbound_available(tmp_path):
    engine = make_engine(tmp_path)
    response = engine.northbound_dict()
    assert response["ok"] is True
    assert response["available"] is False
    assert "净流入" in response["reason"]


def test_engine_northbound_unavailable(tmp_path):
    engine = make_engine(tmp_path)
    response = engine.northbound_dict()
    assert response["ok"] is True
    assert response["available"] is False
    assert response["reason"]


def test_engine_northbound_no_numbers_when_unavailable(tmp_path):
    engine = make_engine(tmp_path)
    response = engine.northbound_dict()
    assert "net_yuan" not in response and "as_of" not in response


def test_engine_northbound_upstream_error(tmp_path):
    engine = make_engine(tmp_path, northbound_fail=True)
    response = engine.northbound_dict()
    assert response["ok"] is True
    assert response["available"] is False
    assert "净流入" in response["reason"]


def test_engine_northbound_cached(tmp_path):
    engine = make_engine(tmp_path)
    before = len(engine.client.calls)
    engine.northbound_dict()
    engine.northbound_dict()
    assert len(engine.client.calls) == before


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------
def test_http_flows_default(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        status, response = get_json(base, "/flows")
    assert status == 200 and response["ok"] is True
    assert response["kind"] == "sector_in"
    assert len(response["rows"]) == 10
    assert response["definition"] == "新浪资金流（个股主力=超大单 r0_net，行业/概念为净流入；厂商口径，仅作辅助参考）"
    assert response["source"] == "gateway.market_fund_flow"
    assert set(response["rows"][0]) == {
        "rank", "code", "name", "main_net_yuan", "main_net_pct", "change_pct", "amount_yuan"
    }


@pytest.mark.parametrize("kind", ["sector_in", "sector_out", "stock_in", "stock_out"])
def test_http_flows_four_kinds(tmp_path, kind):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        status, response = get_json(base, f"/flows?kind={kind}&limit=5")
    assert status == 200 and response["ok"] is True
    assert response["kind"] == kind
    assert len(response["rows"]) <= 5


@pytest.mark.parametrize(
    "query",
    [
        "?kind=top",
        "?kind=sector_sideways",
        "?limit=4",
        "?limit=21",
        "?limit=abc",
        "?limit=0",
        "?include_st=2",
        "?include_bj=x",
    ],
)
def test_http_flows_bad_request(tmp_path, query):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        status, response = get_json(base, "/flows" + query)
    assert status == 400
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_http_flows_northbound(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        status, response = get_json(base, "/flows/northbound")
    assert status == 200
    assert response["ok"] is True
    assert response["available"] is False
    assert response["reason"]


def test_http_flows_unknown_subpath_404(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    with serve(engine) as base:
        status, response = get_json(base, "/flows/extra")
    assert status == 404
    assert response["ok"] is False


def test_config_flows_seconds_default_and_override():
    assert parse_config({}).polling.flows_seconds == 30.0
    assert parse_config({"polling": {"flows_seconds": 45}}).polling.flows_seconds == 45.0
    with pytest.raises(ConfigError):
        parse_config({"polling": {"flows_seconds": 0}})
