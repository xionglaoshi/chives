#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
env_dir="$PWD/.venv"
legacy_env="$HOME/.agents/venvs/chives"
store="$PWD/.pnpm-store"
mkdir -p "$PWD/runtime/tmp"
export TMPDIR="$PWD/runtime/tmp/" UV_CACHE_DIR="$PWD/runtime/uv-cache" UV_PYTHON_INSTALL_DIR="$PWD/runtime/python"
[ -x "$env_dir/bin/python" ] || uv venv --managed-python --python 3.12 "$env_dir"
packages=()
for manifest in packages/*/pyproject.toml; do packages+=("${manifest%/pyproject.toml}"); done
editable=()
for package in "${packages[@]}"; do editable+=(-e "$package"); done
uv pip install --python "$env_dir/bin/python" 'qrcode[pil]' 'cryptography>=42' 'websockets>=15,<17' "${editable[@]}"
bash scripts/install-browser.sh
for package in "${packages[@]}"; do
    link="$package/.venv"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$env_dir" ]; then continue; fi
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$legacy_env" ]; then
        temporary_link="$link.chives-new"
        ln -s "$env_dir" "$temporary_link"
        "$env_dir/bin/python" -c 'import os, sys; os.replace(*sys.argv[1:])' "$temporary_link" "$link"
        continue
    fi
    if [ -e "$link" ] || [ -L "$link" ]; then echo "已有依赖目录：$link" >&2; exit 1; fi
    ln -s "$env_dir" "$link"
done
default_user_dir="$PWD/user-data"
if [[ -d "$PWD/data" && ! -d "$default_user_dir" ]] &&
  ! compgen -G "$PWD/runtime/data-migration-*/active" >/dev/null; then
    default_user_dir="$PWD/data"
fi
"$env_dir/bin/python" scripts/user_archive.py --data "${CHIVES_DATA_DIR:-$default_user_dir}" init
pnpm install --frozen-lockfile --store-dir "$store"
pnpm build
bash scripts/run-dsh.sh --version
"$env_dir/bin/python" scripts/chives_cli.py source --register
