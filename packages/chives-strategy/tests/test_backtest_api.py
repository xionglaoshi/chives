"""HTTP/MCP tests for the asynchronous backtest API (T159)."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from chives_strategy.backtest import BacktestJobStore, BacktestManager
from chives_strategy.daemon import HubDaemon
from chives_strategy.db import AlertStore
from chives_strategy.service import HubService
from chives_strategy.strategy import ZhushenglangStrategy

from .support import build_service

FAKE_SUMMARY = {
    "run_id": "p1_20200101_20261117",
    "scheme": "p1",
    "start": "2020-01-01",
    "cutoff": "2026-11-17",
    "signal_count": 10,
    "per_trade": {
        "count": 8,
        "unfilled_limit_up": 1,
        "suspension_abandoned": 1,
        "skipped_full": 0,
        "win_rate_pct": 50.0,
        "avg_return_pct": 1.2,
        "max_win_pct": 10.0,
        "max_loss_pct": -5.0,
    },
    "portfolio": {"total_return_pct": 12.0, "max_drawdown_pct": -8.0},
    "out_of_sample": {"2020–2023": {"count": 5, "win_rate_pct": 40.0, "avg_return_pct": 0.5}},
    "disclaimer": "按冻结规则的历史模拟，不代表未来收益，不是投资建议。",
}


def _get(base: str, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _backtest_service(databases: dict[str, Path]):
    strategy = ZhushenglangStrategy(databases["surge"], databases["daily"])
    calls: list[tuple] = []

    def runner(strategy_arg, scheme, start, end, run_id):
        calls.append((scheme, start.isoformat(), end.isoformat(), run_id))
        run_dir = databases["hub"].parent / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = dict(FAKE_SUMMARY, run_id=run_id, scheme=scheme, start=start.isoformat(), cutoff=end.isoformat())
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return {"run_dir": str(run_dir), "summary": summary}

    manager = BacktestManager(
        {strategy.id: strategy},
        BacktestJobStore(databases["hub"]),
        run_root=databases["hub"].parent / "runs",
        runner=runner,
    )
    service = HubService({strategy.id: strategy}, AlertStore(databases["hub"]), backtests=manager)
    return service, calls


def test_backtest_post_poll_history_and_cache(databases: dict[str, Path]) -> None:
    service, calls = _backtest_service(databases)
    daemon = HubDaemon(service, port=0).start()
    base = f"http://127.0.0.1:{daemon.port}"
    try:
        status, created = _post(
            base, "/v1/zhushenglang/backtest", {"scheme": "p1", "start": "2020-01-01", "end": "2026-11-17"}
        )
        assert status == 202
        assert created["ok"] is True
        job_id = created["job_id"]
        assert created["status"] in {"queued", "running", "completed"}

        payload = {}
        for _ in range(100):
            status, payload = _get(base, f"/v1/zhushenglang/backtest/{job_id}")
            assert status == 200
            if payload["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert payload["status"] == "completed", payload.get("error")
        assert payload["summary"]["per_trade"]["unfilled_limit_up"] == 1
        assert payload["summary"]["portfolio"]["max_drawdown_pct"] == -8.0
        assert "不是投资建议" in payload["disclaimer"]
        assert payload["paths"]["report"].endswith("report.md")

        status, cached = _post(
            base, "/v1/zhushenglang/backtest", {"scheme": "p1", "start": "2020-01-01", "end": "2026-11-17"}
        )
        assert status == 202
        assert cached["cached"] is True
        assert cached["status"] == "completed"
        assert len(calls) == 1

        status, history = _get(base, "/v1/zhushenglang/backtests?limit=10")
        assert status == 200
        assert history["jobs"][0]["job_id"] == job_id
        assert history["jobs"][0]["status"] == "completed"
    finally:
        daemon.stop()


def test_backtest_rejects_bad_scheme_and_unknown_job(databases: dict[str, Path]) -> None:
    service, _calls = _backtest_service(databases)
    daemon = HubDaemon(service, port=0).start()
    base = f"http://127.0.0.1:{daemon.port}"
    try:
        import urllib.error

        try:
            _post(base, "/v1/zhushenglang/backtest", {"scheme": "nope"})
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert "未知方案" in body["message"]
        else:  # pragma: no cover - assertion helper
            raise AssertionError("expected HTTP 400")

        try:
            _get(base, "/v1/zhushenglang/backtest/not-a-job")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert "没有这个回测任务" in body["message"]
        else:  # pragma: no cover - assertion helper
            raise AssertionError("expected HTTP 404")
    finally:
        daemon.stop()


def test_backtest_requires_manager(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    daemon = HubDaemon(service, port=0).start()
    base = f"http://127.0.0.1:{daemon.port}"
    try:
        import urllib.error

        try:
            _post(base, "/v1/zhushenglang/backtest", {"scheme": "p1"})
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 503
            assert "回测服务未启用" in body["message"]
        else:  # pragma: no cover - assertion helper
            raise AssertionError("expected HTTP 503")
    finally:
        daemon.stop()


def test_mcp_backtest_tools_forward_to_service(databases: dict[str, Path]) -> None:
    from .test_mcp import _exchange, _session

    service, _calls = _backtest_service(databases)
    daemon = HubDaemon(service, port=0).start()
    process = _session(f"http://127.0.0.1:{daemon.port}", "zhushenglang")
    try:
        _exchange(
            process,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        )
        call = _exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "strategy_backtest",
                    "arguments": {"strategy_id": "zhushenglang", "scheme": "p1", "start": "2020-01-01"},
                },
            },
        )
        created = json.loads(call["result"]["content"][0]["text"])
        assert created["ok"] is True
        assert created["disclaimer"].endswith("不是投资建议。")

        payload = {}
        for _ in range(100):
            call = _exchange(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "strategy_backtest_result",
                        "arguments": {"strategy_id": "zhushenglang", "job_id": created["job_id"]},
                    },
                },
            )
            payload = json.loads(call["result"]["content"][0]["text"])
            if payload["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert payload["status"] == "completed"
        assert payload["summary"]["per_trade"]["count"] == 8
    finally:
        process.terminate()
        process.wait(timeout=5)
        daemon.stop()
