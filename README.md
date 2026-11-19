# 🔋 Fangzhen · 电池数据—模型研究工作站

<p align="center">
  <strong>让实验记录、物理仿真、诊断分析与下一轮实验建议接在同一条可追溯的研究链上。</strong><br>
  Battery data → model → simulation → evidence → experiment
</p>

<p align="center">
  <a href="#项目能做什么">项目能力</a> ·
  <a href="#研究流程">研究流程</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#项目路线图">路线图</a> ·
  <a href="STATUS.md">验收状态</a>
</p>

> **当前状态：持续开发的电池仿真与研究工作站。** 平台把电化学仿真、EIS 分析、BMS 状态估计与充电控制的软件实验放在同一工作流中；`v0.1.0-platform` 为早期冻结标签。公开数据回放、合成测试和实物验证是不同证据等级，具体条件以各案例报告为准。

平台面向锂离子与钠离子电池研究，可从实验数据出发进行模型构建、参数辨识和独立工况比较；同时提供材料性能预测、实验方案优化及可导出的分析报告。部分能力依赖可选软件环境与外部数据，实际可运行范围应以安装环境和案例输入为准。

### 近期工作：EIS 与 BMS

- **电芯模型与状态估计：** 支持等效电路的电压回放和库仑计数、EKF 等状态估计；公开数据案例分别记录开环电压和使用电压反馈后的估计结果。
- **EIS 与 HPPC：** 对阻抗谱进行筛查与电路拟合，比较 HPPC 单独辨识、EIS 初始化及联合辨识；结果包括参数、窗口指标、逐点轨迹和报告。EIS 进入时域模型前仍需检查采集条件与参数适用范围。
- **公开数据案例：** Stanford W8 后续动态记录和 W5 逐电芯标定案例使用冻结的 HPPC 模型进行开环回放；CALB 60129 的 EIS 对照属于回顾性探索，当前未显示稳定的 EIS 增量收益。[案例说明](docs/stanford_frozen_delivery_20261029.md) · [CALB 对照](docs/eis_hppc_incremental_validation_20261029.md) · [诊断记录](docs/eis_mpc_diagnostics_20261029.md)
- **充电控制：** 具备 MPC 和电芯模型的仿真闭环，以及合成条件下的 CC–CV 对照；失配条件下的 SOC 估计和拖尾仍需改进，尚未完成实物充电或硬件在环验证。
- **钠电与材料研究：** 提供钠离子电池模型、硬碳性能预测和多目标优化的研究入口；实际材料和不同电芯的预测能力仍需对应实验数据与独立验证。[钠电说明](docs/sodium_dfn_hardcarbon_soh_20261029.md)

已知边界：Stanford W8/W9 的 EIS 尚未通过当前桥接筛查；模型尚未完成统一的低温、跨电芯与真实设备验收。项目不把单个数据集上的结果视为对所有电芯的保证。

本轮增加商用Panasonic PF单体的0/10/25°C参数表、上一循环容量/阻抗更新、增广EKF，以及更新参数→MPC→虚拟CAN。7条新评分工况的逐记录平均电压RMSE为61.31→37.55mV；10段老化历史回归为147.99→42.19mV。EIS全谱严格筛查12/14通过，12项软件故障保护用例通过。最差温度RMSE仍为5.44°C，实物设备尚未连接。[本轮结果和剩余差距](docs/adaptive_pf_v0314_20261029.md)；[四项目、寿命基线与v0.3.13历史验证](docs/frontier_commercial_validation_v0313_20261029.md)。

## 项目能做什么

| 研究环节 | 已有能力 | 关键约束 |
| --- | --- | --- |
| **实验数据** | 数据集适配、协议与单位核对；本地工作站的方案、样品、工艺、表征、极片与半电池记录；Excel/CSV 导入和版本归档 | 原始数据、来源和测试条件必须由研究者提供，软件不补造缺失实测值 |
| **电化学仿真** | 基于 PyBaMM 的 SPM、SPMe、DFN 回放；公开案例、参数敏感性和固定窗口比较 | 尺度、几何、初态和协议需要先核对；低误差不等于参数可辨识或跨材料有效 |
| **电池工程仿真** | 电热ECM、SOX CC/EKF/UKF/增广EKF、MPC、电池包、寿命/故障基线、PyProBE、虚拟CAN和12种选点入口；MOBO-OSD、rMFBO、CAMO、BatteryLife；PF跨温度参数表与上一循环更新、保护逻辑SIL | 同一单体新工况与老化回归分别计分；低温热模型、跨电芯、实际仪器/BMS联调仍待补齐；[本轮结果与差距](docs/adaptive_pf_v0314_20261029.md) |
| **EIS诊断** | 阻抗谱导入、单位冗余核对、含/不含低频串联电容的Lin-KK、独立SVD复算、1RC/2RC拟合、叠图与结果下载 | 原始全谱保留，2条谱阶数诊断与5个幅值字段异常点待查；用于BMS前需要SOC/温度与脉冲验证 |
| **仿真诊断 Agent** | 在声明范围内探索扩散系数与交换电流密度倍率；记录每轮候选、失败原因和曲线；支持规则策略与可选兼容模型 API | Agent 只提出候选，物理任务与数据用途检查仍由平台执行；目前没有真实材料前瞻验证 |
| **描述符与实验闭环** | 分组验证、有限候选模型建议、多目标探索、待实验记录与实验反馈 | 公开/合成回放是方法验收，建议必须经新的独立实验检验 |
| **环境与经济** | 用户工艺清单、Brightway 前景 GWP 计算、成本核算和来源留档；独立的 EverBatt 社区迁移参考案例 | 按声明边界和功能单位筛选；尚非完整背景数据库 LCA 或资本现金流 TEA |

工作站默认监听本机 `127.0.0.1`，研究记录保存在 `data/`（该目录不进 Git）。物理任务需要配置好的 WSL/PyBaMM 环境；Windows 打包程序也不是跨电脑零依赖安装包。具体版本说明见 [工作站文档](docs/workbench_v038.md)、[Agent 接入说明](docs/battery_agent_adaptation.md)和[环境与经济评价](docs/workbench_v036.md)。

## 研究流程

数据能否进入模型、模型输出能否支持结论，在流程里是两道不同的关。诊断或 Agent 发现问题时回到数据与实验设计，而不是直接把最低误差写成验证结论。

![FANGZHEN 电池研究闭环：数据输入、治理、PyBaMM 仿真、证据评估、诊断 Agent 与下一轮实验计划；环境和经济评价为独立清单分支](figures/research-loop-illustrated.png)

[查看高清原图](figures/research-loop-illustrated.png) · [可编辑的 Mermaid 流程图](figures/research-workflow.md) · [Mermaid 源码](figures/research-workflow.mmd)

图中的“下一轮实验”带时钟，表示待开展的计划。**公开数据回放**检验软件通路，**参数诊断**发现模型和数据哪里不一致，**独立实验**才检验结论能否迁移到新样品。碳足迹与成本使用另一套明确的工艺清单，不能与不同功能单位的参考结果混算。

## 快速开始

### 1 · 从仓库自包含案例开始

`examples/half_cell_demo/` 可以在没有本地 `data/` 原始库的 clone 中运行。先按 [HANDOFF.md](HANDOFF.md) 配好 WSL Ubuntu 的 `pybamm` 环境，再执行：

```bash
python -m user_tools.import_dataset --package examples/half_cell_demo
python -m user_tools.run_baseline --package examples/half_cell_demo --models DFN
```

这会走完实验 CSV 导入校验与 zero-fit DFN 基线。完整数据集列表及 YAML 流水线需要另行准备本地数据：

```bash
python run_pipeline.py --list-datasets
python run_pipeline.py --config configs/example.yaml
```

仓库附带三套逐循环钠电容量表。完整测试集中的部分用例还需要另行准备的原始数据，所需实验环境见[状态说明](STATUS.md)。

### 2 · 打开本地研究工作站

在已配置项目依赖的 Windows 电脑上，双击 `启动科研工作站.bat`；它优先启动当前工作区的源码，Python 环境不可用时会尝试本机已有的打包版。也可以直接执行：

```powershell
python -m user_tools.research_workbench
```

工作站自动打开本机浏览器。Windows 打包命令是 `./user_tools/build_workbench.ps1`；生成的 EXE 留在本机 `outputs/`，不纳入 GitHub 源码仓库。工作站的物理/ML 任务仍需可访问项目的 WSL 环境，Excel 导出及环境经济分析还需各自的本机依赖，详见[工作站说明](docs/workbench_v03.md)和[环境与经济说明](docs/workbench_v036.md)。

工程仿真和 EIS 功能还需按需配置 `requirements-engineering.txt`、`requirements-eis.txt` 所列依赖；Windows 可从 `安装工程仿真扩展.bat` 进入安装流程。不同引擎使用隔离环境，具体要求和固定版本见[工程集成说明](docs/engineering_integrations_v0312_20261029.md)。公开数据与本地运行时清单不随仓库发布，需要依来源说明自行准备。Stanford OSF 若要求 view-only 参数，通过本机环境变量 `STANFORD_OSF_VIEW_ONLY` 提供，勿提交访问凭据。

在“容量衰退预测”中可直接选择随仓库提供的 BatteryLife、NIMS 或 NFM 容量数据，切换算法，查看 80%、90% 或 95% 的逐圈预测区间，并导出上下限 CSV。三个基础算法使用 Python 标准库。要复现示例图中的二次多项式预测，在启动工作站的环境中运行 `python -m pip install numpy`。平台也支持导入自己的 CSV 和注册预测算法。[钠电数据、示例与接入说明](docs/sodium_capacity.md)

在“仿真诊断与参数探索”中可直接用规则策略。若使用可选模型服务，展开“模型API地址与端口”，填写基础地址（例如 `http://localhost:11434/v1`）、模型名和可选密钥，保存后检查接口。配置写入本机忽略文件 `data/agent_llm.local.json`；界面检查 `/models`，实际建议任务从 WSL 调用 `/chat/completions`，两者需分别保证可达。详见 [Agent 接入说明](docs/battery_agent_adaptation.md)。

v0.3.11 新增了 EIS 谱诊断与 RC 参数拟合。可用 [合成演示谱](examples/eis_rc_demo/README.md) 检查软件通路；[GitHub 接入选择与操作说明](docs/github_battery_integrations_20261029.md)说明本轮交付及后续 thevenin、PyProBE、电池包和 BMS 硬件路线。

## 项目路线图

实线阶段表示软件已经实现；虚线阶段是还需要真实材料数据与独立实验的研究目标，没有把未来目标写成已验收能力。

![FANGZHEN 项目路线图：v0.1 仿真平台、v0.2 研究数据闭环和 v0.3.10 本地工作站已实现；真实材料独立验证及跨协议可迁移预测仍待验证](figures/project-roadmap-illustrated.png)

[查看高清原图](figures/project-roadmap-illustrated.png) · [可编辑的 Mermaid 路线图](figures/project-roadmap.md) · [Mermaid 源码](figures/project-roadmap.mmd)

| 阶段 | 可检查的交付 | 当前结论 |
| --- | --- | --- |
| **v0.1 冻结平台** | 数据适配、参数来源矩阵、尺度对齐门、PyBaMM 回放与报告 | 冻结标签 `v0.1.0-platform`；详见[预注册判据](docs/preregistration_2026-09-18.md) |
| **v0.2 模拟闭环** | Excel 研究任务、受控约束、公开/合成回放、模拟工艺比较 | 软件闭环通过；[验收报告](docs/v02_simulation_loop.md)保留科学失败门 |
| **v0.3.11 本地工作站** | 数据版本、仿真诊断、描述符/多目标研究、清单评价与本机 API 配置 | 已完成工程接入；[Agent 说明](docs/battery_agent_adaptation.md)与[状态页](STATUS.md)列明限制 |
| **下一阶段** | 真实材料数据、独立协议/批次、前瞻实验和来源完整的环境清单 | 待采集与验证；不能由软件演示结果代替 |

## 复现与判断边界

- **输入来源可追踪**：样品、实验协议、数据用途、单位及参数来源要留档。数据接入方法见[新增数据集](docs/adding_a_dataset.md)；运行前先看[尺度对齐门](docs/scale_alignment_gate.md)。
- **仿真与辨识分开**：zero-fit 回放、同一曲线上的参数探索、独立留出预测是不同证据等级。固定比较窗口和候选覆盖检查防止“少算一段”获得较低误差。
- **真实材料结论尚未过门**：历史 G5/G6、Chen 留出、石墨代理参数等结果和失败条件均在 [STATUS.md](STATUS.md)，不因新界面或新 Agent 上线而改变。
- **环境经济口径单列**：当前石墨清单提供声明边界内的 GWP 与成本筛选；EverBatt 参考预设使用不同原料与功能单位。文献、实现和限制见[环境与经济评价](docs/workbench_v036.md)。

## 仓库导览

```text
battery_sim/           数据集适配、模型和仿真核心
governance/            数据用途、尺度、参数来源等研究约束
identification/        参数辨识与留出预测
user_tools/rg_loop/    Excel 研究记录与模拟闭环
user_tools/workbench/  本地工作站、Agent、ML 与环境经济入口
configs/               模型、化学体系和数据集配置
examples/              可随仓库复现的最小案例
tests/                 自动化回归
docs/                  方法、版本说明与验收记录
figures/               首页图示的 Mermaid 源码与预览
```

本地实验数据、作业记录、打包程序和大体积运行结果不作为源码发布。可复现的少量历史数值产物保留在仓库中；其意义和限制由 [STATUS.md](STATUS.md) 解释。
