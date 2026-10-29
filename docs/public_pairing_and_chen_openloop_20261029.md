# 公开电芯数据配对审计与 Chen2020 开环验证

## CALB 数据核查

来源：[CALB L148N58A V2](https://doi.org/10.17632/ycx459r5c3.2)。本轮从已保存的发布清单检查 11 颗电芯、3 个温度、8 类测试，共 264 个 MAT 文件；逐文件 SHA-256 与清单匹配，零失败。表格包含电芯、温度设定点、文件、哈希、采样、温度范围、脉冲电流与时间字段状态。数据和清单源自先前下载，本轮核对的是本地文件与当时保存的发布者哈希。

例如电芯 60129、25°C，8–12 秒放电脉冲的中位幅值在 `hppc_1c` 为 58.00 A，在 `hppc_c3` 为 19.32 A。因此现有拟合脚本以实际电流幅值区分 1C / C/3 的处理与这两份文件一致；不要只根据目录文案判断。CALB 原始电流放电为负，BMS 回放代码转换为放电为正。

动态工况的初始电压不同。现有程序使用同电芯 C/20 放电电压曲线进行初始 SOC 代理估计，再积分电流；不是将所有工况初始化到 100%，也不等同直接测得真实 SOC。C/20 本身含极化及路径依赖，不能当作精确平衡 OCV。

**重要限制：**处理后 MAT 的 `Times` 是各文件内部时间，不能用数值跨文件排序；本轮没有取得原始 XLSX 的绝对时间，不将相同编号和温度视为严格的同状态配对证明。此前 EIS 晚于脉冲和驾驶的判断基于数据集实验协议，不能由本表独立确认。因此此前 60129 的 EIS→脉冲回放仍只能标为回顾性验证。要完成前瞻性案例，须核对原始时间、诊断阶段、SOC 建立方法与老化状态。

## Chen2020 三电芯、四倍率的 SPM/SPMe/DFN

三个原始文件的 MD5 与 [Zenodo 发布记录](https://doi.org/10.5281/zenodo.4032561)核对一致。用平台已有适配器提取 02/03/04 电芯的 C/10、C/2、1C、1.5C 放电，对每条曲线用实测电流驱动三个 PyBaMM 模型，生成 36 组开环电压回放，全部求解成功。模型在回放期间不使用实测电压更新状态；每条放电初始化 SOC=1、箱温使用该放电期间中位值、采用等温模型；未重放先前充电和静置历史。此实验是模型对照，不是热模型验证，也不是容量预测。Chen2020 参数与 LG M50 同体系且相关，因此不是完全独立数据集。

例如电芯 02 的时间对齐电压 RMSE（mV）：

| 模型 | C/10 | C/2 | 1C | 1.5C |
|---|---:|---:|---:|---:|
| SPM | 92.53 | 144.82 | 134.81 | 131.05 |
| SPMe | 88.05 | 123.88 | 81.80 | 48.04 |
| DFN | 87.99 | 123.54 | 79.06 | 44.40 |

这是**开环电压误差**，不能与 BMS EKF 基于此前实测电压反馈的一步预测残差直接等同。比较仅计算实验和仿真的共同时间，1.5C 的 DFN 覆盖约 99.7%；所有结果应同时查看覆盖率，不能把被截掉的尾部当成成功预测。

## 小范围参数探索和反例

仅以 02 的 C/2 曲线为开发集，调整 DFN 的负极活性材料体积分数这一有效参数，范围为原值的 0.9–1.05 倍；目标为电压 RMSE 加提前终止惩罚。优化得到 0.7278，随后固定，比较 03、04 的四个倍率。对照使用完全相同的共同时间点：

| 电芯 | 工况 | 原参数 RMSE | 调整后 RMSE | 调整后时间覆盖 |
|---|---|---:|---:|---:|
| 03 | C/2 | 120.02 mV | 46.49 mV | 99.99% |
| 04 | C/2 | 114.07 mV | 46.03 mV | 99.91% |
| 03 | 1.5C | 37.71 mV | 76.25 mV | 96.65% |
| 04 | 1.5C | 35.80 mV | 74.38 mV | 96.82% |

因此单倍率调参存在明显权衡；该参数**没有替换平台默认值**，也不能解释为材料真实体积分数。各电芯、倍率此前已经用于基线探索，虽然该次优化未使用 03/04 曲线，这不是全程盲测。应进一步使用多个开发倍率、固定不同电芯/工况、严格报告截断和误差，再考虑部署。

## Stanford W8：初步可按时间配对，但 EIS 筛查尚未通过

通过 [Stanford 作者入口](https://onorilab.stanford.edu/products/code-and-data-set)指向的 [OSF 数据集](https://osf.io/qsabn/) Dropbox 目录，仅获取 W8 电芯 `Diag_1` 容量、HPPC、20/50/80% SOC EIS，以及 `Cycling_1` 第一段动态记录共 6 个原始 XLSX。各文件记录本地 SHA-256；该 Dropbox 接口没有提供发布方哈希，所以不能称为发布方哈希验证。

原始 `Channel` 工作表中的时间显示：20/50/80% EIS 分别于 2020-05-30、05-31、06-01；容量测试 06-01 至 06-02；HPPC 06-02 至 06-03；动态记录 06-05 至 06-06。它们来自同一电芯，且表征日期早于这段动态记录，具备继续研究前瞻验证的时间条件；仅凭日期仍不能保证 SOC、温度、静置与老化状态完全匹配。

将 20%、80% 的 EIS 接入平台现有网格拟合，50% 留作谱插值检查，23°C 是标称温度。全频段 1RC/2RC 都未通过 Lin-KK，50% 相对 RMS 约 25%；检查发现高频有明显正虚部，现有纯 RC 模型不包含感性环节。探索性限制到 500 Hz 后，1RC/2RC 的留出谱相对 RMS 约 5%/4%，但 Lin-KK 仍因模型复杂度截断条件未满足而未通过（并非仅看残差很小即判定通过）。留出谱已用于这次频带探索，不能再作为全新盲测试。

因此系统正确拒绝将该网格桥接为 BMS 参数；**尚未完成该电芯的 EIS→HPPC→动态电压/SOC 预测**。下一步要查明 Lin-KK 判据与有限频点的适用性、测试感性支路或其他 EIS 模型，并用独立数据确认；不能直接绕过筛查。绝对时间表和 EIS 输入可分别查看 `outputs/eis_bms_validation/stanford_aging_w8_audit_20261029/`、`outputs/eis_bms_validation/stanford_aging_w8_eis_20261029/`。

## 文件与复现

```text
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.audit_calb_pairing_20261029
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.validate_chen2020_openloop_20261029
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.calibrate_chen2020_development_20261029
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.fetch_stanford_aging_case_20261029
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.audit_stanford_aging_case_20261029
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.validate_stanford_aging_w8_eis_20261029
```

CALB 表和限制：`outputs/eis_bms_validation/calb_pairing_audit_20261029/`；Chen 的逐点曲线、指标和哈希：`outputs/chen2020_openloop_20261029/`；调参记录、冻结参数与共同区间曲线：`outputs/chen2020_development_20261029/`。这些可复现脚本与现有平台计算模块相连，但本轮没有给桌面工作站增加新按钮。
