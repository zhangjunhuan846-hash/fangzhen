# 低温 OCV、跨电芯与 EIS→BMS 验证

## 数据和实验边界

- [CALB L148N58A V2](https://doi.org/10.17632/ycx459r5c3.2)：11 个方形电芯、10/25/40°C、C/20、HPPC、驾驶与 EIS。此前 8 电芯的文件和另外 3 个电芯文件按 Mendeley 发布的 SHA-256 核验。
- [McMaster Tesla 2170 公开数据](https://doi.org/10.5683/SP3/ZVTR4B)：使用 3 个开放电芯、−20/−10/0/10/25°C 的 C/20、HPPC 和重排驾驶记录。数据自带基于 40°C 容量测量与电流积分的 SOC 参考，不是直接 SOC 仪器读数。温度为箱温设定点。[数据说明](https://batterysocbenchmark.ca/dataset)也指出部分低温测试重新进行过，时间戳与原表不同。
- Tesla 发布的是约 705 MB 的 ZIP，本次通过 HTTP Range 读取所需条目；对每个条目验证 ZIP CRC 并保存本地 SHA-256。**没有下载全 ZIP，因此没有独立核对发布方的整包 MD5**。额外驾驶记录与首次提取的清单分别保存，不使用盲测数据。
- 每个驾驶窗口初始 SOC 设置为其参考值减 4 个百分点，是受控初态误差测试。Tesla 每窗口 1800 秒，CALB 每窗口 600 秒；SOC 指标不代表未知初态时的完整循环表现。单步电压可使用此前电压，开环电压在初始化后不读取电压。

## CALB：无目标 HPPC 标定的跨电芯预测

使用 59294、59485、59627、59690、60129、60403 六个源电芯的同温 HPPC，按 SOC/温度分别取参数中位数。60644、60710 的驾驶记录用于选择是否引入温度 OCV/RC，最后在 59861、60031、60195 三个目标电芯上评分。**目标电芯的 HPPC 不参与模型构建**；其 C/20 数据仅用于生成 SOC 代理参考和按参考值设定的窗口初态，所以这不是不依赖目标数据的盲初态测试。

开发集按单步电压误差选择温度相关 RC。新电芯的 54 个窗口全部完成：

| 模型 | 单步电压 RMSE | SOC 代理 RMSE |
|---|---:|---:|
| 固定 25°C OCV 与 RC | 6.865 mV | 3.043 个百分点 |
| 开发选择：温度相关 RC、25°C OCV | 3.863 mV | 2.308 个百分点 |

按温度看，10°C 电压误差从 12.41 降到 5.78 mV；25°C 两者相同；40°C 从 4.78 降到 2.40 mV，但 40°C SOC 代理误差从 0.94 升到 1.40 个百分点。温度 OCV 单独候选有 1/54 窗口因 UKF 采样点超出已测网格而明确失败；仅用成功窗口算的均值不能与 54/54 的方法直接等同。第一次测试在 59861 早期窗口发现该边界失败后，程序改为记录失败和覆盖率，不通过外推或删去该窗口掩盖问题；该电芯部分结果因此在完整重跑前已被查看，选型仍来自开发电芯。

## Tesla：低温 OCV 和 RC

用 m80 的 C/20 和 1C HPPC 拟合温度 OCV / RC，在 m448-N 的 20 个开发窗口比较固定 25°C 基线、温度 C/20、按 `I×(R0+R1)` 一倍/两倍修正和 HPPC 静置电压。补偿是小电流极化的**经验近似**，其中两倍系数由开发集选择，不是经过验证的平衡 OCV 公式。40°C 的一个 m80 C/20 文件所记录的电芯温度约为 24–26°C，本次不将它冒充 40°C OCV，验证范围截止 25°C。

低温候选使用单独 EKF 和有记录的 SOC 边界投影，避免查询已测 SOC 网格以外的 OCV；投影不修正协方差，是近似处理。开发集在完整覆盖且投影步数不超过 5% 的候选中选择单步电压误差最低者，并在读取 m1000 的 `REORDERED7/8` 信号前冻结。m1000 的 `REORDERED5/6` 已在前一轮比较中使用，所以这次是**同一目标电芯的新驾驶记录**，不是新的独立电芯。

| m1000，20 个新驾驶窗口平均 | 固定 25°C 基线 | 开发选择的温度 OCV/RC |
|---|---:|---:|
| EKF 单步电压 RMSE | 86.44 mV | 49.09 mV |
| 开环电压 RMSE | 142.26 mV | 57.47 mV |
| SOC 参考 RMSE | 21.58 个百分点 | 4.98 个百分点 |
| SOC 投影步数占比 | 7.35% | 0.26% |

这些平均值混合五个温度，仅涉及一个目标电芯。−20°C 仍未解决：选择模型的平均单步电压误差约 128 mV、SOC 参考误差约 8.82 个百分点，投影步数约 1.28%；而 25°C 的 SOC 参考误差从 1.25 增至 3.11 个百分点。选型根据开发集**电压**指标，不应把测试结果当作所有目标均提升。原本同时执行 UKF 的严格网格版本在部分低温窗口因采样点越界失败，失败和覆盖率保存在 `tesla_cold_20261029/`，未作外推。

## EIS → BMS 实际链路及其限制

CALB 电芯 60129 的 10/25/40°C 全网格中，12 条谱只有 11 条通过既定 Lin-KK 筛查，故程序拒绝桥接；另外两颗完整网格电芯的通过谱数均为 8/12。对 60129，只研究 25–40°C 范围时，该范围 8/8 谱通过筛查；2RC 的四条留出谱平均频域相对 RMS 为 4.20%，软件将该参数表经同电芯和哈希检查桥接到滤波器，并运行了 6 条独立 C/3 脉冲窗口。

2RC EIS 网格的单步电压平均误差为 3.744 mV，同窗口 1RC HPPC 基线为 3.808 mV；差异很小，不足以宣称 EIS 明显优于脉冲标定。该 EIS 在脉冲测试**之后**获取，因此只是回顾性连通验证；四条谱根据协议与时间顺序使用标称 80/60/40/20% SOC，20% 标称谱的 C/20 电压推算约 16.3–16.5%，SOC 标签差异另存 `soc_label_audit.csv`。不得将此链路当成同状态、事前预测或硬件认证。

可导入工作站 EIS 入口的文件位于 `outputs/eis_bms_validation/calb_eis_pulse_20261029/60129-25_40C/eis_input.csv`，选择 2RC、`log_invT`、0.5–1000 Hz，来源填写 CALB DOI。完成 EIS 网格后可按原有同方案、同电芯筛查桥接到 BMS；OCV、容量和温度仍需单独提供。

同一目录还提供 `eis_config.json`、`bms_config.json` 和 `bms_pulse_input.csv`，对应已跑通的 25°C 脉冲示例：先用 EIS 配置和谱 CSV 创建任务，再切换“电热模型与SOC估计”，粘贴 BMS 配置、上传脉冲 CSV、选择该 EIS 网格并勾选同电芯。示例声明等温并使用测试温度设定点；`soc_reference` 是库仑积分代理。完整程序回放存于 `bms_end_to_end/`，不是硬件回放。

## 工作站和复现

工作站工程任务新增“CALB跨电芯温度OCV与RC验证”和“Tesla低温OCV补偿与跨电芯验证”，可导出配置、逐窗口指标、逐点轨迹和模型/验证 JSON。BMS 配置增加 `filter_ocv_mode`、`enable_ukf` 和 `soc_constraint`；默认保留原来的 SOC-only OCV、UKF 开启、严格边界。`project` 仅供 EKF，次数写入结果，不适合作为已经验证的设备保护策略。当前电芯仿真 plant 的 OCV 仍使用声明的 SOC-only 曲线；SOC×温度表只作用于滤波器。

```text
python user_tools/fetch_calb_matched.py --extra3
python user_tools/fetch_soc_benchmark.py --fetch
python user_tools/fetch_soc_benchmark.py --holdout2
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m user_tools.validate_calb_eis_bms --cell 60129 --warm-only
wsl -e /home/zjh/.local/share/fangzhen/engineering/bin/python -m pytest tests/test_calb_validation.py tests/test_engineering_eis_grid.py tests/test_engineering.py -q
```

每项任务保存程序快照和参数来源。CALB 结果在 `outputs/eis_bms_validation/calb_crosscell_20261029/`，Tesla 结果在 `outputs/eis_bms_validation/tesla_refined_20261029/`。下一步应增加独立低温电芯和不借助参考 SOC 的完整记录，获取时间顺序为 EIS→脉冲→驾驶的同状态数据，并研究两 RC / 极化及温度传感误差；−20°C 的误差仍不足以用于实物控制。
