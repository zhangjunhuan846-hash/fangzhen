# v0.4 Step 30 — PyBaMM 26.8 LFP 参数集审计（A123）

日期：2026-09-08　|　验证环境：WSL pybamm env，PyBaMM 26.8.0.0。
所有候选实测 `pybamm.ParameterValues(...)` + SPM/SPMe/DFN build，非凭记忆。

## 1. 目标电芯（Step 28/29 审计结论）

A123 Systems APR18650M1A：LFP 正极 / 石墨负极，18650，1.1 Ah，
2.0–3.6 V（数据实测一致），测试温度 25 °C（实测电芯温度 26.5–28.4 °C）。

## 2. 候选实测（全集枚举后逐个验证）

| 参数集 | 正极 OCP / 负极 OCP（实测） | 容量 / 窗口（实测） | SPM/SPMe/DFN build | 判级 |
|---|---|---|---|---|
| **Prada2013** | `LFP_ocp_Afshar2017` / `graphite_LGM50_ocp_Chen2020` | 2.3 Ah，**2.0–3.6 V** | 全 OK | **B: compatible_surrogate** |
| Chayambuka2022 | NVPF / 硬碳（**钠离子**，NVPF_diffusivity/HC_ocp） | 0.003 Ah，2.0–4.2 V | 全 OK（但非 LIB） | 排除（非锂离子体系） |
| Ai2020 | LiCoO2（`lico2_ocp_Ai2020`）/ 石墨 | 2.28 Ah，3.0–4.2 V | 全 OK | 排除（LCO，窗口不符） |
| Chen2020 / Mohtat2020 / ORegan2022 | NMC 系 | 2.5/4.2–4.4 V | — | 排除（非 LFP） |
| Ecker2015 / Ramadass2004 | LNO / LCO | — | — | 排除（非 LFP） |
| Prada2013 之外剩余（Marquis2019/Xu2019/Sulzer2019/OKane2022/NCA_Kim2011/MSMR/ECM 等） | 非 LFP 目标体系或示例/半电池 | — | — | 排除 |

**PyBaMM 26.8 中唯一锂离子 LFP/石墨参数集 = Prada2013**（ fitted to 2.3 Ah
LFP/石墨电芯；正极 OCP 用 Afshar2017 平滑拟合，能表达 LFP 平台特征）。

## 3. 判级：Prada2013 = B（compatible_surrogate）

支持点：
- 化学体系匹配：LFP 正极 + 石墨负极（正极 OCP 即 LFP）。
- **电压窗口逐位一致：2.0–3.6 V**（实测 ParameterValues），与 A123 规格和
  数据完全重合——replay 电压事件可比性最好的一个 surrogate。
- LFP 平台特征由 OCP 函数承载，不是人为改出来的。

明确的限制（随结果输出）：
- 容量 2.3 vs 1.1 Ah、电极几何（软包 0.6×0.3 m vs 18650）不同 → 同样 3.85 A
  峰值放电在模型里只有 1.67C；结构性偏差，非拟合误差。
- `fitted_to_dataset: false`，禁止任何 fitting。
- 未实证 Prada2013 的具体电芯与 APR18650M1A 电极参数是否接近——不猜测，
  一律按 surrogate 对待。

**注意判级不随"名字里有 LFP"自动升高**：Prada2013 在 v0.2 对 CALCE CS2
（LCO）判 C 级，在本数据集（LFP）判 B 级——层级绑定的是"参数集 vs 实验电芯"
的化学匹配，不是参数集本身的优劣。

## 4. config 对接

`configs/datasets.yaml` 的 `calce_a123.parameter_match`：
`level: compatible_surrogate, grade: B, parameter_set: Prada2013,
fitted_to_dataset: false`。由 `adapter.get_metadata()` 自动带入
run_metadata（v0.2 机制，零改动）。

v0.4 不做 parameter fitting；RMSE 只作 software regression reference。
