#!/usr/bin/env bash
# market-watch 引擎启停器：start | stop | restart | status | check | logs
# 配置默认 packages/market-watch/config.yaml（不存在时从 config.example.yaml 复制）。
# 运行产物（pid、日志、sqlite）在 runtime/market/。只启动本仓库的 market-watch，
# 不读取任何密钥，不写仓库外的位置。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packages/market-watch"
PY="$PKG/.venv/bin/python"
CFG="${MARKET_WATCH_CONFIG:-$PKG/config.yaml}"
case "$CFG" in /*) ;; *) CFG="$(cd "$(dirname "$CFG")" 2>/dev/null && pwd)/$(basename "$CFG")" ;; esac
DEFAULT_CFG="$PKG/config.yaml"
# 未显式指定且本机配置尚未创建时，直接用示例配置（示例里的相对路径指向仓库 runtime/ 与 config/）。
if [ "$CFG" = "$DEFAULT_CFG" ] && [ ! -f "$CFG" ]; then CFG="$PKG/config.example.yaml"; fi
RUN="$ROOT/runtime/market"
CACHE="$ROOT/public-data/mechanical-cache/market/market.db"
PID="$RUN/engine.pid"
LOG="$RUN/engine.log"
PORT="$(sed -n 's/^[[:space:]]*port:[[:space:]]*\([0-9]*\).*/\1/p' "$CFG" 2>/dev/null | head -1)"
PORT="${PORT:-8866}"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }
health() { curl -sf --max-time 2 "http://127.0.0.1:$PORT/health"; }

case "${1:-status}" in
  check)
    [ -x "$PY" ] || { echo "缺少 $PY（先在 packages/market-watch 里建 venv 并安装 pytest）"; exit 2; }
    cd "$PKG" && PYTHONPATH="$PKG/src" "$PY" -m market_watch --config "$CFG" --check-config ;;
  start)
    if alive; then echo "已在运行 (pid $(cat "$PID"))"; exit 0; fi
    if curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:$PORT/health"; then
      echo "端口 $PORT 已被占用（不是本脚本启动的引擎），未启动"; exit 1
    fi
    "$0" check >/dev/null || { echo "配置校验失败："; "$0" check; exit 2; }
    CAL="$ROOT/config/trade_calendar.json"
    if [ ! -f "$CAL" ]; then
      echo "警告：交易日历 $CAL 不存在，引擎将降级为工作日判断" >&2
    elif [ -n "$(find "$CAL" -mtime +30 2>/dev/null)" ]; then
      echo "警告：交易日历超过 30 天未更新，请确认 $CAL" >&2
    fi
    mkdir -p "$RUN" "$(dirname "$CACHE")" || exit 1
    if [[ ! -f "$RUN/.mechanical-cache-migrated" && -f "$RUN/market.db" && ! -e "$CACHE" ]]; then
      "$PY" - "$RUN/market.db" "$CACHE" <<'PYTHON' || exit 1
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

source, target = map(Path, sys.argv[1:])
temporary = target.with_suffix(".migrating")
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
    with closing(sqlite3.connect(temporary)) as new:
        old.backup(new)
temporary.replace(target)
PYTHON
    fi
    touch "$RUN/.mechanical-cache-migrated" || exit 1
    rm -f "$PID"
    ( cd "$PKG" && PYTHONPATH="$PKG/src" exec nohup "$PY" -m market_watch --config "$CFG" --out-dir "$RUN" --db-path "$CACHE" >>"$LOG" 2>&1 ) &
    echo $! >"$PID"
    for _ in $(seq 1 120); do sleep 0.5; health >/dev/null && break; done
    if alive && health >/dev/null; then
      echo "已启动 (pid $(cat "$PID"), 127.0.0.1:$PORT)"
    else
      echo "启动失败，见 $LOG"
      if alive; then kill -TERM "$(cat "$PID")" 2>/dev/null; fi
      rm -f "$PID"
      tail -5 "$LOG"; exit 1
    fi ;;
  stop)
    if ! alive; then echo "未在运行"; rm -f "$PID"; exit 0; fi
    kill -TERM "$(cat "$PID")"
    for _ in $(seq 1 20); do alive || break; sleep 0.5; done
    if alive; then echo "未能优雅退出，强制结束"; kill -KILL "$(cat "$PID")"; fi
    rm -f "$PID"; echo "已停止" ;;
  restart) "$0" stop; "$0" start ;;
  status)
    if alive; then echo "运行中 (pid $(cat "$PID"))"; health; echo; else echo "未运行"; exit 3; fi ;;
  logs) tail -n "${2:-50}" "$LOG" ;;
  *) echo "用法: $0 start|stop|restart|status|check|logs [n]"; exit 64 ;;
esac
