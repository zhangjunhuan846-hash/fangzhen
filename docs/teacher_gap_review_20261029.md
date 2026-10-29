# 对照老师要求：GitHub、算法顶会与电池材料论文的补充检索

> 本文保留v0.3.11时点的检索与缺口判断；v0.3.12已接通工程扩展，当前实现、验证和新增论文见[工程接入更新](engineering_integrations_v0312_20261029.md)。

检索与代码核对日期：2026-10-29。方法：对照本地源码、验收记录及已有文献清单，检索 GitHub 官方仓库、会议正式论文集、出版社和作者公开正文。以下是定向证据扫描，不是穷尽式系统综述；未重新运行候选第三方项目，也未逐篇全文复现。

## 1. 判断

平台已形成较完整的数据与模型研究工作站，具有公开/自有参数回放、参数可信性检查、描述符学习、多目标探索和结果留档。本轮还接通了 EIS 的 Lin-KK 残差诊断与局部 RC 拟合。

距离老师“以工程电池为对象，形成硬件与 EIS/BMS 配套软件，先做出整套仿真”的要求，主要差在：**同一目标电芯的数据与参数贯通、BMS在线状态估计、含温度与约束的控制闭环，以及独立工况下的验证证据**。硬件通信、实物联调属于后续目标；顶会算法是改进决策效率的工具，不是完成第一阶段的前置清单。

“工业级”在截图中没有具体型号、工况或验收指标。以下以工程可验证的商用整电芯研究原型为第一阶段，不将它扩大解释为量产认证或车规产品交付。

## 2. 当前证据与缺口

| 环节 | 本地已经具备的证据 | 距离目标的具体缺口 | 建议验收物 |
| --- | --- | --- | --- |
| 目标电芯与参数 | Chen2020等商用参考参数/数据，SPM/SPMe/DFN，材料元数据与尺度门 | 需要冻结一款目标型号、来源、批次和适用窗口；参考参数与自己的样品尚未完整匹配 | 同型号的容量、OCV、EIS、脉冲/动态工况、温度及来源清单 |
| EIS到模型 | 频域正向计算、谱导入；v0.3.11的Lin-KK与1RC/2RC拟合 | 单条谱局部拟合尚未成为跨SOC/温度/老化的参数表；也没有完成多SOC物理参数联合辨识 | 条件化参数表、拟合残差、可辨识性检查、冻结参数的时域留出预测 |
| BMS状态估计 | 仿真中可设置初始SOC | 尚无面向带噪声传感器流的完整SOC估计任务；初始SOC输入不等于SOC估计 | 库仑计数、EKF/UKF对照，初值偏差/电流零偏/缺测试验，误差与单步耗时 |
| 电热与充放电控制 | 前向协议、电压截止和温度输入；PyBaMM内核可提供进一步模型基础 | 工作站主链还需实现并校准电热耦合、控制器、限流/限压/温度约束、求解失败回退 | 单一运行中同时保存I/V/T/SOC、控制动作、约束裕度和回退事件 |
| 老化与故障 | 描述符ML、既有参数探索与公开/合成研究 | 缺SOH/RUL/故障任务的成套标签、分组评估与外部工况验证 | 容量/内阻参考测量；按电芯/车辆划分；误报漏报及老化外推评估 |
| 串并联电池包 | 当前主链以单体/半电池为主 | 单体差异、连接阻抗、电流分配、均衡和温差尚未贯通工作站 | 小型串并联算例；退化到单体的一致性检查；不同初态/参数的对照 |
| 硬件与通信 | CSV/Excel/Parquet离线接入 | 尚无EIS仪、测试柜或BMS板的已验收实时驱动/DBC/时钟与单位契约 | 先虚拟CAN和日志回放，再对明确硬件做收发与异常处理联调 |
| 优化收益 | 预算对照、动作选择研究与复现记录已经存在 | 尚无对目标电芯或新材料的前瞻收益证据；既有研究未证明预设的总体算法优势 | 同初始信息/预算/候选/约束比较，冻结规则后新工况或新实验确认 |

本地依据：`user_tools/workbench/eis_fit.py`、`eis_worker.py`、`candidate_multi.py`、`user_tools/rg_loop/physics.py`、`STATUS.md`、`outputs/analysis/resource_budget_20261014/interpretation.md`、`outputs/analysis/action_study_20261015/report.md`。

已有预算研究不能简单写成“尚未做实验”：它完成了同预算对照与诊断，但相对随机策略的总体收益未获支持，且费用为假设。动作选择研究保留了联合不确定性/协议差异的机制证据，预定的KG/费用总体优势未获支持；方法文档还明确说明它与已有知识梯度的关系。下一轮需要针对已暴露的失配、费用和校准问题设计方法，而不是仅换算法名称。

## 3. 值得继续接的GitHub项目

优先级以补齐老师第一阶段链路为依据；“已核对”不表示已安装或已通过平台兼容性测试。

| 项目/原始来源 | 接入价值 | 边界与成本 | 建议 |
| --- | --- | --- | --- |
| [thevenin](https://github.com/NatLabRockies/thevenin) | 含SOC、RC、温度/滞后的等效电路；Simulation/Prediction接口连接离线标定与逐步预测 | 是电池状态演化模型，仍需估计算法；当前依赖含scikit-sundae，须独立验证运行环境。BSD-3-Clause | **P0：与状态估计合成一条主链** |
| [SOX](https://github.com/ahemmatifar/sox) | 库仑计数、EKF、UKF，以及电流/电压噪声与传感器故障注入 | 上游自定位为playground；核对了EKF/UKF源码和MIT许可，仍需数值稳定性、边界和跨版本测试 | **P0：先做SOC最小闭环** |
| [PyBOP](https://github.com/pybop-team/PyBOP) | 复用已有环境，扩展同电芯多SOC/多数据类型参数拟合 | 已有PyBOP不等于已经完成该联合拟合；新参数必须有激励与留出证据 | **P0：补全已有工具的使用链** |
| [BoTorch](https://github.com/meta-pytorch/botorch) | 官方qNEHVI/LogEI族、HVKG、成本/多保真建模的实现基础 | 仓库现位于meta-pytorch；现有平台是有限候选q=1轻量适配。新库需隔离依赖并对相同输入做数值对照 | **P1：建立强基线，再升级选点** |
| [do-mpc](https://github.com/do-mpc/do-mpc) | 非线性/鲁棒MPC、MHE，可做充电/温控策略仿真 | 通用控制工具箱，需自己定义经过校核的电池模型、状态、目标和约束；LGPL-3.0许可 | **P1：模型与估计可用后接** |
| [python-can](https://github.com/hardbyte/python-can) + [cantools](https://github.com/cantools/cantools) | CAN收发、日志回放与DBC解析/编码；将电池模型接到BMS通信层 | 需具体适配器、DBC及消息语义，库本身不提供用户设备协议 | **P1：先虚拟总线，再实际板卡** |
| [BatteryML](https://github.com/microsoft/BatteryML) | ICLR2024正式论文的电池退化数据格式、特征与基线 | **仓库当前archived=true**，README仍有旧“活跃更新”文案；适合固定快照复现，不能按活跃核心依赖设计。MIT | **P1：离线SOH/RUL基线** |
| [CH-BatteryGen](https://github.com/CH-BatteryGen/dataset-warehouse) | ICLR2026 Battery Fault对应数据，故障分类/严重程度基准 | 公开数据为生成数据；README限制学术/非商业用途，标注CC BY-NC-SA 4.0。不能当成公开的真实故障车队遥测 | **P1：补故障仿真基准** |
| [liionpack](https://github.com/pybamm-team/liionpack) | 将PyBaMM单体扩展为串并联电池包 | 上游明确maintenance mode；与现有PyBaMM版本需实测兼容 | **P2：单体主链通过后再接** |
| [foxBMS 2](https://github.com/foxBMS/foxbms-2) | BMS硬件、嵌入式软件、构建与调试工具链 | 需要实际硬件与工具链；软件BSD-3-Clause，硬件/文档CC-BY-4.0 | **P2：硬件确定后的联调对象** |
| [PyProBE](https://github.com/ImperialCollegeLondon/PyProBE) | 测试仪数据处理、按工步/循环组织实验 | 需实际厂商文件来证明映射正确；现有文件导入先保留 | 数据规模/格式成为瓶颈时接 |

已接入的 [impedance.py](https://github.com/ECSHackWeek/impedance.py) 继续负责局部谱诊断；它与上述工程模型、状态估计、控制器承担不同职责。当前新增模块中，只有impedance.py已经由本轮实际任务验证。

## 4. 算法顶会：每篇具体补什么

| 编号 | 已核对论文、作者与正式出处 | 对本平台的用途与限制 | 读取范围 |
| --- | --- | --- | --- |
| A01 | Zhang, H. et al. **BatteryML: An Open-source Platform for Machine Learning on Battery Degradation**，ICLR2024。[正式论文](https://proceedings.iclr.cc/paper_files/paper/2024/hash/4048c740bec4c682b17c640f584d2762-Abstract-Conference.html) | 为SOH/RUL建立数据与传统/深度基线；不能直接获得用户电芯的通用模型；代码仓库已归档 | 正式元数据/摘要、官方README与许可 |
| A02 | Liu, Q. et al. **Battery Fault: A Comprehensive Dataset and Benchmark for Battery Fault Diagnosis**，ICLR2026。[正式论文](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0d781fa5f639bf2caf728a68e9678362-Abstract-Conference.html) | 提供正常、自放电、高阻、低容量等故障基准；适合扩展BMS诊断任务。公开集是经真实车队约束的生成数据，需实测迁移验证 | 正式PDF第1–3节及数据范围说明、官方仓库 |
| A03 | Daulton, S., Balandat, M. & Bakshy, E. **Parallel Bayesian Optimization of Multiple Noisy Objectives with Expected Hypervolume Improvement**，NeurIPS2021。[正式论文](https://proceedings.neurips.cc/paper/2021/hash/11704817e347269b7254e744b5e22dac-Abstract.html) | 以qNEHVI建立噪声多目标强基线；现有轻量q=1功能不能冒充完整批量连续实现 | 正式元数据/摘要；结合本地轻量实现核对 |
| A04 | Ament, S. et al. **Unexpected Improvements to Expected Improvement for Bayesian Optimization**，NeurIPS2023。[正式论文](https://papers.neurips.cc/paper_files/paper/2023/hash/419f72cbd568ad62183f8132a3605a2a-Abstract-Conference.html) | LogEI族改善采集函数的数值优化；先在相同问题上核对数值与收益，不预设一定胜过现有方法 | 正式元数据/摘要、BoTorch LogEI模块源码头部 |
| A05 | Daulton, S., Balandat, M. & Bakshy, E. **Hypervolume Knowledge Gradient: A Lookahead Approach for Multi-Objective Bayesian Optimization with Partial Information**，ICML2023。[正式论文](https://proceedings.mlr.press/v202/daulton23a.html) | 在补EIS、脉冲、重复测量或新候选之间选择信息动作的关键已有方法；需要动作成本、观测映射与联合模型 | 正式摘要、官方HVKG接口；与既有动作研究比对 |
| A06 | Cheng, C. X. et al. **Practical Bayesian Algorithm Execution via Posterior Sampling**，NeurIPS2024。[正式论文](https://proceedings.neurips.cc/paper_files/paper/2024/hash/f3c8bfcc9c2bc13a0f141cb58afc6e5a-Abstract-Conference.html) | PS-BAX可作为面向“合格候选集合/最终决策”的信息获取基线，降低复杂信息增益计算负担；本平台尚未实现 | 正式元数据/摘要、算法段落预览 |
| A07 | Takeno, S. et al. **Multi-fidelity Bayesian Optimization with Max-value Entropy Search and its Parallelization**，ICML2020。[正式论文](https://proceedings.mlr.press/v119/takeno20a.html) | 在同一目标的不同精度/成本评价之间选取查询；SPM/SPMe/DFN与实测能否构成有信息的低/高保真层需先验证 | 正式元数据/摘要与方法段预览 |
| A08 | Sui, Y., Gotovos, A., Burdick, J. W. & Krause, A. **Safe Exploration for Optimization with Gaussian Processes**，ICML2015。[正式论文](https://proceedings.mlr.press/v37/sui15.pdf) | 对受约束探索提供理论起点；其GP/规律性/安全初始条件等假设需满足。工程平台仍要独立硬约束、停止和回退 | 正式PDF摘要与问题设定预览 |

这些是可复现方法与对照来源。把它们接在同一界面中，不自动产生新的算法贡献。当前最值得研究的具体问题是：**物理模型有失配、参数不完全可辨识时，预算应花在新工况/EIS/脉冲/重复测量中的哪一项，才能改善最终可用策略的判断？** 该问题已有HVKG/BAX等近邻工作，需明确新观测模型或决策机制，并和它们作同预算对照。

## 5. 电池与材料论文：补齐物理及实验依据

| 编号 | 已核对论文与出处 | 本平台应学习的内容 | 读取范围与局限 |
| --- | --- | --- | --- |
| M01 | Hallemans, N. et al. **Physics-based battery model parametrisation from impedance data**，Journal of The Electrochemical Society 172, 060507 (2025)，DOI [10.1149/1945-7111/add41b](https://doi.org/10.1149/1945-7111/add41b)。[公开正文](https://arxiv.org/html/2412.10896v4) | 商用LG M50LT、多SOC联合EIS拟合、分组SPMe和独立动态工况验证，最接近本轮缺口 | 阅读参数/验证/可用性相关正文；部分参数触边、低频拟合有失配。OCP来自About:Energy，尚未确认整套原始数据可直接自由下载；M50LT不能仅凭相似型号与Chen2020 M50数据混用 |
| M02 | Zhang, Y. et al. **Identifying degradation patterns of lithium ion batteries from impedance spectroscopy using machine learning**，Nature Communications 11, 1706 (2020)。[原文](https://www.nature.com/articles/s41467-020-15235-7) | EIS整谱到容量/SOH/RUL的统计路线，提示EIS除RC拟合外还能提供预测信息 | 阅读摘要、容量估计与讨论；文中测试电芯与训练电芯使用相同充放电速率，动态跨协议泛化仍需新实验 |
| M03 | Attia, P. M. et al. **Closed-loop optimization of fast-charging protocols for batteries with machine learning**，Nature 578, 397–402 (2020)。[原文](https://www.nature.com/articles/s41586-020-1994-5) | 早期寿命预测、BO选协议、真实反馈与后续验证，可作为“仿真优化最后怎样验收”的参照 | 核对摘要与实验闭环说明；不将论文节省时间的比例移植为本平台预期收益 |
| M04 | Sabanza-Gil, V. et al. **Best practices for multi-fidelity Bayesian optimization in materials and molecular research**，Nature Computational Science 5, 572–581 (2025)。[原文](https://www.nature.com/articles/s43588-025-00822-9) | 多保真的价值取决于低保真信息性与成本；先做相关性/失配/费用检查，再决定是否使用 | 核对出版社摘要与方法概要；项目10月14日清单已收录，本轮重新核对，不算全新发现 |
| M05 | Zheng, C., Lai, P., Zeng, M. et al. **Inverse inference of lithium-ion battery degradation parameters via physical modeling and data-driven machine learning**，npj Computational Materials，2026-07-24，[DOI 10.1038/s41524-026-02250-3](https://www.nature.com/articles/s41524-026-02250-3) | 通过退化斜率/拐点等轨迹特征，把P2D模拟与轻量XGBoost连接，适合学习低维老化表征的设计 | 当前出版社页面为已同行评议的提前公开版本；本轮仅摘要/元数据，尚未核对全部正文、代码或机制唯一性，不直接推荐部署 |
| M06 | Sweeney, L., Sargent, A. T., Dai, Y. et al. **Advanced Characterization and Rejuvenation of End-Of-Life Lithium-Ion Anodes: Toward the Development of a Green Upcycling Route**，Small 22, e12626 (2026)。[原文](https://doi.org/10.1002/smll.202512626) · [作者机构PDF](https://pure-oai.bham.ac.uk/ws/portalfiles/portal/294294432/SweeneyL2026Advanced.pdf) | 真实退役负极、多模态表征、X射线成像与基于图像的模拟，可补“处理→结构→响应”的实验依据 | 核对摘要、版本与机构记录；其演示为特定处理条件下的短期结果，不能推出长期BMS或再生工艺泛化 |

材料侧仍有一处需要专门补证据：热处理温度、BET、拉曼或杂质变化，怎样形成可用于整电芯模型的参数及其不确定度。要保留“工艺→结构→电极/半电池→整电芯”的测量关联；不能由软件直接把一个表征值翻译成通用扩散系数或寿命。

## 6. 推荐推进顺序与可展示的最低交付

### 第一阶段：补齐整套仿真

1. **冻结一个目标电芯和一个任务**。优先用实验室可获得或数据授权完整的商用全电芯；目标可先选动态SOC估计或受约束充电中的一个。把拟合数据、留出工况、初态与评价窗口先分开。
2. **把EIS结果接到时域ECM**。建立同电芯的SOC/温度索引参数表，与OCV/容量一起进入thevenin或经过校核的现有PyBaMM等效电路。用未参与拟合的脉冲/动态电流检查电压；超出参数表范围时明确标识。
3. **加状态估计**。先库仑计数，再EKF/UKF，使用带噪声观测并故意扰动初始SOC、电流零偏和参数；报告收敛、误差、协方差行为和单步耗时。生成被控对象与估计器使用相同模型的理想测试，须另配失配测试。
4. **连接温度与决策**。先固定CC-CV或简单规则作为基线，再引入MPC或BO调参；保存电压、温度、电流限制和求解失败回退。具体上限来自目标电芯资料/测试协议，而不是通用默认值。
5. **冻结规则后的验证**。新电流协议、独立电芯或新实验反馈至少形成一种清晰的留出证据。报告基线、误差/约束事件、实际计算和实验预算；参数拟合误差、状态估计误差和优化收益分别评价。

达到这一阶段后，可向老师展示同一个电芯的“实验输入→参数→动态电池模型→带噪声传感器→SOC估计→控制动作→响应→独立评价”全链录像与可复跑任务包。现有环境经济与材料探索模块可作为旁路输出，不必阻塞该交付。

### 第二阶段：硬件和更强算法

先用虚拟CAN/已录日志与DBC对齐单位、符号、时钟和消息含义，再连接明确BMS板/测试设备。随后扩展电池包、均衡、老化/故障诊断与闭环实验调度。具体项目是否接入，由前一阶段暴露的误差与瓶颈决定。

## 7. 检索记录与证据等级

关键词覆盖battery state estimation/EKF/UKF、EIS parameterisation/identifiability、battery degradation/fault benchmark、noisy multiobjective BO、partial information/cost/multifidelity、graphite rejuvenation。保留经典方法并向2024–2026会议/材料文章扩展；只使用正式会议、出版社、作者机构库、原始仓库作为结论依据。未调用未配置的Zotero/Obsidian，也未自动下载全部PDF。

上游状态核对：BatteryML通过GitHub仓库元数据确认归档；BoTorch确认规范仓库名为`meta-pytorch/botorch`；SOX核对README、pyproject、EKF/UKF源文件与MIT许可；python-can与cantools核对README；do-mpc核对README与LGPL许可；CH-BatteryGen核对正式论文的数据生成说明和官方README用途限制。既有项目的文件版本凭据另见 [本轮接入说明](github_battery_integrations_20261029.md)。

本文的“缺口”是结合本地实现与上述来源作出的工程判断；不是老师额外提出的条款，也不是对未运行候选项目作出的性能承诺。
