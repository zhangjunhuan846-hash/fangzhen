# 面向 EIS + BMS 的 GitHub 接入选择与本轮交付

> 本文保留v0.3.11时点的检索与缺口判断；v0.3.12已接通工程扩展，当前实现、验证和新增论文见[工程接入更新](engineering_integrations_v0312_20261029.md)。

核对日期：2026-10-29。上游 README、许可说明及选中项目源码通过 GitHub 实际读取；不以星数作为工程适用性的证明。

老师的截图表达了三个目标：基于有工程背景的电池做仿真优化，最终形成硬件与 EIS/BMS 配套软件，先把完整仿真链做起来。对当前平台，优先补齐实测谱分析，再做固定工况参数到时域电路的验证，随后进入电池包与控制器联调。

## 项目选择

| 项目与原始来源 | 可补的平台能力 | 接入判断与下一步验收 | 本轮状态 |
| --- | --- | --- | --- |
| [impedance.py](https://github.com/ECSHackWeek/impedance.py) | Lin-KK 一致性诊断、等效电路参数拟合 | 直接接现有 EIS CSV 与任务队列；使用 MIT 许可的软件包，通过数值恢复与实际后台任务验收 | **已接入**；固定 `impedance==1.7.1` |
| [thevenin](https://github.com/NatLabRockies/thevenin) | 含 RC 支路、SOC、温度和滞后的时域等效电路；逐步状态预测接口 | **建议下一项**。将同一电芯、SOC/温度条件下的 RC 参数组织成表，补 OCV/容量与脉冲留出数据；先验证时域电压。其预测接口本身不等于完整 SOC/SOH 估计算法 | 已核对，尚未安装或接入 |
| [PyProBE](https://github.com/ImperialCollegeLondon/PyProBE) | 电池测试仪数据处理，按实验、循环与工步筛选 | 当测试仪原始导出成为瓶颈时接入；先用实际仪器文件核对列名、量纲与电流符号。PyPI 名称为 `PyProBE-Data`，与现有 CSV 接口互补 | 已核对，尚未接入 |
| [liionpack](https://github.com/pybamm-team/liionpack) | 将 PyBaMM 单体模型组织成串并联电池包与网络 | 先独立环境验证 PyBaMM 版本兼容，再比较单体退化回放和小型串并联电流分配。上游 README 明确处于 maintenance mode，仍维护关键问题与兼容性，不再新增功能 | 候选，尚未接入 |
| [foxBMS 2](https://github.com/foxBMS/foxbms-2) | 开源 BMS 硬件、嵌入式软件及工具链 | 硬件确定后作为控制器联调候选。软件 BSD-3-Clause；硬件与文档 CC-BY-4.0。需要匹配 MCU、采集芯片、通信报文与实物，不能作为普通 Python 插件直接接通 | 架构参考，尚未连接硬件 |

已有 PyBaMM、PyBOP 和原生 `EISSimulation` 继续负责物理模型与原有辨识任务。现有仓库曾下载 PyBOP、pybamm-eis、EP-BOLFI 的专利检索快照；下载快照不等于已经接入工作站。

## 本轮交付：工作站 v0.3.11

可先使用 [合成演示谱](../examples/eis_rc_demo/README.md) 检查软件通路。入口保持为根目录 `启动科研工作站.bat`，在“论文方法 / EIS校准”选择 EIS。选择 CSV、Hz/rad/s 与 Ω/mΩ，确认虚部列的符号，再运行“Lin-KK与RC拟合”。本轮构建的程序位于 `outputs/fangzhen_workbench_ui_v0311_ready/FangzhenResearch/FangzhenResearch.exe`。

- 支持 `R0-p(R1,C1)` 和 `R0-p(R1,C1)-p(R2,C2)`，可填写初值；初值留空时由输入谱生成并随结果保存。
- 每次明确选择一条谱；多谱文件使用 `spectrum_id`。所选谱保留全部频点，重复频率报错，程序不自动平均或删除。
- 可选模值归一或等权拟合。结果显示 R/C、局部标准误、复阻抗 RMSE、归一 RMS、Lin-KK 重构和残差判定。
- 页面叠加输入谱、RC 拟合与 Lin-KK 重构；支持逐点拟合/残差 CSV、参数 CSV、完整 JSON 下载。
- 保留原始 CSV、配置、方案版本、文件 SHA-256、实际软件版本及适配器/上游算法源码哈希。
- Lin-KK 默认使用预先按点数确定的固定网格阶数 `M=min(20,n//3)`，也可显式选上游自动 μ 截止（c=0.85，最多30支路）。默认残差参考阈值为 0.02，可明确修改。固定网格可能欠/过拟合，自动截止也可能在宽频带理想RC谱上提前停止；结果保留阶数、μ与残差，不据此认证测量有效性。

实现为 `user_tools/workbench/eis_fit.py` 的可选适配器，未改动 `battery_sim/` 冻结内核。依赖在已有 WSL `pybamm` 环境安装，NumPy 与 PyBaMM 版本保持；Windows 工作站只负责校验、提交与显示。依赖声明单列在 `requirements-eis.txt`。

### 环境与兼容处理

在已按根目录 `requirements.txt` 配置的 WSL 环境中：

```bash
python -m pip install -r requirements.txt -r requirements-eis.txt
```

`impedance==1.7.1` 的 Lin-KK 实现将 NumPy 标量拼入内部求值表达式。NumPy 2 的标量表示包含 `np.float64(...)`，该版本缺少对应求值命名空间。适配器在调用期间临时提供 NumPy 名称，并在 `finally` 中恢复；未改写安装包或冻结模型，兼容处理写入结果。仅允许预定义 RC 电路，界面不会将任意电路字符串交给上游求值器。

### 复现与验收

数值测试使用独立解析公式生成 RC 谱，检查单/双支路参数恢复、单位与符号转换、异常谱残差、重复频率、多谱选择及提交后文件变动拒绝。实际通过项数与日期记录在 [STATUS.md](../STATUS.md)。

```bash
python -m pytest tests/test_eis_fit.py tests/test_workbench.py tests/test_workbench_pipeline.py tests/test_paper_methods.py tests/test_module_manifest.py tests/test_module_graph.py -q
```

Windows 实际 HTTP → WSL → 下载链验收使用独立 `--data` 目录，避免将合成算例混入实验方案：

```powershell
python -m user_tools.research_workbench --data outputs/workbench_eis_tests_20261029 --no-browser
# 另一个终端执行；它读取上面实例的 session.json
python -m user_tools.workbench.smoke_eis outputs/workbench_eis_tests_20261029
```

完整 RC 拟合产物与验收记录保存在上述目录的 `jobs/` 和 `eis_verification.json`。该验收是合成软件通路，不是实测材料或工业 BMS 验证。

## 下一步如何连成老师要求的平台

1. 选定明确型号的商业电芯，记录化学体系、容量、OCV、SOC/温度、EIS 测量条件和脉冲工况；“工业级”需要具体型号与工程验证指标。
2. 对每个条件单独做谱诊断和电路拟合，检查电路结构适用性。低频扩散、感抗或明显压扁的弧未必能由当前理想 RC 电路描述；残差高应保留失败信息。
3. 接 thevenin，先用同条件脉冲数据校核时域电压，再做 SOC 估计与独立工况验证。单张 EIS 谱的 RC 参数不直接代表跨 SOC/温度的 BMS 参数表。
4. 验证串并联与单体差异后接电池包层；确认实物和协议后做 foxBMS/CAN 联调。仅浏览 GitHub 不能证明现成驱动已适配用户设备。

RC 参数目前不会自动写成 PyBaMM 的扩散系数、交换电流密度或材料常数；结果明确记录 `material_validation=false`、`parameter_identifiability=not_assessed`。这些字段服务后续实验判定，不阻止查看局部拟合结果。

## 上游读取凭据

以下为实际读取的 README Git blob SHA，可用于重新获取本次比较所依据的文件；这是文件版本标识，不是对整个仓库兼容性的证明。

| 仓库 | 默认分支 | README blob SHA |
| --- | --- | --- |
| ECSHackWeek/impedance.py | main | `6e8c29c951ed1fc15be02ca509cf764f92765f05` |
| NatLabRockies/thevenin | main | `b78e37ec1e807c55504720639df0ac8dcc5b884a` |
| ImperialCollegeLondon/PyProBE | main | `f4b6f61d7f1cb2ea0d9e8dfc93a8362b496373e3` |
| pybamm-team/liionpack | develop | `ccb94d68e13441cfdebd82503942cd1be8cff614` |
| foxBMS/foxbms-2 | master | `c5fac5d34e255fe2bc659a566c5417a5d197ecca` |

选中包还核对了 [Lin-KK](https://github.com/ECSHackWeek/impedance.py/blob/main/impedance/validation.py)、[电路接口](https://github.com/ECSHackWeek/impedance.py/blob/main/impedance/models/circuits/circuits.py)、[拟合与权重实现](https://github.com/ECSHackWeek/impedance.py/blob/main/impedance/models/circuits/fitting.py)及 [MIT 许可](https://github.com/ECSHackWeek/impedance.py/blob/main/LICENSE)。最终运行以固定 PyPI 包与输出的实际源码哈希为准。
