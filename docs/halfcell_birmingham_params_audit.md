# Half-cell Pilot H0 — H2: 作者 PyBaMM 参数集审计（Jackowska-2025-JPS）

- 日期：2026-09-08
- 仓库：`external/Jackowska-2025-JPS/`（`Battery-Intelligence-Lab/Jackowska-2025-JPS`，depth 1，只读；**未 pip install**，未改动 pybamm env）
- 配套数据：`data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw/`
- 审计脚本：`scripts/halfcell_birmingham/h2_identity_check.py`

## 1. 版本/依赖约束（downgrade 风险评估）

`pyproject.toml` 锁定作者复现环境：**PyBaMM==25.8.0**、pybammsolvers==0.3.1、pybop==25.6、
casadi==3.6.7、**numpy==1.26.4**、jax 0.5.3、scipy 1.16.2、salib 1.5.1 等。

- 我们的环境：**PyBaMM 26.8.0.0** / pybammsolvers 0.9.1 / casadi 3.7.2 / numpy 2.3.5 / PyBOP 26.3。
- **结论：该 pyproject 的依赖与本环境冲突（25.8 vs 26.8；numpy 1.26 vs 2.3.5；PyBOP 25.6 vs 26.3），
  严禁把仓库 pip install 进现有 env（会 downgrade/破坏冻结的仿真环境）。**
- 本阶段及后续一律**直接 import 模块**（`sys.path` 指到仓库目录，复用 `Jackowska2025.py` 的函数），
  不注册 entry-point、不安装包。H3 专门验证该方案在 PyBaMM 26.8 下是否成立。

## 2. 参数集注册机制与加载路径

- 包通过 entry-point group `pybamm_parameter_sets` 暴露两套参数：
  `Jackowska2025_2mAh_cm2 = "Jackowska2025:get_parameter_values_2mAh_cm2"`（4mAh 同理）。
- `Jackowska2025.py` 内 `get_parameter_values("2mAh_cm2")` 返回**原始 dict**（`chemistry: lithium_ion`
  + 覆写参数 + 函数型参数 OCP/D(c_s)/exchange-current/electrolyte 输运）。dict 里 `"chemistry": "lithium_ion"`
  会被 PyBaMM 当作"基于默认锂离子基础参数集 + 本 dict 覆写"来处理 → 缺省参数自动补齐。
- **等价加载（免安装）**：`pybamm.ParameterValues(Jackowska2025.get_parameter_values_2mAh_cm2())`
  与 `pybamm.ParameterValues("Jackowska2025_2mAh_cm2")` 数据同源。H3 将验证 PyBaMM 26.8 下该等价性。

## 3. 2mAh_cm2 参数集关键内容（与实验的对应关系）

| 项目 | 值 | 与实验核验 |
|---|---|---|
| 电极几何 | width=height=√π·0.0148/2 m（等价 disc d=14.8 mm）→ **A=1.7204e-4 m²=1.72 cm²** | 实验 1C=3.44 mA ÷ 2 mAh cm⁻² = 1.72 cm² ✅ **完全一致** |
| Nominal cell capacity | 0.003112 Ah | 与实验名义 3.44 mAh **不一致（~10.5%）**；作者回放时以实验电流驱动，此名义值仅作"Current function"默认，H0 复现实验电流时不受影响，但需在 metadata 中注明 |
| Current function [A] | 0.003112（默认 1C） | 同上，H0 会覆写为实验电流 |
| Positive electrode thickness | 3.25e-5 m；porosity 0.259；active vol frac 0.661；Brug(elyte) 1.90 | — |
| c_max | 49225 mol/m³；R_p 1.88e-6 m | — |
| OCP | `ocp_discharge.csv`（2mAh_cm2/results）线性插值 | 由 pOCV 处理（figure_1） |
| D_s(sto) | `diffusivity_discharge.csv` 插值 ×"Diffusivity scaling factor"（published=1.0） | GITT 导出（figure_2/3） |
| k0 / Ea | 1.037e-6 / 56410 | 由作者拟合 |
| Contact resistance | **22.4 Ω**（published） | 作者用 1C 放电前 120 s 拟合（figure_5_prep） |
| cutoffs | lower 2.5 V / upper 4.2 V | 实验放电下限 2.5 V、充电上限 4.2 V ✅ |
| Initial c_e / c_s | 1000 / **5e3 mol/m³（默认值）** | ⚠️ 见 §5 |
| 温度 | Ambient/Reference 298.15 K | 实验恒温 298.15 K ✅ |
| Li counter | 来自 Xu2019（i0(Li)=f(c_e,c_Li)；σ=1.0776e7 S/m；厚 100 µm；OCP=0 V） | — |
| 电解液 | Landesfeind2019 EC:EMC(3:7) 输运系数 | — |

模型 options（作者 `run_model.py`/figure 脚本一致）：
`{"working electrode": "positive", "surface form": "differential", "contact resistance": "true"}`。

## 4. matched 数据链路的数值验证（关键证据）

作者 figure_5.py 对每个倍率**回放实验电流**做 DFN 半电池放电，并逐行存
`results/<rate>_discharge.csv`（Time/Current/Discharge capacity/Voltage/**Absolute error [V]**），
其中 error = |V_exp − V_sim|。将该结果与我们下载的原始 `RateCapability_*` 文件**按行比对**：

| 文件对 | drop_duplicates 后行数（我们=作者） | 偏差诊断 |
|---|---|---|
| Cover10 ↔ C_10_discharge | 924 = 924 | med 0.025 mV / p95 0.047 / max 0.051 mV |
| Cover5 ↔ C_5_discharge | 679 = 679 | med 0.025 mV |
| Cover2 ↔ C_2_discharge | 554 = 554 | med 0.023 mV |
| 1C ↔ 1C_discharge | 527 = 527 | med 0.025 mV |
| 2C ↔ 2C_discharge | 490 = 490 | med 0.024 mV |

即：**我们下载的 5 个 rate 文件与作者存盘 CSV 所基于的实验数据逐行同源**（偏差 ≤0.06 mV，
属浮点/存储舍入）。作者 figure_5/6 正是用同名同构文件（`RateCapability_<rate>_2mAhcm^2_NCM920305.csv`，
本地下载名把 `^2` 写作 `_2`）验证模型。

→ **parameter_match 拟判级：level=exact（matched half-cell），grade=A**
（实验电极 = 参数化所用电极；几何/电流/温度/cutoff 全部自洽）。仓库不含实验 CSV 原件
（README 指向 Birmingham Research Portal），但 §4 的逐行核验已构成充分同源性证据。

## 5. 接线进平台前必须处理的科学细节（H7 决策输入）

1. **初始浓度不可用 published 默认 5e3 mol/m³**（sto≈0.10 → 起点 ~4.3 V 以上，与 4.19 V 不符）。
   作者做法：`soc_init = inverse_OCP(V0_rest)`，`c_s_init = soc_init·c_max`（V0=各文件首行静置 OCV，
   C/10: 4.1935 → soc≈0.31）。H7 adapter/runner 必须复刻该映射（不依赖 PyBOP，自行插值反解）。
2. **驱动方式**：回放实验电流（`I_model = +|I_exp|`，mA→A、放电为正），逐倍率单独初始化。
3. **published scaling=1.0 vs 作者逐倍率拟合 scaling（C/10:1.16 … 2C:12.26）**：论文最终发布参数集的
   D 缩放为 1.0，而 results/*_discharge.csv 是对应各倍率拟合后的最优解 → **H0 首跑用 as-published，
   预期与作者存盘最优曲线有差异（尤其高倍率），记录即可，不拟合。**
4. **采样差异**：实验时间轴绝对秒、切换瞬态 2 ms、稳态 60 s → 半电池 time-aligned 比较与 full-cell
   平台同逻辑即可，但窗口=纯 CC（无 CV），初始/末尾静置剔除。
5. 方向：PyBaMM 半电池"放电"（V 下降、NCM 嵌锂）在平台 canonical 里 = 放电正电流，与作者
   `dataset.Current = −I_exp_mA·1e-3`（实验放电为负）等价。

## 6. H3 兼容性风险清单（在 26.8 下逐项验证）

- `pybamm.parameters.process_1D_data` 是否仍存在（Jackowska2025.py import 期即执行）；
- `pybamm.Interpolant(x,y,sto,name=,interpolator="linear")` 签名；
- `ParameterValues(dict_with_chemistry)` 基础参数补齐路径；
- 半电池 options `working electrode/surface form/contact resistance` 在 26.8 的合法取值；
- Li-metal counter 相关键名是否仍被模型接受（"Exchange-current density for lithium metal electrode…"）；
- DFN/SPMe 各自 build + 短 CC solve 通过；solver（IDAKLUSolver/缺省）可用。

## 7. 结论

- 不产生 downgrade：**不安装**该包到 pybamm env，走 direct-import。
- matched（A 级）证据链**已建立**：几何 ↔ 电流、温度、cutoff、逐行数据同源、作者明确用本数据做
  参数化+验证（figure_5/6 + run_model.py）。
- 进入 H3：平台外 half-cell preflight（DFN/SPMe × `Jackowska2025_2mAh_cm2` @ PyBaMM 26.8）。
