"""Manual smoke run against real public endpoints (not part of the test suite).

    .venv/bin/python tools/smoke.py [--port 8868]

Starts a temporary loopback daemon, calls each tool once, then prints a short
envelope summary and the /health state. Read-only and low frequency.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chives_data.daemon import GatewayDaemon  # noqa: E402


def _post(port: int, tool: str, args: dict) -> dict:
    body = json.dumps({"tool": tool, "args": args}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/call",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(port: int, path: str) -> dict:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        f"http://127.0.0.1:{port}{path}", timeout=30
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _last_weekday() -> str:
    day = date.today()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def _recent_weekday(days_back: int) -> str:
    day = date.today() - timedelta(days=days_back)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def _summary(payload: dict) -> dict:
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("announcements"), list):
        size = len(data["announcements"])
    elif isinstance(data, dict) and isinstance(data.get("text"), str):
        size = data.get("chars")
    elif isinstance(data, dict) and isinstance(data.get("bars"), list):
        size = len(data["bars"])
    elif isinstance(data, dict) and isinstance(data.get("quotes"), list):
        size = len(data["quotes"])
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        size = len(data["items"])
    elif isinstance(data, dict) and isinstance(data.get("groups"), dict):
        size = {key: len(value) for key, value in data["groups"].items()}
    elif isinstance(data, dict) and isinstance(data.get("rows"), list):
        size = len(data["rows"])
    elif isinstance(data, dict) and isinstance(data.get("records"), list):
        size = len(data["records"])
    elif isinstance(data, dict) and isinstance(data.get("reports"), list):
        size = len(data["reports"])
    elif isinstance(data, dict) and isinstance(data.get("events"), list):
        size = len(data["events"])
    elif isinstance(data, dict) and isinstance(data.get("candidates"), list):
        size = len(data["candidates"])
    elif isinstance(data, dict) and isinstance(data.get("periods"), list):
        size = len(data["periods"])
    elif isinstance(data, dict) and isinstance(data.get("days"), list):
        size = len(data["days"])
    elif isinstance(data, dict) and isinstance(data.get("channels"), list):
        size = len(data["channels"])
    elif isinstance(data, dict) and isinstance(data.get("tiers"), list):
        size = len(data["tiers"])
    else:
        size = None
    return {
        "status": payload.get("status"),
        "as_of": payload.get("as_of"),
        "stale": payload.get("stale"),
        "size": size,
        "missing": len(payload.get("missing") or []),
        "basis": payload.get("basis"),
        "message": payload.get("message"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8868)
    parsed = parser.parse_args()
    daemon = GatewayDaemon(port=parsed.port).start()
    port = daemon.port
    cases = [
        ("market_quote", {"codes": ["600519", "000300.SH", "000528"]}),
        ("market_bars", {"code": "600519", "interval": "1d", "limit": 20}),
        ("market_bars", {"code": "000300.SH", "interval": "1d", "limit": 20}),
        ("market_intraday", {"code": "600519", "date": _last_weekday()}),
        ("market_global", {"groups": ["a50", "fx"]}),
        ("market_overview", {}),
        ("market_movers", {"kind": "gainers", "limit": 5}),
        ("market_limit_pool", {"kind": "zt", "limit": 5}),
        ("market_sectors", {"kind": "industry", "limit": 5}),
        ("market_fund_flow", {"scope": "rank", "kind": "in", "limit": 5}),
        ("market_trading_activity", {"kind": "dragon_tiger", "date": _recent_weekday(14)}),
        ("market_northbound", {"kind": "daily", "date": _recent_weekday(1)}),
        ("company_search", {"query": "南方精工"}),
        ("company_search", {"query": "300750"}),
        ("company_financials", {"code": "002553", "periods": 4}),
        ("company_financials", {"code": "600519", "statement": "income", "periods": 2}),
        ("company_valuation", {"scope": "stock", "code": "600519", "years": 3}),
        ("company_valuation", {"scope": "industry", "limit": 5}),
        ("company_valuation", {"scope": "index", "index": "000300.SH"}),
        ("company_valuation", {"scope": "market"}),
        ("company_consensus", {"code": "600519", "limit": 3}),
        ("company_reports", {"code": "600519", "limit": 3}),
        ("company_earnings", {"kind": "report", "period": "2026-09-30", "code": "600519"}),
        ("company_earnings", {"kind": "schedule", "period": "2026-09-30", "code": "002107"}),
        ("company_holders", {"code": "002553", "kind": "top10"}),
        ("company_holders", {"code": "600519", "kind": "funds", "limit": 3}),
        ("company_holders", {"code": "002553", "kind": "count", "limit": 3}),
        ("company_holders", {"code": "002553", "kind": "lockup", "limit": 3}),
        ("company_holders", {"kind": "lockup", "limit": 10,
                             "start": date.today().isoformat(),
                             "end": (date.today() + timedelta(days=30)).isoformat()}),
        ("company_profile", {"code": "002553"}),
        ("company_profile", {"index": "000300.SH", "limit": 5}),
        ("news", {"kind": "stock", "code": "000528", "limit": 5}),
        ("news", {"kind": "irm", "code": "000528", "limit": 5}),
        ("news", {"kind": "flash", "limit": 10}),
        ("news", {"kind": "calendar", "date": _recent_weekday(0), "limit": 5}),
        ("news", {"kind": "suspensions", "date": _recent_weekday(0)}),
    ]
    try:
        for tool, args in cases:
            try:
                payload = _post(port, tool, args)
            except (urllib.error.URLError, OSError) as exc:
                print(f"{tool} {args}: request failed ({type(exc).__name__})", file=sys.stderr)
                continue
            print(f"\n== {tool} {json.dumps(args, ensure_ascii=False)}")
            print(json.dumps(_summary(payload), ensure_ascii=False, indent=2))
        _sector_extras(port)
        _lockup_extras(port)
        _news_extras(port)
        health = _get(port, "/health")
        print("\n== /health")
        for host, state in (health.get("upstreams") or {}).items():
            print(
                f"{host}: state={state.get('state')} requests={state.get('requests_total')} "
                f"failures={state.get('failures_total')} last_error={state.get('last_error')}"
            )
        print("cache:", json.dumps(health.get("cache"), ensure_ascii=False))
        print("recent:", json.dumps((health.get("recent") or [])[-5:], ensure_ascii=False))
    finally:
        daemon.stop()
    return 0


def _sector_extras(port: int) -> None:
    """Industry ranking top 5 with the breadth fields added by T145."""
    payload = _post(port, "market_sectors", {"kind": "industry", "limit": 5})
    data = payload.get("data") or {}
    print("\n== market_sectors industry top5 breadth")
    print(json.dumps(_summary(payload), ensure_ascii=False, indent=2))
    for row in data.get("rows") or []:
        print(json.dumps({key: row.get(key) for key in (
            "name", "change_pct", "up_count", "down_count", "limit_up_count",
            "rel_300_pct", "rank_change_30m", "amount_share_pct",
        )}, ensure_ascii=False))
    print("missing:", [item.get("field") for item in payload.get("missing") or []])


def _lockup_extras(port: int) -> None:
    """Whole-market release calendar for the next 30 days, top 10 by cap."""
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=30)).isoformat()
    payload = _post(port, "company_holders", {"kind": "lockup", "limit": 10, "start": start, "end": end})
    data = payload.get("data") or {}
    print("\n== company_holders lockup whole market top10")
    print(json.dumps(_summary(payload), ensure_ascii=False, indent=2))
    print("range:", data.get("start"), data.get("end"), "total:", data.get("total_count"))
    for row in data.get("rows") or []:
        print(json.dumps({key: row.get(key) for key in (
            "date", "code", "name", "shares", "market_cap_yuan", "float_ratio_pct", "holder_type",
        )}, ensure_ascii=False))
    print("daily:", json.dumps((data.get("daily") or [])[:3], ensure_ascii=False))


def _news_extras(port: int) -> None:
    """Announcement search -> second page -> read the first page; bond list -> two live quotes."""
    announcements = _post(
        port,
        "company_announcements",
        {"code": "000528", "start": _recent_weekday(30), "end": _recent_weekday(0), "limit": 5},
    )
    print("\n== company_announcements search 000528")
    print(json.dumps(_summary(announcements), ensure_ascii=False, indent=2))
    next_offset = (announcements.get("data") or {}).get("next_offset")
    if next_offset is not None:
        second = _post(
            port,
            "company_announcements",
            {"code": "000528", "start": _recent_weekday(30), "end": _recent_weekday(0),
             "limit": 5, "offset": next_offset},
        )
        print("\n== company_announcements search 000528 page 2")
        print(json.dumps(_summary(second), ensure_ascii=False, indent=2))
        print("offset:", (second.get("data") or {}).get("offset"),
              "next_offset:", (second.get("data") or {}).get("next_offset"))
        for row in (second.get("data") or {}).get("announcements") or []:
            print(row.get("date"), row.get("title"))
    rows = (announcements.get("data") or {}).get("announcements") or []
    if rows:
        read = _post(port, "company_announcements", {"url": rows[0]["url"], "end_page": 1, "max_chars": 3000})
        print("\n== company_announcements read first PDF page")
        print(json.dumps(_summary(read), ensure_ascii=False, indent=2))
        text = (read.get("data") or {}).get("text") or ""
        print("text head:", text[:80].replace("\n", " "))
    bonds = _post(port, "convertible_bonds", {"kind": "list", "limit": 5})
    print("\n== convertible_bonds list")
    print(json.dumps(_summary(bonds), ensure_ascii=False, indent=2))
    codes = [row["bond_code"] for row in (bonds.get("data") or {}).get("rows") or []][:2]
    if codes:
        quotes = _post(port, "convertible_bonds", {"kind": "quote", "codes": codes})
        print("\n== convertible_bonds quote", codes)
        print(json.dumps(_summary(quotes), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
