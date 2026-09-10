# 开发环境说明（本机特有的两个问题与绕法）

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

## 附：脚本做了什么

`scripts/dev/apply_env_fixes.sh`：

1. 写 `.git/config` 的 `credential.helper`（空值 + wincred），并现场试读凭据；
2. 把 `refs/remotes/origin/main`（取 `ls-remote`，不可用则回退本地 HEAD）
   写进 `.git/packed-refs`，去掉 `sorted` 声明，并校验引用可解析。

幂等，可重复执行。
