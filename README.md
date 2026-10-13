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

> **当前软件：本地工作站 v0.3.10。** `v0.1.0-platform` 是保留的仿真平台冻结标签，两者用途不同。工作站增加了数据录入、参数探索、机器学习辅助研究，以及环境和经济筛选；这些工程能力不自动构成真实回收石墨的材料验证。详细判据与失败记录以 [STATUS.md](STATUS.md) 为准。

## 项目能做什么

| 研究环节 | 已有能力 | 关键约束 |
| --- | --- | --- |
| **实验数据** | 数据集适配、协议与单位核对；本地工作站的方案、样品、工艺、表征、极片与半电池记录；Excel/CSV 导入和版本归档 | 原始数据、来源和测试条件必须由研究者提供，软件不补造缺失实测值 |
| **电化学仿真** | 基于 PyBaMM 的 SPM、SPMe、DFN 回放；公开案例、参数敏感性和固定窗口比较 | 尺度、几何、初态和协议需要先核对；低误差不等于参数可辨识或跨材料有效 |
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

`data/` 不随仓库发布，因此在全新 clone 上直接运行完整测试集会遇到依赖本地原始数据的用例；请按 [STATUS.md](STATUS.md) 区分软件回归与带数据的研究验收。

### 2 · 打开本地研究工作站

在已配置项目依赖的 Windows 电脑上，双击 `启动科研工作站.bat`；它优先打开本机已有的 v0.3.10 打包版，GitHub clone 中没有打包版时会改用源码启动。也可以直接执行：

```powershell
python -m user_tools.research_workbench
```

工作站自动打开本机浏览器。Windows 打包命令是 `./user_tools/build_workbench.ps1`；生成的 EXE 留在本机 `outputs/`，不纳入 GitHub 源码仓库。工作站的物理/ML 任务仍需可访问项目的 WSL 环境，Excel 导出及环境经济分析还需各自的本机依赖，详见[工作站说明](docs/workbench_v03.md)和[环境与经济说明](docs/workbench_v036.md)。

在“仿真诊断与参数探索”中可直接用规则策略。若使用可选模型服务，展开“模型API地址与端口”，填写基础地址（例如 `http://localhost:11434/v1`）、模型名和可选密钥，保存后检查接口。配置写入本机忽略文件 `data/agent_llm.local.json`；界面检查 `/models`，实际建议任务从 WSL 调用 `/chat/completions`，两者需分别保证可达。详见 [Agent 接入说明](docs/battery_agent_adaptation.md)。

## 项目路线图

实线阶段表示软件已经实现；虚线阶段是还需要真实材料数据与独立实验的研究目标，没有把未来目标写成已验收能力。

![FANGZHEN 项目路线图：v0.1 仿真平台、v0.2 研究数据闭环和 v0.3.10 本地工作站已实现；真实材料独立验证及跨协议可迁移预测仍待验证](figures/project-roadmap-illustrated.png)

[查看高清原图](figures/project-roadmap-illustrated.png) · [可编辑的 Mermaid 路线图](figures/project-roadmap.md) · [Mermaid 源码](figures/project-roadmap.mmd)

| 阶段 | 可检查的交付 | 当前结论 |
| --- | --- | --- |
| **v0.1 冻结平台** | 数据适配、参数来源矩阵、尺度对齐门、PyBaMM 回放与报告 | 冻结标签 `v0.1.0-platform`；详见[预注册判据](docs/preregistration_2026-09-18.md) |
| **v0.2 模拟闭环** | Excel 研究任务、受控约束、公开/合成回放、模拟工艺比较 | 软件闭环通过；[验收报告](docs/v02_simulation_loop.md)保留科学失败门 |
| **v0.3.10 本地工作站** | 数据版本、仿真诊断、描述符/多目标研究、清单评价与本机 API 配置 | 已完成工程接入；[Agent 说明](docs/battery_agent_adaptation.md)与[状态页](STATUS.md)列明限制 |
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
