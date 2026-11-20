from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from surge_engine.annotate import annotate_round
from surge_engine.cli import main
from surge_engine.market import InMemorySource
from surge_engine.outputs import OutputStore
from surge_engine.replay import SurgeReplay

from test_replay import build_market


class FakeStore:
    def __init__(self, days: list[date], bars: dict[str, dict[date, object]], limits: set[tuple[str, date]]) -> None:
        self._days = days
        self._bars = bars
        self._limits = limits

    def calendar(self) -> list[date]:
        return self._days

    def bars(self, code: str, start, end, adjust: str = "qfq"):
        series = self._bars.get(code, {})
        return [
            SimpleNamespace(
                date=day,
                open=bar.close,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for day, bar in sorted(series.items())
            if str(start) <= day.isoformat() <= str(end)
        ]

    def is_limit_up(self, code: str, day: date) -> bool:
        return (code, day) in self._limits

    def close(self) -> None:
        pass


def _replay(tmp_path):
    days, source = build_market()
    output = OutputStore(tmp_path / "out.sqlite")
    replay = SurgeReplay(source, output, state_path=tmp_path / "state.json")
    replay.run(days[0], days[-1])
    fake = FakeStore(days, source._bars, source._limit)
    return output, fake


def test_annotate_outputs_json_and_svg(tmp_path) -> None:
    output, fake = _replay(tmp_path)
    payload = annotate_round(
        "000001.SZ", 1, output=output, store=fake, out_dir=tmp_path / "review"
    )
    json_path = tmp_path / "review" / "000001.SZ_1.json"
    html_path = tmp_path / "review" / "000001.SZ_1.html"
    assert json_path.is_file() and html_path.is_file()
    stored = json.loads(json_path.read_text())
    assert stored["code"] == "000001.SZ"
    assert stored["bars"]
    assert {"ma5", "ma10", "ma20", "hb"}.issubset(stored["bars"][0])
    assert stored["lines"]["golden_pit"] is not None
    assert stored["lines"]["golden_pit_date"]
    assert stored["lines"]["first_board_date"]
    assert stored["lines"]["mark_price"] is not None
    page = html_path.read_text()
    assert "<svg" in page and "MA10" in page and "000001.SZ" in page


def test_cli_pools_and_round(tmp_path, capsys) -> None:
    output, _ = _replay(tmp_path)
    output.close()
    assert main(["--output", str(tmp_path / "out.sqlite"), "pools", "--date", "2020-03-01"]) == 0
    captured = capsys.readouterr().out
    assert "首板观察池" in captured and "主升浪池" in captured
    assert main(["--output", str(tmp_path / "out.sqlite"), "round", "000001.SZ"]) == 0
    captured = capsys.readouterr().out
    assert "轮次" in captured and "优先级二确定" in captured
