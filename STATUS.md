# STATUS.md — 唯一可信状态页

> 本文件是平台状态的**唯一真源**。任何其它文档（README / HANDOFF / docs/*.md）里的
> 状态描述、测试数、阶段结论，若与本文件冲突，**以本文件为准**。
>
> 维护规则：只允许在本文件写"已验证"的数字。每个数字必须写明**验证方式**与**验证日期**。
> 不允许写"应该""大约""计划中"。

---

## 版本

```text
Platform version:       v0.1 (run_pipeline.py 自述版本；尚无语义化版本号)
Last verified commit:   12a6cd9  (2026-09-15, "feat: add traceable runtime parameter overrides")
origin/main:            ee45d62  (本地领先 1 个 commit，**尚未 push**)
Working tree:           见「已知限制 #1」
STATUS.md last updated: 2026-09-15
```

---

## 工程门（Engineering gates）

```text
G0 环境可复现        PARTIAL  — 本机可跑；未在干净机器上验证过
G1 数据接入          PASS     — 2026-09-15 实测
G2 SPM/SPMe/DFN 回放 PASS     — 2026-09-15 实测
G3 provenance        PASS     — 2026-09-15 实测
```

### G0 环境可复现 — PARTIAL

- **PASS 的部分**：本机（WSL Ubuntu / conda env `pybamm`）按 README 可完整跑通，
  PyBaMM 26.8.0 / PyBOP 26.3 / numpy 2.3.5 / pandas 3.0.5。
- **未验证的部分**：**没有在干净 clone 的机器上跑过**。因此不能声称"新机器能跑起来"。
- **已知的环境陷阱**（不在任何安装文档里，只存在于脚本与经验中）：
  - Windows 侧 Python **没有 pandas**，仿真必须走 WSL。这是一个硬分叉，新人不看代码发现不了。
  - Windows git 的 `credential.helper` 与 `refs/remotes/origin/main` 需要修复才能 push；
    修复脚本为 `scripts/dev/apply_env_fixes.sh`。**"新 clone 需重跑此脚本"这件事写在脚本注释里，
    没写在 README 里。**

### G1 数据接入 — PASS

验证方式（2026-09-15）：

```bash
python -m user_tools.import_dataset --package examples/half_cell_demo
```

结果：679 行转 canonical / 12 项校验 / 严重 0 / 警告 2 / 匹配参数集
`Jackowska2025_2mAh_cm2` (grade B) / 输出 `outputs/user_datasets/demo_birmingham_cover5`。

### G2 SPM/SPMe/DFN 回放 — PASS

验证方式（2026-09-15）：

```bash
python run_pipeline.py --list-datasets
python run_pipeline.py baseline --dataset sintef_graphite --model SPM
python -m user_tools.run_baseline --package examples/half_cell_demo --models DFN
```

已注册数据集 6 个：`chen2020` / `calce_cs2` / `calce_20r` /
`birmingham_ncm920305` / `calce_a123` / `sintef_graphite`。

### G3 provenance — PASS

单次 baseline 落盘 8 个产物（石墨 SPM / cell4ccc47 实测）：

```text
metrics.csv
run_metadata.json                  （24 个键）
<rate>_time_aligned.csv
<rate>_Vt.png
<rate>_parameter_mapping.json
```

`run_metadata.json` 含：`parameter_set` / `parameter_source` / `parameter_repo_commit` /
`pybamm_version` / `working_electrode` / `model_options` / `capacity_metric_type` /
`capacity_is_predictive` / `capacity_metric_note` / `parameter_overrides_requested` /
`parameter_match` / `timestamp` / `runtime_s`（共 24 项）。

**本门是全平台做得最扎实的部分**：`surrogate` / `zero-fit` / `not a validation run`
等标注直接进入机器可读字段，而不是只写在散文里。

---

## 科学门（Scientific gates）

```text
G4 OCP/GITT 提取         PASS（受限）  — 见下方限定
G5 参数辨识 / 可信性      IN PROGRESS   — G5.0 PASS；G5.1 IN PROGRESS
  G5.0 单参数 synthetic recovery（集成验证）  PASS     — 2026-09-15
  G5.1 加噪声 recovery（0.5/1/2/5 mV）        PASS     — 2026-09-16（偏差未被确定，见下）
  G5.2 模型失配（SPMe→SPM）+ cross-protocol   PASS     — 2026-09-16（参数被污染，见下）
  G5.3 双参数 {D_s, R_p} 耦合                  NOT STARTED
  G5.4 真实实验 + cross-protocol 验证           NOT STARTED
G6 held-out 预测         NOT DONE
G7 再生状态泛化          NOT STARTED
G8 优化闭环              NOT DONE
```

**G5 的判据已重新定义**：从"优化器能不能找到真值？"改为

> **"这个参数在噪声、模型失配、不同 protocol 下，是否仍具有唯一性与可迁移性？"**

### G4 OCP/GITT 提取 — PASS（受限）

已完成且有封版值：双支 OCP 派生、容量一致化、GITT 按日志间隙分段、表观 D_s 反演。

**限定条件（必须一起引用，否则会误读）**：

- D_s 反演已得出**否定性结论**：单颗粒模型是这份数据的错误透镜。
  共同集 614 条中位 `2.155e-16`，比参考低 57×；一阶/二阶两种函数形式给出同一质性结论。
  → **"能提取"不等于"提取出的东西是物理参数"。**
- `B1` 与 `B1.6` 是**诊断**，不是验证。
- 实验反演出的 D_s 是 **apparent / effective**，不是本征材料常数。

### G5.0 单参数 synthetic recovery — **PASS**（2026-09-15）｜**口径：集成验证**

> **这一关的名字是"集成验证"，不是"参数辨识完成"。**
>
> 它证明的是**管道连通**，不是真实 $D_s$ 可辨识。
> 因为生成数据与反演数据用的是**同一模型、同一物理结构、同一参数定义** ——
> 典型的 **inverse crime**：
> $$\text{synthetic recovery success} \;\neqq\; \text{experimental identifiability}$$
>
> 真值处 cost **精确为 0** 也是**构造出来的，不是拟合出来的**
> （那份"观测"就是平台自己在真值处的输出）。

**问题**：给定一个在已知 $D_s$ 处生成的 synthetic 电压响应，管道能不能把它找回来？

**完整报告**：`docs/g5.0_synthetic_recovery.md`
**可复现命令**：`python scripts/identification/g5_0_synthetic_recovery.py`（约 39 s）

```text
dataset/cell/rate   chen2020 / 02 / C2      model  SPM
D_s_true            2.0e-15                 z = log10(D_s) ∈ [-16, -13]
三个初值            1e-15, 4e-15, 1e-14     同一份观测（284 点，t_end 7090.5 s）
optimiser           pybop.SciPyMinimize(method="Nelder-Mead")
```

| 验收项 | 结果 | 数字 |
|---|---|---|
| ① 同一 basin | **PASS** | 三个初值 → `1.999979e-15` / `1.999815e-15` / `1.999979e-15`，散布 **0.00004 dex** |
| ② 接近真值 | **PASS** | 最差相对误差 **0.009 %**（容差 5 %） |
| ③ cost 曲线最低点在真值附近 | **PASS** | 显式扫描（粗扫 0.2 dex + 细扫 0.043 dex），argmin 距真值 **0.0010 dex**；**真值处实测 $J = 0.000\times10^{0}$** |
| ④ provenance 完整 | **PASS** | **92 次评估，0 次缺失**；每次都有 requested / applied(old,new,source) / run_metadata.json 路径 |

**这一步证明的是管道连通，不是物理**：
`PyBOP → parameter override → PyBaMM → cost → optimizer → recovered parameter` 闭合。

**没有证明的（必须一起引用）**：
- 不证明 $D_s$ 在**真实**数据上可辨识（→ G5.2）
- 不证明 $D_s$ 与其它参数**不互相补偿**（→ G5.1 二维）
- 观测是平台自己的输出，**zero residual 是构造出来的，不是拟合出来的**
- 单倍率（C2）、单模型（SPM）；换倍率/模型不保证同样成立

**两处判据错误已修并记档**（都不是物理问题，是我把验收标准写错了）：
① 容差比网格间距还小 → 一条**网格定位精度不可能优于其步长**；
② 用线性插值估"真值处 cost" → 最低点仅 ~$10^{-3}$ dex 宽，插值暴涨 4 个数量级。
→ 修法：容差取 `max(名义, 实测分辨率)` + 加细化扫描；**真值直接实测，不插值**。

### G5.1 加噪声 recovery — **PASS**（2026-09-16）｜偏差**未被确定**

完整报告 `docs/g5.1_noise_recovery.md`。
可复现：`python scripts/identification/g5_1_noise_recovery.py`（约 410 s，5 噪声水平 × 3 种子 × 3 初值 = 45 次恢复）

| σ (mV) | 偏差 (dex) | 偏差 (%) | 种子间 std (dex) | 多初值散布 (dex) | **fit RMS (mV)** |
|---|---|---|---|---|---|
| 0 | −0.00002 | −0.004 | 0 | 0.00004 | **0.003** |
| 0.5 | −0.00014 | −0.03 | ±0.00015 | 0.00007 | **0.492** |
| 1 | −0.00027 | −0.06 | ±0.00030 | 0.00007 | **0.983** |
| 2 | −0.00056 | −0.13 | ±0.00058 | 0.00007 | **1.966** |
| 5 | −0.00142 | −0.33 | ±0.00146 | 0.00005 | **4.915** |

**两条已建立**：
① **`fit RMS` 紧贴注入噪声**（比值 0.98，稳定在 5 个水平上）
   → 优化器**没有拟合噪声**，也不是够不着数据。
② **主导不确定度是"噪声实现"而非优化器**：多初值散布 ≤ 0.00007 dex，
   而种子间 std 到 ±0.00146 dex。**报精度应当报对噪声实现的敏感度。**

**一条未建立（必须一起引用）**：σ ≥ 0.5 时"偏差"一列全为负，**看着像系统性下偏，但不能这样读** ——
5 mV 时平均偏差 −0.00142 **小于**种子间 std ±0.00146，且 seed 0 的偏差是**正**的。
**3 个种子无法把"偏差"与"抽样散度"分开。** 目前只能说偏差量级 ≤ 0.15 %（2σ，5 mV）。

**边界**：噪声是高斯、加性、独立同分布；**仍未涉及模型失配**（→ G5.2）；
单倍率（C2）、单参数；观测仍是平台合成输出。

### G5.2 模型失配 — **PASS**（2026-09-16）｜**参数被污染，"拟合好"不等于"参数对"**

完整报告 `docs/g5.2_model_mismatch.md`。
可复现：`python scripts/identification/g5_2_model_mismatch.py`（约 270 s）

```text
Control   SPM  truth → SPM  inverse   （4 个倍率）
Mismatch  SPMe truth → SPM  inverse   （4 个倍率）
始终只辨识一个参数；无噪声（把失配与噪声分开）
```

**倍率可用性**：门控要求 C/20, C/10, C/5, 0.5C, 1C, 2C；
**chen2020 只有 0.1C / 0.5C / 1C / 1.5C**，缺的三种已在报告标明。

| 倍率 | Control 偏差 | **Mismatch** $D_s^*$ | **Mismatch 偏差** | **残差地板** |
|---|---|---|---|---|
| C10 (0.1C) | −0.001 % | 1.499796e-15 | **−25.01 %** | **1.6562 mV** |
| C2 (0.5C) | −0.001 % | 1.446921e-15 | **−27.65 %** | **7.0108 mV** |
| 1C | −0.001 % | 1.679975e-15 | **−16.00 %** | **33.0200 mV** |
| 1p5C (1.5C) | −0.001 % | 1.992946e-15 | **−0.35 %** | **92.5719 mV** |

跨倍率散布：control **0.00001 dex** vs mismatch **0.13905 dex**。

**① Control 证明链路没坏**（最差 0.00379 %，$D_s$ 与 protocol 无关）。

**② 两个现象方向相反**：
倍率↑ → 参数偏差**缩小**（−0.125 → −0.002），残差地板**单调放大 56×**（1.66 → 92.57 mV）。
→ **"高倍率下识别出真值"不是成功，是危险信号** —— 那时 $D_s$ 已失去杠杆作用。

**③ 最危险的一条 —— 错误模型下真值不是最优解**：
用低倍率辨识出的"错"参数（$D_s^*$=1.45–1.50e-15）跨 protocol 预测，
**在 C10 和 C2 上都比真值好 3.4×**；而 1.5C 的"看似恢复真值"对应的地板是 92.6 mV。
→ **若手上只有 SPM 拟合结果，会报告 $D_s\approx1.45\times10^{-15}$ 为材料参数，
它在每个 protocol 上都比真值拟合得好，残差健康，跨倍率"可迁移" —— 且没有任何残差信号提示它是错的。**

**④ 可迁移性检验反向失效**：低倍率 → 高倍率 **完全跑不通**（5 个单元格 unreachable，
覆盖 < 50 %）；高倍率 → 低倍率跑得通但差（5.602 vs 1.656）。
→ **不存在 protocol 无关的 $D_s$。**

**边界**：仍是合成数据（换掉的是**模型形式**，不是数据来源）；只测了一个方向的失配
（SPMe→SPM）；单电芯（cell 02）、单参数集；倍率覆盖不全。
**没有**结论说"SPM 不能用" —— 结论是**SPM 下辨识出的 $D_s$ 是 effective parameter，
不是材料常数**，而它"看起来很好"本身就是失配的证据。

### G5 的历史起点 — 平台曾零拟合代码

**证据（2026-09-15，全仓搜索）**：

```bash
grep -rn "import pybop\|from pybop" --include="*.py" \
  battery_sim/ parameters/ extraction/ user_tools/
# → 0 命中（G5.0 开工前）
```

`identification/` 是 G5.0 新增的层；平台冻结内核
（runner / evaluator / factory / registry / rates.py / paths.py）**未改动**。

**环境侧**：PyBOP 26.3 已安装且可 import。但注意 ——
**26.3 的 API 与公开教程不一致**，以下名字在 26.3 中**不存在**：

| 教程里的写法 | 26.3 实际 |
|---|---|
| `pybop.FittingProblem` | `pybop.Problem(simulator, cost)` |
| `pybop.Parameterisation` | `pybop.Parameters` / `pybop.Parameter` |
| `pybop.Optimisation` | `pybop.optimisers.*`（scipy / pints） |
| — | `pybop.ScipyOptimise` 亦不存在，须走子模块 |

直接相关的现成工具（26.3 自带）：
`pybop.lithium_ion.SPDiffusion`、`pybop.lithium_ion.WeppnerHuggins`、
`pybop.applications.gitt_methods`。

→ **任何照抄网上 PyBOP 示例的代码都不能直接运行。**

### G5 的历史路障：一个已修掉的假拒绝（2026-09-15 发现并修复）

参数覆盖能力表把 `particle_diffusivity` 全局声明为 **CURVE**（标量一律拒绝）。
但**表示形式是 (参数, 参数集) 的属性，不是全局属性**：

| pybamm 键 | Chen2020 | Ecker2015_graphite_halfcell |
|---|---|---|
| `Positive particle diffusivity [m2.s-1]` | **float = 4e-15** | **function** |
| `Positive electrode exchange-current density [A.m-2]` | function | function |

后果：在 Chen2020 上，一个**本来就是 float** 的 `D_s` 会被以
`unsupported_parameter_representation` **误拒** —— 而它正是第一版辨识向量里最该辨识的那个。
拒绝理由看起来完全合理，不会有任何告警。

**已修**（2026-09-15）：参数表示不再按名字全局声明，改为按 `(参数, 参数集)` 运行时解析。
见下一节。

---

## 能力分级：`consumed` 是一个歧义词，已拆成五级

一个参数要能进入辨识，必须**依次**过五关。把前几关混成一句"被消费了"，
会同时犯两种错：**误拒**可用的参数，和**放过**根本不起作用的参数。
两者都实测到过。

```text
representable → accepted → resolved → numerically_active → identifiable
```

| 级别 | 问题 | 判定方式 | 实测反例 |
|---|---|---|---|
| **representable** | 平台能否**表达**这种参数形式？ | 探测该键在**当前参数集**里的类型 | `D_s` 在 Chen2020 是 float，在石墨集是 function |
| **accepted** | 安全检查是否放行这个覆盖？ | 能力表 + 单位/模型适用性 | — |
| **resolved** | 模型构建时是否**查找**该参数？ | 删键看能否构建 | SPM 会解析 `porosity` |
| **numerically_active** | 改它是否**真的改变**预测？ | 覆盖后看解是否移动 | SPM 下 `porosity` **逐位不变** |
| **identifiable** | 能否从数据中把它与其它参数**区分**？ | G5 的 identifiability 分析 | **尚待验证** |

**关键区分：`resolved` 会高报，必须用 `numerically_active` 才能下结论。**
判"适用模型"那张表记录的是 `numerically_active`，不是 `resolved`。

| 参数 · 条件 | representable | accepted | resolved | numerically_active | identifiable |
|---|---|---|---|---|---|
| $D_s$ · Chen2020 · SPM/SPMe/DFN | ✓ | ✓ | ✓ | **✓**（RMSE −25.63 / −21.88 / −21.88） | 尚待 G5 |
| $\epsilon_{am}$ · Chen2020 · SPM | ✓ | ✓ | ✓ | **✓**（RMSE −38.31） | 尚待 G5 |
| $R_{ohm}$ · Chen2020 **默认 options** | ✓ | ✓ | ✓ | **✗**（delta 恰好 `0.000000`） | — |
| $R_{ohm}$ · Chen2020 **+ `contact resistance: "true"`** | ✓ | ✓ | ✓ | **✓**（−37.63 / −31.70 / −31.66） | 尚待 G5 |
| `porosity` · SPM | ✓ | ✗ | ✓ | **✗**（delta 恰好 `0.000000`） | — |
| $k_0$ · Chen2020 | ✗（函数） | ✗ | — | — | — |
| `temperature` · Chen2020 / 石墨 | ✓ | ✓ | ✓ | **✗**（PyBaMM 构建期折入） | — |

**`numerically_active` 可以是"带条件的"** —— `R_ohm` 就是唯一的确证案例：
默认配置下位移**恰好 `0.000000`**，开启 `contact resistance` 后位移 **−37.6 mV**。
所以它必须**分两行记录**，写成单一状态就是错的。

**已隔离验证**（`tests/test_contact_resistance_option.py`，11 项）：通过
`_run_one_replay` 显式传 `model_options`，**不改 `configs/datasets.yaml`**。
该文件表达"这个数据集默认怎么跑"，不承担能力探针的职责；测试里有一条
断言把这个隔离契约**钉死**（配置块里出现 `contact resistance` 即失败）。

**附带钉住一个坑**：该 option 的值必须是**字符串** `"true"`，传布尔 `True` 会被 PyBaMM
以 `OptionError` 拒绝。这个错误曾被宽泛的 `except` 吞掉，导致探针"成功"跑出
"参数惰性"的假结论 —— 现在它是测试而非注释。

**两处诚实边界**：
- "resolved 用删键法、numerically_active 用覆盖法"这两个探针**不可互换**，
  混用会得出错误结论（删键法会高报：它说 SPM 解析 `porosity`，而覆盖它逐位不变）。
- $D_s$ / $\epsilon_{am}$ 的 `numerically_active` 已证，但 **`identifiable` 尚待 G5** ——
  位移大只说明"能动"，不说明"能从数据里与其它参数区分开"。

### G6 / G7 / G8 — 未完成

`G6` 依赖 G5；`G7` 依赖回收石墨数据到位；`G8` 依赖 G5+G6。

---

## 测试状态

```text
pytest:        329 passed, 5 warnings
failures:      0
duration:      100.16s
last run date: 2026-09-15  (提交前复跑)
command:       python -m pytest -q   (WSL, conda env pybamm)
```

**文档中的测试数已过期，勿引用**（2026-09-15 核对）：

| 文件 | 写的数 | 实际 |
|---|---|---|
| `README.md` | 293 | **329** |
| `HANDOFF.md` | 88 | **329** |

两个数字互不相同，且都与实际不符。已改为指向本文件，不再写死数字。
**引用测试数时只引用本文件的 329。**

---

## 已知限制

1. **`initial_state` 仍未实现，44.64 mV 缺口未闭合。**
   当前 48.36 mV 是公共接口的诚实结果。闭合需要把初值策略放进 request
   （与"顶层只有四个字段"冲突），属独立设计任务。

2. **覆盖 API 已提交但未 push。**
   `12a6cd9 feat: add traceable runtime parameter overrides`（+753/−0）在本地 `main` 上，
   `origin/main` 还停在 `ee45d62`。
   → **任何人 clone 远程仓库仍看不到这个 API。** 需要 push 才对导师可见。

3. **跑一次 pipeline 会改动被 git 跟踪的产物文件。**
   `outputs/` 有 418 个文件在版本控制内。一次 baseline 会改 6 个文件。
   实测差异内容：`timestamp`、`runtime_s`，以及 schema 新增的
   `parameter_overrides_requested` / `parameter_overrides_applied` / `parameter_override_sources`。
   **数值结果逐位不变**（`150.05925543689233` / `875.752828973872` 完全一致）——
   即**结果可复现，但产物不可复现（含时间戳）**。
   → 长期建议：`outputs/` 不入 git，只保留少数 golden regression artifacts。
   命名口径：`timestamp`/`runtime_s` 是 **execution metadata**（本该变），
   RMSE/模型版本/参数集 commit/覆盖记录/输入 hash/solver 设置才是 **science payload**（该冻结）。

4. **`_PARAM_SET_ABSENT_KNOWN` 已降级为"离线近似"。**
   探针可用时缺失判定走真实的 `KEY_ABSENT`；这份硬编码名单只在
   `validate_request`（平台无关层）无探针时兜底。

5. **Agent 侧 bridge 耦合平台输出布局**（依赖 `{rate_slug}_time_aligned.csv`）。
   平台输出目录结构一旦调整，Agent 侧会静默失效。

6. **Agent 仓库没有 `.git`**（当初 tarball 解压）→ 它的改动**无法提交**，
   也没有 upstream commit ancestry。上游 `opqrst-chen/Battery-Sim-Agent` 的写权限未确认。
   **不要直接在 tarball 上 `git init`**——那会丢掉来源历史。

7. **石墨线的 `Ecker2015_graphite_halfcell` 参考集半径与其自身不一致**
   （用户商业石墨 D50 = 17.58 µm vs 参考集 13.7 µm，差 1.56×；因 D ∝ R²，
   对 D 是 2.4× 量级）。**这不是 bug，是已知系统性不确定度，必须在论文里报。**

---

## 一句话状态

> 工程基础设施（G0–G4）可用且 provenance 扎实。
> **G5 已推进到 5.2**，主线判据是"参数在噪声、模型失配、不同 protocol 下
> 是否仍具唯一性与可迁移性"，而不是"优化器能不能找到真值"。
>
> 目前最重要的**科学**结论（G5.2）：
> **在结构错误的模型下，被辨识出的"错"参数会优于真值** ——
> 低倍率时残差只有 1.66 mV、看起来完全成功，而参数已偏 25 %；
> **没有任何残差信号会提示它是错的**。
>
> 即：
> $$\text{parameter fit} \neqq \text{parameter identification} \neqq \text{physical transferability}$$
>
> **口径提醒**：G5.0–5.2 **全部是合成数据**。
> 换掉的是模型形式与噪声，**不是数据来源**；
> 真实实验辨识是 G5.4，尚未开始。
