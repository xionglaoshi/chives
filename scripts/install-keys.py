#!/usr/bin/env python3
"""Install the FMP, Tavily and X API keys from a dotenv-style file into config/secrets.env (mode 600, git-ignored).

Run this YOURSELF: it exists so that key values never pass through an AI agent. It prints only which names were found and
how long the values are, never the values. Only FMP_API_KEY, TAVILY_API_KEY and X_BEARER_TOKEN are copied (any subset; names not in the file are reported as NOT FOUND and left unchanged); everything else in the source is ignored.

    python3 scripts/install-keys.py /path/to/keys.txt
"""
import os
import re
import stat
import sys
from pathlib import Path

WANT = ("FMP_API_KEY", "TAVILY_API_KEY", "X_BEARER_TOKEN")
OUT = Path(__file__).resolve().parent.parent / "config/secrets.env"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 64
    src = Path(sys.argv[1]).expanduser()
    found: dict[str, str] = {}
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        name, val = m.group(1).upper(), m.group(2).strip().strip("\"'")
        if name in WANT and val:
            found[name] = val
    missing = [n for n in WANT if n not in found]
    for n in WANT:
        print(f"{n}: {'found, ' + str(len(found[n])) + ' characters' if n in found else 'NOT FOUND'}")
    if "TAVILY_API_KEY" in found and not found["TAVILY_API_KEY"].startswith("tvly-"):
        print("note: TAVILY_API_KEY does not start with 'tvly-' (Tavily keys normally do); installed anyway")
    if not found:
        print("nothing installed")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old: dict[str, str] = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                old[m.group(1)] = m.group(2)
    old.update(found)
    tmp = OUT.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Chives secrets (git-ignored, mode 600). Written by scripts/install-keys.py. Never commit or paste this file.\n")
        for k in sorted(old):
            f.write(f"{k}={old[k]}\n")
    tmp.replace(OUT)
    OUT.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"wrote {OUT} (mode 600) with {sorted(old)}")
    if src.stat().st_mode & 0o077:
        print(f"note: {src} is readable by other users (mode {oct(src.stat().st_mode & 0o777)}); consider `chmod 600` or deleting it after this")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
