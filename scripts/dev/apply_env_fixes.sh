#!/usr/bin/env bash
# ============================================================
# 一键修复本仓库在本机上的两个环境问题
#
# 这两条都是 **workaround，不是根治**：
#   1. 全局 credential.helper = git-credential-manager(GCM 2.9)
#      在本机任何上下文都会死锁（git credential fill 45s 超时、
#      GCM_TRACE 无输出），于是 push 卡 90-120s 后被 SIGTERM。
#      凭据其实存在（Windows 凭据管理器里有 git:https://github.com），
#      只是 GCM 读不出来。改用 Git 自带的 wincred 读同一条目。
#   2. .git/refs/remotes/origin/main 创建后会被安全软件秒删
#      （git fetch / update-ref 都报成功，文件随即消失，status 显示
#      [gone]）。改为把该引用写进 .git/packed-refs——安全软件只盯
#      松散引用，packed 能存活。
#
# 换机器 / 重新 clone 之后跑一次即可。幂等，可重复执行。
#
#   bash scripts/dev/apply_env_fixes.sh
# ============================================================
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1
echo "repo: $(pwd)"

# ------------------------------------------------------------
# 1) 凭据助手：空值（清零全局的 GCM）+ wincred
#    顺序有意义：没有前面那条空值，global 的 GCM 仍排第一并卡死。
# ------------------------------------------------------------
git config --local --unset-all credential.helper >/dev/null 2>&1 || true
git config --local --add credential.helper ""
git config --local --add credential.helper wincred
echo "credential.helper (local):"
git config --local --get-all credential.helper | sed 's/^/    /'

if printf 'protocol=https\nhost=github.com\n\n' \
    | timeout 25 git credential fill >/dev/null 2>&1; then
    echo "    -> 凭据可读（若仍卡住，说明 wincred 也取不到，需要重新登录）"
else
    echo "    -> 警告：取凭据仍然失败或超时"
fi

# ------------------------------------------------------------
# 2) 把 refs/remotes/origin/main 钉进 packed-refs
#
#    坑一：packed-refs 头部若声明 "sorted"，git 会做**有序查找**，
#    插错位置的引用 show-ref（线性扫描）看得见、rev-parse/status 看不见，
#    表现为 [gone] 却"明明在里面"。
#    坑二：带注释的 tag 后面跟 peeled('^') 行，重排会把它与 tag 拆散。
#
#    所以这里不重排：**去掉头部的 sorted 声明**，让 git 回退线性查找，
#    于是顺序不再敏感、peeled 行原样保留。之后任何一次
#    `git pack-refs --all` 都会把它恢复成规范有序文件（自愈）。
# ------------------------------------------------------------
REMOTE="origin"
BRANCH="main"
SHA="$(timeout 30 git ls-remote "$REMOTE" "$BRANCH" 2>/dev/null \
        | awk '{print $1}' | head -1)"
if [ -z "${SHA:-}" ]; then
    SHA="$(git rev-parse HEAD 2>/dev/null || true)"
    echo "ls-remote 不可用，回退用本地 HEAD"
fi

PACKED=".git/packed-refs"
if [ -n "${SHA:-}" ]; then
    TMP="$(mktemp)"
    printf '# pack-refs with: peeled fully-peeled \n' > "$TMP"
    if [ -f "$PACKED" ]; then
        grep -v '^#' "$PACKED" \
            | grep -v "refs/remotes/${REMOTE}/${BRANCH}" \
            | grep -v '^$' >> "$TMP" || true
    fi
    printf '%s refs/remotes/%s/%s\n' "$SHA" "$REMOTE" "$BRANCH" >> "$TMP"
    mv "$TMP" "$PACKED"
    echo "packed-refs: refs/remotes/${REMOTE}/${BRANCH} -> ${SHA:0:7}"
    echo "            （头部已去掉 sorted 声明，顺序不再敏感）"

    if git rev-parse --verify -q "refs/remotes/${REMOTE}/${BRANCH}" >/dev/null; then
        echo "校验：引用可解析 ✓"
        echo "status: $(git status -sb | head -1)"
    else
        echo "校验失败：引用仍不可解析"
    fi
else
    echo "拿不到任何 SHA，跳过 packed-refs 修复"
fi

echo
echo "完成。注意：这两条都只作用于**本机本仓库**；"
echo "换机器或新 clone 需要重新执行本脚本（见 docs/dev_environment_notes.md）。"
