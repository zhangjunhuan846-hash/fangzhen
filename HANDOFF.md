# HANDOFF · 平台交接与从零安装指南

> **不含原始实验数据**：`data/`（约 13 GB 公开数据集库）与 `logs/` 不在仓库内。
> **但仓库里有历史结果**：`outputs/`（约 430 个文件：评价指标、逐窗口表、报告、图）
> 与 `examples/frozen_results/` 都随包附上，**clone 后不跑任何仿真也能直接翻阅结论**。
> 附带的两个数据文件是 `user_dataset_template/raw/demo_birmingham_cover5.csv` 与
> `examples/half_cell_demo/raw/demo_birmingham_cover5.csv`，来自公开的
> Birmingham NCM920305 数据集（Zenodo），仅用于演示。

---

## 1. 这是什么

一套基于 PyBaMM 的电池仿真平台（v0.4，冻结版）：

- 对公开电池数据集跑 **zero-fit 基线**（SPM / SPMe / DFN 三模型，电压对齐 RMSE）；
- 给实验人员用的**免编程入口**：CSV/XLSX 放进模板 → 填一张 Excel → 双击两个按钮
  → 自动出数据质检报告 + 基线仿真结果；
- 全程**不做拟合**；每次运行自动记录参数来源（provenance）。

**诚实边界**（引用结果时请注意）：
- 参数集匹配分 A/B/C 级；CALCE 等 surrogate 数据集的结果只叫"一致性对比"，不叫"验证"；
- 自助入口的参数支持表：LFP 全电池 → Prada2013；NMC 全电池 → Chen2020；
  NMC 正半电池 → Jackowska2025（仅当面容量 2±0.2 mAh/cm²）；
  其它材料 → 仿真显示 NOT AVAILABLE（不会偷偷换参数集）。

---

## 2. 从零安装（新 Windows 机器，约 20–40 分钟）

仿真在 **WSL Ubuntu** 里跑（Windows Python 装不了 PyBaMM）。需要一次性的环境搭建：

### 第 1 步：安装 WSL2 + Ubuntu
管理员 PowerShell 里执行，然后重启：
```powershell
wsl --install -d Ubuntu
```

### 第 2 步：装 miniforge（WSL 内）
```bash
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -b -p ~/miniforge3
~/miniforge3/bin/conda init bash
# 关掉终端重开
```

### 第 3 步：建 pybamm 环境并装依赖
```bash
conda create -n pybamm python=3.11 -y
conda activate pybamm
cd /path/to/解压后的项目目录      # 例如 /mnt/c/Users/you/Desktop/battery_platform
pip install -r requirements.txt
```

### 第 4 步：验证
```bash
python run_pipeline.py --list-datasets     # 应列出 5 个数据集
```

### 第 5 步：双击演示（免编程）
打开 `user_dataset_template\` 文件夹（**在 Windows 资源管理器里**）：
1. 双击 `导入并检查数据.bat` → 结束后打开
   `outputs\user_datasets\demo_birmingham_cover5\validation_report.html`（网页质检报告）；
2. 双击 `运行仿真.bat` → 结束后看
   `outputs\user_datasets\demo_birmingham_cover5\baseline_metrics.csv`
   （RMSE ≈ 104 mV 为正常，zero-fit 基线）。

两条 BAT 均要求：WSL 发行版名为 `Ubuntu`、miniforge 装在 `~/miniforge3`、环境名 `pybamm`。

---

## 3. 换成自己的数据

把你的 CSV/XLSX 放进 `user_dataset_template/raw/`，照着
`docs/师姐使用说明.md`（两页，六个步骤）填 `dataset_info.xlsx`，再双击两个 BAT。
平台**不猜**任何东西：列名、单位、电流符号、材料体系都要你在 Excel 里显式声明。

---

## 4. 包内目录速览

| 目录 | 内容 |
|---|---|
| `run_pipeline.py` | 命令行入口（baseline / benchmark / reproduction / sensitivity） |
| `battery_sim/` | 平台核心（v0.4 冻结，勿改科学逻辑） |
| `configs/` | 数据集 / 模型 / 敏感性配置 |
| `user_tools/` + `user_dataset_template/` | 免编程自助入口 |
| `analysis/` `scripts/` `docs/` | 科学分析脚本、阶段脚本与报告 |
| `STATUS.md` | **唯一可信状态页**：门控表 / 测试数 / 已知限制。与本文档冲突时以它为准 |
| `tests/` | 回归测试（**需要完整数据目录才能跑**，数据不在本包内）。当前项数见 `STATUS.md`，勿引用本文档里的历史数字 |
| `external/Jackowska-2025-JPS/` | 公开的 Jackowska 半电池参数集代码（第三方仓库快照，commit 9f3b526） |

不在仓库内：`data/`（约 13 GB 公开数据集库）、`logs/`、`.git/`（clone 自带）。
**在仓库内**：`outputs/`（约 430 个历史结果文件）、`examples/`、`templates/`、`docs/`。

### 4.1 clone 之后先做什么（**已实测，2026-09-18**）

```bash
# ① 看结论，不需要数据、不需要跑仿真
ls outputs/analysis            # G5/G6 的可辨识性地图、L4 倍率预测报告、各项审计
ls examples/frozen_results     # 冻结产物样例（报告 + 图，各自带 README）

# ② 跑一个能跑的端到端示例（自包含，不需要 data/）
python -m user_tools.import_dataset --package examples/half_cell_demo
python -m user_tools.run_baseline   --package examples/half_cell_demo --models DFN
# 实测输出：13 项校验 / 严重 0 / 警告 3 / 导入 PASS / DFN baseline RMSE(t) ≈ 104 mV
```

⚠️ **`python -m pytest -q` 在 clone 里不会全绿 —— 这是预期的，不是代码坏了。**
实测（全新 clone，无 `data/`）：

```text
44 failed, 495 passed, 4 skipped, 70 errors
```

`failed` 与 `errors` **全部**是 `FileNotFoundError`，指向 `data/...`
（DLR / SINTEF / Chen2020 / CALCE / Birmingham 的原始文件）。
`STATUS.md` 里的 613 passed 是**带 `data/` 的完整环境**下的数字。
要全绿请先按 §2 准备 `data/`；**只用 clone 复现结论，走 ① 与 ② 即可。**

---

## 5. 引用与许可

- PyBaMM：开源（BSD-3）。
- Birmingham NCM920305 数据与 Jackowska2025 参数集：Jackowska et al., *J. Power Sources*
  2025（公开 Zenodo/GitHub）；demo CSV 即其公开数据子集。
- 其余数据集（Chen2020 / CALCE CS2 / 20R / A123）均为公开文献数据集，本包未附带。
