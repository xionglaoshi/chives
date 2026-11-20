"""A fake headless runner used by the offline tests. Never touches the network."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

mode = os.environ.get("FAKE_RUNNER_MODE", "ok")
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
log_path = os.environ.get("FAKE_RUNNER_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "argc": len(sys.argv) - 1,
                    "prompt": prompt,
                    "env_names": sorted(os.environ),
                    "cwd": os.getcwd(),
                    "pid": os.getpid(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())

if mode in {"slow", "slow_spawn"}:
    if mode == "slow_spawn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        child_path = os.environ.get("FAKE_RUNNER_CHILD_PID")
        if child_path:
            with open(child_path, "w", encoding="utf-8") as handle:
                handle.write(str(child.pid))
    time.sleep(60)

if mode == "fail":
    print("boom", file=sys.stderr)
    raise SystemExit(1)

if mode == "no_final":
    raise SystemExit(0)

session_id = "session-fake-" + hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]
print("not a json line", flush=True)
print(json.dumps({"type": "session", "sessionId": session_id}), flush=True)
print(json.dumps({"type": "tool_call", "tool": "cn_get_quote_snapshot", "input": {}}), flush=True)
if mode == "text":
    text = os.environ.get("FAKE_RUNNER_TEXT", "")
else:
    text = "观察｜现价仍在区间下沿，量能未确认｜10:30 看能否站稳 VWAP｜跌破 10.20 放弃"
print(json.dumps({"type": "final", "text": text}, ensure_ascii=False), flush=True)
