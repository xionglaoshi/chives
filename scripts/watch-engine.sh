#!/usr/bin/env bash
# 盯盘引擎的常驻启动器：start | stop | restart | status | check | logs
# 配置 config/watch.yaml；进程日志在 runtime/watch/，盯盘状态在用户数据目录。
# 只启动本仓库的 cn-watch，不读取任何密钥，不写仓库外的位置。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packages/cn-watch"
PY="$PKG/.venv/bin/python"
CFG="${WATCH_CONFIG:-$ROOT/config/watch.yaml}"
RUN="$ROOT/runtime/watch"
STATE="${CHIVES_DATA_DIR:-$ROOT/user-data}/watch-engine"
PID="$RUN/engine.pid"
LOG="$RUN/engine.log"
PORT="$(sed -n 's/^api:.*port: *\([0-9]*\).*/\1/p' "$CFG" 2>/dev/null | head -1)"; PORT="${PORT:-8865}"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null && ps -p "$(cat "$PID")" -o command= | grep -q "cn_watch"; }
health() { curl -s --max-time 2 "http://127.0.0.1:$PORT/health"; }

case "${1:-status}" in
  check)
    [ -x "$PY" ] || { echo "缺少 $PY（先在 packages/cn-watch 里建 venv）"; exit 2; }
    cd "$PKG" && "$PY" -m cn_watch --config "$CFG" --check-config ;;
  start)
    if alive; then echo "已在运行 (pid $(cat "$PID"))"; exit 0; fi
    if curl -s --max-time 1 -o /dev/null "http://127.0.0.1:$PORT/health"; then echo "端口 $PORT 已被占用（不是本脚本启动的引擎），未启动"; exit 1; fi
    CAL="$ROOT/config/trade_calendar.json"
    if grep -q "source: file" "$CFG" 2>/dev/null && { [ ! -f "$CAL" ] || [ -n "$(find "$CAL" -mtime +20 2>/dev/null)" ]; }; then
      VPY="${CALENDAR_PYTHON:-$ROOT/.venv/bin/python}"
      "$VPY" -I "$ROOT/scripts/refresh-trade-calendar.py" || echo "警告：交易日历刷新失败，沿用现有文件" >&2
    fi
    "$0" check >/dev/null || { echo "配置校验失败："; "$0" check; exit 2; }
    mkdir -p "$RUN" "$STATE" || exit 1
    if [[ ! -f "$RUN/.user-state-migrated" ]]; then
      for name in alerts.jsonl polls.jsonl state.json plans.runtime.json watchlist.runtime.json rules.runtime.json; do
        if [[ -f "$RUN/$name" && ! -e "$STATE/$name" ]]; then
          cp -p "$RUN/$name" "$STATE/$name.migrating" &&
            mv "$STATE/$name.migrating" "$STATE/$name" || exit 1
        fi
      done
      touch "$RUN/.user-state-migrated" || exit 1
    fi
    rm -f "$PID"
    ( cd "$PKG" && exec nohup "$PY" -m cn_watch --config "$CFG" --out-dir "$STATE" >>"$LOG" 2>&1 ) &
    echo $! >"$PID"
    for _ in $(seq 1 20); do sleep 0.5; health >/dev/null && break; done
    if alive && health >/dev/null; then echo "已启动 (pid $(cat "$PID"), 127.0.0.1:$PORT)"; else echo "启动失败，见 $LOG"; tail -5 "$LOG"; exit 1; fi ;;
  stop)
    if ! alive; then echo "未在运行"; rm -f "$PID"; exit 0; fi
    kill -TERM "$(cat "$PID")"
    for _ in $(seq 1 20); do alive || break; sleep 0.5; done
    if alive; then echo "未能优雅退出，强制结束"; kill -KILL "$(cat "$PID")"; fi
    rm -f "$PID"; echo "已停止" ;;
  restart) "$0" stop; "$0" start ;;
  status)
    if alive; then echo "运行中 (pid $(cat "$PID"))"; health; echo; else echo "未运行"; exit 3; fi ;;
  logs) tail -${2:-50} "$LOG" ;;
  *) echo "用法: $0 start|stop|restart|status|check|logs [n]"; exit 64 ;;
esac
