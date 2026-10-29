# EIS / BMS 多工况与跨电芯验证（2026-10-29）

## 新增软件能力

- EIS 网格支持 `interpolation: "linear"`（默认）或 `"log_invT"`：对正 RC 参数取对数后在 SOC 和绝对温度倒数上插值。相同实现供频域留出测试、桥接初始参数及 Thevenin 电芯模型使用；不允许超出已测网格。
- `ecm_bms` 支持 `filter_rc_mode: "estimated_grid"`：EKF / UKF 各自使用上一步自身 SOC 估计和输入温度查询网格；一步内 RC 固定，EKF 不包含参数随 SOC 变化的导数。默认 `fixed` 保留旧行为。实测需每行 `temperature_C`，除非明确等温；合成测试的温度传感器无噪声。初始估计或输入温度超出网格会报错。
- 工作站需要先创建通过谱误差、Lin-KK 和辨识质量筛查的同电芯 EIS 网格任务，再在同一方案选择该任务、核对电芯，设置相同来源类型，才能将它接到 SOC 回放。筛查通过不等同于独立脉冲或安全验证。
- 下面的跨电芯缩放校准目前只在可复现实验脚本中，不会绕过同电芯桥接约束，也没有自动部署到 BMS。

## 原始数据

1. Stanford Molicel P42A：[公开记录](https://doi.org/10.17605/OSF.IO/9CEAV)、[数据论文](https://doi.org/10.1038/s41597-025-05725-y)。下载 `phase_2/EIS` 全部 107 个 XLSX，记录 OSF SHA-256 并验证；一条电芯工况不完整。论文描述 EIS 标称 SOC 为 20/50/80%，温度设定点为 5/25/40°C；本验证不把设定点当作实际温度轨迹。文件名所示测量日期跨 2024 和 2025，跨日期的状态变化可能影响结果。
2. [Zenodo 54 个 NMC811 电芯](https://doi.org/10.5281/zenodo.15422339)：54 个独立电芯在 30% SOC 的 EIS；下载全部 CSV 并验证 Zenodo MD5，另存本地 SHA-256。它不提供本实验所需的多 SOC / 多温度覆盖。
3. 同一 Stanford 项目额外下载了 A37 25°C 的原始脉冲文件 `20240422_A37_HCGT.xlsx`，OSF SHA-256 `c1771ef34127b8b2df73218d907e86cf08eab6bfc92a246148adf2edf01f7a98`。尚未完成该文件与 2025 年 EIS 状态对应、脉冲 SOC 基准及 OCV 标定，因此本次不将其计入时域验证。

下载清单 `data/external/eis_public_20261029/manifest.json` 包含文件、来源和校验值。数据及脚本可用原始文件复现；数据复用请遵循各原始发布页面的条款。

## 跨电芯实验

统一在 0.5–1000 Hz 的 40 个对数频点上以实测频谱对数频率内插，指标为每谱复阻抗模值归一化误差 RMS。完整数据电芯中，A2/A4/A6/A8/A9/A11/A12 用于训练，A15/A19 用于开发选择，A21/A37 最终测试，A13 因工况不完整排除。每个训练电芯仅使用 SOC 20/80%、5/40°C 四个角点。开发集比较复数直接插值、1RC、2RC、参数/温度不同插值以及是否单谱缩放；测试电芯在选择后保留。

使用单谱缩放时，从被测电芯 20% SOC / 25°C 的一条独立 EIS 算一个标量，其余 8 个谱计分；不缩放的基线也排除同一条谱，保持评分工况一致。开发集平均误差选出的 `2rc_log_invT + 单谱缩放`：开发 9.95%，测试 10.10%，测试最差单谱 19.05%。基础 `2rc + 线性插值 + 无标定`：开发 10.84%，测试 13.33%，测试最差 40.39%。对同一可用的 `log_invT` 而不做缩放，测试平均为 12.30%。被选模型在 A21 和 A37 的均值分别为 8.48% 和 11.73%；按标称温度 5/25/40°C 分别为 12.84% / 8.80% / 8.24%。这只是两个测试电芯和一次划分，且开发集仅两个电芯，不能宣称普适改进。

Zenodo 依电芯编号固定 40/7/7 划分为训练/开发/测试，开发集选出的训练平均复谱在测试电芯上平均误差 2.50%；1RC 和 2RC 分别为 3.11% 和 2.81%。该结果只对应单 SOC、同批 NMC811 电芯，不能解释成多温度或时域 SOC 精度。

## 同电芯网格实测与桥接筛查

另用 A21 / A37 各自的四个角点实测原始频点拟合 2RC，另外五个 SOC / 温度谱作为留出；本实验不使用跨电芯缩放。留出谱平均相对误差：

| 电芯 | 线性参数插值 | log_invT 插值 | Lin-KK 筛查 | 可桥接 |
|---|---:|---:|---:|---|
| A21 | 6.24% | 5.22% | 4 / 9 谱 | 否 |
| A37 | 6.27% | 4.88% | 9 / 9 谱 | 是，频域筛查通过 |

Lin-KK 与模型残差在限定频带内计算，是研究质量筛查；不能证明电路唯一性或确认时域表现。SOC、温度、跨电芯分析均属于频域验证，不是 SOC 预测 RMSE。

两电芯分别生成了可直接上传工作站 EIS 网格入口的 `eis_input.csv`；选择公开数据来源并填写上述 DOI，`rc_branches` 设为 2，频率设置为 0.5–1000 Hz。A37 可选择 `log_invT` 得到本次通过筛查的网格。随后须完整填写同电芯的电热参数、OCV 和回放 CSV，才能进行有意义的 BMS 回放。

## 复现

在项目根目录：

```text
python user_tools/fetch_eis_public_20261029.py
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.validate_eis_public_transfer
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.validate_stanford_same_cell_grid
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m pytest tests/test_engineering_eis_grid.py tests/test_engineering.py -q
```

结果和每谱分数位于 `outputs/eis_bms_validation/public_transfer_20261029/`，同电芯实际平台网格拟合和筛查明细位于 `outputs/eis_bms_validation/stanford_same_cell_20261029/`。后续优先工作是建立同日期、同电芯、独立容量/OCV 参考及多个温度的脉冲与动态工况，比较固定 RC 和估计 SOC 查表两种滤波器，并以未见电芯和工况评价电压与 SOC；仅凭本次 EIS 不应报告 BMS 精度提升。
