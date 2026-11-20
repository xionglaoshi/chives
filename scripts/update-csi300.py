"""Publish the rolling two-year CSI 300 daily close series for the login page."""
import calendar
from datetime import date, datetime, time, timedelta
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("STATE_DIRECTORY", ROOT / "data/market/login-chart"))
SEED = ROOT / "deploy/public/csi300.json"
SINA = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh000300&scale=240&ma=no&datalen=550"
TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,{start},{end},640,qfq"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def anniversary(day):
    year = day.year - 2
    return day.replace(year=year, day=min(day.day, calendar.monthrange(year, day.month)[1]))


def fetch_series(name, url, cutoff, previous):
    res = requests.get(url, timeout=(6, 15))
    res.raise_for_status()
    body = res.json()
    if name == "新浪财经":
        rows = ((r["day"], r["close"]) for r in body)
    else:
        rows = ((r[0], r[2]) for r in body["data"]["sh000300"]["day"])
    points = {}
    for stamp, close in rows:
        day = date.fromisoformat(stamp)
        if day > cutoff:
            continue
        price = float(close)
        if day.weekday() >= 5 or not math.isfinite(price) or price <= 0 or stamp in points:
            raise ValueError("invalid or duplicate trading day")
        points[stamp] = price
    latest = date.fromisoformat(max(points))
    first = anniversary(latest)
    result = [[day, points[day]] for day in sorted(points) if day > first.isoformat()]
    dates = [date.fromisoformat(row[0]) for row in result]
    if (latest < date.fromisoformat(previous[-1][0]) or (cutoff-latest).days > 16
            or not 440 <= len(result) <= 525 or (dates[0]-first).days > 16
            or any((b-a).days > 16 for a,b in zip(dates, dates[1:]))):
        raise ValueError("short, stale or incomplete two-year history")
    for day, price in previous:
        if first.isoformat() < day and (day not in points or abs(points[day]-price) > 0.02):
            raise ValueError(f"history disagrees with published close on {day}")
    return result


def update(now, store=STORE):
    cutoff = now.date() if now.time() >= time(16, 30) else now.date()-timedelta(days=1)
    store.mkdir(parents=True, exist_ok=True)
    out = store / "csi300.json"
    with (store / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = json.loads((out if out.exists() else SEED).read_text())["points"]
        candidates = []
        urls = [("新浪财经", SINA), ("腾讯证券", TENCENT.format(start=anniversary(cutoff)-timedelta(days=30), end=cutoff))]
        for name, url in urls:
            try:
                candidates.append((fetch_series(name, url, cutoff, previous), name, url))
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
                print(f"{name}: {error}", file=sys.stderr)
        if not candidates:
            raise ValueError("all sources unavailable or rejected; retained previous snapshot")
        # Newest validated day wins; stable ordering prefers Sina on a tie.
        rows, name, url = max(candidates, key=lambda item: item[0][-1][0])
        if len(candidates) == 2:
            other = dict(candidates[1][0])
            if any(day in other and abs(price-other[day]) > 0.02 for day,price in candidates[0][0]):
                raise ValueError("sources disagree; retained previous snapshot")
        if out.exists() and rows[-1][0] == previous[-1][0]:
            return f"unchanged through {rows[-1][0]}"
        snapshot = {"symbol":"000300", "name":"沪深300", "source":url, "sourceName":name,
                    "publishedAt":now.isoformat(timespec="seconds"), "points":rows}
        with tempfile.NamedTemporaryFile(mode="w", dir=store, delete=False) as tmp:
            path = Path(tmp.name)
            try:
                json.dump(snapshot, tmp, ensure_ascii=False, separators=(",",":"), allow_nan=False)
                tmp.write("\n")
                tmp.flush()
                os.fchmod(tmp.fileno(), 0o644)  # The web server reads this public index snapshot.
                os.fsync(tmp.fileno())
                os.replace(path, out)
            finally:
                path.unlink(missing_ok=True)
        return f"published {rows[0][0]} .. {rows[-1][0]}, {len(rows)} closes, {name}"


if __name__ == "__main__":
    current = datetime.now(SHANGHAI)
    try:
        print(current.isoformat(timespec="seconds"), update(current))
    except (ValueError, OSError) as exc:
        sys.exit(f"{current.isoformat(timespec='seconds')} {exc}")
