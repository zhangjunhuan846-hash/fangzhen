# 开发环境说明（本机特有的三个问题与绕法）

> 这两条都是**本机 workaround，不是根治**。换机器或重新 clone 之后，
> 跑一次 `bash scripts/dev/apply_env_fixes.sh` 即可复现本机状态。

---

## 1. Git 凭据助手：GCM 死锁

### 现象

`git push` 卡住 90–120 秒后被 SIGTERM；重试循环里表现为
`CONNECT tunnel failed, response 502` 与超时交替出现，**看起来像网络问题**。

### 真因

全局 `credential.helper` 指向 **git-credential-manager (GCM) 2.9**，
而 GCM 在本机**任何上下文都会死锁**：

- `git credential fill` 45 秒超时；
- `GCM_TRACE=1` 不产生任何输出；
- 但凭据**确实存在**：`cmdkey /list` 里有
  `LegacyGeneric:target=git:https://github.com`，
  `git-credential-manager github list` 也能列出账号。

也就是说：卡的不是网络，也不是"没有凭据"，而是 **GCM 读不出来**。

### 绕法

改用 Git 自带的 `wincred` 读**同一条凭据管理器条目**：

```bash
git credential fill      # 之前 45s 超时，之后 ~1.6s 返回
```

写进本仓库 `.git/config`：

```ini
[credential]
    helper =
    helper = wincred
```

**顺序有意义**：前面那条空值会把全局配置里的 GCM **清零**；
少写这一行，GCM 仍排在第一位并继续卡死。

> 副作用：这只对**本仓库**生效，全局配置不动。
> 这也是为什么它写在 `.git/config` 而不是 `~/.gitconfig`。

---

## 2. `refs/remotes/origin/main` 被安全软件秒删

### 现象

`git status` 显示 `## main...origin/main [gone]`；
`git fetch` 报告 `* [new branch] main -> origin/main` 成功，
但 `.git/refs/remotes/` 目录**随即不存在**。

### 真因

安全软件会删除 `.git/refs/` 下新建的松散引用文件。
沙箱内外都一样，所以与 WorkBuddy 的沙箱无关。

### 绕法

把该引用写进 **`.git/packed-refs`**（安全软件只盯松散引用）：

```
# pack-refs with: peeled fully-peeled
<sha> refs/remotes/origin/main
```

**这里有个必须记住的坑**：`packed-refs` 头部若声明 `sorted`，
git 会对它做**有序查找**。此时把引用插在错误位置会出现极迷惑的现象——
`git show-ref`（线性扫描）**能列出**它，`git rev-parse` 与 `git status`
却找不到。所以脚本故意**去掉头部的 `sorted` 声明**，让 git 回退线性查找，
顺序就不再敏感；同时也避免了重排把带注释 tag 的 peeled (`^`) 行与其 tag 拆散。

之后任何一次 `git pack-refs --all` 都会把它恢复成规范有序文件（自愈）。

---

## 3. `.git` 内部被成批删除（2026-09-15 实测两次）

这一条比前两条严重得多：**它会毁掉整个仓库**。前两条只是让人烦，这一条会让人丢历史。

### 现象

- **第一次（约 17:05）**：`.git/refs/` **整个目录消失**，且 `.git/objects/` 下的**松散对象被清空**
  （只剩空目录残留）。表现为 `git switch -c` 建出的分支"没有提交"，
  接着 `git status` 报 `not a git repository`——因为 git 认为没有 `refs/` 就不是仓库。
- **第二次（约 17:17）**：`git repack -ad` 之后，`.git/` 只剩 `info/` 与 `objects/info/packs`。
  `HEAD`、`config`、`index`、`packed-refs`、整个 `objects/pack/`（含 29 MB 的 pack）
  **全部消失**。

### 关键观察（用于判断，不要凭感觉归因）

1. **工作树从来没有被碰过。** 两次事故后，所有源码、文档、测试文件完好无损，
   md5 与备份逐一相符。**"丢的永远是 `.git`，不是你的代码。"**
2. **已经在 pack 文件里的对象挺过了第一次**；松散对象没有。
   第二次连 pack 也被删了。
3. 两次删除**都紧跟一次"写/删很多 `.git` 内文件"的 git 操作**
   （`git switch -c` 建引用；`git repack -ad` 建 pack + 清理松散对象）。
   两次间隔约 **12 分钟**，更像**周期性扫描**而不是"某条命令的副作用"。
   → 所以**不要做第二遍同样的操作去复现**，那只会再丢一次。
4. 同一父目录下的普通文件备份（`_recovery_20260915/`）**两次都活着**。
   被针对的是 `.git` 这个目录形态。

### 恢复流程（已实测两次走通）

```bash
# 1. 先备份工作树里所有改动过的文件（这一步永远最先做）
# 2. 重建仓库骨架
git init
git remote add origin https://github.com/zhangjunhuan846-hash/fangzhen.git
git config user.name  "WorkBuddy Agent"        # 与待重建的提交保持一致
git config user.email "agent@workbuddy.local"
git config --local --add credential.helper ""   # 先清全局 GCM，见第 1 节
git config --local --add credential.helper wincred

# 3. 从远端取回历史（本地对象没了，远端还在）
git fetch origin main

# 4. 写引用 + 重建索引
printf '<sha of main>\n' > .git/refs/heads/main
git symbolic-ref HEAD refs/heads/main     # git init 默认是 master
git reset -q                              # 用 HEAD 重建 index

# 5. 重新提交，然后把 `git show --stat` 与已知的 diff 规模逐个对照
# 6. 立刻做单文件备份
git bundle create <仓库外路径>/fangzhen-main.bundle --all
git bundle verify <仓库外路径>/fangzhen-main.bundle   # 应报 "complete history"
```

**校验靠 diff 规模，不靠感觉。** 重建后逐笔核对
`git show --stat`：本次重建后三笔分别是 `+753/−0`、`+287/−3`、`+176/−12`，
与事故前**完全一致**，这才算恢复成功。

### 缓解（写进 `apply_env_fixes.sh`）

关掉一切"会自动重打包"的机制——它们是事故触发点：

```bash
git config gc.auto 0
git config gc.autoDetach false
git config fetch.writeCommitGraph false
git config maintenance.auto false
```

并坚持两条纪律：

- **改动一落盘就做 bundle**（`git bundle create ... --all`）。单文件，比目录形态抗删。
- **能 push 就 push**。远端是唯一不受本机这行为影响的地方。

### 不要做的事

- **不要为了"整齐"跑 `git gc` / `git repack -ad` / `git pack-refs --all`。**
  本机上这些操作已经造成过一次全库丢失，收益（省几十 MB）远小于风险。
- 事故后**不要在原目录反复重试**同一个操作——先把工作树备份出去，再动手。

---

## 附：脚本做了什么

`scripts/dev/apply_env_fixes.sh`：

1. 写 `.git/config` 的 `credential.helper`（空值 + wincred），并现场试读凭据；
2. 把 `refs/remotes/origin/main`（取 `ls-remote`，不可用则回退本地 HEAD）
   写进 `.git/packed-refs`，去掉 `sorted` 声明，并校验引用可解析；
3. 关掉一切自动重打包机制（`gc.auto` / `gc.autoDetach` /
   `fetch.writeCommitGraph` / `maintenance.auto`），见第 3 节：本机上
   `git repack` / `git gc` 已造成过一次全库丢失。

幂等，可重复执行。

第 3 节的**恢复流程**脚本不自动执行——它要在 `.git` 已经损坏时人工跑，
且第一步永远是先把工作树的改动备份出去。
