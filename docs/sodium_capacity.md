# 钠电公开数据与容量衰退预测

双击项目根目录的「启动科研工作站.bat」，选择左侧「容量衰退预测」。选数据集、电芯或轨迹、算法和训练截止循环，在「预测区间」选择 80%、90%（默认）、95% 或「仅点预测」，点击「预测容量」。默认截止点对应最早约 70% 的观测。想检验区间，保留截止点后的实测数据。想从最新记录预测未来，把截止设为最后实测循环，并填写外推圈数。

从 GitHub 克隆后，使用 Python 3.11 或更高版本可以直接运行 `python -m user_tools.research_workbench`。顶部数据框会列出随仓库提供的三套逐循环容量表，共 143 条轨迹、84,347 个观测。线性、平方根与末次容量算法可直接运行。复现下文的 NumPy 算例时，在同一个 Python 环境中执行 `python -m pip install numpy`。比萨大学 Hakadi 数据可按下文从作者仓库下载并生成第四套容量表。

紫线显示训练实测，绿线显示留出实测，橙色虚线显示容量预测，浅橙色区域显示逐圈预测区间。MAE 和 RMSE 在留出实测点上计算，单位是 Ah。页面也给出沿用最后一个训练容量的基线误差。可下载输入 CSV、逐点预测 CSV 和带来源、输入哈希、算法版本及训练范围的 JSON。每次运行保存到当前方案。

## 复现一次 90% 区间预测

选择 BatteryLife、轨迹 `270040-1-1-64`、算法「NumPy 二次多项式」，设训练截止 63、末次实测后外推 10、预测区间 90%。模型使用第 1–63 圈的数据。第 64–91 圈的 28 个留出实测值全部落在区间内，平均区间宽度为 19.85 mAh。第 92–101 圈是未来预测，第 92 圈的点预测为 0.7694 Ah，上下限为 0.7406 和 0.7982 Ah。以下文件从 Windows 工作站页面导出。[曲线图](../outputs/sodium_capacity_forecast/区间90_270040-1-1-64.png) · [逐圈 CSV](../outputs/sodium_capacity_forecast/区间90_270040-1-1-64.csv) · [运行记录](../outputs/sodium_capacity_forecast/区间90_270040-1-1-64.json)

在同一数据集的 69 条文件轨迹上，各用最早约 70% 的观测训练，使用相同算法和 90% 目标水平。按留出测量点合计，3,990 个点都有上下限，3,494 个落入区间，实测覆盖率为 87.6%。这是同一条轨迹沿循环方向预测后续容量的验证。实际覆盖率随轨迹、算法与外推跨度变化。[逐轨迹回测结果](../outputs/sodium_capacity_forecast/区间90_逐轨迹回测.csv)

平台在每条轨迹的训练段内选取至多 64 个历史起点，用截至各起点的容量拟合所选算法，再与当时往后各跨度的实测容量比较。最早的拟合使用至少 3 个观测和训练段的 20%（向上取整）。给定目标循环，以最后一个训练观测为起点，取相同循环跨度的历史绝对误差。对于 `m` 个误差和目标覆盖率 `p`，将误差升序排列，取第 `ceil((m+1) × p)` 个作为区间半宽，下限最低为零。截止点以后的实测容量只用于最后的回测。相邻循环的误差可能相关，页面给出的覆盖率是按点计算的经验结果。[Hyndman 与 Athanasopoulos 的时间序列交叉验证方法](https://otexts.com/fpp3/tscv.html) · [Barber 等关于数据分布变化与覆盖率的讨论](https://arxiv.org/abs/2202.13415)

区间模式的 CSV 增加 `lower_Ah`、`upper_Ah` 和 `calibration_count`（该跨度可用的历史误差数）。80%、90%、95% 分别至少需要 4、9、19 个同跨度历史误差。数量不足时仍输出点预测，上下限留空。实测覆盖率和平均宽度只统计有上下限的留出实测点。仅有四个稀疏容量检查点的比萨数据适合演示点预测。

## 已接入的逐循环容量

| 数据 | 循环轴与容量口径 |
| --- | --- |
| BatteryLife Na-ion | 使用发布文件内的循环号。CSV 取放电步骤的最大累计放电容量，XLSX 使用循环摘要的 CapD/Ah。略去末次可能未完成的循环。70 个原始文件中有一个只有 6 行静置记录，得到按文件计的 69 条轨迹。作者处理版的钠电说明记载了 31 只商用 18650，跨电芯实验需先核对样本对应关系。[原始文件](https://huggingface.co/datasets/Battery-Life/BatteryLife_Raw/tree/main/NAion) · [作者处理版及说明](https://zenodo.org/records/21149533) |
| NIMS 电解液筛选 | 72 只 NVP / 硬碳叠片电芯。按 sample_key 和原始 cycle_number 取 cycling 阶段的正放电容量，将 mAh 换算为 Ah。化成数据仍在原始表中。[发布者数据卡](https://huggingface.co/datasets/TOzawa-8887/nims-sib-additives-72) |
| 比萨大学 Hakadi 20 Ah | 一只电芯在 25 °C 下老化。使用 0.5C 放电测得的 `Q_dsch`，保留 0、250、500、750 四个实测循环号，适合演示稀疏容量检查点的预测。原始档案还含脉冲、UDDS 和家庭负载工况。[作者的数据说明](https://github.com/batterylabunipi/SIB_Aging_Dataset) |
| 4.5 Ah NFM | 分别读取 25 °C、−15 °C 的放电工作表，计算 2.00–4.00 V 两端的容量差。原表没有独立循环编号，横轴采用工作表观测行序，适合做顺序回放。[原始工作簿](https://data.mendeley.com/datasets/4mztcdc4gt/1) |

### 随仓库提供的容量表与署名

以下 CSV 由上表中的转换步骤生成，配套 JSON 记录原始版本、转换方法和 SHA-256。各表沿用数据发布者注明的许可。

- **BatteryLife。** 数据由 BatteryLife 团队发布，原始版数据卡标明 MIT。使用时请引用 Ruifeng Tan 等的 *BatteryLife: A Comprehensive Dataset and Benchmark for Battery Life Prediction*。版权及许可文本随附。[原始版数据卡](https://huggingface.co/datasets/Battery-Life/BatteryLife_Raw/blob/e52318a5a5036a46f5fb2f69b3dbd584d0d815e5/README.md) · [MIT 许可](licenses/BatteryLife-MIT.txt)
- **NIMS 电解液筛选。** 发布账户 TOzawa-8887，数据集 *Sodium-ion battery electrolyte screening (112 series, 72 cells)*。本表选取循环阶段的放电容量并换算为 Ah。[原始数据卡](https://huggingface.co/datasets/TOzawa-8887/nims-sib-additives-72/blob/489059aea27d13770ad5630393bed3fe5745e38c/README.md) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **NFM 温度试验。** Mendeley Data 第 1 版，发布者署名为 Siyuan, Shen、Yue, Xinyang、Zhao, Junjian、Chen, Zhengyu、Hao, Wei、Chen, Yuanmao、Zhang, Yu、Liu, Yakun 和 Liang, Zheng。本表从原工作簿提取两条钠电放电轨迹。[原始数据与署名](https://doi.org/10.17632/4mztcdc4gt.1) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## 数据下载与核验

同步工具将原始数据存入 `data/public/sodium_ion/`，并生成 `下载目录.csv` 和 `文件清单.csv`，记录发布页、许可、文件大小、本地 SHA-256 和下载状态。每个来源目录的 `manifest.json` 保存相同信息和失败原因。工作站页面下方的原始数据目录按本机已有清单显示，顶部容量数据框可离线使用附带的曲线。完整的 34 条来源见[公开来源配置](../configs/sodium_public_sources.json)。

本次检索日期为 2026-11-18。检索覆盖 DataCite、Battery Data Commons、Zenodo、Mendeley Data、Figshare、Hugging Face、GitHub 及高校机构库，并从论文的数据可用性声明回查原始发布页。组合检索使用了 sodium-ion、Na-ion、钠离子电池，以及循环老化、capacity、cycling、EIS、HPPC、SOC、pack 等词。目录统计以实际核对的发布版本和文件为准。3.2 Ah / 10 Ah 工况数据在两个仓库重复发布，按文件 SHA-256 可识别同一份原始数据。BatteryLife 作者的原始版与处理版也单独标明。

这批数据按整电芯和电池包收集，覆盖循环与日历老化、倍率、低温、OCV、阻抗、脉冲和动态工况。CT 原始投影与重建数据按本次要求跳过。温州数据的作者将七个钠电样品标为半电池，既有副本保存在原来的外部数据目录。部分发布包同时附带半电池诊断或锂电对照，建模时应使用对应电芯的记录。[温州原论文](https://doi.org/10.1039/D5EB00215J)

需要从原件生成 Hakadi 容量表时，在项目根目录运行下列命令，并将 UnRAR 加入 PATH。同步工具会检查已完成的文件，转换器读取两份 RAR 分卷。刷新工作站页面即可选择新表。要重建其他容量表，将两条命令中的来源 ID 换成相应 ID。

~~~powershell
python -m pip install requests pandas openpyxl h5py
python -m user_tools.sync_sodium_data --only pisa-hakadi
python -m user_tools.prepare_capacity_curves --only pisa-hakadi
~~~

同步更多来源时，TU Berlin 页面解析需要 beautifulsoup4，RWTH 和 NLR 文件页需要 Playwright 和本机浏览器。NLR 还用 remotezip 提取钠电工作簿。Windows 上的 `--tum-rsync` 调用 WSL Ubuntu 中的 rsync，默认方式也支持发布方的 FTP。`python -m user_tools.sync_sodium_data --index-only` 会根据本机清单重建索引。需要订阅或作者授权的记录会在索引中列出原因。

## 接入新数据与算法

- **临时使用数据。** 选择「导入容量 CSV」，使用 UTF-8 编码和表头 `cell_id,cycle,capacity_Ah`。每只电芯每个循环一行。有间断的测量保留真实循环编号。导入时会校验容量列名、重复循环和数值。
- **把数据加入目录。** 将标准表放在 `data/public/capacity_curves/<数据集ID>.csv`，刷新页面即可选择。同名 JSON 可提供 `title`、`url`、`method` 及 `sha256`。MAT、NDA、原始电流电压或电池包工况需先按各自的协议转换。现有转换逻辑见[容量表适配器](../user_tools/prepare_capacity_curves.py)。
- **接入算法。** 在工作站所用 Python 环境中安装自己的算法包，通过下列 Python entry point 注册并刷新页面。平台向函数传入单只电芯的训练循环、训练容量以及待预测的循环号。返回值按目标顺序排列，每个值为有限、非负的 Ah。算法依赖和预训练权重由该包提供。

~~~toml
[project.entry-points."fangzhen.capacity_forecasters"]
my_model = "my_package.model:forecast"
~~~

~~~python
from sklearn.linear_model import HuberRegressor


def forecast(train_cycles, train_capacity_ah, target_cycles):
    first, last = train_cycles[0], train_cycles[-1]
    scale = max(1, last - first)
    model = HuberRegressor()
    model.fit([[(c - first) / scale] for c in train_cycles], train_capacity_ah)
    estimates = model.predict([[(c - first) / scale] for c in target_cycles])
    return [max(0.0, value) for value in estimates]
~~~

此扩展示例需要在算法包依赖中声明 scikit-learn。[HuberRegressor 文档](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.HuberRegressor.html)

内置线性、平方根和末次容量三种基线。本机还可以直接选择「NumPy 二次多项式」，调用 NumPy 的 `Polynomial.fit` 并记录实际库版本。只有两个训练点时使用一次多项式。留出误差描述同一轨迹后续观测的回测表现。[NumPy 算法文档](https://numpy.org/doc/stable/reference/generated/numpy.polynomial.polynomial.Polynomial.fit.html)
