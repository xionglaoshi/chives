#!/usr/bin/env bash
# 告警触发分析守护进程：start [--dry-run] [--keep-config] | stop | restart | status | pause | resume | logs [n]
#   start --dry-run   观察模式：走完全部检查但不调用模型，只在 runtime/watch/analyses/analyses.jsonl 里记 dry_run
#   pause / resume    熔断：创建/删除 runtime/watch/analyses/STOP（暂停期间到来的告警不会在恢复后补跑）
# 分析只读：runner 里没有模拟盘和交易守卫。首次启动只设基线，不分析历史告警。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packages/cn-watch-trigger"
PY="$PKG/.venv/bin/python"
CFG="$ROOT/config/trigger.yaml"
RUN="$ROOT/runtime/watch"
PID="$RUN/trigger.pid"
LOG="$RUN/trigger.log"
STOPF="$RUN/analyses/STOP"
alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null && ps -p "$(cat "$PID")" -o command= | grep -q "cn_watch_trigger"; }

case "${1:-status}" in
  start)
    shift; DRY=""; KEEP=""
    for a in "$@"; do case "$a" in --dry-run) DRY="--dry-run";; --keep-config) KEEP=1;; esac; done
    if alive; then echo "已在运行 (pid $(cat "$PID"))"; exit 0; fi
    [ -x "$PY" ] || { echo "缺少 $PY"; exit 2; }
    curl -s --max-time 2 -o /dev/null "http://127.0.0.1:8865/health" || { echo "盯盘引擎没在运行，先 scripts/watch-engine.sh start"; exit 1; }
    mkdir -p "$RUN"; [ -n "$KEEP" ] && [ -f "$CFG" ] || python3 "$ROOT/scripts/build-trigger-config.py" || exit 2
    rm -f "$PID"
    ( cd "$PKG" && exec nohup "$PY" -m cn_watch_trigger --config "$CFG" $DRY >>"$LOG" 2>&1 ) &
    echo $! >"$PID"; sleep 2
    if alive; then echo "已启动${DRY:+（观察模式，不调用模型）} (pid $(cat "$PID"))"; else echo "启动失败，见 $LOG"; tail -5 "$LOG"; exit 1; fi ;;
  stop)
    if ! alive; then echo "未在运行"; rm -f "$PID"; exit 0; fi
    kill -TERM "$(cat "$PID")"; for _ in $(seq 1 20); do alive || break; sleep 0.5; done
    alive && { echo "强制结束"; kill -KILL "$(cat "$PID")"; }; rm -f "$PID"; echo "已停止" ;;
  restart) shift; "$0" stop; "$0" start "$@" ;;
  pause)  mkdir -p "$RUN/analyses"; : >"$STOPF"; echo "已熔断：新告警不再分析（$STOPF）" ;;
  resume) rm -f "$STOPF"; echo "已恢复" ;;
  status)
    alive && echo "运行中 (pid $(cat "$PID"))" || echo "未运行"
    [ -f "$STOPF" ] && echo "熔断：开（STOP 文件存在）" || echo "熔断：关"
    F="$RUN/analyses/analyses.jsonl"; [ -f "$F" ] && python3 - "$F" <<'PY'
import json,sys,collections
rows=[json.loads(l) for l in open(sys.argv[1],encoding="utf-8") if l.strip()]
c=collections.Counter((r["status"]+("/"+r["reason"] if r.get("reason") else "")) for r in rows)
print("记录：",len(rows),"条",dict(c))
PY
    alive || exit 3 ;;
  logs) tail -${2:-50} "$LOG" ;;
  *) echo "用法: $0 start [--dry-run] [--keep-config] | stop | restart | status | pause | resume | logs [n]"; exit 64 ;;
esac
