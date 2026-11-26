"""Trading calendar: config, three sources, fallback, and engine gating."""

from __future__ import annotations

import copy
import json
import threading
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from chives_radar import cli
from chives_radar.calendar import (
    AkshareCalendar,
    DateSetCalendar,
    WeekdayCalendar,
    build_calendar,
)
from chives_radar.config import ConfigError, load_config, parse_config
from chives_radar.engine import Engine, SourceError, run_once
from chives_radar.models import CN_TZ, CalendarConfig
from chives_radar.server import make_server, stop_server
from support import BASE_CONFIG, MemoryStore, ScriptedSource, StepClock, config, quote

SATURDAY = datetime(2026, 11, 7, 9, 30, 0, tzinfo=CN_TZ)
SUNDAY = datetime(2026, 11, 8, 9, 30, 0, tzinfo=CN_TZ)
MONDAY = datetime(2026, 11, 9, 9, 30, 0, tzinfo=CN_TZ)
FRIDAY = datetime(2026, 11, 6, 9, 30, 0, tzinfo=CN_TZ)


class FunctionSource:
    def __init__(self, func):
        self.func = func

    def fetch(self, codes, now):
        return self.func(codes, now)


def run(cfg, source, *, start=SATURDAY, seconds=150, calendar=None):
    if callable(source) and not hasattr(source, "fetch"):
        source = FunctionSource(source)
    clock = StepClock(start)
    store = MemoryStore()
    engine = Engine(cfg, source, clock, store, calendar=calendar)
    engine.run(threading.Event(), end_at=start + timedelta(seconds=seconds))
    return engine, store


# ------------------------------------------------------------------ sources
def test_weekday_calendar_only_weekdays():
    cal = WeekdayCalendar()
    assert cal.status == "ok"
    assert cal.is_trading_day(FRIDAY)
    assert cal.is_trading_day(MONDAY)
    assert not cal.is_trading_day(SATURDAY)
    assert not cal.is_trading_day(SUNDAY)


def test_file_calendar_only_listed_days():
    cal = DateSetCalendar([date(2026, 11, 6), date(2026, 11, 7)])
    assert cal.is_trading_day(FRIDAY)
    assert cal.is_trading_day(SATURDAY)  # a make-up working Saturday
    assert not cal.is_trading_day(MONDAY)


def test_load_config_resolves_calendar_file_beside_the_config(tmp_path: Path):
    (tmp_path / "calendar.json").write_text('["2026-11-07"]', encoding="utf-8")
    raw = copy.deepcopy(BASE_CONFIG)
    raw["calendar"] = {"source": "file", "file": "calendar.json"}
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    cfg = load_config(cfg_path)
    assert cfg.calendar.source == "file"
    assert cfg.calendar.dates == (date(2026, 11, 7),)
    calendar = build_calendar(cfg.calendar, tmp_path)
    assert calendar.is_trading_day(SATURDAY)
    assert not calendar.is_trading_day(MONDAY)


def test_build_calendar_covers_all_three_sources(tmp_path: Path, monkeypatch):
    assert isinstance(build_calendar(CalendarConfig(), tmp_path), WeekdayCalendar)
    file_calendar = build_calendar(
        CalendarConfig(source="file", dates=(date(2026, 11, 7),)), tmp_path
    )
    assert isinstance(file_calendar, DateSetCalendar)

    monkeypatch.setattr("chives_radar.calendar.load_akshare_dates", lambda: [date(2026, 11, 7)])
    ak_calendar = build_calendar(CalendarConfig(source="akshare"), tmp_path)
    assert isinstance(ak_calendar, AkshareCalendar)
    assert ak_calendar.is_trading_day(SATURDAY)
    assert (tmp_path / "trade_calendar.json").exists()


# ------------------------------------------------------------- validation
@pytest.mark.parametrize(
    ("calendar", "content"),
    [
        ({"source": "magic"}, None),
        ({"source": "file"}, None),
        ({"source": "file", "file": "nope.json"}, None),
        ({"source": "file", "file": "bad.json"}, '{"a": 1}'),
        ({"source": "file", "file": "bad.json"}, '["2026-13-45"]'),
        ({"source": "file", "file": "bad.json"}, '["2026-11-03", 5]'),
        ({"source": "file", "file": "bad.json"}, "[]"),
        ({"source": "file", "file": "bad.json"}, "not json"),
    ],
)
def test_invalid_calendar_configs_raise(tmp_path: Path, calendar, content):
    if content is not None:
        (tmp_path / "bad.json").write_text(content, encoding="utf-8")
    raw = copy.deepcopy(BASE_CONFIG)
    raw["calendar"] = calendar
    with pytest.raises(ConfigError):
        parse_config(raw, base_dir=tmp_path)


def test_check_config_exits_2_for_invalid_calendar(tmp_path: Path, capsys):
    raw = copy.deepcopy(BASE_CONFIG)
    raw["calendar"] = {"source": "file", "file": "missing.json"}
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    assert cli.main(["--config", str(cfg), "--check-config"]) == 2
    assert "配置错误" in capsys.readouterr().err


# ---------------------------------------------------------------- akshare
def test_akshare_caches_and_refreshes_at_most_once_per_day(tmp_path: Path):
    calls: list[int] = []

    def loader():
        calls.append(1)
        return [date(2026, 11, 7)]

    cache = tmp_path / "trade_calendar.json"
    cal = AkshareCalendar(cache, loader=loader)

    assert cal.is_trading_day(SATURDAY)
    assert cal.is_trading_day(SATURDAY + timedelta(hours=1))
    assert len(calls) == 1
    assert cal.status == "ok"
    assert json.loads(cache.read_text(encoding="utf-8")) == ["2026-11-07"]

    assert not cal.is_trading_day(MONDAY)
    assert len(calls) == 2


def test_akshare_failure_falls_back_to_disk_cache(tmp_path: Path):
    cache = tmp_path / "trade_calendar.json"
    cache.write_text('["2026-11-07"]', encoding="utf-8")

    def loader():
        raise RuntimeError("network down")

    cal = AkshareCalendar(cache, loader=loader)
    assert cal.is_trading_day(SATURDAY)
    assert cal.status == "ok"
    assert not cal.is_trading_day(MONDAY)


def test_akshare_failure_without_cache_falls_back_to_weekdays_degraded(tmp_path: Path):
    calls: list[int] = []

    def loader():
        calls.append(1)
        raise RuntimeError("network down")

    cal = AkshareCalendar(tmp_path / "none.json", loader=loader)
    assert not cal.is_trading_day(SATURDAY)
    assert cal.status == "degraded"
    assert not cal.is_trading_day(SATURDAY + timedelta(hours=1))
    assert len(calls) == 1
    assert cal.is_trading_day(MONDAY)
    assert len(calls) == 2
    assert not (tmp_path / "none.json").exists()


# ------------------------------------------------------------------ engine
def test_closed_day_polls_and_updates_but_never_alerts():
    def source(codes, now):
        price = 15.6 if (now - SATURDAY).total_seconds() >= 30 else 15.0
        return {code: quote(price=price, exch=now) for code in codes}

    engine, store = run(config(), source)

    assert store.alerts == []
    assert store.polls and all(
        row["trading_day"] is False
        and row["stale"] is False
        and row["mode"] == "idle"
        and row["next_interval"] == 30.0
        and row["calendar_status"] == "ok"
        for row in store.polls
    )
    state = engine.state_dict()
    assert state["trading_day"] is False
    assert state["calendar_status"] == "ok"
    assert state["quotes"]["002553.SZ"]["price"] == 15.6
    health = engine.health_dict()
    assert health["trading_day"] is False
    assert health["calendar_status"] == "ok"


def test_closed_day_is_never_stale_even_with_lagging_quotes():
    def source(codes, now):
        old = SATURDAY - timedelta(days=2)
        return {code: quote(price=15.0, exch=old) for code in codes}

    engine, store = run(config(), source, seconds=30)
    assert store.polls
    assert all(row["stale"] is False for row in store.polls)
    assert all(row["health"] != "stale" for row in store.polls)
    assert engine.state_dict()["lag_seconds"] > 20


def test_trading_day_still_alerts_once(tmp_path: Path):
    calendar = tmp_path / "calendar.json"
    calendar.write_text('["2026-11-06", "2026-11-07"]', encoding="utf-8")

    def source(codes, now):
        price = 15.6 if (now - SATURDAY).total_seconds() >= 30 else 15.0
        return {code: quote(price=price, exch=now) for code in codes}

    engine, store = run(
        config(calendar={"source": "file", "file": str(calendar)}), source
    )

    assert [alert["rule_id"] for alert in store.alerts] == ["pct_up_3"]
    assert datetime.fromisoformat(store.alerts[0]["ts"]) == SATURDAY + timedelta(seconds=30)
    assert store.polls and all(row["trading_day"] is True for row in store.polls)
    assert engine.state_dict()["trading_day"] is True


def test_non_trading_day_failure_stays_idle_and_not_stale():
    store = MemoryStore()
    engine = Engine(
        config(),
        ScriptedSource([SourceError("timeout")]),
        StepClock(SATURDAY),
        store,
    )
    engine.poll()

    row = store.polls[-1]
    assert row["ok"] is False
    assert row["trading_day"] is False
    assert row["stale"] is False
    assert row["mode"] == "idle"
    assert row["next_interval"] == 30.0
    assert row["health"] == "degraded"
    assert row["calendar_status"] == "ok"


def test_engine_reports_degraded_when_akshare_falls_back(tmp_path: Path):
    def loader():
        raise RuntimeError("network down")

    calendar = AkshareCalendar(tmp_path / "none.json", loader=loader)
    engine = Engine(
        config(),
        ScriptedSource([{"002553.SZ": quote(price=15.6, exch=SATURDAY)}]),
        StepClock(SATURDAY),
        MemoryStore(),
        calendar=calendar,
    )
    engine.poll()
    state = engine.state_dict()
    assert state["trading_day"] is False
    assert state["calendar_status"] == "degraded"


def test_run_once_payload_exposes_calendar_fields():
    payload = run_once(
        config(),
        ScriptedSource([{"002553.SZ": quote(price=15.6, exch=SATURDAY)}]),
        StepClock(SATURDAY),
        MemoryStore(),
    )
    assert payload["trading_day"] is False
    assert payload["calendar_status"] == "ok"
    assert payload["alerts"] == []


def test_http_health_and_state_expose_calendar_fields():
    engine = Engine(
        config(),
        ScriptedSource([{"002553.SZ": quote(price=15.6, exch=SATURDAY)}]),
        StepClock(SATURDAY),
        MemoryStore(),
    )
    engine.poll()
    httpd = make_server(engine, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read())
        with urllib.request.urlopen(base + "/state", timeout=5) as response:
            state = json.loads(response.read())
        assert health["trading_day"] is False
        assert health["calendar_status"] == "ok"
        assert state["trading_day"] is False
        assert state["calendar_status"] == "ok"
    finally:
        stop_server(httpd, thread)
