from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cn_daily_store.db import connect, init_schema
from surge_engine.outputs import OutputStore


def _daily_db(path: Path) -> None:
    conn = connect(path, readonly=False)
    try:
        init_schema(conn)
        days = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
                "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12",
                "2026-11-13", "2026-11-16", "2026-11-17"]
        for day in days:
            conn.execute("INSERT INTO calendar(date) VALUES(?)", (day,))
        conn.execute(
            "INSERT INTO securities(code, name, board, list_date, delist_date, updated_at) "
            "VALUES('600519.SH','贵州茅台','main','2001-08-27',NULL,'2026-11-17')"
        )
        conn.execute(
            "INSERT INTO names(code, start_date, name) VALUES('600519.SH','2001-08-27','贵州茅台')"
        )
        closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
        for day, close in zip(days, closes):
            conn.execute(
                "INSERT INTO bars(code, date, open, high, low, close, volume, amount, adj_factor) "
                "VALUES('600519.SH',?,?,?,?,?,?,?,1.0)",
                (day, close, close + 0.5, close - 0.5, close, 1000000, close * 1000000),
            )
        conn.commit()
    finally:
        conn.close()


def _surge_db(path: Path) -> None:
    output = OutputStore(path)
    try:
        output.set_meta("engine", "surge-engine")
        output.set_meta("spec_version", "v1")
        output.set_meta("last_date", "2026-11-17")
        output.conn.execute(
            "INSERT INTO rounds(code, round_id, F, C_F, L_F, G, window_max, window_min, drawdown, branch,"
            " started, T_star, P_star, priority, priority_date, vr, E, B, first_in_date, first_out_date,"
            " first_out_reason, first_pool_days, main_out_date, main_out_reason, main_pool_days, ma10_count, out)"
            " VALUES('600519.SH',1,'2026-10-30',12.0,10.5,10.2,12.0,10.2,0.06,'first',1,'2026-11-04',13.5,"
            " 'p1','2026-11-05',1.8,'2026-11-04',13.5,'2026-10-31',NULL,NULL,6,NULL,NULL,NULL,1,0)"
        )
        output.conn.execute(
            "INSERT INTO pool_snapshots(date,pool,code,round_id,rank,status,priority,priority_date,vr,k,score,"
            "support_score,ma_score,time_score,volume_score,hb,s1_status,s2_status,t_star,p_star,close,entry_date,"
            "basis,hmax,gain,drawdown,base_score,deduction,ma10_count,ma10_obs_left)"
            " VALUES('2026-11-17','first','600519.SH',1,1,'优先级一','p1','2026-11-05',1.8,12,85,100,100,75,100,"
            " 13.2,'normal','normal','2026-11-04',13.5,22.0,'2026-11-04',13.5,22.0,0.63,0.0,100,0,1,0)"
        )
        output.conn.execute(
            "INSERT INTO pool_snapshots(date,pool,code,round_id,rank,status,priority,priority_date,vr,k,score,"
            "support_score,ma_score,time_score,volume_score,hb,s1_status,s2_status,t_star,p_star,close,entry_date,"
            "basis,hmax,gain,drawdown,base_score,deduction,ma10_count,ma10_obs_left)"
            " VALUES('2026-11-17','main','600519.SH',1,1,'观察中','p1','2026-11-05',1.8,12,90,100,100,75,100,"
            " NULL,NULL,NULL,'2026-11-04',13.5,22.0,'2026-11-04',13.5,22.0,0.63,0.0,90,0,1,0)"
        )
        events = [
            ("2026-11-17", "启动", {"T_star": "2026-11-04", "P_star": 13.5, "Hb": 13.2, "k": 3, "vr": 1.8}),
            ("2026-11-17", "优先级一确定", {"P_star": 13.5, "close": 14.0, "k": 4, "vr": 1.8}),
            ("2026-11-17", "MA10跌破", {"n": 1, "ma10": 20.5, "close": 20.0}),
        ]
        output.conn.executemany(
            "INSERT INTO events(code, round_id, date, event, \"values\") VALUES('600519.SH',1,?,?,?)",
            [(day, event, json.dumps(values, ensure_ascii=False)) for day, event, values in events],
        )
        output.conn.commit()
    finally:
        output.close()


@pytest.fixture
def databases(tmp_path: Path) -> dict[str, Path]:
    daily = tmp_path / "daily.sqlite"
    surge = tmp_path / "surge.sqlite"
    hub = tmp_path / "hub.sqlite"
    _daily_db(daily)
    _surge_db(surge)
    return {"daily": daily, "surge": surge, "hub": hub}


@pytest.fixture
def read_sqlite():
    def read(path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            return list(conn.execute(sql, params))
        finally:
            conn.close()

    return read
