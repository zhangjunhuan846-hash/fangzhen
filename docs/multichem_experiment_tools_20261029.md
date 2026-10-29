# 锂钠实验分析工具

工作站侧栏“锂钠实验分析”支持选择工具、下载合成示例 CSV、填写 JSON 配置、上传用户 CSV 并运行。结果 JSON、原 CSV、配置、SHA-256 和所属方案记录在本地 jobs 中，可在该页面历史区下载。示例是合成输入，不是材料测试结果。CSV 大小上限 20 MB；既有预处理器另有 20 万行限制。

| 功能 | 实际实现 | 范围 |
|---|---|---|
| 数据体检 | 调用原有列映射、时间和时间戳差异检查；相邻差分 MAD 筛查 | 不自动修复；正常脉冲可能被标记。可按原有配置明确列名和单位 |
| OSBAD 统计异常 | 实际调用 OSBAD 1.7.0 的 sd、mad、iqr、zscore、mod_zscore 统计检测器 | 对同时间段的相邻差分工作；不是完整基准或安全诊断 |
| 硬碳数据预检 | 检查来源组、批次和六项常见字段缺失 | CSV 必须由用户准备并核对来源；用“描述符与机器学习”做分组训练。上限增加到 1000 个有标签样本 |
| 电解液配方预检 | 检查盐、浓度及单一溶剂比例 | 多组分守恒约束和下一批选点通过已有“多目标科研闭环”配置；未自动检验配方兼容性 |
| Arrhenius | 本地线性最小二乘，拟合 ln(电导) 或 ln(1/R) 与 1/T | 输出斜率、R²、斜率标准误及表观活化能；MADAP 方法启发，未调用 MADAP 软件 |
| 温度与滞回电路 | 用户给定充放电 OCV 和 R0 的 SOC×温度完整表，线性插值、安时积分及单状态滞回；支持至多3个固定参数RC支路和可选R0在线RLS | 正电流放电，超表拒绝；温度作为输入而非预测，RC参数固定。不是论文完整模型；RLS应在新工况独立验证 |
| CV 曲线比较 | 原始多曲线电流极值 | 不判定峰机理 |
| ElectroKitty CV 模拟 | 实际调用 ElectroKitty 1.0.11.6 模拟 a*=b* 表面反应 | 单反应演示，无拟合、溶液扩散或完整电池模型；参数必须自行标定 |
| 原位对齐 | 本地或 ixdat 0.4.0 时间序列插值 | 手动偏移、重叠区间内插值；不自动估计偏移、光谱拟合或仪器控制 |
| 部分充电 | 积分电量和可选 SOC 基线 | 需要初始 SOC、容量和充电符号；未训练 SOC/SOH 网络 |

## 可选依赖

本地基础功能使用 Windows Python 标准库。上游工具需要 WSL Ubuntu 的现有 `/home/zjh/miniforge3/envs/pybamm/bin/python`。双击 `安装锂钠实验分析扩展.bat`，在 `/home/zjh/.local/share/fangzhen/multichem-20261029` 建立独立 venv（继承现有科学计算依赖）；不会在 PyBaMM 环境里直接安装这些新包。安装 ixdat 和 ElectroKitty，同时仅安装 OSBAD 包自身以使用其统计模块，不安装完整 OSBAD 的神经网络或 CUDA 依赖。其他机器需调整上述路径。

## 本次验证

使用 [SINTEF 2026 数据集版本 0.7.1](https://zenodo.org/records/18986774) 的 Digatron HPPC CSV，13,275,587 字节、47,926 个有效记录；原表头时间单位为秒，文件实际时间为毫秒。体检将持续时间与时间戳变化比较，提示约 1000 倍单位差异。差分筛查标出 968 个待审位置，不能当成 968 个确认错误或真实故障。该版本页面提示存在后续版本。

独立 WSL 环境实际执行 ElectroKitty 100 点表面反应模拟；ixdat 对 0 和 2 秒的信号在 1 秒插值得到 15；OSBAD IQR 测试识别合成突变。均为软件运行检查，不是钠电材料验证。

## 参考来源

- [硬碳论文代码与数据](https://github.com/erweixi/Targeted-Screened-Hard-Carbon)：该仓库页面未发现明确许可证；未随本软件分发。其数据需增加可靠的来源分组后才能进行按文献留出验证。
- [钠电温度与滞回 ECM](https://doi.org/10.1016/j.jpowsour.2026.240262)：目前实现独立的简化模型，并非论文复现。
- [钠电电解液主动学习](https://doi.org/10.1039/d6dd00149a)：现有闭环可供用户输入数据并构造约束，未复现论文模型。
- [OSBAD](https://github.com/meichinpang/osbad)、[MADAP](https://github.com/fuzhanrahmanian/MADAP)、[ElectroKitty](https://github.com/RedrumKid/ElectroKitty)、[ixdat](https://github.com/ixdat/ixdat)。
- [钠电部分充电估计](https://arxiv.org/abs/2504.00393)：当前实现安时积分基线，未复现论文网络；需要独立电芯标注数据。

当前平台原有 SPM/SPMe/DFN 工厂仍为锂电；本页面不把锂电参数静默用于钠电，也不提供已验证的钠电 DFN。

## 使用在线 R0 更新

在温度与滞回电路配置中，用户可在已有 `rc_branches` 和 `ocv_table` 之外添加：

```json
"rls": {
  "forgetting_factor": 0.995,
  "initial_covariance": 1.0,
  "max_delta_ohm": 0.005
}
```

每行必须有实测 `voltage_V`。`max_delta_ohm` 必须小于表中最小 R0，以保证调整后的电阻为正。当前点先用已有估计预测，再用该点实测更新后续点；因此同一序列的误差不是独立验证。数值协方差有上限，参数应根据电芯数据与未参与更新的工况验证，以上数字仅为软件示例。
