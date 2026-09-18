# Example: half-cell CSV → platform → zero-fit baseline

真实实验 CSV 的最小可复现案例（公开数据：Birmingham NCM920305‖Li
半电池，Cover5 协议窗口，~0.22 C）。整个流程不依赖 13 GB 的
`data/` 原始库，clone 后即可运行。

## 这是什么

演示导师需求的核心链路——**实验数据自动进入模型**：

```
raw CSV → 导入/校验(12项) → canonical 格式 → 参数集自动匹配
        → PyBaMM DFN (zero-fit) → 指标 + 图 + 溯源清单
```

## 怎么跑（两条命令）

```bash
# 1) 导入并校验（生成 validation_report.html / dataset_manifest.json）
python -m user_tools.import_dataset --package examples/half_cell_demo

# 2) zero-fit baseline（DFN；也可 --models SPMe DFN）
python -m user_tools.run_baseline --package examples/half_cell_demo --models DFN
```

WSL 环境先 `source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm`，
或直接双击包内的「导入并检查数据.bat」「运行仿真.bat」（Windows）。

## 预期结果（已随仓库固化在 result/）

| 文件 | 内容 |
|---|---|
| `result/baseline_metrics.csv` | RMSE(t)=104.29 mV，MAE=34.26 mV（zero-fit，未拟合） |
| `result/curve.png` | 仿真 vs 实验 电压-时间对齐曲线 |
| `result/metrics.csv` | 平台标准指标表（run 级） |
| `result/validation_report.html` | 13 项校验报告（严重 0，警告 3） |
| `result/dataset_manifest.json` | 完整溯源：参数集 Jackowska2025_2mAh_cm2、匹配等级、zero-fit 声明 |

## 换成自己的实验数据

复制本目录，替换 `raw/*.csv`，按 `dataset_info.xlsx` 填写
（容量、电压窗口、正负极、温度等 16 个字段），其余流程完全相同。
参数集匹配规则见 `docs/师姐使用说明.md`：
LFP 全电池→Prada2013，NMC 全电池→Chen2020，NMC 半电池→
Jackowska2025（仅 2.0±0.2 mAh/cm²）；无匹配参数集时工具会明确报
SIMULATION=NOT AVAILABLE，**绝不偷换参数集**。

## 措辞红线

- 本案例是 **zero-fit baseline**（不称 fitting）；
- 参数集为设计匹配的 **surrogate**（不称 validation）；
- 与专用 adapter 数值等价（不称 byte-identical）。
