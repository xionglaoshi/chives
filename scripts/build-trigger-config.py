#!/usr/bin/env python3
"""Generate config/trigger.yaml and runtime/watch/persona.cordis.yml for the cn-watch-trigger daemon.

The runner is `dsh --profile headless` with the finance persona (presets/finance/{prefix,suffix}.md) and READ-ONLY MCP overlays only:
cn-data, cn-extra, cn-watch, tavily, hub. The paper broker and the trading guard are deliberately NOT included (analysis never trades).
Environment: DSH_FINANCE_HOME (default: Chives data/dsh), DSH_FINANCE_OVERLAY (model provider overlay, optional),
Uses the Chives-selected dsh version. All paths written are absolute (the runner changes its cwd).
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = os.environ.get("DSH_FINANCE_HOME", str(ROOT / "data/dsh"))
MODEL = os.environ.get("DSH_FINANCE_OVERLAY", "")
RUN = ROOT / "runtime/watch"
READ_ONLY = ["cn-data", "cn-extra", "cn-watch", "tavily", "hub"]  # fmp removed for the A-share focus (T113); add it back here to restore


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "analysis-workspace").mkdir(exist_ok=True)
    prefix = (ROOT / "presets/finance/prefix.md").read_text(encoding="utf-8")
    suffix = (ROOT / "presets/finance/suffix.md").read_text(encoding="utf-8")
    persona = RUN / "persona.cordis.yml"
    persona.write_text("- id: system-prompt\n  name: '@deepseek-ai/dsh-system-prompt'\n  config:\n    personaPrefix: " + json.dumps(prefix, ensure_ascii=False)
                       + "\n    personaSuffix: " + json.dumps(suffix, ensure_ascii=False) + "\n", encoding="utf-8")
    cmd = [str(ROOT / "scripts/run-dsh.sh"), "--profile", "headless", *(["--patch", MODEL] if MODEL else []), "--patch", str(persona)]
    for n in READ_ONLY:
        if (ROOT / f"overlays/{n}.cordis.yml").exists():
            cmd += ["--patch", str(ROOT / f"overlays/{n}.cordis.yml")]
    cmd += ["--json", "{prompt}"]
    cfg = {
        "engine": "http://127.0.0.1:8865",
        "state_dir": str(RUN / "analyses"),
        "poll_seconds": 3.0,
        "prompt_template": str(ROOT / "presets/finance/alert-analysis.md"),
        "triggers": [{"rule_ids": ["*"], "codes": ["*"]}],
        "limits": {"max_runs_per_day": 10, "cooldown_seconds": 1800, "max_alert_age_seconds": 600, "run_timeout_seconds": 780, "max_queue": 5},
        "runner": {"command": cmd, "env": {"DSH_HOME": HOME}, "cwd": str(RUN / "analysis-workspace")},
    }
    out = ROOT / "config/trigger.yaml"
    out.write_text("# 生成文件：scripts/build-trigger-config.py（每次 start 都会重新生成）。想改触发规则、预算，请改这个脚本里的默认值或直接编辑后用 `start --keep-config`。\n"
                   + json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} and {persona}")


if __name__ == "__main__":
    main()
