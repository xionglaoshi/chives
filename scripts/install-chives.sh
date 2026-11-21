#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
env_dir="$HOME/.agents/venvs/chives"
store="$HOME/.agents/state/chives-pnpm"
[ -x "$env_dir/bin/python" ] || uv venv --python 3.12 "$env_dir"
packages=()
for manifest in packages/*/pyproject.toml; do packages+=("${manifest%/pyproject.toml}"); done
editable=()
for package in "${packages[@]}"; do editable+=(-e "$package"); done
uv pip install --python "$env_dir/bin/python" 'qrcode[pil]' 'websockets>=15,<17' "${editable[@]}"
bash scripts/install-browser.sh
for package in "${packages[@]}"; do
    link="$package/.venv"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$env_dir" ]; then continue; fi
    if [ -e "$link" ] || [ -L "$link" ]; then echo "已有依赖目录：$link" >&2; exit 1; fi
    ln -s "$env_dir" "$link"
done
pnpm install --frozen-lockfile --store-dir "$store"
pnpm build
bash scripts/run-dsh.sh --version
"$env_dir/bin/python" scripts/chives_cli.py source --register
