# v0.3 Step 18 — CALCE INR18650-20R 数据审计

日期：2026-09-08　|　审计方式：只读解析（脚本 `scripts/audit_20r_step18.py`，
机读结果 `outputs/audit/v03_step18_20r_audit.json`）。未修改任何数据文件。

## 1. 文件盘点

根目录：`data/raw/LIB/NMC_Graphite/CALCE_INR18650_20R/`

| 文件 | 格式 | 内容 | cell |
|---|---|---|---|
| `11_05_2015_SP20-2_DST_50SOC.xls` | Arbin .xls（BIFF） | DST 动态测试，SOC 起点 50% | SP20-2 |
| `11_05_2015_SP20-2_DST_80SOC.xls` | Arbin .xls | DST，80% | SP20-2 |
| `11_06_2015_SP20-2_FUDS_80SOC.xls` | Arbin .xls | FUDS，80% | SP20-2 |
| `11_09_2015_SP20-2_FUDS_50SOC.xls` | Arbin .xls | FUDS，50% | SP20-2 |
| `11_11_2015_SP20-2_US06_50SOC.xls` | Arbin .xls | US06，50% | SP20-2 |
| `11_11_2015_SP20-2_US06_80SOC.xls` | Arbin .xls | US06，80% | SP20-2 |
| `11_5_2015_low current OCV test_SP20-1.xlsx` | xlsx | 低倍率 OCV-SOC 标定 | SP20-1 |
| `12_2_2015_Incremental OCV test_SP20-1.xlsx` | xlsx | 增量 OCV/pulse 标定 | SP20-1 |

archive/ 下三个 zip（`SP2_25C_DST/FUDS/US06.zip`）与 raw/ 内容一致（校验文件大小
匹配），raw/ 为解压后正本。注意归档名 `SP2_25C_*` 中 **"25C" 指测试温度 25 °C**
（进入 Step 19 温度假设）。

## 2. 表结构与列名（动态 .xls，每个文件相同）

Sheets：`Info`（测试报告头）+ `Channel_1-008`（数据）。数据列：

```text
Data_Point, Test_Time(s), Date_Time, Step_Time(s), Step_Index, Cycle_Index,
Current(A), Voltage(V), Charge_Capacity(Ah), Discharge_Capacity(Ah),
Charge_Energy(Wh), Discharge_Energy(Wh), dV/dt(V/s), Internal_Resistance(Ohm),
Is_FC_Data, AC_Impedance(Ohm), ACI_Phase_Angle(Deg)
```

- 时间列：`Test_Time(s)`（相对测试开始，秒）。
- **没有温度列**（无任何 Thermocouple/Aux 列）→ 温度只能作为平台建模假设。
- `Charge/Discharge_Capacity(Ah)` 是 Arbin 累计列（同 CS2 陷阱 T2），禁用，
  capacity 一律由 I(t) 梯形积分。

## 3. 每文件时间轴 / 电流 / 电压审计（数值见机读 JSON）

| 文件 | n | 时长 h | dt 中位 / min / max (s) | I min/max (A) | I RMS (A) | V first→last (V) | 时间重置 | NaN/重复 |
|---|---|---|---|---|---|---|---|---|
| DST_50SOC | 9501 | 9.65 | 1.016 / 1.8e-4 / 10.14 | −4.000 / +2.005 | 0.960 | 3.435 → 2.500 | 0 | 0 / 0 |
| DST_80SOC | 12561 | 8.29 | 1.016 / 8.5e-5 / 10.02 | −4.002 / +2.001 | 1.003 | 3.938 → 2.403 | 0 | 0 / 0 |
| FUDS_80SOC | 13681 | 10.29 | 1.016 / 1.6e-2 / 10.42 | −4.000 / +2.142 | 1.037 | 3.412 → 2.497 | 0 | 0 / 0 |
| FUDS_50SOC | 9308 | 8.37 | 1.016 / 1.8e-5 / 10.02 | −4.001 / +2.142 | 1.003 | 3.777 → 2.499 | 0 | 0 / 0 |
| US06_50SOC | 8321 | 5.91 | 1.003 / 3.1e-4 / 10.01 | −3.997 / +1.000 | 0.938 | 3.329 → 2.499 | 0 | 0 / 0 |
| US06_80SOC | 11898 | 6.33 | 1.015 / 1.3e-4 / 10.02 | −3.997 / +1.000 | 0.943 | 3.432 → 2.498 | 0 | 0 / 0 |

结论：

1. **DST / FUDS / US06 每个文件都是单一连续 profile**：时间单调递增、
   `n_time_resets = 0`、无重复时间戳、无 NaN。不存在跨文件拼接问题；
   每个 (protocol, SOC 档) 就是一个文件。
2. **电流符号（原始）**：Arbin 约定，充电 = 正（+1.0 A 标准充、+2.0 A 快充，
   FUDS 文件里出现 +2.14 A 的峰值），放电 = 负（−4.0 A 峰值放电，2C of 2 Ah）。
   → 与平台约定（放电 = 正）**相反，adapter 必须翻转**（同 CS2 陷阱 T1）。
3. **电压窗口**：数据实际范围 2.40–4.20 V，与 Samsung INR18650-20R 规格
   2.5–4.2 V 一致（DST_80SOC 末段 2.403 V 略低于截止，属 Arbin 过冲记录）。
4. **近零间隔记录**：所有文件都存在 min dt ≈ 1e-5–1e-2 s 的记录对（Arbin 在
   电流切换时刻额外落点）。处理策略：排序 + 相同时间戳去重 + 首点归零后，
   对仍残留的 dt→0 点保留（梯形积分与 `np.diff>0` 校验时剔除非严格递增），
   并在 adapter 中保证输出 `np.diff(time_s) > 0`。
5. **rest 段 10 s 采样**（dt max ≈ 10 s），动态段 1 s 采样。

## 4. 测试程序结构（规则化识别依据）

每个文件 1 个 Cycle_Index、8 个 Step，结构一致：

| Step | 内容 | 特征（用于规则识别） |
|---|---|---|
| 1 | 初始静置 | 1 点，I=0 |
| 2 | CC 充电 +1 A | 单一符号，恒幅 |
| 3 | 满充收尾（CV/降流 0.02–0.97 A） | 单一符号（正），幅度变化 |
| 4 | 静置 | I=0，~720 点 |
| 5 | −1 A 放电至目标 SOC（50 档 360 s / 80 档 144 s） | 单一符号（负），恒幅 |
| 6 | 静置 | I=0 |
| 7 | **动态 profile 循环直至 2.5 V 截止** | 混合符号、数千点、|I| 峰值 ≥2 A |
| 8 | 结束静置 | 个位数点 |

SOC 标签语义：Step 5 的放电量决定 profile 起点 SOC（50 档放得更多 → SOC 更低）。
文件名 `50SOC/80SOC` 为 CALCE 的标称起点，精度无法从文件内独立验证 → 记为
source 标签，仿真初始 SOC 是低置信度假设（见 Step 21/参数审计与 config）。

**动态段识别规则（不写死 step=7）**：在 (cycle, step) 分组中，选满足
「点数最大 且 电流同时含正负号 且 |I| 峰值 ≥ 1 A」的 step。用此规则对全部 6 个
文件验证，命中均为 Step 7（100% 一致），记录于 provenance。

## 5. 对 v0.3 的直接结论

- 单 cell（SP20-2）× 3 protocol × 2 SOC 档 = 6 个 replay 窗口；canonical
  rate/protocol id 设计为 `DST50/DST80/FUDS50/FUDS80/US0650/US0680`
  （rate_slug：`DST_50SOC` 等），`--protocol DST` 在 CLI 层展开为该 protocol
  的全部窗口。
- 无温度列 → 温度假设由 config 持有（archive 命名 25C，source=calce_archive_25C）。
- capacity 语义：`capacity_is_predictive: false`、`forced_current_window`
  （Step 25 要求，复用 v0.2 机制）。
- OCV 文件（SP20-1）属于另一颗 cell，仅作参数集标定参考，**不进入 replay**。
