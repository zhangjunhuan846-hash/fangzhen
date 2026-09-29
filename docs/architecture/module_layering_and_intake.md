# 模块分层与接入协议

日期：2026-09-29 ｜ 状态：**已落地（含校验器与测试）**
配套：`MODULES.yaml`（清单本体）、`MODULE_GRAPH.yaml`（**单模块级依赖图**）、
`scripts/check_module_manifest.py` / `scripts/scan_module_graph.py` / `scripts/check_module_graph.py`（校验器）、
`tests/test_module_manifest.py`（9 项）+ `tests/test_module_graph.py`（11 项）、`PACKAGING.md`（打包）

---

## 0. 一句话

**"哪些模块必要"这个问题，不能靠"重不重要"来回答 —— 那个判据不可执行。**
本文件改用一条可机器验证的判据：

> ### 把它删掉，测试会不会红？

| 档 | 判据 | 含义 |
|---|---|---|
| **core** | 删掉 ⇒ 有测试变红，且红的是**科学判据**类 | 不许删。改动必须走版本号 |
| **optional** | 删掉 ⇒ 有测试变红，但红的是**"能力少了一个"** | 可换，走接入协议 |
| **scratch** | 删掉 ⇒ **没有任何测试变红** | 它本来就该是一次性的 |

这条判据的价值不在于它更聪明，而在于**它能被脚本判定**。
本文件末尾给出一条命令，能当场把三类分出来。

---

## 0.5 粒度：目录级 → 单模块级（2026-09-29 增补）

**导火索**：导师指出「**要细化得看代码**」「**模块和模块之间就成了关键**」。

本文件原先按**目录**分档，于是出现「`battery_sim/` 38 个模块」这样一条 —— 
**38 个模块打成一条，等于没细化**。`MODULE_GRAPH.yaml` 是它的细化层，
把粒度降到**单文件**，并回答两个目录级答不了的问题：

1. **同一个目录里，哪些文件是真核心？**
2. **依赖方向是不是真的单向？**

### 结论一：真核心是 `paths.py`，不是整个 `battery_sim/`

按被依赖次数（in-degree）实测：

| in-degree | 模块 | 行数 | 说明 |
|---|---|---|---|
| **16** | `battery_sim.paths` | **53** | ⚠️ **只有 53 行，却被 16 个模块依赖** |
| 13 | `battery_sim.datasets.base` | 127 | 7 个 adapter 的基类 |
| 11 | `battery_sim.models.pybamm_factory` | 246 | 所有仿真入口经它构模型 |
| 8 | `battery_sim.schemas` | 112 | canonical 数据形状 |
| 7 | `battery_sim.registry` | 137 | 数据集注册 |
| 7 | **`user_tools.spec`** | 398 | ⚠️ **不在内核里，却并列第 6** |
| 5 | `battery_sim.simulation.baseline` | — | 回放主循环 |
| 4 | `battery_sim.datasets.material_metadata` | — | 材料元数据 |

**⇒ 真核心不是最复杂的模块，是最被依赖的。**
两条目录级看不出的结论：

- `paths.py` 只有 53 行，但改它波及全平台；
- `user_tools.spec`（接入层）与内核模块**同等核心** —— 
  说明「接入层」不是外围，是核心。

### 结论二：分层单向的声明与实况曾有 **1 处不一致** —— 2026-09-29 已修

治理层对内核的依赖有 3 处，**现已全部为 lazy**：

| 方向 | kind | 判定 |
|---|---|---|
| `simulation.protocol_replay` → `governance.scale_alignment` | lazy | ✅ **合法**：刻意设计的强制点，尺度门是回放前置条件（`docs/scale_alignment_gate.md`） |
| `governance.scale_alignment` → `battery_sim.models.pybamm_factory` | lazy | ✅ 可接受 |
| `governance.geometry_channel` → `battery_sim.datasets.material_metadata` | lazy | ✅ **原为 module 级，已修** |

**修复前的形态**：`geometry_channel.py` 把
`from battery_sim.datasets.material_metadata import load_metadata`
写在**文件顶部**。后果不是"不够规范"，是
`import governance.geometry_channel` 会**立刻拉起 6 个 `battery_sim` 模块** ——
治理层与内核在**导入期**就被焊死，"分层单向"在 import 那一刻就破产。

**修复**：把该 import 移入 `geometry_override_channel()` 函数体内，
与同目录 `scale_alignment.py` 的既有写法一致。
**依赖关系与行为均不变**，只是导入期不再牵连。

**实测验证（修复前 → 修复后）**：

```
import governance.geometry_channel 后牵连的 battery_sim 模块数：6 → 0
scripts/scan_module_graph.py 对该边的判读：          [module] → [lazy]
```

**防回退**（两重，都在 `tests/test_module_graph.py`）：
1. 静态：校验输出里 `geometry_channel` 那条必须标 `[lazy]`，出现 `[module]` 即红；
2. 行为：直接测 `import governance.geometry_channel` 牵连的 `battery_sim` 模块数必须为 0。
   第二条更硬 —— 它不关心 import 写在哪，只关心导入期到底拉起了什么。

**为什么第 3 条当初是问题、而这里的 `ok: true` 不等于"这依赖不该有"**：
`geometry_channel` 必须读 metadata 才能把实测量翻成 PyBaMM 键，**这是它的职责**。
合规的是**时机**（lazy 而非 module），不是**存在性**。

**这条是本次细化最有价值的产出** —— 它只能靠**看代码**发现，
目录级分档和"重不重要"的判断都看不见它。

### 结论三：一个"接线缺口" —— **2026-09-29 已接线**

`governance.settings_hash` 实测**孤立**（没有任何模块依赖它，它也不依赖别人）。
但它是三层比对的前置门 —— 所以这是一个**接线缺口**，
不是"无用模块"。**tier 保持 core（能力不可删）。**

**缺口的真实形态比"没人 import"更具体。** 查下去发现：

```
grep -rn "settings_hash_per_level" --include=*.py . | grep -v tests/   →   0 命中
```

而模板里槽位是齐的（`run_record.yaml:58-61`，四个槽位）。
也就是说——**模板里挖了坑，没有任何代码往里放东西**。
这正是本仓库反复出现的"机制有了、没人用"：坑的存在感让人以为缺口已填。

**解法**：`user_tools/settings_wiring.py`（本文件写就时新增）。
读若干份 `run_metadata.json` → 复算指纹 → 比对 → 输出可直接粘进
run_record 的四个槽位。它承载一条关键语义：

> 三层里**只要有一层不可复算**（旧 run 缺 `solver` / `model_options`），
> `settings_identical_across_levels` 必须写 `'unknown'`，**不许写 `True`**。
>
> 为什么必须有第三态：二值化的结果是"没查也说一样"。
> 而"三层设置一致"正是"M2 比 M1 好"这句话成立的前提；
> 前提没验证就给 `True`，是**说假话**。

**实测（2026-09-29）**：`outputs/` 下 **61 份 `run_metadata.json`，
0 份**带 `solver`/`model_options` 块 ⇒ 现有 run 一份都不能复算指纹。
这是**数据的历史事实**（那两个键 2026-09-28 才写进产物），不是工具缺陷。
测试 `test_real_outputs_currently_have_no_fingerprintable_run` 把它钉住 ——
将来有新式 run 出现时它会红，提醒把该 run 当作三层比对的起点。

**另修一处**（同一批，v0.1.1）：`governance/geometry_channel.py` 的
模块级反向依赖已改为 lazy import（见下节）。

### 一条"假环"

`battery_sim.models` ↔ `battery_sim.models.pybamm_factory` 
—— 包导出惯例（`__init__.py` 转出 + 工厂 import 同包子模块）导致的假环，
Python 能正常解析（实测可 import）。**不改。**

### 科研 / 工业双档（只标注，不展开）

导师指出：「如果需求只是单纯科研，相对简单；要下工业界，就会难一点。」
`MODULE_GRAPH.yaml` 的 `research_vs_industry` 节逐条标注差异：

| 模块 | 科研 | 工业界 |
|---|---|---|
| `logging_utils.py` | 够用 | 不够：需审计日志与可追溯 |
| `settings_hash.py` | 够用 | 不够：需配置管理与版本回滚 |
| `scripts/probe_*.py` | 留着（研究过程证据） | **必须清**（不进交付物） |
| `data/`（不随包） | 可接受 | 不行：需数据血缘与可重放 |

**工业化其余部分（部署、监控、SLA）明确不在本项目范围。**

### 细化的工具链（三条命令）

```bash
python scripts/scan_module_graph.py        # 生成依赖图（AST 静态分析，不拉起 pybamm）
python scripts/check_module_graph.py       # 校验图与代码一致；能分辨 lazy 与 module 级
python scripts/check_module_manifest.py    # 校验目录级清单
```

**实测**：`check_module_graph.py` → **OK 13 / WARN 0 / FAIL 0**；
`test_module_graph.py` → **11 passed**。
校验器会**真的报出** `geometry_channel` 那一处 module 级反向依赖 —— 
把图与代码的一致性变成红灯，所以图不会在下次重构后变成错的。

---

## 1. 为什么"重不重要"不能用

你原来的问法是「确定哪一些模块是必要的，不管项目怎么迭代，这些模块都需要留着」。

「必要」这个词在工程上没有可判定性，因为它不产生任何可观测后果。举三个本平台**真实发生过**的例子：

| 事件 | 当时的判断 | 实际后果 |
|---|---|---|
| `k` 写成函数默认值 `3.0` | "这是个常见的起点，先用 3" | 阈值看起来定了，**其实是事后挑的**；报告渲染 `3×σ` 而 JSON 写 `"k": null`，**同一份产物自相矛盾** |
| `SEARCH_KEYS` 在两条 pipeline 各写一份 | "就近写方便" | 两套名字**零重叠** ⇒ 白名单过滤成空 ⇒ 撞进 while 循环**空转 10000 秒** |
| 43 个 `probe_*.py` 堆在 `scripts/` | "都是研究过程的一部分" | 无法区分核心与一次性；打包时不知道带哪些 |

**三次判断都不是"重要不重要"的问题，而是"有没有一个机制在它出错时报警"。**
所以判据必须落在"会不会报警"上。

---

## 2. 三档的具体划分（本平台现状）

### core — 不可删

| 模块 | 为什么删不得 |
|---|---|
| `battery_sim/`（38 模块） | 平台之所以是平台的东西。STATUS.md 多处声明"科学核心改动 = 0"，**本条就是那个声明变成的清单项** |
| `governance/`（8 模块） | 让平台**不能悄悄说错话**。删掉任何一项，对应的静默错误就回来了 |
| `configs/datasets.yaml` | 删掉平台不知道自己能跑什么数据 |
| `battery_sim/registry.py` | 被 **14 个测试文件**引用（全平台最多）——这是"删了必红"的最强证据 |
| `battery_sim/schemas.py` `rates.py` `paths.py` `config.py` `logging_utils.py` | 公共依赖与冻结表 |
| `user_tools/validate.py` | 删掉 ⇒ 错数据一路走到结论里 |
| `run_pipeline.py` | 四个模式的唯一入口 |
| `tests/` | **测试本身是核心资产**：三档判据完全建立在它之上。没有测试，分类退化成主观判断 |
| `scripts/check_module_manifest.py` | 本清单的校验器。没有它，本文件是会腐烂的文档 |
| `external/` | OCP 表被半数 adapter 依赖；`Jackowska-2025-JPS` 锁 `PyBaMM==25.8` |

⚠️ **两条已声明的例外**（core 但无测试提及，已在清单里具名）：
`battery_sim/config.py`、`battery_sim/logging_utils.py`。
理由：它们是**结构性依赖**——删掉会让所有测试一起红（import 失败），
属"结构性命中"而非"判据性命中"。**这个例外必须显式写出来，不许静默**。

### optional — 可换

| 模块 | 换法 |
|---|---|
| `battery_sim/datasets/`（7 adapter + 基础设施） | 换数据集 = **新增一个 adapter 文件 + datasets.yaml 一行**，不许改 runner |
| `battery_sim/models/` | 换模型族走 `supported_models` 声明 |
| `battery_sim/excitation/` | 激励门可换；换时保住"零电流对照逐位 0" |
| `extraction/`（9） | 提取算法可换；保住"只有 `identifiable` 才报数值"的出口 |
| `identification/`（10） | 辨识算法可换；`forward.py` 是 L4 入口，**保住"预测不重拟合"** |
| `user_tools/`（14） | `sigma_noise.py` 的 `k` **必须走预注册文件，不许有默认值** |
| `analysis/`（7） | 全部无测试 ⇒ 按判据本应归 scratch。仍列 optional 是因为**产物是证据**（docs 引用），而**代码是一次性的** |
| `templates/` `examples/` `parameters/` | 夹具与模板 |

⚠️ **`analysis/` 这一档要特别说清**：它体现了本判据的一个边界——
**代码的位置不等于证据的位置**。图谱是论文证据，画图谱的脚本是一次性的。
把两者混为一谈，就会出现"为了保住一张图而不敢动一个脚本"。

### scratch — 一次性

| 家族 | 数量 | 处理 |
|---|---|---|
| `scripts/probe_*.py` | **43** | 打包不进包（或进 `archive/` 且不在 import 路径） |
| `scripts/*_phase_*_compare.py` | 8 | 同上；产物是证据，代码是一次性的 |
| `scripts/` 顶层零散（triage/audit/export/aggregate/run_*） | 14 | 已逐条登记，结论进 docs 后即可归档 |
| `scripts/_*.py` | 3 | wiring 文档已注"可删或提升为测试" |
| `scripts/audit/ dev/ lfp_h1*/ lfp_screening/ halfcell_birmingham/` | ~40 | 历史阶段脚本 |

**关键数字：`scripts/` 116 个 .py 里，超过一半是一次性代码。**
这正是"必要与一次性混在一起、没法自动区分"的证据。

---

## 3. 新模块接入协议（回答第二问）

你的原话是「根据某次的项目需要，把这个模块以比较合适的方式补上去」。

**这个说法里有一个危险的模糊处**：「根据项目需要」是**模糊授权**。
没有判据的话，它会退化成"这次先凑一下"——而上面第 1 节那三个例子，
全都是这样发生的。

所以接入协议的第一条不是"怎么补"，而是**补之前先声明它属于哪一档**。

### 3.1 五步（照抄平台已验证的模式）

平台里已经有一个**成功运营的接入协议**，写在 `configs/datasets.yaml` 头部：

> `Adding a new dataset = new adapter in platform/datasets/ + one entry here.`
> `No changes to the core runners required.`

**同一模式适用到模块层**：

```text
新增模块 M =
  ① 独立目录     —— 不许改已有模块的文件
  ② 清单登记     —— 在 MODULES.yaml 写 {path, layer, tier, test_hook, pack}
  ③ additive 入口 —— 不许 monkey patch（agent_platform_fusion.md §3 已写死）
  ④ 存在性测试   —— 加一条测试断言该模块被注册（这是本平台原先缺的那一环）
  ⑤ 若归 core，必须同时给测试
                 —— 给不出测试的，只能归 scratch
```

**第 ④ 步是新增的、也是关键的**：平台原先**没有"新模块必须登记"的机制**，
所以 43 个探针才能悄悄躺在 `scripts/` 里。现在有了校验器：

```bash
python scripts/check_module_manifest.py
```

它会做三件事并给出可判成败的退出码：

1. 清单登记的路径**真的存在**吗？（防清单腐烂）
2. 标为 core 的模块**真的有测试覆盖**吗？（防"自称核心却没有测试"）
3. `scripts/` 下**有没有未登记的文件**？（防下一个探针溜进来）

**实测**：本清单初次运行就抓出 **20 个未登记的顶层脚本**。
这不是演示，是它第一次跑就干的事。

### 3.2 四条反模式（都是本平台踩过的）

| 反模式 | 实例 | 为什么危险 |
|---|---|---|
| **静默默认值** | `k=3.0` 写在默认参数里 | 看起来像决定了，其实是事后挑的 |
| **哨兵值** | 失败返回 `capacity=0` | 与"真算出 0"不可分；且失败/成功**形状不同**，调用方必须特判 |
| **两处各写一份常量** | `SEARCH_KEYS` 两份 | 必然漂移。修法应是**让白名单从判定图长出来**，而不是把两份对齐 |
| **同名不同义** | `prompt.yaml` 用 snake_case、白名单用 PyBaMM 风格 | 零重叠 ⇒ 空转 |

**这四条的共同点**：出错时**不报警**。
所以接入协议的第 ⑤ 步是硬要求——**给不出测试的模块，不许进 core**。

---

## 4. 与既有文档的关系

本清单不取代任何既有文档，它把散落的声明**收拢成一份可校验的表**：

| 既有声明 | 出处 | 本清单如何处理 |
|---|---|---|
| "科学核心改动 = 0" | STATUS.md（多处） | 变成 `core: battery_sim/` 一条，带 freeze `ee2fb36` |
| "平台侧不再加模块" | STATUS.md:1159 | 与"新模块走接入协议"并不矛盾：**不再加的是内核**，扩展走独立目录 |
| 冻结范围 | `platform_v04_freeze_manifest.md` | 被引用，不重复 |
| 三层只做前两层 | `agent_platform_fusion.md` §1 | 决定 Agent 在打包中的 `sibling` 地位 |

---

## 5. 明确不做的

| 不做 | 理由 |
|---|---|
| 用"代码行数/复杂度"判核心 | 不可执行，且 43 个探针每个都不复杂 |
| 把 scratch 全删掉 | **探针是研究过程的证据**。要的是"不进包"，不是"不存在" |
| 让 core 也允许无测试 | 那等于放弃判据。给不出测试的就进 scratch，这是**强制**的 |
| 把 `analysis/` 强行归 core | 它的代码无测试；归 core 会让判据自相矛盾。正确做法是**分离代码与产物** |

---

## 6. 一句话总结

> **必要 = 删了会红。**
> 这个定义的好处不是更准确，而是**它能被脚本判定**——
> 所以清单不会腐烂，三档不会漂移，
> 而"根据某次需要补一个模块"这件事，从模糊授权变成**五步可检查的流程**。
