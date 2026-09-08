# Cross-dataset Residual Analysis v0.1 — Phase A1 结果

日期：2026-09-08　|　平台状态：**v0.4 冻结**（`docs/platform_v04_freeze_manifest.md`）
数据源：`outputs/analysis/residual_atlas/`（residual_long.csv 26,950 行 × 18 runs；
run_summary / decomposition / transient_conditioned / current_load_conditioned / progress_error
+ Fig A1–A5）

**本阶段只建立 residual 结构与机制假设，禁止下物理结论**（任务书 Step A9/A10）。

---

## 0. 输入与定义（固定）

- 每个 run = SPMe baseline replay（open-loop I(t)，时间对齐），残差
  `e(t) = V_sim(t) − V_exp(t)`，取自平台落盘 `*_time_aligned.csv`，电流轨迹由
  adapter canonical 窗口插值到公共时间轴。
- 分解（**精确恒等式，非近似**）：定义 centered residual RMS
  σ_e = √( mean( (e − mean(e))² ) )，则 `RMSE² = Bias² + σ_e²`；
  `bias_fraction = Bias²/RMSE²`；`dynamic_residual_component = σ_e²/RMSE²`；
  且 `bias_fraction + dynamic_residual_component = 1` **精确成立**。
  这样 A123 的 bias_fraction = 0.30–0.41 才能严格解读为
  "误差能量更多来自时变 (centered) residual"。
- dI/dt 数值定义（**锁死**，写进 atlas definitions）：共享单调时间轴上的
  forward finite difference `dI_dt_i = (I_i − I_{i−1}) / (t_i − t_{i−1})`
  （首点 pad）；I(t) 为 adapter canonical 电流在共享网格的线性插值
  （网格已审计、严格递增）。异常采样规则：任一 dt ≤ 1e-6 s 或比值非有限
  → 该点判 transient-indeterminate，**审计报错**（raise），绝不静默置零或剔除
  （v0.1 全部 18 run 网格通过，零触发）。`dynamicity_index_norm =
  mean(|dI/dt|)/rms(I)`；transient 分箱 = 每 run 的 |dI/dt| 分位
  （<50%、50–90%、>90%）；current-load 分箱 = |I| 三分位。
- progress = elapsed/protocol progress（**不是 SOC**）；CC 另有 q_fraction。
- 覆盖：Chen2020 cell02×4 rate（A/exact, CC）、CS2 33×0p5C + 35×1C（B, CC）、
  20R cell2×6 窗口（B, DST/FUDS/US06）、A123 007/008×3（B, DST/FUDS/US06）。
- 注意：CC run 的 transient 分箱是**数值噪声切片**（真实 |dI/dt|≈0），
  其 medium/high bin 不携带瞬态物理含义，下文凡涉及瞬态仅引用动态 run。

---

## 1. Pattern P1 — 双失效模式并存（dataset-associated pattern，非参数等级因果）

**Pattern observed**
`bias_fraction` 把 18 个 run 分成清晰的两簇：

```text
系统偏置主导（bias_fraction 0.75–0.92）：
  20R 全部 6 窗口（0.75–0.92）、CS2（0.78 / 0.86）、
  Chen2020 CC 的 3/4（0.57–0.81）
动态成分主导（dynamic_residual_component 0.59–0.70）：
  A123 全部 6 窗口（bias_fraction 仅 0.30–0.41）
```

**Evidence**：`run_summary.csv` / Fig A1、Fig A2。20R 的 Bias 达 134–274 mV
而 σ_e 仅 67–87 mV；A123 相反（σ_e 135–189 mV > Bias 110–132 mV）。

**Caveat（绑定，勿误读）—— P1 只允许称作 dataset-associated pattern**
P1 只描述"哪些 run 的误差能量以何种形式集中"，不识别原因。当前
parameter_match / chemistry / protocol / dataset / initialization 高度共线：
只有一个 A 级 exact 数据集（Chen2020），**无法单独估计 parameter-match
effect**；P6 恰好证明 exact model 同样 bias-dominated。因此**禁止**写作
"B-grade surrogate 导致 dynamic error / bias error" 或任何同类因果句；
只允许写作："P1 与 {20R/CS2 偏置主导、A123 动态成分主导} 的 dataset 归属
相关联（associated），原因待 A2/A3 判定"。

**Possible physical explanation（假设，未证明）**
- 偏置主导 → OCP 形状 / stoichiometry 窗口 / 容量平衡 / 初始状态映射的
  系统性失配（surrogate 或模型结构级）。
- A123 的 centered 主导与 LFP 平台有关：平坦 OCP 在低极化区"压缩"了
  SOC 类误差的电压读数，暴露出来的反而是动力学/输运极化误差。

**Not yet proven**：哪一类参数负责；A123 的低 bias_fraction 是否真由
LFP 平台造成。

**What would falsify it**：若对 A123 施加 OCP/stoichiometry 扰动后
bias_fraction 仍不变（说明其偏置不由 OCP 类参数控制），或对 20R 的
OCP 窗口扰动无法按比例移动 Bias（说明 20R 的偏置另有来源）。

**Next test**：targeted sensitivity——对 {OCP 形状/化学计量窗口、初始
SOC、容量平衡} vs {R0、j0、D_s、电解液输运} 两组参数分别做 OAT，
看 `bias_fraction` 与 `dynamic_residual_component` 各自的响应。

---

## 2. Pattern P2 — |residual| 随电流负荷单调上升（动态工况）

**Pattern observed**：|I| 三分位 RMSE（low→medium→high）：

```text
20R:  110→132→193 (DST50) … 258→269→330 (US0680)   ratio 1.3–1.8
A123:  80→163→269 (007DST) … 100→143→351 (008FUDS) ratio 2.7–3.9
CC (Chen2020): ratio ≈ 1.0–1.3（恒流下无梯度，符合预期）
```

**Evidence**：`current_load_conditioned.csv` / Fig A3。

**Possible physical explanation**：高负荷下固体扩散 / 电解液输运 /
动力学 / 欧姆极化的失配被放大。A123 梯度比 20R 更陡，与 P1 的
"LFP 平台掩盖低负荷误差"假设自洽。

**Not yet proven**：哪个输运/动力学参数；欧姆与扩散的贡献比。

**What would falsify it**：若高 |I| bin 的超额误差被一个纯欧姆项
（R0 缩放）完全复现，则扩散/电解液假设降级；反之若 R0 扰动无法
复现梯度，扩散/动力学嫌疑上升。

**Next test**：OAT {R0, j0} vs {D_s, 电解液 θ}，比较 high/low 梯度的
复现能力。

---

## 3. Pattern P3 — 高电流转变率处误差一致放大（动态工况）

**Pattern observed**：|dI/dt| 分位（low→high）RMSE：

```text
20R:  137→173 (DST50) … 278→334 (US0680)      +9%…+36%
A123: 200→247 (007DST) … 162→296 (007FUDS)    +23%…+83%
（且 A123 high bin 的 Bias 反而更低——超额误差是 centered 成分）
```

**Evidence**：`transient_conditioned.csv` / Fig A4。

**Possible physical explanation**：动力学（j0/交换电流密度）、欧姆、
电解液浓度极化的瞬态响应失配——恰是脉冲响应类误差特征。

**Not yet proven**：时间常数尺度（秒级欧姆 vs 十秒级扩散）。

**What would falsify it**：若把 high-transition 超额误差用一阶 RC
（R0+C）完全拟合，则电解液/固相扩散瞬态假设降级。

**Next test**：residual 脉冲响应分析（对单次大 |dI/dt| 事件叠图）+
{j0, R0} targeted sensitivity。

---

## 4. Pattern P4 — 末段（progress 80–100%）残差系统性抬升

**Pattern observed**：mean residual（0–20% → 80–100%）：

```text
20R:   104→210 (DST50) … 174→372 (US0680)
A123:   56→257 (007DST) … 74→270 (008US06)
CS2:   109→279、178→370
Chen2020: 19.6→141 (C0p1)、18.9→180 (C0p5)、30.8→103 (C1)
反例：Chen2020 C1p5 末段反而最低（56→13.5 mV）
```

**Evidence**：`progress_error.csv` / Fig A5。

**Possible physical explanation**：放电末段进入 OCP 陡峭区 /
低 SOC 化学计量区，OCP 形状与 stoichiometry 窗口失配被放大；
也可能叠加容量平衡（累积荷电状态偏移）。高倍率反例（C1p5）
提示陡峭 OCP 区间内电压对参数偏差的读数符号可能翻转，
需谨慎。

**Not yet proven**：OCP 失配 vs 容量平衡/累积漂移的占比。

**What would falsify it**：若以每 run 自身末段起点重新锚定
（扣除累积偏移）后末段超额误差消失，则"累积容量平衡漂移"
成分为主；若仍存在，则 OCP 形状局部失配为主。

**Next test**：扣除 per-run Bias 后重算 progress 曲线（零成本，
Phase A2 可做）+ OCP/stoichiometry 局部 OAT。

---

## 5. Pattern P5 — 20R 的 50%→80% SOC：Bias 近似翻倍

**Pattern observed**：同协议下 80SOC 的 Bias≈2× 50SOC
（134→263、135→260、149→274 mV），两者 bias_fraction 均 ≥0.75。

**Evidence**：`run_summary.csv`。

**Possible physical explanation**：初始状态（文件名 SOC 标签）→
Chen2020 surrogate stoichiometry 的映射失配随初始 SOC 系统性放大；
**初始状态映射是显式混杂因子**（v0.3 冻结令：不得解读为
"模型在高 SOC 泛化更差"）。

**What would falsify it**：若对 50/80 两窗口分别做 initial-SOC 微扰
OAT，Bias 的响应无法用单一 stoichiometry 平移解释，则映射失配
假设不足。

**Next test**：initial-SOC 一维扫描 × {50,80}SOC，看 Bias(ΔSOC)
是否平行移动。

---

## 6. Pattern P6 — A 级 exact 参数化同样偏置主导

**Pattern observed**：Chen2020（A/exact，CC）RMSE 48–124 mV 中
bias_fraction 0.56–0.81（C1 达 0.81），Bias 36–93 mV——**偏置主导不是
surrogate 特有**。

**Possible physical explanation**：模型结构误差 / 未建模机制
（如电解液、热、老化）或"exact 对文献 cell 而非对 THIS cell"的
残留失配。这直接支撑 Phase A 的核心问题：残差须按
(P_match, chemistry, protocol, I, progress) 联合解释，
单一"参数等级"维度不足。

**Next test**：Chen2020 cell03/04 复算 bias_fraction，确认该 pattern
跨 cell 稳定。

---

## 7. 汇总：机制假设 → 下一步 targeted sensitivity 映射

```text
假设                          关联 pattern      待扰参数（Phase A2 候选）
OCP/stoichiometry 窗口失配     P1 P4 P5         OCP 缩放/平移、电极厚
初始状态映射误差               P1 P5            initial SOC（×50/80）
固体扩散 / 电解液输运          P2 P3            D_s、电解液 θ、Bruggeman
动力学 / 欧姆                  P3 P2            j0、R0
容量平衡/累积漂移              P4               容量、正负极 Li 库存
```

注：上表是"假设→扰动方向"的映射清单，不是因果结论；P1 只作为
dataset-associated pattern 输入（见 §1 Caveat），各假设需由 A2 的方向
一致性检验才能升级为 candidate explanatory direction。

## 8. 局限（v0.1）

1. Chen2020 只含 cell02；CS2 每 cell 单一 rate；结论外推需扩 cell。
2. CC run 的 transient 分箱是数值噪声切片，仅动态 run 支持瞬态结论。
3. dI/dt 为共享网格 forward finite difference（数值定义与异常规则锁死，
   见 §0）；网格间距 ~1–4 s，短于最小网格间距的瞬态不可见（分辨率限制，
   非算法缺陷）。
4. 全部为 SPMe；未检验 DFN 是否改变 pattern 归属。
5. bias/σ 分解对初始状态锚定方式敏感（CC 从 rest OCV 起算）。

## 9. 停止边界（已执行）

本阶段零 fitting / 零 optimization / 零 ML / 零参数修正；
`battery_sim/` 科学逻辑零改动（analysis 只读平台输出）。
下一步（Phase A2，待批准）：由上表驱动的 targeted sensitivity。
