# Half-cell Pilot H1 — Phase H1-C：Parameter-Source Audit（SINTEF LFP-NMP-1 p-OCV）

**日期**：2026-09-08（H1-B 封板 commit `fab5c1d` 之后；HEAD 复核 = `fab5c1d` ✅）
**范围**：只做参数**审计**，不做参数**拟合**。唯一实验事实源 = 已冻结的 H1-B canonical replay + SINTEF `meta/metadata.csv`。
**硬禁止**：× PyBaMM forward simulation × least-squares/BO/MCMC × 调参凑容量 × 下载 GITT × 把 acfc66/ae94f3 写成 SINTEF measured × 修改 H0/H1-B 冻结产物。

---

## 1. 结论摘要（TL;DR）

- **反向枚举完成**：pybamm 26.8 半电池（positive working + Li counter）DFN 所需 key 全集 **51 个**（以 H0 跑通的 Jackowska2025 half-cell 参数集为命名真值），按 8 个物理分组全部落表；另加 4 个非-key 概念输入（x0、Δx、活性质量载量、OCP 迟滞定义），共 **55 行**。
- **来源分级双标签**（role × source_class）逐行落实：SINTEF 直接/派生事实 **A0/A1** 与外部 LFP prior **B2/C** 完全分离；**14 项 UNKNOWN 保留不填**。
- **Capacity closure（本次最重发现）**：`Q_geom = F·A·L·ε_s·c_smax·Δx`。标称 3.0788 mAh 与实测 3.2878 mAh（+6.8%）都能被**几何 + 理论密度 + 合理先验**解释：closure 所需 `ε_s·Δx ≈ 0.448`（实测）／`0.419`（标称）。在 ε_s∈[0.40–0.70]×Δx∈[0.80–1.00] 的 84 格先验网格中，ε_s≈0.5, Δx≈0.85–0.9 等物理合理的商业 LFP 组合即落入实测带。**结论：closure CONSISTENT 但 DEGENERATE**——ε_s 与 Δx 无法由容量单独分离（与 Birmingham 的 nominal-vs-cycler 失配同族，但性质相反：这里 nominal 是保守标签，几何容量足够）。
- **OCP 审计**：SINTEF 自带充/放两支全窗口曲线（**迟滞代理 ≈ 37.5 mV**，充中位 3.444 V / 放中位 3.407 V）；5 个 OCP 候选逐项标注来源/方向/范围/迟滞/插值/外插。**单支 equilibrium OCP 无法同时表示两支实测曲线**——若 H1-D 用单支平衡 OCP 复现迟滞数据，残差应首先归因于模型结构而非 D_s/k0。
- **7 Gate 全过**；**GITT 下载判定 = DEFER**（p-OCV C/50 近平衡扫对 D_s 低敏感，D_s 缺口不构成 H1-D0 的主要证据缺口）。
- **三层参数包**：`experimental_facts.json`（仅 A0/A1）→ `literature_prior_bank.csv`（B2/C）→ `model_ready_composite_draft.json`（DRAFT，声明 `composite_unmatched / publication_reproduction=false / fit_performed=false`，**禁跑**）。

---

## 2. 反向枚举：模型需求全表

方法（可追溯性说明）：对 SPM/SPMe/DFN 的 AST 遍历在 PyBaMM 26.8 上**不可靠**（半电池模型构造后符号树只暴露 16 个顶层参数，孔隙率/动力学等大量参数未物化），已弃用该探针。改用平台可运行的真值：**H0 冻结的 half-cell 参数集 `Jackowska2025_2mAh_cm2`（51 keys，H0 DFN 已在该集上成功求解）** 作为 pybamm 26.8 半电池 key 命名全集快照（`scripts/lfp_h1c/halfcell_required_keys.json`）。SPM/SPMe/DFN 三列的 required 归属按各自控制方程归约判定（DFN 列以 H0 工作集核实；SPMe/SPM 列偏保守，H1-D0 wiring 时复核）。

分组与行数（`parameter_requirements.csv` / `parameter_source_matrix.csv`，55 行）：

| 物理分组 | 行数 | 关键行示例 |
|---|---|---|
| geometry / loading | 14 | L=78µm(A0)、A=1.539cm²(A1)、ε_s(U)、孔隙率(U)、隔膜(U)、电流/截止(A0) |
| solid thermo / OCP | 5 | OCP(A1 双支)、entropic(T)、Li 参考 0 V |
| solid transport | 4 | D_s(U)、R_p(U)、c_smax(B2/theoretical)、D 缩放(fixed=1) |
| kinetics | 5 | i0/k0(U)、α(fixed 0.5)、Ea(fixed 0) |
| electrolyte transport | 7 | D_e/κ/t+/热力学因子(U→generic C)、c_e0(B2 1M)、brug |
| electronic transport | 4 | 电极电导(U/C)、接触电阻(U)、双电层(C) |
| thermal / constants | 5 | (T) 类 isothermal 不消费；Reference T 298.15 |
| initialization | 4 | c_s0/x0/Δx(U)、载量(U) |

### role × source_class 使用情况（55 行统计）

- role：measured 5、derived 6、fixed 14、prior 21、inferred 6、design 2、nuisance 0（`positive_ds_scaling` 记 fixed）。
- source_class：A0 8、A1 8、B2 5、C 20、U 14。（B1 无适用：公开生态不存在 same-material/same-study 的 SINTEF 匹配参数研究。）
- **U 类 14 项零填充**：一律 `value=UNKNOWN`，见 `unresolved_parameters.csv`。

---

## 3. Capacity closure：三方对照（`capacity_closure.csv`）

输入：`F=96485.33212 C/mol`；`A=π(7 mm)²=1.53938e-4 m²`（A0 d=14mm）；`L=78 µm`（A0 干厚）；`c_smax∈{22820 (ae94f3≈theoretical), 21852 (acfc66)}`；`ε_s∈[0.40…0.70]`；`Δx∈[0.80…1.00]`。**全部为网格/先验值，未做任何选择以贴合目标**（hard rule 落盘于 gate 摘要）。

| 目标 | 值 | closure 所需 ε_s·Δx | 解读 |
|---|---|---|---|
| Q_nominal | 3.0788 mAh | **0.419** | 制造商保守标签 |
| Q_exp（5 圈放电均值） | 3.2878 mAh | **0.448** | 需 ε_s≈0.5 & Δx≈0.85–0.9（或 ε_s≈0.55 & Δx≈0.8）即落入实测带 3.2662–3.3059 |

网格极值：`Q_geom` 2.35 mAh（ε_s=0.40, Δx=0.80, c_smax=22820，vs 实测 −28.5%）→ 5.14 mAh（ε_s=0.70, Δx=1.00, c_smax=22820，vs 实测 +56%）。**结论与 Birmingham H0 相反的要点**：Birmingham 是"参数容量 > 实测、cycler 达不到模型容量"；SINTEF 是"几何×理论密度足够覆盖实测，nominal 标签偏低 6.8%"——因此 SINTEF 侧 capacity 不构成 H1-D 的隐性障碍，真正的障碍是 ε_s/Δx 不可分性，需在 H1-D0 用**独立信息**（初始 V0→x0、选定 OCP 端点）收窄，而不是把容量当 fitting target。

> 注意：metadata 的 Mass/Coating/wt%/Loading 对 LFP 行**全空白** → 质量路线不可用（已在 experimental_facts.json 的 `mass_loading` 记 U）。

---

## 4. OCP 审计（`ocp_source_audit.json`）

- **SINTEF 自带双支**（A1，c2–c5 全窗）：discharge 3.406 V / charge 3.444 V（驱动段中位电压代理，**非 throughput 对齐的严格迟滞**）；迟滞代理 37.5 mV。两支都有密集 C/50 采样、[2.5, 3.65] 内无需外插。
- **外部候选**：acfc66（自身 C/50 OCP，figure-only，298 K，电极 26.5 µm/4.749 mg/cm² 与 SINTEF 不同）；ae94f3（自身 C/25 equilibrium + 2×C/25 化成，**窗口 2.8–3.8 V 与 SINTEF 不同**，载量 11.0 mg/cm²）；generic 单支（含 pybamm Prada2013 LFP OCP，C 级）。
- **结构性提醒**：单支 equilibrium 无法表达实测迟滞；若 H1-D 采用单支而残差集中于迟滞带，先判"模型结构假设错误"，禁止直接归罪 D_s/k0。

### H1-C 对 H1-A 参数表的两处数据订正（prior bank 已更新）

1. **ae94f3 载量 = 11.0 ± 0.8 mg/cm²**（fetch 论文正文），不是 H1-A 候选表里误抄的 4.749 mg/cm²（那是 acfc66 的载量）。
2. **ae94f3 电压窗口 = 2.8–3.8 V**（Table II），非 2.5–4.0 推测值。

另：acfc66 正文电解液为 **1 M LiPF6 in EC:DEC 1:1**（非 H1-A 的 EC:EMC 猜测）；其电压窗口与化学计量窗口在 fetch 到的正文中**未明确给出**（保持"未陈述"）。

---

## 5. Gate 表（`h1c_gate_summary.json`）

| Gate | 通过条件 | 结果 |
|---|---|---|
| G1 Model requirement coverage | SPM/SPMe/DFN 所需项全部被枚举 | ✅ 51 keys + 4 conceptual，0 missing |
| G2 Provenance | 每个采用值都有明确 source class | ✅ 55 行 role/class/grade 齐全，U 行零填充 |
| G3 Experimental separation | SINTEF facts 与外部 prior 无混写 | ✅ 三层文件职责分离 |
| G4 Capacity closure | nominal/measured/geometric 差异已量化 | ✅ 84 格 + ε_s·Δx 诊断，未调参 |
| G5 OCP traceability | 来源/方向/范围/外插语义明确 | ✅ 5 候选全字段标注 |
| G6 Unknown preservation | 缺失项明确为 UNKNOWN，不擅自填 | ✅ 14 项 |
| G7 Model declaration | composite 非 exact matched publication set | ✅ draft 三字段声明 |

fresh-replay 字节门：**10/10 文件逐字节一致**。

---

## 6. GITT 下载判据（维持 DEFER）

判定规则：`parameter audit 证明 D_s 成为主要证据缺口 → 才调用 GITT`。
本次裁决：D_s 确为 U 类且外部 spread 达数量级，但 **H1-D0 目标是 C/50 p-OCV 的 zero-fit 复现**，近平衡慢扫对 D_s **低敏感**；容量与 OCP/迟滞才主导。故 SINTEF GITT（b89ab5/b26620）**继续不下**。触发下书的正式理由仅当：(a) 批准 D_s-attribution 实验，或 (b) 批准多倍率 CC 复现。

---

## 7. 产物清单

`outputs/analysis/lfp_h1/parameter_audit/`
```
parameter_requirements.csv       55 行需求枚举（8 分组 × SPM/SPMe/DFN 归属）
experimental_facts.json          layer-1：仅 SINTEF A0/A1 事实
parameter_source_matrix.csv      layer-1+2：role/source_class/value/grade 逐行
literature_prior_bank.csv        layer-2：acfc66/ae94f3/… 18 行可追溯 prior
capacity_closure.csv             84 格 F·A·L·ε_s·c_smax·Δx 对照
ocp_source_audit.json            5 OCP 候选 + 迟滞代理 37.5 mV
unresolved_parameters.csv        14 项 UNKNOWN + 原因 + 出路
model_ready_composite_draft.json layer-3 DRAFT（禁跑声明）
h1c_gate_summary.json            7 Gate + GITT 判定 + 下一站
source_manifest.json             输入/脚本/输出 sha256（确定性）
```
脚本：`scripts/lfp_h1c/build_parameter_audit.py`（0 pybamm import）、`scripts/lfp_h1c/halfcell_required_keys.json`（51-key 命名快照）。

---

## 8. 下一站（H1-D0，待批）

用**审计过的 composite pristine-LFP 参数**做一次 zero-fit forward baseline，把残差分解到 **容量 / OCP / 动力学 / 传输** 层；在 H1-D0 分解与 (V2) identifiability 之前**不做参数辨识**。H1-D0 需先显式定义 as-published 语义（OCP 单支 vs 双支、x0 由实测 V0 + 选定 OCP 反演、ε_s/Δx 在独立信息下收窄——而非容量拟合）。
