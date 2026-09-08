# Phase A2 — Residual-guided Targeted Sensitivity（结果报告）

日期：2026-09-08　|　前置：平台 v0.4 冻结 + Atlas A1 冻结（含 2026-09-08 三项方法学修订：
bias/σ 精确恒等式、P1 降级为 dataset-associated pattern、|dI/dt| 数值定义锁死）
代码：`analysis/targeted_sensitivity/`（common / simulate / build_tables / plot_a2）
输出：`outputs/analysis/targeted_sensitivity/`（4 CSV + Fig A2-1…A2-4 + cache + validation json）

**本阶段零 fitting / 零 optimization / 零参数修正；`battery_sim/` 零改动（只读复用其
已验证的 perturbation machinery 与 baseline replay 管线）。**

---

## 0. 定义（与任务书一致，已锁定）

- 扰动方向向量（中心差分，δ = 0.20）：

  `S_p(t) = [ V(t, p(1+δ)) − V(t, p(1−δ)) ] / (2δ)`，单位 **mV per unit fractional
  parameter change**（≈ 每 100% 相对参数变化的电压响应）。
  正负两支各解一次 SPMe open-loop replay，评估在与冻结平台完全相同的 time-aligned 网格上。

- 残差 `e(t) = V_sim(t) − V_exp(t)`（mV），直接取自平台落盘 `*_time_aligned.csv`；
  条件分箱沿用 A1 规则（run 级边缘）：high-|I| = 第 3 三分位、high-|dI/dt| = >90 分位、
  late-progress = elapsed_fraction ≥ 0.8。**CC run 的 transient 条件量仍是数值噪声切片**
  （A1 既有结论），其 high-transition 列不携带瞬态物理。

- 指标：
  - `response_rms_mV` = √mean(S_p²)　（参数能多大程度移动模型输出）
  - `cosine_alignment` = (e·S_p)/(‖e‖‖S_p‖)　（**原始向量**，混合"均值对齐 + 形状对齐"）
  - `projection_fraction` = ‖Proj_{S_p} e‖²/‖e‖² = cos²θ（单方向 span 投影；
    **local linear diagnostic，NOT fitted variance explained**）
  - `affine_r2`（附加列）= 允许自由截距的 e~a+b·S_p 拟合 R²——**剥离均值平移后的
    形状解释力**，用于区分"偏置对齐"与"形状对齐"
  - `response_bias_mV` / `centered_response_rms_mV` = mean(S_p) / std(S_p)
    （偏置校正型 vs 时变响应型的分类依据）
  - `high_current / high_transition / late_progress_response_ratio` =
    RMS(S_p|条件)/RMS(S_p|全体)（响应集中位置）

- **解释规则（冻结）**：单一大响应 ≠ 根因；一个纯平移型响应（如 kappa_e 在 CC 下
  centered≈0）与任何常偏置残差都"天然对齐"，**均值对齐不构成证据**。只有
  高 response + 高**形状**证据（affine_r2 或带符号形状一致）+ 物理方向合理，才列为
  **candidate explanatory direction**；仍不得称为 identified parameter。

---

## 1. 代表性 run 与执行验证

| run | 选择理由 |
|---|---|
| chen2020/02/C0p5（=legacy "C2"=C/2） | A/exact；bias 93.5 mV + 末段抬升（P4 主例） |
| chen2020/02/C1p5 | A/exact；内部反例（末段反而最低，中段隆起） |
| calce_cs2/33/C0p5 | B/surrogate；CC；bias_fraction 0.78 |
| calce_20r/2/DST_50SOC | B；dynamic；Bias 134 mV |
| calce_20r/2/DST_80SOC | B；dynamic；Bias 263 mV（初始状态对照） |
| calce_a123/007/DST | B；dynamic；动态成分主导（0.67） |
| calce_a123/008/DST | **追加**：007 vs 008 残差形状显著不同（fraction-grid 相关 DST 0.44 / FUDS 0.46 / US06 0.51 < 0.5 阈值），且 008 DST 动态成分最大（0.68） |

第一轮参数（已验证 machinery，keys 见 `configs/sensitivity.yaml`）：
`Dsn Dsp j0n j0p De kappa_e Rn Rp brug_e`；未动 OCP / stoichiometry / 活物质占比。

**执行验证（`simulation_validation.json`）**：每 run 重解一次无扰动基线并与冻结平台
落盘 V_sim 逐点比较——7 run 的 max|ΔV| 全部 ≤ 3.2e-11 mV（机器精度级），证明扰动
replay 与平台 baseline 共享完全一致的 solver/参数管线；共 126 个扰动 case，wall 189 s。
个别 case 的 perturbed 解提前触发截止事件（coverage<1）：仅出现在 Chen2020 1p5C
（Dsn 0.944 / Rn 0.909 / 其余 ≥0.95），指标在公共支撑段上计算，已在 CSV `coverage_fraction`
列显式记录。

---

## 2. 总览读数（Fig A2-1…A2-3）

要点（完整数字见 `sensitivity_run_parameter_summary.csv`）：

1. **响应量级（A2-1）**：CC 短窗口上 S_p 可达 46–246 mV/unit（Rp/brug_e/Dsp/De），
   动态窗口 12–27 mV/unit（Rn/j0n 最大）。**响应大 ≠ 方向对**（见 1p5C）。
2. **对齐（A2-2，raw cos）**：所有 run 都存在 |cos|>0.7 的参数——但其中很大一部分
   是**均值对齐**（偏置主导残差 vs 平移型响应），不构成形状证据（A2-4 的 1p5C/CS2
   面板里"平线投影"即此现象的直观呈现）。
3. **投影（A2-3）**：fproj = cos²，从 0.006 到 0.95。**必须用 affine_r2 区分**：
   - 偏置方向候选（affine_r2 低、fproj 主要来自均值）：CS2 的 brug_e/kappa_e/De/j0p、
     Chen C2 的 j0n/Dsp/De/kappa_e/brug_e/Rp、20R 的 Rp/Dsp。
   - **形状方向候选**（affine_r2 高）：见 §3/§4。

---

## 3. 逐 pattern 诊断（五段式）

### 3.1 Chen2020 C2（A/exact，CC；RMSE 123.9 / Bias 93.5 / σ 81.3）

- **Observed residual**：整体正偏 + 末段 80–100% 抬升（P4 主例），high-transition
  ratio 2.02（截止前电流恒定、抬升集中在末段陡峭区）。
- **Candidate directions**：**Rn**（cos −0.976，fproj 0.953，**affine_r2 0.916**，
  late ratio 1.59）与 **Dsn**（cos +0.934，fproj 0.872，**affine_r2 0.937**，
  transition 2.20 / late 1.76）。负号方向含义：残差 e>0 需要 V_sim 上移，对应
  Rn 减小 / Dsn 增大（两者都降低负极极化）。残差的末段抬升形状被这两个方向
  高保真复现——**负极动力学/固态输运家族是 exact 基线 late-rise 的候选解释方向**。
- **Inconsistent directions**：brug_e/Rp/Dsp/De/kappa_e/j0n——响应大（10–83）但
  affine_r2 ≤0.45 且形状平（纯偏置型），解释不了末段结构。
- **Remaining unexplained**：σ 的前半段小波动（affine 残差 ~8%）。
- **Next hypothesis**：负极 single-particle 输运/动力学在陡峭 OCP 区的放大；与 P4 的
  "OCP 陡峭区读数放大"假设自洽。A2b 侧仍需检验 OCP/stoich 窗口能否同样复现该形状。

### 3.2 Chen2020 1p5C（A/exact 反例；RMSE 48.0 / 中段隆起）

- **Observed residual**：中段 ~0.2–0.5h 处 80 mV 隆起 + 末段下探（late ratio 0.65，
  与所有其他 run 相反）。
- **Candidate directions**：**无**。全部 9 参数 affine_r2 ≤ 0.57 且 cos 低
  （Rn 仅 −0.36）；j0n/kappa_e 投影为平线（只对齐均值）。
- **Inconsistent directions**：brug_e（响应 246 mV/unit，最大！cos −0.71 仅均值对齐，
  affine 0.26）、Rp（响应 226，affine 0.47 但形状不符）——**"最敏感的参数恰恰
  解释不了残差"**，是本阶段最有价值的单点证据。
- **Remaining unexplained**：几乎全部 centered 结构（隆起）。
- **Next hypothesis**：高倍率下中段隆起来自 9 参数 block 之外的机制——OCP 形状/
  stoichiometry 端点/容量平衡（A2b），或未建模机制。这把 P4 反例从"读数符号翻转"
  升级为"当前 block 张成空间不足"的直接证据。

### 3.3 CS2 33 0p5C（B/CC；RMSE 200.4 / Bias 176.6 / σ 94.6）

- **Observed residual**：常偏置 + 末段抬升（late ratio 1.63）。
- **Candidate directions（偏置型）**：brug_e（响应 49.8，纯平移，cos −0.88，
  fproj 0.78）、kappa_e/De/j0p/j0n/Rn/Rp 同为平移型候选——但**方向家族退化**：
  任何纯平移都能对齐常偏置，偏置不能辨识参数（kappa_e centered=0.002 即极端例）。
- **Candidate directions（形状型）**：**无 ≥0.5**；最高 j0p affine 0.44。
- **Remaining unexplained**：σ=94.6 mV 的 centered 结构（含末段抬升）基本未被
  9 参数 block 解释。
- **Next hypothesis**：B 级 surrogate（Ramadass2004）的 OCP/stoich 窗口失配 +
  容量平衡——直接进入 **A2b thermodynamic/stoichiometric sensitivity** 的首要对象。

### 3.4 20R DST 50SOC / 80SOC（B/dynamic；Bias 134 / 263 mV）

- **Observed residual**：偏置主导 + 电流跳变处尖峰；high-current ratio 1.26/1.12。
- **Candidate directions（形状型，中等）**：**j0n / Rn / kappa_e / j0p 家族**
  （affine 0.45–0.51（DST50）/ 0.33–0.39（DST80），high-current ratio 1.5–1.6、
  high-transition 1.4–1.5，与残差自身的负荷条件化一致）；brug_e（affine 0.42/0.33）。
  两窗口家族一致 → pattern 对初始状态不敏感（形状层面）。
- **Inconsistent directions**：Rp/Dsp（响应 17–23，纯偏置型，affine ≤0.32）；
  Dsn（响应 0.6，可忽略）。
- **Remaining unexplained**：偏置主体（Bias 134/263 mV）只被平移型方向"吸收"，
  无形状辨识力——与 P5 的初始状态映射混杂一致。
- **Next hypothesis**：动态 centered 成分 ↔ 动力学+电解液输运家族；偏置主体 →
  A2b（stoich/OCP/初始状态映射），由 P5 的 initial-SOC 扫描承接。

### 3.5 A123 007 & 008 DST（B/dynamic LFP；动态成分主导 0.67/0.68）

- **Observed residual**：σ≫Bias；high-current ratio 1.35/1.46、transition 1.24/1.45
  （P2/P3 的 LFP 主例）。
- **Candidate directions（两 cell 家族一致，affine_r2 括号内 007/008）**：
  - **kappa_e**（cos +0.82/+0.92；fproj 0.66/0.85；**affine 0.56/0.81**；
    transition ratio 1.59/1.62）
  - **j0n**（响应 22.2；cos +0.78/+0.88；affine 0.46/0.67）
  - **brug_e**（cos −0.77/−0.83；affine 0.39/0.54）
  - **Rn**（响应 27.1 最大；cos −0.73/−0.81；affine 0.32/0.49）
  这是任务书"理想结局"的实现：**A123 瞬态残差与 electrolyte-transport/kinetic
  方向族高度同形**。注意 kappa_e 在动态工况才携带时变形状（CC 下 centered≈0.001），
  电解液欧姆/浓度极化只在变化的电流下"显形"。
- **Inconsistent directions**：Dsp/Rp/De（响应小且形状无关，affine ≤0.05）；
  j0p 响应很小（0.56）虽 cos 高——响应量级不足以解释 200 mV 级残差。
- **Remaining unexplained**：约 20–45% centered 方差（1−affine），以及与 007/008
  差异对应的 cell 个体成分（两 cell affine 差 0.1–0.25）。
- **Next hypothesis**：输运/动力学 block 是 A123 失效主因的方向成立 → 下一步
  **不是 fitting**，而是先做 direction-family 内的可辨识性分析（见 §5 结果三）。

---

## 4. 跨 run 综合

1. **偏置不可辨识性（警示）**：所有 bias 主导 run 的偏置都能被某个平移型响应
   "对齐"（fproj 0.5–0.95），但这是**方向退化**：常值偏置方向与参数一一对应关系
   不存在。偏置问题的出路在 A2b（OCP/stoich/容量平衡/初始状态），不在 9 参数 block。
2. **形状证据分层**（affine_r2 为准）：
   - 强：Chen C2 ← {Rn 0.92, Dsn 0.94}（late/transition 集中）
   - 强：A123 ← {kappa_e 0.56/0.81, j0n 0.46/0.67, brug_e 0.39/0.54, Rn 0.32/0.49}
     （load/transition 集中）
   - 中：20R ← {j0n/Rn/kappa_e/j0p 0.33–0.51}（load/transition 集中）
   - 无：CS2 centered（≤0.44）、Chen 1p5C 隆起（≤0.57 且形状不符）
3. **非可辨识性预警（结果三的部分实现）**：同族参数响应形状近似互为镜像/平移——
   j0n vs Rn vs kappa_e vs brug_e 在 20R/A123 上 affine 值接近、符号相反
   （提高 j0p/j0n/kappa_e 与减小 Rn/brug_e 对电压的影响近乎共线）。
   **在任何 calibration 之前必须先做 sensitivity-vector correlation / SVD-Fisher
   可辨识性分析**，否则 fitting 会退化到参数组合的方向上。

## 5. 三分支判定（对应任务书预设）

- **分支一（A123 ↔ transport/kinetic 对齐）**：成立 → 下一步
  **identifiability（direction-family SVD / Fisher 相关）**，对象为
  {j0n, Rn, kappa_e, brug_e} ± Dsn 家族。
- **分支二（exact/CS2 bias 与 1p5C 隆起不被 9 参数解释）**：成立 → 下一步
  **A2b thermodynamic/stoichiometric/capacity sensitivity**
  （OCP 形状缩放/平移、stoichiometry 端点、initial-SOC 映射、容量/锂库存），
  首要对象：CS2 centered 结构、Chen 1p5C 隆起、20R 偏置主体。
- **分支三（同族方向强共线）**：部分成立（§4.3）→ 在分支一之前先做可辨识性。

**A2 停止条件已到**：9 参数 × 7 代表 run 全部完成；不新增参数、不 fitting。
按任务书，下一步顺序建议：**identifiability（分支一/三）与 A2b（分支二）并行设计，
由用户批准后启动。**

## 6. 产物与复现

```text
outputs/analysis/targeted_sensitivity/
  sensitivity_long.csv                  # 82,683 行，time-resolved S_p(t)+e(t)
  sensitivity_run_parameter_summary.csv # 63 行 = 7 run × 9 参数全指标
  residual_alignment_matrix.csv         # 行=参数，列=run × {cos, proj, rms}
  conditioned_response.csv              # 70 行：63 response + 7 residual 参照
  simulation_validation.json            # 基线镜像验证（≤3.2e-11 mV）
  cache/*.npz                           # 133 个解缓存（复用不重解）
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
```

边界重申：`battery_sim/` 本阶段 diff 为零；A1 修订仅触及 `analysis/residual_atlas.py`
定义注释 + 退化步守卫（18 run 全过、CSV 逐字节不变）与 `docs/cross_dataset_residual_analysis_v01.md`。
