# 钠电 SOH 跨电芯与数据来源验证

## 新公开数据与转换

在此前 Wenzhou 四只钠电芯之外，下载了 [BatteryLife 原始 Na-ion 数据](https://huggingface.co/datasets/Battery-Life/BatteryLife_Raw/tree/main/NAion)的十只电芯；该数据集记录为 1 Ah、18650、25°C，电极与电解液具体组成未公开，不假定与 Chayambuka 参考电芯一致。引用 Tan 等 [BatteryLife, KDD 2025](https://doi.org/10.1145/3711896.3737372)。

每只电芯的第一循环放电容量作为假设已知的参考值，选取第一循环之后每第五个循环，充电窗口固定为 3.0–3.6 V；标签为同一循环后续放电容量除以第一循环放电容量，仅用于离线训练和评估。每条曲线最多取 100 个时间有序点；保留原始文件 SHA-256、排除记录和口径。Wenzhou 数据沿用此前的同口径处理，明确参考值和单位。两类数据在额定容量、倍率、测试条件以及来源方面明显不同，不保证化学体系相同。

转换脚本：`user_tools/prepare_batterylife_sodium.py`；文件和哈希：`outputs/sodium_validation/batterylife/provenance.json`。不得把第一循环的未来放电容量当作第一循环充电之前已知的信息；本次已排除第一循环充电片段。

## 改动

1. 增加 `feature_mode=reference_normalized`：输入需包括每只电芯预先测得的 `reference_capacity_Ah`；窗口电量和中间时间积分按该参考容量归一化，并记录充电倍率。默认仍是原始特征，旧模型兼容。
2. 材料硬碳和 SOH 的分组训练增加实际 GPR、CPU XGBoost 与 CatBoost，使用独立环境；与均值、岭回归、Extra Trees 按训练电芯组交叉验证比较。用于分组选择的误差及最终留出测试分开计算。可选 `selection_policy=worst_group` 做最差组选择实验，不默认声称能提高泛化。
3. 新增联合特征域外检查。使用训练数据的预处理器，将训练电芯逐一拿掉，计算该电芯到其他电芯的最近样本距离；以各电芯 95% 分位的 95% 分位作为阈值。预测超过该阈值时同时输出原模型结果和训练均值回退，并标记回退来源。阈值是启发式而非置信保证，也不能替代其他电芯数据。
4. 长时钠电 DFN 请求遇到 PyBaMM 插值边界时，默认只返回已成功求解的边界前区间，清楚标记提前结束；`extrapolation_policy=error` 可保留严格报错。1C、25°C 请求 3600 秒时约在 2536 秒前停止。0.1C、0.6C 运行到 3600 秒；1.2C、1.4C 分别约在 2008、640 秒前停止。它们是软件参考仿真，未完成对应实测验证。

## 结果：同来源和混合训练，按电芯留出

两个来源共 14 只电芯、707 个符合窗口的片段。将其混合，每次留出一只电芯，使用其余电芯的分组交叉验证选择六个预设模型之一，再预测留出的整只电芯；同一电芯的所有片段始终在同一侧。以下 MAE 为逐电芯等权平均，单位为 SOH **百分点**：

| 留出来源 | 电芯数 | 原始模型 MAE | 联合偏移保护后 MAE | 训练均值基线 MAE |
|---|---:|---:|---:|---:|
| Wenzhou | 4 | 0.51 | 0.53 | 3.69 |
| BatteryLife | 10 | 3.68 | 1.40 | 4.45 |

BatteryLife 的一只电芯上，GPR 原始误差约 28.99 个百分点；该电芯所有片段触发联合域外检测，回退后约 6.10 个百分点。Wenzhou 的 3 个片段也触发，造成该来源平均误差从 0.51 增至 0.53。两组数据已参与此前探索和方法选择，故这些是探索性逐电芯验证，非完全独立的前瞻性验证。

完整逐折结果保存在 `outputs/sodium_validation/pooled_loco_wenzhou_mean_group.json` 和 `pooled_loco_batterylife_mean_group.json`，每折均含留出组、交叉验证模型、误差及触发数量。脚本 `user_tools/benchmark_sodium_pooled.py` 可重算。尝试以训练组最差 MAE 选择模型时，Wenzhou 平均误差 1.33、BatteryLife 6.06 个百分点，未优于默认方案；不采用它作为默认。

## 零样本跨来源测试

另一次先只用 BatteryLife 的七只训练电芯选择并训练模型，把三只 BatteryLife 电芯和全部 Wenzhou 电芯保留在训练外。对于后者的四只电芯，直接预测平均 MAE 为 **9.94 个百分点**；联合域外规则全部触发，回退均值后为 **4.43 个百分点**，即训练均值基线。单电芯提供第一次已知 SOH 后的偏移校准平均误差为 8.09 个百分点，直接沿用该已知 SOH 的基线为 8.19。该校准没有充分解决域偏移。见 `outputs/sodium_validation/batterylife/cross_anchor_wenzhou.json` 和脚本 `user_tools/validate_sodium_transfer.py`。

因此，目前仅可说归一化和混合训练在这些逐电芯留出探索中有帮助；**未证明零样本跨实验室/跨化学体系泛化**。联合域外标记只提供一种异常提示，触发时的均值是保守基线，不是可信的个体电芯 SOH。仍需新数据来源、不同温度/倍率、独立电芯和标准化容量测试验证。

## 新手段清单的当前边界

- XGBoost、CatBoost、GPR：已接到硬碳及部分充电 SOH 分组训练；原有通用描述符页面也已有 GPR，但不是所有机器学习任务都自动使用新算法。
- Permutation Importance：原有描述符模型有留出置换重要性；SHAP 未接入。
- 基础独立组 split conformal：原有描述符模型提供；RSA-CP、KMM-CP 未实现。新增联合偏移筛查不是 KMM-CP。
- MOBO、成本感知与多保真：工程页面有 BoTorch qLogNEHVI、MF-KG/MF-MES 及成本模型等有限范围适配，具体条件见 `docs/engineering_integrations_v0312_20261029.md`；不能视为已针对用户钠电实验完成闭环验证。
- PyBaMM/PyBOP、PyProBE、impedance.py：平台已有；钠电 DFN 是 Chayambuka 参考前向模型，钠电 PyBOP 辨识及实测倍率验证尚未完成。
- TabPFN、TabICLv2、SHAP、RSA-CP、KMM-CP、Ax、HELAO 的指定原版工作流当前没有接入。HELAO 仪器控制也没有上线。
