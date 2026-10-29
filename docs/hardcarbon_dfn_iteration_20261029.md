# 硬碳容量、双目标与钠电 DFN：接入和迭代记录

## 当前能力和操作

双击 `启动科研工作站.bat`，进入“锂电 / 钠电实验分析”：

1. 选择“硬碳容量与 ICE 联合建模”，上传同时包含来源、容量与 ICE 的 CSV。两目标共用按文献分组的测试集，各自在训练文献内比较模型。容量单位 mAh/g，ICE 用 0–1。
2. 选择“硬碳容量与 ICE 联合候选筛选”，指定该训练任务及候选 CSV，输出两项预测、特征越界信息及 Pareto 集。若任一目标在训练时保留的测试文献上比均值基线改进不到 5%，默认暂停 Pareto；`allow_exploratory=true` 可查看探索性排序。测试集是部署门槛，不用于挑选模型。
3. 选择“钠电 DFN 扩散与极化辨识”，上传同一电芯恒流放电曲线，按 `curve_id` 分配 `train` 和 `test`，曲线从 0 秒开始，指定倍率与温度。可选择同方案候选任务，并在配置里填写 `candidate_id`，将候选记录与辨识任务关联。此关联由研究者确认，不能证明测量样品与候选实际一致。
4. 新实验完成后记录配方、来源、工艺、测试条件、样本批次以及实测容量、ICE 和曲线；将可信记录加入新版本数据文件，重新训练并保留原任务。**当前回填和训练仍由用户启动，不是自动采集或自动长期训练。** 不应把性能预测直接转换为 DFN 扩散系数、OCP 或其他材料参数。

`feature_mode=measured` 使用碳化温度、层间距、Raman、比表面积、电解液和测试电流；`measured_extended` 另用碳化时间、升温速率、孔体积及结构尺寸；这些包含制备后表征。`process` 使用工艺和测试电流；`process_precursor` 额外使用用户提供的 `precursor_type` 和 `electrolyte_type`。制备条件、前驱体和测试协议必须真实已知。公开数据中 `material_name` 多数是论文内样品代号，不可可靠视作前驱体；本轮没有用代号假装原料信息。缺少的数值由训练组中位数填补，候选输入须明确填写。`process_precursor` 已做合成数据的软件测试，尚无对应公开数据性能验证。

两目标预测模型选取均在训练组交叉验证中完成；输出的 Pareto 是对上传有限候选的**点预测非支配筛选**，不是 Ax 的贝叶斯采集函数，不是新实验结果。新增“Ax 硬碳容量与 ICE 双目标选点”，以配对实测记录调用 Ax/BoTorch 多目标采集函数，每个来源最多取一条，使用用户给定的工艺范围和目标参考阈值。公开硬碳数据以 700–1400°C 和指定参考阈值成功生成过候选，只有 15 个不同工艺组合；这仅验证软件流程，不证明该温度最佳。不同论文的测试条件、材料与前驱体并不一致，不能将混合文献数据生成的候选直接当实验优化结论。结果见 `outputs/hardcarbon_dfn_validation/ax_mobo_public.json`。

## 公共硬碳数据

数据源：[Targeted-Screened Hard Carbon](https://github.com/erweixi/Targeted-Screened-Hard-Carbon)，其[论文](https://www.nature.com/articles/s41467-026-77440-0)。本地 565 行中 558 条具有来源映射、有效 ICE 与可逆容量；按规范化来源字符串代理分组，仍可能有标题变体、同材料跨文献或数据整理误差。当前公开库已用于多次开发和对照，所有结果均属探索，不能当完全独立外部验证。预处理和分组没有把测试目标用作训练输入。

固定种子 2026，训练 182 个文献组、435 行；留出 61 个组、123 行：

| 特征 | 目标 | 训练组CV选中 | 留出组等权 MAE | 训练均值基线 |
|---|---|---|---:|---:|
| 已表征 | ICE | TabPFN v2 | 5.56 个百分点 | 12.81 个百分点 |
| 已表征 | 可逆容量 | CatBoost | 63.36 mAh/g | 63.64 mAh/g |
| 工艺 | ICE | TabICLv2 | 6.38 个百分点 | 12.81 个百分点 |
| 工艺 | 可逆容量 | CatBoost | 64.83 mAh/g | 63.64 mAh/g |
| 已表征扩展 | 可逆容量 | ExtraTrees | 62.78 mAh/g | 63.64 mAh/g |

以上均未达到容量比基线改善 5% 的预设门槛，故默认暂停联合 Pareto。参见 `outputs/hardcarbon_dfn_validation/{measured_gated,process_gated,extended_gated}/result.json`。

对已表征模式的 123 条留出记录进行不加筛选约束的探索性回放：预测 Pareto 共 2 条，实测 Pareto 共 6 条，二者重合 1 条（预测集合精确率 1/2、召回率 1/6）。这是异质文献记录的事后排名诊断，不是同一原料、统一协议下的新实验优化验证；此处没有套用实际界面的特征越界筛查与推荐门槛。见 `measured_gated/pareto_diagnostic.json`。

加入更细叶节点 ExtraTrees、MAE 损失 CatBoost、绝对误差 XGBoost，与均值、岭回归、原模型、TabPFN/TabICL一起做四次预先指定的来源分组划分，均由训练组 CV 选择模型，留出组不参与选择。四次留出文献组平均 MAE：

| 特征 | ICE / 百分点 | ICE 均值基线 / 百分点 | 容量 / mAh/g | 容量均值基线 / mAh/g | 容量胜基线次数 |
|---|---:|---:|---:|---:|---:|
| 工艺 | 7.38 | 13.16 | 57.36 | 59.57 | 3 / 4 |
| 已表征扩展 | 5.32 | 13.16 | 56.91 | 59.57 | 3 / 4 |

容量改善幅度小且不稳定，不能仅取表现最好的划分。各折完整结果见 `outputs/hardcarbon_dfn_validation/robust_grouped/summary.json`；复现命令为多化学 WSL 环境下 `python -m user_tools.validate_hardcarbon_robust`。未使用模型生成的合成标签冒充真实数据。新论文 [Chen 等](https://arxiv.org/abs/2510.12833) 采用 TabPFN 数据增强和 XGBoost，并报告了实验检验；其不同数据和划分下的指标不能直接与本平台分组结果比较。可参考其前驱体信息和实验方案，尚未复现其数据增强流程。

## 钠电 DFN 辨识

模型使用 PyBaMM `sodium_ion.BasicDFN` 和 Chayambuka2022 的 NVPF/硬碳参考参数。拟合范围为负极扩散系数整体倍率（0.1–10）及经验倍率电压降（0–0.3 V/C）；后一项是曲线级经验修正，不等于真实欧姆接触电阻。训练曲线按条等权，整条曲线独立留出；默认初始状态和参考参数必须与数据相符。使用有限差分雅可比、求解器成功状态、边界接近标记及局部敏感度诊断；局部条件数不能证明参数唯一可辨识。不把拟合后曲线自动写入DFN参数库。

合成回收：按扩散倍率 2.0、经验电压降 0.03 V/C 生成 0.5C、0.8C 训练曲线和 1C 留出曲线，回收约 1.99996 和 0.029999，1C 曲线误差约 0.0019 mV。合成数据是软件验证，不是实测验证。

公开 [Wenzhou 钠电数据](https://github.com/lvdongzhen/Wenzhou-Sodium-ion-Battery-Degradation-Data) 的 H-1-2 首次放电曲线拟合，第二次放电留出：初始电压 RMSE 约 375 mV，拟合后约 175 mV，但参数触边、20次评估未收敛，且电芯电极体系和初态与参考模型尚未证实相同，25°C 是未核实假设、倍率按首放容量归一化；两个循环也不是独立电芯。这只能作为**模型失配压力测试**，不能声称实现同体系参数辨识或泛化。原始来源哈希及结果保存在 `outputs/hardcarbon_dfn_validation/dfn_wenzhou_mismatch/result.json`；合成回收结果在 `dfn_synthetic/result.json`。脚本 `python -m user_tools.validate_hardcarbon_sodium_dfn` 可在 WSL 环境复现。

另下载并按发布方 MD5 核对 [Zenodo 14359482](https://zenodo.org/records/14359482) 的 Figure 10 两条数据，[原文](https://doi.org/10.1002/batt.202500015)给出 NaMnHCF/硬碳、23°C、1C=150 mA/g。按比容量和声明电流换算时间，以 C/5 曲线拟合、C/20 曲线留出：留出电压 RMSE 由 558 mV 变为 542 mV，参数触边且 20 次评估未收敛。正极与模型 NVPF 不同、倍率标定基准及初态不等价、曲线来自不同循环，结果只说明跨体系失配，不能作为同体系辨识验证。见 `outputs/hardcarbon_dfn_validation/dfn_zenodo_mismatch/result.json` 和 `user_tools/validate_sodium_zenodo.py`。

## EIS 与 BMS 配套

已有 EIS 导入、Lin-KK、1RC/2RC 拟合，同方案可在确认同一电芯和邻近 SOC/温度后把单谱 RC 参数桥接到 ECM/SOC 或 MPC，并接虚拟 CAN；见 `user_tools/workbench/engineering_service.py`。下一步应构建多 SOC×温度×SOH 参数表，用独立脉冲/动态记录检验，再联调具体设备。当前未形成已验收的真实仪器与 BMS 硬件闭环，亦不能从单条 EIS 拟合直接获得 DFN 材料物性。

## 软件检查

硬碳与钠电新增及既有学习测试在 WSL 通过；Windows 工作站测试 23 通过、1 跳过。打包程序经 HTTP → WSL 验证了联合训练、探索候选、候选与 DFN 任务关联、合成参数回收。运行需要本机项目和独立 WSL 环境；旧工作站运行时请先保存关闭，再启动新版。
