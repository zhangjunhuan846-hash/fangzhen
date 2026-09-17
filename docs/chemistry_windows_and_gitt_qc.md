# 用户数据 QC 的两项新增门：体系锚定电压窗 + 脉冲协议分级

> 适用范围：`user_tools/`（自服务导入通道）。**平台科学核心未改动。**
> 起因：2026-09-17 对导师「冻结前补 4 点」清单的核对 —— 清单里的「数据 QC」与
> 「GITT 采样间隔升级」两项在实现后发现只剩两个真缺口，就是本文档这两件。

## A. 体系锚定电压窗口（chemistry-anchored）

### 原来缺什么

`VOLTAGE_RANGE`（第 6 项）只做「数据 vs **用户自己填的窗口**」的对账。
用户把石墨半电池的窗口填成 `[0.005, 15]` V，那项检查会 **PASS** ——
声明与数据自洽，但**声明本身是错的**，而仿真层不会因此报错，
只会把整段曲线按一个不存在的窗口跑完。

### 现在做了什么

规则表：`battery_sim/datasets/chemistry_windows.py`（纯规则，无 pandas/pybamm 依赖）。
每条规则带 **两组界**：

| 组 | 含义 | 越界后果 |
| --- | --- | --- |
| `nominal` | 该体系**通常**用的窗口 | WARN（部分窗口/厂商窗口是正当的，不判死） |
| `hard` | 对**该体系而言物理上讲不通**的界 | FAIL（石墨半电池里出现 20 V 不是窗口宽，是单位/参比/通道错了） |

已收录（闭集，每条都写了 rationale 与 source）：

| system_id | 体系 | nominal | hard |
| --- | --- | --- | --- |
| `graphite_halfcell_li` | 石墨 ‖ Li 金属（半电池，工作电极 = 石墨） | 0.005–1.5 V | 0–2.5 V |
| `nmc_fullcell` | NMC/石墨 全电池 | 2.5–4.2 V | 1.5–5.0 V |
| `lco_fullcell` | LCO/石墨 全电池 | 2.7–4.2 V | 1.5–5.0 V |
| `lfp_fullcell` | LFP/石墨 全电池 | 2.0–3.65 V | 1.0–4.5 V |

两处检查码：

- `VOLTAGE_WINDOW_SYSTEM`：声明窗口 vs 体系窗口
- `VOLTAGE_SYSTEM_RANGE`：实测极值 vs 体系窗口

**锚定靠声明，不靠推断**：半电池只认显式写出的工作电极材料
（`working_electrode_material`，别名表是闭集）。没写就 **WARN 说明检查被跳过**，
而不是 PASS —— **跳过 ≠ 通过**。同理，`cell_configuration=half_cell`
**不会**被推断成石墨。

### 实验侧要填的新字段

`user_dataset_template/dataset_info.xlsx` 的 experiment 表新增
`working_electrode_material`（下拉：graphite / nmc / lfp / lco / lithium_metal /
silicon_c / other）。石墨半电池填 `graphite` + 对电极 `lithium_metal`
⇒ 自动命中 0.005–1.5 V 规则。

### 怎么扩展

改 `WINDOWS` 闭集（加一条 `VoltageWindow`）。三件事必做：
① 写 `rationale`（为什么是这两组界）② 写 `source`（依据在哪）
③ 在 `tests/test_user_data_qc.py` 加一条正例 + 一条边界例。
**不要**为了"让用户的数据过"而放宽容差。

## B. 脉冲协议 QC 分级 + 脉冲时长核对

### 原来缺什么

`SAMPLING_INTERVAL_GAP` 对任何数据都只报 WARN。对 GCD 这是对的
（插值能补），但对 GITT/PITT 是致命的：**D_s 由脉冲时长与 ΔV 算出来**，
一个断点就同时改掉这两个量 —— 而报告里看不出区别。

另外「声明脉冲 10 min、实际跑了 11 min」这类错，平台原先完全看不见。

### 现在做了什么

新增 `protocol_type` 字段（**闭集**：GCD / GITT / PITT / pOCV / rate_capability /
cycle_life / EIS / other）。自由文本的 `protocol` 字段保留原样（仪器档位名要留），
**但不参与分级**；用户只填了自由文本时，只在里面找无歧义的脉冲写法
（`gitt` / `pitt` / `pulse` / `脉冲`）来补齐，识别不到就保持"未知"——
**不许默认成 GITT**，否则一份普通 GCD 也会吃脉冲级判据。

分级与新增检查：

| 检查码 | 触发 | 判据 | 级别 |
| --- | --- | --- | --- |
| `SAMPLING_INTERVAL_GAP` | 最大间隔 > 20× 中位间隔 | 脉冲协议下 = 结构性缺陷 | GCD: WARN / 脉冲: **FAIL** |
| `GITT_STRUCTURE` | 按 5 % 峰值电流切段后脉冲段数 < 2，或没有静置段 | 这不是脉冲数据 / 被截断 / 无法定义 ΔV | FAIL |
| `GITT_PULSE_DURATION` | 实测中位脉冲时长 vs 声明 `pulse_duration_s` | 相对差 > **5 %** -> FAIL；未声明 -> WARN 并报出实测值 | FAIL / WARN |
| `GITT_PULSE_UNIFORMITY` | 脉冲之间的时长离散 | `std/median > 0.10` -> FAIL | FAIL |
| `GITT_PULSE_RESOLUTION` | 脉冲**内部**的采样间隔 | > 3× 中位间隔 -> FAIL（比全局那条严格得多，专门针对"脉冲内部掉点"）；> 脉冲时长/20 -> WARN | FAIL / WARN |

阈值写 `user_tools/validate.py` 第 12 节里（它们是**判据**不是平台约定；
改判据必须同时改 `tests/test_user_data_qc.py`）。

实验侧要填：`protocol_type=GITT`、`pulse_duration_s`、`relax_duration_s`。
填了才核对得上；不填只给 WARN 并报出实测值（实测值才是算 D_s 该用的那个）。

## 实测证据（2026-09-17）

- `python -m pytest tests/test_user_data_qc.py -q` -> **29 passed**
- Demo 包（Birmingham NCM 半电池，未声明工作电极材料）：
  `python -m user_tools.import_dataset --package examples/half_cell_demo`
  -> 13 项检查 / 严重 0 / 警告 3（新增的那条 WARN 就是"体系窗口检查被跳过"，
  理由写的是缺哪条声明）。**导入仍然 PASS**：新增门没有把正常数据变成错误。

## 两个入口，一份规则（2026-09-17 晚补齐）

**原来只有一个入口**：规则接在自服务导入通道上，而真实样品走的是材料元数据路径
（`metadata/*.yaml` → adapter）—— 结果是「demo 数据很严格、自己的实验数据反而绕过」。
真实商业石墨四个样品全走第二条，所以这条必须补。

补法是**共用同一张表，不复制规则**：

```text
battery_sim/datasets/chemistry_windows.py      <- 唯一规则源 + 唯一词表
        ├── user_tools/validate.py              -> VOLTAGE_WINDOW_SYSTEM / VOLTAGE_SYSTEM_RANGE
        └── material_metadata.validate_voltage_window()   -> 由 validate() 调用
                （因此 `--series` 与 adapter 的 `--validate` 都经过它）
```

材料元数据新增三个**可选**键（都在 `cell:` 下，模板已预填）：

| 键 | 闭集 | 作用 |
| --- | --- | --- |
| `cell.working_electrode_material` | graphite / nmc / lfp / lco / lithium_metal / silicon_c / other | 规则靠它锚定；石墨样品填 `graphite` |
| `cell.counter_electrode_type` | lithium_metal / graphite / other | 机器可读的对电极类型 |
| `cell.voltage_window_V` | `[下限, 上限]` V | 与体系参考窗口对账 |

**为什么还要一个"类型"字段**：`cell.counter_electrode` 与 `cell.electrolyte` 是人写的描述
（例「Li 片 φ15.6 mm × 0.45 mm（过量）」、`<1 ppm H2O/O2`），规则表不该去解析自由文本。
这与 configs 里 `working_electrode`（PyBaMM 槽位）vs `physical_working_electrode`（物理含义）
是同一套做法：**给人看的写自由文本，给代码看的写闭集**。

两个口径与自服务通道完全一致：缺声明 → WARN 说明检查被跳过（跳过 ≠ 通过）；
越 `hard` 界 → error；越 `nominal` 界 → warning。

**唯一性由测试钉住**：`tests/test_material_voltage_window.py::test_vocabularies_have_a_single_source`
断言两个入口的词表都来自 `chemistry_windows.py`（加一条新体系时只改一处）；
`tests/test_material_voltage_window.py::test_templates_declare_the_anchor_fields` 断言
四个石墨模板都自带锚定声明 —— 否则四个真实样品会一起掉进"检查被跳过"。

**`cell_configuration` 可以不声明**：「工作电极 = 石墨 且 对电极 = 锂金属」这一对声明
本身就唯一确定了半电池（全电池不存在锂金属对电极）。这不是推断，是读两条显式声明；
正因如此，如果同时声明 `full_cell` 却给了锂金属对电极，解析器报**「自相矛盾」**而不是挑一个信。

## 与导师清单的差异（记录，免得被问）

1. 清单写石墨下限 **0.01 V**，平台设计口径是 **0.005 V**
   （`docs/graphite_heat_treatment_test_plan.md`）。下限决定锂化端能到哪，
   以设计文档为准。
2. 清单建议的键名 `heating_rate_C_min` / `cooling_method` / `container`
   与现有闭集冲突（已有 `ramp_rate_C_per_min` / `cooling` / `crucible`）。
   **加键必须改闭集常量**，不是新加键名就完事。
