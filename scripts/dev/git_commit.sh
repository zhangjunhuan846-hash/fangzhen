#!/usr/bin/env bash
# ============================================================
# 提交包装器：让 ref 在本机活下来
#
# 为什么需要它 —— 2026-09-15 实测到的确切机制：
#
#   `git commit` 会 **成功创建提交对象**，然后写一个新的松散引用
#   `.git/refs/heads/<branch>`。在这个机器上，这个新写的松散引用
#   **会被安全软件在瞬间删除**，于是 git 回落到 `.git/packed-refs`
#   里的旧值，分支指针**静默回到提交前**。
#
#   表现极具迷惑性：
#
#       $ git commit -m "..."
#       [feat/x c0be547] ...            <- 报告成功
#       $ git log --oneline -1
#       c83b420 ...                     <- 还是旧的！
#
#   而提交对象 c0be547 其实**完好地存在**（`git cat-file -t c0be547`
#   返回 commit）。丢的只是"分支指向哪里"这一条指针。
#
# 本脚本在 commit 之后，把新 SHA 直接写进 `.git/packed-refs`，
# 于是分支指针不再依赖会被删的松散引用。
#
# 用法（与 git commit 同参）：
#
#   bash scripts/dev/git_commit.sh -m "feat: ..."
#   bash scripts/dev/git_commit.sh -F message.txt
#
# 注意：这只是 **workaround**。根治办法是把项目目录加进安全软件的
# 信任区/白名单（见 docs/dev_environment_notes.md 第 3 节）。
# ============================================================
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

BRANCH="$(git symbolic-ref --short HEAD)" || {
    echo "错误：当前不在分支上（detached HEAD），脚本不适用" >&2
    exit 1
}
BEFORE="$(git rev-parse HEAD 2>/dev/null || true)"

OUT="$(git commit "$@" 2>&1)"
RC=$?
printf '%s\n' "$OUT"

if [ "$RC" -ne 0 ]; then
    echo "commit 返回 $RC，未改动 packed-refs" >&2
    exit "$RC"
fi

# ---- 找到新提交的 SHA ------------------------------------------
# 首选：git commit 的输出形如 "[branch abc1234] subject"
NEW="$(printf '%s\n' "$OUT" \
        | sed -n 's/^\[[^]]* \([0-9a-f]\{7,\}\)\].*/\1/p' | head -1)"

# 回退：扫对象库，找 parent == BEFORE 的那个提交
# （对象即使松散也还在；被删的只是引用文件）
if [ -z "${NEW:-}" ]; then
    echo "提示：未能从输出解析 SHA，改为扫描对象库…" >&2
    NEW="$(git cat-file --batch-all-objects \
              --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
            | awk '$1=="commit"{print $2}' \
            | while read -r c; do
                  p="$(git cat-file -p "$c" 2>/dev/null \
                       | sed -n 's/^parent //p' | head -1)"
                  [ "$p" = "$BEFORE" ] && printf '%s\n' "$c"
              done | head -1)"
fi

if [ -z "${NEW:-}" ]; then
    echo "错误：拿不到新提交的 SHA，packed-refs 未更新。" >&2
    echo "      提交对象可能已创建，请用 git fsck --lost-found 找回。" >&2
    exit 1
fi

FULL="$(git rev-parse "$NEW")"
echo "新提交: $FULL"

# ---- 把该分支写进 packed-refs ----------------------------------
# 头部不要带 "sorted"：本机安全软件删引用后，packed-refs 顺序可能
# 与声明不符，线性查找才不会出现 show-ref 看得见、rev-parse 看不见。
PR=".git/packed-refs"
TMP="$(mktemp)"
printf '# pack-refs with: peeled fully-peeled \n' > "$TMP"
if [ -f "$PR" ]; then
    grep -v '^#' "$PR" \
        | grep -vE "^[0-9a-f]{40} refs/heads/${BRANCH}$" \
        | grep -v '^$' >> "$TMP" || true
fi
printf '%s refs/heads/%s\n' "$FULL" "$BRANCH" >> "$TMP"
mv "$TMP" "$PR"

echo "packed-refs 已更新: refs/heads/${BRANCH} -> ${FULL:0:7}"
echo "现在: $(git log --oneline -1)"

if [ "$(git rev-parse HEAD)" != "$FULL" ]; then
    echo "校验失败：HEAD 仍不是新提交，请检查 .git/refs 是否又被删" >&2
    exit 1
fi
echo "校验通过 ✓"
