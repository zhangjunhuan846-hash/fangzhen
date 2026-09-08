# v0.4 封版报告 — Chemistry generalization（A123 LFP/Graphite）

日期：2026-09-08　|　状态：**封版，平台建设到此为止**（55 → 64 → 74 tests，
v0.2/v0.3 zero-regression gate 全部通过）

## 0. 一句话结论

A123（LFP/石墨）经新 adapter 进入**同一个** replay runner / evaluator /
输出 schema，runner 与 evaluator 的科学计算逻辑修改数 = **0**，
model factory 修改数 = **0**。至此四个维度全部证明：

```text
Data source generalization    ✓  v0.2  (Maccor + Arbin)
File-format generalization    ✓  v0.2  (CSV + XLSX + XLS)
Protocol generalization       ✓  v0.3  (CC → DST/FUDS/US06)
Chemistry generalization      ✓  v0.4  (NMC/LCO → LFP)
```

## 1. Step 28/29 数据审计（docs/v04_step28_a123_audit.md）

- `data/raw/LIB/LFP_Graphite/CALCE_A123/`：archive zip 保留，raw/ 已解压。
- **每 cell 一个 xlsx（A1-007 / A1-008）内含 DST+US06+FUDS 三个动态段**（与
  20R 的"每窗口一文件"结构不同）；每段前有独立满充（CC 1.1A → CV 3.6V）+ rest。
- 动态段规则识别（混合符号 + |I|峰≥1A + 点数最大）→ 恰好 3 个候选
  （Step 8/16/24）；协议身份由**充电峰签名规则**判定（US06 回充峰最小 0.83A、
  FUDS 最大 2.06A、DST 1.93A——与 v0.3 20R 的符号特征跨数据集交叉印证），
  并与 CALCE 归档顺序 DST-US06-FUDS 交叉验证，不一致即报错。
- 原始符号 discharge=− → 翻转；时间单调、无重置、无 NaN；近零 dt 事件点处理同 20R。
- **A123 有实测温度列**（`Temperature (C)_1`，26.5–28.4 °C）。**温度语义
  （v0.4 终版冻结）**：实测电芯温度 T_cell,exp(t) 是**响应量**，只保留在
  canonical 列 `temperature_cell_C` 作 **validation target**，绝不驱动模型；
  等温回放环境 = **动态段前静置末端实测电芯温度**（规则提取：动态段起点前
  紧邻静置段 |I|<0.05A 的最后 120 s 中位数），同时用于 initial 与 ambient，
  全程固定。archive 无 chamber 传感器，故标
  `ambient_temperature_source: assumed_from_preprofile_rest_cell_temperature`
  （实测静置末端 26.8–27.6 °C）。未来打开 thermal 模型后，才是
  T_sim(t) vs T_cell,exp(t) 的比较；等温假设本身此时**尚未被验证**。
- 电芯身份（证据链：CALCE 官方页 + Batteries 2023 论文引用 + A123 原厂规格 +
  数据内证）：A123 Systems APR18650M1A，LFP/石墨，1.1 Ah（实测满充 1.04 Ah），
  18650，2.0–3.6 V（数据实测一致）。无 unknown 项。

## 2. Step 30 参数集审计（docs/v04_a123_parameter_audit.md）

- PyBaMM 26.8 全集枚举 + 实测 build：**唯一锂离子 LFP/石墨参数集 = Prada2013**
  （`LFP_ocp_Afshar2017` + Chen2020 石墨 OCP，2.3 Ah，**2.0–3.6 V 与 A123 逐位
  一致**，SPM/SPMe/DFN 全部可 build）。
- Chayambuka2022 是钠离子（NVPF/硬碳）、Ai2020 是 LCO，均排除。
- **Prada2013 = B 级 compatible_surrogate**（`fitted_to_dataset: false`）。
  判级不随"名字里有 LFP"自动升高：同一 Prada2013 在 v0.2 对 CS2(LCO) 是 C 级。

## 3. Step 33 — LFP 平台诊断（只记录，不改 evaluator）

- **平台性诊断（关键发现）**：Prada2013 的 LFP OCP 在高 SOC 区极陡，而在平台区
  极平——初始 SOC 从 0.98 → 0.995 变化，三协议 RMSE 变化 < 0.5 mV
  （DST 199.69 / FUDS 198.12 / US06 176.56 mV 几乎不动）。该观察的成立范围
  **仅限于**：Prada2013 surrogate + 当前三个动态工况 + 0.98–0.995 这一局部
  SOC 初始化区间。它只说明**在此范围内电压误差对 initial SOC 数值初始化不
  敏感**；**不能**据此推断该数据集对正极参数（OCP、扩散、动力学、活性材料
  比例等）不可辨识——参数辨识涉及多个方向，initial-SOC 局部不敏感不能代表
  其余参数都不可辨识。
- 回放曲线（Vexp/Vsim/residual）已在输出目录逐窗口落盘
  （`{PROTOCOL}_Vt.png` + `{PROTOCOL}_time_aligned.csv`）。
- 平台对齐差异**只记录不修**：未改 OCP、未 fitting。

## 4. Step 34 — initial-state 语义（v0.3 冻结规范延续）

A123 的每个动态段从协议自身的满充出发（与 20R 的 50/80% 变体不同）。
但 surrogate 下不能直接用 nominal SOC 1.0：Prada2013 模型 OCV 在 SOC 1.0 处
**正好压在它自己 3.6 V 上截止事件边界上**（surrogate 化学计量窗口失配），
任何回充噪声即触发求解终止。处理（config 持有，adapter 无默认值）：

```json
{
  "initial_state": {
    "type": "surrogate_ocv_mapped_soc",
    "value": 0.995,
    "purpose": "stable surrogate initialization",
    "fitted_to_voltage": false,
    "source": "protocol full charge; highest audited SOC not at the Prada2013 upper-cutoff event boundary (model rest V 3.484 V vs measured 3.554 V; RMSE insensitive over 0.98-0.995)",
    "history_replayed": false,
    "is_exact_electrochemical_state": false
  }
}
```

**措辞禁令（v0.4 冻结）**：0.995 只能表述为 "stable surrogate
initialization"——它**不是**实验测得的真实 SOC，**不是** "A123 实际
SOC = 99.5%"，也未对实测电压做 fitting。metrics/provenance 已带
`initial_state_purpose` 与 `initial_state_fitted_to_voltage` 列。

**解读禁令**（延续 v0.3）：不得由不同 protocol/cell 的 RMSE 差直接声称模型
泛化优劣；RMSE 混有 surrogate 参数失配、SOC–stoichiometry 映射失配、历史未
重放、模型动态响应误差四重来源。所有 A123 RMSE 仅作 software regression reference。

## 5. DST/FUDS/US06 完整输出（同一 runner，SPMe / Prada2013）

```text
python run_pipeline.py --dataset calce_a123 --mode baseline --model SPMe --cell 007 --protocol DST
  A1-007  DST  RMSE(t)= 199.69 mV | MAE 132.35 | coverage 1.00
  A1-007  FUDS RMSE(t)= 198.12 mV | MAE 132.02 | coverage 1.00
  A1-007  US06 RMSE(t)= 176.56 mV | MAE 122.02 | coverage 1.00
  A1-008  DST  RMSE(t)= 211.58 mV | MAE 146.18 | coverage 1.00
  A1-008  FUDS RMSE(t)= 226.70 mV | MAE 155.37 | coverage 1.00
  A1-008  US06 RMSE(t)= 209.03 mV | MAE 146.52 | coverage 1.00
```

（温度为静置末端固定值后重锁定的 v0.4 golden。与改用前（剖面内温度中位数）
相比差 < 0.5 mV——该差异只说明**当前等温模型对约 0.5 °C 的环境温度定义
变化不敏感**，**不构成对等温假设的验证**；等温假设成立与否需靠实验
T_cell(t) 与热模型预测的比较，或证明整个测试温升足够小来判定。）

无 `run_a123.py`/`run_lfp.py`，无 `if chemistry == "LFP"` 分支；chemistry
差异完全由 config（parameter_set: Prada2013 + cutoff 2.0/3.6 + 参数判级块）
与 model factory 的既有 `load_parameter_values` 消化。

## 6. Step 35 — regression tests

`tests/test_a123.py`，10 用例（任务书要求的 10 个名称全部实现）：
registry / file_reading / sign_conversion / time_monotonic / protocol_list /
dst / fuds / us06 / parameter_match（build 实测）/ cli（实跑 + schema 断言）。
Golden 锁定：source step、n_points、duration、电流峰、起止电压、积分电量、
静置末端环境温度（恒定校验）；RMSE 仅作软件回归。

**全套 74 passed（v0.2 55 + v0.3 9 + v0.4 10），0 failed。**

## 7. Step 36 — zero-regression gate

| Golden | 期望 | 实测 | 状态 |
|---|---|---|---|
| Chen2020 reproduction SPMe cell02 | 82.33 / 115.81 / 70.02 / 46.84 mV | 同 | ✅ |
| CALCE CS2_33 / CS2_35 baseline | 200.37 / 269.93 mV | 200.365 / 269.929 | ✅ |
| CALCE 20R 6 窗口（v0.3） | 152.79 / 275.57 / 151.06 / 271.04 / 172.33 / 287.59 | 同，逐位 | ✅ |

```text
runner scientific logic modifications for v0.4 = 0
evaluator scientific logic modifications       = 0
model factory scientific logic modifications   = 0
```

v0.4 新增/改动清单：`battery_sim/datasets/calce_a123.py`（新）、
`tests/test_a123.py`（新）、configs `calce_a123` 条目（新）、
`scripts/audit_a123_step28.py`（新审计脚本）。baseline.py / evaluation /
models / registry / 既有三个 adapter：**零改动**。

## 8. 四数据集架构总表（最终验收图）

```text
Dataset      Format       Chemistry       Parameter set   Protocol        Cells
-------------------------------------------------------------------------------
Chen2020     Maccor CSV   NMC/Graphite    Chen2020 (A/exact)   CC C10..1.5C    02/03/04
CALCE CS2    Arbin XLSX   LCO/Graphite    Ramadass2004 (B)     CC 0.5C/1C      33/35
CALCE 20R    Arbin XLS    NMC/Graphite    Chen2020 (B)         DST/FUDS/US06   SP20-2
A123         Arbin XLSX   LFP/Graphite    Prada2013 (B)        DST/FUDS/US06   A1-007/008
                │               │              │                  │
                └── adapters ───┴──────┬───────┴────────┬─────────┘
                                       ↓                ↓
                          canonical schema (t, I(t), Vexp(t))
                                       ↓
                     同一 baseline/replay runner（protocol-agnostic）
                                       ↓
                            同一 evaluator / 输出 schema
```

## 9. v0.4 limitations

1. Prada2013 fitted to 2.3 Ah LFP 软包，非 APR18650M1A：容量 2.3 vs 1.1 Ah、
   电极几何不同 → 模型内 3.85 A 峰值仅 1.67C；结构性偏差。
2. 初始状态是 surrogate OCV 映射的**稳定数值初始化**（0.995，purpose=
   stable surrogate initialization，fitted_to_voltage=false），非电化学
   精确状态，非实测 SOC；history 未重放。
3. LFP OCP 平台使 V(t) 对初始 SOC 数值（0.98–0.995）不敏感——观察范围仅限
   Prada2013 surrogate + 三个动态工况 + 该局部 SOC 区间；**不得**延伸为
   "该数据集不适合做正极参数辨识"（OCP/扩散/动力学/活性材料比例等多个方向
   的辨识性与此处无关）。
4. 未做 thermal。实测 T_cell,exp(t) 仅作 validation target 保留；等温回放
   环境为静置末端实测温度（assumed_from_preprofile_rest_cell_temperature，
   archive 无 chamber 传感器）。**等温假设未被验证**——仅知等温模型对
   约 0.5 °C 的环境温度定义变化不敏感。未做 DFN 对比扩展、未 fitting。
5. A123 协议身份由电流签名规则判定（有跨数据集交叉验证），但未与 CALCE
   原始测试程序文件逐段比对——provenance 已完整记录识别依据。

## 10. 平台建设阶段收尾

按任务书：**v0.4 完成后停止，不做 v0.5+**。下一步从"建平台"转向"用平台做
科学"，候选方向：A) physics-model transferability（exact vs surrogate ×
CC/dynamic 失效边界）；B) parameter identifiability & transfer（单数据集
calibration → freeze → unseen protocol/cell 外部验证）。
