#!/bin/bash
set -eu
umask 077
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
export GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1
export HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897

cd /Users/xiong/.chives
gitdir=$(git rev-parse --absolute-git-dir)
[ "$gitdir" = "$PWD/.git" ]
branch=$(git symbolic-ref --quiet --short HEAD) || exit 0
for marker in index.lock MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply sequencer BISECT_START; do
    [ ! -e "$gitdir/$marker" ] || exit 0
done
[ -z "$(git ls-files --unmerged)" ] || exit 0

# Check the effective destination, including Git URL rewrite rules.
url=https://github.com/xionglaoshi/chives.git
if [ "$(git remote get-url --push --all origin)" != "$url" ]; then
    echo 'origin 推送地址已变化，已暂停自动同步。' >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    git add --all -- .
    if ! git diff --cached --quiet; then
        [ "$(git symbolic-ref --quiet --short HEAD)" = "$branch" ] || exit 1
        git commit -m "开发快照 $(date '+%Y-%m-%d %H:%M:%S %z')"
    fi
fi
[ "$(git symbolic-ref --quiet --short HEAD)" = "$branch" ] || exit 1
head=$(git rev-parse HEAD)
tracking=$(git rev-parse --verify --quiet "refs/remotes/origin/$branch") || tracking=''
[ "$head" != "$tracking" ] || exit 0

visibility=$(gh api repos/xionglaoshi/chives --jq '.visibility')
if [ "$visibility" != private ]; then
    echo 'chives 未确认为私有仓库，已保留本地提交。' >&2
    exit 1
fi
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
    -c http.lowSpeedLimit=64 -c http.lowSpeedTime=30 \
    push origin "$head:refs/heads/$branch"
