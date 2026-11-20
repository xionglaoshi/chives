#!/usr/bin/env bash
# 给同一 WiFi 下的朋友开一个独立的 dsh web 实例（完整功能，独立会话目录，只绑定 WiFi 地址，到点自动关闭）。
#   scripts/guest-web.sh start [小时数，默认 2] | stop | status
# 注意：这个实例的智能体有完整工具（含 bash 和读文件）。链接等于该实例的全部权限，只发给你信任的人，用完就 stop。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUEST="${DSH_FINANCE_GUEST:-$ROOT/runtime/dsh-guest}"
PORT="${DSH_FINANCE_GUEST_PORT:-3082}"
LOG="$ROOT/runtime/guest-web.log"
TIMER="$ROOT/runtime/guest-timer.pid"
kill_timer() { [ -f "$TIMER" ] && { pkill -P "$(cat "$TIMER")" 2>/dev/null; kill "$(cat "$TIMER")" 2>/dev/null; rm -f "$TIMER"; }; }
IP="${DSH_FINANCE_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)}"
mkdir -p "$ROOT/runtime"
case "${1:-status}" in
  start)
    [ -n "$IP" ] || { echo "没有找到 WiFi 地址（en0/en1）；确认已连上 WiFi"; exit 1; }
    pgrep -f "dsh web .*--port $PORT" >/dev/null && { echo "已在运行："; grep -o "http://[^ ]*token=[^ ]*" "$LOG" | tail -1; exit 0; }
    H="${2:-2}"
    python3 "$ROOT/scripts/build-finance-bundle.py" >/dev/null || exit 2
    "$ROOT/scripts/watch-engine.sh" status >/dev/null 2>&1 || "$ROOT/scripts/watch-engine.sh" start
    mkdir -p "$GUEST/workspace" "$GUEST/home" || exit 1
    cd "$GUEST/workspace" && DSH_HOME="$GUEST/home" nohup "$ROOT/scripts/run-dsh.sh" web \
      --patch "$ROOT/packages/finance-bundle/cordis.patch.yml" --host "$IP" --port "$PORT" --no-open \
      --public-url "http://$IP:$PORT/" --trusted-host "$IP:$PORT" > "$LOG" 2>&1 &
    kill_timer
    ( sleep $((H*3600)); "$0" stop >/dev/null 2>&1 ) >/dev/null 2>&1 &
    echo $! > "$TIMER"
    for _ in $(seq 1 90); do grep -q "token=" "$LOG" 2>/dev/null && break; sleep 2; done
    echo "到点自动关闭：$H 小时后。链接："; grep -o "http://[^ ]*token=[^ ]*" "$LOG" | head -1 ;;
  stop) kill_timer; pkill -f "dsh web .*--port $PORT"; echo "访客实例已停止" ;;
  status) pgrep -f "dsh web .*--port $PORT" >/dev/null && { echo "运行中："; grep -o "http://[^ ]*token=[^ ]*" "$LOG" | tail -1 | sed -E 's/token=.*/token=<见日志>/'; } || echo "未运行" ;;
  *) echo "用法: $0 start [小时] | stop | status"; exit 64 ;;
esac
