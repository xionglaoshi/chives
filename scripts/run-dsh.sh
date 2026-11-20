#!/bin/bash
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
file="${CHIVES_DATA_DIR:-$root/data}/harness/dsh/version"
[ -f "$file" ] || file="$root/config/dsh-version"
version="$(cat "$file")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][A-Za-z0-9.+-]+)?$ ]] || exit 65
export npm_config_cache="${npm_config_cache:-$HOME/.agents/state/chives-npm}"
exec npx -y "@deepseek-ai/dsh@$version" "$@"
