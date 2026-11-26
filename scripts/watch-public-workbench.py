"""Check the Mac workbench and repair individual unhealthy engines."""
import json
import os
from pathlib import Path
import subprocess
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "runtime/workbench-watchdog.json"
JOB = f"gui/{os.getuid()}/local.chives.workbench"
OPENER = build_opener(ProxyHandler({}))
FAILURE_LIMIT = 3
ENGINES = {
    "gateway": 8868,
    "watch-engine": 8865,
    "market-watch": 8866,
    "chives-hub": 8867,
    "strategy": 8869,
}


def probe(port, path, *, require_ok=False):
    try:
        with OPENER.open(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            if require_ok:
                return json.load(response).get("ok") is True
            return response.status == 200
    except (OSError, ValueError, AttributeError):
        return False


def update_failures(previous, checks):
    return {name: previous.get(name, 0) + 1 for name, healthy in checks.items() if not healthy}


def main():
    loaded = subprocess.run(["/bin/launchctl", "print", JOB], capture_output=True)
    if loaded.returncode != 0:
        STATE.unlink(missing_ok=True)
        return
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = {}
    workbench_ok = probe(8888, "/api/health", require_ok=True) and probe(8888, "/")
    if not workbench_ok:
        failed = update_failures(previous, {"workbench": False})
    else:
        failed = update_failures(previous, {name: probe(port, "/health") for name, port in ENGINES.items()})
    # Persist counts before repair so an interrupted attempt is retried on a later pass.
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(failed))
    temporary.replace(STATE)
    if failed.get("workbench", 0) >= FAILURE_LIMIT:
        print("Chives workbench failed three checks; restarting via launchd.", flush=True)
        subprocess.run(["/bin/launchctl", "kill", "SIGTERM", JOB], check=True)
        STATE.unlink(missing_ok=True)
        return
    for name in ENGINES:
        if failed.get(name, 0) < FAILURE_LIMIT:
            continue
        # Recheck after earlier repairs, particularly after recovering the data gateway.
        if not probe(ENGINES[name], "/health"):
            print(f"Chives engine {name} unhealthy; recovering it.", flush=True)
            try:
                subprocess.run(
                    ["/bin/bash", str(ROOT / "scripts/chives.sh"), "recover-engine", name],
                    cwd=ROOT, check=True, timeout=100, start_new_session=True,
                )
            except (subprocess.SubprocessError, OSError) as error:
                print(f"Chives engine {name} recovery failed: {error}", flush=True)


if __name__ == "__main__":
    main()
