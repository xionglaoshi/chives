#!/bin/bash
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
data="$root/user-data"
if [[ -d "$root/data" && ! -d "$data" ]] &&
  ! compgen -G "$root/runtime/data-migration-*/active" >/dev/null; then
  data="$root/data"
fi
file="${CHIVES_DATA_DIR:-$data}/harness/dsh/version"
[ -f "$file" ] || file="$root/config/dsh-version"
version="$(cat "$file")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][A-Za-z0-9.+-]+)?$ ]] || exit 65
export npm_config_cache="${npm_config_cache:-$root/runtime/npm-cache}"
exec npx -y "@deepseek-ai/dsh@$version" "$@"
