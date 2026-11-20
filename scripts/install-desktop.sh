#!/usr/bin/env bash
# Install / uninstall the Chives finance stack into the dsh Desktop app's home (~/.dsh), using only supported user-level hooks:
#   1. a marked block appended to ~/.dsh/cordis.patch.yml   (MCP gateways, trading guard, watch-panel plugin row)
#   2. a symlink ~/.dsh/profiles/node_modules/watch-panel   (so the plugin row resolves)
#   3. symlinks for our skills in ~/.dsh/skills/            (user-level skill layer)
#      Discover packages directly in the repository skill directory.
# The Desktop profile itself is managed by the app and is NOT touched. Nothing in ~/.dsh is ever printed.
# Usage: scripts/install-desktop.sh install|uninstall|status      (quit the Desktop app first; restart it afterwards)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DSH="${DSH_HOME:-$HOME/.dsh}"
PATCH="$DSH/cordis.patch.yml"
BEGIN="# >>> dsh-finance (managed block; remove with scripts/install-desktop.sh uninstall) >>>"
END="# <<< dsh-finance <<<"
ALL_SKILL_DIRS=("$ROOT"/skills/*/)
SKILL_DIRS=(); ALLOWED_NAMES=" "
for d in "${ALL_SKILL_DIRS[@]}"; do
  name="$(basename "$d")"
  [[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || continue
  [ -f "${d}SKILL.md" ] && [ ! -L "${d%/}" ] && [ ! -L "${d}SKILL.md" ] || continue
  SKILL_DIRS+=("$d"); ALLOWED_NAMES="$ALLOWED_NAMES$name "
done

# Names of links in ~/.dsh/skills that point into this repo's skills/ but are not allowed any more.
extra_links() {
  for d in "${ALL_SKILL_DIRS[@]}"; do name="$(basename "$d")"; l="$DSH/skills/$name"
    [ -L "$l" ] || continue
    case "$(readlink "$l")" in "$ROOT"/skills/*) ;; *) continue ;; esac
    case "$ALLOWED_NAMES" in *" $name "*) ;; *) echo "$name" ;; esac
  done
}

running() { pgrep -f "DSH NEXT.app" >/dev/null 2>&1; }
has_block() { grep -qF "$BEGIN" "$PATCH" 2>/dev/null; }

remove_block() {
  python3 - "$PATCH" "$BEGIN" "$END" <<'PY'
import sys
p, b, e = sys.argv[1:4]
t = open(p, encoding="utf-8").read()
if b in t:
    i = t.index(b); j = t.index(e, i) + len(e)
    t = (t[:i].rstrip("\n") + "\n" + t[j:].lstrip("\n")).rstrip("\n") + "\n"
    open(p, "w", encoding="utf-8").write(t)
PY
}

case "${1:-status}" in
  install)
    running && { echo "请先退出 Desktop 应用（它运行时会覆盖配置），装完再启动。"; exit 1; }
    [ -f "$PATCH" ] || { echo "找不到 $PATCH"; exit 1; }
    for d in watch-panel; do [ -f "$ROOT/packages/$d/lib/client.js" ] && [ -f "$ROOT/packages/$d/lib/index.js" ] || { echo "面板未构建：cd packages/watch-panel && npm run build"; exit 1; }; done
    TS="$(date +%Y%m%d-%H%M%S)"; BK="$DSH/backup-finance-$TS"; mkdir -m 700 "$BK" && cp -p "$PATCH" "$BK/cordis.patch.yml" && chmod 600 "$BK/cordis.patch.yml"
    has_block && remove_block
    {
      echo ""
      echo "$BEGIN"
      cat "$ROOT/packages/finance-bundle/cordis.patch.yml"
      printf '\n# ---- watch-panel (plugin row) ----\n- insert:\n    - id: watch-panel\n      name: watch-panel\n'
      echo "$END"
    } >> "$PATCH"
    mkdir -p "$DSH/profiles/node_modules" && ln -sfn "$ROOT/packages/watch-panel" "$DSH/profiles/node_modules/watch-panel"
    mkdir -p "$DSH/skills"
    for name in $(extra_links); do rm "$DSH/skills/$name" && echo "移除不在白名单的 skill 链接：$name"; done
    n=0; for d in ${SKILL_DIRS[@]+"${SKILL_DIRS[@]}"}; do [ -f "${d}SKILL.md" ] || continue; name="$(basename "$d")"
      if [ -e "$DSH/skills/$name" ] && [ ! -L "$DSH/skills/$name" ]; then echo "跳过 $name：~/.dsh/skills 里已有同名的非链接目录"; continue; fi
      ln -sfn "${d%/}" "$DSH/skills/$name"; n=$((n+1)); done
    echo "已安装：配置块 + watch-panel 链接 + $n 个 skill 链接。备份：$BK。现在可以启动 Desktop。" ;;
  uninstall)
    running && { echo "请先退出 Desktop 应用。"; exit 1; }
    has_block && remove_block && echo "已移除配置块"
    [ -L "$DSH/profiles/node_modules/watch-panel" ] && rm "$DSH/profiles/node_modules/watch-panel" && echo "已移除 watch-panel 链接"
    for d in "${ALL_SKILL_DIRS[@]}"; do name="$(basename "$d")"; l="$DSH/skills/$name"; [ -L "$l" ] || continue
      case "$(readlink "$l")" in "$ROOT"/skills/*) rm "$l" ;; esac; done; echo "已移除 skill 链接"
    echo "完成。备份仍在 $DSH/backup-finance-*（确认无误后可自行删除）。" ;;
  status)
    has_block && echo "配置块：已安装" || echo "配置块：未安装"
    [ -L "$DSH/profiles/node_modules/watch-panel" ] && echo "面板链接：存在" || echo "面板链接：无"
    c=0; for d in ${SKILL_DIRS[@]+"${SKILL_DIRS[@]}"}; do [ -L "$DSH/skills/$(basename "$d")" ] && c=$((c+1)); done
    k=0; for name in $(extra_links); do k=$((k+1)); done
    src="技能目录 ${#SKILL_DIRS[@]} 个"
    echo "skill：$src / 已链接 $c 个 / 多余 $k 个"
    running && echo "Desktop：运行中" || echo "Desktop：未运行" ;;
  *) echo "用法: $0 install|uninstall|status"; exit 64 ;;
esac
