"""Restart the launchd workbench after repeated local readiness failures."""
import json
import os
from pathlib import Path
import subprocess
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "runtime/public-workbench-failures"
JOB = f"gui/{os.getuid()}/local.chives.workbench"
OPENER = build_opener(ProxyHandler({}))


def healthy():
    try:
        with OPENER.open("http://127.0.0.1:8888/api/health", timeout=3) as response:
            if json.loads(response.read(1024)).get("ok") is not True:
                return False
        with OPENER.open("http://127.0.0.1:8888/", timeout=3) as response:
            return response.status == 200
    except (OSError, URLError, ValueError, AttributeError):
        return False


def main():
    loaded = subprocess.run(["/bin/launchctl", "print", JOB], capture_output=True)
    if loaded.returncode != 0 or healthy():
        STATE.unlink(missing_ok=True)
        return
    failures = int(STATE.read_text()) + 1 if STATE.exists() else 1
    STATE.write_text(str(failures))
    if failures >= 3:
        # TERM lets the workbench owner stop its children before KeepAlive relaunches it.
        print("Chives workbench unhealthy after three checks, requesting a restart.", flush=True)
        subprocess.run(["/bin/launchctl", "kill", "SIGTERM", JOB], check=True)
        STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
