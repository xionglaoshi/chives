#!/usr/bin/env bash
# Public entry point, compatible with the Bash supplied with macOS.
(
set -euo pipefail
repo=xionglaoshi/chives
source_url="https://codeload.github.com/$repo/tar.gz/refs/heads/main"
lock=
step=0
work=
cleanup() { test -z "$work" || rm -rf -- "$work"; test -z "$lock" || rmdir -- "$lock"; }
trap cleanup EXIT
trap 'printf "\n安装在第 %s 步中断，请查看上方错误后重试。\n" "$step" >&2' ERR
fail() { printf '\n安装未完成 · 第 %s 步 · %s\n' "$step" "$*" >&2; exit 1; }
stage() {
    step=$1
    local filled=$((step-1)) bar= i
    for ((i=0; i<6; i++)); do if ((i<filled)); then bar="$bar#"; else bar="$bar-"; fi; done
    printf '\n  [%s/6] [%s] %d%%  %s\n' "$step" "$bar" "$((filled*100/6))" "$2"
}
done_step() { printf '    ✓ %s\n' "$1"; }
banner() {
    if [[ -t 1 && -z ${NO_COLOR+x} ]]; then printf '\033[1;92;40m'; fi
    cat <<'BANNER'
   ███ █ █ ███ █ █ ███ ███
   █   █ █  █  █ █ █   █
   █   ███  █  █ █ ██  ███     CHIVES-AGENT
   █   █ █  █  █ █ █     █
   ███ █ █ ███  █  ███ ███
BANNER
    if [[ -t 1 && -z ${NO_COLOR+x} ]]; then printf '\033[0m'; fi
    printf '\n  老韭菜 · 本地安装向导\n  从仓库取得 Chives 源码，复用本机工具，缺少的组件从官方来源下载。\n  共六步：检查本机 → 选择网络 → 下载源码 → 准备运行环境 → 安装依赖并构建 → 启动工作台\n'
}
proxy_candidates() {
    printf '%s\n' "${https_proxy:-}" "${HTTPS_PROXY:-}" "${all_proxy:-}" "${ALL_PROXY:-}" "${http_proxy:-}" "${HTTP_PROXY:-}"
    if command -v scutil >/dev/null; then
        scutil --proxy | awk '$2==":"{v[$1]=$3} END{for(i=1;i<=3;i++){k=(i==1?"HTTPS":i==2?"HTTP":"SOCKS"); if(v[k"Enable"]==1 && v[k"Proxy"] && v[k"Port"])print (k=="SOCKS"?"socks5h://":"http://") v[k"Proxy"] ":" v[k"Port"]}}'
    elif command -v gsettings >/dev/null && [[ $(gsettings get org.gnome.system.proxy mode 2>/dev/null || :) == "'manual'" ]]; then
        local kind host port scheme
        for kind in https http socks; do
            host=$(gsettings get "org.gnome.system.proxy.$kind" host 2>/dev/null | tr -d "'" || :)
            port=$(gsettings get "org.gnome.system.proxy.$kind" port 2>/dev/null || :)
            scheme=http; [[ $kind != socks ]] || scheme=socks5h
            [[ -z "$host" || ! "$port" =~ ^[1-9][0-9]*$ ]] || printf '%s://%s:%s\n' "$scheme" "$host" "$port"
        done
    fi
    local host port gateway=
    if [[ -n ${WSL_DISTRO_NAME:-} ]] && command -v ip >/dev/null; then
        gateway=$(ip -4 route show default | awk 'NR==1{print $3}')
    fi
    for host in 127.0.0.1 $gateway; do
        for port in 7897 7890 10809; do printf 'http://%s:%s\n' "$host" "$port"; done
        printf 'socks5h://%s:1080\n' "$host"
    done
}
download() {
    printf '    下载 %s（已收字节 / 当前速率）\n' "$3"
    "${fetch[@]}" -fL --retry 2 --speed-time 90 --speed-limit 1 -o "$2" -w '\n    已接收 %{size_download} 字节 · 平均 %{speed_download} B/s\n' "$1" || fail "$3 下载失败"
}
main() {
    banner
    stage 1 '检查平台和安装目录'
    case $(uname -s) in Darwin) os=macos;; Linux) os=linux;; *) fail '请在 Windows PowerShell 使用 installer.ps1';; esac
    case $(uname -m) in x86_64|amd64) arch=x64;; arm64|aarch64) arch=arm64;; *) fail '需要 x64 或 ARM64 处理器';; esac
    root=${CHIVES_INSTALL_HOME:-"$HOME/.chives"}
    if [[ -z ${CHIVES_INSTALL_HOME:-} && ! -e "$root" && -d "$HOME/.chives-install/releases" ]]; then root="$HOME/.chives-install"; fi
    [[ "$root" = /* && "$root" != / && "$root" != "$HOME" ]] || fail '安装目录须为独立的绝对路径'
    [[ ! -e "$root/.git" && ! -e "$root/package.json" ]] || fail "检测到源码安装 $root，请按 INSTALL.md 更新。"
    for cmd in curl tar mktemp; do command -v "$cmd" >/dev/null || fail "缺少 $cmd"; done
    if command -v sha256sum >/dev/null; then digest=(sha256sum); else command -v shasum >/dev/null || fail '缺少 SHA-256 工具'; digest=(shasum -a 256); fi
    platform="$os-$arch"
    python=
    py_dir="$root/tools/cpython-3.12.13-20260510-$platform"
    for exe in python3.12 python3 python "$py_dir/bin/python3"; do
        if command -v "$exe" >/dev/null && "$exe" -I -c 'import ctypes,ensurepip,platform,ssl,struct,sys,venv; assert sys.implementation.name=="cpython" and sys.version_info[:2]==(3,12) and struct.calcsize("P")==8 and ("arm64" if platform.machine().lower() in ("arm64","aarch64") else "x64")==sys.argv[1]' "$arch" >/dev/null 2>&1; then
            python=$(command -v "$exe"); break
        fi
    done
    done_step "$os/$arch · $root"
    if [[ -n "$python" ]]; then done_step "复用 $("$python" -V) · $python"; else printf '    缺少兼容的 Python 3.12，将从 Astral 的 CPython 分发下载。\n'; fi
    local tool info
    for tool in node npm pnpm; do
        if command -v "$tool" >/dev/null && info=$(COREPACK_ENABLE_NETWORK=0 npm_config_manage_package_manager_versions=false "$tool" --version 2>/dev/null); then
            printf '    已检测到 %s %s\n' "$tool" "$info"
        else
            printf '    %s 未就绪，将按仓库要求补齐。\n' "$tool"
        fi
    done
    stage 2 '验证通往 GitHub 的网络'
    # Force each probe to use its candidate, including when NO_PROXY contains github.com.
    fetch=(curl -q --proto '=https' --proto-redir '=https' --connect-timeout 8)
    local candidate route=直连
    local via=(--noproxy '*')
    while IFS= read -r candidate; do
        if "${fetch[@]}" --proxy "$candidate" --noproxy '' --connect-timeout 2 --max-time 4 -fsIL "https://github.com/$repo" >/dev/null 2>&1; then
            via=(--proxy "$candidate" --noproxy ''); route=代理; break
        fi
    done < <(proxy_candidates | awk 'NF && !seen[$0]++')
    fetch+=("${via[@]}")
    if [[ "$route" == 代理 ]]; then export CHIVES_SETUP_PROXY="$candidate"; else export CHIVES_SETUP_PROXY=; fi
    done_step "已选择$route"
    stage 3 '下载 GitHub main 分支源码'
    mkdir -p "$root/tools"
    mkdir "$root/.installing" 2>/dev/null || fail "已有安装任务；若上次被强制终止，请确认后移走 $root/.installing"
    lock="$root/.installing"
    work=$(mktemp -d "$root/.setup.XXXXXXXX")
    download "$source_url" "$work/main.tar.gz" 'Chives 源码'
    tar -xzf "$work/main.tar.gz" -C "$work" chives-main/deploy/installer/source.py chives-main/deploy/installer/install.py
    done_step '源码和安装引擎已就绪'
    stage 4 '准备 Python、Node.js 和 npm'
    if [[ -z "$python" ]]; then
        case "$platform" in
            macos-arm64) target=aarch64-apple-darwin; hash=55bc1a5edbc8ac4da0081f4f5731ed2d1ed10c57cb37a820b2a0dbc7cad742e9;;
            macos-x64) target=x86_64-apple-darwin; hash=6bab7fa97d4f2ddba86da0e05acff66c53b5edaca1df8edcf00ddca785a9c59b;;
            linux-arm64) target=aarch64-unknown-linux-gnu; hash=8e2907baca8b08ae43f366e65f09fda6337d3543f322c399d8800cf689c79973;;
            linux-x64) target=x86_64-unknown-linux-gnu; hash=d480f5d5878910ecbae212bf23bd7c25d7b209eb8cf5e98823c977384d272e88;;
        esac
        url="https://github.com/astral-sh/python-build-standalone/releases/download/20260510/cpython-3.12.13%2B20260510-$target-install_only_stripped.tar.gz"
        download "$url" "$work/python.tar.gz" 'CPython 3.12'
        actual=$("${digest[@]}" < "$work/python.tar.gz")
        [[ ${actual%% *} == "$hash" ]] || fail 'CPython 的 SHA-256 不匹配'
        tar -xzf "$work/python.tar.gz" -C "$work"
        [[ ! -e "$py_dir" ]] || fail "已有无法使用的 Python 目录，请检查 $py_dir"
        mv "$work/python" "$py_dir"
        python="$py_dir/bin/python3"
    fi
    "$python" -X utf8 -I -u "$work/chives-main/deploy/installer/source.py" "$root" "$work/main.tar.gz" "$platform" || exit $?
}
main
)
