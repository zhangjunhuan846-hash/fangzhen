# 回收石墨工作站：描述符、机器学习与实验决策接入评估

核查日期：2026-10-13。范围：LCA/经济分析以外的机器学习、表征特征、实验规划和物理—数据连接。此报告记录检索与接入设计，不代表这些算法已加入 v0.3.5 或完成再生石墨验证。

## 证据范围

之前八篇论文及源码评估保留在 outputs/paper_study_20261012。此次补充核查原始会议页、出版社摘要/可访问方法段、官方 README 和部分关键源码。没有逐篇全文及补充材料复现，也没有执行第三方算法。

精选源码文本归档在 data/external/ml_reference_review_20261013；manifest.json 记录文件 SHA256 与获取状态。GitHub API 后续限流，部分快照提交号未能在最终清单中恢复核验，因此标为 commit_unverified；只取得 README 的项目单独标记。实现前必须另行锁定兼容版本及模型权重。不能把该目录视为十三个完整源码仓库。

## 推荐候选与接入判断

| 来源 | 核查到的方法 | 工作站可以借鉴 | 条件与限制 | 优先级 |
|---|---|---|---|---|
| FABO，Chemical Science 2025，DOI 10.1039/D5SC00200A | GP 与迭代内 Spearman/mRMR 描述符筛选，README 提供固定/动态筛选和多随机种子配置 | 自由选列后，比较固定描述符与每轮更新描述符的优化回放 | 每轮只能用已揭示标签筛选；未制样候选的 BET/XRD 不能默认已知；MOF/分子结果不是石墨验证 | 优先 |
| TabArena，NeurIPS 2025 Datasets & Benchmarks | 持续维护的表格模型评测；验证方法、预算和集成影响排名 | 固定分组划分、保存逐折预测、区分调参与最终评估、比较模型预算 | 不搬整个大规模评测环境；重复电芯必须在同组；反复挑最高验证分也会过拟合 | 优先借鉴协议 |
| TabPFN，Nature 2025，DOI 10.1038/s41586-024-08328-6 | 基于合成先验预训练的表格分类/回归模型 | 可选的小样本预测基线及预测分布 | 原论文版本与当前默认版本不同；分布需校准；代码和权重分别许可；不使用云端推理上传自有数据作为默认 | 可选后端 |
| xRFM，ICLR 2026 | 特征学习核机器、平均梯度外积，树式扩展适应大样本 | 描述符相关变换和核模型解释，与 GP/岭回归对比 | 对几十组优先基本 RFM；fit 的验证参数用于选择模型，不能传最终测试集；解释不是因果 | 实验性 |
| Statistical Significance of Feature Importance Rankings，UAI 2025 | 对 SHAP/LIME 排名前 K 特征的抽样稳定性进行检验 | 重要性排序的不确定性与排名稳定性 | 主要控制解释器抽样误差，不等同跨批次稳定性；仍需重复分组划分；源码许可未核实不复制 | 方法借鉴 |
| SISSO 符号描述符主动学习，npj Computational Materials 2025，DOI 10.1038/s41524-025-01596-4 | 稀疏解析描述符、bootstrap 与特征 dropout 集成，引导主动学习 | 从现有标量探索少量可解释组合，比较单一描述符与组合描述符 | 单位/定义域/复杂度约束；折内搜索；几十组易过拟合；论文为氧化物 DFT 数据 | 第二阶段 |
| MODNet，成熟材料学习基础工具；PySR，成熟符号回归工具 | MODNet 用归一化互信息与 relevance–redundancy 排序；PySR 搜索解析表达式 | 冗余控制、描述符候选公式、误差—复杂度比较 | 不必搬完整神经网络；PySR 需要 Julia；特征筛选本身必须在训练折内 | 先借鉴筛选 |
| BayBE，Digital Discovery 2025，DOI 10.1039/D5DD00050E | 离散/连续/混合参数、类别编码、约束、实验 campaign | 改掉固定 x1/x2：路线、试剂、温度、时间、配方、待完成实验统一建模 | 不把类别编成有序数；多目标缺失不能补零；转移学习须保留材料与协议任务标识 | 优先架构 |
| Understanding High-Dimensional Bayesian Optimization，ICML 2025 | GP 长度尺度初始化影响梯度，MSR 用维度尺度与局部 RAASP | 多描述符优化时诊断核尺度与局部搜索失效 | 不支持据此忽略小样本高维风险；官方伴随代码依赖旧 BoTorch/Torch；真实数据不能套无噪声设置 | 后端升级时 |
| PandoraBayesOpt，NeurIPS 2024 | 以 Pandora's Box Gittins index 处理观测成本 | 在实验预算内比较制样、重复测量、补充表征的价值 | 观测成本与产品成本不同；基本实现以单目标 GP 为主；多目标扩展另验证 | 第二阶段 |
| chem-MFBO，Nature Computational Science 2025，DOI 10.1038/s43588-025-00822-9 | 检查低保真成本、信息性和高保真目标，比较单/多保真优化 | 对同一条件的便宜模拟/短测试与昂贵实验建立决策 | A/B批不是保真等级；低倍率与高倍率也不是天然同一目标；必须有可验证映射，必要时退回单保真 | 有成对数据后 |
| AFL-agent，Chemistry of Materials 2025，DOI 10.1021/acs.chemmater.5c00860 | 模块化、可保存中间结果的散射数据处理与主动学习 pipeline | 拉曼/XRD/EIS 原始数据→明确处理参数→特征→模型 | 软材料散射例不能直接替代石墨峰拟合；不得把滤波示例套所有数据；许可类型需进一步核对 | 第二阶段 |
| Active oversight and quality control，npj Computational Materials 2025，DOI 10.1038/s41524-024-01485-2 | 主性能 GP 与辅助质量 GP 约束实验搜索 | 将时间轴、标签、拟合失败质检接入决策，区分有效低性能与故障 | 辅助 GP 需要质量标签；不足时先规则门控；未核实配套官方 GitHub | 优先规则层 |
| AL-HTE-Electrolyte，Nature Communications 2024，DOI 10.1038/s41467-024-47070-5 | 公开实际配方、描述符、测量与主动学习代码/数据 | 增加真实数据闭环回放验收案例 | 目标是电解液溶解度，不是石墨容量；须同时核查 correction；文件类型以实际文件为准 | 回放验证候选 |

## 原始论文与代码

- FABO：[出版社](https://doi.org/10.1039/D5SC00200A)，[官方代码](https://github.com/AI4ChemS/FABO)。README 说明 FS_method 为 spearman/mRMR、min_features/max_features 与多种子回放。不要直接把默认 5–20 特征数量用于十八组实验。
- TabArena：[会议页](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1697e3fb412da11dc9488249f9e7bbc9-Abstract-Datasets_and_Benchmarks_Track.html)，[源码](https://github.com/autogluon/tabarena)。Apache-2.0。
- TabPFN：[论文](https://www.nature.com/articles/s41586-024-08328-6)，[源码](https://github.com/PriorLabs/TabPFN)。当前代码 Apache-2.0；权重单独许可，部署前针对选定 checkpoint 核查。首次下载及授权行为应明确，不悄悄向用户数据建模流程加入网络上传。
- xRFM：[会议页](https://proceedings.iclr.cc/paper_files/paper/2026/hash/ecbc5963c05a83e07404c028b55b29bc-Abstract-Conference.html)，[源码](https://github.com/dmbeaglehole/xRFM)。MIT，Torch 后端。
- 重要性排名：[UAI论文](https://proceedings.mlr.press/v286/goldwasser25a.html)，[源码](https://github.com/jeremy-goldwasser/feature-rankings)。本轮未确认代码许可。
- SISSO 主动学习：[论文](https://www.nature.com/articles/s41524-025-01596-4)，[工作流](https://gitlab.com/akhilsnair/workflow_sisso)，[SISSO++](https://gitlab.com/sissopp_developers/sissopp)。SISSO++ Apache-2.0；工作流许可独立核对。
- [MODNet](https://github.com/ppdebreuck/modnet)，MIT；关键文件 modnet/preprocessing.py。其 NMI/RR 利用目标数据，不得预先在全部样本上计算再宣称独立验证。
- [PySR](https://github.com/MilesCranmer/PySR)，Apache-2.0；关键文件 pysr/feature_selection.py、pysr/sr.py。当前 feature_selection.py 的说明称梯度提升，但实际使用 RandomForestRegressor(100 trees,max_depth=3)，应以源码而非注释为准。
- BayBE：[论文](https://doi.org/10.1039/D5DD00050E)，[源码](https://github.com/emdgroup/baybe)，Apache-2.0；关键 acquisition/_builder.py、campaign 与 search space 接口。
- MSR：[ICML论文](https://proceedings.mlr.press/v267/papenmeier25a.html)，[作者伴随代码](https://github.com/lpapenme/understanding-hdbo-code)，[原始代码](https://github.com/LeoIV/sample-from-high-dim-GP)。伴随仓库 MIT；更改 refit cadence 等设置须与严格复现区分。
- PBGI：[NeurIPS论文](https://proceedings.nips.cc/paper_files/paper/2024/hash/d14c355d5e88cff437a6303d2d716252-Abstract-Conference.html)，[源码](https://github.com/QianJaneXie/PandoraBayesOpt)，MIT；关键 pandora_bayesopt/acquisition/gittins.py。
- 多保真：[论文](https://www.nature.com/articles/s43588-025-00822-9)，[代码](https://github.com/atinary-technologies/chem-MFBO)，MIT。acquisition.py 中 CostMultiFidelityEI 使用高保真 EI×相关性×逆成本，AffineModifiedCostModel 明确仅支持两个等级；不直接推广为任意层次或批次。
- AFL：[论文](https://doi.org/10.1021/acs.chemmater.5c00860)，[NIST源码](https://github.com/usnistgov/AFL-agent)。本轮只归档 README；许可及内部模块待专项核查。
- 质量门控：[论文](https://doi.org/10.1038/s41524-024-01485-2)，[作者预印本](https://arxiv.org/abs/2405.16230)。未声称有已确认的完整开源实现。
- 电解液案例：[论文](https://doi.org/10.1038/s41467-024-47070-5)，[MIT代码与数据](https://github.com/MolecularMaterials/AL-HTE-Electrolyte)。尚未下载并执行实验文件。

## 不宜优先加入

TabM（ICLR 2025）可以作为后续表格深度集成基线，但当前几十组数据应先建立 GP/岭回归/PLS/树模型公平比较。代码 https://github.com/yandex-research/tabm，Apache-2.0。

LEAF（Digital Discovery 2025，10.1039/D4DD00346B，https://github.com/lrcfmd/LEAF）描述元素局部晶体环境；同为碳的回收石墨差异不能靠同一 C 元素向量代替真密度、缺陷和孔隙。GNN/原子势、端到端 PINN、训练大模型不作为当前优先项。SeqAuto 未核实到匹配的材料项目，不列入。

2026 年候选优先保留已确认正式 ICLR proceedings 的 xRFM；不把未核实会议信息的预印本标成主会接收。期刊层级在表中明确，Digital Discovery 与 npj Computational Materials 不写成 Nature 主刊。

## 功能结构与验收

第一阶段补用户数据主线：自动关联样品/工艺/表征/电芯；每列声明单位、阶段与角色；自由选描述符和目标；自动排除 ID、目标自身及不允许的未来字段。支持用户确认的自定义标量列。

训练配置至少包括样品组、批次、协议、目标、输入列与输入在推荐时是否已知。重复电芯必须同组；批次外验证独立报告。未测目标保持缺失，不插补为训练真值。

模型先比较均值基线、岭回归/PLS、GP、树模型；缺失处理、标准化、类别编码、相关性筛选、mRMR 和超参数选择全部在训练折内。外层分组评估保存每个样本的独立预测；内层选择仅在样本量允许时运行，不足则固定配置并明确报告。报告 MAE/RMSE、偏差、区间覆盖/宽度、样本范围以及不确定性，不能只显示训练 R²。

解释同时输出置换重要性、适用模型的 SHAP、重复划分的入选频率与排名区间；强相关变量成组解释。重要性不写成再生因果机制。

工艺推荐允许输入“可实施的工艺变量”；表征预测允许已测材料描述符。工艺→表征→性能级联模型必须采用折外中间预测验证，并传播中间误差；不能用训练内拟合值掩盖两级误差。

第二阶段比较固定描述符与 FABO 式动态筛选，在同初始条件、同观测预算、多种子、同候选池下回放；评测器保管未揭示标签。增加混合类别空间、部分目标结果、实验重复建议、规则质量门控和超出训练范围提示。符号描述符发现作为明确的实验性功能。

第三阶段在有同条件成对数据后评估迁移/多保真和按测量成本选实验；不预设一定优于单保真。曲线/谱特征提取按技术分开注册，保留原始数据与处理参数，禁止未经确认的统一平滑。

LCA 与经济分析仅对接用户正在建设的模块，不重复开发：按工艺方案 ID 接收结果及来源/不确定性，作为目标或约束。区分生产成本与为了获取信息发生的实验观测成本。

完成上述功能的验收应包括：换描述符/目标后可复现训练；重复样品不泄漏；选择器不能看留出标签；未来字段被阻止；分组目标缺失不造真值；候选合乎配方/工艺约束；模型版本可回滚；新数据预测失败有可操作原因。现有 Chen 失败与石墨 BO 不胜随机结果继续保留，不因新算法而改写结论。
