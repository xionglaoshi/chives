from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cn_daily_store.db import connect, init_schema, meta_set

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_db(tmp_path: Path, *, calendar: list[date] | None = None) -> Path:
    path = tmp_path / "daily.sqlite"
    conn = connect(path, readonly=False)
    init_schema(conn)
    days = calendar or [date(2020, 8, 20), date(2020, 8, 21), date(2020, 8, 24)]
    conn.executemany("INSERT INTO calendar(date) VALUES(?)", [(d.isoformat(),) for d in days])
    meta_set(conn, "schema_version", "1")
    conn.commit()
    conn.close()
    return path


def add_security(conn, code: str, board: str, list_date: str, name: str = "测试股", delist: str | None = None):
    conn.execute(
        "INSERT INTO securities(code, name, board, list_date, delist_date, updated_at) "
        "VALUES(?, ?, ?, ?, ?, '2026-01-01T00:00:00+08:00')",
        (code, name, board, list_date, delist),
    )
    conn.execute(
        "INSERT INTO names(code, start_date, name) VALUES(?, ?, ?)",
        (code, list_date, name),
    )


def add_bar(conn, code: str, day: str, close: float, *, factor: float = 1.0, **prices: float):
    open_ = prices.get("open", close)
    high = prices.get("high", max(open_, close))
    low = prices.get("low", min(open_, close))
    volume = int(prices.get("volume", 1000))
    amount = prices.get("amount", 10000.0)
    conn.execute(
        "INSERT INTO bars(code, date, open, high, low, close, volume, amount, adj_factor) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, day, open_, high, low, close, volume, amount, factor),
    )
