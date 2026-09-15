#!/usr/bin/env bash
# ============================================================
# 一键修复本仓库在本机上的三个环境问题
#
# 前两条是 **workaround，不是根治**：
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
# 第三条是 **防御性开关**，2026-09-15 加：
#   3. 同一类删除行为会连 .git/objects 里的松散对象和 refs/ 一起清掉，
#      最严重的一次（git repack -ad 之后）整个 .git 只剩 info/。
#      两次事故都紧跟"一次写/删很多 .git 内文件"的 git 操作，
#      所以这里把自动重打包全关掉，并坚持改完就 bundle。
#      完整现象与恢复流程见 docs/dev_environment_notes.md 第 3 节。
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

# ------------------------------------------------------------
# 3) 关掉一切"会自动重打包"的机制
#
#    2026-09-15 两次事故：refs/ 与松散对象被成批删除；其中一次
#    （git repack -ad 之后）整个 .git 只剩 info/，HEAD/config/index/
#    packed-refs/objects 全没，git status 报 "not a git repository"。
#    两次都紧跟"一次写/删很多 .git 内文件"的操作，间隔约 12 min。
#
#    收益（省几十 MB）远小于风险，所以直接关掉。
#    恢复流程与校验方式见 docs/dev_environment_notes.md 第 3 节。
# ------------------------------------------------------------
git config gc.auto 0
git config gc.autoDetach false
git config fetch.writeCommitGraph false
git config maintenance.auto false
echo "自动重打包已关闭:"
for k in gc.auto gc.autoDetach fetch.writeCommitGraph maintenance.auto; do
    printf '    %-26s = %s\n' "$k" "$(git config --local --get "$k")"
done

# 单文件备份：目录形态两次都被清过，单文件更抗删
BUNDLE_DIR="${BUNDLE_DIR:-$(dirname "$(git rev-parse --show-toplevel)")/_git_bundles}"
mkdir -p "$BUNDLE_DIR" 2>/dev/null || true
echo "bundle 备份目录: $BUNDLE_DIR"
echo "    （建议每次提交后跑：git bundle create <该目录>/<name>.bundle --all）"

echo
echo "完成。注意：这三条都只作用于**本机本仓库**；"
echo "换机器或新 clone 需要重新执行本脚本（见 docs/dev_environment_notes.md）。"
