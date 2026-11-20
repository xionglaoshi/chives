#!/usr/bin/env bash
set -euo pipefail
base=https://150.158.11.154/chives-install
root="${CHIVES_INSTALL_HOME:-$HOME/.chives-install}"
printf '\n  CHIVES  /  安装向导\n  %s · %s\n  安装目录  %s\n\n  uv · Python 3.12 · Node.js · Chromium · Chives 本地服务\n\n  [1/6] 检查分发服务，准备 Python 环境…\n' "$(uname -s)" "$(uname -m)" "$root"
status="$(curl -sS --max-time 15 "$base/status")"
if [ "$status" != enabled ]; then printf '%s\n' "$status" >&2; exit 1; fi
case "$(uname -s)" in Darwin) os=apple-darwin;; Linux) os=unknown-linux-gnu; if { ldd --version 2>&1 || true; } | grep -i musl >/dev/null; then os=unknown-linux-musl; fi;; *) exit 1;; esac
case "$(uname -m)" in x86_64|amd64) cpu=x86_64;; arm64|aarch64) cpu=aarch64;; *) echo '暂不支持该处理器'; exit 1;; esac
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$root/tools"
version="$(curl -fsS --retry 2 "$base/assets/uv-version")"
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
name="uv-$cpu-$os"
uv="$root/tools/uv-$version-$cpu-$os"
if [ ! -x "$uv" ]; then
  echo "  下载 uv $version"
  url="$base/assets/uv/$version/$name.tar.gz"
  curl -f --progress-bar --retry 2 "$url" -o "$work/uv.tgz"
  expected="$(curl -fsS "$url.sha256" | awk '{print $1}')"
  if command -v sha256sum >/dev/null; then actual="$(sha256sum "$work/uv.tgz")"; else actual="$(shasum -a 256 "$work/uv.tgz")"; fi
  [[ "${actual%% *}" = "$expected" ]] || { echo 'uv 校验失败'; exit 1; }
  tar xzf "$work/uv.tgz" -C "$work" "$name/uv"
  tmp="$(mktemp "$root/tools/.uv.XXXXXX")"
  install -m 755 "$work/$name/uv" "$tmp"
  mv -f "$tmp" "$uv"
else echo "  已复用 uv $version"; fi
curl -fsS --retry 2 "$base/install.py" -o "$work/install.py"
export CHIVES_UV="$uv" UV_PYTHON_INSTALL_MIRROR="$base/assets/python" UV_NO_CONFIG=1
export PYTHONUTF8=1 UV_PYTHON_INSTALL_DIR="$root/tools/python" UV_MANAGED_PYTHON=1
"$uv" python install 3.12 --upgrade --no-bin
cd "$root"
"$uv" run --no-project --python 3.12 python "$work/install.py" "$root"
