#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
export CHIVES_DATA_DIR="$PWD/data" DSH_FINANCE_HOME="$PWD/data/dsh"
export DSH_FINANCE_OVERLAY="" CHIVES_PAPER_STATE_DIR="$PWD/runtime/paper"
export CN_DAILY_STORE_DB="$PWD/data/marketdata/daily.sqlite"
export CHIVES_HARNESS=dsh
export npm_config_cache="$HOME/.agents/state/chives-npm"
export DSH_HOME="$DSH_FINANCE_HOME" CALENDAR_PYTHON="$HOME/.agents/venvs/chives/bin/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/ms-playwright/browsers"
export PATH="$HOME/.local/bin:$HOME/.agents/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
trap 'bash scripts/chives.sh stop --engines; exit' TERM INT
bash scripts/chives.sh start --engines
while :; do sleep 5 & wait $!; done
