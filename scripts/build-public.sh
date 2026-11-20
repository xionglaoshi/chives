#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
pnpm --dir apps/web exec vite build --base=/chives/ --outDir "$PWD/runtime/public-dist.next" --emptyOutDir
mkdir -p runtime/public-dist/assets
cp runtime/public-dist.next/assets/* runtime/public-dist/assets/
cp runtime/public-dist.next/chives.svg runtime/public-dist/
cp runtime/public-dist.next/index.html runtime/public-dist/index.next
mv runtime/public-dist/index.next runtime/public-dist/index.html
