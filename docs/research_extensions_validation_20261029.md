# 电池平台科研扩展与公开数据验证（2026-10-29）

## 汇报用简述

平台已形成电池物理仿真、实验数据处理、硬碳性能与部分充电 SOH 预测、预测区间、实验候选推荐及离线实验计划等模块。钠离子 DFN 能运行，但尚无与该模型和参数完全对应的同体系实测曲线验证。硬碳与 SOH 功能已用公开数据按文献或电芯分组验证，结果目前属于研究探索，尚不能证明对所有材料和新电芯有效。

## 新增接口

- TabPFN v2 与 TabICLv2 已加入硬碳和 SOH 的分组训练候选，可在 `algorithms` 数组填写 `tabpfn`、`tabicl`。当前使用 CPU、单模型配置；TabPFN v2 的模型权重许可证与软件代码不同，使用及分发需遵守其归属要求。首次运行需下载权重。参见 [TabPFN 官方许可](https://github.com/PriorLabs/TabPFN#license)、[TabICL 官方仓库](https://github.com/soda-inria/tabicl)。
- SHAP：以模型训练数据为背景，解释上传的前 20 个硬碳样本；分类特征经独热编码展示。特征贡献不是因果效应。
- RSA-CP：使用 [ICML 2026 作者代码](https://github.com/PankajBhagwat/RSA-CP-ICML-2026-Paper)，版本 `67f9eb9ef1eb6215a83433d25411416363774a16`，许可证 CC0，代码及许可保存在 `user_tools/workbench/vendor/rsa_cp/`。回归半宽取作者提供的数值网格近似，可能无有限区间。
- KMM-CP：根据 [论文](https://arxiv.org/abs/2603.26415) 的非选择性 KMM 加权方案，自行扩展到回归残差。论文所列源码地址检索时返回 404；没有复用或声称验证作者代码，也未实现 selective KMM。测试特征参与无标签分布匹配，测试标签只用于事后计算覆盖率。该扩展不自动获得有限样本覆盖保证。
- Ax：使用实际 Ax/BoTorch；少于 5 条已完成实验采用 Sobol，至少 5 条使用 BoTorch。可定义一个或两个目标；多目标应提供目标阈值。候选并非实测结果。
- HELAO：使用 [HELAO-async](https://github.com/High-Throughput-Experimentation/helao-async) `ba910c4c2bdcbcbc49476e32a5b20ca0abb93529` 的 `ShortSequenceModel` 校验并导出计划，仅在本地生成，不调度实验或连接仪器。目标系统仍须验证实验函数、驱动、设备参数和执行条件。
- 部分充电 SOH 增加 `guarded_group` 模型选择策略：训练组交叉验证时应用训练内的域外回退，再按分组平均误差选模型；同时保留原始预测及回退预测。验证中该策略未改变此次选中的模型。

入口为工作站“锂电 / 钠电实验分析”，可以下载合成 CSV 示例。新模型运行依赖本机的 WSL 多化学环境；`user_tools/install_multichem.ps1` 包含对应安装步骤。因已有旧版本服务器时应用会提示先关闭，请先保存并关闭旧工作站再重启。

## 公开硬碳数据

使用 [Targeted-Screened-Hard-Carbon](https://github.com/erweixi/Targeted-Screened-Hard-Carbon) 的本地 master CSV，565 条原始记录中 560 条通过来源和目标检查。以来源字符串代理文献分组，存在标题变体和材料家族未完全隔离的可能。特征含碳化温度、层间距、拉曼比值、比表面积、电解液类型、电流密度；其中多项需样品制备和表征后才可获得，不能直接作为纯制备前预测。

种子 42 的既有探索划分：TabICLv2 文献组平均 MAE 4.70 个百分点，TabPFN v2 为 4.76，训练均值基线为 9.84。分别按训练组交叉验证与均值竞争，采用相同留出组。

种子 2026：训练集 439 条、183 个来源组，留出 121 条、61 个来源组。训练组内比较均值、Ridge、ExtraTrees、GPR、XGBoost、CatBoost、TabPFN v2 和 TabICLv2，选择 TabICLv2；留出文献组平均 MAE **5.29 个百分点**，训练均值基线 **13.67 个百分点**，最差单组 MAE 24.83 个百分点。原始结果：`outputs/new_methods_validation/combined_seed2026/result.json`。同一公开库已多次用于探索，上述并非全新外部数据验证。

对另一拆分中的每个文献组只取一条：134 个训练组、36 个参考组、37 个校准组、37 个测试组。固定 XGBoost 后，90% 名义水平的标准 CP、RSA-CP、非选择性 KMM-CP 在 37 个测试组上覆盖率均为 100%；区间平均宽度分别约 0.279、0.259、0.279（ICE 小数单位），KMM 有效校准样本数约 14.54。样本量小，此次结果不能证明 90% 覆盖保证，也不能说明 KMM 比普通 CP 更好。结果及分组预测见 `outputs/new_methods_validation/intervals/`，流程可由 `python -m user_tools.validate_research_extensions` 在多化学 WSL 环境中复现。

真实硬碳数据上的 SHAP 测试解释了 5 条留出样本，其相对贡献排序仅反映该模型和样本；见上述目录 `shap.json`。Ax 使用 20 条公开数据生成过候选，但这些文献材料和条件并非受控实验，候选不代表工艺优化已获验证，不应直接据此投料。

## 公开钠电部分充电 SOH

联合 [Wenzhou 数据](https://github.com/lvdongzhen/Wenzhou-Sodium-ion-Battery-Degradation-Data)与 [BatteryLife NAion](https://huggingface.co/datasets/Battery-Life/BatteryLife_Raw/tree/main/NAion)，采用 14 个电芯、707 个符合固定电压窗口的充电片段，并使用预先测得的参考容量归一化。种子 2026 按电芯分组，10 个训练电芯、4 个留出电芯；在上述 8 个候选中，训练组 CV 选择 GPR。四个测试电芯等权平均 MAE：原始预测 **7.35 个百分点**，其中最差电芯 **28.27 个百分点**；18 个片段触发域外回退后平均 **1.71 个百分点**，均值基线 **4.36 个百分点**。结果见 `outputs/new_methods_validation/soh_guardcv_seed2026/result.json`。

该数据早已用于特征、模型及回退方案探索，不能作为完全独立的最终测试；回退值是训练集均值，不是新电芯的已验证真实 SOH。训练组内按平均误差、最差组误差和回退误差三种策略均选择同一个 GPR；又增加 `gp_short`（长度尺度 0.5、alpha 0.01）和 `gp_smooth`（长度尺度 2、alpha 0.03），训练组交叉验证仍选择原配置，留出结果未改善，记录在 `outputs/new_methods_validation/soh_tuned_seed2026/result.json`。尚需更多不同厂家与化学体系的独立电芯验证。

## 软件检查

新功能和现有锂钠分析相关 WSL 测试 20 项通过；Windows 工作站测试 23 项通过、1 项跳过；新版 Windows 程序的 HTTP → WSL 端到端检查通过 HELAO、Ax BoTorch、RSA/KMM。Windows Python 未安装 scikit-learn 而无法收集的机器学习测试，改在独立 WSL 环境运行，11 项通过。
