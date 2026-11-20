"""Contract v1.2: index mini-chart daily fallback (``spark_kind``)."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta

import pytest

from market_watch.gateway import SourceError
from market_watch.models import CN_TZ
from market_watch.sources.gateway import BoardSource
from market_watch.server import start_server, stop_server
from tests.support import FakeClient, board_history_payload
from tests.test_engine import OPEN, make_engine

CLOSED = datetime(2026, 11, 3, 22, 0, tzinfo=CN_TZ)
LUNCH = datetime(2026, 11, 3, 12, 0, tzinfo=CN_TZ)
HOLIDAY = datetime(2026, 11, 7, 10, 30, tzinfo=CN_TZ)


def spark_of(engine, code="000001.SH"):
    row = next(item for item in engine.overview_dict()["indexes"] if item["code"] == code)
    return row["spark"], row["spark_kind"]


def kline_calls(engine):
    return [call for call in engine.client.calls if call[0] == "eastmoney_hist"]


def test_open_uses_intraday(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    points, kind = spark_of(engine)
    assert kind == "intraday"
    assert len(points) == 1


def test_lunch_uses_intraday(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(LUNCH)
    points, kind = spark_of(engine)
    assert kind == "intraday"
    assert points


def test_closed_uses_daily(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    points, kind = spark_of(engine)
    assert kind == "daily"
    assert len(points) == 30


def test_holiday_uses_daily(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(HOLIDAY)
    points, kind = spark_of(engine)
    assert kind == "daily"
    assert len(points) == 30


def test_daily_points_are_sorted_and_finite(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    points, _ = spark_of(engine)
    stamps = [item["t"] for item in points]
    assert stamps == sorted(stamps)
    assert len({item["t"] for item in points}) == len(points)
    assert all(item["p"] > 0 for item in points)
    assert stamps[-1].startswith("2026-10-10")


def test_daily_failure_returns_empty_daily(tmp_path):
    engine = make_engine(tmp_path, daily_fail=True)
    engine.tick(CLOSED)
    points, kind = spark_of(engine)
    assert points == []
    assert kind == "daily"
    assert engine.health_dict()["sources"]["daily_spark"]["ok"] is False


def test_cold_start_fetches_all_six_indexes(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    assert len(kline_calls(engine)) == 6
    health = engine.health_dict()["sources"]["daily_spark"]
    assert health["ok"] is True


def test_daily_spark_cache_ttl(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    calls = len(kline_calls(engine))
    engine.poll_daily_spark(CLOSED + timedelta(seconds=100))
    assert len(kline_calls(engine)) == calls
    engine.poll_daily_spark(CLOSED + timedelta(seconds=301))
    assert len(kline_calls(engine)) == calls + 6


def test_daily_spark_persists_and_restores(tmp_path):
    first = make_engine(tmp_path)
    first.tick(CLOSED)
    expected, _ = spark_of(first)
    second = make_engine(tmp_path, daily_fail=True)
    restored, kind = spark_of(second)
    assert kind == "daily"
    assert restored == expected


def test_daily_spark_keeps_last_value_on_failure(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    before, _ = spark_of(engine)

    def boom(*args, **kwargs):
        raise SourceError("upstream_http", "down")

    monkeypatch.setattr(engine.board_source, "fetch_index_history", boom)
    engine.poll_daily_spark(CLOSED + timedelta(seconds=400))
    after, kind = spark_of(engine)
    assert kind == "daily"
    assert after == before


def test_overview_spark_kind_every_index(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    for row in engine.overview_dict()["indexes"]:
        assert row["spark_kind"] in {"intraday", "daily"}
        assert len(row["spark"]) == 30


def test_fetch_index_history_parses_real_shape():
    client = FakeClient()
    client.add(
        "eastmoney_hist",
        "/api/qt/stock/kline/get",
        json.dumps(
            {
                "rc": 0,
                "data": {
                    "code": "000001",
                    "name": "上证指数",
                    "klines": [
                        "2026-10-30,3605.65,3599.02,3660.21,3595.26,1,1.0",
                        "2026-11-02,3614.31,3638.03,3648.13,3594.77,1,1.0",
                        "2026-11-03,3624.58,3608.10,3624.58,3580.38,1,1.0",
                    ],
                },
            },
            ensure_ascii=False,
        ),
    )
    bars = BoardSource(client).fetch_index_history("000001.SH", OPEN)
    assert [bar.close for bar in bars] == [3599.02, 3638.03, 3608.1]
    assert bars[-1].day.isoformat() == "2026-11-03"
    assert client.calls[-1][1] == "/api/qt/stock/kline/get"


def _boom(path, params):
    raise SourceError("upstream_http", "down")


def test_fetch_index_history_unknown_code():
    client = FakeClient()
    client.add("eastmoney_hist", "/api/qt/stock/kline/get", _boom)
    with pytest.raises(SourceError):
        BoardSource(client).fetch_index_history("999999.SH", OPEN)


def test_fetch_index_history_empty_raises():
    client = FakeClient()
    client.add("eastmoney_hist", "/api/qt/stock/kline/get", json.dumps({"data": {"klines": []}}))
    with pytest.raises(SourceError):
        BoardSource(client).fetch_index_history("399001.SZ", OPEN)


def test_http_overview_spark_kind(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(CLOSED)
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/overview", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        stop_server(httpd, thread)
    assert all(row["spark_kind"] == "daily" for row in payload["indexes"])
    assert all(len(row["spark"]) >= 20 for row in payload["indexes"])
