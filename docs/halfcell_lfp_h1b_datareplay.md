# Half-cell Pilot H1 — Phase H1-B：SINTEF LFP-NMP-1 p-OCV data replay gate

**日期**：2026-09-08（H1-A commit `17342ab` 之后）
**对象**：`sintef__sintef-lfp-R2032-gelon-d07eb6__20250602__p-ocv__RT.bdf.parquet`（唯一对象，不接第二数据源）
**范围**：仅 adapter 级数据回放验证——provenance / protocol / capacity 三重验证。**不写平台、不跑模型、
不做 inverse OCP / 化学计量学反演、不下载 GITT、不推 D_s**。
**脚本**：`scripts/lfp_h1b/data_replay.py`（纯 pandas/pyarrow/numpy/matplotlib，**0 pybamm import**）
**产出**：`outputs/analysis/lfp_h1/data_replay/`（source_manifest.json、cycle_manifest.csv、
processed_pocv.parquet、replay_summary.json、figures/ 3 张 sanity 图）

---

## 0. 结论

**H1-B 全部 8 项 Gate 通过**，SINTEF LFP-NMP-1 p-OCV 从"有个公开文件"升级为
**经 provenance + protocol + capacity 三重验证的 canonical half-cell 实验数据集**。
数据接口冻结于 `outputs/analysis/lfp_h1/data_replay/`，管线确定性（fresh replay 7/7 文件逐字节一致）。
现有 88 tests 重跑全绿，H0 Birmingham 冻结产物零改动（测试重跑造成的 runtime_s 漂移已还原）。

**最重要的容量发现**：电流积分全窗 (2.50–3.65 V) 容量 **3.27–3.31 mAh**，比 metadata 制造商
标称 3.079 mAh（2.0 mAh/cm² × 1.539 cm²）**高 ~6.8%**——标称是标签，不是 cycler 实测窗容量
（与 Birmingham H0 的 nominal vs 实验容量失配同类）。此事实必须在 H1-C/D 组装 P2D 时显式处理。

---

## 1. 原始数据完整性（provenance freeze）

| 项 | 值 |
|---|---|
| raw 文件 | 2,845,751 B；**md5 `3efea83a…c3c` == Zenodo v1 官方值**；sha256 `dcadc267…80d5` |
| 行 × 列 | 221,209 × 7（Test Time/s, Unix Time/s, Current/A, Voltage/V, Cycle Count/1, Step Index/1, Cumulative Capacity/Ah） |
| 采样跨度 | 0.02 – 2,232,710.323 s（**620.20 h ≈ 25.84 天**）；时间单调非降，无重复行 |
| 本地落盘 | parquet mtime 2026-09-08 09:45 (+08)；metadata.csv 11:04 (+08)（H1-A 筛查日捕获） |
| metadata.csv | 95 行 × 14 列；sha256 `4016e21f…af3f`、md5 `b5aaaed5…e3`；LFP-NMP-1 行（d07eb6）：p-OCV、d=14、78 µm、2.0 mAh/cm²、起始 2025-06-02 |
| 数据集 | Zenodo 10.5281/zenodo.19107295（v1；newer 20086298），CC-BY-4.0，SINTEF Battery Lab |

备注：metadata 列头 "Electrode Diameter / cm" 值为 14 → 按 14 mm 盘处理（R2032 几何，列头单位
疑为笔误）；该商用电极的 Mass/Loading/wt% 列为空。两条 caveat 均写入 source_manifest。

## 2. Protocol reconstruction

分割规则**只用实测电流符号**（|I|≤1e-12 A = rest），Cycle/Step 列仅做事后交叉核对——
21 个连续 block 全部与 (cycle, step) 一一对应，结构可重复识别：

```
pre_rest(6h, 3.1498→3.1677 V) → [charge(3.65V) → top_rest(8h) → discharge(2.50V) → bottom_rest(8h)] × 5
```

- **5 个完整 p-OCV cycle**（10 个驱动 leg + 11 个 rest block），与 manifest 完全对应；
- **C/50 实测电流 |I_med| = 61.60 µA**（充放同值），vs 标称几何推算 61.575 µA
  （3.0788 mAh / 50 h），比值 **1.0004** → cycler 电流确实按 metadata 标称容量设定；
- **截止全部精确到达**：每个 charge leg 末点 3.6500 V、每个 discharge leg 末点 2.5000 V
  （全文件 V ∈ [2.49999, 3.65000]）；
- **rest 精确 8.000 h**（pre-rest 6.000 h）；驱动 leg 时长 53.0–53.7 h。

`cycle_manifest.csv`（21 行）字段：cell_id, cycle, segment, segment_label, t_start, t_end,
duration_h, I_mA_median, V_start, V_end, Q_Ah, termination_reason, n_rows, raw_cycle_index, raw_step_index。

## 3. Capacity reconstruction（H1-B 最关键一关）

对每个驱动 leg 独立梯形积分 Q=|∫I dt|（块内积分，绝不跨边界）：

| 量 | c1 | c2 | c3 | c4 | c5 |
|---|---|---|---|---|---|
| charge leg (mAh) | 3.2783* | 3.2772 | 3.3009 | 3.3055 | 3.3059 |
| discharge leg (mAh) | 3.2662 | 3.2882 | 3.2935 | 3.2953 | 3.2958 |

\* c1 charge 从 3.17 V（6 h pre-rest 后）起充，为**半窗 leg**，不参与全窗比较；
5 个 discharge leg 与 c2–c5 charge leg 均为全窗 (2.50↔3.65 V) 参考。

三方对照：

- metadata 标称：**3.0788 mAh**（2.0 mAh/cm² × 1.53938 cm²）
- 协议 C/50 隐含：**3.0788 mAh**（61.575 µA × 50 h）——两者自洽
- 电流积分实测（discharge 均值）：**3.2878 mAh = 2.136 mAh/cm²**，**+6.8% vs 标称**

交叉验证：积分值 vs cycler Cumulative Capacity 列（该列**每 leg 起点清零**，已在 manifest
unit_map 注明）最大偏差 **0.001 µAh**（数值上精确一致）。discharge leg 间极差 0.0296 mAh
（<1%），c1 最低、c2–c5 收敛于 ~3.296 mAh——稳定性良好，差异可解释为初期活化/收敛，
不构成 gate 风险。

## 4. 初始状态：只记录实验事实

`replay_summary.json → initial_states`（10 条，每驱动 leg 一条），只含实测：
段首电压、前序 rest 的末点开路电压与时长、段前电流(0)、段首采样电流。**无 x0/c_s0/OCP 反演**
（属 H1-C/D 参数化层）。摘要（V0 = 段首实测电压；prev.rest end = 前序 rest 末点电压）：

| segment | V0 (V) | prev.rest end (V) | prev rest |
|---|---|---|---|
| c1_charge | 3.1717 | 3.1677 | 6 h pre-rest |
| c1_discharge | 3.4761 | 3.4771 | top 8 h |
| c2_charge | 3.2107 | 3.2096 | bottom 8 h |
| c2_discharge | 3.5315 | 3.5322 | top 8 h |
| c3_charge | 2.9416 | 2.9408 | bottom 8 h |
| c3_discharge | 3.5463 | 3.5469 | top 8 h |
| c4_charge | 2.8140 | 2.8132 | bottom 8 h |
| c4_discharge | 3.5503 | 3.5510 | top 8 h |
| c5_charge | 2.8095 | 2.8087 | bottom 8 h |
| c5_discharge | 3.5568 | 3.5574 | top 8 h |

观察（仅记录，不建模）：底部 rest 8 h 后弛豫电压 2.81–3.21 V、顶部 rest 后 3.48–3.56 V；
文件起始于一次未完成的弛豫中段，**不声明任何初始 SOC**。

## 5. Adapter 输出（不绑死 PyBaMM）

`processed_pocv.parquet`（221,209 行 × 10 列）：time_s, voltage_V, current_A, capacity_Ah,
segment_type, segment_label, cycle_index + 透传 raw_cycle_index, raw_step_index,
cum_capacity_raw_Ah。几何/配置/来源作为 attrs 记录于 source_manifest（parquet 不存 attrs）。

`capacity_Ah` 定义（已写入 manifest）：**当前 charge/discharge leg 起点的累计 | throughput |**，
随后的 rest 段保持常数（等组分弛豫），逐 leg 清零——**不是全局 SOC / 绝对嵌锂坐标**。
不含任何模型字段（无 diffusivity / porosity / initial concentration）。

## 6. Gate 结果

| Gate | 要求 | 结果 |
|---|---|---|
| File provenance | 官方 hash 对得上 | ✅ md5 == Zenodo v1 官方 |
| Segmentation | 5 cycle / 协议段可重复识别 | ✅ 21 blocks，电流符号驱动 + Step 列交叉一致 |
| Voltage window | 2.50–3.65 V 一致 | ✅ 全文件 [2.49999, 3.65000]，各 leg 精确达截止 |
| Current | 与 C/50 自洽 | ✅ 61.60 vs 61.575 µA（1.0004） |
| Capacity | 积分稳定、圈间差异可解释 | ✅ 极差 <1%；+6.8% vs 标称已记录 |
| Geometry | 14 mm / 78 µm / 2.0 mAh cm⁻² 继承 | ✅（含列头单位 caveat） |
| Fresh replay | 删派生输出重跑结果一致 | ✅ **7/7 文件逐字节一致**（json/csv/parquet/png） |
| Model dependency | 0 PyBaMM import | ✅（运行时 sys.modules 断言 + 依赖仅 numpy/pandas/pyarrow/matplotlib） |

复现命令（WSL pybamm env）：
`python scripts/lfp_h1b/data_replay.py [--out <dir>]`；确定性管线，两次运行逐字节一致。

## 7. 范围与后续

- **未做**（按任务书）：GITT 下载、D_s 推导、inverse OCP、第二数据源、平台接线。
- 复制细胞 `178617`（2025-07-06 p-ocv）在 metadata 中已登记但未下载；如需重复性对照再取。
- **下一步待批：H1-C parameter-source audit**（P2D 参数缺口：孔隙率/粒径/k0/电解液 →
  acfc66 / ae94f3 文献锚组装，沿用 H0 parameter_mapping JSON 模式）；需要时再下 GITT
  （b89ab5/b26620）。H1-D 前须显式定义 as-published 语义（同 H1-A 报告 §3）。
- LFP 两相平台（~3.42 V 平台、充放迟滞）在 V–Q 图（fig3）直接可见；单相 DFN 能否复现
  属 H1-D 待检验的模型结构假设，不在此预设。
