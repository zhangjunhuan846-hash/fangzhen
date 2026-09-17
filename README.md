# 🔋 Battery Data–Model Integration Framework

<p align="center">

<strong>面向电池研究的数据—模型串联仿真平台</strong>

<br>

A reproducible framework connecting battery experimental data, electrochemical models and simulation analysis.

</p>


---

## 🔒 已冻结版本 `v0.1.0-platform`（2026-09-16）

**状态**：平台开发阶段结束，进入「冻结 → 接真实材料」。
**唯一可信状态页**：[`STATUS.md`](STATUS.md)（版本、判据、测试数、已知限制）。
**Tag**：`v0.1.0-platform`。**备份**：`../_git_bundles/fangzhen_platform_freeze_pushed.bundle`。

冻结的含义是：**接一份新数据不再是开发任务**。

```
实验数据 → dataset adapter → protocol 解析 → scale alignment → PyBaMM replay
        → identifiability 判定 → 参数报告
```

- 接新数据：读 [`docs/adding_a_dataset.md`](docs/adding_a_dataset.md)（4 步 + 必答的 10 个格式问题），
  自检 `python -m battery_sim.datasets.template --check <dataset_id>`
- 出报告：`python -m identification.parameter_report --windows <逐窗口表> ...`
- 真实材料分析必须用 `analysis_mode="material"`（synthetic truth 会被代码拒绝）
- **尺度对齐是所有参数结论的前提**：`docs/scale_alignment_gate.md`（Q_model == Q_measured）
- 回收石墨（数据未到位也能自检契约）：`python -m battery_sim.datasets.recycled_graphite --validate`
- 冻结产物样例（少量：summary + 报告 + 图）：`examples/frozen_results/`
- 设计与历史决策：`docs/architecture/`

---

## 📌 Overview

电池研究中，实验数据、物理模型和分析流程通常相互独立，导致：

- 实验数据格式不统一；
- 数据难以直接进入电化学模型；
- 模型比较和参数分析流程复杂；
- 模拟结果缺少统一追踪机制。

本项目基于 **PyBaMM** 构建数据—模型串联框架，实现：

```

Experimental Data
↓
Data Standardization
↓
Electrochemical Models
↓
Automated Simulation
↓
Evaluation & Analysis
↓
Sensitivity Exploration

```

用于支持电池模型验证、参数分析以及后续智能化设计。


---

# 🏗️ Architecture

```
             Battery Data

                  │

                  ▼

      ┌───────────────────┐
      │ Dataset Adapter   │
      │ 数据标准化接口     │
      └───────────────────┘

                  │

                  ▼

      ┌───────────────────┐
      │  PyBaMM Models    │
      │ SPM/SPMe/DFN      │
      └───────────────────┘

                  │

                  ▼

      ┌───────────────────┐
      │ Simulation Engine │
      │ 自动化仿真流程     │
      └───────────────────┘

                  │

                  ▼

      ┌───────────────────┐
      │ Evaluation        │
      │ Error Analysis    │
      └───────────────────┘

                  │

                  ▼

      ┌───────────────────┐
      │ Sensitivity       │
      │ Parameter Analysis│
      └───────────────────┘
```

---

# ✨ Features

## 1. Multi-source Battery Data

支持：

- 恒流充放电数据；
- 电压-时间曲线；
- 电流-容量数据；
- 不同采样频率实验数据。

通过数据适配模块，实现不同实验数据统一进入模型。


---

## 2. Electrochemical Model Support

基于 PyBaMM：

| Model | Description |
|---|---|
| SPM | 快速单粒子模型 |
| SPMe | 考虑电解液影响 |
| DFN | 完整电化学模型 |


支持：

- 模型自动调用；
- 参数统一管理；
- 不同模型性能比较。


---

## 3. Automated Simulation Pipeline

统一入口：

```bash
# 一键运行（推荐）：YAML 配置 → 读取数据 → 选参 → 仿真 → 评价 → 保存
python run_pipeline.py --config configs/example.yaml

# 或命令行形式
python run_pipeline.py baseline --dataset chen2020 --model SPMe --cell 02
```

支持：

| Mode         | Function  |
| ------------ | --------- |
| reproduction | 实验/文献结果复现 |
| benchmark    | 模型性能比较    |
| baseline     | 标准仿真      |
| sensitivity  | 参数敏感性分析   |

---

## 4. Simulation Evaluation

自动计算：

* Voltage RMSE；
* MAE；
* Capacity error；
* Time alignment。

输出：

* 模拟曲线；
* 评价指标；
* 运行记录。

---

## 5. Sensitivity Analysis

分析：

* 固相扩散系数；
* 反应速率；
* 电极参数；
* 结构参数。

用于：

* 关键参数识别；
* 模型优化；
* 实验设计。

---

# 📂 Project Structure

```
.
├── run_pipeline.py        # Main entry（支持 --config 一键运行）
├── battery_sim/           # Core simulation modules (frozen v0.4)
├── configs/               # datasets / chemistry / models / sensitivity 注册表
├── examples/              # 最小真实数据案例（half_cell_demo）
├── user_tools/            # 自助入口：实验 CSV → 校验 → zero-fit baseline
├── outputs/               # Simulation results
├── external/              # Vendored upstream parameter-set repo (BSD-3)
├── STATUS.md              # **唯一可信状态页**（门控表 / 测试数 / 已知限制）
├── tests/                 # Regression tests (see STATUS.md for the current gate)
└── README.md
```

---

# 🔬 Reproducibility

每次运行自动保存：

```
run_metadata.json
```

记录：

* Dataset
* Model
* Parameters
* Runtime environment
* Results

保证模拟过程可追溯。

---

# ✅ Current Status

> 完整门控表、测试数、已知限制见 **`STATUS.md`**。下面这份清单只表示"曾经完成过"，
> 不表示"当前仍然通过" —— 两者可能不一致，以 `STATUS.md` 为准。

* [x] Dataset standardization
* [x] PyBaMM integration
* [x] SPM/SPMe/DFN support
* [x] One-shot YAML run (`--config`)
* [x] Explicit chemistry registry
* [x] Automated simulation pipeline
* [x] Benchmark workflow
* [x] Baseline simulation
* [x] Sensitivity analysis
* [x] Result tracking
* [x] Regression testing (count in `STATUS.md`)
* [x] Experimental-CSV self-service entry (`user_tools/` + example case)
* [x] Graphite half-cell line, Phase A: SINTEF graphite R2032 → zero-fit SPM chain
* [x] Graphite Phase A.5: geometry-aware zero-fit (measured electrode geometry)
* [x] Graphite Phase B0: experiment-derived two-branch OCP (pseudo-OCP)
* [x] Graphite Phase B0.5: capacity-consistent eps_am (Q_model == measured Q_ref)
* [x] Graphite Phase B0.6: high-fidelity OCP v2 (full-resolution, branch-aware sampling)
* [x] Graphite Phase B1: GITT segmentation + apparent D_s(SOC) (consistency-checked)
* [x] Graphite Phase B2: D_s diagnostics + constant-D sensitivity (when is it a valid model input)
* [x] Graphite Phase B0.7: initial-state / window-start correction (lith 44.7 -> 1.6 mV)
* [x] Graphite Phase B1.5: GITT pulse overpotential budget (why the D_s is biased)
* [x] Graphite Phase B1.6: drift-corrected re-inversion of the whole D_s(SOC) table
      (fit-form line closed; corrected table still below the reference, not adopted)

---

# 🚀 Future Development

## Phase I

Experimental data

↓

Battery simulation

## Phase II

Literature data extraction

↓

Model parameter generation

## Phase III

AI-assisted battery research workflow

```
Literature
     ↓
AI Agent
     ↓
Simulation
     ↓
Optimization
     ↓
Experiment
```

---

# 🎯 Project Goal

构建一个面向电池数字化研究的数据—模型集成基础设施：

**Battery Data → Physics Model → Simulation → Analysis → Design**

为电池模型验证、材料研究和智能化实验设计提供基础平台。

---

# 🚀 Quick Start

**先跑这个。** `examples/half_cell_demo/` 是自包含案例，clone 后即可运行，
不需要 13 GB 的 `data/` 原始库：实验 CSV → 12 项导入校验 → zero-fit DFN baseline。

```bash
# 1) 环境（详见 HANDOFF.md：WSL Ubuntu + conda + pip install -r requirements.txt）
conda activate pybamm

# 2) 自包含案例：导入校验 + zero-fit baseline（预期结果已固化在 result/）
python -m user_tools.import_dataset --package examples/half_cell_demo
python -m user_tools.run_baseline    --package examples/half_cell_demo --models DFN

# 3) 平台本体（以下命令需要先准备 data/ 原始库；该目录不在仓库内，见 HANDOFF.md）
python run_pipeline.py --list-datasets
python run_pipeline.py --config configs/example.yaml
```

化学体系显式注册表：`configs/chemistry.yaml` —— 化学体系 → 正负极/电解液/
电池形式/参数集 + 溯源等级（A-exact / B-compatible_surrogate），可直接对接
文献抽取输出（如 `NMC811||graphite`）。

石墨半电池（Phase A）：`python run_pipeline.py baseline --dataset sintef_graphite --model SPM`
—— SINTEF graphite R2032 半电池 p-OCV 脱锂支的 zero-fit replay。
注意其 RMSE 由参考参数集与目标电芯的**尺度失配**主导（面积 55.8×），
只作通路验证，见 `docs/graphite_platform_integration_plan.md`。

> 措辞约定：surrogate 参数集结果为**代理基线**，不称 validation；
> baseline 为 **zero-fit**，不称 fitting。
