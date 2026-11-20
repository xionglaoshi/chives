"""Async backtest jobs for the unified strategy service (T159).

The HTTP API is asynchronous: ``POST /v1/<id>/backtest`` returns a job id, and
the caller polls ``GET /v1/<id>/backtest/<job_id>``.  Results are the files the
``surge-engine backtest`` CLI writes, so a CLI run and a service run with the
same frozen parameters share one cache directory and one result.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .service import StrategyNotFound
from .strategy import Strategy

SCHEMES = ("p1", "p2", "start", "second_board")
SHANGHAI = ZoneInfo("Asia/Shanghai")

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_jobs (
    job_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    scheme TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    params_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    run_id TEXT,
    run_dir TEXT,
    summary_path TEXT,
    error TEXT,
    cached INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_params ON backtest_jobs(params_key, status);
"""


def now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class BacktestJobStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with _connect(self.path) as conn:
            conn.executescript(SCHEMA)

    def create(self, payload: dict[str, Any]) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO backtest_jobs(job_id, strategy_id, scheme, start_date, end_date, params_key,"
                " status, created_at, started_at, finished_at, run_id, run_dir, summary_path, error, cached)"
                " VALUES(:job_id,:strategy_id,:scheme,:start_date,:end_date,:params_key,:status,:created_at,"
                ":started_at,:finished_at,:run_id,:run_dir,:summary_path,:error,:cached)",
                payload,
            )

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "run_id",
            "run_dir",
            "summary_path",
            "error",
            "cached",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        assignments = ", ".join(f"{key}=:{key}" for key in values)
        values["job_id"] = job_id
        with _connect(self.path) as conn:
            conn.execute(f"UPDATE backtest_jobs SET {assignments} WHERE job_id=:job_id", values)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with _connect(self.path) as conn:
            row = conn.execute("SELECT * FROM backtest_jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else dict(row)

    def completed_for(self, params_key: str) -> dict[str, Any] | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM backtest_jobs WHERE params_key=? AND status='completed' "
                "ORDER BY finished_at DESC LIMIT 1",
                (params_key,),
            ).fetchone()
        return None if row is None else dict(row)

    def latest_running_for(self, params_key: str) -> dict[str, Any] | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM backtest_jobs WHERE params_key=? AND status IN ('queued','running') "
                "ORDER BY created_at DESC LIMIT 1",
                (params_key,),
            ).fetchone()
        return None if row is None else dict(row)

    def list(self, strategy_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_jobs WHERE strategy_id=? ORDER BY created_at DESC LIMIT ?",
                (strategy_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_stale(self) -> int:
        with _connect(self.path) as conn:
            cursor = conn.execute(
                "UPDATE backtest_jobs SET status='failed', finished_at=?, "
                "error='服务重启，任务中断，请重新发起' WHERE status IN ('queued','running')",
                (now_iso(),),
            )
            return int(cursor.rowcount)


class BacktestManager:
    """Create, cache and run backtest jobs in background threads."""

    def __init__(
        self,
        strategies: dict[str, Strategy],
        store: BacktestJobStore,
        *,
        run_root: Path | str,
        runner: Callable[[Strategy, str, date, date, str], dict[str, Any]] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.strategies = strategies
        self.store = store
        self.run_root = Path(run_root)
        self.runner = runner or self._default_runner
        self.now = now or now_iso
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.store.mark_stale()

    def _default_runner(self, strategy: Strategy, scheme: str, start: date, end: date, run_id: str) -> dict[str, Any]:
        from surge_engine.backtest import run_backtest, write_result

        result = run_backtest(
            surge_db=getattr(strategy, "surge_db"),
            daily_db=getattr(strategy, "daily_db"),
            scheme=scheme,
            start=start,
            end=end,
            run_root=self.run_root,
        )
        run_dir = write_result(result, self.run_root)
        return {"run_dir": str(run_dir), "summary": result["summary"]}

    def _strategy(self, strategy_id: str) -> Strategy:
        strategy = self.strategies.get(strategy_id)
        if strategy is None:
            raise StrategyNotFound(strategy_id)
        return strategy

    @staticmethod
    def _date(value: str, name: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} 需要 YYYY-MM-DD：{value}") from exc

    def submit(
        self,
        strategy_id: str,
        scheme: str,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        strategy = self._strategy(strategy_id)
        if scheme not in SCHEMES:
            raise ValueError(f"未知方案：{scheme}；可选 {'、'.join(SCHEMES)}")
        start_date = self._date(start or "2020-01-01", "start")
        if end:
            end_date = self._date(end, "end")
        else:
            latest = strategy.latest_date()
            if latest is None:
                raise ValueError("策略还没有计算过任何交易日，无法确定回测结束日")
            end_date = self._date(latest, "end")
        if end_date < start_date:
            raise ValueError("结束日早于起始日")
        params_key = f"{strategy_id}|{scheme}|{start_date.isoformat()}|{end_date.isoformat()}"
        run_id = f"{scheme}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        run_dir = self.run_root / run_id

        cached = self.store.completed_for(params_key)
        if cached is not None and cached.get("summary_path") and Path(str(cached["summary_path"])).is_file():
            return self._payload(cached, cached=True)
        running = self.store.latest_running_for(params_key)
        if running is not None:
            return self._payload(running, cached=False)
        if (run_dir / "summary.json").is_file():
            job = self._record_completed(
                strategy_id, scheme, start_date, end_date, params_key, run_id, run_dir, cached=True
            )
            return self._payload(job, cached=True)

        job_id = f"{run_id}-{int(datetime.now().timestamp() * 1000) % 1_000_000:06d}"
        payload = {
            "job_id": job_id,
            "strategy_id": strategy_id,
            "scheme": scheme,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "params_key": params_key,
            "status": "queued",
            "created_at": self.now(),
            "started_at": None,
            "finished_at": None,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "summary_path": None,
            "error": None,
            "cached": 0,
        }
        self.store.create(payload)
        thread = threading.Thread(
            target=self._run,
            args=(job_id, strategy, scheme, start_date, end_date, run_id),
            name=f"backtest-{job_id}",
            daemon=True,
        )
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return self._payload(payload, cached=False)

    def _run(
        self,
        job_id: str,
        strategy: Strategy,
        scheme: str,
        start: date,
        end: date,
        run_id: str,
    ) -> None:
        self.store.update(job_id, status="running", started_at=self.now())
        try:
            outcome = self.runner(strategy, scheme, start, end, run_id)
            run_dir = Path(str(outcome.get("run_dir") or self.run_root / run_id))
            summary_path = run_dir / "summary.json"
            summary = outcome.get("summary") if isinstance(outcome.get("summary"), dict) else {}
            self.store.update(
                job_id,
                status="completed",
                finished_at=self.now(),
                run_dir=str(run_dir),
                summary_path=str(summary_path),
                run_id=str(summary.get("run_id") or run_id),
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - job must record a Chinese failure
            self.store.update(
                job_id,
                status="failed",
                finished_at=self.now(),
                error=f"回测失败：{exc}",
            )

    def _record_completed(
        self,
        strategy_id: str,
        scheme: str,
        start: date,
        end: date,
        params_key: str,
        run_id: str,
        run_dir: Path,
        *,
        cached: bool,
    ) -> dict[str, Any]:
        job_id = f"{run_id}-cached"
        existing = self.store.get(job_id)
        if existing is not None:
            return existing
        record = {
            "job_id": job_id,
            "strategy_id": strategy_id,
            "scheme": scheme,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "params_key": params_key,
            "status": "completed",
            "created_at": self.now(),
            "started_at": None,
            "finished_at": self.now(),
            "run_id": run_id,
            "run_dir": str(run_dir),
            "summary_path": str(run_dir / "summary.json"),
            "error": None,
            "cached": 1 if cached else 0,
        }
        self.store.create(record)
        return self.store.get(job_id) or record

    def result(self, strategy_id: str, job_id: str) -> dict[str, Any]:
        self._strategy(strategy_id)
        row = self.store.get(job_id)
        if row is None or str(row["strategy_id"]) != strategy_id:
            raise KeyError(job_id)
        return self._payload(row, cached=bool(row.get("cached")))

    def history(self, strategy_id: str, limit: int = 20) -> dict[str, Any]:
        self._strategy(strategy_id)
        return {"ok": True, "strategy": strategy_id, "jobs": [self._history_row(row) for row in self.store.list(strategy_id, limit)]}

    def _history_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "scheme": row["scheme"],
            "start": row["start_date"],
            "end": row["end_date"],
            "status": row["status"],
            "run_id": row.get("run_id"),
            "created_at": row["created_at"],
            "finished_at": row.get("finished_at"),
            "cached": bool(row.get("cached")),
        }

    def _payload(self, row: dict[str, Any], *, cached: bool) -> dict[str, Any]:
        payload = {
            "ok": True,
            "job_id": row["job_id"],
            "strategy": row["strategy_id"],
            "scheme": row["scheme"],
            "start": row["start_date"],
            "end": row["end_date"],
            "status": row["status"],
            "run_id": row.get("run_id"),
            "cached": bool(cached or row.get("cached")),
            "created_at": row["created_at"],
            "finished_at": row.get("finished_at"),
            "error": row.get("error"),
            "disclaimer": "按冻结规则的历史模拟，不代表未来收益，不是投资建议。",
        }
        summary_path = row.get("summary_path")
        if row["status"] == "completed" and summary_path and Path(str(summary_path)).is_file():
            try:
                payload["summary"] = json.loads(Path(str(summary_path)).read_text(encoding="utf-8"))
            except (ValueError, OSError):
                payload["summary_error"] = "结果文件无法读取"
        if row.get("run_dir"):
            payload["paths"] = {
                "run_dir": row["run_dir"],
                "summary": row.get("summary_path"),
                "trades": str(Path(str(row["run_dir"])) / "trades.csv"),
                "equity": str(Path(str(row["run_dir"])) / "equity.csv"),
                "report": str(Path(str(row["run_dir"])) / "report.md"),
            }
        return payload
