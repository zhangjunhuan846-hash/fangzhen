# v0.3.6：环境与经济评价接入

本版基于用户最新的 v0.3.5 加入“环境与经济评价”入口。保留 EIS、Parquet、有限候选 MC-NEHVI、区间校准及原有数据录入与仿真功能。

## 如何使用

1. 结束旧版正在运行的任务，关闭旧程序，再双击项目根目录 `启动科研工作站.bat`。
2. 打开“环境与经济评价”→“我的石墨工艺”。填写名称、合格产量、地域、价格依据、系统边界及数据性质，可以关联本方案的处理工艺样品。
3. 逐项录入电力、药剂、气体、运输等实际消耗量，明确单位、单位成本、碳足迹因子及其来源。支持 CSV 导入和空白模板；空值不会自动替换为零。人工、设备等批次费用需单独填写，也要说明依据。
4. 点击“计算并归档”。可以查看每 kg 合格再生石墨的碳足迹与成本、批次总量和消耗项贡献，下载输入/结果 JSON、贡献 CSV 或科研报告。

“加载合成校验例”用于检查软件计算：4 kWh × 0.8 CNY/kWh + 0.2 kg × 10 CNY/kg + 3 CNY = 8.2 CNY；4 × 0.5 + 0.2 × 2 = 2.4 kg CO₂e。合格产量为 1 kg，单位产品结果相同。这些是假设值，不是回收石墨的实验或文献结果。

“EverBatt参考案例”提供六个上游预设。选择案例并声明采用其工艺、产能和价格假设后运行。默认湿法黑粉参考成本为 5.08192735237198 USD/kg 投入废料。这种功能单位不同于“我的石墨工艺”的 kg 合格产品，结果不能直接混合比较。

## 接入的计算模型

### Brightway

[Brightway bw2calc](https://github.com/brightway-lca/brightway2-calc) 2.5.0、[bw2data](https://github.com/brightway-lca/brightway2-data) 4.7。每项消耗作为前景过程，采用用户给出的聚合 GWP 因子。实际执行 Brightway LCI/LCIA，并与透明清单核算交叉验证；数据库位于每次任务的 `assessment/brightway` 中。

当前结果是所声明边界内的 **GWP 和工艺成本筛选**。前景模型已接入计算引擎，背景工艺数据库尚需配置；也尚未实现多类别影响评价、分配/避免负担、完整资本投资与现金流 TEA。背景数据库和价格不能由程序任意填入。成本路径采用清单和明确录入的批次费用核算。

### EverBatt 社区迁移模型

[zhouzhq2021/recycle_cost_tool](https://github.com/zhouzhq2021/recycle_cost_tool)，固定源码提交 `e834058d2b361c8009fe53bd73347d84b17b4704`。接入 Python 核心，调用原有预设和计算表；不需要启动其 Streamlit 界面。成本、收入、能耗、用水、排放均保留上游单位和假设。

该仓库是社区 Python 迁移，不是本平台对 Argonne 官方 EverBatt 的全面复现认证。六个预设涉及 NMC 整电池、黑粉或制造废料，不能替代你的纯石墨再生流程。源码 MIT 许可与原工作簿、背景数据的使用条件分别记录；原模型保存在本机 `data/backends/recycle_cost_tool_e834058`，未捆绑进入桌面发行目录。每次运行校验源文件 SHA256，并将源码提交、文件哈希和依赖版本写入结果。

## 环境与数据

已经安装独立 Windows Python 环境 `data/runtime/sustainability`，不修改 WSL PyBaMM/PyBOP 环境。依赖固定为 bw2calc 2.5.0、bw2data 4.7、NumPy 2.5.4、Pandas 3.0.6、SciPy 1.18.1、openpyxl 3.1.5。

如需在本机重装，运行 `安装环境与经济评价.bat`；需要 Python 3.13 或更新版及联网。安装脚本不会把本机已改变的上游源码重新认证为原提交：现有文件与记录的哈希不符时停止。

新版默认数据目录 `data/workbench_scalar7`。首次启动优先通过 SQLite 备份接口复制 v0.3.5 的 `data/workbench_scalar6`，保存 `升级前备份.sqlite`，并复制 jobs/imports/exports。原库与原发行版保留。只有新版目录尚无数据库时迁移，因此使用新版后继续修改旧版的数据，不会再次自动合并。

评价任务保存规范化输入、所关联方案的版本快照、原始导入 CSV 与 SHA256、运行日志、结果及贡献表。可以复用任务输入，但新运行会建立新归档。

## 验证记录

- Windows：50 项相关测试通过；1 项 PyBaMM 运行测试留给原 WSL 环境；2 项需原科学依赖的 EIS/Parquet 测试未在独立评价环境执行。
- 原 WSL 科学环境：28 项 EIS、Parquet、MC-NEHVI、自有参数半电池与数据迁移相关测试通过；部分测试与 Windows 检查重叠。
- JavaScript 语法检查通过，新桌面 exe 成功构建。
- 真实桌面 exe + 隔离数据：清单导入、Brightway 求解、按合格产量归一、6 个上游预设、下载输入/结果/贡献、科研报告及原有 EIS 导入通过。
- 隔离迁移：旧库不变，标量表征字段和 jobs/imports/exports 档案保留，新版建立备份。
- 浏览器界面：合成校验例实际显示 8.2 CNY/kg 与 2.4 kg CO₂e/kg；参考假设未声明时阻止提交，声明后成功调用后端。

详见 `outputs/sustainability_v036_20261013/verification.json`、`verify_packaged.py` 与 `packaged_report.html`。测试均使用隔离数据目录，没有把软件算例写入用户研究方案。软件基准不替代实物实验验证。
