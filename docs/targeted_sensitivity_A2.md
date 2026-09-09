# Phase A2 — Residual-guided Targeted Sensitivity（结果报告）

日期：2026-09-08　|　版本：6-run panel（原 7-run 版已归档至
`outputs/analysis/targeted_sensitivity/_archive_7run/`，本次为解释层修订版）
前置：平台 v0.4 冻结 + Atlas A1 冻结
代码：`analysis/targeted_sensitivity/`（common / simulate / build_tables / plot_a2 / interpret_a2）
输出：`outputs/analysis/targeted_sensitivity/`

**本阶段零 fitting / 零 optimization / 零参数修正；`battery_sim/` 零改动（只读复用其
已验证的 perturbation machinery 与 baseline replay 管线）。本解释层修订版未运行任何新的
PyBaMM 算例——所有数字均来自已落盘的 CSV 的重新整理与门控。**

---

## 0. 措辞与推断边界（本次修订，已锁定）

本阶段的推断力被**显式限制在 ±20% 单参数局部扰动区间内**。以下写法被禁止，不得出现在
任何正式产物中：

| 禁止写法 | 原因 |
|---|---|
| “the residual is not determined by these parameter values” | 超出检验范围（只检验了 ±20% 单参数，未检验大幅/多参数/其它参数块） |
| “therefore the error is model-structure error” | 把“本 block 不足”偷换成“结构误差”的定位结论 |
| “identified parameter” / “identified <name> error” | 本阶段不做辨识 |
| “root cause” | 同上 |
| “fitted variance explained” | projection_fraction 是局部线性投影，不是拟合方差解释率 |

对应的**唯一允许写法**（在无候选方向时使用，逐字固定）：

> **Within the local ±20% single-parameter perturbation range,
> the tested kinetic/transport parameter block is insufficient
> to explain the observed residual magnitude.**

对 Chen2020 C/2 的 Rn，只允许使用：

> **strongly shape-aligned, amplitude-insufficient candidate model direction**

禁止写成 “identified particle-radius error” 或 “root cause”。

---

## 1. 两个指标族：用途不同，必须并列报告

这是本次修订的核心方法学更正。

| | **RAW 族** | **CENTERED 族** |
|---|---|---|
| 量 | `cosine_alignment`、`projection_fraction` | `affine_r2`（= `centred_cosine²`） |
| 向量 | **未去均值**的 e(t)、S_p(t) | 双端去均值后 |
| 是否含直流分量 | **含** | 已投影掉 |
| 定义 | `cos = (e·S)/(‖e‖‖S‖)`；`proj = cos²` | `e ≈ a + b·S` 允许自由截距的 R² |
| 用途 | **总体同向性**（偏置 + 形状一起） | **仅形状一致性** |
| 失效模式 | 偏置主导的 run 里被共同 DC 抬高 | 不携带幅度信息 |

**明确记录**：`projection_fraction = cos²` 使用的是**未经去均值**的向量。因此对于
bias-dominated run，任何近似常值的响应都会与近似常值的残差自动“对齐”，proj 会被共同
直流分量抬高。它**不是**形状一致性的证据。

**二者恒等关系已数值审计**：`max|affine_r2 − centred_cosine²| = 2.4e-15`（54/54 格），
即 `affine_r2` 与去均值 cos² 是同一量的两种算法，不是两个独立指标。

并列产物：`outputs/analysis/targeted_sensitivity/centred_shape_matrix.csv`
（每 run × 参数同时给出 `raw_cos / raw_proj / centred_cos / centred_r2 / cover20`），
以及 `candidate_directions.csv`（逐格两族指标 + 分类）。

---

## 2. 定义（未变更，沿用已锁定口径）

- 扰动方向向量（中心差分，δ = 0.20）：

  `S_p(t) = [ V(t, p(1+δ)) − V(t, p(1−δ)) ] / (2δ)`，单位 **mV per unit fractional
  parameter change**。正负两支各解一次 SPMe open-loop replay，评估在与冻结平台完全相同的
  time-aligned 网格上。

- 残差 `e(t) = V_sim(t) − V_exp(t)`（mV），直接取自平台落盘 `*_time_aligned.csv`；
  条件分箱沿用 A1 规则。**CC run 的 transient 条件量仍是数值噪声切片**（A1 既有结论）。

- `coverage_20pct = 0.20 × response_rms_mV / residual_RMSE_mV`
  —— ±20% 参数移动能在残差 RMS 上覆盖的比例（“杠杆大小”，与符号无关）。

---

## 3. 代表性 run 与执行验证

| run | grade | 选择理由 |
|---|---|---|
| `chen2020/02/C0p5`（legacy “C2” = C/2） | A | exact；Bias 93.5 mV + 末段抬升 |
| `chen2020/02/C1p5` | A | exact；内部反例（末段最低、中段隆起） |
| `calce_cs2/33/C0p5` | B | surrogate；CC；bias²/RMSE² = 0.78 |
| `calce_20r/2/DST_50SOC` | B | surrogate；dynamic；Bias 134 mV |
| `calce_20r/2/DST_80SOC` | B | surrogate；dynamic；Bias 263 mV（初始状态对照） |
| `calce_a123/008/FUDS` | B | **A123 代表 run**，见下 |

**A123 代表 run 的选择依据**（从 A1 Residual Atlas 的六个 A123 动态窗中选定，非阈值调参）：
`calce_a123/008/FUDS` 同时是 ——

- `dynamic_residual_component` **最大**（0.696，六窗中最高）；
- `residual_std` **最大**（189.13 mV，六窗中最高）；

两个判据同向，且 `bias_fraction` 仅 0.304（误差以动态部分为主，不是偏置主导）。

参数块（9 个，未增未减）：`Dsn Dsp j0n j0p De kappa_e Rn Rp brug_e`。

**执行验证（`simulation_validation.json`）**：每 run 重解一次无扰动基线并与冻结平台落盘
V_sim 逐点比较，max|ΔV| 全部 ≤ 3.1e-11 mV（机器精度级），证明扰动 replay 与平台 baseline
共享同一 solver/参数管线。**6 run × 9 参数 = 54 格，108 个扰动算例**。
覆盖度：45/54 格 `coverage_fraction = 1.0`；**9 格为 0.909–0.993，全部出现在
Chen2020 1.5C**（高倍率下个别扰动解略早终止），指标只在公共支撑段上计算，`coverage_fraction`
列显式记录。

---

## 4. 门限（含披露）

**预先注册**（看结果之前固定）：

- `ALIGN_GATE`  |cos| ≥ 0.70
- `PROJ_GATE`   projection_fraction ≥ 0.49（= 0.70²）
- `MAG_GATE`    coverage_20pct ≥ 0.10

**事后追加（明确披露，非预先注册）**：首次判读发现 raw cos/proj 被 DC 分量抬高后，追加

- `SHAPE_GATE`  centred R²（= affine_r2）≥ 0.50
- `AMP_GATE`    coverage_20pct ≥ 1.00（±20% 移动即可跨越整个残差 RMS，才算幅度充分）

追加门限是**收紧**而非放宽：它只把原本及格的方向降级，不会把任何方向升级为候选。
因此追加门限不改变“哪些方向是候选”的方向性，只提高了准入门槛。

分类结果：

| 分类 | 含义 |
|---|---|
| `strongly_shape_aligned_amplitude_insufficient_candidate_model_direction` | 三预注册门 + 形状门全过，但 cover20 < 1.0 |
| `candidate_model_direction` | 上述全过且 cover20 ≥ 1.0（本次无） |
| `shape_aligned_magnitude_short` | 形状一致但杠杆低于 0.10 |
| `magnitude_viable_shape_unconfirmed` | 杠杆够但形状未证实 |
| `weak_or_inconsistent` | \|cos\| < 0.30 |

---

## 5. 结果

### 5.1 逐 run 分类

| run | RMSE / Bias / σ (mV) | bias²/RMSE² | candidate model direction | shape-aligned, magnitude short | magnitude-viable, shape-unconfirmed | weak / inconsistent |
|---|---|---|---|---|---|---|
| chen2020/02/C0p5 | 123.9 / 93.5 / 81.3 | 0.57 | **Rn** | Dsn, j0p | — | — |
| chen2020/02/C1p5 | 48.0 / 36.0 / 31.8 | 0.56 | NONE | — | brug_e, j0n, kappa_e | Dsn |
| calce_cs2/33/C0p5 | 200.4 / 176.6 / 94.6 | 0.78 | NONE | — | — | — |
| calce_20r/2/DST_50SOC | 152.8 / 134.1 / 73.2 | 0.77 | NONE | Rn, j0p, Dsn | — | — |
| calce_20r/2/DST_80SOC | 275.6 / 263.4 / 81.0 | 0.91 | NONE | — | — | — |
| calce_a123/008/FUDS | 226.7 / 125.0 / 189.1 | 0.30 | NONE | j0n, brug_e, kappa_e, j0p | — | Dsn, Rp, Dsp |

### 5.2 CENTERED 形状指标矩阵（`affine_r2` = 去均值 cos²）

| 参数 | 20R DST50 | 20R DST80 | A123 008 FUDS | CS2 0.5C | Chen C/2 | Chen 1.5C |
|---|---|---|---|---|---|---|
| Dsn | **0.546** | 0.031 | 0.006 | 0.239 | **0.937** | 0.568 |
| j0p | **0.512** | 0.387 | **0.541** | 0.439 | **0.755** | 0.532 |
| kappa_e | 0.498 | 0.387 | **0.748** | 0.004 | 0.002 | 0.000 |
| Rn | **0.500** | 0.338 | 0.488 | 0.136 | **0.916** | 0.477 |
| j0n | 0.450 | 0.329 | **0.663** | 0.110 | 0.451 | 0.192 |
| brug_e | 0.418 | 0.325 | **0.582** | 0.033 | 0.011 | 0.263 |
| Rp | 0.098 | 0.324 | 0.013 | 0.216 | 0.018 | 0.467 |
| Dsp | 0.003 | 0.139 | 0.000 | 0.235 | 0.028 | 0.400 |
| De | 0.005 | 0.005 | 0.003 | 0.026 | 0.010 | 0.262 |

（加粗 = 过 SHAPE_GATE 0.50）

### 5.3 RAW projection fraction 矩阵（= cos²，**未去均值，DC 抬高**）

| 参数 | 20R DST50 | 20R DST80 | A123 008 FUDS | CS2 0.5C | Chen C/2 | Chen 1.5C |
|---|---|---|---|---|---|---|
| Rn | 0.626 | 0.480 | 0.636 | 0.732 | **0.953** | 0.129 |
| Rp | 0.781 | **0.933** | 0.045 | 0.651 | 0.488 | 0.414 |
| brug_e | 0.796 | 0.748 | 0.696 | 0.782 | 0.574 | 0.510 |
| j0n | 0.588 | 0.462 | 0.740 | 0.739 | 0.628 | 0.574 |
| j0p | 0.541 | 0.397 | 0.621 | 0.795 | 0.676 | 0.435 |
| kappa_e | 0.537 | 0.399 | 0.799 | 0.777 | 0.570 | 0.573 |
| Dsn | 0.670 | 0.288 | 0.047 | 0.605 | 0.872 | 0.006 |
| Dsp | 0.708 | **0.910** | 0.011 | 0.512 | 0.462 | 0.355 |
| De | 0.542 | 0.642 | 0.168 | 0.783 | 0.573 | 0.418 |

**对照读法**：Dsp 在 20R DST80 的 raw proj = 0.910（很高）但 centred R² = 0.139（很低）
→ 高 raw 值完全来自共同直流分量，**不构成形状证据**。同类例子：CS2 的 De（0.783 / 0.026）、
brug_e（0.782 / 0.033）、kappa_e（0.777 / 0.004）、j0p（0.795 / 0.439）；Chen 1.5C 的
kappa_e（0.573 / 0.000）、j0n（0.574 / 0.192）、brug_e（0.510 / 0.263）。
**Fig A2-3（projection heatmap）必须与 §5.2 的 centred 矩阵对照阅读。**

### 5.4 coverage_20pct（±20% 杠杆 / 残差 RMS）

| 参数 | 20R DST50 | 20R DST80 | A123 008 FUDS | CS2 0.5C | Chen C/2 | Chen 1.5C |
|---|---|---|---|---|---|---|
| brug_e | 0.016 | 0.009 | 0.001 | 0.050 | 0.075 | **1.022** |
| Rp | 0.023 | 0.017 | 0.004 | 0.005 | 0.134 | **0.942** |
| Rn | 0.023 | 0.013 | 0.025 | 0.002 | **0.120** | 0.747 |
| Dsp | 0.011 | 0.008 | 0.002 | 0.001 | 0.064 | 0.426 |
| Dsn | 0.001 | 0.000 | 0.006 | 0.000 | 0.037 | 0.389 |
| j0n | 0.023 | 0.013 | 0.021 | 0.002 | 0.064 | 0.207 |
| De | 0.005 | 0.003 | 0.001 | 0.005 | 0.024 | 0.381 |
| kappa_e | 0.006 | 0.003 | 0.001 | 0.009 | 0.017 | 0.132 |
| j0p | 0.004 | 0.002 | 0.001 | 0.002 | 0.013 | 0.129 |

四个 B-grade run 的**最大** cover20 分别只有 0.023 / 0.017 / 0.025 / 0.050。

---

## 6. 逐 run 判读

### 6.1 chen2020/02/C0p5（A / CC）

- **唯一的 candidate model direction：Rn**，读作
  **strongly shape-aligned, amplitude-insufficient candidate model direction**
  （raw cos −0.976，raw proj 0.953，**centred R² 0.916**，cover20 0.119）。
  形状与幅度两族指标同时为正，这在 54 格中是唯一的。
- 但 cover20 = 0.119：±20% 的 Rn 移动只覆盖残差 RMS 的约 12%。要覆盖 123.9 mV 的
  残差需要远超 ±20% 的移动，早已越出局部线性区间。**因此它是方向，不是充分解释。**
- Dsn 是**形状最佳者**（centred R² 0.937，高于 Rn 的 0.916），但 cover20 仅 0.037
  → 形状一致、幅度不足，列为 `shape_aligned_magnitude_short`。
- 禁止写成 “identified particle-radius error”。**符号读法**（按本阶段的问题口径，即
  “哪个方向能*产生*与观测残差同形的电压误差”）：cos(e, S_Rn) = −0.976 表示**减小 Rn**
  （负向分数变化）所产生的响应形状与观测残差同形；反过来，**增大 Rn** 是抵消该残差的
  方向。本阶段只陈述方向与形状，**不估计幅度，也不声称 Rn 的实际值有误**。
  同理 Dsn（cos +0.934）是“增大 Dsn 产生同形误差”的方向。

### 6.2 chen2020/02/C1p5（A / CC，内部反例）

- **无 candidate model direction。**
- `magnitude_viable_shape_unconfirmed`：brug_e（cover20 1.022，centred R² 0.263）、
  j0n（0.207 / 0.192）、kappa_e（0.132 / **0.000**）。这三个原本按预注册门限会被判为
  候选，加入形状门后全部降级——**它们的 raw 对齐基本只来自共同直流分量**。
- 一例值得记录的边界情形：Dsn 的 centred R² = 0.568（过形状门）但 raw cos 仅 +0.075
  → 形状相关而直流分量反向。按双轴门限它归入 `weak_or_inconsistent`，
  **记为 shape-correlated-but-DC-opposed，不作为方向**。
- 结论（按允许措辞）：Within the local ±20% single-parameter perturbation range,
  the tested kinetic/transport parameter block is insufficient to explain the
  observed residual magnitude. 本 run 有幅度杠杆（最高 cover20 1.022）但形状未证实。

### 6.3 calce_cs2/33/C0p5（B / CC，偏置主导）

- 无候选方向。centred 形状指标**最高仅 0.439**（j0p），全部 raw 高值都是 DC 抬高。
- 最大 cover20 = 0.050。
- 结论：Within the local ±20% single-parameter perturbation range, the tested
  kinetic/transport parameter block is insufficient to explain the observed
  residual magnitude.（见 §7 未测混杂因素）

### 6.4 calce_20r/2/DST_50SOC 与 DST_80SOC（B / dynamic）

- 两窗口均无候选方向。
- DST50 有 3 个 `shape_aligned_magnitude_short`：Rn（centred 0.500，临界过门）、
  j0p（0.512）、Dsn（0.546）——但三者 cover20 分别为 0.023 / 0.004 / 0.001。
- DST80 连形状门都不过（最高 centred R² 0.387），bias²/RMSE² = 0.91。
- 两窗口在形状层面的家族不完全一致（DST50 的 Dsn 0.546 vs DST80 的 0.031），
  与“偏置主体对初始状态敏感”一致，但**不构成任何参数的辨识结论**。
- 结论：Within the local ±20% single-parameter perturbation range, the tested
  kinetic/transport parameter block is insufficient to explain the observed
  residual magnitude.（见 §7 未测混杂因素）

### 6.5 calce_a123/008/FUDS（B / dynamic LFP，动态残差最大窗）

- 无候选方向。
- 形状最佳的三个方向：kappa_e（centred R² **0.748**，54 格中最高）、j0n（0.663）、
  brug_e（0.582）。但对应 cover20 为 **0.0007 / 0.021 / 0.001** ——
  **形状最像的方向杠杆几乎为零**（kappa_e 的 response rms 仅 0.78 mV/unit）。
  这是本次最清晰的“形状与幅度脱耦”实例：不能用高形状相关性推出“输运/动力学块是主因”。
- `weak_or_inconsistent`：Dsn（raw cos +0.216）、Rp（−0.213）、Dsp（+0.106）。
- 结论：Within the local ±20% single-parameter perturbation range, the tested
  kinetic/transport parameter block is insufficient to explain the observed
  residual magnitude.（见 §7 未测混杂因素）

---

## 7. B-grade（surrogate 参数集）run 的未测混杂因素

以下因素**本阶段未测试**，因此 §6.3–6.5 的“本 block 不足”不能被读作对这些 run 的
任何定位性结论。逐项列出（对每个 B-grade run 均适用）：

1. **OCP** —— 未扰动；B 级 run 使用 surrogate 参数集的 OCP，未做 OCP 形状/平移敏感性。
2. **stoichiometry window** —— 未扰动；stoich 端点直接决定容量轴与电压窗口。
3. **active-material inventory** —— 未扰动；决定容量尺度，与残差的容量轴成分直接耦合。
4. **initial-state mapping** —— 未扰动；A1 已标为 P5 混杂，对 DST 50/80 SOC 尤其相关。
5. **multi-parameter interaction** —— 本阶段只做单参数中心差分，未测任意交互项。
6. **nonlinear large perturbations** —— 只测 ±20% 局部线性响应；外推到大幅移动未验证。
7. **other resistance terms** —— 未测接触电阻、集流体、膜阻等 9 参数之外的阻抗项。

**推论边界**：在这 7 项未被测试之前，B-grade run 的残差只能表述为
“within the local ±20% single-parameter perturbation range, the tested
kinetic/transport parameter block is insufficient to explain the observed
residual magnitude”，不得升级为任何关于误差来源归属的陈述。

---

## 8. 跨 run 综合

1. **raw 与 centred 必须并列**：54 格中有 **14 格**呈现“raw proj ≥ 0.50 但
   centred R² < 0.15”，分布在 **6 个 run 中的 5 个**（唯一例外是 A123 008 FUDS，它
   本身 bias²/RMSE² 只有 0.30）。凡 bias²/RMSE² ≥ 0.56 的 run（6 个中 5 个），raw
   对齐都不可单独作为证据。**Fig A2-2 / A2-3 只能在与 §5.2 centred 矩阵对照后解读。**
2. **形状与幅度系统性脱耦**：过形状门（centred R² ≥ 0.50）的 **12 格**里，cover20
   中位数仅 **0.017**、最高 0.389（Chen 1.5C Dsn，但其 raw cos 仅 +0.075，属
   §6.2 记录的 DC-opposed 边界情形）；centred R² 全表最高的两格（Chen C/2 Dsn 0.937、
   Rn 0.916）的 cover20 只有 0.037 / 0.119；而 cover20 全表最高的三格
   （Chen 1.5C brug_e 1.022 / Rp 0.942 / Rn 0.747）的 centred R² 只有 0.263 / 0.467 /
   0.477。**“最敏感”与“最像”从不落在同一格。**
3. **唯一双族同时成立的方向**：同时通过 raw 门 + 形状门 + 最小杠杆门三者的，54 格中
   **只有 Chen2020 C/2 的 Rn 一格**（centred 0.916、cover20 0.119），且即便如此仍属
   amplitude-insufficient。
4. **同族方向近共线（可辨识性预警，不在本阶段执行）**：j0n / kappa_e / brug_e / Rn
   在多个 run 上 centred R² 数值接近、符号交错（如 CS2：j0n 0.110 / kappa_e 0.004 /
   brug_e 0.033 / Rn 0.136 且符号不一致；20R DST80：0.329 / 0.387 / 0.325 / 0.338）。
   **在任何 calibration 之前必须先做方向族内的可辨识性分析**；本阶段不执行。
5. **无 RMSE 阈值门**：本阶段未设、也不设“RMSE < 某值”的通过条件。

---

## 9. 停止条件与下一步（等待批准，本阶段不执行）

硬停止已到：6 runs × 9 parameters = 54 格全部完成，未新增参数、未进入
fitting / identifiability / SVD / OCP 敏感性 / 热力学敏感性 / calibration /
optimization / 新数据集 / H1-D0。

下一步候选（**均需人工批准后另行启动**）：

1. 对 §7 的 7 项混杂因素中的 OCP / stoichiometry window 做同样的 targeted sensitivity
   （沿用同一 ±20% machinery 与双族指标口径）；
2. 方向族内可辨识性分析（对应 §8.4）；
3. 多参数交互与非线性的有限探索（对应 §7.5 / §7.6）。

---

## 10. 产物与复现

```text
outputs/analysis/targeted_sensitivity/
  sensitivity_long.csv                  # 64,683 行，time-resolved S_p(t) + e(t)
  sensitivity_run_parameter_summary.csv # 54 行 = 6 run × 9 参数全指标
  residual_alignment_matrix.csv         # 宽表：raw cos / proj / rms
  centred_shape_matrix.csv              # 宽表：raw_cos / raw_proj / centred_cos
                                        #       / centred_r2 / cover20（本次新增）
  candidate_directions.csv              # 逐格两族指标 + 分类（本次修订）
  conditioned_response.csv              # 60 行：54 response + 6 residual 参照
  simulation_validation.json            # 基线镜像验证（≤3.1e-11 mV）
  interpret_report.txt                  # 7 项汇报全文（本次修订）
  interpret_gates.json                  # 门限 + 指标族定义 + 允许/禁止词汇
  _archive_7run/                        # 旧 7-run 版 4 CSV + validation（归档）
  cache/*.npz                           # 解缓存（复用不重解）
  fig_a2_1_response_rms_heatmap.png
  fig_a2_2_cosine_alignment_heatmap.png
  fig_a2_3_projection_fraction_heatmap.png
  fig_a2_4_residual_vs_top3_response.png
```

复现（WSL pybamm env）：

```bash
python analysis/targeted_sensitivity/simulate.py            # 解算（已缓存则跳过）
python analysis/targeted_sensitivity/build_tables.py        # 4 CSV
python analysis/targeted_sensitivity/plot_a2.py             # 4 图
python analysis/targeted_sensitivity/interpret_a2.py        # 解释层（零求解）
```

**图仍为 4 张，未增加。** Fig A2-3 的读法限制见 §5.3。

边界重申：`battery_sim/` 本阶段 diff 为零；本解释层修订版只改
`analysis/targeted_sensitivity/interpret_a2.py` 与 `docs/targeted_sensitivity_A2.md`，
未运行任何新仿真，未改动 `simulate.py` / `build_tables.py` / `plot_a2.py` 的数值口径。
