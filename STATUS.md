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
Last verified commit:   280ca81  (2026-09-17 晚，L4 倍率预测验收 + 体系锚定电压窗
                                    + 脉冲协议 QC 分级 + GCD 路径初值接线修复)
Tag:                    v0.1.0-platform  (**平台开发阶段冻结**；接新数据不再是开发任务)
origin/main:            **与本地同链，已 push**（2026-09-16；33 个 commit 积压已清零）
Working tree:           见「已知限制 #1」
STATUS.md last updated: 2026-09-17
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

结果：679 行转 canonical / **13 项校验 / 严重 0 / 警告 3** / 匹配参数集
`Jackowska2025_2mAh_cm2` (grade B) / 输出 `outputs/user_datasets/demo_birmingham_cover5`。

（2026-09-17 复核：仍是 679 行；检查项 12 → 13、警告 2 → 3 是新增的体系锚定
窗口门带来的 —— 该 demo 是 NCM 半电池且未声明工作电极材料，所以那条是
"检查被跳过"的 WARN，不是错误。见 `docs/chemistry_windows_and_gitt_qc.md`。）

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
  G5.3 联合 D_s–R_p 辨识几何与失配补偿         PASS     — 2026-09-16（退化方向即补偿方向，见下）
  G5.4 多协议辨识性 + 模型一致性                PASS **FROZEN**  — 2026-09-16（多协议无效，独立测量有效）
  G5.5 测量 → 模型尺度映射 + 不确定度传递       PASS **FROZEN** — 2026-09-16（含 G5.5a，见下）
  ══ Chen2020 方法学分支到此封存 ══
G6 graphite‖Li 实验约束模型                   IN PROGRESS
  G6.0 graphite 参数 provenance 审计            IN PROGRESS — 见下
  G6.1a 协议依赖的数值活性门                    PASS(实质)/FAIL(判据) — 2026-09-16，见下
  G6.1b-1 全局 log-multiplier 恢复门            **FAIL(I1)** — 2026-09-16，见下
  ══ 尺度对齐门（scale alignment gate）═         已提升为一级概念 —— 2026-09-16，见下
  G6.1c GITT 激励地图（476 窗口，双向）         放电 **FAIL(M1/M2)**｜充电 **PASS(6/6)** — 见下
  G6.1b-2 3-region basis                        落脚点**存在但很窄**（3 个窗口；先测方向独立性）
  G6.2a D_s(x) 表示接口门                       **接口 PASS / 判据 9/11**（2 条窗口类 FAIL）— 见下
  ══ 结构表征契约 + 回收石墨 adapter 骨架 ═      完成 —— 2026-09-17，见下
  ══ 商用石墨热处理梯度（材料侧，第一线）═      设计 v2 + 4 份样品元数据 —— 见下
  ══ 生产一批数据（实验）═                      **下一步就是它**（不是写代码）
  G6.2 graphite identifiability                 NOT STARTED
  G6.3 独立 protocol 验证                       NOT STARTED
  ══ 平台冻结包（productization freeze）═         完成 —— 2026-09-16，见下
G6 held-out 预测         NOT DONE
G7 再生状态泛化          NOT STARTED
G8 优化闭环              NOT DONE
```

### 平台冻结包 — **完成**（2026-09-16）

导师定的"产品化冻结"五项全部落地，**纯 additive**（`run_pipeline.py` / runner / evaluator /
factory / registry / `rates.py` / `paths.py` **一行未改**）。目标状态：
`实验数据 → dataset adapter → protocol 解析 → scale alignment → PyBaMM replay →
identifiability → 参数报告`；"接入新数据集"从写一份 20 KB adapter 变成**填 5 个 hook + 一份 metadata**。

| # | 交付物 | 位置 | 实测 |
|---|---|---|---|
| 1 | 数据集接入模板 + 契约自检 | `battery_sim/datasets/template.py` | `--check dlr_gitt` → **PASS(0 err / 3 warn)** |
| 2 | 新数据接入 README | `docs/adding_a_dataset.md` | 4 步 + 写代码前必答的 10 个格式问题 |
| 3 | material identification mode | `governance/analysis_mode.py` | material 模式下 truth 字段 → `ModeViolation` |
| 4 | 自动报告生成 | `identification/parameter_report.py` | 双向报告已生成，见下 |
| 5 | 回收石墨空模板 | `templates/recycled_graphite/` | 元数据不完整 → **构造即失败** |

**判定词汇只有五个**（`governance.analysis_mode.ALLOWED_VERDICTS`）：
`identifiable` / `not identifiable` / `bounded` / `unconstrained` / `not_measured`。
**只有 `identifiable` 允许引用数值；`bounded` 只报界；另两个不许报数。**
判据（水平 1 mV、上限 0.30 dex、扫描 ±1 dex、网格分辨率 0.05 dex）必须与判定一起写。
`bounded` 的方向写清了：左截断 → 可报上界；右截断 → 可报下界（G6.1c 实测那一侧是下界）。

**已生成的报告**（由产物直接生成，**未手抄**）：

| 报告 | 判定 | 依据窗口 | 带宽 |
|---|---|---|---|
| `outputs/reports/dlr_gitt_charge_identifiability.md` | `identifiable` | `GITT-charge#t475` | 0.0988 dex |
| `outputs/reports/dlr_gitt_discharge_identifiability.md` | `not identifiable` | `GITT-discharge#t224` | 0.3261 dex |

两份报告里 `k0` / `Rct` 都写 **`not_measured`**（本条记录没有 EIS）——
这正是新治理层要防的："没测"不许被写成"不显著"。
两份报告都自动带上 `dataset_role: benchmark` 的提示：**不构成对该材料参数集的验证**。

**契约自检在真实 adapter 上暴露的三个警告**（照实记，未改阈值）：
① 协议型数据集没有额定放电（`load_discharge` 未实现，属预期）；
② 没声明 `nominal_capacity_Ah`（尺度对齐门只能从参数集反推模型容量）；
③ **`list_protocols()` 广告的扫程级 id `GITT-charge` 不可整流回放**（只有 `#tN` 窗口 id 可，
   因为充电半程在记录里是交错的）——D62 级别的接口不一致，**不影响 G6.1c**（它一直用窗口 id），
   但新接入的 adapter 必须让 `list_protocols()` 只返回 `load_protocol` 能接受的 id。

**顺带补上的 provenance**：`configs/datasets.yaml` 的 `dlr_gitt` 块补了 `source:` 字段
（平台的来源字段此前缺失，而"实验数据必须留来源"是红线）。

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
→ **"高倍率下识别出真值"不能当作成功。**

> **更正（2026-09-16，G5.3 实测）**：初稿解释为"高倍率下 $D_s$ 失去杠杆作用"，
> **该解释已被否定**。G5.3 量了 profile $J(z_D\pm0.05)$（以 profile 最小值为基准）：
> 0.1C ×1.700 / 0.5C ×1.638 / **1.5C ×1.466** —— **全部 STILL SENSITIVE**，
> 目标函数在 1.5C 上**并不平坦**。
> 正确表述：**高倍率失配表现为"$D_s$ 无法消除的加性残差"，而不是"D_s 被拉偏"。**
> **教训：地板大只证明失配大，不证明目标函数平坦 —— 残差性质与曲率性质必须分别测量。**

**③ 最危险的一条 —— 错误模型下真值不是最优解**：
用低倍率辨识出的"错"参数（$D_s^*$=1.45–1.50e-15）跨 protocol 预测，
**在 C10 和 C2 上都比真值好 3.4×**；而 1.5C 的"看似恢复真值"对应的地板是 92.6 mV。
→ **若手上只有 SPM 拟合结果，会报告 $D_s\approx1.45\times10^{-15}$ 为材料参数，
它在每个 protocol 上都比真值拟合得好，残差健康，跨倍率"可迁移"。**

> **适用范围有限定（重要）**：这个"残差不报警"只在**低–中倍率**成立。
> 0.1C 地板 1.66 mV（确实不报警）、0.5C 地板 7.01 mV（很弱），
> 但 **1C（33.0 mV）与 1.5C（92.6 mV）的残差本身就是明显警告**。
> 论文表述应为：
> **"At low-to-moderate rates, model-form error can be partially absorbed by a
> biased effective diffusivity while retaining deceptively small residuals."**

**④ 可迁移性检验反向失效**：低倍率 → 高倍率 **完全跑不通**（5 个单元格 unreachable，
覆盖 < 50 %）；高倍率 → 低倍率跑得通但差（5.602 vs 1.656）。
→ **不存在 protocol 无关的 $D_s$。**

**边界**：仍是合成数据（换掉的是**模型形式**，不是数据来源）；只测了一个方向的失配
（SPMe→SPM）；单电芯（cell 02）、单参数集；倍率覆盖不全。
**没有**结论说"SPM 不能用" —— 结论是**SPM 下辨识出的 $D_s$ 是 effective parameter，
不是材料常数**，而它"看起来很好"本身就是失配的证据。

### G5.5a 模型尺度不确定度传递 — **PASS ｜ Chen2020 分支封存**（2026-09-16）

完整报告 `docs/g5.5a_radius_uncertainty.md`。
可复现：`python scripts/identification/g5_5a_radius_uncertainty.py`（340.6 s）
\+ `python scripts/identification/g5_5a_beta_analysis.py`（后处理）

**定位**：Chen2020 方法学分支的**收尾**。刻意**不**解释 5.22 µm 对应哪个 PSD 统计量，
也**不**虚构数量/面积/体积三套加权 —— 没有对应原始测量时那是制造伪信息。

$$\beta=\frac{d\log D_s^*}{d\log R_p}$$

| 臂 | 绕 δ=0 拟合 | LOO 范围 |
|---|---|---|
| control | **2.0751** | **[2.0708, 2.0812]** |
| mismatch | **2.0564** | **[2.0533, 2.0606]** |

**两臂都紧贴理论参照 $\beta=2$（只约束 $\tau_d=R_p^2/D_s$ 时的精确值）。**

> **判据修正（本轮踩的坑）**：失配臂在 δ=0 处**本身带 −25.0 % 偏差**，
> 过原点的幂律拟合把常数偏移折进指数 → LOO 炸到 `[1.22, 2.96]`。
> **绕 δ=0 归一化**后 LOO 立刻收到 `[2.053, 2.061]`。
> 控制臂两种算法给出同一数（偏移为零），是一致性检查。

**产出：粒径表征精度要求**（$\Delta D_s/D_s \approx 2\,\Delta R_p/R_p$）

| 粒径精度 | $D_s$ 不可约偏差 |
|---|---|
| ±2 % | ∓4 % |
| **±5 %** | **∓10 %** |
| ±10 % | ∓20 % |
| ±20 % | ∓37~46 % |

**边界**：合成数据；**协议只有 0.1C 一个**（β 是否依赖倍率/协议集未测）；
扰动是均匀相对扰动，非真实误差分布。

---

### G6.1a — Protocol-dependent activity gate for function-valued parameters（2026-09-16）

完整报告 `docs/g6.1a_protocol_dependent_activity.md`；先行审计 `docs/g6.1a_gitt_protocol_audit.md`。

**结论：门的实质成立，但按预先登记的判据「未通过」—— 负对照失败。**
正对照干净通过且按倍数单调；单变量负对照完全惰性；原定 pOCV 负对照失败，
**而那个失败推翻了我上一轮的结论**。
**四臂结果**（`dV_pulse` 的展开是观测量；判据跑前固定）

| 臂 | 协议 | ×0.316 | ×1.000 | ×3.162 | 展开 | 判定 |
|---|---|---|---|---|---|---|
| 负（单变量） | GITT 窗口**电流置零** | +0.0000 | +0.0000 | +0.0000 mV | **0.0000** | **惰性 ✓** |
| 正 | GITT 平台区（C/10, 150 s） | −16.9640 | −12.4358 | −8.7190 mV | **8.2450** | **活跃 ✓** |
| 正 | GITT 陡峭区（$V\approx0.93$） | −215.1409 | −193.2171 | −185.7535 mV | **29.3874** | **活跃 ✓** |
| 负 | pOCV（C/50） | RMSE 77.6701 | 76.2860 | 79.7139 mV | **3.4279** | **失败 ✗** |

**正对照严格按倍数单调**；零电流臂三个倍数**逐位相同**（证明覆盖链路干净）。
三档梯度 `无激励 0.00 < pOCV 3.43 < GITT 平台区 8.25 < GITT 陡峭区 29.39` 即协议依赖性的直接度量。

⚠️ **推翻了上一轮结论**：此前记的"pOCV 整条 $D_s$ ×10 只动 0.018 mV、
准平衡本来就不激发固相扩散"**是错的** —— 那次用的是未做容量一致化的 Ecker2015 几何（202 mAh），
$4.33\times10^{-5}$ A 实际是 **C/4670**。**惰性是 31 倍尺度失配造的，与准平衡无关。**
修正表述：**模型与电芯同尺度时，C/50 的 sweep 仍能分辨 $D_s$（RMSE 展开 3.43 mV）。**

**必须先解决的前提：容量一致化（Q_model == Q_measured）**
Ecker2015 描述 86 cm² / **202.398 mAh** 电芯，而 DLR 扫程电荷只有 **6.528 mAh** →
那条"C/10"脉冲实际是 **C/309**，sim 瞬态比实测小 **43 倍**。
判别接线问题 vs 尺度问题：把电流缩放 ×1/×10/×100 → 响应 **−0.394 / −4.019 / −29.92 mV**
⇒ **成比例，电流确实进了模型** ⇒ 是尺度问题。
两个修正：① **容量基准取扫程电荷，不取单个脉冲**（单个脉冲只有 0.0273 mAh，
用它当容量会把模型缩到 1/7400、直接撞截止、`dV_pulse` 全 NaN，
**读起来正好像"参数惰性"**）—— 契约测试已钉住；
② 缩放电极 footprint（长宽各 ×√scale，保长宽比），面积缩放 DLR 0.032252 / SINTEF 0.008818。

**新增代码（四层）**：`battery_sim/excitation/`（纯数据 protocol schema + Basytec 解析）、
`battery_sim/datasets/dlr_gitt.py`、`battery_sim/simulation/protocol_replay.py`、
`scripts/graphite/g6_1a_activity_gate.py`、`tests/test_dlr_gitt.py`（28 项）。
**additive**：adapter 契约加**可选** protocol 能力；`resolve_model_options` 从
`run_baseline_cell` **原样抽取**（避免第二个入口变成第二份半电池翻译副本）。
平台全量 **356 passed**。
**治理**：`dlr_gitt` 声明 **benchmark**（仅评估、禁标定）。

**边界**：**不是对 Ecker2015 的验证** —— 另一颗电芯、另一实验室、另一种电极与 OCP；
容量一致化是**构造前提**不是测量（DLR 几何无数据手册，footprint 按实测电荷缩放）；
只有 SPM、单电芯、单温度；pOCV 臂覆盖率 0.957，其瞬态量为 NaN（**"跑不完" ≠ "瞬态小"**）；
×0.316 与实测吻合（−16.96 vs −17.17 mV）**不能**读成"真实 $D_s$ 是参考的 0.316 倍"。

**原定的 pOCV 负对照为什么不再当对照**：它**不是单变量** —— 同时改了尺度、时长、状态，
无法把"没有激励"和"什么都不同"分开。零电流臂是追加的更强对照；
**原判据的失败保留在报告里，没有事后改阈值。**

**正对照被阻断 —— SINTEF `gitt`/`gitthold` 不含脉冲序列**：

| 证据 | 事实 |
|---|---|
| step 数目 | 每循环只有 **9 个** step（真 GITT 应 ~40 个脉冲+静置对） |
| 相位性质 | step 4/10 为 **C/50 恒流**；step 7/13 为**恒压保持**（V 钉在截止、I 衰减 33×/6 h） |
| 倍率 | 4.4155e-05 A ÷ 1.942466 mAh = **C/44 ≈ C/50** |
| 行序 | **每个 parquet batch 都含 >1 个 step**（347/347）；每个时间桶同时有 **3 个 step** 在记录 |
| 采样率 | 三通道不同：**8.14 Hz / 0.076 Hz / 0.163 Hz** |
| 通道不同源 | 同一时刻 step 8 V=0.09019、step 10 V=0.10605 → **不是重复记录** |

由此按 `(cycle, step)` 分组（**adapter 的做法**）会得到三个物理不可能的结果：
`I` 精确为 0 却移动 2 V 电压（cycle 1/2 step 2）、同一 step 电流积分 0.0136 Ah
而容量列只累积 0.002293 Ah（**差 6 倍**）。

→ **`(cycle, step)` 不是该文件的物理分段；不能照 p-ocv 老路换名就跑。**

**找到替代：`data/DLR__LiGrHydra0b__20221114__GITT__25degC__Basytec.txt` 是真 GITT。**

| 项 | 值 |
|---|---|
| Command 组 | **Discharge 240 段 / Charge 238 段 / Pause 478 段** |
| 脉冲 | **149.94 s**（放电）/ 149.65 s（充电） |
| 电流 | **−6.552e-04 A**（水平高度一致：30,221 行 @ −6.552198e-04） |
| 温度 | **24.85–26.25 °C 实测通道**（SINTEF 无温度通道） |
| 电压 / 时长 | 0.00973–1.51486 V / 25.62 天 |
| 可用 pulse-rest 三元组 | **239 个**（排除截止削顶） |

**为什么 150 s 正是需要的**：$\tau_d=R^2/D_s\sim10^4$ s → $t_{\rm pulse}/\tau_d\approx0.015\ll1$
→ 处在**半无限扩散（Sand）区**，瞬态由固相扩散主导 —— 这正是 pOCV 给不出的。

**推荐窗口**：三元组 **#120**（$V\approx0.116$ V 石墨平台区）
静置 5472 s → 脉冲 150 s @ −6.5098e-04 A（**ΔV = −17.5 mV**）→ 静置 7293 s；
脉冲段采样 ~1 Hz（~154 点），窗口内温度 26.05–26.08 °C（无温度混杂）。
备选 #4（$V$ 0.93→0.65，ΔV −279 mV）、#6（ΔV −121 mV）用于更大信噪。

**建 adapter 时的三个坑（已记入代码与测试）**：
① 编码是 **Latin-1**（UTF-8 在 `0xb0` 处失败）；
② 相位靠 **`Command` 列**（Pause/Charge/Discharge），不靠 step 编号；
③ **符号** —— 本文件 Discharge 电流为负（Basytec 惯例），平台 canonical 是 discharge = +，须翻转；
且符号**在数据内被验证**（canonical I>0 与 V 下降同时发生），契约测试钉住。

### 尺度对齐门（Scale alignment gate）— **已提升为平台一级概念**（2026-09-16）

完整说明 `docs/scale_alignment_gate.md`；实现 `governance/scale_alignment.py`；
测试 `tests/test_scale_alignment.py`（18 项）。

**为什么它必须是流程而不是脚本里的一段**：同一个坑踩了两次，**两次的输出完全一样**。

| | 参数集描述的电芯 | 记录实际通过的电荷 | 比值 | 当时的（错误）读数 |
|---|---|---|---|---|
| G5 p-OCV | 202.398 mAh | 1.7846 mAh | **113×** | "准平衡不激发固相扩散" |
| G6 DLR GITT | 202.398 mAh | 6.5277 mAh | **31×** | "C/10 脉冲只动 0.4 mV" |

标称 C/10 的脉冲在 31× 失配的模型上实跑 **C/309**（瞬态小 43 倍）；
判别"接线问题 vs 尺度问题"的办法：把电流 ×1/×10/×100 →
响应 −0.394 / −4.019 / −29.92 mV **成比例** ⇒ **是尺度问题**。

```
Dataset -> Geometry audit -> Capacity alignment -> Protocol excitation -> Parameter inference
```
顺序写成常量 `PIPELINE_STAGES` 并有测试钉住：**跳过前三步，"参数不可辨识"无法归因**。

**门的产物是两个 C-rate**（历来只报第一个）：

```
c_rate_on_cell           = I_pulse / Q_measured  = 0.1004    （读数怎么写的）
c_rate_on_model_unscaled = I_pulse / Q_model     = 0.003237  （模型实际跑的，C/309）
```
**只有第二个决定固相扩散是否被激发。**

**强制点是新增的 additive 入口**（冻结内核一行未改）：`run_protocol_replay(scale_alignment=...)`
默认 `"check"` → **不对齐就拒绝跑**；`"align"` → 自动施加 footprint 配方；
`"assume"` → 声明豁免并在 `run_metadata.json` 留下
`scale_alignment.verdict == "assumed_by_caller"` + "没有证据表明它真的对齐"。
异常类型是专用的 `ScaleMisalignment`（不是 `ValueError`）：尺度失配**可修**，
参数名写错不可修，混进同一类型就是它们被混为一谈的开始。

**两个附属结论**：① 容量基准必须是**扫程**不是单个脉冲（单脉冲 0.0271 mAh
→ 模型缩到 1/7400 → 撞截止 → 瞬态全 NaN，**读起来正好像"参数惰性"**）；
② 缩放的是电极 footprint（长宽各 ×√scale），不是 ε_am/厚度
（那会得到 0.012 / 2.4 µm 的荒谬值）；③ 容差是**声明**值 ±0.05 dex，
有测试专门证明它不是隐藏常数（同一组数字 + 容差放宽 → verdict 必须翻面）。

### G6.1b-1 全局 log-multiplier 恢复门 — **FAIL（I1 可辨识性）**（2026-09-16）

完整报告 `docs/g6.1b1_global_recovery.md`。
可复现：`python scripts/graphite/g6_1b1_global_recovery.py`（266 次仿真，**52.8 s**）

$$\log_{10}D_s(x)=\log_{10}D_{\rm ref}(x)+a_0,\quad \varphi_0(x)=1,\quad a_0\in[-1,+1]\ \text{dex}$$

先过尺度对齐门（模型 202.398 mAh vs 扫程 6.5277 mAh → MISALIGNED 31.0×，footprint ×0.032252）。

**判据跑前固定：过 8 条，`I1 可辨识性` 失败。**

| 判据 | 结果 | 数字 |
|---|---|---|
| F1 前向活性 | PASS | 峰值 model-to-model RMSE **15.5726 mV** |
| F2 前向有序 | PASS | `dV_pulse` 沿 41 点严格单调 |
| R1 恢复 | PASS | 最大误差 **0.000000 dex**（**inverse crime，见下**） |
| R2 内点 | PASS | argmin 全部 = 真值 |
| **I1 可辨识带** | **FAIL** | 最大带 **1.0089 dex**（上限 0.30） |
| C1 优化器一致 | PASS | Brent 与扫描差 **0 dex** |
| C2 扫描覆盖 | PASS | 41/41 可达 |
| C3 脉冲外干净 | PASS | 泄漏 **0.000e+00 mV** |
| N1 负对照平坦 | PASS | 无激励面**精确平坦**（max\|dV\| = 0） |

**1 mV 代价带**（带的分辨率一律 0.05 dex，即粗网格步长）：

| 真值 $a_0$ | 平台区带宽 | 陡峭区带宽 |
|---|---|---|
| −0.5 | 0.682 dex | **0.140 dex** |
| 0.0 | 0.897 dex | 0.350 dex |
| +0.5 | **1.009 dex（截断）** | **0.826 dex（截断）** |

**三条主结论**：

1. **R1 是接线检查，不是成绩。** 观测就是同一次扫描在 $a_0$ 点的输出
   （同模型、同参数化、同求解器、无噪声）⇒ $J(a_0)$ **精确为 0** ⇒ 不可能失败。
   **inverse crime**：$\text{synthetic recovery success}\neqq\text{experimental identifiability}$（同 G5.0 红线）。
2. **活性 ≠ 可辨识（实测）**：G6.1a 判"活跃"（平台区 8.2450 / 陡峭区 29.3874 mV 展开）没错，
   但 1 mV 水平上 $D_s$ 在平台区可动 **7.9×**（0.897 dex）而轨迹不动 —— 报不出材料参数。
3. **单侧性：$D_s$ 只有下界**（本轮最实质的结论）。六个 (窗口, 真值) 组合**全部**同一方向：
   曲率不对称量六个**全为负**（−0.007…−0.043）；1 mV 带**右侧一律 ≥ 左侧**；
   $a_0=+0.5$ 的两个窗口**右侧撞到扫描边界仍未穿过 1 mV**（⇒ 报出的是**下界**）。
   端点对比最直白（$a_0=0$，陡峭区）：$a=-1$（$D_s$ 小 10 倍）→ **13.775 mV**；
   $a=+1$ → **2.501 mV**。
   > **这些脉冲协议给的是 $\tau_d$ 的上界（$D_s$ 的下界），不是 $D_s$ 的估计值。**
   > 报点估计在数学上是一个**没有上界的**量。

   **规范措辞（引用请用这句，不要写 "GITT cannot identify D_s"）：**
   > *The tested GITT excitation constrained diffusion kinetics only within a
   > one-sided sensitivity region, providing bounds rather than point
   > estimates of $D_s$.*
   （这个激励**确实**在一个方向上约束了 $D_s$；它给的是**界**，不是**点估计**——
   与"不给信息"是不同的失败方式。）

   （与 G5.3"谷是脊不是碗"同族但**更严重**：G5 是两参数沿一条浅方向**线性**补偿，
   G6.1b-1 是单参数**单向半轴**失去约束 —— 后者长得像一次成功的拟合。）

**④ 幅度与带宽不成比例**：活性比 3.56× / 曲率比 6.24× / **带宽改善只有 2.56×**
⇒ **不能拿"响应大"当协议选择的代理指标**，必须直接测带。
（G5.4"残差排序与精度排序相反"在同一主题上的第二次出现。）

**⑤ 负对照把"没有信息"翻译成"误差有多大"**：零电流 → 代价矩阵 max **0.000000e+00 mV²**，
任何确定性优化器返回**初值**；以 $a_{\rm init}=0$ 计，$a_0=\pm0.5$ 的隐含误差是
**0.5 dex（$D_s$ −68.4 % / +216 %）**（标注 `derived_not_measured`）。

**判据更正**：设计里要求的 **Hessian condition number 在 $d=1$ 时是空话**
（$1\times1$ 矩阵条件数恒为 1）—— 按规定上报，并同时写明它为什么不含信息；
替代量是**实测** $J''(\hat a_0)$ 与 1 mV 带宽度（最小值是测出的网格点，**不插值**）。
条件数到 G6.1b-2（$3\times3$）才成为真判据。

**为什么暂缓 G6.1b-2**：本轮**没通过**，而失败方向说明**加基函数会变糟**
（3-region 把 1 个系数换成 3 个，每个的带只会更宽）。
带宽本身就是选择下一步的依据：陡峭区带比平台区窄 **4.9×** ⇒ **协议选择比参数化更重要**；
建议先在这份记录里把 239 个可用三元组逐个跑出"1 mV 带宽度"（成本极低：266 次仿真 53 s），
再决定是否进 3-region。

**边界**：无噪声、无模型形式差异（**理想条件下的最好情况**，真机只会更宽）；
1 mV 是本轮选定的**可辨识水平**不是仪器噪声；带分辨率 0.05 dex
（最窄的 0.140 dex 相对不确定度约 ±36 %，I1 的失败不是分辨率产物）；
两个组合的带**被扫描边界截断**；只有 SPM / 单电芯 / 26 °C / 150 s 脉冲；
**不是对 Ecker2015 的验证**（另一颗电芯，`dataset_role: benchmark`，不许叫 validation）。

### G6.1c GITT 激励地图 — **放电 FAIL（M1/M2）｜充电 PASS（6/6）**（2026-09-16）

完整报告 `docs/g6.1c_excitation_map.md`。
可复现：`python scripts/graphite/g6_1c_excitation_map.py --sweep discharge|charge`
（放电 239 窗口 / 225 可用 / **10009 次仿真 24.5 min**；充电 237 / 230 / **9933 次 24.5 min**）

每个窗口一个数：$B_i$ = 使 model-to-model RMSE 回到 **1 mV** 所需的 $a_0$ 位移（dex），
在 $a_0=0$ 处；扫描 $\pm1$ dex 均匀 0.05 dex；容量尺度/模型/参数集**全部固定**。

| 判据 | 放电 239 | **充电 237** |
|---|---|---|
| **M1 存在性**（$B\le0.30$ dex 且未截断） | **FAIL**（0） | **PASS（3）** |
| M1b 同上 @$a_0=-0.5$（冒烟后追加，secondary） | PASS（4） | PASS（11） |
| **M2 筛选性**（按实测 $\lvert dV_{\rm pulse}\rvert$ 的 top-10 与按 $B$ 的 top-10 重叠 ≥5） | **FAIL**（4/10） | **PASS（7/10）** |
| M3 单侧性（不对称量中位数 < 0） | PASS（−0.0159） | PASS（−0.0291） |
| M4 分辨率（中位 ≤0.10 dex） | PASS（0.050） | PASS（0.050） |
| N1 负对照（零激励精确平坦） | PASS | PASS（3 个里 1 个能跑） |

**⇒ 这份记录里确实有能把 $D_s$ 定下来的激励，但只在充电方向、最脱锂的那一端。**
**推荐子集**：放电侧 = **空集**；充电侧 = **`['GITT-charge#t475']`**（唯一）。

| 合格窗口 | $x_0$ | $V_{\rm pre}$ | $\lvert dV_{\rm pulse}\rvert$ | $B$ @0 | $B$ @−0.5 | 不可达探针 |
|---|---|---|---|---|---|---|
| `#t475` | 0.0054 | 0.9183 V | 596.6 mV | **0.0988** | **0.0084** | 2/43 |
| `#t474` | 0.0067 | 0.8319 V | 642.5 mV | **0.1336** | 0.0119 | 8/43 |
| `#t0` | 0.0114 | 0.7747 V | 729.5 mV | **0.1368** | 0.0199 | **0/43** |

**主体没变**：放电 **155/225（69 %）** 与充电 **214/230（93 %）** 右侧截断，
$B$ **中位数两侧都是 2.000 dex**（= 整个扫描范围，完全没闭合）。

**同状态配对（$|\Delta x_0|\le0.01$，204 对）—— 方向本身是变量**：
115 对两侧都无信息；49 对两侧都可测（中位差 **−0.082 dex**，38/49 在 0.25 dex 内）；
**40 对只有一侧可测**（另一侧精确停在 2.000）。
最干净一例：**同一个 $x_0\approx0.0053$，放电脉冲 $B=0.350$ vs 充电脉冲 $B=0.099$（3.5×）**；
$x_0\approx0.015$ 处 **5.1×**。更深一点（$x_0\approx0.021$）**反号**。
⇒ **"哪个窗口好"是（状态 × 方向）的函数，不是状态的函数。**

**其它结论**：
1. 绝大部分窗口对 $D_s$ 没有信息（放电 75 %、充电 93 % 在 $\pm1$ dex 内不闭合）。
2. **单侧性在大样本上成立**（两侧中位不对称量均 < 0），与 G6.1b-1 一致。
3. 放电侧"最好的窗口"（`#t225`）在**模型失效边界**上（41 探针 19 个跑不到，
   紧邻 9 个根本回放不了的窗口）；充电侧不同 —— `#t0` 探针 **43/43 全可达**。
4. **实测脉冲幅度在放电侧不是可靠筛选量**（$\rho=-0.713$，4/10）；
   在充电侧**够用**（$\rho=-0.515$，7/10）—— 因为那里最可辨识的窗口恰好也是脉冲最大的。
   后验的"松弛/脉冲比"两侧**符号都反**（+0.287 / +0.448）；模型侧展开量两侧都最强
   （−0.914 / −0.758）。
5. **16 个窗口无法回放**（放电 9 + 充电 7，均初始条件撞最低电压事件）⇒ 可用率 455/476。

**② 决策更新（G6.1b-2）**：落脚点**存在但很窄** —— 467 个窗口里只有 3 个合格、
按"状态要分散"只留 1 个。若做 3-region：**先在这 3 个窗口上做，且必须同时报每条系数自己的带**；
但这 3 个窗口状态极近（$x_0$ 0.005–0.011），**大概率不构成三个独立方向**，须先实测。
更值得先做的仍是**激励设计**：方向能带来 3.5–5× 差别 ⇒ "在悬崖区做**双向**脉冲"
比"在下游加密参数"更可能拿到信息。

**③ caveat（必须一起引用）**：三条合格窗口的脉冲幅度是 **597–729 mV**（记录里最大一档），
`#t0` 脉冲末端约 **0.046 V**、贴在电压下限。$B$ 小**部分来自**电压被推到 OCP 悬崖，
**那里的模型有效性需要论证 —— "可辨识"与"模型在那里是对的"是两件事**。

**边界**：$B$ 是 model-to-model 量，无噪声/无模型形式差异（**理想条件下最好情况**）；
分母 225/230 不是 239/237；6 个放电窗口的带在被削定义域上量出（全部带 `truncated`）；
只有 SPM / 单电芯 / 26 °C / 150 s 脉冲；§7.3 的"方向效应"是**实测现象**、机制解释只是**假设**；
**不是对 Ecker2015 的验证**。

### 结构表征契约 + 回收石墨 adapter 骨架 — **完成**（2026-09-17）

导师 Step 1/2：**契约先于数据**。字段、单位、来源、缺失处理方式全部定下来，
数据到手时只剩「填 metadata + 跑自检」。

- **结构块** `structure: {xrd, raman, bet}`（`battery_sim/datasets/material_metadata.py`）：
  键是**闭集白名单**；`available: true` 时必须给 file / role / 关键测量量 / source；
  `available: false` 时必须给 `not_available_reason`
  （「没测」与「忘了写」在下游无法区分，与 `not_measured` 同一个道理）。
  关键测量量：xrd `d002_nm`｜raman `id_ig`｜bet `surface_area_m2_g` **+** `pore_volume_cm3_g`
  （**不只留面积**：回收石墨更关心孔结构）。
- **只收测量量**：`defect_level: high` 这类**解释**被拒绝，并指向该写的测量量
  （`INTERPRETATION_KEYS` 里 6 条定向提示：defect_level / graphitization / crystallinity /
  activation / quality / capacity_fade）。单位写在字段名里（`_nm`/`_cm1`/`_m2_g`/`_cm3_g`），
  **不做换算**；超常见区间的值只 warn（先怀疑单位，不直接判死）。
- **逐块来源**：`source: {type, instrument, operator, date}`，`type` 词表
  `experiment|literature|vendor|estimate`；缺任一项即错
  （「出现 BET=56.3 却不知道谁测的 / 哪台仪器 / 哪一天」）。
- **回收石墨 adapter 骨架** `battery_sim/datasets/recycled_graphite.py`
  （**不写进 live config**，避免空数据集破坏管线）：
  `python -m battery_sim.datasets.recycled_graphite --validate`
  → **PASS（0 错 / 0 警 / 5 待办）**，含义是**契约成立、等数据**；
  `--require-data` 把「数据未就位」升级为错误（数据到手后的复核用）。
  能力声明守契约：基类的协议接口**保持未覆盖**（有测试钉住）。
- **目录约定**（样品是 metadata 字段，**不是**目录层级，否则加一个样品就要改代码）：
  `raw/electrochemistry/`、`raw/structure/`、`processed/`。
- **`examples/frozen_results/`**：只放 summary.json + report.md + 一张图（**209 KB**），
  **不放全部 CSV**；`outputs/fitting/` 继续 gitignore（复核靠重跑命令）。

### 商用石墨热处理梯度：设计 v2 + 工艺史契约 — **完成**（2026-09-17）

导师定的下一步是**停止开发平台功能、进入真实材料验证**，具体两件事：
600/800/900 °C 商业石墨的实验设计，和三个样品（含 baseline）的 metadata 模板。
两件都做完，并顺带修掉一处**会当场说谎**的报告措辞。

**① 实验设计 v2** —— `docs/graphite_heat_treatment_test_plan.md`（重写 v1）

| 项 | v1 | **v2** | 依据 |
|---|---|---|---|
| 样品 | 干燥 / 500 / 800 °C | **CG-AR / 600 / 800 / 900 °C** | 处理温度是本批**自变量** |
| GITT | ❌ 不做（估 4 个月/颗） | ✅ **做，且是重点**（40 h/颗/方向） | 4 个月来自**另一个协议**：1800 s 脉冲 + 9000 s 静置 × ~1000 脉冲（0.1 %/步）。按导师的 10 min/30 min、60 脉冲（1.67 %/步），机时 **3000 h → 40 h（约 75×）** |
| EIS | 可选、含糊 | ✅ 必测（100 kHz–10 mHz × 10/50/90 % SOC） | 不测就分不清"扩散变慢"与"界面变差" |
| 结构 | D10/D50/D90 + BET | **+ SEM 取 R_p** | 平台里 **D ∝ R²**：粒径不测，D_s 的差异无法归因 |

**② 一处新算出来的量化判据（v1 没有，而它决定"哪里能反演"）**

GITT 的无量纲时间 τ = D·t/R²。用参考参数集 `Ecker2015_graphite_halfcell`
（R_p = **13.70 µm**）算 600 s 脉冲：x = 0.02 → **τ = 2.37**；x = 0.10 → **0.98**；
x ≥ 0.30 → 0.128 → 0.029。
⇒ **稀相端（x ≲ 0.15）形式上不满足半无限扩散**（那里 D_s 大 80 倍，颗粒在脉冲内
已被平衡），**该区间不报 Sand 反演结果**。这同时解释了 G6.1c 的反直觉现象：
"唯一可辨识"的窗口正好落在最脱锂端 —— **可辨识区与模型有效域边界重合**。

口径：参数集自带 `R_p = 13.70 µm` 与实测 D50/2 = 8.79 µm 相差 **1.56×**，
对应 D_s 相差约 **2.4×** ⇒ 报告必须写明用的是哪一个 R。

**③ 工艺史契约** `processing`（`battery_sim/datasets/material_metadata.py`）

`recycling` 回答"材料从哪来"，`processing` 回答"对它做了什么"——后者是这条
梯度的**自变量**，只写进 sample_id 字符串没人能复核。形状与 structure 块同构：
`applied: true` → 方法/温度/时长/气氛四项 + **闭集键**；`applied: false` →
必须写 `not_applied_reason`。含 `mass_before_mg`/`mass_after_mg` → **失重率**
（"去掉了多少 SEI / 官能团 / 无定形碳"最便宜的第一手证据）；
氧化性气氛 + >500 °C 与 recycling **共用同一条 warn**（一个实现，两个入口）。

**系列级校验** `validate_series` + CLI `python -m battery_sim.datasets.material_metadata --series <dir>`：
sample_id 唯一；每份都声明工艺；工艺**至少有一样不同**（全同 = 不是梯度）；
电极几何一致（否则"材料差异"与"电极差异"混在一起，结论只能退到
「当前电极工艺下的综合差异」）。

**④ 四份样品模板** `templates/commercial_graphite_ht/`（+ 数据集条目片段）

预填**设计决定**（编号 / 工艺条件 / 测量清单与角色 / 电极与电芯规格）；
**故意留空恰好 7 个只有人能填的实测量**：`source`、载量、厚度、面积、
`particle.d50_um`、对电极、电解液。留空而不是预填"看起来合理"的数，因为
预填值会安静地进入容量尺度换算，而 **D ∝ R²**：粒径错一倍 = D_s 差 4 倍。
实测：四份各报 **7 个错误**、系列级 **0 错误**（测试钉住）。

角色**预先登记**（做完不能改口径）：0.1C / 0.2C = identification；
0.5C / 1C / 2C = validation；**1C 是 Level 4 留出集**。
数据集条目 = 4 个样品 + 1 个 `_holdout_1C`（平台层 validation 门），
目录 `data/raw/graphite_ht/<SAMPLE>/`（`data/` 全在 gitignore 内）。

**⑤ 验收阶梯 L1–L4**（判据明确**不是** RMSE 低）
L1 数据进入（元数据错误 = 0）→ L2 模型复现（只**记录** RMSE 与残差形状，
不作判据）→ L3 参数辨识（五个判定词；`D_s` 只有 `identifiable` 才报数值，
`bounded` 只报界）→ L4 用 0.1C 辨识的参数**前向预测 1C**，参数一个都不许回改。

**⑥ 修掉一处会当场说谎的报告措辞**

`unmeasured_probes` 在**"测了但平台没有拟合通路"**时，原来输出
「本数据集没有 EIS 测量」—— 下一批数据带 EIS 进来时，这句话是**假的**。
现在它是明确的**第三种状态**：「EIS 已测，但平台没有从它拟合 k0 的通路」，
判定词仍是 `not_measured`（没有估计值就是没有），但理由指向**通路**而不是数据。
测试同步收紧：原来只查"理由里没有『缺』"，现在**禁止**出现"没有 EIS 测量"
且**要求**出现"通路"。

### G6.2a D_s(x) 表示接口门 — **接口 PASS / 判据 9/11**（2026-09-16）

完整报告 `docs/g6.2a_representation_interface.md`。
复现：`python scripts/graphite/g6_2a_representations.py`（**246 次仿真，45.0 s**）

三种形状（RMS 归一化：$\phi_0=1$、$\phi_1=\sqrt3(2x-1)$、$\phi_2=(1,-2,1)/\sqrt2$）
各扫 ±1 dex（0.05 dex 网格），两个窗口：`GITT-charge#t475` + 对照 `GITT-discharge#t120`。

| 判据 | 结果 |
|---|---|
| **A1 API 通**（callable 覆盖真的到达模型） | **PASS**（峰值 model-to-model RMSE 1.05–64.80 mV） |
| A1_order / N2_coverage | **t475 FAIL**（该窗口贴电压下限，G6.1c 已记录其 2/41 探针不可达）｜**t120 全过** |
| **A2 溯源通** | **PASS**（`run_metadata.json` 里 D_s 是 `{__callable__, __module__, __qualname__}` 描述符，来源含 shape/amplitude_dex/phi_rms） |
| **A3 报告通** | **PASS**（首次在真实产物上走到 `bounded` 分支） |
| N1 amp=0 与"不改参数"逐位相同 | **PASS**（三个形状） |

**跨阶段逐位复现（本轮最有分量的核对）**：`constant` 就是 $\phi_0=1$，由**另一条构造代码**
（`representations.shape_override`，不是 `replay_scan.build_multiplier_override`）产生，
却给出 `#t475` **0.0988** dex（= G6.1c）与 `#t120` **0.8966** dex（G6.1c 0.89663）
⇒ 新表示层与已发布的路等价，估计器只有一份。

**五个实测结果**：
1. 接口三项全过，且溯源是可复核的描述符而不是字符串；
2. 上一条逐位复现；
3. **哪个形状"看得见"是窗口的函数**：t475 → linear 63.48 mV（可见）/ three_region 0.90 mV（不可分辨）；
   t120 反过来 → 0.54 mV（不可分辨）/ 2.86 mV（可见）。同族于 G6.1c 的"方向是变量"，
   但这次是从**形状**侧独立测出的：**"更复杂的形状"不是普遍更优**。
4. **不可达探针点会把带宽量窄**：`cost` 对不可达返回 inf，`band_width` 丢弃这些点后把剩下的当相邻
   ⇒ `linear@t475`（10/41 不可达）的 0.0359 dex **只能是上限**。报告 JSON 用
   `bands_measured_with_unreachable_amps` 单独列出这些行 ⇒ **`N2` 不是形式主义**。
5. t120 上 `linear` 判定 **`bounded`**（1.9594 dex，右侧截断）——那条"one-sided sensitivity region"
   的规范措辞被报告生成器自动带上，**不许报点估计**。

**四条接口事实（写代码前不知道，全是实测）**：① pybamm 把函数型参数的实参以**符号**传入
（`Maximum(...)`），不是浮点数；② `pybamm.Heaviside` 在 26.8 **不存在**，且
`EqualHeaviside(left, right)` 在 `left <= right` 时返回 1（与直觉相反）；
③ 形状对**标量**必须返回 Python `float`，0 维 ndarray 会让 `symbol * 0d-array` 在域合并时崩；
④ 参考 $D_s$ 本身是 pybamm 符号（`ref(x,T)` 返回 `Multiplication`）⇒ 两个符号之间的 `==`
不是数值比较，测试必须 `.evaluate()` 取数或换成浮点 fixture。

**决策**：不进 3-region / smooth basis。回收石墨需要的是 $D_s$、$k_0$、$R_{ct}$、Q 这些**标量**，
而标量路径（`#t475`，B = 0.0988 dex）已经是可辨识的 ⇒ 下一步是 Phase 1/2 接真实样品数据。

**边界**：只验接口，不做辨识、不做优化、不拟合测量；只两个窗口、单电芯、26 °C、SPM；
数据集是公开 benchmark（`dlr_gitt`），**不是任何回收石墨样品**。

### G6.0 graphite 参数 provenance 审计 — **IN PROGRESS**（2026-09-16）

完整文档 `docs/g6.0_graphite_parameter_provenance.md`。
参数集 dump：`outputs/graphite/g6_0_parameter_set.json`（89 key，含 callable 源文件）
脚本：`scripts/graphite/dump_graphite_parameters.py`、`list_graphite_parameter_keys.py`

**两个结构性发现（都比单行数值重要）**：

**① graphite 参数挂在 `Positive electrode ...` 名下**（半电池把工作电极映射到 positive 槽）。
`configs/datasets.yaml` 已写明 `working_electrode: "positive"`；
`Negative electrode OCP [V] = 0.0` 是**锂金属对电极**。
→ **任何按名字取参数的脚本在这里都会取错。**

**② ⚠️ `Positive particle diffusivity` 是 CALLABLE 函数，不是标量。**

> **这对 G5 → G6 的迁移是决定性的**：G5 全链条辨识的是**标量** $D_s$，
> 而 graphite 的 $D_s = D_s(x)$ 是**化学计量数的函数**。
> **G6 的辨识问题不是"换数据集重跑"，而是"如何辨识函数值参数"。**
> 平台当前**无法表示函数型参数**（G5 阶段 $k_0$ 即因此不能进第一版向量）。
> **G6.2 之前必须先定义 $D_s(x)$ 的有限维表示。**

**关键当前值**：thickness 74 µm · porosity 0.329 · active frac 0.372 ·
**particle radius 13.7 µm** · $D_s(x)$ 函数 · OCP 函数 ·
Bruggeman(electrolyte) **1.6372789…**（非整数 → 拟合/推导）· Contact resistance **0**（假定）

**待办**：逐项回溯 ⚠️ 行为"实测/文献/拟合/假定"；
核对 `data/metadata.csv` 与参数集的 geometry/loading；
说明两套 OCP（Ecker2015 内置 vs 平台从 p-OCV 派生）的关系；
**定义 $D_s(x)$ 的有限维表示**。

### G5.5 测量 → 模型尺度映射 — **PASS ｜ FROZEN**（2026-09-16）

完整报告 `docs/g5.5_measurement_to_model_scale.md`。

**第一步（来源审计）已完成 —— 这一步不做任何优化，只查清数从哪来。**

| 项 | 结论 |
|---|---|
| 参数集 provenance | `ParameterValues("Chen2020")` **没有任何 citation/doi/source/notes 属性**；5.22 µm 是裸字面量 |
| 出处 | Chen et al., *JES* **167** (2020) 080534（开放获取），商用 21700 LGM50，正极 NMC 811 |
| **粒径怎么测** | **SEM 二维俯视图 + ImageJ 测量全部颗粒**，取**数量加权平均半径**，**假设球形**；**非**激光衍射；**未报告** D10/D50/D90 |
| **$D_s$ 怎么来** | **GITT（C/10 脉冲 2.5 min）+ Sand 方程** → 论文自己标为 **apparent**；论文值 **1.48e-15**，而 PyBaMM 里是 **4e-15**（**2.7× 差异，原因未查明**） |
| 交叉核对 | Chen2020 平均**半径** 5.22 µm → 平均**直径 10.44 µm** ≈ 你的 **D10 = 10.72 µm**（差 2.6 %） |

> **$10.44 \approx 10.72$ 是统计量的性质，不是发现** —— 数量加权平均直径天然落在小分位附近
> （按体积加权会把均值拉向 D50 一侧）。这解释了 G5.4 里 $D_{10}/2$ 为何"恰好"接近真值，
> 但**仍不支持**"$D_{10}$ 是正确的统计量"。

**这条审计解释了整条 G5 链的长脊**：

```text
R_p = 5.22 µm  ← SEM 图像分析（数量加权均值、假设球形、固定不随 SOC 变）
D_s = 4e-15    ← GITT + Sand 方程（apparent 值、假设单一粒径）
                 ↑ 两套互不相干的实验
τ_d = R_p²/D_s  ← 这个组合没有任何一个实验直接测过它
```

→ 电压曲线所约束的主要是 $\tau_d$，而 $\tau_d$ 是一个**由两套独立测量拼出来的派生量**
   （derived quantity），**不是任何实验直接给出的可观测量**。
   ⚠️ 初稿写"最没有实验依据的量"**过强，已更正** —— $R_p$ 与 $D_s$ 各自都有实验来源，
   缺的是它们的**组合**从未被独立测量或联合校验。
→ G5.4 里"独立 $R_p$ 约束能打破退化"，正因为它**唯一直接锚定了这个比值里的一个因子**。

**下一步（主体）**：先做**不确定度传递**而非立刻建映射 ——
$R_p$ 钉在真值与 $(1\pm5\%/10\%/20\%)$，测 $D_s$ 的不确定度，
产出**"粒径表征精度要求"曲线**。
**待确认（否则映射无从谈起）**：你手上 PSD 的**仪器**、**加权方式**、**颗粒定义**（primary / secondary / 复合）。

### G5.4 多协议辨识性 + 模型一致性 — **PASS ｜ FROZEN**（2026-09-16）

完整报告 `docs/g5.4_multi_protocol.md`。
可复现：`python scripts/identification/g5_4_multi_protocol.py`（约 1539 s）

**目标函数**：等权 per-protocol $J=\frac1K\sum_k\frac1{N_k}\sum_i[\Delta V]^2$
（**不是拼接 SSE** —— 实现为电压先除 $\sqrt{N_k}$ 再拼接，让 PyBOP 自带 cost 恰好等于 $K\cdot J$）。

**① Control**：P1/P2/P4 全部精确恢复真值，每协议残差 ~0.0000 mV ✓

**② A+B 多协议 —— 没有解决失配**：

| 协议集 | K | $D_s$ | $R_p$ | equal-weighted RMS |
|---|---|---|---|---|
| P1 (0.1C) | 1 | +1215.4 % | 20.000 µm（**撞界**） | 0.480 mV |
| P2 (+0.5C) | 2 | +1086.3 % | 19.010 µm | 2.431 mV |
| **P3 (+1C)** | 3 | **+1242.6 %** | 20.000 µm（**撞界**） | 6.257 mV |
| P4 (+1.5C) | 4 | +1363.7 % | 20.000 µm（**撞界**） | 25.975 mV |

**1→2→3→4 个协议，最优点在 +1086 %~+1364 % 之间来回，没有趋向真值的趋势。**
（Control 臂对照：四集全部 $|\Delta D_s|$ < 0.01 %，最差 per-protocol RMS 0.0018 mV。） 但暴露了模型不一致 ——
**联合最优下 per-protocol 残差随倍率单调上升、跨度 25 倍**：
`P4: C10 1.9027 / C2 7.7167 / 1C 19.5206 / 1.5C 47.4485 mV`。
且 **C10 自己的残差随协议数单调上升：0.4804 → 0.5718 → 0.6048 → 1.9027 mV** ——
联合拟合不断牺牲它去迁就新倍率，仍谁都满足不了。
→ **parameter inconsistency across protocols becomes a diagnostic of model-form error.**

**③ C 独立 $R_p$ 约束 —— 能，且决定性**（$R_p$ 用**注入常数覆盖**真正钉住）：

| 组 | 臂 | $R_p$ 钉在 | $D_s$ 偏差 | equal-weighted RMS |
|---|---|---|---|---|
| C_low | control | D10/2 = 5.36 µm | **+5.50 %** | — |
| C_mid | control | D50/2 = 8.79 µm | **+204.39 %** | — |
| **C_low** | **mismatch** | D10/2 | **+5.06 %** | 55.428 mV |
| **C_mid** | **mismatch** | D50/2 | **+182.60 %** | 46.499 mV |
| 自由 $R_p$ | mismatch | — | +1364.06 % | **25.975 mV** |

**$D_s$ 偏差从 +1364 % 降到 +5.06 %（270 倍）。**

> **但残差排序与精度排序完全相反**：
> 残差 `自由(26.0) < D50/2(46.5) < D10/2(55.4)`；精度 `D10/2(+5%) ≫ 自由(+1364%) > D50/2(+183%)`。
> **以残差最小为准会选中三种里最差的那一个**；而且 mismatch 臂里**钉错的 $R_p$ 残差反而更低** ——
> 残差不仅选不对，还会主动推向错的解读。
> （control 臂里残差**能**分辨：5.53e-07 vs 8.92e-05，差 160 倍 —— 同一诊断量在模型正确时有效、在模型错误时反号。）

**核算（`R_p` 能不能取 $D_{50}$）**：模型 $R_p$=5.22 µm，
**≈ D10/2 = 5.36 µm（1.03×）**，而不是 D50/2 = 8.79 µm（1.68×）。
→ 它是**有效扩散长度尺度**，不是几何均值半径。

**边界**：仍合成；**P3 未跑**（用 1→2→4 嵌套）；单失配方向；单电芯；
$R_p$ 上界自设（mismatch 最优撞界 → 真解可能在界外）；
**已封存（2026-09-16）**：补回 **P3**（`P1⊂P2⊂P3⊂P4` 完整），
**持久化改造完成** —— 各阶段只写自己的文件、互不覆盖：
`manifest.json` / `group_A_*.json` / `group_B_*.json` / `group_C_*.json` /
`runs/<arm>_<set>.json`（8 个 leaf fit）/ `summary.json`（从磁盘**重建**，自述 `groups_present` 与 `leaf_fits`）。
本次封存运行**验证了该改造**：group C 单独一次运行写入后，`summary.json` 报告 **3 个 group 全在 + 8 个 leaf fit**。
**scope 声明：本关不再扩倍率、不再加协议集。**

### G5.3 联合 $D_s$–$R_p$ 辨识几何 — **PASS**（2026-09-16）｜**放开第二参数不修复失配，只是把它藏起来**

完整报告 `docs/g5.3_joint_identifiability.md`。
可复现：`python scripts/identification/g5_3_joint_identifiability.py`（约 652 s）

**前置能力门**：`particle_radius` = 5.22e-6 m，被消费、±20 % 位移 2.4–39.7 mV ✓

**① Control 二维图（SPM→SPM）**：**四个倍率**的 argmin 都**精确落在真值**（分辨率 0.0107 dex）。
但谷是**脊不是碗**，而且**高倍率让它更狭长、更贴 iso-τ_d**：

| 倍率 | 伸长率 | 与 iso-τ_d 夹角 | profile 灵敏度（±0.05 dex） |
|---|---|---|---|
| 0.1C | 3.22 | 3.16° | ×3.447 |
| 0.5C | 3.25 | 1.96° | ×3.024 |
| 1C | **5.17** | **0.77°** | ×1.884 |
| **1.5C** | **11.01** | 1.09° | **×1.466** |

→ **"高倍率打破 $D_s$–$R_p$ 退化"= 否（情况 A），而且退化被强化 3.4 倍。**
→ **电压曲线主要约束 $\tau_d=R_p^2/D_s$。**

**② Mismatch（SPMe→SPM）**：

| 倍率 | $\theta=\{D_s\}$ RMS | $\theta=\{D_s,R_p\}$ RMS | 残差下降 | 双参数 $D_s$ | 双参数 $R_p$ | $\tau_d$ 变化 |
|---|---|---|---|---|---|---|
| 0.1C | 1.656 mV | **0.480 mV** | −91.6 % | +1215 % | +283 %（**撞界**） | +11.60 % |
| 0.5C | 7.011 mV | **3.389 mV** | −76.6 % | +1065 % | +261 % | +12.00 % |
| 1C | 33.020 mV | **13.104 mV** | −84.3 % | +1244 % | +283 %（**撞界**） | +9.20 % |
| 1.5C | 92.568 mV | **47.440 mV** | −73.7 % | +1364 % | +283 %（**撞界**） | **+0.28 %** |

**残差大幅下降，但 τ_d 几乎不动**，而 $\Delta z_D$ 与 $2\Delta z_R$ **几乎精确满足 iso-τ_d 条件**。
**1.5C 最干净：$\tau_d$ 只变 +0.28 %，而 $D_s$ 变 +1364 %、$R_p$ 变 +283 %** ——
即 $(D_s\times14.6, R_p\times3.83)$ 这一对组合，对电压曲线而言**几乎与真值不可区分**。
**1C 与 1.5C 的 $R_p$ 都精确停在同一个上界 `2.00000e-05`** → 该"解"是**边界产物**。

**残差大幅下降，但 τ_d 只变 +12 %**（13624 → 15204/15259 s），
而 $\Delta z_D=+1.12$ 与 $2\Delta z_R=+1.17$ **几乎精确满足 iso-τ_d 条件**。
→ **优化器沿 §1 里那条浅方向逃逸**：一个组合被确定、另一个自由漂移，参数彻底失去意义。

**③ Profile（补 G5.2 缺的证据，并更正其推断）**：以 profile 自身最小值为基准，
±0.05 dex 的 J 抬升 = 0.1C **×3.447** / 0.5C **×3.024** / 1C **×1.884** / 1.5C **×1.466**。
→ **$D_s$ 曲率随倍率单调变弱（弱 2.35 倍），但未塌陷**。
**G5.2 的"杠杆作用丧失"表述过强，已更正为 "sensitivity is reduced (~2.4×), not collapsed"。**
**教训：残差地板大只证明失配大，不证明目标函数平坦 —— 残差性质与曲率性质必须分别测量。**
（内部校验：单参数优化器偏差与 profile 最小值位置独立吻合：0.1C −25.0 % vs −0.10 dex 等。）

**边界**：仍合成；只测 0.1C/0.5C 两档（**1C/1.5C 见 G5.3.1/5.3.2**）；单失配方向；单电芯；
伸长率 3.2 属"中等脊"。$R_p$ 上界（20 µm）是本次自设，0.1C 解撞界说明真解可能在外。

**措辞（重要，不要写成"不可辨识"）**：本文结果**不支持** "structural non-identifiability"，
因为 §0 已实测**同一 $\tau_d$ 并不完全等价**（两端响应符号相反）。严谨表述：

> **Under single-rate voltage fitting, $D_s$ and $R_p$ exhibit strong practical
> correlation dominated by the diffusion timescale, while additional protocols
> are required to improve parameter separability.**

即 **practical identifiability limitation**，不是 structural non-identifiability。

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

**G6.1a 卡点已解除（2026-09-16）**：SINTEF 石墨线**没有任何扩散受限的真实协议** ——
p-ocv 是 C/50，`gitt`/`gitthold` 实为 C/50 CC–CV 且多通道交错。
唯一真实的脉冲数据是 **DLR LiGrHydra0b GITT**，已建 adapter 并纳入治理（**benchmark**）。
**这是数据受阻，不是能力受阻** —— 换数据源即解。
**另有一条常驻教训（已升级为平台概念）**：参数惰性有两个来源（**协议不激发** 与
**模型不在同一尺度**），两者看起来完全一样，**必须先把尺度对齐（Q_model == Q_measured）再谈协议**。
→ 2026-09-16 已实现为 **`governance/scale_alignment.py`（尺度对齐门）**，
在 protocol replay 入口**默认强制**，见上文独立小节。

**G6 当前的真实卡点（2026-09-16，G6.1c 双向之后）**：不是能力、不是数据量，
而是**这份记录里只有极少数激励能把 $D_s$ 定下来**。
476 个窗口（放电 239 + 充电 237）跑成地图：**放电侧 0 个合格**（75 % 在 $\pm1$ dex 内连 1 mV 都不动），
**充电侧 3 个合格**（$B$ = 0.099 / 0.134 / 0.137 dex），全在**最脱锂端**且脉冲高达 597–729 mV；
按"状态要分散"只留 **1 个窗口**。
**同状态配对（204 对）显示"方向"本身是变量**：同一个 $x_0\approx0.0053$，
放电脉冲 $B=0.350$、充电脉冲 $B=0.099$（**3.5×**），"只有一侧可测"的有 40 对。
⇒ 下一步是**激励设计**（悬崖区做双向脉冲 / 更长脉冲 / 多温度），而不是加基函数；
做 3-region 之前必须先测那 3 个窗口是否构成独立方向。
理由与数字见 `docs/g6.1c_excitation_map.md`。

---

## L4 验收与两项新 QC 门（2026-09-17 晚）

导师清单核过之后，判定「真正要动手」的是三件（细节：
`docs/chemistry_windows_and_gitt_qc.md` / `docs/l4_rate_prediction.md`）。
**平台科学核心（runner / evaluator / factory / registry / rates / paths）改动 = 0。**

### ① 体系锚定电压窗口

`battery_sim/datasets/chemistry_windows.py`（新增，纯规则）+ 接进
`user_tools/validate.py` 的两条检查码 `VOLTAGE_WINDOW_SYSTEM` /
`VOLTAGE_SYSTEM_RANGE`。原来只核「数据 vs 用户自填窗口」——填 `[0.005, 15]`
也 PASS；现在会与**该体系**的窗口对账（石墨半电池 0.005–1.5 V，硬界 0–2.5 V）。
没声明工作电极材料就 WARN 说明检查被跳过（**跳过 ≠ 通过**）。

### ② 脉冲协议 QC 分级

`protocol_type` 进 experiment 闭集；`SAMPLING_INTERVAL_GAP` 对脉冲协议升级为
**FAIL**；新增 4 条：`GITT_STRUCTURE` / `GITT_PULSE_DURATION`（实测中位脉冲时长
vs 声明，5 % 容差）/ `GITT_PULSE_UNIFORMITY`（std/median ≤ 0.10）/
`GITT_PULSE_RESOLUTION`（脉冲内部间隔 > 3× 中位即 FAIL）。依据：
D_s 由脉冲时长与 ΔV 算出。

### ③ L4 倍率预测验收

`python -m identification.rate_prediction`（新增）。四道门：角色门（辨识集不能当
留出集）/ 尺度门（模型 vs **电芯声明**容量，不是窗口电荷）/ 覆盖率门（< 80 % 记失败）/
初值接线门（起点差 > 30 mV 记失败）。合成倍率梯夹具
`examples/synthetic_rate_ladder/` 实测：

```text
真值参数（D_s ×0.35）          目标倍率 C1: RMSE 3.27 mV, 覆盖 100.0%  PASS
零拟合负对照（不做覆盖）        目标倍率 C1: RMSE 20.09 mV, 覆盖 100.0%  PASS（差 6×）
目标数据集声明成 identification  ->  角色门拒绝（PredictionProtocolError）
```

**首轮暴露并修掉的接线缺口（对真实石墨同样致命）**：GCD 路径
（`load_processed_discharge`）原先没挂 `attrs['initialisation']`，
于是半电池回放从参数集默认初值出发 —— 夹具实测起点 **1.453 V** vs 记录
**0.745 V**，整个 RMSE 被这 708 mV 的初值差吃掉，看上去像"模型差 60 mV"。
已在 `RecycledGraphiteAdapter` 里覆盖该方法挂上（与 sintef / dlr / birmingham
一致）。修前/修后同一夹具：**59.89 mV → 3.27 mV**。

### 本轮实证（可复跑）

```bash
python -m user_tools.import_dataset --package examples/half_cell_demo
# -> 13 项校验 / 严重 0 / 警告 3（新增的 WARN 是"体系窗口被跳过：缺声明"）/ 导入 PASS

python -m pytest -q
# -> 597 passed, 5 warnings, 119.66s
```

---

## 测试状态

```text
pytest:        597 passed, 5 warnings
failures:      0
duration:      119.66s
last run date: 2026-09-17  (提交前复跑)
command:       python -m pytest -q   (WSL, conda env pybamm)
```

**文档中的测试数已过期，勿引用**（2026-09-15 核对，2026-09-16 更新）：

| 文件 | 写的数 | 实际 |
|---|---|---|
| `README.md` | 293 | **504** |
| `HANDOFF.md` | 88 | **504** |

两个数字互不相同，且都与实际不符。已改为指向本文件，不再写死数字。
**引用测试数时只引用本文件的 597。**
（2026-09-16 的增量：329 → 356 是 G6.1a 的 28 项 `test_dlr_gitt.py`；
356 → 374 是尺度对齐门的 18 项 `test_scale_alignment.py`；
374 → 392 是 G6.1c 的 18 项 `test_recovery_stats.py`；
392 → **448** 是平台冻结包的 56 项：`test_dataset_template.py` +
`test_analysis_mode.py` + `test_parameter_report.py`；
448 → **466** 是 G6.2a 的 18 项 `test_representations.py`；
466 → **504** 是结构契约与 adapter 的 38 项：`test_material_structure.py`
+ `test_recycled_graphite.py`。
⚠️ **更正**：上一版把 504 写成"当前值"，但同一轮后来实测是 **517**
（`test_recycled_graphite.py` 在契约变更后又有增/改写），504 是过期数。
→ 517 + **32** = **549**：`test_material_processing.py`（20 项）+
`test_ht_templates.py`（12 项）。
→ 549 + **48** = **597**：`test_user_data_qc.py`（29 项：体系锚定电压窗 +
脉冲协议分级）+ `test_rate_prediction.py`（19 项：L4 验收的判据与措辞）。
本轮新增的三件见「L4 验收与两项新 QC 门」一节。）

---

## 已知限制

1. **`initial_state` 仍未实现，44.64 mV 缺口未闭合。**
   当前 48.36 mV 是公共接口的诚实结果。闭合需要把初值策略放进 request
   （与"顶层只有四个字段"冲突），属独立设计任务。

2. **推送通道已恢复（2026-09-16）。** 远端 `main` 与 `feat/parameter-identification`
   都指向同一条链，33 个 commit 的积压已清零 ——
   **导师现在 clone 就能看到**覆盖 API、G6.1a 的协议层、尺度对齐门、G6.1b-1、
   G6.1c 与整个平台冻结包。
   ⚠️ **判断推送状态必须用 `git ls-remote --heads origin`**：
   本机的 `refs/remotes/origin/main` 会被安全软件删掉/不更新
   （显示成旧的 `ee45d62`），信它会得出"没推上去"的错误结论。

3. **跑一次 pipeline 会改动被 git 跟踪的产物文件。**
   `outputs/` 有 418 个文件在版本控制内。一次 baseline 会改 6 个文件。
   实测差异内容：`timestamp`、`runtime_s`，以及 schema 新增的
   `parameter_overrides_requested` / `parameter_overrides_applied` / `parameter_override_sources`。

   ⚠️ **另一半事实（2026-09-16 补）**：`outputs/fitting/`、`outputs/validation/`、
   `outputs/audit/`、`outputs/sensitivity/` 被 `.gitignore` **刻意排除**
   （注释写的是"只留冻结的小数值表"）⇒ **G5/G6 的全部辨识产物（逐窗口 CSV、report.json）
   从未进版本控制**。文档里引用的每个数字因此只能靠**重跑命令**复核
   （G6.2a 246 次仿真 45 s；G6.1c 10009 次仿真 25 min），不能靠 clone 后的文件。
   这是**已知且接受**的取舍（每个 gate 都能单命令复现），代价是复核要花算力。
   要改成随版本发布，需要单独决定 `.gitignore` 策略与体积预算。
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
> **G5 已推进到 5.3**，主线判据是"参数在噪声、模型失配、不同 protocol 下
> 是否仍具唯一性与可迁移性"，而不是"优化器能不能找到真值"。
>
> 目前最重要的**科学**结论（G5.2–G5.4 是同一条链的四步）：
>
> ```text
> G5.2  错误模型下，"错"的参数优于真值；低倍率残差只有 1.66 mV、看不出异常
> G5.3  曲线主要只约束 τ_d = R_p²/D_s；优化器沿那条浅方向逃逸（τ_d 仅变 12 %，D_s 变 12 倍）
>      高倍率不但不打破退化，反而强化 3.4 倍（伸长率 3.2 → 11.0）
> G5.4  四协议联合：最优点几乎不动，但暴露 rate-dependent 残差（模型不一致）
>      独立 R_p 测量：D_s 偏差 +1364 % → +5.06 %（270 倍）
>      然而残差排序与精度排序相反 —— 以残差最小为准会选中最差的答案
> ```
>
> 即：
> $$\text{parameter fit} \neqq \text{parameter identification} \neqq \text{physical transferability}$$
> $$\text{parameters become identifiable} \neqq \text{they became meaningful}$$
> $$\text{residual minimum} \neqq \text{parameter truth}$$
>
> **G6 补上的第四条（标量 → 函数值参数）**：
>
> ```text
> G6.1a   函数型 D_s(x) 的数值活性依赖协议（无激励读数逐位不变；GITT 展开 8–29 mV）
> G6.1b-1 但"活性"不给出可辨识性：1 mV 带上，平台区要 0.9 dex、陡峭区 0.35 dex，
>         而且六个 (窗口,真值) 组合全部单侧 —— D_s 只有下界，没有上界
>         （τ_d 的上界，不是 D_s 的估计值）
>         幅度与带宽不成比例（活性比 3.56× / 带宽改善只有 2.56×）
> ```
>
> $$\text{parameter activity} \neqq \text{parameter identifiability}$$
>
> 以及一条**流程**结论（两次踩同一个坑换来）：
> $$\text{scale mismatch} \equiv \text{parameter inertness} \ \text{（输出里不可区分）}$$
> ⇒ Dataset → Geometry audit → **Capacity alignment** → Protocol excitation → Parameter inference
>
**口径提醒**：G5.0–5.3 **全部是合成数据**。
> 换掉的是模型形式与噪声，**不是数据来源**；真实实验辨识是 G5.4，尚未开始。
> **G6.1b-1 同样是合成数据**（观测就是同一模型在真值处的输出，**inverse crime**），
> 所以它的可辨识带宽是**理想条件下的最好情况**。
