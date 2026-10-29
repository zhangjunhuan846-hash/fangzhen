# 工作站工程扩展接入与新算法筛选

工作站 v0.3.12 增加了“电池工程仿真”页面，连接电热模型、SOC估计、充电控制、电池包、寿命与故障基线、测试数据处理、虚拟CAN和实验选点。根目录 `启动科研工作站.bat` 为日常入口；已有 EIS 页面继续使用。

当前已具备可复跑的软件仿真链。对照老师的工程电池要求，下一步的重点是冻结一个商业电芯型号，并用同一电芯的OCV、容量、EIS、动态电流和温度数据完成独立验证。真实仪器与BMS板联调需要明确设备和报文协议。

## 已接入的工程任务

| 页面任务 | 实际运行的项目与算法 | 输入与产物 | 已实现范围 |
| --- | --- | --- | --- |
| 电热模型与SOC估计 | [Thevenin](https://github.com/NatLabRockies/thevenin) 0.2.1、[SOX](https://github.com/ahemmatifar/sox) CC/EKF/UKF | 电芯参数、OCV、动态电流/电压；SOC、协方差、I/V/T逐点数据和曲线 | 1RC/2RC电热响应；支持被控对象的SOC×温度RC网格，估计器使用声明工况固定RC；输入电流放电为正 |
| 受约束充电MPC | [do-mpc](https://github.com/do-mpc/do-mpc) 5.1.2、CasADi、Thevenin、SOX EKF | 估计SOC/极化、仿真测温；充电指令、约束裕度、回退和停止事件 | 控制器接收估计状态；约束步初及步末电压/温度，默认留10mV及1°C裕度；求解失败记录零电流回退 |
| 多SOC联合电路辨识 | [PyBOP](https://github.com/pybop-team/PyBOP) 26.3 | 多SOC复阻抗与train/test角色；共享参数、条件参数表、留出误差 | 联合1RC模型：R0/C1共享，R1随SOC指数变化；训练初值仅来自训练谱。与18参数SPMe物理辨识分别标注 |
| 串并联电池包 | [liionpack](https://github.com/pybamm-team/liionpack) 0.4.0、PyBaMM 24.9 | Ns/Np、恒流协议；连接表、全部求解数组、电流守恒残差 | Chen2020参考电芯、连接阻抗、小型串并联；当前无主动均衡控制，未校准用户电池包 |
| 寿命预测基线 | [BatteryML](https://github.com/microsoft/BatteryML) 固定归档快照 | 每电芯一个截止时点特征快照；官方Dummy/Ridge/RF预测、独立电芯划分 | DataBundle及仅训练集拟合的ZScore；用户确认特征在预测前可用。未开放任意pickle上传 |
| 故障诊断 | [CH-BatteryGen](https://github.com/CH-BatteryGen/dataset-warehouse) 官方字段；sklearn RF/SVM | 正常/高阻/低容量/自放电标签；整车隔离、混淆矩阵、宏F1 | 已跑官方公开生成数据小子集；是车辆特征基线，未复现论文全部CNN和全量评估 |
| 测试数据处理 | [PyProBE](https://github.com/ImperialCollegeLondon/PyProBE) Data 2.6.1 | 标准测试CSV；实际Result对象、单位/循环索引与标准CSV导出 | 平台放电正显式转换为PyProBE充电正；当前标准列入口，各厂商原始格式仍需实际文件校核 |
| DBC与虚拟CAN | [foxBMS 2](https://github.com/foxBMS/foxbms-2)、[python-can](https://github.com/hardbyte/python-can)、[cantools](https://github.com/cantools/cantools) | 遥测信号、日志或同方案SOC/MPC结果；编码/虚拟收发/解码与信号目录 | 41个DBC消息；仅虚拟总线。保留行序和时间戳，未按墙钟节奏发送，也未烧录固件 |
| 实验选点 | [BoTorch](https://github.com/meta-pytorch/botorch) 0.18.1 | 已完成、未测、待回传候选；分数、建议和训练清单 | 见下表；未测目标必须留空，待回传候选不重复推荐 |

EIS页面已有 [impedance.py](https://github.com/ECSHackWeek/impedance.py) Lin-KK和1RC/2RC拟合。工程页面可选择本方案已完成的EIS任务作为RC来源，要求核对同一电芯并填写SOC/温度；单谱桥接限制初始SOC相差≤0.05、温度相差≤1°C，并保存局部固定RC外推假设和父结果SHA-256。

SOC/MPC结果也可传入虚拟CAN：单体电压转换为DBC的mV，映射到 `CellVoltage_000`，其余单体槽标无效，不复制成一个虚构的四电芯包。

## 已运行的选点算法

这些入口执行一次有限候选池选点。多轮使用时需将新实验结果更新为completed；不同算法的采集分数不在同一量纲，不能直接比较数值大小。

| 算法 | 实际实现与边界 |
| --- | --- |
| qLogNEHVI | BoTorch双目标带噪超体积改进，真实MC采样；显式参考点，两目标最大化；当前每次推荐1点 |
| HVKG | BoTorch真实超体积知识梯度；逐一固定可查询候选，数值优化终局Pareto设计，2个幻想样本和2个终局点的交互预算近似 |
| PS-BAX | 按[NeurIPS2024 Algorithm 1](https://proceedings.neurips.cc/paper_files/paper/2024/file/f3c8bfcc9c2bc13a0f141cb58afc6e5a-Paper-Conference.pdf)执行后验函数采样、目标集合计算、集合内最大后验熵；扩展为双目标有限Pareto集合，未将原文标量定理直接用于该扩展 |
| MF-KG | BoTorch多保真知识梯度，真实幻想条件下内层优化及成本加权；目标为保真度1的objective1 |
| MF-MES | BoTorch多保真最大值熵搜索；需同一物理量、多保真观测和费用模型 |
| GIBBON | BoTorch下界最大值熵搜索；只优化objective1 |
| qLogEI | BoTorch数值稳定的单目标改进基线 |
| DynMeanBO | ICLR2026核心动态先验均值的现代BoTorch适配：`exp(-gamma*t)*(A*pi(x)+B)`，配qLogEI；公开归一化高斯先验来源和衰减轮数；不重跑作者整套混合初始化及基准 |
| SafeOpt | ICML2015同一标量兼作效用/安全量的单轮有限域适配；声明安全种子、阈值、归一化域Lipschitz上界和GP置信倍数，在潜在最优/扩展集合中选置信宽度最大点；集合无可查询点时正常停止推荐 |

DynMeanBO的A/B均值在标准化输出空间中设置，先验center/width位于任务保存的归一化输入域。

多保真输入必须有至少两个保真度及目标层数据。SPM、SPMe、DFN是不同模型结构，平台不自动把模型名称编码成一个保证收敛的连续精度坐标。真实使用前需检查相同目标的偏差、低高保真信息性和实际费用。

SafeOpt入口目前的安全量就是objective1；温度、电压等多个独立约束需另建观测模型。其推荐依赖声明的安全种子、规律性与置信界，不能代替MPC限制或实物保护。

## 新检索的论文与下一步优先级

核对日期为2026年10月29日。以下优先级结合本平台现有缺口判断；会议或期刊论文中的提升幅度不作为平台预期收益。

| 优先级 | 论文和原始来源 | 适合加入的能力 | 接入条件与当前状态 |
| --- | --- | --- | --- |
| 已接核心 | Qu等，**Incorporating Expert Priors into Bayesian Optimization via Dynamic Mean Decay**，[ICLR2026正式论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/020e313d40a7c060ed07a10cef287750-Abstract-Conference.html)，[作者代码](https://github.com/quchongqi/DynMeanBO) | 让工程先验在早期指导选点，并随观测积累衰减 | 核对作者`DecayPriorMean`和归一化先验实现后接入核心公式；需另做正确/错误先验与普通BO的同预算对照 |
| 高 | Zhang等，**Discovery Learning predicts battery cycle life from minimal experiments**，[Nature650,110–115，2026](https://www.nature.com/articles/s41586-025-09951-7)；[数据](https://doi.org/10.5281/zenodo.17654407)，[代码CodeOcean](https://doi.org/10.24433/CO.5569470.v1) | 物理特征、主动学习和跨设计寿命预测，最贴近商业电芯数据验证 | 官方提供123个大尺寸工业软包电芯；代码不在GitHub。需要核对设计/协议组、前50循环可用特征和跨设计划分；尚未移植整套Discovery Learning |
| 高 | Tan等，**BatteryLife**，KDD2025；[正式DOI](https://doi.org/10.1145/3711896.3737372)，[作者仓库](https://github.com/Ruifeng-Tan/BatteryLife) | 序列寿命预测、CPMLP/CPTransformer等基线、跨数据集迁移 | 2026年v12增加标准化Farasis数据；可与已接BatteryML互补。上游依赖NumPy1.26/Torch2.4，宜独立训练环境；当前为下一阶段候选 |
| 中高 | Ngo等，**MOBO-OSD**，[NeurIPS2025正式论文](https://proceedings.neurips.cc/paper_files/paper/2025/hash/18e780ccbd60697ea4a0184f1e680660-Abstract-Conference.html)，[作者代码](https://github.com/LamNgo1/mobo-osd) | 并行选择一批互补实验，改善多目标Pareto覆盖 | 适合一次可开展多个工况/样品的实验；需批量执行与异步结果契约。作者环境BoTorch0.6.2/Torch1.13.1，需现代API迁移；尚未安装 |
| 中 | Xing等，**CAMO**，[NeurIPS2025正式论文](https://proceedings.neurips.cc/paper_files/paper/2025/hash/d2875f6d67841b7fe6c9ba55d9a6cab7-Abstract-Conference.html)，[作者代码](https://github.com/IceLab-X/CAMO) | 将保真度收敛规律编码进非平稳核 | 先选择确有精度收敛含义的保真轴并采集配对数据。作者真实场景示例调用MATLAB，完整requirements含Windows/CUDA条目，不能直接灌入主环境；尚未安装 |
| 中 | Zhang、Desautels、Chen，**Robust Multi-fidelity Bayesian Optimization with Deep Kernel and Partition**，[AISTATS2025](https://proceedings.mlr.press/v258/zhang25g.html)，[会议链接的作者代码](https://github.com/SchroDeCat/rMFBO) | 处理低高保真关系失配，适合继续研究现有费用/信息动作问题 | 需要成对不同精度数据和失配对照；上游requirements包含作者本地路径，需要清理成最小依赖后移植；尚未安装 |
| 材料侧后续 | Kang等，**Digital twin quantifies spatial-heterogeneity-driven failure in fast-charging lithium-ion battery anodes**，[InfoMat8,e70141，2026](https://doi.org/10.1002/inf2.70141) | 商业石墨负极的孔隙/粘结剂空间分布到传输、析锂、应力的机制链 | 正文使用3D重构和COMSOL；数据在正文、补充材料或向作者合理申请。适合指导微结构变量和实验设计，当前不是可直接安装的Python算法 |

建议先用已接的DynMeanBO、qLogEI/qLogNEHVI、HVKG和随机策略做冻结预算对照。数据侧优先核对Nature2026/Farasis与BatteryLife，再决定是否增加序列大模型。若主要瓶颈是并行实验吞吐量，优先MOBO-OSD；若主要瓶颈是低高保真失配，优先rMFBO，并在确有收敛轴时考虑CAMO。

## 运行环境和兼容记录

工程依赖安装在WSL的三个可选环境中。原有PyBaMM26.8和NumPy2.3.5内核保留。

- `engineering`：Thevenin、SOX、do-mpc、PyBOP、BoTorch、PyProBE、CAN工具；NumPy2。
- `pack`：liionpack0.4与PyBaMM24.9、NumPy1.26、pandas2.2、CasADi3.6.7；仅执行电池包任务。liionpack0.4在26.8及25.8上实际遇到`len_rhs_sens`接口不兼容，未改写已安装科学内核。
- `batteryml_legacy`：归档BatteryML与NumPy1.26；独立环境运行官方传统预测器。`xgboost-cpu`提供所需的同名Python模块。

`安装工程仿真扩展.bat`调用本地安装脚本。依赖见`requirements-engineering.txt`和`requirements-batteryml-legacy.txt`；上游源码提交锁在`configs/engineering_sources.lock.json`。本机路径、实际版本和环境freeze校验保存在忽略的`data/engineering_runtime.local.json`及相邻freeze文件。安装脚本保留与锁不一致或被修改的源码目录，不自动reset。尚未在干净电脑完成重装验收。

SOX按正确的电池仓库固定源码安装，避免装到同名音频软件包。lcapy1.26的旧`importlib`反向兼容依赖不适用于现代Python，安装时跳过其依赖解析，实际数值依赖由工程环境提供。foxBMS原始DBC不改写：只在内存派生文本中去掉指向不存在消息的`VAL_`枚举声明，保留逐条审计与原始/派生SHA-256，其他DBC内容仍严格解析。

## 验收和现存缺口

工程测试包含独立解析RC时域对照、SOC初值偏差恢复、无独立参考时不计算SOC误差、留出SOC扰动不影响拟合、未来目标泄漏拒绝、真实采集函数、MPC达标/不可行回退、DBC毫伏单位映射和虚拟收发。Windows打包程序另外完成HTTP提交、三个WSL环境、结果读取和下载链验收。具体数量、路径与日期以[STATUS](../STATUS.md)本次条目为准。

本机验收为34项工程测试、61项已有相关回归及20个最终EXE工程任务通过。最终程序在 `outputs/fangzhen_workbench_ui_v0312_final/`；[逐任务验收记录](../outputs/workbench_engineering_final_tests_20261029/engineering_verification.json)和[界面截图](../outputs/workbench_engineering_final_tests_20261029/engineering_ui.png)保存在独立验收目录。

```powershell
python -m user_tools.install_engineering --inventory-only
python -m user_tools.research_workbench --data outputs/workbench_engineering_tests_new --no-browser
# 在另一个终端读取上面实例的session.json执行
python -m user_tools.workbench.smoke_engineering outputs/workbench_engineering_tests_new
```

CH官方v1.0归档已在本机下载并校验。固定种子选择LFP四类各6辆，训练4辆/测试2辆，每辆一个充电记录，均匀采样后7112行。此次小样本基线RF宏F1为0.3917、SVM为0.5000，反映简易特征基线仍有限，不能以合成演示中1.0的分数宣称真实诊断准确。归档SHA-256为`2bce2a26720519833f8a0b73e7af95bb6ab8ac997cc62afc3d320c67fd02be21`；文件和采样索引在`data/vendor_assets/ch_fault_smoke_manifest.json`，未随源码分发受限数据。

老师要求中尚需补齐的关键证据：

1. 明确一个目标商业电芯，建立同电芯、同协议的容量/OCV/EIS/动态电流/温度参数来源；当前演示采用合成5Ah电芯或Chen2020参考电芯。
2. 用未参与拟合的脉冲、动态工况、温度和独立电芯评估电压/SOC误差、约束事件及优化收益。小残差、模型运行成功与真实材料改进分别评价。
3. 确定仪器、BMS板与CAN适配器后，完成设备时钟、报文、丢包、保护和实物收发联调。当前完成的是软件模型、文件回放及进程内虚拟总线。

全部工程结果继续保存`material_validation=false`和`hardware_connected=false`，对应当前证据状态。工艺表征到电化学材料参数、跨尺度微结构机制以及真实退化收益仍需专门实验与辨识，不能从接入项目数量推得。
