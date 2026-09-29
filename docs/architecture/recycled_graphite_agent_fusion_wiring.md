# 回收石墨实验 × Battery-Sim-Agent：**融合接线图**（整条实验计划逐段分工）

日期：2026-09-28 ｜ 状态：**接线方案已落地 —— 接缝 A/B/C 均已修，见 §3**
配套：`recycled_graphite_agent_fusion_plan.md`（要不要做 / 什么时候做）、
`agent_platform_fusion.md`（一般方案）、`graphite_heat_treatment_test_plan.md`（实验设计 v2）、
`preregistration_annex_B_preflight_gaps.md`（开跑前待填）

---

## 0. 一句话：融合的形状是「串成一条回路」，不是「把两个系统拼在一起」

```text
        实验数据                     平台判定                      Agent 提议
   ┌──────────────┐   ┌────────────────────────────┐   ┌──────────────────┐
   │ GITT 逐脉冲  │ → │ L3 带宽图（逐窗口五词判定） │ → │ 只在可辨识窗口上 │
   │ + GCD + OCP  │   │  ← 这是"哪里能反演"的清单   │   │ 提 D_s 候选值     │
   └──────────────┘   └────────────────────────────┘   └──────────────────┘
                              ↓                              ↓
                        L4 冻结参数预测 1C ←──── 回灌的是**判定词**，不是 RMSE
```

**回灌箭头是这条回路的核心**：平台回给 Agent 的不是"你差了 48.36 mV"，
而是"你改的这个参数在窗口 #t475 是 `bounded`，你**不能**把它当点估计"。

下面把实验计划的**六步测试序列 + 四级验收**全部摊开，逐段标出**谁干活、产出什么、边界在哪**。

---

## 1. 逐段接线表（这是本文的主体）

图例：**[平台]** = 已就位、直接跑 ｜ **[Agent]** = 上游 Agent 相关 ｜ **[桥]** = 需要新写的适配 ｜ **[人]** = 只能人做

### 阶段 0：开跑前（零数据）

| 步骤 | 谁 | 产出 | 边界 |
|---|---|---|---|
| 定死跑哪一套样品 + 命名唯一 | **[人]** | 附件 B §1 | 未定不能开跑 |
| A1 三条红线（前处理序列相同 / 干燥 ≤150 °C / 焙烧不与温档重叠） | **[人]** | 书面确认 | 不阻塞 Excel，但阻塞动手 |
| 定 τ 阈值口径（`0.1` vs `0.04`，差 **2.5×**） | **[人]**★ | 一个数 | **决定 GITT 覆盖哪些 SOC 段** |
| `σ_noise` 空跑 30 min | **[平台]** 跑 | mV | N1 负对照判据的输入 |
| **Agent 侧：把 `prompt.yaml` 知识文本与白名单对齐** | **[Agent]** | 一份对齐表 | 这是那 10000 秒空转的真凶，**必须在接 Agent 前修** |

⚠️ **阶段 0 里 Agent 唯一的活是"修自己的 bug"，没有仿真可做** —— 因为还没有数据。

### 阶段 1：测试序列（六步）

| # | 测试 | 数据到平台 | **Agent 能不能用** |
|---|---|---|---|
| 1 | 化成（C/20 × 2） | **[平台]** adapter 建档、ICE | ❌ 无 |
| 2 | 准平衡 OCP（双支） | **[平台]** `ocp_table_path()` 替 OCP | ❌ 无 —— **但这是关键：OCP 走 adapter，不走桥** |
| 3 | GCD 0.1C | **[平台]** 容量基准 `Q_model == Q_measured` | ❌ 无（容量一致化是平台的尺度门，Agent 不许碰） |
| 4 | **GITT（双向）** | **[平台]** 逐脉冲瞬态 | ⚠️ **见下** |
| 5 | EIS | 存数据，本轮不建拟合通路 | ❌ 无（`k0`/`Rct` = `not_measured`，理由写"已测但无通路"） |
| 6 | 倍率（0.2 / 0.5 / **1C** / 2C） | **[平台]** | ⚠️ **见下** |

**第 4 步 GITT —— 这是 Agent 唯一真正有活的地方，但要看分辨**

```
GITT 逐脉冲 t/I/V
   ↓ [平台] 脉冲协议 QC（protocol_type=GITT, pulse_duration_s 声明；两条一致性检查）
   ↓ [平台] L3：逐窗口 1 mV 带宽 B + 五词判定
   ↓
   ├── 窗口判定 = identifiable  →  [Agent] 提 D_s 候选值 → [平台] 局部优化填充数值
   ├── 窗口判定 = bounded       →  [Agent] **只许报界**，不许报点估计
   └── 窗口判定 = unconstrained / not identifiable
                                →  [Agent] **不许提数**（提了平台也会拒）
```

**⚠️ 但 τ 判据先砍掉一大段**：R_p 13.70 µm + 600 s 脉冲 ⇒
x=0.02 **τ=2.37**、x=0.10 **τ=0.98** ⇒ **稀相端不满足半无限扩散，不报 Sand 反演**。
⇒ Agent 的活动范围**只剩中段**，而且 G6.1c 已证那里大概率是 `unconstrained`。

**第 6 步倍率 —— 这里是融合最有价值的地方，但有个硬约束**

| 倍率 | 角色 | Agent 能不能碰 |
|---|---|---|
| 0.2C | identification | ✅ 可以（拟合用） |
| 0.5C | validation | ⚠️ 可作对照，**不可进拟合** |
| **1C** | **L4 holdout** | ❌ **绝对不许碰**（含"以调参为目的的试跑"） |
| 2C | validation | ⚠️ 同 0.5C |

**这条比什么都重要**：1C 一旦进入任何一轮 Agent 迭代，**L4 永久失效**。
预注册 §3.4 已冻结，`governance/dataset_roles.py` 在**数据层**强制（拿 1C 标定直接报错）。

### 阶段 2：验收阶梯 L1–L4

| 级 | 谁 | 产出 |
|---|---|---|
| **L1 数据进入** | **[平台]** | 元数据错误 = 0；canonical 四列齐全 |
| **L2 模型复现** | **[平台]** | 0.1C 回放完成；**RMSE 只记录不作判据** |
| **L3 参数信息量** | **[平台] 出图 → [Agent] 消费** | 逐窗口带宽图 + 五词判定（**不是一条漂亮的 D_s(x)**） |
| **L4 预测** | **[平台]**（Agent 禁入） | 冻结参数预测 1C，四道门 |

**⇒ 在这四级里，Agent 的唯一插入点是 L3 的出口。**

### 阶段 3：四个样品横比

| 谁 | 干什么 |
|---|---|
| **[平台]** | 每个样品出一张带宽图 |
| **[Agent]** | **不参与** |
| **[人]** | 比**图的形状**与**判定等级**，以及**方向差异**（同状态充/放电窗口差 **3.5–5×**） |

⚠️ **对照必须是"回收料处理组 vs 回收料未处理组"**（`RG_raw`），
**商业石墨是参照系不是处理对照** —— 这条在附件 B §1 已定。

---

## 2. Agent 在你这批数据上的**三个真实插入点**（就这三个）

### 插入点 ①：L3 门前的**候选集限定**

**不是 Agent 提议，是 Agent 被限定。**

```text
平台的 L3 输出（逐窗口判定表）
    ↓ 过滤：只留 identifiable / bounded
Agent 的候选参数集 =  这张表，而不是人手写的白名单
```

**为什么这解决真问题**：Agent 侧那个"两套名字零重叠"的 bug，
上游修法是**把名字对齐**（在 `prompt.yaml` 里补一句"用精确拼写"）。
**你的修法应该是"让白名单从图里长出来"** —— 名字由平台生成，就没有第二份名单可以和它不一致。

### 插入点 ②：`identifiable` 窗口上的**数值填充**

**Agent 在这里退化成一个"局部优化器"，不是"自主提议者"。**

| 平台给 | Agent 做 | 平台验 |
|---|---|---|
| 一个窗口 + 判定 `identifiable` + 带宽 `B` | 在该带宽内提 `D_s` 候选值 | 用 `identification/forward.py` 的 `predict_at()` 打分（**固定 D_s，不重拟合**） |

⚠️ **必须用 `predict_at` 而不是重新拟合**（`forward.py:514` 的文档字符串写得很清楚）：
"the parameter was identified on protocol A, so evaluating it on protocol B must NOT re-optimise.
Re-fitting on B would answer a different question."

### 插入点 ③：**没有任何插入** —— 失败路径也要接进去

`agent_platform_fusion.md` §7 的融合成功判据第 2 条：

> **被 `param_capability` 拒的那些轮，原因写得出来**
> （unknown / 曲线给标量 / 模型不消费 / 参数集无此键）

Agent 提了个 `unconstrained` 窗口的参数、或提了个曲线型参数给了标量值，
**平台要拒得出来并且拒得有理**。这一条比"提对了"更能证明回路是通的。

**接缝修完之后，这条失败路径现在有七种可区分的理由**（不再是笼统一句"不支持"）。
下表是**代码里的常量名逐字**（`param_capability.py:453-460`），
因为「调用方要能 **不解析散文** 就 branch」本身就是这张表存在的理由：

| 常量 | 字面值 | 触发 | 消息指向 |
|---|---|---|---|
| `UNKNOWN_PARAMETER` | `unknown_parameter` | 名字不在 14 个逻辑名里 | 拼写 + 可用名单 |
| `UNSUPPORTED_PARAMETER_REPRESENTATION` | `unsupported_parameter_representation` | 曲线型参数给了标量 | **adapter 通路 `ocp_table_path()`** |
| `PARAMETER_NOT_USED_BY_MODEL` | `parameter_not_used_by_model` | 参数集里有、但该模型不读 | 换模型 / 换参数 |
| `PARAMETER_ABSENT_FROM_PARAM_SET` | `parameter_absent_from_param_set` | 参数集里没有这个键 | 换参数集 |
| `UNSUPPORTED_INITIAL_STATE` | `unsupported_initial_state` | `method` 不在平台支持的两个里 | 平台实际支持的方法名（**接缝 C 新增**）|
| `UNSUPPORTED_CELL_CONFIGURATION` | `unsupported_cell_configuration` | 槽位解析失败（键里找不到槽位词）| 该键对布局的依赖（**接缝 A 新增**）|
| `UNSUPPORTED_PARAMETER_YET` | `unsupported_parameter_yet` | 认得这个键、但本轮没通路 | 本轮不做的理由（如 EIS→`k0`/`Rct`）|

⚠️ **光有常量还不够：新增的 kind 必须登记进 `simulator._REFUSAL_KINDS`。**
那张注册表是让调用方能**从校验消息里把 kind 结构化取出来**的东西
（`_extract_refusal` 靠它，而不是让调用方去解析散文）。
**漏登记的症状是「常量存在、消息永远不带它」** —— 一个能写出但读不回来的 kind。
`unsupported_initial_state` / `unsupported_cell_configuration` 第一版就漏了登记，
已补；并加了一条测试
（`test_every_failure_kind_is_registered_for_refusal_extraction`）
把这个性质钉住 —— **实测把注册项删掉会让它变红，不是装饰。**

⚠️ **`UNSUPPORTED_PARAMETER_YET` 从"初值的去处"变成了"真·本轮不做"**：
接缝 C 之前，声明了初值走的就是这个种类 —— 而它和「压根没声明初值」输出一样。
**现在初值有消费者了**（`check_reserved_key` 对它返回 `None`），
这个种类回归它字面的意思。

---

## 3. ✅ 三个接缝 —— **已修**（2026-09-28，改动全在本地副本）

**改的全是 `C:\Users\24330\WorkBuddy\Battery-Sim-Agent`（tarball 解压，非 git 仓库）。**
**上游 `opqrst-chen/Battery-Sim-Agent` 一行没动**（它仍是 `354f2dd`，含 10000 秒空转等原样缺陷）。

| 接缝 | 症状 | 修法 | 落点 |
|---|---|---|---|
| **A** | 14 个逻辑名**全映射全电池双电极键**，石墨在正极槽位时语义错 | 新增 `resolve_pybamm_key(name, cell_configuration)`，`full_cell` 原样返回；半电池只重指槽位词 | `param_capability.py` |
| **B** | 曲线参数拒绝消息是「曲线型给标量」，**不说该走哪条路** | 拒绝时指名 adapter 通路 `ocp_table_path()`，并写明「把这里放宽成收数字**不是**修法」 | `param_capability.py` |
| **C** | `initial_state` 被当**保留键直接拒**，初值策略不可端到端传递 | 翻成平台 `df.attrs['initialisation']` 块；新增 `initialisation_block()` + `_apply_initialisation()` | `param_capability.py` / `simulator.py` |

### 接缝 A：桥的**参数白名单全是全电池键**（实测）
`battery_agent/param_capability.py` 的 `PARAMETERS` 共 **14 个逻辑名**，
**全部**映射到 `Positive/Negative electrode ...` 的**全电池双电极键**，
且都带 `models: ("SPM","SPMe","DFN")`。**没有任何半电池概念。**

对你石墨 half-cell（石墨在**正极槽位**）：

| 桥的键 | 你的真实含义 | 状态 |
|---|---|---|
| `positive electrode thickness` | **石墨**极片厚度 | ✅ 已可重指（`half_cell_positive` → 槽位不变、语义由声明负责） |
| `particle_radius` → `Positive particle radius [m]` | 石墨颗粒半径 | ✅ 数值上可用 |
| `particle_diffusivity` → `Positive particle diffusivity` | **石墨** D_s | ✅ `RESOLVED`，需探测（探测问的是**重指后**的键） |
| `ocp` → `Positive electrode OCP [V]` | 石墨 OCP | ❌ **不需要**（走 adapter，见接缝 B） |
| — | `Negative electrode ...`（锂对电极） | ✅ `half_cell_negative` 可重指到该槽位 |

**已按 A1 实施**：改的是**桥**（本地副本），**不动上游 `param_capability.py` 的 14 个键**。

关键实现细节（第一次写错过，被测试抓回来）：

- 槽位词在声明的键里有**两种拼法** —— 首字母式 `"Positive particle radius [m]"`，
  和**串中小写式** `"Maximum concentration in positive electrode [mol.m-3]"`。
  **只匹配首字母会把 `max_concentration` / `initial_concentration` 漏掉**。
  现在两种拼法都重指，**且保留原大小写**。
- 分类是**穷举 + 断言**的：`SLOT_DEPENDENT_LOGICAL_NAMES`（12 个）
  + `SLOT_INDEPENDENT_LOGICAL_NAMES`（`temperature` / `nominal_capacity`，2 个）
  = 14，测试 `test_classification_covers_every_parameter` 强制这个等式。
  **将来加参数忘了分类会当场报错，不会静默按全电池处理。**
- 槽位不是桥猜的，是**从数据集声明里读**的：
  `_cell_configuration_for(adapter)` 读 `config.extra['cell_configuration']`；
  只写裸 `half_cell` 时按 `working_electrode` 补成 `half_cell_<slot>`。
  测试 `test_bridge_reads_dataset_layout.py` 用两个**不同槽位**的适配器证明它读的是声明。

- **⚠️ 第四处修复（沿同一个病继续查出来的）**：`_cell_configuration_for` 原来在
  **裸 `half_cell` 但槽位字段不可识别**时**静默退回 `full_cell`**。
  这又是那个病：**声明说半电池，跑的却是全电池键，输出不会告诉你**。
  更糟的是**两侧行为不一致** —— `resolve_pybamm_key` 遇到不认识的配置**会拒**
  （`param_capability.py:798`），而这里会降级；**同一个坏输入得到两个判决**。
  现已改成**响亮失败**（`BridgeError` → `simulate` 转成
  `contract_violation` + `refusal_kind=unsupported_cell_configuration`），
  并具名指出 `working_electrode` 才是槽位、
  **`physical_working_electrode` 是材料名**（`"graphite_negative"`）不能当槽位用。
  新增 `test_the_resolver_and_this_reader_agree_on_what_is_valid`
  把两侧的接受词表钉在一起 —— **实测恢复旧降级会让两条测试变红**。

### 接缝 B：**曲线参数的拒绝必须指出通路**（好消息：不是缺口）

`ocp` 与 `particle_diffusivity` 在桥里仍然拒绝标量值 —— **这条没变，也不该变**。

**但拒绝消息现在指名道姓**：

```text
ocp is a curve-valued parameter: the platform supplies it from the measured
table via the dataset adapter (ocp_table_path()); widening this interface to
accept a number here is NOT the fix.
```

⚠️ **一个必须记清的区别**（我第一版测试写错了，是测试错了不是代码错了）：

| 逻辑名 | 声明 | 无探测时行为 |
|---|---|---|
| `ocp` | **`RESOLVED`** | **推迟**（deferred），不是拒绝 |
| `particle_diffusivity` | **`RESOLVED`** | 同上 |

`RESOLVED` = 「随参数集而变，需要探测才知道是标量还是曲线」；
只有探测回来说「这是曲线」时才拒绝。所以 `check_declaration(...)` 直接给 `CURVE`
才会拿到拒绝 —— **测试必须显式区分 `RESOLVED` 与 `CURVE`**，否则断言是空的。

**在你这条路上 OCP 根本不需要桥**：

```text
实测 p-OCV 双支表 → RecycledGraphiteAdapter.ocp_table_path()   (recycled_graphite.py:383)
                  → 平台内部替进参数集 → run_baseline_cell 回放
```

⇒ **平台侧不需要新的「曲线覆盖公开入口」**。
（`agent_platform_fusion.md` §3③ 把它列为「唯一必须进 v0.1.1 的融合项」，
那是为**全电池 Agent 提议 OCP 曲线**设的场景，与你的实验无关。）

### 接缝 C：**初始态**（`initial_state`）—— **原来是这么坏的**

**症状**：桥把 `initial_state` 列为保留键，**一律拒绝**。
**为什么这是病**：拒绝让「声明了初值」和「没声明初值」输出**完全一样** ——
声明的东西被静默丢掉，而这**恰好**是 B0.5 那个 44.64 mV vs 48.36 mV 的成因
（初值策略不可端到端传递）。

**修法**：不再拒绝，翻成平台消费的形状：

```python
# 1) schema 校验：method 必须是平台认识的两个之一
PLATFORM_INITIALISATION_METHODS = ("initial_soc", "fixed_initial_concentration")
# 2) 值域：stoichiometry_from_ocp 必须在 (0, 1) 开区间
# 3) 补齐平台要的键（按槽位解析），ocp_voltage_V 必填
block, refusal = initialisation_block(initial_state,
                                      cell_configuration=cfg)
# 4) 装进 df.attrs['initialisation']，由 baseline.py::_run_one_replay 消费
_apply_initialisation(adapter, cell, block)
```

**⚠️ 修完接缝 A 之后，才发现接缝 C 里藏着同一个病的两个变种**（都是**读平台源码**才发现的）：

| 变种 | 桥原来怎么写 | 平台实际怎么消费 | 后果 |
|---|---|---|---|
| **键名硬编码 `positive`** | `"Initial concentration in positive electrode [mol.m-3]"` 写死在默认值里 | `params[conc_key]` 直接查参数集（`baseline.py:277-285`）| 石墨半电池落在**负极槽位**时 ⇒ **`ValueError`** |
| **`ocp_voltage_V` 当"元数据"** | 注释写 "metadata for the record, NOT an input"，缺失就不带 | `init_block["ocp_voltage_V"]` **硬下标**（`baseline.py:287`）| 缺失 ⇒ **`KeyError`** |

⇒ **两处都已修**：
- 键名改走 `resolve_pybamm_key("initial_concentration"/"max_concentration", cfg)`，
  按槽位解析（不再硬编码）；
- `ocp_voltage_V` 变成 `fixed_initial_concentration` 的**必填**，缺失时桥侧具名拒绝。

**为什么这比原方案更重要**：第一版「只在实测到时才带」的写法**看起来更谨慎**，
实际是**把失败推到了求解时**，而且推成了一个和初值无关的报错
（`KeyError` 出现在 `baseline.py` 而不是桥）。**安静地少给一个必填字段 ≠ 谨慎。**

**交叉校验**（`scripts/_shape_check.py`，实测 PASS）：
桥的块与平台 `RecycledGraphiteAdapter.initialisation_block()` 的块
**键集合逐一相同**（6 个键），两个参数键名**逐字一致**：

```text
桥的键 / 平台的键 : {concentration_parameter, mapping_reason,
                    max_concentration_parameter, method,
                    ocp_voltage_V, stoichiometry_from_ocp}
平台有而桥没有    : 无
桥有而平台没有    : 无
conc 键一致 / cmax 键一致 : True / True
结论: PASS
```

⇒ **系统里只有一种 initialisation 块形状，没有"桥方言"。**

**`_apply_initialisation` 为什么不直接改平台 API**：它**包装**适配器的
`load_processed_discharge` / `load_processed_protocol`，在返回的 DataFrame 上挂
`attrs['initialisation']`。**平台侧一行没改**（`ee2fb36` 保持冻结），
而且这条路对**任何**适配器都成立，不需要每个适配器自己记得挂。

**层一致性守卫**（`tests/test_initial_state_wiring.py`）：
有一条测试**读源码**，断言 `PLATFORM_INITIALISATION_METHODS` 与
`battery_sim/simulation/baseline.py` 里 `_run_one_replay` 实际 `if` 分支的字符串**一致**。
另有两条**反向守卫**读平台源码，断言：
① `init_block["ocp_voltage_V"]` 这个**硬下标**仍然存在（否则桥的"必填"就该放宽）；
② 平台仍用 `init_block.get("concentration_parameter")` **按名查**（否则槽位解析无意义）。
⇒ **平台若改了消费方式，桥的测试会红**，而不是桥继续按旧假设翻译。

### 三接缝联合实测（`scripts/_seam_demo.py`）

一条真实的回收石墨半电池请求（`Ecker2015_graphite_halfcell` + `particle_radius`
+ `particle_diffusivity` + `initial_state{stoich 0.001, OCP 0.780 V}`）跑通的输出：

```text
接缝A 槽位解析 : half_cell_positive
校验           : PASS
接缝A 覆写键   : particle_radius       -> Positive particle radius [m]
                 particle_diffusivity  -> Positive particle diffusivity [m2.s-1]
接缝C 初值块   : {method: fixed_initial_concentration, stoichiometry_from_ocp: 0.001,
                  ocp_voltage_V: 0.78,
                  concentration_parameter: Initial concentration in positive electrode [mol.m-3]}
接缝C 负对照   : 缺 ocp_voltage_V -> 拒绝
接缝B 曲线拒绝 : 指向 adapter 通路 = True
负对照         : particle_diffusivity 无 probe -> 拒绝
```

**测试基线：`222` → `283 passed, 1 skipped`**（净增 56；同时**删掉/改写了 8 个
"断言桥会拒绝它做不到的事"的测试** —— 那些测试**把病写进了断言**，
现在改成断言那条拒绝原本要守的性质：**声明了的初值不许被静默忽略**）。

⚠️ **`scripts/_seam_demo.py` 与 `scripts/_shape_check.py` 是一次性验证脚本**
（`_` 前缀，与既有 `_output_isolation.py` 同约定），可删或提升为测试 ——
它们住在**平台的 `scripts/`** 下但**验证的是 Agent 侧的桥**，位置本身就该再想一次。

---

## 4. 明确不做（三条，都有实测理由）

| 不做 | 理由 |
|---|---|
| 让 Agent 参与 **L1/L2** | 那是数据接入与回放，**没有参数可提** |
| 让 Agent 参与 **L4** | 回改即 L4 作废（预注册已冻结）；且 holdout 一旦进迭代就永久失效 |
| **先做多参数联合辨识** | G6.1b/1c 已证：**瓶颈在激励不在参数化**（放电扫程 **239 个窗口一个都不合格**） |
| 把 BO / CMA-ES 搬进平台 | 那是 Agent 的**基线**不是平台的**判据**；且**算法本身也不是上游自研的**（BO 走 `ax.service.ax_client.AxClient`，CMA-ES 走 `import cma`） |

---

## 5. 接线图上最容易搞错的**四处**（都是踩过的）

| # | 容易搞错 | 实际 |
|---|---|---|
| 1 | "Agent 提参数 → 平台跑 → 给个 RMSE" | 回灌的是**判定词**。**只有判定词是全新信息** —— 这就是融合能成论文的原因 |
| 2 | "GITT 做完就能反演出 `D_s(x)`" | 产出是**逐窗口判定表**。G6.1c 实测：225 个放电窗口 **0 个**、230 个充电窗口 **3 个**达 0.30 dex |
| 3 | "四组处理温度 = 四组 D_s 比较" | 比的是**图的形状与判定等级**。且**粒径必须先测**（D ∝ R²：粒径差 2× ⇒ D_s 差 4×，`CG-AR` 实测 D50 17.58 µm vs 假设 13.70 µm **差 1.56×**） |
| 4 | "1C 先拿来试跑一下调参" | **L4 当场永久失效** |
| 5 | "接缝修好了 ⇒ 现在可以接 Agent 了" | **修接缝 ≠ 接上回路**。接缝只是**让回路能通**；接线点仍在 **L3 出口**（§6 第 ④ 根柱子）|
| 6 | "半电池映射做完，参数就该对上了" | 映射只解决**键名寻址**。**值**对不对是另一回事 —— 粒径仍须实测，载量/厚度/面积/D50 **仍没有代码通路进 `parameter_overrides`**（须人工转写 + `run_record` 留痕）|

---

## 6. 顺序（什么时候接哪根线）

```text
现在    ──── ① 阶段 0：定死方案 / 红线 / τ 口径        [人]
               其中可并行：修 Agent 侧名字对齐的 bug     [Agent]
               ↓
           ② 由 CG-AR（或 RG_raw）过 L1/L2              [平台]
               ↓
           ③ 补接缝 A / B / C        ✅ 已完成 2026-09-28  [桥]
              + 补单位层（affine）      ← 仍未做，v0.1.1  [平台]
               ↓
           ④ L3 出带宽图 ────────────► **接线点在这里**  [平台]
               ↓                            ↓
           ⑤ L4 冻结参数预测 1C         ⑥ 带宽图 → 候选白名单     [平台→Agent]
               ↓                            ↓
                                       ⑦ 插入点 ①②③ 开动        [Agent]
```

**三根时间线上的硬柱子**：
1. **① 之前不碰 Agent**（附件 B §2：A2/A3/A4/A6 任一条没定不许开跑）。
2. **④ 之前不接 Agent**（没有带宽图，Agent 的候选集就是手写名单 —— 回到那个 bug）。
3. **⑤ 之后 Agent 只读不写**（L4 冻结的参数一个都不许回改）。

**⚠️ 接缝已修不改变上面任何一根柱子。** ③ 修完只意味着**线路通了**；
**④ 没到就接上，回路依然是空转的** —— 因为⑧那一步（Agent 提数）的**依据**
是 L3 的判定词，没有图就没有依据，Agent 只能退回手写白名单。

---

## 7. 一句话总结

**融合是一个回路，不是一次集成。** 对你的回收石墨实验：

- **平台负责**：数据接入（L1）、回放（L2）、**判定每个窗口能不能反演（L3）**、冻结参数做预测（L4）；
- **Agent 负责**：**只在 L3 说"能"的地方提数**，退化成局部优化器；
- **桥负责**：把半电池语义、曲线参数、初值策略翻译过去（**接缝 A / B / C**）；
- **回灌的是判定词，不是 RMSE** —— 这是整条回路区别于"跑个优化器"的唯一地方。

⇒ **Agent 的活最少，但位置最关键：它只在最不缺数据的地方动手，在数据不够的地方闭嘴。**
