#!/usr/bin/env bash
# Chives 2.0 本机启动器：start | stop | restart | status | logs
# 起数据网关（packages/cn-market-gateway，127.0.0.1:8868）、策略服务（packages/strategy-hub，127.0.0.1:8869）、Chives Server（apps/server，127.0.0.1:8880）与 Web（apps/web，Vite 127.0.0.1:8888）；
# 加 --engines 时按需起三个引擎（cn-watch 8865、market-watch 8866、chives-hub 8867，各自的脚本负责）。
# 运行产物在 runtime/chives/。全新安装使用 user-data/ 和 public-data/。
# 不读取任何密钥：DSH_FINANCE_HOME / DSH_FINANCE_OVERLAY 只作为路径传给服务端。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/runtime/chives"
mkdir -p "$RUN"
SERVER_PORT="${CHIVES_PORT:-8880}"
WEB_PORT="${CHIVES_WEB_PORT:-8888}"
GATEWAY_PORT="${CN_MARKET_PORT:-8868}"
GATEWAY_DIR="$ROOT/packages/cn-market-gateway"
STRATEGY_PORT="${STRATEGY_HUB_PORT:-8869}"
STRATEGY_DIR="$ROOT/packages/strategy-hub"
default_user_dir="$ROOT/user-data"
default_mechanical_dir="$ROOT/public-data/mechanical-cache"
if [[ -d "$ROOT/data" && ! -d "$default_user_dir" ]] &&
  ! compgen -G "$ROOT/runtime/data-migration-*/active" >/dev/null; then
  default_user_dir="$ROOT/data"
  default_mechanical_dir="$ROOT/data"
fi
export CHIVES_DATA_DIR="${CHIVES_DATA_DIR:-$default_user_dir}"
export CN_DAILY_STORE_DB="${CN_DAILY_STORE_DB:-$default_mechanical_dir/marketdata/daily.sqlite}"
# Keep existing workspaces readable until the migration has been prepared.
if [[ -z "${CHIVES_WORKSPACE_DIR:-}" && "$CHIVES_DATA_DIR" == "$default_user_dir" ]]; then
  workspace_ready=true
  if [[ ! -d "$ROOT/workspace/bots" ]]; then
    for legacy_workspace in "$CHIVES_DATA_DIR"/bots/*/workspace; do
      if [[ -d "$legacy_workspace" ]]; then
        workspace_ready=false
        break
      fi
    done
  fi
  if "$workspace_ready"; then
    export CHIVES_WORKSPACE_DIR="$ROOT/workspace"
  fi
fi
export DSH_FINANCE_HOME="${DSH_FINANCE_HOME:-$CHIVES_DATA_DIR/dsh}"
if [[ "$CHIVES_DATA_DIR" == "$ROOT/user-data" ]]; then
  export DSH_FINANCE_PROFILE_DIR="$CHIVES_DATA_DIR/profile"
fi
export DSH_FINANCE_OVERLAY="${DSH_FINANCE_OVERLAY:-}"
export CHIVES_DEFAULT_ROUTE="${CHIVES_DEFAULT_ROUTE:-huosan/deepseek-v4.1-flash}"
export CHIVES_PORT="$SERVER_PORT"

ENGINES=0
for a in "$@"; do [ "$a" = "--engines" ] && ENGINES=1; done

alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
up() { curl -sf --max-time 2 -o /dev/null "$1"; }

start_one() { # name dir cmd...
  local name="$1" dir="$2"; shift 2
  if alive "$name"; then echo "$name 已在运行 (pid $(cat "$RUN/$name.pid"))"; return 0; fi
  # Redirect the whole group (not just the command) so no inherited fd keeps a caller's pipe open.
  (cd "$dir" && exec nohup "$@") >"$RUN/$name.log" 2>&1 </dev/null &
  echo $! >"$RUN/$name.pid"
  echo "$name 启动中 (pid $(cat "$RUN/$name.pid"))，日志 $RUN/$name.log"
}

stop_one() {
  local name="$1"
  if alive "$name"; then
    local pid; pid="$(cat "$RUN/$name.pid")"
    pkill -TERM -P "$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && { pkill -KILL -P "$pid" 2>/dev/null; kill -KILL "$pid" 2>/dev/null; }
    echo "$name 已停止"
  else
    echo "$name 未运行"
  fi
  rm -f "$RUN/$name.pid"
}

engines() { # start|stop|status
  for s in watch-engine market-watch chives-hub; do
    [ -x "$ROOT/scripts/$s.sh" ] || continue
    echo "== $s"; "$ROOT/scripts/$s.sh" "$1" || true
  done
}

case "${1:-status}" in
  start)
    [ -d "$ROOT/node_modules" ] || { echo "先在仓库根运行 pnpm install"; exit 2; }
    (cd "$ROOT" && pnpm --filter @chives/chives-mcp build >"$RUN/build.log" 2>&1) || { echo "chives-mcp 构建失败，见 $RUN/build.log"; exit 2; }
    if ! alive server && up "http://127.0.0.1:$SERVER_PORT/api/health"; then echo "端口 $SERVER_PORT 已被占用，未启动"; exit 1; fi
    # The data gateway first: bots mount its MCP forwarder (cn_market) when their process starts.
    if [ -x "$GATEWAY_DIR/.venv/bin/cn-market-gateway" ]; then
      if ! alive gateway && up "http://127.0.0.1:$GATEWAY_PORT/health"; then echo "端口 $GATEWAY_PORT 已被占用，数据网关未启动"
      else
        start_one gateway "$GATEWAY_DIR" "$GATEWAY_DIR/.venv/bin/cn-market-gateway" serve --host 127.0.0.1 --port "$GATEWAY_PORT"
        for _ in $(seq 1 30); do up "http://127.0.0.1:$GATEWAY_PORT/health" && break; sleep 0.5; done
        up "http://127.0.0.1:$GATEWAY_PORT/health" && echo "gateway 就绪 http://127.0.0.1:$GATEWAY_PORT" || echo "gateway 未就绪，见 $RUN/gateway.log"
      fi
    else
      echo "数据网关未安装（$GATEWAY_DIR/.venv 不存在），bot 的行情与研究数据将不可用"
    fi
    # Strategy service (rule layer 2): reads the local daily store and engine output only.
    if [ -x "$STRATEGY_DIR/.venv/bin/python" ]; then
      start_one strategy "$STRATEGY_DIR" "$STRATEGY_DIR/.venv/bin/python" -m strategy_hub --port "$STRATEGY_PORT"
      for _ in $(seq 1 20); do up "http://127.0.0.1:$STRATEGY_PORT/health" && break; sleep 0.5; done
      up "http://127.0.0.1:$STRATEGY_PORT/health" && echo "strategy 就绪 http://127.0.0.1:$STRATEGY_PORT" || echo "strategy 未就绪（首次启动可能在补算），见 $RUN/strategy.log"
    else
      echo "策略服务未安装（$STRATEGY_DIR/.venv 不存在），策略面板与主升浪 bot 不可用"
    fi
    start_one server "$ROOT/apps/server" "$ROOT/apps/server/node_modules/.bin/tsx" src/main.ts
    start_one web "$ROOT/apps/web" "$ROOT/apps/web/node_modules/.bin/vite" --host 127.0.0.1 --port "$WEB_PORT" --strictPort
    for _ in $(seq 1 40); do up "http://127.0.0.1:$SERVER_PORT/api/health" && up "http://127.0.0.1:$WEB_PORT/" && break; sleep 0.5; done
    up "http://127.0.0.1:$SERVER_PORT/api/health" && echo "server 就绪 http://127.0.0.1:$SERVER_PORT" || echo "server 未就绪，见 $RUN/server.log"
    up "http://127.0.0.1:$WEB_PORT/" && echo "web 就绪 http://127.0.0.1:$WEB_PORT" || echo "web 未就绪，见 $RUN/web.log"
    if [ "$ENGINES" = 1 ]; then engines start; fi
    ;;
  stop)
    stop_one web; stop_one server; stop_one strategy; stop_one gateway
    if [ "$ENGINES" = 1 ]; then engines stop; fi
    ;;
  restart) "$0" stop "$@"; shift; "$0" start "$@" ;;
  status)
    for n in gateway strategy server web; do if alive "$n"; then echo "$n 运行中 (pid $(cat "$RUN/$n.pid"))"; else echo "$n 未运行"; fi; done
    up "http://127.0.0.1:$SERVER_PORT/api/health" && echo "server health ok" || echo "server health 不可达"
    up "http://127.0.0.1:$GATEWAY_PORT/health" && echo "gateway health ok" || echo "gateway health 不可达"
    up "http://127.0.0.1:$STRATEGY_PORT/health" && echo "strategy health ok" || echo "strategy health 不可达"
    if [ "$ENGINES" = 1 ]; then engines status; fi
    ;;
  logs) tail -n "${2:-60}" "$RUN/server.log" ;;
  *) echo "用法: $0 start|stop|restart|status|logs [--engines]"; exit 2 ;;
esac
