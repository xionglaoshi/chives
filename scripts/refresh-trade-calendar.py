#!/usr/bin/env python3
"""Write config/trade_calendar.json (JSON array of YYYY-MM-DD trading days) from AKShare's Sina calendar.

Run with a Python that has akshare (e.g. the shared Chives environment). The cn-watch engine reads the file (`calendar: {source: file}`)
and stays free of the akshare dependency. Exits non-zero and leaves the old file untouched on any failure.
"""
import json
import sys
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "config/trade_calendar.json"


def main() -> int:
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        days = sorted({str(d)[:10] for d in df["trade_date"]})
        assert len(days) > 1000 and all(len(d) == 10 for d in days)
    except Exception as exc:
        print(f"calendar refresh failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    last = days[-1]
    if last < date.today().isoformat():
        print(f"calendar ends at {last}, before today; refusing to write", file=sys.stderr)
        return 1
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(days), encoding="utf-8")
    tmp.replace(OUT)
    print(f"wrote {OUT} ({len(days)} days, {days[0]}..{last})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
