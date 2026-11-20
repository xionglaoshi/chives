#!/usr/bin/env bash
# 启动 Chives（金融模式）的 dsh web（独立本机实例）：start | stop | status
#   金融研究预设为默认；加载 scripts/build-finance-bundle.py 的 OVERLAYS 清单（A 股聚焦后不含 openbb / fmp / x）+ 交易守卫；盯盘面板。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIAL="${DSH_FINANCE_TRIAL:-$ROOT/runtime/dsh-web}"
PORT="${DSH_FINANCE_WEB_PORT:-3081}"
LOG="$ROOT/runtime/web.log"
mkdir -p "$ROOT/runtime"
case "${1:-status}" in
  start)
    pgrep -f "dsh web .*--port $PORT" >/dev/null && { echo "已在运行，地址见 $LOG"; exit 0; }
    python3 "$ROOT/scripts/build-finance-bundle.py" >/dev/null || exit 2
    "$ROOT/scripts/watch-engine.sh" status >/dev/null 2>&1 || "$ROOT/scripts/watch-engine.sh" start
    "$ROOT/scripts/market-watch.sh" status >/dev/null 2>&1 || "$ROOT/scripts/market-watch.sh" start
    "$ROOT/scripts/chives-hub.sh" status >/dev/null 2>&1 || "$ROOT/scripts/chives-hub.sh" start
    mkdir -p "$TRIAL/workspace" "$TRIAL/home" || exit 1
    cd "$TRIAL/workspace" && DSH_HOME="$TRIAL/home" nohup "$ROOT/scripts/run-dsh.sh" web \
      --patch "$ROOT/packages/finance-bundle/cordis.patch.yml" --host 127.0.0.1 --port "$PORT" --no-open > "$LOG" 2>&1 &
    for _ in $(seq 1 60); do grep -q "token=" "$LOG" 2>/dev/null && break; sleep 2; done
    grep -o "http://127.0.0.1:$PORT/?token=[^ ]*" "$LOG" | head -1 ;;
  stop) pkill -f "dsh web .*--port $PORT"; echo "已停止" ;;
  status) pgrep -f "dsh web .*--port $PORT" >/dev/null && echo "运行中" || echo "未运行" ;;
  *) echo "用法: $0 start|stop|status"; exit 64 ;;
esac
