#!/usr/bin/env python3
"""Verify `path:line` citations in a report and print the cited lines for spot-checking.

Usage:
  python3 scripts/cite_check.py /path/to/report.md --root /path/to/repo [--root /path/to/other]

Exit code 0 when every citation resolves, 1 otherwise. A resolved citation only proves the
line exists; the reviewer must still read the printed line to judge whether it supports the claim.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CITE = re.compile(
    r"(?P<path>[\w.@/\-]+\.(?:d\.mts|d\.cts|d\.ts|mts|cts|tsx|ts|jsx|js|mjs|cjs|py|md|json|yml|yaml|toml|sh|css|html|rs|go|java))"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)


def resolve(rel: str, roots: list[Path]) -> Path | None:
    for root in roots:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--root", action="append", required=True, help="repo root(s) to resolve paths against")
    parser.add_argument("--context", type=int, default=0, help="extra lines to print around the citation")
    args = parser.parse_args()

    roots = [Path(r).expanduser() for r in args.root]
    text = Path(args.report).read_text(encoding="utf-8")
    seen: set[tuple[str, int, int]] = set()
    ok = bad = 0

    for match in CITE.finditer(text):
        rel = match["path"]
        start = int(match["start"])
        end = int(match["end"] or start)
        key = (rel, start, end)
        if key in seen:
            continue
        seen.add(key)

        path = resolve(rel, roots)
        if path is None:
            print(f"MISSING  {rel}:{start}-{end}  (file not found under any --root)")
            bad += 1
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if start < 1 or end > len(lines) or end < start:
            print(f"RANGE    {rel}:{start}-{end}  (file has {len(lines)} lines)")
            bad += 1
            continue
        ok += 1
        lo = max(1, start - args.context)
        hi = min(len(lines), end + args.context)
        print(f"OK       {rel}:{start}-{end}")
        for n in range(lo, hi + 1):
            marker = ">" if start <= n <= end else " "
            print(f"   {marker} {n:5d} | {lines[n - 1][:160]}")

    print(f"\n{ok} resolved, {bad} unresolved, {ok + bad} unique citations")
    if ok + bad == 0:
        print("WARNING: report contains no citations")
        return 1
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
