# v0.2 Step 12–13：CALCE 数据审计报告 + Canonical Schema 映射定义

> 状态：**待评审**（评审通过后才进入 Step 14 写 adapter）
> 日期：2026-09-07
> 审计脚本：`scripts/audit/audit_calce_cs2*.py`（只读，未修改任何数据）
> 硬约束重申：Step 14 起 `battery_sim/simulation/*.py` 与 `battery_sim/evaluation/*.py` **禁止修改**。

---

## Part I — Step 12 数据审计

### 1. 本地 CALCE 数据资产盘点（均已解压可用）

| 数据集 | 路径 `data/raw/LIB/...` | 电芯 | 格式 | 适合 v0.2 吗 |
|---|---|---|---|---|
| **CALCE_CS2** | `LCO_Graphite/CALCE_CS2/raw/{CS2_3,CS2_33,CS2_35}/` | 3 只 LCO 方形 1.1 Ah | Arbin `.xlsx`（MITS_PRO） | ✅ **首选** |
| CALCE_A123 | `LFP_Graphite/CALCE_A123/raw/` | A1-007/008 | `.xlsx` | 仅动态工况（DST/FUDS/US06）+ OCV，无干净 CC 放电纵向切片 |
| CALCE_INR18650_20R | `NMC_Graphite/CALCE_INR18650_20R/raw/` | SP20-1/20-2 | `.xls`（BIFF 旧格式，需 xlrd） | 动态工况 + OCV；动态工况可作后续 replay 素材 |

**选型结论：vertical slice = CS2_33**。理由：
1. 协议最干净：0.5C 恒流放电（0.55 A）→ 2.7 V，CC-CV 0.5C 充电 → 4.2 V → CV 至 0.05 A（官方页 + 文件内 Schedule_File_Name `CS2_point5C.sdu` 双重印证）；
2. CS2_3 是变倍率循环（0.11–2.2 A 交替），CS2_35 是 1C —— 留作后续 "1 cell × multiple rates" 扩展；
3. 数据最完整（CS2_33 23 个文件，2010-08-17 → 2011-02-02，~500 循环）。

### 2. 文件格式（实测 `CS2_33_8_17_10.xlsx`）

- 每个 `.xlsx` 两张表：`Info`（测试元信息，无温度字段）+ `Channel_1-006`（数据）。
- 数据列（17 列，dtype 已核实）：

```
Data_Point, Test_Time(s), Date_Time, Step_Time(s), Step_Index, Cycle_Index,
Current(A), Voltage(V), Charge_Capacity(Ah), Discharge_Capacity(Ah),
Charge_Energy(Wh), Discharge_Energy(Wh), dV/dt(V/s), Internal_Resistance(Ohm),
Is_FC_Data, AC_Impedance(Ohm), ACI_Phase_Angle(Deg)
```

- 采样：CC 段约 **30 s** 一点（240 pts / 放电段）；CV/静置段采样变疏。
- 一个文件 = 一天的连续循环（CS2_33_8_17_10 含 23 个完整循环，10759 行）。

### 3. 关键陷阱（audit 发现，adapter 必须处理）

| # | 发现 | 证据 | 对策（进 Step 13 映射） |
|---|---|---|---|
| T1 | **符号约定与 Chen2020 相反**：充电为正（+0.55 A）、放电为负（−0.55 A） | Step 2 mean=+0.55（充至 4.2V）；Step 7 mean=−0.55（放至 2.7V） | 映射时翻转：`I_canonical = −I_CALCE`，得"放电为正" |
| T2 | **`Discharge_Capacity(Ah)` 是文件内累计值，不是每循环容量** | 单文件 Q_dis 最大 23.7 Ah ≈ 23 循环 × ~1.03 Ah | **禁止直接用该列**；容量一律由 I(t) 积分得到（平台 baseline 本就如此） |
| T3 | **文件名排序 ≠ 时间顺序**（如 `CS2_33_9_7_10` 按字典序排最后，实为最早 2010-09-07） | 实测 chronological sort 对比 | 排序键 = 从文件名解析日期 `M_D_YY` |
| T4 | Cycle_Index/Step_Index **在每个文件内重新从 1 开始** | 各文件 Cycle_Index 均 1..N | 全局循环号 = 文件序号偏移 + 局部 Cycle_Index |
| T5 | 存在**伪 step**（单点、电流≈0.003 A 的 Step 6；Step 9 末尾杂点） | step 表实测 | 放电段判定必须按"段内 mean 电流阈值 + 最小点数"，不能只看 Step_Index |
| T6 | Step 4 是 **CV 段**（电流 0.97→0.05 A 衰减），不是 CC | step 表：mean 0.498, min 0.05, max 0.97 | CC-CV 识别：CC 段后接恒压段（|I| 单调衰减 + V 恒定） |
| T7 | **数据文件无温度列、Info 表无温度记录** | 列清单 + Info 表全文 | 环境温度只能取文档假设（见 §4） |

### 4. 电池规格与测试条件（官方 CALCE 页 + 文献交叉核实）

| 项 | 值 | 来源 |
|---|---|---|
| 标称容量 | 1.1 Ah（1100 mAh） | CALCE 官方页 |
| 化学体系 | **LCO/石墨**（EDS 示痕量 Mn） | CALCE 官方页 |
| 尺寸/重量 | 5.4 × 33.6 × 50.6 mm，21.1 g（方形软包形） | CALCE 官方页 |
| 充电协议 | CC-CV：0.5C → 4.2 V → CV 至 <0.05 A | CALCE 官方页 |
| 放电截止 | 2.7 V（CS2_33@0.5C=0.55 A；CS2_35@1C=1.1 A） | CALCE 官方页 + 实测 |
| 实测电压窗 | 2.699 – 4.200 V | 文件审计 |
| **环境温度** | **官方页未记录**；第三方数据集综述（Kirkaldy et al.）认为 CS2 系室温 **~23 °C**；个别二手资料称 25 °C | ⚠️ 平台取 **25 °C 作为 modeling assumption**（`temperature_source: assumed`, `temperature_confidence: low`）——**不是** documented assumption，写入 run_metadata.notes，不冒充实测 |
| 首文件初始状态 | 文件起点为静置（V≈3.38 V，部分 SOC）→ 每 file 先充满再循环 | 文件审计 |

### 5. Vertical slice 候选段（Step 15 目标）

**`CS2_33_8_17_10.xlsx`（首个文件）Cycle 2 / Step 7：**
- 240 点、30 s 采样、I = −0.5502 A（canonical 翻转后 +0.5502 A）
- V：4.108 → 2.700 V，历时 7082 s
- 起点紧跟"CV 充满 + 短静置"→ 初始 SOC ≈ 100%，初始电压由静置末段确定
- 该段干净（无伪点、无 RPT 插入），是 ideal vertical slice

### 6. Chemistry–parameter 兼容性预判（Step 16 提前定调）

| 数据集电芯 | 化学体系 | PyBaMM 候选参数集 | 判级 |
|---|---|---|---|
| CS2（LCO/石墨，1.1 Ah 方形） | LCO | **Ramadass2004**（graphite / **LiCoO₂** / LiPF6；PyBaMM 官方警告其为混合 "Frankenstein" 参数集） | **B: compatible_surrogate**（已实测 PyBaMM 26.8.0.0 中存在、可加载、SPM/SPMe/DFN 可 build；几何 1.0 Ah 与 CS2 不同）——产出一律标注 *unfitted surrogate baseline* |
| （对照）Ecker2015 用于 CS2 | **Kokam SLPB75106100 = graphite / Li(Ni₀.₄Co₀.₆)O₂，不是 LiCoO₂** | Ecker2015 | **C: mismatched**（化学体系不匹配）——仅工程链路对照，禁止物理解读。**修订记录：初版误判 Ecker2015 为 B 级 LCO surrogate，已纠正** |
| A123（LFP） | LFP | Prada2013 | B 级（后续版本） |
| INR18650-20R（NMC） | NMC | Chen2020 | B 级（几何/成分仍有差异，后续版本） |

> CS2 不存在 exact-match 公开参数集 —— 这本身就是 Step 16 的核心结论：**所有 CALCE 仿真都只能是 transfer baseline，不得称为 physics-model validation。**

---

## Part II — Step 13：CALCE → Canonical Schema 映射定义

### 1. 字段映射（CALCE Arbin → 平台 canonical trace）

| Canonical 字段 | 来源 | 变换 |
|---|---|---|
| `time_s` | `Test_Time(s)` | 文件内局部时间（文件起点 t=0）；不跨文件拼接（v0.2 slice 只用单文件） |
| `current_A` | `Current(A)` | **取负**：`I_canon = −I_CALCE` → 放电为正（对齐 Chen2020 约定） |
| `voltage_V` | `Voltage(V)` | 直通 |
| `capacity_Ah` | 由 I(t) 积分 | `cumtrapz(I_canon)/3600`；**不用** `Discharge_Capacity(Ah)`（陷阱 T2） |
| `cycle_index` | `Cycle_Index` | + 文件级偏移（陷阱 T4） |
| `step_index` | `Step_Index` | 直通（段判定见下） |
| `temperature_C` | 无数据 | 常数 = config 中 `ambient_temperature_C: 25.0`（documented assumption） |

### 2. 放电段判定规则（canonical segmentation）

```
is_discharge_step = (sign-flipped mean current > 0.5 × I_nominal_1C)
                    AND (n_points >= 10)          # 排除伪 step（T5）
                    AND (ΔV < 0.05 V 全程)         # 排除 CV 段（T6，CV 段 V 恒定）
```

充电 CC 段、CV 段、静置段按同样阈值族归类；RPT/阻抗插入点（`Is_FC_Data`、AC_Impedance 列）在 slice 中直接排除。

### 3. 初始状态（initial state）定义

- **baseline/replay 语义**：取目标放电段之前的最近一个静置段（step mean |I| < 0.01 A）末 5 min 电压中位数 = `V0`；
  slice 段（cycle2/step7）的 `V0 ≈ 4.108 V`（紧跟 CV 充满 + 短静置）。
- PyBaMM 侧沿用已验证的 `initial_soc=f"{V0:.5f} V"` + `calc_esoh=False` 路径（经 runner 参数传入，不改 runner）。

### 4. `run_metadata.json` 新增 `parameter_match` 块（全局 schema 扩展，Chen2020 侧回填 `exact`）

```json
"parameter_match": {
  "level": "exact | compatible_surrogate | mismatched",
  "parameter_set": "Ecker2015",
  "experimental_cell": "CALCE CS2_33 (LCO/graphite, 1.1 Ah prismatic, 5.4x33.6x50.6mm)",
  "notes": "Ambient temperature undocumented by CALCE; 25 C assumed (literature: room temp ~23-25 C). Unfitted surrogate baseline - NOT physics-model validation."
}
```

规则：
- `level=compatible_surrogate` 的 run，其 metrics 表头/绘图标题自动带 `unfitted surrogate` 标注；
- `level=mismatched` 的 run 允许执行，但输出标注 "engineering chain check only — no physical interpretation"；
- 三层级判据与 Step 16 audit 一致，未来 NASA/Oxford/SIB 复用此 schema。

### 5. `configs/datasets.yaml` 中 calce 条目草案

```yaml
calce_cs2:
  name: "CALCE CS2 (LCO/Graphite)"
  ion: "Li"
  chemistry: "LCO_Graphite"
  raw_dir: "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw"
  adapter: "calce_cs2"
  protocol: "calce_cs2"          # CC-CV 充 + CC 放翻译层
  parameter_set: "Ecker2015"      # level: compatible_surrogate
  nominal_capacity_Ah: 1.1
  lower_voltage_cutoff_V: 2.7
  upper_voltage_cutoff_V: 4.2
  ambient_temperature_C: 25.0     # documented assumption（官方未记录）
  sign_convention: "calce_arbin"  # charge=+, discharge=- → adapter 内翻转
  cells: ["33", "35"]             # v0.2 先 33；35(1C) 作多倍率扩展
  rates: ["0p5C"]                 # CS2_33；CS2_35 另列 1C
  supported_models: ["SPM", "SPMe", "DFN"]
```

### 6. 对核心 runner 的零修改承诺（成功标准核对）

| 平台组件 | 是否需要改动 | 说明 |
|---|---|---|
| `simulation/baseline.py` | **否** | 消费 canonical trace（time/current/voltage/V0/T），与 Chen2020 完全同构 |
| `simulation/reproduction.py` | **否**（v0.2 slice 不触碰） | |
| `simulation/benchmark.py` / `sensitivity.py` | **否** | |
| `evaluation/metrics.py` / `plotting.py` | **否** | 仅 run_metadata 写入处按 schema 追加 `parameter_match`（writer 层，属 datasets/config 层职责） |
| `datasets/calce_cs2.py` | **新增** | 全部翻译逻辑集中于此 |
| `configs/*.yaml` | **新增条目** | |
| `registry.py` | **否** | 惰性加载机制天然支持新 adapter |

> 唯一灰色地带：`run_metadata.json` 的 `parameter_match` 写入点目前在 runner 内。若实现时发现必须改 runner，则改为 runner 之外的 writer 包装层，并把差异明确报告——不悄悄修改。

---

## 待评审决策点（2026-09-07 评审已回复，全部落实）

1. **Vertical slice**：✅ 批准 CS2_33 首文件作第一条 smoke-test discharge；**但 cycle/step 只能作为该文件的 locator，正式 adapter 禁止写死 cycle2/step7**。已实现：放电段识别完全基于规则（CALCE 电流符号、恒流幅值 ±10%、最小点数 ≥10、电压方向、2.7 V cutoff），实测自动定位到 cycle1/step7（BOL 满放电段）。
2. **Temperature**：✅ 平台默认 25 °C，但 metadata 必须标 `temperature_source: assumed`、`temperature_confidence: low`，不得写 documented。官方 CALCE metadata 未报告温度；secondary review 仅认为 ~23 °C room temperature。保留后续 23/25 °C robustness check（不阻塞 v0.2）。
3. **Parameter set（已纠正）**：❌ Ecker2015 不是 B 级 LCO surrogate——其 Kokam SLPB75106100 正极是 graphite/Li(Ni₀.₄Co₀.₆)O₂。已降为 **C 级 mismatched 对照**。v0.2 CS2 默认采用 **Ramadass2004**（graphite/LiCoO₂/LiPF6，B 级 compatible_surrogate，fitted_to_dataset=false，metadata 注明 PyBaMM "Frankenstein" 警告）。已在 PyBaMM 26.8.0.0 实测：`"Ramadass2004" in pybamm.parameter_sets` = True，ParameterValues 加载成功，SPM/SPMe/DFN 全部可 build（`scripts/audit/check_ramadass2004.py`）。
4. **Scope**：✅ v0.2 只接 `calce_cs2`；执行顺序细化为 14a（CS2_33 单段 slice）→ 14b（CS2_33 完整可用段）→ 14c（CS2_35 1C，验证同一 adapter 处理不同 cell/protocol）。A123/INR18650 留 v0.3。
