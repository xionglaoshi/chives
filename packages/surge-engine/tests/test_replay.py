from __future__ import annotations

from datetime import date, timedelta

import pytest

from surge_engine.market import InMemorySource
from surge_engine.outputs import OutputStore
from surge_engine.replay import SurgeReplay
from surge_engine.state import BarView

N_DAYS = 130
F_BASE = 25


def _weekdays(count: int) -> list[date]:
    days: list[date] = []
    current = date(2020, 1, 6)
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def build_market() -> tuple[list[date], InMemorySource]:
    days = _weekdays(N_DAYS)
    bars: dict[str, dict[date, BarView]] = {}
    limits: set[tuple[str, date]] = set()
    window = [10.0, 10.4, 10.2, 10.0, 9.9, 9.8, 9.95, 10.05, 10.1, 10.2]
    for number in range(9):
        code = f"00000{number}.SZ"
        f_index = F_BASE + number * 3
        closes = [10.0] * f_index
        closes[f_index - 10 : f_index] = window
        closes.append(11.2)
        limits.add((code, days[f_index]))
        if number == 0:
            closes.append(12.3)
            limits.add((code, days[f_index + 1]))
        elif number == 1:
            closes += [10.8, 11.5, 11.6, 11.7]
        elif number == 2:
            closes.append(10.0)  # F+1 omitted -> suspension
            closes += [9.0, 9.0, 9.0, 9.0]
        elif number == 3:
            closes += [10.0, 9.0, 9.0, 9.0, 9.0]
        elif number == 4:
            closes += [11.0, 11.5, 12.65]
            limits.add((code, days[f_index + 3]))
        elif number == 5:
            closes += [10.5, 11.5, 11.4, 11.3, 11.4, 11.3, 11.2]
        elif number == 6:
            closes += [10.0, 9.0, 9.9, 10.0, 10.0]
        elif number == 7:
            closes += [11.2] * 50
        else:
            closes += [11.2] * 10
        while len(closes) < N_DAYS:
            closes.append(closes[-1])
        series: dict[date, BarView] = {}
        for offset, close in enumerate(closes[:N_DAYS]):
            if number == 2 and offset == f_index + 1:
                continue
            series[days[offset]] = BarView(close=close, low=close, high=close, volume=1000)
        bars[code] = series
    universe = {day: set(bars) for day in days}
    source = InMemorySource(days, bars, universe, limits)
    return days, source


def _run(tmp_path, days, end_index: int, name: str, start_index: int = 0):
    source = build_market()[1]
    output = OutputStore(tmp_path / f"{name}.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / f"{name}.json")
    replay.run(days[start_index], days[end_index])
    return replay, output


def _snapshot_rows(output: OutputStore, day: date) -> list[tuple]:
    rows = output.conn.execute(
        "SELECT * FROM pool_snapshots WHERE date=? ORDER BY pool, rank", (day.isoformat(),)
    ).fetchall()
    return [tuple(row) for row in rows]


def test_first_board_detection_branch_and_priority(tmp_path) -> None:
    days, source = build_market()
    output = OutputStore(tmp_path / "out.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "state.json")
    replay.run(days[0], days[-1])
    events0 = output.events_for("000000.SZ")
    names0 = [event["event"] for event in events0]
    assert "首板" in names0 and "二板" in names0
    assert names0.index("首板") < names0.index("二板")
    assert "入首板池" not in names0
    assert any(event["event"] == "入主升浪池" for event in events0)

    events1 = output.events_for("000001.SZ")
    assert "优先级二确定" in [event["event"] for event in events1]
    events4 = output.events_for("000004.SZ")
    assert "优先级一确定" in [event["event"] for event in events4]
    events5 = output.events_for("000005.SZ")
    assert "确认失败移出" in [event["event"] for event in events5]
    assert any(row["code"] == "000005.SZ" and row["out"] == 1 for row in output.rounds_for("000005.SZ"))

    rounds = output.rounds_for("000005.SZ")
    assert len(rounds) == 1
    assert rounds[0]["branch"] == "first"
    fail_day = next(event["date"] for event in events5 if event["event"] == "确认失败移出")
    exit_days = [event["date"] for event in events5 if event["event"] == "主升浪移出"]
    assert exit_days and exit_days[0] > fail_day


def test_support_and_expiry_events(tmp_path) -> None:
    days, source = build_market()
    output = OutputStore(tmp_path / "out.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "state.json")
    replay.run(days[0], days[-1])
    events3 = [event["event"] for event in output.events_for("000003.SZ")]
    assert "支撑最终破位" in events3
    rounds3 = output.rounds_for("000003.SZ")
    assert rounds3[0]["first_pool_days"] and rounds3[0]["first_pool_days"] == 4
    events7 = [event["event"] for event in output.events_for("000007.SZ")]
    assert "到期移出" in events7
    events6 = [event["event"] for event in output.events_for("000006.SZ")]
    assert "支撑收复" in events6


def test_no_future_data_property(tmp_path) -> None:
    days, _ = build_market()
    for cut in (35, 40, 45):
        _, full = _run(tmp_path, days, N_DAYS - 1, f"full_{cut}")
        _, truncated = _run(tmp_path, days, cut, f"cut_{cut}")
        assert _snapshot_rows(full, days[cut]) == _snapshot_rows(truncated, days[cut]), cut
        full_events = full.conn.execute(
            "SELECT code, round_id, date, event, \"values\" FROM events WHERE date<=? ORDER BY date, code, id",
            (days[cut].isoformat(),),
        ).fetchall()
        cut_events = truncated.conn.execute(
            "SELECT code, round_id, date, event, \"values\" FROM events ORDER BY date, code, id"
        ).fetchall()
        assert [tuple(row) for row in full_events] == [tuple(row) for row in cut_events], cut


def test_incremental_step_matches_full_replay(tmp_path) -> None:
    days, _ = build_market()
    cut = 40
    _, reference = _run(tmp_path, days, cut, "reference")
    source = build_market()[1]
    output = OutputStore(tmp_path / "incremental.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "incremental.json")
    replay.run(days[0], days[cut - 1])
    replay.step(days[cut])
    assert _snapshot_rows(output, days[cut]) == _snapshot_rows(reference, days[cut])
    rerun_events = output.conn.execute(
        "SELECT code, round_id, date, event, \"values\" FROM events WHERE date=? ORDER BY code, id",
        (days[cut].isoformat(),),
    ).fetchall()
    ref_events = reference.conn.execute(
        "SELECT code, round_id, date, event, \"values\" FROM events WHERE date=? ORDER BY code, id",
        (days[cut].isoformat(),),
    ).fetchall()
    assert [tuple(row) for row in rerun_events] == [tuple(row) for row in ref_events]


def test_only_one_active_round_per_code(tmp_path) -> None:
    days, source = build_market()
    output = OutputStore(tmp_path / "out.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "state.json")
    replay.run(days[0], days[-1])
    for code in source.universe(days[0]):
        rounds = output.rounds_for(code)
        ids = [row["round_id"] for row in rounds]
        assert ids == sorted(set(ids))
    assert len(output.conn.execute("SELECT * FROM pool_snapshots").fetchall()) > 0


def test_step_requires_replay_state(tmp_path) -> None:
    days, source = build_market()
    output = OutputStore(tmp_path / "out.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "missing.json")
    with pytest.raises(RuntimeError):
        replay.step(days[10])
