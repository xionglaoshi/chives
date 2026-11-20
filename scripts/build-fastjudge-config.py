#!/usr/bin/env python3
"""Generate config/fastjudge.yaml and runtime/fastjudge/persona.cordis.yml.

The fast-judge runner is ``dsh --profile headless`` with the finance persona and
READ-ONLY quote/watch overlays only: ``cn-data`` and ``cn-watch``.  hub,
paper-broker, trading-guard, portfolio, x and scrape overlays are deliberately
NOT included: the judgement arrives with a frozen context pack and must never
write plans, trade or read private holdings beyond what hub already embedded.

Environment: DSH_FINANCE_HOME (default: Chives data/dsh),
DSH_FINANCE_OVERLAY (model provider overlay, optional),
Uses the Chives-selected dsh version. All written paths are absolute.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
HOME = os.environ.get("DSH_FINANCE_HOME", str(ROOT / "data/dsh"))
MODEL = os.environ.get(
    "DSH_FINANCE_OVERLAY",
    "",
)
RUN = ROOT / "runtime/fastjudge"
READ_ONLY = ["cn-data", "cn-watch"]
DEFAULT_HUB = "http://127.0.0.1:8867"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def hub_url() -> str:
    value = os.environ.get("CHIVES_HUB_URL", DEFAULT_HUB).strip() or DEFAULT_HUB
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in LOOPBACK_HOSTS:
        raise SystemExit(f"CHIVES_HUB_URL 必须是回环 http(s) 地址: {value!r}")
    return value.rstrip("/")


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "state").mkdir(exist_ok=True)
    (RUN / "workspace").mkdir(exist_ok=True)
    prefix = (ROOT / "presets/finance/prefix.md").read_text(encoding="utf-8")
    suffix = (ROOT / "presets/finance/suffix.md").read_text(encoding="utf-8")
    persona = RUN / "persona.cordis.yml"
    persona.write_text(
        "- id: system-prompt\n  name: '@deepseek-ai/dsh-system-prompt'\n  config:\n    personaPrefix: "
        + json.dumps(prefix, ensure_ascii=False)
        + "\n    personaSuffix: "
        + json.dumps(suffix, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        str(ROOT / "scripts/run-dsh.sh"),
        "--profile",
        "headless",
        *(["--patch", MODEL] if MODEL else []),
        "--patch",
        str(persona),
    ]
    for name in READ_ONLY:
        path = ROOT / f"overlays/{name}.cordis.yml"
        if not path.exists():
            raise SystemExit(f"缺少只读 overlay: {path}")
        cmd += ["--patch", str(path)]
    cmd += ["--json", "{prompt}"]
    cfg = {
        "hub": hub_url(),
        "state_dir": str(RUN / "state"),
        "poll_seconds": 2.0,
        "prompt_template": str(ROOT / "presets/finance/fast-judge.md"),
        "limits": {
            "max_runs_per_day": 20,
            "cooldown_seconds": 600,
            "max_trigger_age_seconds": 120,
            "run_timeout_seconds": 120,
            "max_queue": 3,
        },
        "runner": {
            "command": cmd,
            "env": {"DSH_HOME": HOME},
            "cwd": str(RUN / "workspace"),
        },
    }
    out = ROOT / "config/fastjudge.yaml"
    out.write_text(
        "# 生成文件：scripts/build-fastjudge-config.py（每次 start 都会重新生成）。"
        "只含只读行情/盯盘 overlay，不含 hub、模拟盘、交易守卫、持仓、X、抓取。\n"
        + json.dumps(cfg, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} and {persona}")


if __name__ == "__main__":
    main()
