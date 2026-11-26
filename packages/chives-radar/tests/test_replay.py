from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from chives_radar.engine import SourceError
from chives_radar.sources import ReplaySource
from support import DAY0


def write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def row(seconds: int, price: float, *, code: str = "002553.SZ", exch: str | None = None):
    moment = DAY0 + timedelta(seconds=seconds)
    return {
        "t": moment.isoformat(),
        "quotes": {
            code: {
                "name": "南方精工",
                "price": price,
                "prev_close": 15.0,
                "volume_lots": 1000 + seconds,
                "amount_yuan": price * (1000 + seconds) * 100,
                "exch_time": exch or moment.strftime("%Y%m%d%H%M%S"),
                "limit_up": 16.5,
                "limit_down": 13.5,
            }
        },
    }


def test_returns_the_latest_row_at_or_before_now(tmp_path: Path):
    source = ReplaySource(write(tmp_path / "r.jsonl", [row(0, 15.0), row(3, 15.1), row(6, 15.2)]))
    assert source.fetch(["002553.SZ"], DAY0)["002553.SZ"].price == 15.0
    assert source.fetch(["002553.SZ"], DAY0 + timedelta(seconds=4))["002553.SZ"].price == 15.1
    assert source.fetch(["002553.SZ"], DAY0 + timedelta(seconds=9))["002553.SZ"].price == 15.2
    with pytest.raises(SourceError):
        source.fetch(["002553.SZ"], DAY0 - timedelta(seconds=1))


def test_error_row_fails_the_poll(tmp_path: Path):
    rows = [row(0, 15.0), {"t": (DAY0 + timedelta(seconds=3)).isoformat(), "error": "timeout"}]
    source = ReplaySource(write(tmp_path / "r.jsonl", rows))
    assert source.fetch(["002553.SZ"], DAY0)["002553.SZ"].price == 15.0
    with pytest.raises(SourceError, match="timeout"):
        source.fetch(["002553.SZ"], DAY0 + timedelta(seconds=4))


def test_out_of_order_and_duplicate_timestamps(tmp_path: Path):
    rows = [row(6, 15.2), row(0, 15.0), row(3, 15.1), row(3, 15.9)]
    source = ReplaySource(write(tmp_path / "r.jsonl", rows))
    assert source.start_time == DAY0
    assert source.last_time == DAY0 + timedelta(seconds=6)
    assert source.fetch(["002553.SZ"], DAY0 + timedelta(seconds=4))["002553.SZ"].price == 15.9
    assert source.fetch(["002553.SZ"], DAY0 + timedelta(seconds=7))["002553.SZ"].price == 15.2


def test_missing_code_is_absent_not_an_error(tmp_path: Path):
    source = ReplaySource(write(tmp_path / "r.jsonl", [row(0, 15.0)]))
    quotes = source.fetch(["002553.SZ", "300750.SZ"], DAY0)
    assert set(quotes) == {"002553.SZ"}


def test_empty_replay_file_is_rejected(tmp_path: Path):
    target = tmp_path / "empty.jsonl"
    target.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ReplaySource(target)
