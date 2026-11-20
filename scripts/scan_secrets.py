#!/usr/bin/env python3
"""Scan files for likely secrets. Never prints the matched value, only the location and a pattern name.

Usage:
  python3 scripts/scan_secrets.py [path ...]      # defaults to the repository root

Exit code 1 if anything suspicious is found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "lib", ".mypy_cache", ".pytest_cache"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".zst", ".sqlite3", ".lock"}

PATTERNS = {
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "bearer token literal": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{24,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "assigned secret": re.compile(
        r"""(?ix)\b[A-Z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|COOKIE)[A-Z0-9_]*\s*[:=]\s*['"]?(?!\$|<|\{|!!js|process\.env|os\.environ|None|null|''|"")[A-Za-z0-9_\-./+=]{16,}"""
    ),
    "dsh url token": re.compile(r"[?&]token=[A-Za-z0-9_\-]{20,}"),
}


def iter_files(roots: list[Path]):
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in SKIP_SUFFIX:
                continue
            yield path


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]] or [Path(__file__).resolve().parent.parent]
    hits = 0
    for path in iter_files(roots):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    print(f"SUSPECT  {path}:{lineno}  [{name}]")
                    hits += 1
    print(f"\n{hits} suspicious line(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
