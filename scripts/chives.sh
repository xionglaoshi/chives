#!/usr/bin/env bash
# Chives 2.0 本机启动器：start | stop | restart | status | logs
# 起数据网关（packages/chives-data，127.0.0.1:8868）、策略服务（packages/chives-strategy，127.0.0.1:8869）、Chives Server（apps/server，127.0.0.1:8880）与 Web（apps/web，Vite 127.0.0.1:8888）；
# 加 --engines 时按需起三个引擎（chives-radar 8865、chives-compass 8866、chives-signals 8867，各自的脚本负责）。
# 运行产物在 runtime/chives/。全新安装使用 user-data/ 和 public-data/。
# 不读取任何密钥：DSH_FINANCE_HOME / DSH_FINANCE_OVERLAY 只作为路径传给服务端。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/runtime/chives"
mkdir -p "$RUN" "$ROOT/runtime/tmp"
export TMPDIR="$ROOT/runtime/tmp/"
export npm_config_cache="${npm_config_cache:-$ROOT/runtime/npm-cache}"
SERVER_PORT="${CHIVES_PORT:-8880}"
WEB_PORT="${CHIVES_WEB_PORT:-8888}"
GATEWAY_PORT="${CN_MARKET_PORT:-8868}"
GATEWAY_DIR="$ROOT/packages/chives-data"
STRATEGY_PORT="${STRATEGY_HUB_PORT:-8869}"
STRATEGY_DIR="$ROOT/packages/chives-strategy"
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
export CHIVES_ENVIRONMENT="${CHIVES_ENVIRONMENT:-development}"
export CALENDAR_PYTHON="${CALENDAR_PYTHON:-$ROOT/.venv/bin/python}"

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

start_service() {
  local name="$1" port="$2" dir="$3" command="$4"
  shift 4
  [ -x "$command" ] || { echo "$name 缺少启动命令 $command" >&2; return 1; }
  if ! alive "$name" && up "http://127.0.0.1:$port/health"; then
    echo "$name 端口 $port 已由其他进程提供健康接口"
    return 0
  fi
  start_one "$name" "$dir" "$command" "$@"
  for _ in $(seq 1 30); do
    if up "http://127.0.0.1:$port/health"; then echo "$name 就绪 http://127.0.0.1:$port"; return 0; fi
    alive "$name" || break
    sleep 0.5
  done
  echo "$name 未就绪，见 $RUN/$name.log" >&2
  return 1
}

start_engine() {
  case "$1" in
    gateway) start_service gateway "$GATEWAY_PORT" "$GATEWAY_DIR" "$GATEWAY_DIR/.venv/bin/chives-data" serve --host 127.0.0.1 --port "$GATEWAY_PORT" ;;
    strategy) start_service strategy "$STRATEGY_PORT" "$STRATEGY_DIR" "$STRATEGY_DIR/.venv/bin/python" -m chives_strategy --port "$STRATEGY_PORT" ;;
    watch-engine|market-watch|chives-hub) "$ROOT/scripts/$1.sh" start ;;
    *) return 64 ;;
  esac
}

case "${1:-status}" in
  recover-engine)
    service="${2:-}"
    case "$service" in
      gateway) pid_file="$RUN/gateway.pid"; expected='/bin/chives-data serve ' ;;
      strategy) pid_file="$RUN/strategy.pid"; expected=' -m chives_strategy ' ;;
      watch-engine) pid_file="$ROOT/runtime/watch/engine.pid"; expected=' -m chives_radar ' ;;
      market-watch) pid_file="$ROOT/runtime/market/engine.pid"; expected=' -m chives_compass ' ;;
      chives-hub) pid_file="$ROOT/runtime/hub/hub.pid"; expected=' -m chives_signals ' ;;
      *) echo "未知后台引擎" >&2; exit 64 ;;
    esac
    if [[ -f "$pid_file" ]]; then
      service_pid="$(cat "$pid_file")"
      if ! [[ "$service_pid" =~ ^[1-9][0-9]*$ ]]; then
        echo "$service PID 文件无效：$pid_file" >&2
        exit 1
      fi
      if kill -0 "$service_pid" 2>/dev/null &&
         ! ps -p "$service_pid" -o command= | grep -Fq -- "$expected"; then
        echo "$service PID 已由其他进程使用：$service_pid" >&2
        exit 1
      fi
    fi
    case "$service" in
      gateway|strategy)
        if alive "$service"; then stop_one "$service"; fi
        start_engine "$service" ;;
      *) "$ROOT/scripts/$service.sh" restart ;;
    esac ;;
  start)
    [ -d "$ROOT/node_modules" ] || { echo "先在仓库根运行 pnpm install"; exit 2; }
    (cd "$ROOT" && pnpm --filter @chives/chives-mcp build >"$RUN/build.log" 2>&1) || { echo "chives-mcp 构建失败，见 $RUN/build.log"; exit 2; }
    if ! alive server && up "http://127.0.0.1:$SERVER_PORT/api/health"; then echo "端口 $SERVER_PORT 已被占用，未启动"; exit 1; fi
    start_engine gateway || true
    start_engine strategy || true
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
