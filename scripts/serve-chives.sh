#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
export CHIVES_DATA_DIR="$PWD/user-data"
mechanical_dir="$PWD/public-data/mechanical-cache"
if [[ -d "$PWD/data" && ! -d "$CHIVES_DATA_DIR" ]] &&
  ! compgen -G "$PWD/runtime/data-migration-*/active" >/dev/null; then
  export CHIVES_DATA_DIR="$PWD/data"
  mechanical_dir="$PWD/data"
fi
export DSH_FINANCE_HOME="$CHIVES_DATA_DIR/dsh"
export DSH_FINANCE_OVERLAY="" CHIVES_PAPER_STATE_DIR="$PWD/runtime/paper"
export CN_DAILY_STORE_DB="$mechanical_dir/marketdata/daily.sqlite"
export CHIVES_HARNESS=dsh
mkdir -p "$PWD/runtime/tmp"
export TMPDIR="$PWD/runtime/tmp/" npm_config_cache="$PWD/runtime/npm-cache"
export DSH_HOME="$DSH_FINANCE_HOME" CALENDAR_PYTHON="$HOME/.agents/venvs/chives/bin/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/ms-playwright/browsers"
export PATH="$HOME/.local/bin:$HOME/.agents/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
trap 'bash scripts/chives.sh stop --engines; exit' TERM INT
bash scripts/chives.sh start --engines
while :; do sleep 5 & wait $!; done
