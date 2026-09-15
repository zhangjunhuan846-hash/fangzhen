#!/usr/bin/env bash
# ============================================================
# 提交包装器：让 ref 在本机活下来
#
# 为什么需要它 —— 2026-09-15 实测到的现象：
#
#   `git commit` **成功创建提交对象**，但在某些时刻分支指针会**静默回到
#   提交前**：
#
#       $ git commit -m "..."
#       [feat/x c0be547] ...            <- 报告成功
#       $ git log --oneline -1
#       c83b420 ...                     <- 还是旧的！
#       $ git cat-file -t c0be547
#       commit                          <- 提交对象完好地存在
#       $ ls .git/refs/heads/
#       main                            <- 该分支的松散 ref 不见了
#
#   即：**提交对象没丢，丢的是"分支指向哪里"这条引用**。
#
#   **重要更正（同日实测）**：这不是"每次提交都会发生"。在一次性探针仓库里
#   用原生 git 反复提交，松散 ref 是**正常存活**的。所以它是**间歇性**的
#   （当天两次大事故在 17:05 与 17:17，间隔约 12 分钟，更像周期性扫荡），
#   不是确定性的每条命令效应。
#
#   正因如此，本脚本**只作应急恢复工具，不要当作日常基础设施**：
#   手工改 `packed-refs` 是 workaround，不该成为平台开发的常规流程。
#   根治办法是把项目目录加进安全软件的信任区
#   （见 docs/dev_environment_notes.md 第 3 节）。
#
# 本脚本做的事：commit 之后把新 SHA 直接写进 `.git/packed-refs`，
# 让分支指针不再依赖可能消失的松散引用，并校验 HEAD 确实移动。
#
# 用法（与 git commit 同参）：
#
#   bash scripts/dev/git_commit.sh -m "feat: ..."
#   bash scripts/dev/git_commit.sh -F message.txt
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
