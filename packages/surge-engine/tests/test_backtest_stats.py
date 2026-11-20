"""Stats, signal loading, output and benchmark-cache tests for T159."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from cn_daily_store.db import connect, init_schema
from surge_engine.backtest import (
    equity_metrics,
    histogram,
    load_signals,
    max_drawdown,
    run_backtest,
    write_result,
    yearly_returns,
)
from surge_engine.backtest_benchmarks import load_benchmarks
from surge_engine.outputs import OutputStore

DAYS = [date(2020, 1, day) for day in range(1, 11)]


def _daily_db(path: Path) -> None:
    conn = connect(path, readonly=False)
    try:
        init_schema(conn)
        for day in DAYS:
            conn.execute("INSERT INTO calendar(date) VALUES(?)", (day.isoformat(),))
        conn.execute(
            "INSERT INTO securities(code, name, board, list_date, delist_date, updated_at) "
            "VALUES('600000.SH','浦发银行','sh_main','1999-11-10',NULL,'2020-01-10')"
        )
        conn.execute("INSERT INTO names(code, start_date, name) VALUES('600000.SH','1999-11-10','浦发银行')")
        for day, close in zip(DAYS, [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]):
            conn.execute(
                "INSERT INTO bars(code, date, open, high, low, close, volume, amount, adj_factor) "
                "VALUES('600000.SH',?,?,?,?,?,?,?,1.0)",
                (day.isoformat(), close, close + 0.5, close - 0.5, close, 1_000_000, close * 1_000_000),
            )
        conn.commit()
    finally:
        conn.close()


def _surge_db(path: Path) -> None:
    output = OutputStore(path)
    try:
        output.conn.execute(
            "INSERT INTO rounds(code, round_id, F, C_F, L_F, G, branch, started, T_star, P_star, priority,"
            " priority_date, E, B, first_in_date, main_out_date, main_out_reason, main_pool_days, out)"
            " VALUES('600000.SH',1,'2020-01-01',10.0,9.5,9.8,'first',1,'2020-01-01',10.0,'p1','2020-01-01',"
            " '2020-01-01',10.0,'2020-01-01','2020-01-04','ma10_unrepaired',3,0)"
        )
        output.conn.execute(
            "INSERT INTO events(code, round_id, date, event, \"values\") VALUES('600000.SH',1,'2020-01-01',"
            "'优先级一确定','{}')"
        )
        for pool, rank, score in (("first", 1, 85), ("main", 2, 80)):
            output.conn.execute(
                "INSERT INTO pool_snapshots(date,pool,code,round_id,rank,status,priority,priority_date,score,"
                "base_score,gain,close,entry_date,basis,hmax,drawdown) "
                "VALUES('2020-01-01',?,'600000.SH',1,?, '优先级一','p1','2020-01-01',?,80,0.1,10.0,"
                "'2020-01-01',10.0,10.0,0.0)",
                (pool, rank, score),
            )
        output.conn.commit()
    finally:
        output.close()


def test_load_signals_uses_first_pool_rank_for_p1_and_main_rank_for_start(tmp_path: Path) -> None:
    surge = tmp_path / "surge.sqlite"
    _surge_db(surge)
    p1 = load_signals(surge, "p1", date(2020, 1, 1), date(2020, 1, 10))
    assert len(p1) == 1
    assert p1[0].rank == 1
    assert p1[0].score == 85
    assert p1[0].main_out_date == date(2020, 1, 4)


def test_equity_curve_and_max_drawdown() -> None:
    values = [100.0, 120.0, 90.0, 110.0]
    days = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]
    drawdown, peak, trough = max_drawdown(values, days)
    assert drawdown == pytest.approx(-0.25)
    assert (peak, trough) == ("2020-01-02", "2020-01-03")
    metrics = equity_metrics(values, days)
    assert metrics["total_return_pct"] == pytest.approx(10.0)
    assert metrics["max_drawdown_pct"] == pytest.approx(-25.0)


def test_yearly_returns_and_histogram_edges() -> None:
    rows = [
        {"date": "2022-12-30", "equity": 100.0},
        {"date": "2023-12-29", "equity": 120.0},
        {"date": "2024-12-31", "equity": 90.0},
    ]
    yearly = yearly_returns(rows)
    assert [item["return_pct"] for item in yearly] == pytest.approx([0.0, 20.0, -25.0])
    bins = histogram(
        [
            {"return_pct": -60.0, "buy_date": "2020-01-01", "code": "A", "holding_days": 1},
            {"return_pct": 150.0, "buy_date": "2020-01-02", "code": "B", "holding_days": 1},
        ]
    )
    assert bins[0]["label"].startswith("<")
    assert bins[-1]["label"].startswith(">=")
    assert bins[0]["count"] == 1 and bins[-1]["count"] == 1


def test_run_backtest_writes_outputs_and_never_uses_future_data(tmp_path: Path) -> None:
    daily = tmp_path / "daily.sqlite"
    surge = tmp_path / "surge.sqlite"
    _daily_db(daily)
    _surge_db(surge)
    result = run_backtest(
        surge_db=surge,
        daily_db=daily,
        scheme="p1",
        start=date(2020, 1, 1),
        end=date(2020, 1, 10),
        benchmark_closes={"hs300": {}, "csi1000": {}},
        run_root=tmp_path,
    )
    summary_data = result["summary"]
    assert summary_data["signal_count"] == 1
    assert summary_data["per_trade"]["count"] == 1
    assert summary_data["per_trade"]["avg_return_pct"] is not None
    assert "paths" not in summary_data

    for plan in result["plans"]:
        if plan.status == "ok":
            assert plan.buy_index is not None and plan.buy_index > 0
            assert plan.sell_index is not None and plan.sell_index > plan.buy_index

    run_dir = write_result(result, tmp_path)
    for name in ("trades.csv", "portfolio_trades.csv", "equity.csv", "summary.json", "report.md",
                 "equity.svg", "drawdown.svg", "yearly.svg", "histogram.svg"):
        assert (run_dir / name).is_file(), name
    assert (run_dir / "equity.svg").read_text(encoding="utf-8").startswith("<svg")
    stored = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert stored["run_id"] == "p1_20200101_20200110"
    assert "不是投资建议" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_benchmark_cache_reuses_downloaded_bars(tmp_path: Path) -> None:
    calls: list[tuple[str, date, date]] = []

    def fetch(code, start, end):
        calls.append((code, start, end))
        return [(day, 1000.0 + index) for index, day in enumerate(DAYS) if start <= day <= end]

    first = load_benchmarks(tmp_path, start=DAYS[0], end=DAYS[-1], fetch=fetch)
    assert set(first) == {"hs300", "csi1000"}
    assert len(calls) == 2
    second = load_benchmarks(tmp_path, start=DAYS[0], end=DAYS[-1], fetch=fetch)
    assert second == first
    assert len(calls) == 2
