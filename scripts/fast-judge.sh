#!/usr/bin/env bash
# 盘中快速判断守护进程：start [--dry-run] [--keep-config] | stop | restart | status | pause | resume | logs [n]
#   start --dry-run   观察模式：走完全部检查但不调用模型，只在 runtime/fastjudge/state/analyses.jsonl 里记 dry_run
#   pause / resume    熔断：创建/删除 runtime/fastjudge/state/STOP（暂停期间到来的触发不会在恢复后补跑）
# 判断只读：runner 里没有 hub、模拟盘、交易守卫；上下文包已由 hub 冻结嵌入提示词。
# 首次启动只设基线，不处理历史触发。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packages/hub-trigger"
PY="$PKG/.venv/bin/python"
CFG="$ROOT/config/fastjudge.yaml"
HUB="${CHIVES_HUB_URL:-http://127.0.0.1:8867}"
HUB="${HUB%/}"
RUN="$ROOT/runtime/fastjudge"
STATE="$RUN/state"
PID="$RUN/fastjudge.pid"
LOG="$RUN/fastjudge.log"
STOPF="$STATE/STOP"
PYTHONPATH="$PKG/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null && ps -p "$(cat "$PID")" -o command= | grep -q "hub_trigger"; }

case "${1:-status}" in
  start)
    shift; DRY=""; KEEP=""
    for a in "$@"; do case "$a" in --dry-run) DRY="--dry-run";; --keep-config) KEEP=1;; esac; done
    if alive; then echo "已在运行 (pid $(cat "$PID"))"; exit 0; fi
    [ -x "$PY" ] || { echo "缺少 $PY"; exit 2; }
    curl -s --max-time 2 -o /dev/null "$HUB/health" || { echo "hub 没在运行，先 scripts/chives-hub.sh start"; exit 1; }
    mkdir -p "$RUN" "$STATE"; [ -n "$KEEP" ] && [ -f "$CFG" ] || python3 "$ROOT/scripts/build-fastjudge-config.py" || exit 2
    rm -f "$PID"
    ( cd "$PKG" && exec nohup "$PY" -m hub_trigger --config "$CFG" $DRY >>"$LOG" 2>&1 ) &
    echo $! >"$PID"; sleep 2
    if alive; then echo "已启动${DRY:+（观察模式，不调用模型）} (pid $(cat "$PID"))"; else echo "启动失败，见 $LOG"; tail -5 "$LOG"; exit 1; fi ;;
  stop)
    if ! alive; then echo "未在运行"; rm -f "$PID"; exit 0; fi
    kill -TERM "$(cat "$PID")"; for _ in $(seq 1 20); do alive || break; sleep 0.5; done
    alive && { echo "强制结束"; kill -KILL "$(cat "$PID")"; }; rm -f "$PID"; echo "已停止" ;;
  restart) shift; "$0" stop; "$0" start "$@" ;;
  pause)  mkdir -p "$STATE"; : >"$STOPF"; echo "已熔断：新触发不再判断（${STOPF}）" ;;
  resume) rm -f "$STOPF"; echo "已恢复" ;;
  status)
    alive && echo "运行中 (pid $(cat "$PID"))" || echo "未运行"
    [ -f "$STOPF" ] && echo "熔断：开（STOP 文件存在）" || echo "熔断：关"
    F="$STATE/analyses.jsonl"; [ -f "$F" ] && python3 - "$F" <<'PY'
import json,sys,collections
rows=[x for x in (json.loads(l) for l in open(sys.argv[1],encoding="utf-8") if l.strip()) if isinstance(x,dict)]
c=collections.Counter((r["status"]+("/"+r["result"] if r.get("result") else "")+("/"+r["reason"] if r.get("reason") else "")) for r in rows)
print("记录：",len(rows),"条",dict(c))
PY
    exit 0 ;;
  logs) tail -n "${2:-50}" "$LOG" 2>/dev/null || echo "没有日志：$LOG" ;;
  *) echo "用法: $0 start [--dry-run] [--keep-config] | stop | restart | status | pause | resume | logs [n]"; exit 64 ;;
esac
