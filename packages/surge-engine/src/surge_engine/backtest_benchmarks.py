"""Benchmark index closes for the 主升浪 backtest.

Only the data layer may talk to an external source (``docs/architecture.md``
section 3); this module calls the local gateway's ``market_bars`` over loopback
and caches the result under ``runtime/surge/backtest/benchmarks/`` so a re-run
does not hit the network again.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

BENCHMARKS = {
    "hs300": ("000300.SH", "沪深300"),
    "csi1000": ("000852.SH", "中证1000"),
}
GATEWAY_URL = "http://127.0.0.1:8868/v1/call"
MAX_BARS = 1000


class BenchmarkUnavailable(RuntimeError):
    """The gateway or its upstream could not supply index daily bars."""


def _gateway_fetch(code: str, start: date, end: date) -> list[tuple[date, float]]:
    payload = json.dumps(
        {
            "tool": "market_bars",
            "args": {
                "code": code,
                "interval": "1d",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": MAX_BARS,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GATEWAY_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise BenchmarkUnavailable(f"取指数日线失败：{exc}") from exc
    data = body.get("data") if isinstance(body, dict) else None
    bars = data.get("bars") if isinstance(data, dict) else None
    if not isinstance(bars, list) or not bars:
        message = body.get("message") if isinstance(body, dict) else None
        raise BenchmarkUnavailable(f"网关没有返回 {code} 的日线：{message or body.get('status')}")
    out: list[tuple[date, float]] = []
    for bar in bars:
        try:
            out.append((date.fromisoformat(str(bar["time"])), float(bar["close"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise BenchmarkUnavailable(f"网关返回的 {code} 日线没有有效收盘价")
    return out


def _fetch_range(
    fetch: Callable[[str, date, date], list[tuple[date, float]]],
    code: str,
    start: date,
    end: date,
) -> dict[date, float]:
    """Gateway returns the latest <=1000 bars; walk backwards for older chunks."""
    result: dict[date, float] = {}
    cursor = end
    while cursor >= start:
        bars = fetch(code, start, cursor)
        if not bars:
            break
        for day, close in bars:
            if start <= day <= end and close > 0:
                result[day] = close
        first = min(day for day, _ in bars)
        if first <= start or len(bars) < MAX_BARS:
            break
        cursor = first - timedelta(days=1)
    return result


def load_benchmarks(
    cache_dir: Path | str,
    *,
    start: date,
    end: date,
    fetch: Callable[[str, date, date], list[tuple[date, float]]] | None = None,
) -> dict[str, dict[date, float]]:
    """Return ``{key: {day: close}}`` for HS300 and CSI1000, cached on disk."""
    fetch = fetch or _gateway_fetch
    root = Path(cache_dir) / "benchmarks"
    root.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[date, float]] = {}
    for key, (code, _label) in BENCHMARKS.items():
        path = root / f"{code}.json"
        cached: dict[date, float] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                cached = {
                    date.fromisoformat(day): float(close)
                    for day, close in (payload.get("bars") or {}).items()
                }
            except (ValueError, TypeError, AttributeError):
                cached = {}
        covered = bool(cached) and min(cached) <= start and max(cached) >= end
        if not covered:
            fetched = _fetch_range(fetch, code, start, end)
            if not fetched and (not cached or min(cached) > start or max(cached) < end):
                raise BenchmarkUnavailable(f"取不到 {code} 的指数日线")
            cached.update(fetched)
            path.write_text(
                json.dumps(
                    {
                        "code": code,
                        "label": _label,
                        "updated_through": max(cached).isoformat() if cached else None,
                        "bars": {day.isoformat(): close for day, close in sorted(cached.items())},
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
        out[key] = {day: close for day, close in cached.items() if start <= day <= end}
    return out
