from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from x_mcp.budget import DailyBudget

DAY_ONE = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)


def _budget(local_tmp: Path, limit: int = 5) -> tuple[DailyBudget, dict[str, datetime]]:
    clock = {"now": DAY_ONE}
    return DailyBudget(limit, local_tmp / "budget.json", now=lambda: clock["now"]), clock


def test_reserve_and_settle_by_actual_resources(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=10)
    allowed, snapshot = budget.reserve(4)
    assert allowed is True
    assert snapshot.used_today == 4
    assert snapshot.remaining == 6
    settled = budget.settle(4, 2)
    assert settled.used_today == 2
    assert settled.remaining == 8


def test_reserve_is_denied_when_it_would_exceed_the_limit(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=3)
    assert budget.reserve(2)[0] is True
    allowed, snapshot = budget.reserve(2)
    assert allowed is False
    assert snapshot.used_today == 2
    assert snapshot.remaining == 1
    assert budget.snapshot().used_today == 2


def test_exact_fill_leaves_zero_and_blocks_the_next_call(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=3)
    assert budget.reserve(3)[0] is True
    assert budget.snapshot().remaining == 0
    assert budget.reserve(1)[0] is False


def test_release_refunds_a_failed_call(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=5)
    budget.reserve(3)
    assert budget.release(3).used_today == 0
    assert budget.snapshot().remaining == 5


def test_state_file_is_valid_json_and_atomic(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=5)
    budget.reserve(2)
    path = local_tmp / "budget.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"date": "2026-11-03", "used": 2}
    assert list(local_tmp.glob(".budget-*")) == []


def test_budget_resets_on_a_new_local_day(local_tmp: Path) -> None:
    budget, clock = _budget(local_tmp, limit=5)
    budget.reserve(4)
    clock["now"] = DAY_ONE.replace(day=4, hour=0, minute=0, second=1)
    snapshot = budget.snapshot()
    assert snapshot.used_today == 0
    assert snapshot.remaining == 5
    assert budget.reserve(5)[0] is True
    assert json.loads((local_tmp / "budget.json").read_text(encoding="utf-8"))["date"] == "2026-11-04"


def test_corrupted_state_file_falls_back_to_zero(local_tmp: Path) -> None:
    path = local_tmp / "budget.json"
    path.write_text("not json at all", encoding="utf-8")
    budget, _ = _budget(local_tmp, limit=5)
    assert budget.snapshot().used_today == 0
    assert budget.reserve(1)[0] is True
    assert json.loads(path.read_text(encoding="utf-8"))["used"] == 1


def test_state_file_with_wrong_types_falls_back_to_zero(local_tmp: Path) -> None:
    path = local_tmp / "budget.json"
    path.write_text(json.dumps({"date": 5, "used": "many"}), encoding="utf-8")
    budget, _ = _budget(local_tmp, limit=5)
    assert budget.snapshot().used_today == 0
    path.write_text(json.dumps({"date": "2026-11-03", "used": True}), encoding="utf-8")
    assert budget.snapshot().used_today == 0


def test_corrupt_state_is_replaced_with_a_valid_document(local_tmp: Path) -> None:
    path = local_tmp / "budget.json"
    path.write_text("{broken", encoding="utf-8")
    budget, _ = _budget(local_tmp, limit=5)
    budget.snapshot()
    assert json.loads(path.read_text(encoding="utf-8")) == {"date": "2026-11-03", "used": 0}


def test_concurrent_threads_never_overspend(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=7)

    def attempt(_: int) -> bool:
        return budget.reserve(1)[0]

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(40)))
    assert sum(1 for allowed in results if allowed) == 7
    snapshot = budget.snapshot()
    assert snapshot.used_today == 7
    assert snapshot.remaining == 0


def test_concurrent_processes_share_one_budget(local_tmp: Path) -> None:
    path = local_tmp / "budget.json"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from x_mcp.budget import DailyBudget\n"
        "print('ALLOWED' if DailyBudget(5, Path(sys.argv[1])).reserve(1)[0] else 'DENIED')\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, stderr
        outputs.append(stdout.strip())
    assert outputs.count("ALLOWED") == 5
    assert json.loads(path.read_text(encoding="utf-8"))["used"] == 5


def test_snapshot_reports_reset_time() -> None:
    budget = DailyBudget(5, Path("/nonexistent/never-written.json"), now=lambda: DAY_ONE)
    snapshot = budget._snapshot(DAY_ONE, 2)
    assert snapshot.reset_at == "2026-11-04T00:00:00+00:00"
    assert snapshot.reset_at_epoch == int(
        datetime(2026, 11, 4, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    )
    assert snapshot.short() == {"used_today": 2, "remaining": 3}


@pytest.mark.parametrize("count", [-1, True, "1", 1.5])
def test_reserve_rejects_invalid_counts(local_tmp: Path, count: object) -> None:
    budget, _ = _budget(local_tmp)
    with pytest.raises(ValueError):
        budget.reserve(count)  # type: ignore[arg-type]


def test_settle_clamps_an_unexpected_overrun(local_tmp: Path) -> None:
    budget, _ = _budget(local_tmp, limit=5)
    budget.reserve(1)
    snapshot = budget.settle(1, 99)
    assert snapshot.used_today == 5
    assert snapshot.remaining == 0
