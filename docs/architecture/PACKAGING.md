# 打包成一个 Project：边界与做法

日期：2026-09-29 ｜ 状态：**方案（待执行）**
配套：`MODULES.yaml`（三档清单）、`module_layering_and_intake.md`（分层判据与接入协议）

---

## 0. 一句话

**打包不是"把所有东西放进一个压缩包"，而是决定三件事：带什么、不带什么、不带的东西怎么让别人拿到。**

本方案的核心是**五个 block + 五条排除**，其中最大的坎是 `data/`（**13 GB，`.gitignore` 已排除**）。

---

## 1. 先说三个必须先解决的障碍

### 障碍 1：`data/` 有 13 GB，且从不提交

`.gitignore` 第 2 行明写 `data/`，注释「heavy raw data (13 GB) — never commit」。

**⇒ 打包时给获取脚本，不给数据。**
但这里有个细节不能含糊：平台目前在跑的 7 个数据集**来源不同、许可不同**：

| 数据集 | 来源 | 能否随包分发 |
|---|---|---|
| Chen2020 / CALCE CS2 / 20R / A123 | 公开数据集 | 可给下载脚本 |
| SINTEF graphite R2032 | Zenodo `10.5281/zenodo.18214281` | 可给 DOI |
| DLR Hydra.0b GITT | 随包已有的单文件 | 需核对许可 |
| **回收石墨（自己的实验）** | 未跑 | **红线：不许发** |

⚠️ **红线区**：导师明确说过**不要发数据**。所以这个 Project 的"数据获取"部分
**只写"找谁要"，不写"点这里下载"**——自己实验的数据不进任何分发渠道。

### 障碍 2：两个仓库不是 git 仓库 —— **2026-09-29 已解决**

| 仓库 | 状态 | 风险 |
|---|---|---|
| `仿真模拟` | **git** ✅（tag `v0.1.0-platform` → `ee2fb36`） | — |
| `Battery-Sim-Agent` | ✅ **已建**（基线 `b11d1bd`，222 文件） | 原：本地加固（契约 + SimRequest + 参数能力守卫，**283 项测试**）没有任何版本控制备份 |
| `repos_download` | ✅ **已建**（基线 `e7c6061`，23 文件） | 原：分析结论无版本历史 |

**已执行的操作（两个仓库均无 remote，不会误推上游）：**

`Battery-Sim-Agent` —— 222 文件、3.5 MB 全量入档。
提交信息逐条列了本地加固的六个新增件与两处上游缺陷修复，
以及"上游仓库未受影响、本提交不指向任何 remote"。
关键加固文件已逐个核对入档：
`contract.py` / `parse.py` / `sim_contract.py` / `simulator.py` /
`param_capability.py` / `BORROW_NOTES.md` / `SIMREQUEST_IMPLEMENTATION.md` / `test_contract.py`。

`repos_download` —— **只锁不可再生的部分**（23 文件、约 272 KB）：

| 纳入 | 排除 | 排除理由 |
|---|---|---|
| `01_分析产出/`（6 篇模块拆解 + 研究目标 + 通用模块 + 00_总览） | `99_下载临时/`（481 MB） | 下载缓存，可再生 |
| `02_抽取模块/battery_agent_core`（7 模块 + 测试） | `00_源码仓库/` 的第三方仓 | 可再生；其中 3 个**自带 `.git`** |
| `04_项目地图/`（项目地图 + README） | `03_新增仓库/` 的第三方仓 | 同上 |

**这里避开了一个真陷阱**：`00_源码仓库/` 里有 3 个仓库**自带 `.git`**
（`battery-docs-rag-agent` / `battery_ai_agent` / `multi-agent-electrolyte-discovery`）。
若被父仓库 `git add`，git 会把它们记成 **gitlink（子模块引用）而非内容** ——
父仓库里只留一个提交指针，**clone 到别的机器就是空壳**。
这类"看起来备份了其实没有"正是本平台一直在防的失败模式，
所以 `.gitignore` 显式排除，并已实测提交后 `git ls-files -s` 中
**gitlink 计数为 0**。

**为什么不动它们的 git**：上游 owner 是 `opqrst-chen`（**不是**本机账号），
推送到自己的 fork 涉及账号与可见性决定，**用户明确选择暂不推送、先本地**。
本地 git 已足以防误删/误改这一主要风险。

### 障碍 3：环境不可移植（G0 = PARTIAL）

STATUS.md 自述：**没在干净 clone 的机器上跑过**，因此不能声称"新机器能跑起来"。

两个已知陷阱，**都不在任何安装文档里**：

- Windows 侧 Python **没有 PyBaMM** ⇒ 仿真必须走 WSL。这是一个硬分叉。
- Windows git 的 `credential.helper` 与 `refs/remotes/origin/main` 需修复才能 push，
  修复脚本 `scripts/dev/apply_env_fixes.sh`，**"新 clone 需重跑此脚本"写在脚本注释里、没写在 README 里**。

**⇒ 打包时必须把这两条写进 `README` 的显著位置**，否则这个 Project 对别人（包括三个月后的你自己）是不可用的。

---

## 2. 五个 block

### block 1 · 运行时（必需）

```text
battery_sim/        governance/      extraction/
identification/     user_tools/      configs/
templates/          parameters/      external/
run_pipeline.py     requirements.txt
```

体积驱动因素：`external/`（含 `pybamm-input-data` 的 OCP 表，被**半数 adapter**依赖）。
`external/Jackowska-2025-JPS` 锁 `PyBaMM==25.8` —— **严禁 `pip install` 进平台 env**。

### block 2 · 验证（必需，且是打包门）

```text
tests/        pytest.ini
```

**出门条件**：`759 passed`（WSL / pybamm 环境）。
不达标不许打包。这条把"可运行"变成可判定的事实。

### block 3 · 证据（必需）

```text
STATUS.md      ← 唯一可信状态页，pack 时必须领先于其它文档
docs/          ← 56 个文件，含 architecture/ 与 g5.*/g6.* 结论
outputs/       ← 只带图谱与 report.json，不带中间产物
```

⚠️ `outputs/` 有 **169 张 PNG**。全带会让包膨胀，且大部分是阶段中间产物。
**保留规则**：`docs/` 里被引用的图 + 各 `report.json` + `window_map*.csv`。

### block 4 · 证据（拆解产物，可选）

```text
repos_download/01_分析产出     ← 模块拆解 + 通用模块对照
repos_download/04_项目地图     ← 21 个仓库元数据核实
repos_download/02_抽取模块     ← battery_agent_core（85 passed）
```

**只带这三部分。** 不带源码快照，理由见下节。

### block 5 · sibling（不并入主包）

```text
Battery-Sim-Agent/     ← 作为同级目录随 Project 交付
```

**为什么不并入主包**：`agent_platform_fusion.md` §1 已写死——
三层（契约 / 判据 / 治理）**只做前两层**，治理层不搬过去
（搬过去只会变成一份没人校验的声明，正是平台一直在防的）。
两个系统是**回路的两端**，不是一个大系统。

---

## 3. 五条排除

| 排除 | 理由 |
|---|---|
| `data/`（13 GB） | `.gitignore` 已排除；给获取脚本，不给数据 |
| `repos_download/00_源码仓库`、`03_新增仓库` | **上游版权**。10 个仓库里 6 个无 LICENSE（默认保留所有权利），不随包分发 |
| `repos_download/99_下载临时/` | tarball 与解压副本，无价值 |
| `outputs/` 中间产物 | 只留图谱与 report.json |
| `scripts/` 下的 scratch | 或移入 `archive/` 且**不在 import 路径**上 |

⚠️ **关于"排除源码快照"要说清**：这不是因为"不能看"，而是
**① 版权属于上游、② 体积大、③ 结论已经在 `01_分析产出` 里了**。
真要核溯源，`MODULES.yaml` 的 `upstream_ref` 给了**文件:行号**，比带整个仓库更快。

---

## 4. 可复现性（三条纪律）

### 4.1 环境锁

`requirements.txt` 已逐条锁版本，其中两条**不能动**：

- `numpy==2.3.5` —— **必须 <2.4**，PyBOP 26.3 依赖
- `pybamm==26.8.0.0` —— 一次实验**不能跨两个 PyBaMM 版本**

### 4.2 版本号纪律（照抄 STATUS.md，不重复发明）

- `v0.1.0-platform` = `ee2fb36`，**从 2026-09-17 起不再移动**
- 本包走 **`v0.1.1`**
- 原因：**一个会被反复重指的 tag 不表示任何状态**，而"这批实验数据是在哪个平台上跑的"是论文里必须能回答的问题

### 4.3 每次正式 run 记两个 commit

```text
software_commit        = 平台代码状态
protocol_docs_commit   = 判据/协议文档状态
```

**软件冻结 ≠ 判据冻结，两件事分开记录。**

---

## 5. 执行清单（可勾选）

```text
[x] 1. Battery-Sim-Agent  git init + commit  → b11d1bd（222 文件）
[x] 2. repos_download     git init + commit  → e7c6061（23 文件，只锁分析产出）
[x] 3. 跑 tests/ 确认全绿（不达标不出门）      → 799 passed（2026-09-29，WSL）
[x] 4. 跑 scripts/check_module_manifest.py    → OK 51 / WARN 2 / FAIL 0
[ ] 5. 写数据获取脚本（含 Zenodo DOI；自己的实验数据只写"找作者要"）
[ ] 6. 把两条环境陷阱写进 README 显著位置（Windows 无 PyBaMM / env_fixes.sh）
[ ] 7. outputs/ 按保留规则瘦身
[ ] 8. 打 tag v0.1.1-pack
[ ] 9. 记下 software_commit 与 protocol_docs_commit
```

### 第 3、4 项的实测记录（2026-09-29）

| 检查 | 命令 | 结果 |
|---|---|---|
| 平台全量测试 | WSL `~/miniforge3/envs/pybamm/bin/python -m pytest tests -q` | **799 passed**, 5 warnings, 242.52s |
| 模块清单 | `python scripts/check_module_manifest.py` | **OK 51 / WARN 2 / FAIL 0**, rc=0 |
| 依赖图 | `python scripts/check_module_graph.py` | **OK 13 / WARN 0 / FAIL 0**, rc=0 |
| 本轮新增测试 | `pytest tests/test_module_graph.py tests/test_settings_wiring.py` | **31 passed** |

⚠️ **两个环境的区别必须写进 README**（第 6 项，也是障碍 3）：

- **WSL**（`~/miniforge3/envs/pybamm/bin/python`，PyBaMM 26.8.0.0 / Python 3.11）
  → 能跑全量 `tests/`，**799 passed**。这是权威环境。
- **Windows**（托管 venv，Python 3.13，**无 pybamm**）
  → 全量测试会在 collection 阶段报 `ModuleNotFoundError: No module named 'pybamm'`
    （14 个 collection error）。**这不是坏掉，是文档化的硬分叉。**
  → 但纯标准库的检查器与新增测试**在 Windows 上可跑**：
    `scripts/check_module_manifest.py`、`scripts/check_module_graph.py`、
    `tests/test_module_graph.py`、`tests/test_settings_wiring.py`。
    这几个刻意不 import pybamm（AST 静态分析 + 标准库），
    所以"看架构"这件事不需要重环境。

> 注：清单第 3 项原写 `759 passed`，现为 **799 passed** —— 本轮及前几轮
> 新增了 40 项（依赖图 16 + settings_wiring 15 + 其余），零失败。
> 出门条件以**当前实测**为准，不以写死的数字为准。

---

## 6. 一句话总结

> **打包的产物不是一个压缩包，而是一份"别人能重新跑起来"的保证。**
> 所以出门条件是 **全量测试全绿 + FAIL 0**，而不是"文件都放进去了"。
>
> 而最大的风险不是技术问题，是**那条红线**：
> 这个 Project 里**不许出现你自己实验的数据**——
> 数据获取部分只写"找作者要"，不写下载链接。
