from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from market_watch.config import parse_config
from market_watch.engine import Engine
from market_watch.gateway import SourceError
from market_watch.models import CN_TZ
from market_watch.store import AlertStore
from tests.support import (
    FakeClient,
    board_history_payload,
    board_list_payload,
    board_row,
    board_trend_payload,
    breadth_payload,
    flow_row,
    flows_payload,
    member_row,
    members_payload,
    mover_row,
    movers_payload,
    northbound_payload,
    tencent_payload,
)

OPEN = datetime(2026, 11, 3, 10, 30, tzinfo=CN_TZ)
INDEXES = list(range(10, 41))


def default_movers(include_bj: bool = False) -> list[dict]:
    rows = [
        mover_row("600519", "贵州茅台", 1500.0, 1.23, 1.2e9, turnover_pct=0.4, industry="白酒"),
        mover_row("300750", "宁德时代", 250.0, 2.50, 2.4e9, turnover_pct=1.1, industry="电池"),
        mover_row("000001", "平安银行", 10.0, -0.50, 5.0e8, turnover_pct=0.8, industry="银行"),
    ]
    if include_bj:
        rows.append(mover_row("920627", "力王股份", 18.9, 3.30, 2.0e8, industry="电池"))
    return rows


def default_flows(include_bj: bool = False) -> list[dict]:
    rows = [
        flow_row("600519", "贵州茅台", 1.2e8, change_pct=1.23, amount_yuan=1.2e9),
        flow_row("300750", "宁德时代", -2.4e8, change_pct=2.50, amount_yuan=2.4e9),
        flow_row("000001", "平安银行", 5.0e7, change_pct=-0.50, amount_yuan=5.0e8),
    ]
    if include_bj:
        rows.append(flow_row("920627", "力王股份", 2.0e7, change_pct=3.30, amount_yuan=2.0e8))
    return rows


def default_flow_boards() -> list[dict]:
    return [
        flow_row(
            board_code(index),
            board_name(index),
            (index - 25) * 1e8,
            change_pct=(index - 25) * 0.2,
            amount_yuan=1e10,
        )
        for index in INDEXES
    ]


def board_code(index: int) -> str:
    return f"BK{9000 + index}"


def board_name(index: int) -> str:
    return f"行业{index}"


def clock_at(moment):
    holder = {"now": moment}
    return holder, lambda: holder["now"]


class TencentFeed:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.requests = 0

    def set(self, code, name, price, prev, amount, limit_up=None):
        self.rows[code] = dict(
            code=code, name=name, price=price, prev_close=prev, amount_yuan=amount,
            limit_up=limit_up,
        )

    def __call__(self, path, params):
        self.requests += 1
        symbols = path.split("=", 1)[1].split(",")
        rows = []
        for symbol in symbols:
            prefix, digits = symbol[:2], symbol[2:]
            suffix = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[prefix]
            row = self.rows.get(f"{digits}.{suffix}")
            if row:
                rows.append(row)
        return tencent_payload(rows)


def make_feed(
    index_changes=None,
    watch_stock_change=-0.5,
    watch_stock_amount=2e8,
):
    feed = TencentFeed()
    changes = index_changes or {
        "000001.SH": -0.5,
        "399001.SZ": -0.8,
        "399006.SZ": -1.0,
        "000300.SH": -0.2,
        "000852.SH": -0.9,
        "000688.SH": -1.2,
    }
    prev = {
        "000001.SH": 3638.03,
        "399001.SZ": 11010.68,
        "399006.SZ": 2458.70,
        "000300.SH": 4016.92,
        "000852.SH": 6300.0,
        "000688.SH": 1200.0,
    }
    amounts = {
        "000001.SH": 5e11,
        "399001.SZ": 5e11,
        "399006.SZ": 2e11,
        "000300.SH": 3e11,
        "000852.SH": 1.5e11,
        "000688.SH": 0.8e11,
    }
    names = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000300.SH": "沪深300",
        "000852.SH": "中证1000",
        "000688.SH": "科创50",
    }
    for code, change in changes.items():
        feed.set(code, names[code], prev[code] * (1 + change / 100), prev[code], amounts[code])
    feed.set("002553.SZ", "南方轴承", 10.0 * (1 + watch_stock_change / 100), 10.0, watch_stock_amount)
    feed.set("601099.SH", "太平洋", 4.0, 4.0, 1e8)
    return feed


def make_boards(member_count: int = 20, member_change: float = 1.0):
    return [
        board_row(
            board_code(index),
            board_name(index),
            (index - 25) * 0.2,
            1e10,
            up=max(0, member_count - 5),
            down=min(5, member_count),
            flat=0,
            leader_code=f"60{index:02d}00",
            leader_name=f"领涨{index}",
            leader_change_pct=5.0,
            price=1000.0 + index,
        )
        for index in INDEXES
    ]


def board_history_closes() -> list[float]:
    return [1000.0 + index for index in range(40)]


def make_config(tmp_path, watchlist_file=None, **overrides):
    data = {
        "api": {"host": "127.0.0.1", "port": 8866},
        "runtime": {"db_path": str(tmp_path / "market.db")},
        "calendar": {"source": "weekdays"},
        "sector_universe": [
            {"code": board_code(index), "name": board_name(index)} for index in INDEXES
        ],
        "sources": {"sw": {"enabled": False}},
        "polling": {"index_seconds": 3, "breadth_seconds": 20, "sw_l1_seconds": 20,
                    "limit_pool_seconds": 40, "members_seconds": 600, "history_seconds": 300},
        "limits": {"alert_max_per_hour": 10},
        "suppression": {"enabled": True, "open_minutes": 15, "close_minutes": 5},
    }
    if watchlist_file:
        data["watchlist_file"] = str(watchlist_file)
    data.update(overrides)
    return parse_config(data, base_dir=tmp_path)


def make_engine(tmp_path, feed=None, boards=None, breadth=(900, 1100, 50), clock=None,
                member_count=20, member_change=1.0, closes=None, client=None,
                movers=None, movers_fail=False, daily_fail=False,
                flows=None, flow_boards=None, flows_fail=False,
                northbound=None, northbound_fail=False, **cfg):
    feed = feed or make_feed()
    boards = boards if boards is not None else make_boards(member_count=member_count,
                                                           member_change=member_change)
    closes = closes if closes is not None else board_history_closes()
    if client is None:
        client = FakeClient()
        client.add("tencent", "/q=", feed)
        client.add("eastmoney", "/api/qt/ulist.np/get", breadth_payload(breadth, breadth))

        def board_clist(path, params):
            fs = str(params.get("fs", ""))
            if params.get("fid") == "f62":
                if flows_fail:
                    raise SourceError("upstream_http", "down")
                if fs == "m:90+t:2":
                    rows = default_flow_boards() if flow_boards is None else list(flow_boards)
                    page = int(params.get("pn", 1))
                    size = int(params.get("pz", 100))
                    return flows_payload(rows[(page - 1) * size:page * size], len(rows))
                rows = default_flows(include_bj="m:0+t:81" in fs) if flows is None else list(flows)
                rows = sorted(
                    rows,
                    key=lambda item: (item.get("f62") is None, item.get("f62") or 0.0, item["f12"]),
                    reverse=params.get("po") == 1,
                )
                return flows_payload(rows)
            if fs.startswith(("m:0+t:6", "m:1+t:2")):
                if movers_fail:
                    raise SourceError("upstream_http", "down")
                rows = default_movers(include_bj="m:0+t:81" in fs) if movers is None else list(movers)
                return movers_payload(rows)
            if fs.startswith("b:"):
                code = fs[2:]
                index = int(code[-2:]) if code[-2:].isdigit() else 10
                rows = [
                    member_row(
                        f"60{index:02d}{member:02d}",
                        f"M{index}-{member}",
                        10.0 * (1 + member_change / 100),
                        member_change,
                        5e7,
                    )
                    for member in range(member_count)
                ]
                return members_payload(rows, member_count)
            page = int(params.get("pn", 1))
            return board_list_payload(boards if page == 1 else [])

        client.add("eastmoney", "/api/qt/clist/get", board_clist)
        if northbound_fail:
            def northbound_reader(path, params):
                raise SourceError("upstream_http", "down")

            client.add("eastmoney", "/api/qt/kamt/get", northbound_reader)
        else:
            client.add(
                "eastmoney",
                "/api/qt/kamt/get",
                northbound if northbound is not None else northbound_payload("2026-11-03"),
            )
        client.add(
            "eastmoney",
            "/api/qt/stock/trends2/get",
            board_trend_payload(
                [("2026-11-03 09:30", 1000.0), ("2026-11-03 10:30", 1010.0)],
                pre_close=1000.0,
            ),
        )
        if daily_fail:
            def daily_reader(path, params):
                raise SourceError("upstream_http", "down")

            client.add("eastmoney_hist", "/api/qt/stock/kline/get", daily_reader)
        else:
            client.add("eastmoney_hist", "/api/qt/stock/kline/get", board_history_payload(closes))
        client.add("eastmoney_ex", "/getTopicZTPool", json.dumps({"data": {"tc": 30, "qdate": "20261103", "pool": []}}))
        client.add("eastmoney_ex", "/getTopicZBPool", json.dumps({"data": {"tc": 10, "qdate": "20261103", "pool": []}}))
        client.add("eastmoney_ex", "/getTopicDTPool", json.dumps({"data": {"tc": 5, "qdate": "20261103", "pool": []}}))
    cfg = make_config(tmp_path, **cfg)
    holder, clock_fn = (clock if clock else (None, lambda: OPEN))
    store = AlertStore(cfg.runtime.db_path)
    engine = Engine(
        cfg, clock=clock_fn, client=client, store=store, config_path=None,
        member_min_interval=0.0,
    )
    engine.feed = feed
    engine.client = client
    return engine


def default_components():
    return [(f"60{index:02d}{member:02d}", f"M{index}-{member}", 1.0) for index in range(10, 41) for member in range(20)]


def test_tick_fills_blocks(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    overview = engine.overview_dict()
    assert overview["trading_state"] == "open"
    assert len(overview["indexes"]) == 6
    assert all(row["price"] is not None for row in overview["indexes"])
    sectors = engine.sectors_dict()
    assert sectors["ok"] is True
    assert len(sectors["rows"]) == 31
    assert sectors["source"] == "gateway.market_sectors"
    health = engine.health_dict()
    assert health["sources"]["industry"]["ok"] is True
    assert health["sector_universe"]["valid"] == 31


def test_overview_breadth_and_regime(tmp_path):
    engine = make_engine(tmp_path, breadth=(900, 1100, 50))
    engine.tick(OPEN)
    breadth = engine.overview_dict()["breadth"]
    assert breadth["up"] == 1800
    assert breadth["down"] == 2200
    assert breadth["up_ratio"] == pytest.approx(1800 / 4000)
    assert breadth["limit_up"] == 30
    assert breadth["limit_down"] == 5
    assert breadth["broken"] == 10
    assert breadth["seal_ratio"] == pytest.approx(0.75)
    assert engine.overview_dict()["regime"]["label"] in {"risk_on", "neutral", "risk_off"}


def test_amount_share_and_rel_300(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    row = next(item for item in engine.sectors_dict()["rows"] if item["code"] == board_code(40))
    assert row["amount_share_ratio"] == pytest.approx(1e10 / 1e12)
    assert row["rel_300_pct"] == pytest.approx(row["change_pct"] - (-0.2))
    assert row["rank"] == 1


def test_rank_change_after_thirty_minutes(tmp_path):
    engine = make_engine(tmp_path)
    early = datetime(2026, 11, 3, 10, 0, tzinfo=CN_TZ)
    engine.tick(early)
    # At 10:31 the 10:00 rank snapshot is still inside the 150 s tolerance.
    engine.tick(datetime(2026, 11, 3, 10, 30, 30, tzinfo=CN_TZ))
    row = next(item for item in engine.sectors_dict()["rows"] if item["code"] == board_code(40))
    assert row["rank"] == 1
    assert row["rank_change_30m"] is not None


def test_rank_change_null_without_history(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    assert all(row["rank_change_30m"] is None for row in engine.sectors_dict()["rows"])


def test_small_sector_flag(tmp_path):
    engine = make_engine(tmp_path, member_count=5)
    engine.tick(OPEN)
    row = next(item for item in engine.sectors_dict()["rows"] if item["code"] == board_code(40))
    assert row.get("small") is True


def test_lunch_does_not_poll_eastmoney(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    before = len(engine.client.calls)
    engine.tick(datetime(2026, 11, 3, 12, 0, tzinfo=CN_TZ))
    new_calls = engine.client.calls[before:]
    assert new_calls
    assert all(call[0] == "tencent" for call in new_calls)
    assert engine.overview_dict()["trading_state"] == "lunch"


def test_closed_refreshes_once(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(datetime(2026, 11, 3, 15, 2, tzinfo=CN_TZ))
    calls_after_first = len(engine.client.calls)
    engine.tick(datetime(2026, 11, 3, 15, 3, tzinfo=CN_TZ))
    assert len(engine.client.calls) == calls_after_first
    overview = engine.overview_dict()
    assert overview["trading_state"] == "closed"
    assert overview["state_note"] == "休市，显示上一交易时段最后值"
    assert overview["indexes"][0]["stale"] is False


def test_holiday_cold_start_fetches_once(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(datetime(2026, 11, 7, 10, 0, tzinfo=CN_TZ))
    calls_after_first = len(engine.client.calls)
    assert calls_after_first > 0
    engine.tick(datetime(2026, 11, 7, 10, 1, tzinfo=CN_TZ))
    assert len(engine.client.calls) == calls_after_first
    overview = engine.overview_dict()
    assert overview["trading_state"] == "holiday"
    assert overview["indexes"][0]["price"] is not None
    assert overview["state_note"] == "休市，显示上一交易时段最后值"


def test_upstream_failure_returns_null_and_reason(tmp_path):
    engine = make_engine(tmp_path)
    def boom(path, params):
        raise SourceError("upstream_http", "breadth broke")
    engine.client.routes = [route for route in engine.client.routes if not route[1].startswith("/api/qt/ulist")]
    engine.client.add("eastmoney", "/api/qt/ulist.np/get", boom)
    engine.tick(OPEN)
    breadth = engine.overview_dict()["breadth"]
    assert breadth["up"] is None
    assert "breadth broke" in breadth["reason"]
    health = engine.health_dict()
    assert health["sources"]["breadth"]["ok"] is False


def test_stale_flag_after_threshold(tmp_path):
    holder, clock = clock_at(OPEN)
    engine = make_engine(tmp_path, clock=(holder, clock))
    engine.tick(OPEN)
    assert engine.overview_dict()["indexes"][0]["stale"] is False
    holder["now"] = OPEN + timedelta(seconds=30)
    assert engine.overview_dict()["indexes"][0]["stale"] is True


def test_config_reload_success(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "api: {host: 127.0.0.1, port: 8866}\n"
        "runtime: {db_path: market.db}\n"
        "calendar: {source: weekdays}\n"
        "suppression: {enabled: true, open_minutes: 15, close_minutes: 5}\n"
        "rules:\n  R1:\n    enabled: false\n    confirm: 5\n",
        encoding="utf-8",
    )
    cfg = make_config(tmp_path)
    engine = Engine(cfg, clock=lambda: OPEN, client=FakeClient(), store=AlertStore(cfg.runtime.db_path), config_path=cfg_path)
    engine._config_mtime = None
    engine.maybe_reload_config()
    assert engine.config_reload_error is None
    assert engine.evaluator.rules["R1"].enabled is False
    assert engine.evaluator.rules["R1"].confirm == 5


def test_config_reload_failure_keeps_old(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("api: {host: 127.0.0.1, port: 8866}\ncalendar: {source: weekdays}\nrules: {R1: {confirm: 4}}\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    engine = Engine(cfg, clock=lambda: OPEN, client=FakeClient(), store=AlertStore(cfg.runtime.db_path), config_path=cfg_path)
    engine._config_mtime = None
    engine.maybe_reload_config()
    assert engine.evaluator.rules["R1"].confirm == 4
    cfg_path.write_text("rules: {R1: {confirm: 0}}\n", encoding="utf-8")
    engine._config_mtime = None
    engine.maybe_reload_config()
    assert engine.config_reload_error is not None
    assert engine.evaluator.rules["R1"].confirm == 4
    assert "config_reload_error" in engine.health_dict()


def seed_baselines(store, days=2):
    for offset in range(days):
        day = date(2026, 10, 30 - offset)
        store.record_daily_amount("idx:000001.SH", day, 5e11)
        store.record_daily_amount("idx:399001.SZ", day, 5e11)
        store.record_daily_amount("idx:399006.SZ", day, 2e11)
        store.record_daily_amount("idx:000300.SH", day, 3e11)
        store.record_daily_amount("idx:000852.SH", day, 1.5e11)
        store.record_daily_amount("idx:000688.SH", day, 0.8e11)


def test_r1_alert_end_to_end(tmp_path):
    feed = make_feed(index_changes={"000001.SH": -1.5, "399001.SZ": -1.6, "000300.SH": -0.2})
    engine = make_engine(tmp_path, feed=feed)
    seed_baselines(engine.store)
    engine.tick(OPEN)
    assert engine.alerts_dict()["alerts"] == []
    engine.tick(OPEN + timedelta(seconds=3))
    alerts = engine.alerts_dict()["alerts"]
    r1 = [alert for alert in alerts if alert["rule_id"] == "R1"]
    assert len(r1) == 1
    assert r1[0]["status"] == "new"
    assert r1[0]["payload"]["objects"][0]["metrics"]["volume_ratio"] > 1.5
    assert engine.alerts_dict()["next_id"] >= r1[0]["id"]


def test_evaluate_only_on_poll_tick(tmp_path):
    feed = make_feed(index_changes={"000001.SH": -2.0, "399001.SZ": -2.0})
    engine = make_engine(tmp_path, feed=feed)
    seed_baselines(engine.store)
    engine.tick(OPEN)
    engine.tick(OPEN + timedelta(seconds=1))
    assert engine.alerts_dict()["alerts"] == []
    engine.tick(OPEN + timedelta(seconds=3))
    assert [alert for alert in engine.alerts_dict()["alerts"] if alert["rule_id"] == "R1"]


def test_suppression_during_open_window(tmp_path):
    feed = make_feed(index_changes={"000001.SH": -2.0, "399001.SZ": -2.0})
    engine = make_engine(tmp_path, feed=feed)
    seed_baselines(engine.store)
    early = datetime(2026, 11, 3, 9, 35, tzinfo=CN_TZ)
    engine.tick(early)
    engine.tick(early + timedelta(seconds=3))
    assert engine.alerts_dict()["alerts"] == []
    assert engine.health_dict()["rules"]["suppressed"]["R1"] == 2


def test_members_endpoint(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    payload = engine.members_dict(board_code(10))
    assert payload["ok"] is True
    assert payload["rows"] == []
    assert payload["reason"]


def test_sector_detail_history(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    payload = engine.sector_dict(board_code(10))
    assert payload["code"] == board_code(10)
    assert "trend" in payload and "history" in payload
    assert payload["history"]["ret_20d_pct"] is None
    assert payload["history"]["reason"]
    assert payload["history"]["rank_5d"] is None
    assert payload["trend"] == []
    assert "分时" in payload["reason"]


def test_spark_is_downsampled(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    moment = OPEN
    for _ in range(300):
        engine.poll_indexes(moment)
        moment += timedelta(seconds=1)
    overview = engine.overview_dict()
    assert 0 < len(overview["indexes"][0]["spark"]) <= 120
    assert overview["indexes"][0]["spark_kind"] == "intraday"


def test_unknown_sector_error(tmp_path):
    engine = make_engine(tmp_path)
    engine.tick(OPEN)
    payload = engine.sector_dict("BK9999")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_sector"


def test_invalid_level_error(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.sectors_dict("sw2")["ok"] is False
