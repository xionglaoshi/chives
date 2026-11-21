#!/usr/bin/env bash
# Public entry point, compatible with the Bash supplied with macOS.
(
set -euo pipefail
repo=xionglaoshi/chives
channel="https://raw.githubusercontent.com/$repo/main/deploy/installer/channel"
step=0
work=
cleanup() { test -z "$work" || rm -rf -- "$work"; }
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
    printf '\n  老韭菜 · 本地安装向导\n  将从 GitHub 安装 Chives 工作台、DSH、Python、Node.js 和 Chromium。\n  共六步：检查本机 → 选择网络 → 下载校验 → 解包 → 配置环境 → 启动工作台\n'
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
    local name=$1 hash dest actual
    hash=$("${fetch[@]}" -fsSL --retry 2 "$base/$name.sha256") || fail "GitHub 缺少 $name 的校验文件，请检查发行版 $tag。"
    hash=${hash%%[[:space:]]*}
    [[ "$hash" =~ ^[a-f0-9]{64}$ ]] || fail "GitHub 校验文件格式错误：$name"
    dest="$cache/$hash-$name"
    if [[ -f "$dest" ]]; then
        actual=$("${digest[@]}" < "$dest")
        if [[ ${actual%% *} == "$hash" ]]; then done_step "复用已校验的 $name"; downloaded=$dest; return; fi
    fi
    printf '    下载 %s（curl 显示百分比、已收字节及当前速率）\n' "$name"
    "${fetch[@]}" -fL --retry 2 --speed-time 60 --speed-limit 1 -o "$work/$name" -w '\n    已接收 %{size_download} 字节 · 平均 %{speed_download} B/s\n' "$base/$name" || fail "$name 下载失败，可重新运行向导。"
    actual=$("${digest[@]}" < "$work/$name")
    [[ ${actual%% *} == "$hash" ]] || fail "$name 的 SHA-256 不匹配"
    mv -f "$work/$name" "$dest"
    downloaded=$dest
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
    for exe in python3.12 python3 python; do
        if command -v "$exe" >/dev/null && "$exe" -I -c 'import ctypes,ensurepip,platform,ssl,struct,sys,venv; assert sys.implementation.name=="cpython" and sys.version_info[:2]==(3,12) and struct.calcsize("P")==8 and ("arm64" if platform.machine().lower() in ("arm64","aarch64") else "x64")==sys.argv[1]' "$arch" >/dev/null 2>&1; then
            python=$(command -v "$exe"); break
        fi
    done
    done_step "$os/$arch · $root"
    if [[ -n "$python" ]]; then done_step "复用 $("$python" -V) · $python"; else printf '    缺少兼容的 Python 3.12，将使用 GitHub 运行时。\n'; fi
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
    tag=$("${fetch[@]}" -fsSL --retry 2 --max-time 30 "$channel") || fail "无法从 GitHub 取得发布清单，请检查网络及 main 分支的安装入口。"
    [[ $tag != disabled ]] || fail '维护者已暂停便捷安装'
    [[ "$tag" =~ ^installer-[0-9]+([.][0-9]+)+$ ]] || fail 'GitHub 发布清单格式错误'
    base="https://github.com/$repo/releases/download/$tag"
    done_step "GitHub $route · $tag"
    stage 3 '下载并验证平台文件'
    mkdir -p "$root/cache/installer"
    cache="$root/cache/installer"
    work=$(mktemp -d "$root/.setup.XXXXXXXX")
    download "bootstrap-$platform.tar.gz"; tar -xzf "$downloaded" -C "$work"
    if [[ -z "$python" && -x "$root/releases/$tag-$platform/python/bin/python3" ]]; then
        python="$root/releases/$tag-$platform/python/bin/python3"
        done_step '复用 Chives 已安装的 Python'
    fi
    if [[ -z "$python" ]]; then
        download "python-$platform.tar.gz"; tar -xzf "$downloaded" -C "$work"
        python="$work/python/bin/python3"
    fi
    if [[ "$route" == 代理 ]]; then export CHIVES_SETUP_PROXY="$candidate"; else export CHIVES_SETUP_PROXY=; fi
    PYTHONUTF8=1 "$python" -X utf8 -I -u "$work/install.py" install "$root" "$tag" "$platform"
}
main
)
