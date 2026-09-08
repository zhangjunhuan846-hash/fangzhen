# Platform v0.4 Freeze Manifest — 平台冻结清单

日期：2026-09-08（v0.4 终版语义修正后）　|　状态：**冻结**（FROZEN）

本文件固定 Phase A1（Cross-dataset Residual Atlas）所依赖的平台状态。
科学分析阶段禁止修改 `battery_sim/` 下 adapter / runner / evaluator /
model factory 的科学计算逻辑；所有分析代码放在 `analysis/`。

## 1. Datasets & parameter sets（frozen）

| dataset_id   | chemistry       | parameter_set | parameter_match                | protocol          | cells / windows |
|---|---|---|---|---|---|
| chen2020     | NMC_Graphite    | Chen2020      | A / exact (fitted_to_dataset: true)  | CC (reproduction + baseline) | 02 / C10, C2, 1C, 1p5C |
| calce_cs2    | LCO_Graphite    | Ramadass2004  | B / compatible_surrogate       | CC (0p5C, 1C)     | 33, 35 |
| calce_20r    | NMC_Graphite    | Chen2020      | B / compatible_surrogate       | DST/FUDS/US06 × {50,80}SOC | SP20-2 (id "2") |
| calce_a123   | LFP_Graphite    | Prada2013     | B / compatible_surrogate       | DST/FUDS/US06     | A1-007, A1-008 |

## 2. Frozen golden baselines（zero-regression gate, all byte-identical）

| Run | RMSE |
|---|---|
| Chen2020 reproduction SPMe cell02 | 82.33 / 115.81 / 70.02 / 46.84 mV (C10/C2/1C/1p5C, RMSE(Q)) |
| CALCE CS2_33 baseline | 200.365 mV (0p5C) |
| CALCE CS2_35 baseline | 269.929 mV (1C) |
| CALCE 20R baseline (6 windows) | 152.79 / 275.57 / 151.06 / 271.04 / 172.33 / 287.59 mV |
| CALCE A123 baseline (6 windows, 静置末端温度语义) | 199.69 / 198.12 / 176.56 (007) · 211.58 / 226.70 / 209.03 (008) mV |

## 3. Regression tests

- **74 tests passed**（55 v0.2 + 9 v0.3 + 10 v0.4），0 failed。
- 命令：`python -m pytest tests -q`（WSL pybamm env）。

## 4. Semantic freezes（v0.4 final wording）

- A123 等温回放环境 = **动态段前静置末端实测电芯温度**（固定），
  `ambient_temperature_source: assumed_from_preprofile_rest_cell_temperature`；
  实测 T_cell,exp(t) 仅为 validation target，绝不驱动模型；**等温假设未被验证**。
- A123 `initial_soc=0.995` = **stable surrogate initialization**
  （`purpose`，`fitted_to_voltage: false`），非实测 SOC，禁止写成 "99.5%"。
- RMSE 敏感性观察仅限局部范围：Prada2013 surrogate + 三个动态工况 +
  0.98–0.995 SOC 区间；**禁止**延伸为"该数据集不适合做正极参数辨识"。

## 5. Environment snapshot（WSL conda env `pybamm`，2026-09-08）

```text
python       3.11.16
pybamm       26.8.0.0
pybammsolvers 0.9.1
casadi       3.7.2
numpy        2.3.5
scipy        1.17.1
pandas       3.0.5
matplotlib   3.11.1
xlrd         2.0.2
```

## 6. Phase A1 冻结范围

- 分析代码位于 `analysis/`，输出位于 `outputs/analysis/residual_atlas/`。
- 本阶段禁止：fitting、optimization、SHAP、ML、Sobol、thermal fitting、
  parameter correction；对 runner/evaluator/model factory 的一切修改。
- 冻结平台代码：`battery_sim/`、`configs/datasets.yaml`、`run_pipeline.py`。
