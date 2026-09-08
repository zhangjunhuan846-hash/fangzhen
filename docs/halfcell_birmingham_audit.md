# Half-cell Pilot H0 — H1: Birmingham NCM920305 数据审计

- 日期：2026-09-08
- 阶段：Half-cell Pilot H0（`Birmingham NCM920305 || Li`，2 mAh cm⁻²）
- 范围：**只审计，不写 adapter，不触碰 battery_sim/**。
- 审计脚本：`scripts/halfcell_birmingham/audit_raw.py`（原始头部/行数/NUL）
  `audit_struct.py`（分段/采样/符号）`audit_slice.py`（静置段与 C/10 slice 细节）。
- 数据源：`data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw/`（9 CSV，今日 09:50–09:51 落盘）。

## 1. 总体结论（TL;DR）

- 9 个文件全部为**单行表头、逗号分隔、无元数据行、无 NUL** 的标准 CSV，单位直接写在列名方括号中：
  `Time [s]` / `Voltage [V]` / `Current [mA]` / `Capacity [mAh]` / `Temperature [K]`（Formation 与 pOCV 额外带 `Step` 列）。
- **符号约定：放电 = 负电流**（5 个 rate 文件放电段均 I<0 且 V 随 I 下降单调降至 2.5 V 截止；与 Formation/pOCV/GITT 放电段一致）。平台约定 discharge positive 需在 adapter 内翻转。
- **温度恒定 298.15 K（25 °C）**（所有文件唯一值；EIS 亦同）。无实测 T_cell 通道 → ambient = 298.15 K。
- **电压窗口：充电上限 4.2 V，放电下限 2.5 V**（放电在 2.5000 V 处触发停机，见 §4）。
- 时间轴为**跨工况绝对累计秒**（不同文件可能并行/不连续，见 §6）；同一文件内单调。
- 采样间隔**非均匀**：电流/电压切换瞬间密集到 2 ms，稳态段按电压/时间间隔稀疏采样
  （C/10、C/5 稳态中位 60 s；2C 中位 0.44 s）。这对 `|dI/dt|` 类诊断与 time-aligned 比较是重要输入。
- 名义倍率基准：**1C ≈ 3.44 mA**（C/10 −0.3439 mA → 2C −6.8795 mA，比值严格 ×2/×5/×10/×20）。
  由 2 mAh cm⁻² ⇒ 隐含电极面积 ≈ 1.72 cm²（见 §5、§7 的注意项）。

## 2. 文件级总览

| 文件 | 行数 | 列 | 结构 |
|---|---|---|---|
| `Formation_2mAhcm_2_NCM920305.csv` | 5996 | Step,Time,Voltage,Capacity,Current,Temperature | 11 个 Step：2 轮化成循环 |
| `pOCV_2mAhcm_2_NCM920305.csv` | 3551 | Step,Time,Voltage,Capacity,Current,Temperature | 5 个 Step：准 OCV（C/20）充放 + 2.5 V 长时 CV |
| `GITT_25degC_2mAhcm_2_NCM920305.csv` | 38910 | Time,Capacity,Voltage,Current,Temperature | 135 个 600 s C/10 脉冲 + 3 h 静置（**无 Step 列**） |
| `RateCapability_Cover10_...csv` | 924 | Time,Voltage,Current,Capacity,Temperature | 120 s 静置 + 单段 CC 放电(C/10) + 静置 |
| `RateCapability_Cover5_...csv` | 679 | 同上 | C/5 放电 |
| `RateCapability_Cover2_...csv` | 554 | 同上 | C/2 放电 |
| `RateCapability_1C_...csv` | 527 | 同上 | 1C 放电 |
| `RateCapability_2C_...csv` | 490 | 同上 | 2C 放电 |
| `SOC50_25deg_EIS_...csv` | 55 | Frequency,Z_real,Z_imag,Voltage,Temperature | 0.01 Hz–500 kHz 单扫（54 频点+重复点），V=3.852 V |

列名含 `[mA]`、`[mAh]`、`[K]` — 与 CALCE/CS2/A123 的 1 A/1 Ah 主单位不同，adapter 需换算。

## 3. Formation 结构（Step 逐段）

电流 0.172 mA ≈ **C/20**（相对 3.44 mA 的 1C）。

| Step | 类型 | 电流 mA | V 范围 | 时长 s | 容量 mAh（CC 段） |
|---|---|---|---|---|---|
| 1 | 静置/OCV 爬升 | 0 | 2.973→3.510 | 43181 | 0 |
| 2 | 充电 CC → 4.2 V | +0.172 | 3.54→4.2001 | 69445 | 0→3.327 |
| 3 | 4.2 V CV 恒压 | 0.070→0.175 衰减 | 4.200 | 4109 | 3.327→3.449 |
| 4 | 静置 | 0 | 4.199→4.186 | 7152 | — |
| 5 | 放电 CC → 2.5 V | −0.172 | 4.184→2.4999 | 62772 | 3.449→0.457 |
| 6 | 静置 | 0 | →3.560 | 7184 | — |
| 7–9 | 同 2–4（第二轮充电） | +0.172 | →4.2 | ~61000 | →3.486 |
| 10 | 第二轮放电 →2.5 V | −0.172 | →2.5000 | 62843 | →0.491 |
| 11 | 静置 | 0 | →3.561 | 7200 | — |

即：化成 = 两轮 CC–CV 充（顶 4.2 V / CV 截至 ~0.07 mA）→ CC 放至 2.5 V，倍率 C/20。文件终态为满嵌锂（放完）后静置 ~3.56 V。**形成循环含 CV，无直接 C/10 可复现段（H0 不重放 Formation）。**

## 4. Rate capability：5 个放电文件（H0 重放主体）

统一结构：**120 s 静置（V≈4.19–4.20，前一轮 4.2 V 充电+静置后的 OCV）→ 单段恒流放电 → 停表后静置 ~1700 s（文件记录）**。

| 文件 | I 平台中值 mA | 放电时长 s | 起止 V | 截止 V | 库仑积分 mAh | 放电行数/总数 |
|---|---|---|---|---|---|---|
| C/10 (Cover10) | −0.34393 | 31485.7 | 4.1896→2.5000 | 2.5000 | 3.008 | 705/924 |
| C/5 (Cover5) | −0.68797 | 15633.6 | 4.1839→2.5000 | 2.5000 | 2.988 | 461/679 |
| C/2 (Cover2) | −1.71936 | 6149.8 | 4.1711→2.5000 | 2.4999 | 2.937 | 345/554 |
| 1C | −3.43969 | 3069.5 | 4.1490→2.4999 | 2.4999 | 2.933 | 334/527 |
| 2C | −6.87947 | 1509.0 | 4.1032→2.4998 | 2.4998 | 2.884 | 320/490 |

要点：
- 恒流段电流**严格平坦**（plateau 内 |I| 稳定在设定值 ±1%），无 CV 尾。
- 电压下限命中 **2.5000 V 即停机**（末 2–3 个活跃点 2.4998–2.5000，随后 ~0.2 s 内电流归零并进入静置）。
- 起始 OCV 随倍率降低略有差异（C/10 4.1896 V → 2C 4.1032 V）：高倍率前静置更短/极化更大——**初始状态 = 上一轮充电到 4.2 V 后的静置 OCV，需按各文件自身首行 V 映射 initial SOC**（不能假设同一初值）。
- 放电容量随倍率单调下降（3.008→2.884 mAh），符合预期；容量列与库仑积分一致（列内单调、无重置）。

### C/10 vertical slice（H0 首选）
- 文件 `RateCapability_Cover10_2mAhcm_2_NCM920305.csv`，放电窗口 t∈[329902.60, 361388.32] s（时长 31485.7 s ≈ 8.75 h），I=−0.3439 mA。
- 起点 V=4.1896 V（放电首行）；终点 V=2.5000 V（截止）；`Capacity` 列 0→3.008 mAh。
- 采样：起始 0.08 s 间隔若干点后中位 60 s，切换瞬态 2 ms；放电末段靠近截止时加密（p1 至 0.08 s）。
- **该窗口适合先验查：OCP/初始化/符号/half-cell wiring**（低倍率≈准平衡，极化小）。

## 5. pOCV 与 GITT 结构（H0 不重放，仅记录供后续 A2b/pOCV 用）

### pOCV（`pOCV_...csv`，5 Step，C/20）
1. 10 s 静置 @2.51 V；2. CC 充电 +0.1721 mA 3.50→4.2001 V（64040 s，3.065 mAh）；3. ~4.2 V 衰减段 1651 s（至 3.112 mAh）；
4. CC 放电 −0.1721 mA →2.4999 V（63581 s，至 0.075 mAh）；5. **2.5 V 长时 CV（20 h，电流 −0.175→−0.005 mA 衰减，Capacity 列越界到 −0.283 mAh）**。
注意：Step5 表明 pOCV 放电在触 2.5 V 后**又做 20 h 恒压**，不是干净 CC 到底；若日后做 pOCV 对比须裁剪。

### GITT（无 Step 列）
- 前 68 个脉冲为**充电脉冲**（+0.343 mA，600 s），静置 3 h；V 窗 3.54→4.27 V（脉冲末）。
- 后 67 个脉冲为**放电脉冲**（−0.343 mA，600 s），静置 3 h；V 一路降至 ~1.90 V。
- `Capacity [mAh]` 列语义与 Formation/rate 文件不同（逐脉冲增量 ±0.0573 mAh，文件末累计仅 0.054 —— 疑似按段重置或窗口内小 SOC 行程），**GITT 不进入 H0**；日后使用时需先重建库仑积分而非信容量列。

## 6. 时间轴关系与判读

- 绝对累计秒在**文件间不构成同一连续记录**：pOCV（39–241 ks）落在 Formation（0–335 ks）时间区间内；rate 文件序列（330→363→557→707→813→900 ks）与 GITT（385–1926 ks）为后续序列。推测 cycler 多通道/多电池并行记录 → **不可跨文件用绝对时间对齐，也不可假设全部来自同一颗 cell**（至少 pOCV 与 Formation 时间重叠佐证并行）。
- H0 只在**文件内**取窗口重放，跨文件绝对时间无影响。

## 7. 审计中暴露的、需在 H4–H7 处理的 adapter/配置注意项（决策清单）

1. **符号翻转**：原始放电为负 → canonical（discharge positive）需 `I_canonical = −I_raw`；充电（Formation/GITT 正脉冲）为负。
2. **单位换算**：mA → A、mAh → Ah、K → °C（T=298.15 K = 25 °C）。
3. **几何/面积一致性（科学正确性关键）**：1C=3.44 mA 且标称 2 mAh cm⁻² ⇒ 实验电极面积 ≈ **1.72 cm²**。
   - 必须核对 Jackowska2025_2mAh_cm2 参数集内的电极几何（电极面积/半径/集流体面积）是否 ≈ 1.72 cm²；
   - 若参数集面积不同，直接按原始 mA 回放会得到不同的 mA/cm²（等效倍率偏移）——需要在 H3/H7 显式校验并记录，不能静默放行。
4. **初始状态映射**：每文件放电起点 OCV 不同（4.1896/4.1839/4.1711/4.1490/4.1032 V）→ initial SOC 必须按**本文件首行 V** 由参数集 OCP 反解，不能写死。
5. **窗口语义**：重放窗口 = CC 平台段（|I|>1e-6 mA 起至 2.5 V 截止），前后静置剔除（或仅作边界锚点）；放电平台内含切换瞬态行（2 ms）需按既有 time-aligned 逻辑处理。
6. **C-rate 元数据**：c_rate = |I|/3.44 mA（1C 基准由数据推出），rate_slug 建议 `C0p1/C0p2/C0p5/C1/C2`（等待与 canonical 命名比对）。
7. **温度**：ambient = 298.15 K 固定，无 T_cell 通道；等温假设为唯一可用假设（勿称"验证"）。
8. 电压窗：充电 4.2 V / 放电 2.5 V（模型端若需 cutoff 事件，half-cell 放电电压下限应按 2.5 V 校验而非 full-cell 常用值）。

## 8. 与参数集匹配预判（待 H2 核实）

若 Jackowska2025_2mAh_cm2 确为本文 2 mAh cm⁻² 电极的同一配方/同一批参数化来源，则匹配等级**拟 A / exact（matched half-cell pilot）**，
与 CALCE 的 B 级 surrogate 形成对照。但必须在 H2 中核实：①论文/代码确用该参数集拟合本数据；②面积几何自洽；③放电截止与 OCP 定义一致。
当前 H1 阶段**不锁定** metadata，仅记录预判。

## 9. 后续

H2：clone `Battery-Intelligence-Lab/Jackowska-2025-JPS` → 审计 pyproject/PyBaMM 版本约束/参数集定义与几何；
H3：平台外 half-cell DFN/SPMe preflight。均不修改 `battery_sim/`。
