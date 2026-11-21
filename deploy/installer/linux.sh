#!/usr/bin/env bash
# Compatibility entry. A checkout uses its sibling, a piped script uses GitHub.
set -eu
if [[ -n ${BASH_SOURCE[0]:-} && -f "$(dirname "${BASH_SOURCE[0]}")/../installer.sh" ]]; then
    exec bash "$(dirname "${BASH_SOURCE[0]}")/../installer.sh"
fi
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -q -fsSL --proto '=https' https://raw.githubusercontent.com/xionglaoshi/chives/main/deploy/installer.sh -o "$tmp"
bash "$tmp"
