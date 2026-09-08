# v0.3 Step 21 — CALCE INR18650-20R 参数集审计

日期：2026-09-08　|　验证环境：WSL pybamm env，PyBaMM 26.8.0.0。
候选集的容量/电压窗口数值全部实测自 `pybamm.ParameterValues`，非凭记忆。

## 1. 实验电池事实（Samsung SDI INR 18650-20R）

| 项 | 值 | 来源 |
|---|---|---|
| 制造商 | Samsung SDI | CALCE 数据集页 |
| 标称容量 | 2.0 Ah | 官方规格 |
| 正极 | NMC（LiNiMnCoO2） | 官方规格 |
| 负极 | 石墨 | 官方规格 |
| 几何 | 圆柱 18650（Ø18 × 65 mm） | 官方规格 |
| 电压窗口 | 2.5 – 4.2 V | 官方规格；**与数据一致**（审计实测 2.40–4.20 V） |
| 实测电流尺度 | 充 +1 A（0.5C）/ +2 A（1C），放电峰 −4 A（2C） | Step 18 审计 |
| 测试温度 | 25 °C（archive 命名 `SP2_25C_*`；文件内无温度列） | Step 18 审计 |

## 2. PyBaMM 26.8 候选参数集审计

`pybamm.parameter_sets` 中 LIB 全集（实测）：Ai2020, Chayambuka2022, Chen2020,
Chen2020_composite, Ecker2015, Ecker2015_graphite_halfcell, Marquis2019,
Mohtat2020, NCA_Kim2011, OKane2022, ORegan2022, Prada2013, Ramadass2004,
Sulzer2019, Xu2019（+ ECM/MSMR example）。逐个按化学体系筛：

| 参数集 | 正极 / 负极 | 容量 / 电压窗口（实测） | 判级 |
|---|---|---|---|
| **Chen2020** | NMC811 / 石墨（LG M50 软包） | 5.0 Ah，2.5–4.2 V（实测） | **B: compatible_surrogate** |
| Mohtat2020 | NMC811 / 石墨-SiOx（通用） | 5.0 Ah，上限 4.2 V（实测）；负极含 SiOx，20R 负极为纯石墨 | B−，非首选 |
| ORegan2022 | NMC811 / 石墨-SiOx（LG M50L） | 5.0 Ah，上限 4.4 V（实测，与 20R 窗口不符） | B−/C |
| Ecker2015 | Li(Ni0.4Co0.6)O2 / 石墨（Kokam SLPB 软包） | — | C（正极亚化学体系不同；v0.2 已定性） |
| Ramadass2004 | LiCoO2 / 石墨 | — | C（化学体系不匹配） |
| Prada2013 | LFP / 石墨 | — | C（化学体系不匹配） |
| NCA_Kim2011 | NCA / 石墨 | — | C（正极化学体系不同） |
| 其余（Ai2020/OKane2022/Xu2019/Marquis2019/Sulzer2019/MSMR/ECM…） | 非本电池目标体系或半电池/示例集 | — | 不参与 |

**结论：Chen2020 = B 级（compatible_surrogate），v0.3 默认参数集。**

理由：
- 化学体系匹配：NMC 正极 + 石墨负极，与 20R 相同家族（NMC811 vs 20R 的
  NMC，镍比例不同但不属于跨体系）。
- 电压窗口逐位一致：2.5–4.2 V（`pybamm.ParameterValues("Chen2020")` 实测），
  正是 20R 的规格窗口——replay 中电压事件可比。
- 已被平台充分验证（v0.1/v0.2 主参数集），不引入新依赖。

**明确限制（必须随结果输出）**：
- Chen2020 标称 5.0 Ah，20R 是 2.0 Ah → 同样 4 A 电流在模型里只有 0.8C，
  电化学时间尺度被拉长；这不是拟合误差，是 surrogate 的结构性偏差。
- 未对 20R 做任何参数拟合（v0.3 禁止 fitting）。
- 因此所有 CALCE 20R 结果都是 **unfitted surrogate baseline**，
  RMSE 只作为软件 regression reference，不作为物理验证结论。

## 3. 与 v0.2 三层级 schema 的对接

`configs/datasets.yaml` 的 `calce_20r.parameter_match` 块：
`level: compatible_surrogate, grade: B, parameter_set: Chen2020,
fitted_to_dataset: false`。run_metadata 的 `parameter_match` 由
`adapter.get_metadata()` 自动携带（机制 v0.2 已有，零改动）。

初始 SOC 说明：每个窗口的初始 SOC 取自 CALCE 文件名 SOC 标签（50/80%），
属低置信度 source 标签（无法从文件内独立验证），在 provenance 与
run_metadata 中显式标注 `initial_soc_source: calce_filename_SOC_label,
initial_soc_confidence: low`。
