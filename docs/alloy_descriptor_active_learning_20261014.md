# 能接入 fangzhen 的合金描述符、仿真与主动学习论文

核对日期：2026-10-14。根据最新要求，本轮聚焦与现有PyBaMM/PyBOP、参数可信性、描述符ML、约束优化结合，并服务明确的算法研究主张。

本轮整理 **32篇正式期刊/会议论文＋2篇预印本**。已阅读部分正文/方法、出版社预览与官方代码，并核对项目14篇PDF前三页。每条记录说明核对范围；没有逐篇全文复现、没有运行第三方算法，也没有证明本项目取得优化收益。本清单不是穷尽式查新。使用原出版社、原始会议页面、作者机构库/预印本与官方仓库。arXiv助手未找到，采用网页检索核查记录；没有连接的Zotero/Obsidian贡献。

**首轮学习10篇：其中两篇项目已有，只需新增下载8篇。** 下载正文以及描述符定义、选点规则和实验协议所在的补充材料。

| 编号 | 论文与来源 | 用途 | 状态 |
|---|---|---|---|
| D01 | [Materials-discovery workflow guided by symbolic regression for identifying acid-stable oxides for electrocatalysis](https://www.nature.com/articles/s41524-025-01596-4)；npj Computational Materials 11, 150 (2025) | 描述符＋主动学习 | 已有PDF |
| D02 | [Adaptive representation of molecules and materials in Bayesian optimization](https://pubs.rsc.org/en/content/articlehtml/2025/sc/d5sc00200a)；Chemical Science 16, 5464–5474 (2025) | 动态描述符 | 待下载 |
| M01 | [A physics informed bayesian optimization approach for material design: application to NiTi shape memory alloys](https://www.nature.com/articles/s41524-023-01173-7)；npj Computational Materials 9, 221 (2023) | 物理仿真接优化 | 待下载 |
| M04 | [Best practices for multi-fidelity Bayesian optimization in materials and molecular research](https://www.nature.com/articles/s43588-025-00822-9)；Nature Computational Science 5, 572–581 (2025) | 多保真适用条件 | 已有PDF |
| M05 | [Deep Gaussian process-based cost-aware batch Bayesian optimization for complex materials design campaigns](https://www.nature.com/articles/s41524-026-01981-7)；npj Computational Materials 12, 105 (2026) | 部分测量＋成本选点 | 待下载 |
| M07 | [Hypervolume Knowledge Gradient: A Lookahead Approach for Multi-Objective Bayesian Optimization with Partial Information](https://proceedings.mlr.press/v202/daulton23a.html)；ICML 2023, PMLR 202 (2023) | 选择测什么/保真等级 | 待下载 |
| M13 | [Targeted materials discovery using Bayesian algorithm execution](https://www.nature.com/articles/s41524-024-01326-2)；npj Computational Materials 10, 156 (2024) | 面向决策的主动学习 | 待下载 |
| A04 | [Closed-loop inverse design of high entropy alloys using symbolic regression-oriented optimization](https://doi.org/10.1016/j.mattod.2025.06.033)；Materials Today 88, 263–271 (2025) | 符号描述符＋实验闭环 | 待下载 |
| A01 | [Machine-learning design of ductile FeNiCoAlTa alloys with high strength](https://www.nature.com/articles/s41586-025-09160-2)；Nature 643, 119–124 (2025) | 材料发现＋主动学习 | 待下载 |
| A06 | [Noise-Aware Active Learning to Develop High-Temperature Shape Memory Alloys with Large Latent Heat](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/advs.202406216)；Advanced Science 11, 2406216 (2024) | 噪声感知主动学习 | 待下载 |

**建议收敛的主问题**

在原料异质、样本稀少、物理参数可能不可辨识且仿真可能失配时，怎样利用描述符与电化学仿真，选择最值得做的下一项实验，减少找到有效再生条件所需的预算？

平台负责执行和记录。算法论文需要一条可明确实现的新模型或决策规则，并验证规则如何改变选点。一个性能更好的样品，不能单独证明算法更好。

候选方向是：**让仿真适用性与推荐敏感性共同决定信息获取动作**，选择新再生条件、补物理测试、补表征或重复实验。这还是待查新和验证的方向。M05已有成本与部分目标查询，M07已有多目标/多保真知识梯度，M13/M14已有面向决策输出的信息价值，M01/M02已有物理先验BO；界面中组合这些方法不能据此称新算法。

新增规则必须具体回答：参数耦合、某段物理先验错误或实验噪声升高时，为什么选择不同测量、怎样减少有害仿真依赖、什么条件下应保留仿真的预测信息？参数不唯一时，某些工况的预测仍可能稳定，不能默认全部不可辨识参数一律禁止参与决策。

**现有模块与论文的连接**

| 平台位置 | 借鉴方法 | 接入前的数据要求 | 参考 |
|---|---|---|---|
| Excel与样品关系 | 初级量、单位、阶段、变量角色登记 | 原料/工艺/结构/电芯/协议关系 | D03/D04/D06 |
| 描述符ML | 受控组合或符号表达、每轮动态筛选 | 分组性能标签；明确推荐时哪些输入已知 | D01/D02/A10 |
| PyBaMM/PyBOP | 物理先验、预测分布、灰箱/统计残差 | 几何、材料参数或后验、工况与留出曲线 | M01/M02 |
| 仿真和实验 | 多保真/多任务，必要时回退单源 | 同对象同工况可对齐结果、信息性和观测成本 | M03/M04 |
| 参数可信性 | 推荐对参数/失配的敏感性 | 耦合、独立预测偏差、重复实验与失败标签 | A06/M13 |
| 多目标与缺测 | 选择测哪项性能、成本调度 | 部分目标记录、各测量成本、任务关联 | M05/M07 |
| 工艺约束与反馈 | 类别/连续空间、候选与pending任务 | 设备边界、可调范围、路线与耗材约束 | M06/M11/M12 |
| 真实验证 | 冻结规则后推荐、实验、回填 | 新条件实验及后续独立来源 | A01/A04/A05/A07 |

PyBaMM计算电化学响应，不能仅凭热处理温度直接给出再生后BET、表面化学和真实扩散系数。工艺到结构/模型参数的连接需要测量、辨识或验证过的代理；也可先比较物理预测加统计残差方案，不强行从每个表征量推导参数。

BET测量不是容量的天然低保真真值；低倍率和1C容量也不是天然同一目标。不同性能按多任务/部分测量建模，同一性能的不同精度来源才讨论多保真。获取信息的实验成本，与产品成本/碳足迹分别登记。

**描述符构建的四类方法**

| 类型 | 论文中的方法 | 石墨候选应用，均需验证 |
|---|---|---|
| 手工物理特征 | 机制指导选初级量 | 真密度、BET、粒径、缺陷/有序程度、残留组分及表面状态 |
| 确定性组合 | 物理定义或统计聚合 | 粒径span=(D90-D10)/D50、相对层间距变化；保留原始量作对照 |
| 符号描述符 | 受限数学运算搜索简洁公式 | 在同阶段可用量中探索结构/杂质/工艺组合，限制量纲、定义域、复杂度 |
| 学习表示 | 编码器或潜变量 | 后期融合SEM或谱图；当前先与简单标量模型比较 |

合金VEC、B2阈值和熔化焓公式不能直接移植。把真密度、BET等放进模型不等于发现新描述符。应检验新表示是否稳定、可用、便宜，并改善独立预测或闭环选点。

原料BET可推荐前已知；新工艺制备后BET尚未知，只能补测或作为带不确定性的中间预测。重复电芯同组；插补、标准化、筛选、公式搜索与调参在训练折内。报告公式/排名稳定性；SHAP和attention不能单独证明机制。

**算法效果与论文重点**

- 首先用已有G5/G6合成情形测参数耦合、错误物理模型和粒径偏差，明确新增规则怎样改变动作。模拟真值只由评测器保管，仿真调用也计入预算。
- 公开石墨数据回放限制在已测候选池；对新条件的代理预测不能作为实验反馈。
- 同初始观测、同空间、同预算比较随机/合理DOE、普通GP-BO、固定/动态描述符、物理先验或多保真，以及最接近的HVKG/BAX策略；逐项消融新增规则，不要求一次实现清单全部方法。
- 主指标可用达到预设容量/首效/收率条件的预算与成功率；多目标报告可行Pareto超体积/预算曲线，附不可行实验、区间覆盖和决策耗时。训练R²不能替代这些结果。
- 规则冻结后做A/B真实前瞻验证；跨来源泛化还需独立来源。自适应采样改变分布，区间覆盖需单独检查，不能自动沿用i.i.d.保证。收益不成立时保留失败结果并收缩主张。

**方法学习结论**

A01/A04示范描述符与主动学习服务材料发现，机制对照支撑材料结论。A10直接以搜索效率选特征，适合对照“预测最准确的特征是否最适合优化”。D01把公式、集成不确定性与昂贵计算连通，但仍有过度自信。M01提供物理关系注入代理的例子；M04要求便宜信息源实际有用。M05/M07选择测什么；M13/M14围绕最终筛选结果学习。这些是新规则设计时必须了解的已有方法。

**完整下载清单**

每条提供原始来源和核对范围。只有确认过的作者/官方代码才列出，均未执行。优先级1先学、2随后、3扩展，不要求一次加入平台。


**描述符构建与筛选**

**D01. Materials-discovery workflow guided by symbolic regression for identifying acid-stable oxides for electrocatalysis**

Akhil S. Nair et al.；npj Computational Materials 11, 150 (2025)。标识：`10.1038/s41524-025-01596-4`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41524-025-01596-4) · [作者/官方代码](https://gitlab.com/akhilsnair/workflow_sisso)

核对范围：全文/方法；已有本地PDF。

方法与验证：计算闭环：SISSO组合描述符，bootstrap＋特征dropout估计不确定性，POF选HSE06计算。

接入fangzhen：接描述符生成与仿真选点；每轮仅用已观测标签。集成仍有过度自信，须校准。

已有文件：[s41524-025-01596-4.pdf](C:/Users/24330/WorkBuddy/仿真模拟/papers/descriptor_methods_20261013/s41524-025-01596-4.pdf)，无需重复下载。

**D02. Adaptive representation of molecules and materials in Bayesian optimization**

Mahyar Rajabi-Kochi et al.；Chemical Science 16, 5464–5474 (2025)。标识：`10.1039/D5SC00200A`；优先级1。

[原始论文/下载入口](https://pubs.rsc.org/en/content/articlehtml/2025/sc/d5sc00200a) · [官方/作者开放版本或PDF](https://pubs.rsc.org/en/content/articlepdf/2025/sc/d5sc00200a) · [作者/官方代码](https://github.com/AI4ChemS/FABO)

核对范围：出版社正文片段＋官方README。

方法与验证：历史/计算数据任务：FABO每轮进行描述符选择，再训练GP与选点。

接入fangzhen：接自由选列后的动态筛选；对照固定描述符。新工艺尚未知的处理后BET等不能当已知候选输入。

**D03. Big Data of Materials Science: Critical Role of the Descriptor**

Luca M. Ghiringhelli et al.；Physical Review Letters 114, 105503 (2015)。标识：`10.1103/PhysRevLett.114.105503`；优先级2。

[原始论文/下载入口](https://doi.org/10.1103/PhysRevLett.114.105503) · [官方/作者开放版本或PDF](https://link.aps.org/pdf/10.1103/PhysRevLett.114.105503)

核对范围：正式原始PDF。

方法与验证：物理初级特征生成组合后稀疏筛选；交叉验证中重新执行描述符选择。没有新合成闭环。

接入fangzhen：借鉴折内完整搜索和噪声下稳定性；组合表达式不能仅凭拟合称物理定律。

**D04. SISSO: A compressed-sensing method for identifying the best low-dimensional descriptor in an immensity of offered candidates**

Runhai Ouyang et al.；Physical Review Materials 2, 083802 (2018)。标识：`10.1103/PhysRevMaterials.2.083802`；优先级2。

[原始论文/下载入口](https://journals.aps.org/prmaterials/abstract/10.1103/PhysRevMaterials.2.083802) · [官方/作者开放版本或PDF](https://nomad.fhi.mpg.de/uploads/publications/th/PRM-2-083802-2018.pdf)

核对范围：出版社摘要＋作者机构正式PDF入口。

方法与验证：SIS筛相关候选，SO做稀疏组合选择，得到低维显式描述符。

接入fangzhen：接受控公式库；限制量纲、定义域、复杂度，并将公式搜索放入训练折。

**D05. A physics-informed machine learning framework for accelerated discovery of single-phase B2 multi-principal element intermetallics**

Weijiang Zhao et al.；npj Computational Materials 11, 278 (2025)。标识：`10.1038/s41524-025-01775-3`；优先级3。

[原始论文/下载入口](https://www.nature.com/articles/s41524-025-01775-3) · [作者/官方代码](https://github.com/ZHAO-Weijiang/MLcode-for-B2MPEI)

核对范围：出版社全文及方法。

方法与验证：子晶格物理描述符＋ANN/CVAE；有新候选合成表征。

接入fangzhen：借鉴按目标结构构建特征；VEC/B2阈值不适用石墨。原文预处理拆分和潜变量维度有待源码复核。

**D06. Alloy synthesis and processing by semi-supervised text mining**

Weiren Wang et al.；npj Computational Materials 9, 183 (2023)。标识：`10.1038/s41524-023-01138-w`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/s41524-023-01138-w) · [作者/官方代码](https://github.com/MGEdata/Action_extractor)

核对范围：出版社全文及方法。

方法与验证：文献抽取成分/工艺，符号回归构造加工因子；有新文献样本及3个新合成样本外部验证。

接入fangzhen：接工艺顺序与温度/时间组合特征。经验公式有量纲问题，不直接移植为石墨动力学定律。

**D07. Multi-objective optimization of corrosion resistance, strength, ductility properties of weathering steel utilizing interpretable attention-based deep learning model**

Bingxiao Shi et al.；npj Materials Degradation 9, 103 (2025)。标识：`10.1038/s41529-025-00654-y`；优先级3。

[原始论文/下载入口](https://www.nature.com/articles/s41529-025-00654-y) · [作者/官方代码](https://github.com/wenbohuang1002/Multi-Objective-Optimization-of-Steel)

核对范围：出版社全文及方法。

方法与验证：元素性质加权均值/方差、去冗余和监督筛选；新设计钢实测。

接入fangzhen：杂质可探索统计特征，但必须同时表示碳结构/表面状态。原文最终特征数表述不一致；attention不等于因果。


**合金与真实实验闭环**

**A01. Machine-learning design of ductile FeNiCoAlTa alloys with high strength**

Yasir Sohail et al.；Nature 643, 119–124 (2025)。标识：`10.1038/s41586-025-09160-2`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41586-025-09160-2) · [作者/官方代码](https://github.com/diegoxue/Active-learning-for-Record-Setting-Alloy)

核对范围：正文、相关SI、官方R脚本。

方法与验证：领域知识、物理特征与工艺共同输入；4轮合成8种新合金；进一步验证双析出相机制。

接入fangzhen：作为材料篇组织范例。AL主要优化强度；延性还受领域筛选和后续加工影响。公开R脚本是训练/选点片段。

**A02. Machine learning–enabled high-entropy alloy discovery**

Ziyuan Rao et al.；Science 378, 78–85 (2022)。标识：`10.1126/science.abo4940`；优先级2。

[原始论文/下载入口](https://www.science.org/doi/10.1126/science.abo4940) · [官方/作者开放版本或PDF](https://pure.tudelft.nl/ws/portalfiles/portal/134177341/science.abo4940.pdf) · [作者/官方代码](https://github.com/ziyuanrao11/Machine-learning-enabled-high-entropy-alloy-discovery)

核对范围：正式PDF相关方法/结果。

方法与验证：潜空间候选生成，低成本筛选后加入DFT/CALPHAD物理输入，真实合金实验回填。

接入fangzhen：借鉴分阶段投入计算/实验预算；回收石墨还必须表示加工与历史状态。

**A03. Accelerated search for materials with targeted properties by adaptive design**

Dezhen Xue et al.；Nature Communications 7, 11241 (2016)。标识：`10.1038/ncomms11241`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/ncomms11241)

核对范围：官方OA正文方法/结果。

方法与验证：22个初始实验，物理描述符＋预测分布＋EI，9轮反馈合成表征36种配方。

接入fangzhen：学习最小闭环及统一实验协议，不需大模型或自动机器人。

**A04. Closed-loop inverse design of high entropy alloys using symbolic regression-oriented optimization**

Shang Zhao et al.；Materials Today 88, 263–271 (2025)。标识：`10.1016/j.mattod.2025.06.033`；优先级1。

[原始论文/下载入口](https://doi.org/10.1016/j.mattod.2025.06.033)

核对范围：出版社摘要/正文预览。

方法与验证：SR发现熔化焓与高温强度的关联，用以选择体系，再通过不确定性效用选点；4轮制备21个合金。

接入fangzhen：学习描述符怎样缩小工艺/材料空间，再与优化器协作。完整验证协议须下载全文核对。

**A05. Active learning framework to optimize process parameters for additive-manufactured Ti-6Al-4V with high strength and ductility**

Jeong Ah Lee et al.；Nature Communications 16, 931 (2025)。标识：`10.1038/s41467-025-56267-1`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41467-025-56267-1) · [作者/官方代码](https://doi.org/10.24433/CO.0857013.v1)

核对范围：出版社/官方OA方法与结果。

方法与验证：原始工艺量与VED组合量；GP＋EHVI，5轮各2组，完成10组新工艺实验。

接入fangzhen：接再生工艺→多目标性能推荐。温度/时间组合量须有自己的物理依据，不照搬VED。

**A06. Noise-Aware Active Learning to Develop High-Temperature Shape Memory Alloys with Large Latent Heat**

Yuan Tian et al.；Advanced Science 11, 2406216 (2024)。标识：`10.1002/advs.202406216`；优先级1。

[原始论文/下载入口](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/advs.202406216) · [官方/作者开放版本或PDF](https://pmc.ncbi.nlm.nih.gov/articles/PMC11600200/) · [作者/官方代码](https://github.com/tiany0321/noise-aware-strategy)

核对范围：官方OA全文相关方法/结果。

方法与验证：65个初始样本；筛选物理特征、noise-aware Kriging＋SKO；与无噪声EGO并行真实4轮。

接入fangzhen：接重复实验方差与选点；区分测量噪声、模型失配和未知参数。论文部分噪声由模型误差估计。

**A07. Discovering novel lead-free solder alloy by multi-objective Bayesian active learning with experimental uncertainty**

Qinghua Wei et al.；npj Computational Materials 11, 10 (2025)。标识：`10.1038/s41524-024-01480-7`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41524-024-01480-7)

核对范围：出版社全文相关方法/结果。

方法与验证：GP建模强度和伸长率，重复测试均值/方差回填；7轮新合金实验及多项后续验证。

接入fangzhen：接容量/ICE/收率与重复实验；保留实际外推失败。正式年2025，不能根据DOI中的2024判断年份。

**A08. Materials design with target-oriented Bayesian optimization**

Yuan Tian et al.；npj Computational Materials 11, 209 (2025)。标识：`10.1038/s41524-025-01704-4`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/s41524-025-01704-4) · [作者/官方代码](https://github.com/tiany0321/target_oriented_BO)

核对范围：出版社全文相关方法/结果。

方法与验证：t-EI优化接近指定目标；含基准/回放及真实SMA新实验。

接入fangzhen：接目标厚度、孔隙率或适用窗口；不必假设所有指标单调越大越好。

**A09. A process-synergistic active learning framework for high-strength Al-Si alloys design**

Jianming Cai et al.；npj Computational Materials 11, 228 (2025)。标识：`10.1038/s41524-025-01721-3`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/s41524-025-01721-3) · [作者/官方代码](https://www.kaggle.com/code/caijianming/psal-al-si)

核对范围：出版社方法与结果。

方法与验证：工艺条件Wasserstein autoencoder，集成预测和候选多样性规则；多轮真实制样。

接入fangzhen：接工艺路线类别和共享表示；当前小样本先比较GP等简单模型。需核对公式与不确定性偏好表述。

**A10. Toward ultra-high strength high entropy alloys via feature engineering**

Yan Zhang et al.；Journal of Materials Science & Technology 200, 243–252 (2024)。标识：`10.1016/j.jmst.2024.02.058`；优先级2。

[原始论文/下载入口](https://www.jmst.org/EN/10.1016/j.jmst.2024.02.058)

核对范围：期刊原始摘要、出版社引言/结果预览。

方法与验证：以主动学习达到目标所需实验数评价特征工程；摘要报告5轮新合金实验。

接入fangzhen：接描述符评价：同时看预测误差与闭环找到有效条件的效率。最终特征和采集函数待读全文。

**A11. Active-learning-guided discovery of alumina-forming refractory complex concentrated alloys**

Akhil Bejjipurapu et al.；Materials & Design 269, 116644 (2026)。标识：`10.1016/j.matdes.2026.116644`；优先级2。

[原始论文/下载入口](https://www.sciencedirect.com/science/article/pii/S0264127526012190)

核对范围：出版社摘要/预览。

方法与验证：GP＋BO批次推荐，6轮氧化实验并用TEM研究保护层；其他性能有预测项。

接入fangzhen：接工艺→中间结构→性能证据组织。不能把预测硬度/热膨胀写成实测。


**仿真、优化算法与平台方法**

**M01. A physics informed bayesian optimization approach for material design: application to NiTi shape memory alloys**

Danial Khatamsaz et al.；npj Computational Materials 9, 221 (2023)。标识：`10.1038/s41524-023-01173-7`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41524-023-01173-7)

核对范围：出版社正文索引方法/结果片段。

方法与验证：把部分已知物理关系注入GP核，利用Kawin析出模型优化NiTi工艺；是计算闭环。

接入fangzhen：对应PyBaMM灰箱优化接口；物理先验要核实适用性，并比较错误先验/失配情形。

**M02. Physics-informed Bayesian optimization suitable for extrapolation of materials growth**

Wataru Kobayashi et al.；npj Computational Materials 11, 36 (2025)。标识：`10.1038/s41524-025-01522-8`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/s41524-025-01522-8) · [作者/官方代码](https://github.com/nttcslab/PIBO-Vegard)

核对范围：出版社摘要、引言及代码声明。

方法与验证：利用Vegard定律及气流—组成关系，推荐并新合成目标半导体。

接入fangzhen：借鉴物理预测＋统计修正；石墨工艺到电化学参数的连接不能直接由PyBaMM提供。

**M03. Multi-fidelity machine-learning with uncertainty quantification and Bayesian optimization for materials design: Application to ternary random alloys**

Anh Tran et al.；Journal of Chemical Physics 153, 074705 (2020)。标识：`10.1063/5.0015672`；优先级2。

[原始论文/下载入口](https://doi.org/10.1063/5.0015672) · [官方/作者开放版本或PDF](https://arxiv.org/abs/2006.00139)

核对范围：官方摘要及作者预印本。

方法与验证：GP融合DFT和低成本原子势的体模量预测，再在组成空间BO；计算验证。

接入fangzhen：接同一工况目标的低成本仿真和昂贵结果；保持量纲、对象和协议一致。

**M04. Best practices for multi-fidelity Bayesian optimization in materials and molecular research**

Víctor Sabanza-Gil et al.；Nature Computational Science 5, 572–581 (2025)。标识：`10.1038/s43588-025-00822-9`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s43588-025-00822-9) · [官方/作者开放版本或PDF](https://arxiv.org/abs/2410.00544) · [作者/官方代码](https://github.com/atinary-technologies/chem-MFBO)

核对范围：摘要＋本地PDF前三页及已有项目研究。

方法与验证：分析低保真成本和信息性，比较多保真与单保真基准。

接入fangzhen：接仿真/实验预算分配；相关性和成本收益不够时回退单保真。A/B来源不是保真等级。

已有文件：[s43588-025-00822-9.pdf](C:/Users/24330/WorkBuddy/仿真模拟/papers/descriptor_methods_20261013/s43588-025-00822-9.pdf)，无需重复下载。

**M05. Deep Gaussian process-based cost-aware batch Bayesian optimization for complex materials design campaigns**

Sk Md Ahnaf Akif Alvi et al.；npj Computational Materials 12, 105 (2026)。标识：`10.1038/s41524-026-01981-7`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41524-026-01981-7)

核对范围：出版社全文相关方法/结果。

方法与验证：多输出DGP/GP、部分目标查询及成本调度；CALPHAD数据/KNN oracle仿真验证。

接入fangzhen：接缺测目标和测量预算；先用简单多任务GP基线。论文不能证明真实实验成本已下降；官方只承诺后续代码。

**M06. Evolution-guided Bayesian optimization for constrained multi-objective optimization in self-driving labs**

Andre K. Y. Low et al.；npj Computational Materials 10, 104 (2024)。标识：`10.1038/s41524-024-01274-x`；优先级2。

[原始论文/下载入口](https://www.nature.com/articles/s41524-024-01274-x) · [作者/官方代码](https://github.com/Kedar-Materials-by-Design-Lab/Constrained-Multi-Objective-Optimization-for-Materials-Discovery)

核对范围：出版社全文相关方法/结果。

方法与验证：进化选择压力与qNEHVI结合；有银纳米颗粒真实实验以及重复合成基准。

接入fangzhen：接制造边界、配方和多目标前沿；实验每优化器仅一条轨迹，不能扩称多次实验证明。

**M07. Hypervolume Knowledge Gradient: A Lookahead Approach for Multi-Objective Bayesian Optimization with Partial Information**

Sam Daulton et al.；ICML 2023, PMLR 202 (2023)。标识：`pmlr-v202-daulton23a`；优先级1。

[原始论文/下载入口](https://proceedings.mlr.press/v202/daulton23a.html) · [官方/作者开放版本或PDF](https://proceedings.mlr.press/v202/daulton23a/daulton23a.pdf) · [作者/官方代码](https://github.com/meta-pytorch/botorch)

核对范围：原始会议摘要及实验段。

方法与验证：Knowledge Gradient统一解耦目标、不同测量成本和多保真选点。

接入fangzhen：接容量/ICE/循环等不同测量项目；不强制每个样品先测完所有目标。是强基线而非本项目原创。

**M08. Adaptive Batch Sizes for Active Learning: A Probabilistic Numerics Approach**

Masaki Adachi et al.；AISTATS 2024, PMLR 238 (2024)。标识：`pmlr-v238-adachi24b`；优先级2。

[原始论文/下载入口](https://proceedings.mlr.press/v238/adachi24b.html) · [官方/作者开放版本或PDF](https://proceedings.mlr.press/v238/adachi24b/adachi24b.pdf) · [作者/官方代码](https://github.com/ma921/AdaBatAL)

核对范围：原始会议摘要＋官方仓库。

方法与验证：将批次选点视为求积任务，按精度/约束自适应改变批量。

接入fangzhen：接每轮做几个条件及候选多样性；不是当前最先要加入的深度模型。

**M09. High-Dimensional Bayesian Optimization with Sparse Axis-Aligned Subspaces**

David Eriksson and Martin Jankowiak；UAI 2021, PMLR 161 (2021)。标识：`pmlr-v161-eriksson21a`；优先级3。

[原始论文/下载入口](https://proceedings.mlr.press/v161/eriksson21a.html) · [官方/作者开放版本或PDF](https://proceedings.mlr.press/v161/eriksson21a/eriksson21a.pdf)

核对范围：原始会议摘要/引言。

方法与验证：SAAS稀疏先验学习重要维度，HMC推断；计算基准。

接入fangzhen：作为多描述符优化的对照；数十组样本仍需控制有效维度。

**M10. A multimodal robotic platform for multi-element electrocatalyst discovery**

Zhen Zhang et al.；Nature 647, 390–396 (2025)。标识：`10.1038/s41586-025-09640-5`；优先级3。

[原始论文/下载入口](https://www.nature.com/articles/s41586-025-09640-5) · [作者/官方代码](https://github.com/zhang21mit/CRESt)

核对范围：出版社摘要/扩展图及代码声明。

方法与验证：CRESt融合组成、文本与微图像，知识辅助BO和机器人真实实验。

接入fangzhen：后期可接SEM/拉曼等表示及异常诊断。属于多元催化剂，机器人规模不是当前必需条件。

**M11. Rapid design of top-performing metal-organic frameworks with qualitative representations of building blocks**

Yigitcan Comlek et al.；npj Computational Materials 9, 170 (2023)。标识：`10.1038/s41524-023-01125-1`；优先级3。

[原始论文/下载入口](https://www.nature.com/articles/s41524-023-01125-1) · [作者/官方代码](https://github.com/ideal-nu/MOF-LVGP-MOBBO)

核对范围：出版社全文相关方法/结果。

方法与验证：LVGP学习构筑单元类别位置，MOBO在已计算MOF数据库回放。

接入fangzhen：接试剂/路线类别编码；不同类别不能直接整数编号当有序距离。不是新MOF合成闭环。

**M12. BayBE: a Bayesian Back End for experimental planning in the low-to-no-data regime**

Martin Fitzner et al.；Digital Discovery 4, 1991–2000 (2025)。标识：`10.1039/D5DD00050E`；优先级2。

[原始论文/下载入口](https://doi.org/10.1039/D5DD00050E) · [官方/作者开放版本或PDF](https://pubs.rsc.org/en/content/articlepdf/2025/dd/d5dd00050e) · [作者/官方代码](https://github.com/emdgroup/baybe)

核对范围：出版社题录＋官方README与已有项目研究。

方法与验证：混合搜索空间、约束、实验campaign、目标及迁移的开源后端。

接入fangzhen：借鉴工艺路线/连续参数、pending实验和反馈记录。软件接入不是新算法证据。

**M13. Targeted materials discovery using Bayesian algorithm execution**

Sathya R. Chitturi et al.；npj Computational Materials 10, 156 (2024)。标识：`10.1038/s41524-024-01326-2`；优先级1。

[原始论文/下载入口](https://www.nature.com/articles/s41524-024-01326-2) · [官方/作者开放版本或PDF](https://arxiv.org/abs/2312.16078) · [作者/官方代码](https://github.com/sathya-chitturi/multibax-sklearn)

核对范围：出版社正文相关方法/讨论＋官方仓库。

方法与验证：把用户筛选目标转为InfoBAX/MeanBAX/SwitchBAX；纳米颗粒与磁性材料历史数据任务。

接入fangzhen：接满足容量/首效/收率约束的候选集合与决策信息价值；不能称这篇已做再生石墨前瞻闭环。

**M14. Bayesian Algorithm Execution: Estimating Computable Properties of Black-box Functions Using Mutual Information**

Willie Neiswanger et al.；ICML 2021, PMLR 139 (2021)。标识：`pmlr-v139-neiswanger21a`；优先级2。

[原始论文/下载入口](https://proceedings.mlr.press/v139/neiswanger21a.html) · [官方/作者开放版本或PDF](https://proceedings.mlr.press/v139/neiswanger21a/neiswanger21a.pdf)

核对范围：原始会议摘要及PDF入口。

方法与验证：InfoBAX选择对目标算法输出最有信息的查询，区别于只学习整条未知函数。

接入fangzhen：为候选集合/排序稳定性设计提供基础；新的决策准则需与BAX比较。


**最新预印本候选**

**P01. Multi-Objective Multi-Fidelity Bayesian Optimization with Causal Priors**

Md Abir Hossen et al.；arXiv预印本；未核实正式接收 (2026)。标识：`arxiv-2602.00788`；优先级3。

[原始论文/下载入口](https://arxiv.org/abs/2602.00788)

核对范围：作者预印本摘要。

方法与验证：RESCUE因果先验多保真代理＋因果HVKG，计算任务验证。

接入fangzhen：是因果/多保真组合的近邻参考，不自动适用于石墨；缺乏干预证据不能把相关图称因果图。

**P02. Accelerating materials discovery using foundation model based In-context active learning**

Jeffrey Hu et al.；arXiv预印本；未核实正式接收 (2026)。标识：`arxiv-2603.12567`；优先级3。

[原始论文/下载入口](https://arxiv.org/abs/2603.12567)

核对范围：作者预印本摘要。

方法与验证：用TabPFN做主动学习代理，材料数据集回放比较GP/RF。

接入fangzhen：作为你已有TabPFN候选的后续算法基线；不是已验证再生石墨新实验闭环。

**下载保存**

新PDF放在 `papers/alloy_active_learning_20261014/`。原始正文、SI和数据分开保存。该目录目前只有下载README，没有代为下载新论文。已有D01/M04保留原目录。

本报告是检索、学习与研究设计记录；不是新算法已实现或已取得性能提升的验收报告。LCA和经济模块继续对接已有工作，不作为这轮算法论文的唯一创新理由。
