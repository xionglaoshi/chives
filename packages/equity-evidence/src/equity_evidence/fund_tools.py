import json
import re
import sys
import subprocess
import fcntl
from datetime import date
from .storage import library, save, stamp


def fund_ranking(limit: int = 20) -> dict:
    """Freeze and return stock-fund share-class ranking by trailing one-year performance."""
    from .funds import rankings

    if not 1 <= limit <= 100:
        raise ValueError("limit 须在 1–100 内")
    return rankings(limit)


def fund_holdings(code: str, year: int) -> dict:
    """Read one public fund's disclosed quarterly holdings, shares and NAV weights."""
    from .funds import holdings

    if not re.fullmatch("[0-9]{6}", code) or not 2000 <= year <= date.today().year:
        raise ValueError("基金代码或年度无效")
    return holdings(code, year)


def fund_holdings_changes(
    year: int, stock: str = "", study_id: str = "", offset: int = 0, limit: int = 30
) -> dict:
    """Query a frozen fund study. List available studies or page changes and common holders for one security."""
    if (
        not 2000 <= year <= date.today().year
        or not 0 <= offset
        or not 1 <= limit <= 100
    ):
        raise ValueError("年份或分页无效")
    directory = library() / "studies/funds" / str(year)
    if not study_id:
        return {
            "year": year,
            "studies": sorted(p.stem[6:] for p in directory.glob("study-*.json")),
        }
    if not re.fullmatch("[a-f0-9]{32}", study_id):
        raise ValueError("研究编号无效")
    data = json.loads((directory / f"study-{study_id}.json").read_bytes())
    from .market import symbol

    digits = symbol(stock)[:6] if stock else ""
    changes = [r for r in data["changes"] if not digits or r["stock"] == digits]
    return dict(
        id=study_id,
        observed=data["observed"],
        scope=data["scope"],
        interpretation=data["interpretation"],
        failures=data["failures"],
        stocks=len(data["holdings"]),
        comparable=len(changes),
        changes=changes[offset : offset + limit],
        holders=data["holdings"].get(digits, []) if digits else [],
        ranking_snapshot=data.get("ranking_snapshot"),
        source_snapshots={
            r["fund"]: data.get("fund_snapshots", {}).get(r["fund"])
            for r in changes[offset : offset + limit]
        },
    )


def fund_study_job(year: int, limit: int = 100, start: bool = False) -> dict:
    """Read or explicitly start a background top-fund study. Poll for its snapshot ID; same date and inputs reuse the job."""
    if not 1 <= limit <= 100 or not 2000 <= year <= date.today().year:
        raise ValueError("年份或基金数量超限")
    root = library() / "studies/jobs"
    root.mkdir(parents=True, exist_ok=True)
    key = f"{date.today().isoformat()}-{year}-{limit}"
    state = root / (key + ".json")
    with (root / (key + ".lock")).open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"job": key, "status": "running"}
        previous = json.loads(state.read_bytes()) if state.exists() else {}
        if not start or previous.get("status") == "done":
            return previous or {"job": key, "status": "not_started"}
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                __name__,
                str(year),
                str(limit),
                str(lock.fileno()),
                key,
            ],
            pass_fds=(lock.fileno(),),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return {"job": key, "status": "running"}


if __name__ == "__main__":
    from .fund_study import study

    year, limit, fd, key = sys.argv[1:]
    dest = library() / "studies/jobs" / (key + ".json")
    try:
        result = study(int(limit), int(year))
        save(
            dest,
            dict(
                job=key,
                status="done",
                study_id=result["id"],
                failures=result["failures"],
                finished=stamp(),
            ),
        )
    except Exception as error:
        save(
            dest,
            dict(
                job=key, status="failed", reason=type(error).__name__, finished=stamp()
            ),
        )
