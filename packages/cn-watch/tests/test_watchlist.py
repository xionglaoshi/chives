from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest

from cn_watch.config import ConfigError, SymbolError, normalize_watch_code, parse_config
from cn_watch.engine import Engine, SourceError, WatchlistError
from cn_watch.storage import FileStore
from support import BASE_CONFIG, DAY0, MemoryStore, ScriptedSource, StepClock, config, quote

ALL_CODES = ["002553.SZ", "601099.SH", "600000.SH", "000001.SZ"]


class MappingSource:
    def __init__(self, quotes=None, *, error: bool = False) -> None:
        self.quotes = quotes if quotes is not None else {
            code: quote(code=code, name=f"名称{code[:6]}") for code in ALL_CODES
        }
        self.error = error
        self.calls: list[list[str]] = []

    def fetch(self, codes, now):
        self.calls.append(list(codes))
        if self.error:
            raise SourceError("boom")
        return {code: self.quotes[code] for code in codes if code in self.quotes}


def build(tmp_path: Path, *, source=None, overrides=None, store=None):
    cfg = config(**(overrides or {}))
    out = store or FileStore(tmp_path / "data")
    return Engine(cfg, source or MappingSource(), StepClock(), out), out


def codes(engine: Engine) -> list[str]:
    return [row["code"] for row in engine.watchlist_dict()["watchlist"]]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("601099", "601099.SH"),
        ("601099.sh", "601099.SH"),
        ("002553", "002553.SZ"),
        ("002553.sz", "002553.SZ"),
        (2553, "002553.SZ"),
        ("600000", "600000.SH"),
        ("900901", "900901.SH"),
        ("300750", "300750.SZ"),
    ],
)
def test_normalize_watch_code(value, expected):
    assert normalize_watch_code(value) == expected


@pytest.mark.parametrize(
    "value",
    ["920001", "920001.BJ", "430047", "830799", "871981", "889999", "600000.BJ"],
)
def test_beijing_codes_are_unsupported(value):
    with pytest.raises(SymbolError) as excinfo:
        normalize_watch_code(value)
    assert excinfo.value.code == "unsupported_market"


@pytest.mark.parametrize(
    "value",
    ["", "ABC123", "60000", "6000000", "600000.XX", "600000.SH.X", "../600000", None, 1.5, True, -1, 1000000],
)
def test_bad_codes_are_invalid(value):
    with pytest.raises(SymbolError) as excinfo:
        normalize_watch_code(value)
    assert excinfo.value.code == "invalid_symbol"


def test_add_verifies_a_snapshot_and_rejects_missing_quote(tmp_path: Path):
    engine, store = build(tmp_path, source=MappingSource({}))
    with pytest.raises(WatchlistError) as excinfo:
        engine.add_symbol("601099")
    assert excinfo.value.code == "quote_unavailable"
    assert codes(engine) == ["002553.SZ"]
    assert not (store.out_dir / "watchlist.runtime.json").exists()


def test_add_rejects_source_failure_and_empty_name(tmp_path: Path):
    broken, _ = build(tmp_path / "a", source=MappingSource(error=True))
    with pytest.raises(WatchlistError) as excinfo:
        broken.add_symbol("601099")
    assert excinfo.value.code == "quote_unavailable"

    source = MappingSource({"601099.SH": quote(code="601099.SH", name=" ")}, error=False)
    empty, _ = build(tmp_path / "b", source=source)
    with pytest.raises(WatchlistError) as excinfo:
        empty.add_symbol("601099")
    assert excinfo.value.code == "quote_unavailable"
    assert codes(empty) == ["002553.SZ"]


def test_limit_counts_config_and_runtime_symbols(tmp_path: Path):
    engine, store = build(tmp_path, overrides={"limits": {"max_watchlist": 2}})
    engine.add_symbol("601099")
    assert codes(engine) == ["002553.SZ", "601099.SH"]
    with pytest.raises(WatchlistError) as excinfo:
        engine.add_symbol("600000")
    assert excinfo.value.code == "watchlist_full"
    assert codes(engine) == ["002553.SZ", "601099.SH"]
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == ["601099.SH"]


def test_duplicate_add_is_idempotent_and_does_not_refetch(tmp_path: Path):
    source = MappingSource()
    engine, store = build(tmp_path, source=source)
    first = engine.add_symbol("601099")
    calls = len(source.calls)
    second = engine.add_symbol("601099.SH")
    assert first["status"] == "added"
    assert second["status"] == "already_present"
    assert second["source"] == "runtime"
    assert len(source.calls) == calls
    assert codes(engine) == ["002553.SZ", "601099.SH"]
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == ["601099.SH"]


def test_config_symbol_is_protected_from_removal(tmp_path: Path):
    engine, store = build(tmp_path)
    with pytest.raises(WatchlistError) as excinfo:
        engine.remove_symbol("002553")
    assert excinfo.value.code == "protected_symbol"
    assert codes(engine) == ["002553.SZ"]
    assert not (store.out_dir / "watchlist.runtime.json").exists()


def test_remove_missing_runtime_symbol_is_not_an_error(tmp_path: Path):
    engine, _ = build(tmp_path)
    result = engine.remove_symbol("601099")
    assert result["status"] == "not_present"
    assert codes(engine) == ["002553.SZ"]


def test_runtime_file_roundtrip_and_restart_merge(tmp_path: Path):
    first, store = build(tmp_path)
    first.add_symbol("601099")
    data = json.loads((store.out_dir / "watchlist.runtime.json").read_text(encoding="utf-8"))
    assert data == ["601099.SH"]

    second = Engine(
        first.config,
        MappingSource(),
        StepClock(),
        FileStore(store.out_dir),
    )
    rows = second.watchlist_dict()["watchlist"]
    assert [(row["code"], row["source"]) for row in rows] == [
        ("002553.SZ", "config"),
        ("601099.SH", "runtime"),
    ]
    assert rows[1]["name"] is None
    second.poll()
    assert second.watchlist_dict()["watchlist"][1]["name"].startswith("名称")


def test_corrupt_runtime_file_is_logged_and_treated_as_empty(tmp_path: Path, caplog):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    (store.out_dir / "watchlist.runtime.json").write_text("{not json", encoding="utf-8")
    engine = Engine(config(), MappingSource(), StepClock(), store)
    assert codes(engine) == ["002553.SZ"]
    assert any("已损坏" in record.getMessage() for record in caplog.records)
    engine.add_symbol("601099")
    saved = json.loads((store.out_dir / "watchlist.runtime.json").read_text())
    assert saved == ["601099.SH"]


def test_runtime_file_can_be_configured_explicitly(tmp_path: Path):
    cfg = config(watchlist_runtime_file=str(tmp_path / "nested" / "custom.json"))
    store = FileStore(tmp_path / "data")
    engine = Engine(cfg, MappingSource(), StepClock(), store)
    engine.add_symbol("601099")
    assert (tmp_path / "nested" / "custom.json").exists()
    assert not (store.out_dir / "watchlist.runtime.json").exists()


def test_config_parses_limits_and_runtime_path(tmp_path: Path):
    raw = {**BASE_CONFIG, "watchlist_runtime_file": "runtime/watch/watchlist.runtime.json"}
    cfg = parse_config(raw, base_dir=tmp_path)
    assert cfg.limits.max_watchlist == 10
    assert cfg.watchlist_runtime_file == tmp_path / "runtime/watch/watchlist.runtime.json"
    assert parse_config({**BASE_CONFIG, "limits": {"max_watchlist": 3}}).limits.max_watchlist == 3
    with pytest.raises(ConfigError):
        parse_config({**BASE_CONFIG, "limits": {"max_watchlist": 0}})
    with pytest.raises(ConfigError):
        parse_config({**BASE_CONFIG, "limits": {"max_watchlist": 81}})
    with pytest.raises(ConfigError):
        parse_config(
            {
                **BASE_CONFIG,
                "watchlist": ["002553.SZ", "601099.SH"],
                "limits": {"max_watchlist": 1},
            }
        )


def test_add_and_remove_take_effect_on_the_next_poll(tmp_path: Path):
    engine, store = build(tmp_path)
    engine.poll()
    assert set(engine.state_dict()["quotes"]) == {"002553.SZ"}

    engine.add_symbol("601099")
    engine.poll()
    state = engine.state_dict()
    assert set(state["quotes"]) == {"002553.SZ", "601099.SH"}

    engine.remove_symbol("601099")
    engine.poll()
    state = engine.state_dict()
    assert set(state["quotes"]) == {"002553.SZ"}
    assert all(row["code"] != "601099.SH" for row in state["rules"])
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == []


def test_existing_state_cooldown_and_alert_ids_survive_add_remove(tmp_path: Path):
    store = MemoryStore(alerts=[{"id": 7, "code": "002553.SZ", "rule_id": "pct_up_3", "ts": DAY0.isoformat()}])
    source = MappingSource(
        {
            "002553.SZ": quote(price=15.47),
            "601099.SH": quote(code="601099.SH", name="太平洋", price=10.0, prev_close=10.0),
        }
    )
    engine = Engine(config(), source, StepClock(), store)
    engine.poll()
    before = engine.state_dict()
    alerts_before = engine.alerts()["alerts"]

    engine.add_symbol("601099")
    engine.poll()
    engine.remove_symbol("601099")
    engine.poll()
    after = engine.state_dict()

    assert engine.alerts()["alerts"] == alerts_before
    assert after["quotes"]["002553.SZ"] == before["quotes"]["002553.SZ"]
    assert [row for row in after["rules"] if row["code"] == "002553.SZ"] == [
        row for row in before["rules"] if row["code"] == "002553.SZ"
    ]
    assert before["last_rule_eval_ts"] == after["last_rule_eval_ts"]


def test_concurrent_adds_are_serialized(tmp_path: Path):
    engine, _ = build(tmp_path, overrides={"limits": {"max_watchlist": 4}})
    results: list[str] = []
    lock = threading.Lock()

    def add(code: str) -> None:
        try:
            outcome = engine.add_symbol(code)
            value = outcome["status"]
        except WatchlistError as exc:
            value = exc.code
        with lock:
            results.append(value)

    threads = [threading.Thread(target=add, args=(code,)) for code in ("601099", "600000", "000001")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["added", "added", "added"]
    assert len(codes(engine)) == 4


def test_audit_log_has_action_code_and_result(tmp_path: Path, caplog):
    caplog.set_level(logging.INFO, logger="cn_watch.engine")
    engine, _ = build(tmp_path)
    engine.add_symbol("601099")
    engine.remove_symbol("601099")
    messages = [record.getMessage() for record in caplog.records]
    assert any("action=add" in item and "added" in item for item in messages)
    assert any("action=remove" in item and "removed" in item for item in messages)


def test_failed_atomic_replace_keeps_previous_file_and_list(tmp_path: Path, monkeypatch):
    from cn_watch import watchlist

    engine, store = build(tmp_path)
    engine.add_symbol("601099")
    path = store.out_dir / "watchlist.runtime.json"
    before = path.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(watchlist.os, "replace", boom)
    with pytest.raises(WatchlistError) as excinfo:
        engine.add_symbol("600000")
    assert excinfo.value.code == "persistence_error"
    assert path.read_text(encoding="utf-8") == before
    assert codes(engine) == ["002553.SZ", "601099.SH"]
    assert not (store.out_dir / ".watchlist.runtime.json.tmp").exists()


def test_runtime_file_accepts_object_and_bare_list(tmp_path: Path):
    store = FileStore(tmp_path / "data")
    store.out_dir.mkdir(parents=True, exist_ok=True)
    path = store.out_dir / "watchlist.runtime.json"
    path.write_text(
        json.dumps({"version": 1, "codes": ["601099.SH"], "names": {"601099.SH": "太平洋"}}),
        encoding="utf-8",
    )
    engine = Engine(config(), MappingSource(), StepClock(), store)
    assert codes(engine) == ["002553.SZ", "601099.SH"]
    assert engine.watchlist_dict()["watchlist"][1]["name"] == "太平洋"

    path.write_text(json.dumps(["600000.SH"]), encoding="utf-8")
    engine = Engine(config(), MappingSource(), StepClock(), store)
    assert codes(engine) == ["002553.SZ", "600000.SH"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("512880", "512880.SH"),
        ("512880.SH", "512880.SH"),
        ("510300", "510300.SH"),
        ("159915", "159915.SZ"),
        ("159915.SZ", "159915.SZ"),
    ],
)
def test_normalize_etf_codes(value, expected):
    assert normalize_watch_code(value) == expected


@pytest.mark.parametrize("value", ["399975", "399975.SZ", "000300.SH", "999999"])
def test_index_codes_are_unsupported_instruments(value):
    with pytest.raises(SymbolError) as excinfo:
        normalize_watch_code(value)
    assert excinfo.value.code == "unsupported_instrument"
    assert "指数" in str(excinfo.value)


def test_runtime_add_accepts_an_etf_symbol(tmp_path: Path):
    source = MappingSource(
        {"512880.SH": quote(code="512880.SH", name="证券ETF国泰", price=1.006, prev_close=0.962)}
    )
    engine, store = build(tmp_path, source=source)
    result = engine.add_symbol("512880")
    assert result["status"] == "added"
    assert result["code"] == "512880.SH"
    assert result["name"] == "证券ETF国泰"
    assert codes(engine) == ["002553.SZ", "512880.SH"]
    assert json.loads((store.out_dir / "watchlist.runtime.json").read_text()) == ["512880.SH"]

    engine.poll()
    assert "512880.SH" in engine.state_dict()["quotes"]
