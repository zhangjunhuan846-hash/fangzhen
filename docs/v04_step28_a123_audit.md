# v0.4 Step 28/29 — CALCE A123 数据审计

日期：2026-09-08　|　审计方式：只读解析（`scripts/audit_a123_step28.py`，机读结果
`outputs/audit/v04_step28_a123_audit.json`）。archive zip 原样保留，未改动任何数据文件。

## 1. 文件盘点

根目录：`data/raw/LIB/LFP_Graphite/CALCE_A123/`

| 文件 | 内容 |
|---|---|
| `archive/A123_DST-US06-FUDS-25.zip` | 原始归档（保留）：2 个动态测试 xlsx |
| `archive/A123_OCV25-20120905.zip` | 原始归档（保留）：2 个 OCV xlsx |
| `raw/DST-US06-FUDS-25/A1-007-DST-US06-FUDS-25-20120827.xlsx` | cell A1-007，24469 行 |
| `raw/DST-US06-FUDS-25/A1-008-DST-US06-FUDS-25-20120827.xlsx` | cell A1-008，25106 行 |
| `raw/OCV25-20120905/A1-00x-OCV-25-20120905.xlsx` | 25°C 低电流 OCV（不入 replay） |

**与 20R 的关键结构差异：20R 是 1 cell × (protocol×SOC) 各一个文件；A123 是
1 cell × 1 个文件，内含 DST/US06/FUDS 三个动态段（各从满充出发）。**

## 2. 表结构与列名（两文件一致）

Sheets：`Info` + `Channel_1-006`（A1-007）/ `Channel_1-005`（A1-008）+ `Sheet1`。
数据列与 20R 同为 Arbin 全家桶，**但多一列实测温度 `Temperature (C)_1`**
（26.5–28.4 °C，舱温标称 25 °C）——A123 有温度实测，20R 没有。

## 3. 时间轴 / 电流 / 电压审计

| 项 | A1-007 | A1-008 |
|---|---|---|
| 时间范围 | 3.1–36294.8 s（10.1 h） | 3.0–37541.9 s（10.4 h） |
| 时间单调 / 重复 / NaN | 是 / 0 / 0 | 是 / 0 / 0 |
| 时间重置 | 0 | 0 |
| dt 中位 / min / max (s) | 1.005 / 1.1e-3 / 300.0 | 1.005 / 8.2e-4 / 300.0 |
| 电流原始范围 (A) | −3.849 … +2.061 | −3.850 … +2.061 |
| 电压范围 (V) | 1.938–3.700 | 1.999–3.781 |

- 原始符号同 CALCE 惯例：充电=+（+1.1 A 标准充、峰值 +2.06 A），放电=−
  （峰值 −3.85 A ≈ 3.5C of 1.1 Ah）→ **adapter 需翻转**。
- 电压窗口与 LFP 规格一致：上限 3.6 V（+CV），下截止 2.0 V（动态段均以
  ≈2.0 V 结束；3.7/1.94 V 为个别过冲/回弹记录）。
- 近零 dt 事件点存在（~1e-3 s），处理策略同 20R。

## 4. 测试程序结构：每文件 1 个 Cycle、27 个 Step = 3 个重复块

每个块：满充（CC 1.1 A → CV 至截止）→ rest → **动态 profile 至 2.0 V** → rest。
三个动态段规则识别（混合符号 + |I|峰≥1A + 点数最大）命中 Step **8 / 16 / 24**，
与协议身份证据吻合：

| Step | 时长 | dur/周期 | 充电峰 (A) | 放电峰 (A) | Q_dis (Ah) | 判定 |
|---|---|---|---|---|---|---|
| 8 | 7387 s (A1-007) | /3600 s = 2.05 | 1.93 | 3.85 | 1.231 | **DST**（3600 s 周期 ≈2 整循环+尾部） |
| 16 | 6980 s | /600 s = 11.63 | 0.83 | 3.85 | 1.156 | **US06**（600 s 周期） |
| 24 | 7400 s | /1554 s ≈ 4.76 | 2.06 | 3.85 | 1.273 | **FUDS**（充电峰特征与 20R FUDS 一致） |

协议顺序与 zip 文件名 `DST-US06-FUDS-25` 一致；充电峰排序 DST(1.93) <
FUDS(2.06)、US06 最小(0.83)，与 v0.3 20R 审计的符号特征交叉印证。
（A1-008 对应 7461 / 7184 / 7606 s，比值 2.07 / 11.97 / 4.89。）

**SOC levels：无。** 每个动态段都从满充出发（与 20R 的 50/80% SOC 变体不同）。
initial-state 语义：`type=nominal_full_soc, value=1.0, history_replayed=false,
is_exact_electrochemical_state=false`（前序 charge/CV/rest 未重放）。

## 5. Step 29 — 电芯身份确认（证据，不靠文件名补全）

| 项 | 值 | 证据 |
|---|---|---|
| 制造商 | A123 Systems | CALCE 数据集页 "A123 Battery" 条目 |
| 电芯型号 | APR18650M1A（18650 圆柱） | A123 官方规格（cellsaviors 数据库收录原厂数据）；多篇使用 CALCE A123 数据的论文引用 |
| 正极 | LiFePO4（LFP） | 同上（Batteries 2023, 9, 114, Table 1：CALCE A123 数据 = "Cathode LiFePO4 / Anode Graphite"） |
| 负极 | 石墨 | 同上 |
| 标称容量 | 1.1 Ah | 同上；**数据内证**：满充 CC+CV 电量 1.036 Ah（A1-007）/ 1.052 Ah（A1-008），动态段放电吞吐 1.16–1.30 Ah |
| 标称电压 | 3.3 V | 原厂规格 |
| 电压窗口 | 2.0–3.6 V | 原厂规格；与数据实测完全一致（CV 3.60 V、动态截止 2.0 V） |
| 测试温度 | 25 °C 舱温（实测电芯温度列 26.5–28.4 °C） | zip 命名 "-25"；文件内有实测温度列 |

结论：`chemistry: LFP_Graphite` 有充分证据支持；容量/窗口/化学体系三项
独立证据链（原厂规格 + 论文引用 + 文件内实测）互相一致，无 unknown 项。

## 6. 对 v0.4 的直接结论

- canonical 窗口：cell {007, 008} × protocol {DST, US06, FUDS} = 6 个 replay 窗口
  （rate_slug：`DST`/`US06`/`FUDS`；c_rate=NaN，动态无单一倍率）。
- 温度：**有实测列** → `temperature_cell_C` 逐点实测；
  `temperature_ambient_C` 用实测电芯温度（无独立舱温传感器；舱温标称 25 °C，
  记录于 config note）——与 20R 的"纯假设"不同，这里走数据。
- 符号翻转、时间轴卫生、规则化动态段识别：复用 v0.3 calce_20r 的处理范式。
