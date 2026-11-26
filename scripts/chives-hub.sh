#!/usr/bin/env bash
# chives-signals 启停器：start | stop | restart | status | check | logs
# 配置默认 packages/chives-signals/config.yaml（不存在时用 config.example.yaml）。
# 运行产物（pid、日志、sqlite）在 runtime/hub/。只启动本仓库的 chives-signals，
# 不读取任何密钥，不写仓库外的位置。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packages/chives-signals"
PY="$PKG/.venv/bin/python"
CFG="${CHIVES_HUB_CONFIG:-$PKG/config.yaml}"
case "$CFG" in /*) ;; *) CFG="$(cd "$(dirname "$CFG")" 2>/dev/null && pwd)/$(basename "$CFG")" ;; esac
DEFAULT_CFG="$PKG/config.yaml"
if [ "$CFG" = "$DEFAULT_CFG" ] && [ ! -f "$CFG" ]; then CFG="$PKG/config.example.yaml"; fi
RUN="$ROOT/runtime/hub"
USER_DATA="${CHIVES_DATA_DIR:-$ROOT/user-data}"
STATE="$USER_DATA/hub/hub.db"
PID="$RUN/hub.pid"
LOG="$RUN/hub.log"
PORT="$(sed -n 's/^[[:space:]]*port:[[:space:]]*\([0-9]*\).*/\1/p' "$CFG" 2>/dev/null | head -1)"
PORT="${PORT:-8867}"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }
health() { curl -sf --max-time 2 "http://127.0.0.1:$PORT/health"; }

case "${1:-status}" in
  check)
    [ -x "$PY" ] || { echo "缺少 $PY（先在 packages/chives-signals 里建 venv 并安装 pytest）"; exit 2; }
    cd "$PKG" && PYTHONPATH="$PKG/src" "$PY" -m chives_signals --config "$CFG" --check-config ;;
  start)
    if alive; then echo "已在运行 (pid $(cat "$PID"))"; exit 0; fi
    if curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:$PORT/health"; then
      echo "端口 $PORT 已被占用（不是本脚本启动的 hub），未启动"; exit 1
    fi
    "$0" check >/dev/null || { echo "配置校验失败："; "$0" check; exit 2; }
    # 依赖服务只提示，不阻塞（上游不可达时 /health 会标注，已有信号照常提供）。
    curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:8865/health" \
      || echo "警告：chives-radar (127.0.0.1:8865) 未响应，个股告警暂不可用" >&2
    curl -sf --max-time 1 -o /dev/null "http://127.0.0.1:8866/health" \
      || echo "警告：market-watch (127.0.0.1:8866) 未响应，板块告警暂不可用" >&2
    # 持仓文件按 DSH_HOME 解析（与 dsh 实例一致）；默认使用 Chives 的本地内核目录，只用于定位 finance-portfolio.json。
    export DSH_HOME="${DSH_HOME:-${DSH_FINANCE_HOME:-${DSH_FINANCE_TRIAL:+$DSH_FINANCE_TRIAL/home}}}"
    export DSH_HOME="${DSH_HOME:-$USER_DATA/dsh}"
    mkdir -p "$RUN" "$(dirname "$STATE")" || exit 1
    if [[ ! -f "$RUN/.user-state-migrated" && -f "$RUN/hub.db" && ! -e "$STATE" ]]; then
      "$PY" - "$RUN/hub.db" "$STATE" <<'PYTHON' || exit 1
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
    touch "$RUN/.user-state-migrated" || exit 1
    rm -f "$PID"
    ( cd "$PKG" && PYTHONPATH="$PKG/src" exec nohup "$PY" -m chives_signals --config "$CFG" --out-dir "$RUN" --db-path "$STATE" >>"$LOG" 2>&1 ) &
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
