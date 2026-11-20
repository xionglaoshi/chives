#!/usr/bin/env bash
set -euo pipefail
base=https://150.158.11.154/chives-install
status="$(curl -sS --max-time 15 "$base/status")"
if [ "$status" != enabled ]; then printf '%s\n' "$status" >&2; exit 1; fi
case "$(uname -s)" in Darwin|Linux) ;; *) echo '请使用 Windows PowerShell 安装入口。' >&2; exit 1;; esac
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
root="${CHIVES_INSTALL_HOME:-$HOME/.chives-install}"
mkdir -p "$root/tools"
curl -fsSL --max-time 60 "$base/install.py" -o "$work/install.py"
if [ ! -x "$root/tools/uv" ]; then
  curl -fsSL --max-time 60 https://astral.sh/uv/install.sh -o "$work/uv-install.sh"
  UV_UNMANAGED_INSTALL="$root/tools" sh "$work/uv-install.sh"
fi
cd "$root"
UV_NO_CONFIG=1 "$root/tools/uv" run --no-project --python 3.12 python "$work/install.py" "$root"
