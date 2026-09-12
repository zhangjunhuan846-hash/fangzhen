# 石墨半电池接入：代码审计与实现计划（Step 1，只审计不编码）

日期：2026-09-10
范围：`run_pipeline.py`、`battery_sim/`、`configs/`、`tests/`、`outputs/`
目标链路：`dataset → chemistry → parameter extraction → PyBaMM → evaluation`（石墨负极半电池优先）

---

## 1. 当前架构理解

平台是**三层 + 注册表**结构，扩展方式是"新增文件 + 声明式配置"，不是改代码：

```
configs/*.yaml（声明）
      ↓  registry.py 按命名约定解析
battery_sim/datasets/<adapter>.py     纯数据 I/O（禁止 import pybamm）
      ↓  返回 canonical DataFrame（time_s/current_A/voltage_V/capacity_Ah/temperature）
battery_sim/simulation/*.py           开环 replay（zero-fit）
      ↓  models/pybamm_factory.py（建模 + 参数集加载）
      ↓  evaluation/{metrics,plotting}.py
outputs/platform/<dataset>/<task>/<MODEL>/cell<cell>/
```

### 1.1 已有模块职责

| 模块 | 职责 | 冻结 |
|---|---|---|
| `run_pipeline.py` | CLI 入口；`--config` YAML、位置参数 task、`--mode` | 可扩展（已支持 YAML 合并） |
| `battery_sim/registry.py` | `dataset_id → adapter` 解析（`battery_sim.datasets.<adapter>` + `PascalCase(adapter)+Adapter`） | ✅ 不改 |
| `battery_sim/config.py` | 读 `configs/*.yaml`（datasets/models/sensitivity） | ✅ 不改 |
| `battery_sim/schemas.py` | `DatasetConfig` 数据类 + 必填字段校验（`extra` 承载数据集专属块） | ✅ 不改 |
| `battery_sim/paths.py` | `ROOT` / 输出目录约定 | ✅ 不改 |
| `battery_sim/rates.py` | rate 归一化：`c_rate`（机器主键）/`rate_label`/`rate_slug`/`source_rate`/`legacy_rate` | ✅ 不改 |
| `battery_sim/datasets/base.py` | `BatteryDatasetAdapter` 接口（抽象基类） | ✅ 不改 |
| `battery_sim/datasets/*.py` | 5 个现有 adapter（chen2020 / calce_cs2 / calce_20r / calce_a123 / birmingham_ncm920305） | ✅ 不改（但**可以新增同目录文件**） |
| `battery_sim/simulation/{baseline,benchmark,reproduction,sensitivity}.py` | 四个 runner | ✅ 不改 |
| `battery_sim/models/pybamm_factory.py` | `build_model` / `build_model_options` / `load_parameter_values`；半电池走 `{"working electrode": "negative"}` | ✅ 不改 |
| `battery_sim/models/parameter_sources.py` | **外部参数集注册表**（`EXTERNAL_PARAMETER_SETS`）+ 直接模块导入 | ⚠️ 注册表条目可追加（需批准） |
| `battery_sim/evaluation/*` | 指标 + 绘图 | ✅ 不改 |
| `configs/datasets.yaml` | 数据集注册表（含半电池一等配置块） | ⚠️ 可追加条目 |
| `configs/chemistry.yaml` | 化学体系显式层（化学体系→电极/电解液/参数集/等级） | ⚠️ 可追加条目 |
| `tests/` | 98 项回归门 | 只新增 |

### 1.2 关键发现（审计结论）

1. **`base.py` 声明的接口与 runner 实际调用不完全一致**：
   `base.py` 定义 `load_discharge()`，但 `simulation/baseline.py` 实际调用的是
   **`load_processed_discharge(cell, rate)`**（鸭子类型，未在基类中声明）。
   新 adapter 必须实现该方法，否则 baseline 跑不通。
2. **`df.attrs` 是隐式契约**（决定初始化与溯源）：
   - `df.attrs["provenance"]`（可含 `initial_state`、温度来源、source_file…）
   - `df.attrs["initialisation"]`（可选）：`method ∈ {initial_soc, fixed_initial_concentration}`
   - `df.attrs["initial_soc"]`（full-cell 路径）
3. **baseline 会强制抽稀到 2000 点**（`_filter_and_downsample`），但**抽稀发生在 df 之后** →
   adapter 若把 9100 万行读进内存会直接 OOM。**抽稀必须在 adapter 内完成**。
4. **输出目录约定**：`outputs/platform/<dataset_id>/<task>/<MODEL>/cell<cell>/`，
   并写 `metrics.csv` / `run_metadata.json` / `<rate_slug>_time_aligned.csv` / `<rate_slug>_Vt.png`。
   这与用户目标的 `results/{voltage_fit.csv, voltage_fit.png, parameter_summary.json, report.md}`
   **不一致**——见 §7 的产物映射方案。
5. **半电池是一等配置**：`cell_configuration: half_cell` + `working_electrode: positive|negative`
   + `counter_electrode` + `model_options` 已在 datasets.yaml 与
   `build_model_options("half_cell_negative", ...)` 中支持 → **石墨半电池（工作电极=负极）无需改工厂代码**。
6. **参数集加载有两条路**：PyBaMM 内置名（直接 `ParameterValues(name)`）与
   `parameter_sources` 注册的外部仓库集合。**PyBaMM 内置 `Ecker2015_graphite_halfcell`
   可直接按名加载**（已验证存在于 `pybamm.parameter_sets`）。

---

## 2. 数据流

### 2.1 现有（命令级 / CC / 动态）
```
--dataset + --model + --cell + --rate
  → registry.get_dataset_config → DatasetConfig
  → registry.get_dataset      → Adapter(config)
  → adapter.rate_info(rate)   → c_rate/rate_slug/source_rate
  → adapter.load_processed_discharge(cell, rate) → DataFrame + attrs
  → baseline._run_one_replay  → pybamm.Simulation（实测电流作 Interpolant）
  → metrics + time_aligned.csv + Vt.png + run_metadata.json
```

### 2.2 新增（石墨半电池）——目标数据流
```
SINTEF .parquet / DLR .txt（只读）
  → [新 adapter]  → canonical DataFrame（含 window/分支语义 + attrs 溯源）
  → [新 extraction/]  → graphite_ocp.csv（双支）+ graphite_diffusion.csv（D_s vs SOC）
  → [新 parameters/]  → parameter_set.json（有效/表观参数 + 来源）
  → 回接 runner（先用 PyBaMM 内置 Ecker2015_graphite_halfcell 做 zero-fit）
  → outputs/... + report.md
```

---

## 3. 插入点分析（与你的目标目录的差异）

| 你的提议 | 仓库实际 | 建议 | 理由 |
|---|---|---|---|
| `battery_sim/adapters/` | ❌ 不存在；现为 `battery_sim/datasets/` | ✅ **新 adapter 放 `battery_sim/datasets/`**（新增文件，不改任何现有文件） | `registry.py` 硬编码了 `battery_sim.datasets.<adapter>` 路径 + 类名约定；换目录必须改 registry（违反冻结） |
| `battery_sim/extraction/` | ❌ 不存在 | ✅ **顶层 `extraction/`**（新包） | `battery_sim/` 冻结；顶层已有 `user_tools/`、`analysis/` 先例；提取属数据分析，不属仿真内核 |
| `battery_sim/parameters/` | ❌ 不存在 | ✅ **顶层 `parameters/`**（新包） | 同上；参数构建也不属仿真内核 |

**一句话**：adapter 必须进 `battery_sim/datasets/`（因为注册表按约定解析），
而 extraction / parameters 应放顶层新包（因为核心不可动）。

---

## 4. 新 adapter 的接口契约（必须实现）

| 成员 | 用途 | 备注 |
|---|---|---|
| `get_metadata() -> dict` | 数据集元数据 | 含 chemistry / cell_configuration / 温度来源 |
| `list_cells()` / `list_rates()` | CLI 枚举 | cell = 电芯 id；rate = 程序 id |
| `rate_info(rate)` | 归一化 rate | 继承基类即可，需提供 `SOURCE_TO_CANONICAL` |
| `load_raw(cell) -> DataFrame` | 原始（规范列） | 大文件必须**流式 + 抽稀** |
| **`load_processed_discharge(cell, rate)`** | **runner 真正调用的方法** | 返回 canonical 列 + `attrs` |
| `get_initial_state(cell)` | 初始 OCV | 半电池给 rest OCV |
| `get_ambient_temperature(cell)` | 环境温度 | SINTEF 无温度列 → config 声明 |

### 4.1 SINTEF 适配要点（已审计）
- 窗口定义：p-OCV 的**脱锂段**（+43.28 µA，0.01 → 1.0 V）对应平台语义的 `discharge`
  （半电池"放电"= 脱锂）；**锂化段 = charge**；两段都保留为独立 rate
- 分支识别：`Step Index` + 电流符号（step2 = 锂化，step4 = 脱锂，step3/5 = 静置）
- 符号：SINTEF 负电流 = 锂化 = 平台 canonical 的"充电（负）"→ **与平台符号一致，无需翻转**
  （与 Birmingham 相反，需在 provenance 里写明）
- 采样：8 Hz、91 M 行、121 天 → 必须流式抽稀（建议按时间或按点数抽稀，目标 ≤ 5k 点/窗口）
- 温度：文件无温度列 → 由 `datasets.yaml` 声明 RT 并记录来源等级
- 溯源：`file_sha256`（340 MB 全量哈希约 1 s，建议缓存），metadata.csv 提供
  直径/厚度/载量/面容量/活性物质占比

### 4.2 DLR 适配要点（待补审计）
- 解析：跳过 `~` 头行，空白分隔，按列位取值；`Time[h] → time_s`
- 单位：`Ah/kg` 需**活性物质质量**才能换 Ah（质量来源待确认）
- 段识别：`Command` / `State` 列（含 Pause 等）
- **符号约定待实测确认**（I>0 的物理含义）
- 名称 `Hydra.0b_A` + `Testchannel #12` → 需确认是单电芯还是多通道测试台

---

## 5. 参数集接线方案（三选一）

| 方案 | 做法 | 是否改 battery_sim | 建议 |
|---|---|---|---|
| **A** | 用 PyBaMM 内置 `Ecker2015_graphite_halfcell` 作 zero-fit 参比：只加 adapter + `datasets.yaml` 条目 | **零改动** | ✅ **先做这个，打通链路** |
| **B** | 生成的 `parameter_set.json` 接回 runner：在 `parameter_sources.EXTERNAL_PARAMETER_SETS` 追加一条（注册表，非科学逻辑） | 改 1 个 dict（需批准） | Phase D 再做 |
| **C** | 新包内自带 runner，复用 `pybamm_factory` + `evaluation` | 零改动 | 备选（产物格式更自由） |

---

## 6. 实现计划（分阶段，每阶段带最小测试）

> 原则：每阶段结束跑 `python -m pytest tests -q`（当前 **98 passed**），且新增测试**不依赖 13 GB 数据目录**
> （用 `tmp_path` 造微型 parquet / txt fixture）。

### Phase A — SINTEF adapter（最小闭环）
- 新增：`battery_sim/datasets/sintef_graphite.py`（类 `SintefGraphiteAdapter`）
- 追加：`configs/datasets.yaml` 条目（half_cell / working_electrode=negative /
  counter=lithium_metal / 参数集 `Ecker2015_graphite_halfcell` / 温度块 / 溯源块）
- 追加：`configs/chemistry.yaml` 增 `Graphite_LiMetal`
- 测试：`tests/test_sintef_graphite.py`（合成小 parquet：验证列映射、符号、窗口识别、抽稀、attrs 溯源）
- 验收：`python run_pipeline.py baseline --dataset sintef_graphite --model SPM --cell <id>`
  跑通并产出 metrics.csv（**数值不设阈值**，只验通路与语义）

### Phase B — 参数提取
- 新增：`extraction/ocp_extractor.py`（p-OCV 双支 → `graphite_ocp.csv`：SOC, Voltage, branch）
- 新增：`extraction/gitt_extractor.py`（GITT → `graphite_diffusion.csv`：SOC, D_eff, 拟合质量；
  用 `pybop.GITTFit`/`GITTPulseFit`）
- 测试：合成 GITT 波形（已知 D 的人造响应）验证提取器方向正确；名称强制
  `effective_diffusivity` / `apparent`
- 验收：输出两份 CSV + 每脉冲拟合 R² 记录；**不产生"材料常数"表述**

### Phase C — 参数构建
- 新增：`parameters/graphite_parameter_builder.py` → `parameter_set.json`
  （maximum concentration / particle radius / diffusivity function / OCP function / loading）
- 测试：JSON schema 校验 + 每个值必须带 `source` 字段（不许出现无来源数字）
- 验收：生成的文件可被 `pybamm.ParameterValues(dict)` 成功加载

### Phase D — Pipeline 集成
- 选项 B（注册表追加）或 C（独立 runner）
- 新增：`run_pipeline.py` 无需改动（用 `--config` + 新数据集条目）
- 验收：`python run_pipeline.py --dataset sintef_graphite --model SPM` 一条命令产出
  `voltage_fit.csv / voltage_fit.png / parameter_summary.json / report.md`
  （产物映射见 §7）
- 之后扩展 DFN

### Phase E — 报告与 Gate
- 新增：`report.md` 生成（含 provenance、匹配等级、措辞表）
- Gate 复核（数据可用性，非 RMSE 竞赛）：G1 平行样 / G3 OCP 双支 / G4 GITT 拟合质量 /
  G6 验证集不参与拟合

---

## 7. 产物与既有输出规范的映射（需你拍板）

| 你要求 | 平台现有 | 建议做法 |
|---|---|---|
| `voltage_fit.csv` | `<rate_slug>_time_aligned.csv` | 直接用现有文件（同义），不再另造一份 |
| `voltage_fit.png` | `<rate_slug>_Vt.png` | 同上 |
| `parameter_summary.json` | `run_metadata.json` + `<rate_slug>_parameter_mapping.json` | **新增** `parameter_summary.json`（仅石墨数据集写） |
| `report.md` | 无（现为 docs/ 手工报告） | **新增**，由新包生成，写入 `outputs/platform/<dataset>/.../report.md` |

即：**不破坏现有输出格式**（四个冻结数据集输出不变），只对石墨数据集**追加**两个文件。

---

## 8. 冻结边界清单

**可以新增（不改现有文件）**
- `battery_sim/datasets/sintef_graphite.py`、`battery_sim/datasets/dlr_graphite.py`
- 顶层 `extraction/`、`parameters/` 新包
- `tests/test_sintef_graphite.py`、`tests/test_dlr_graphite.py`、`tests/test_extraction.py`
- `docs/*.md`

**可以追加条目（既有文件，但属注册表/声明，非科学逻辑——需你批准）**
- `configs/datasets.yaml`、`configs/chemistry.yaml`
- `battery_sim/models/parameter_sources.py` 的 `EXTERNAL_PARAMETER_SETS`（Phase D，若走方案 B）

**不可修改**
- `battery_sim/simulation/*`、`battery_sim/evaluation/*`、`battery_sim/models/pybamm_factory.py`
- `battery_sim/registry.py`、`schemas.py`、`config.py`、`rates.py`、`paths.py`
- `battery_sim/datasets/base.py` 与现有 5 个 adapter
- 现有 98 项测试

---

## 9. 风险与待确认决策（5 条）

1. **目录方案**：接受"adapter 进 `battery_sim/datasets/` + 顶层 `extraction/`、`parameters/`"吗？
   （若坚持 `battery_sim/adapters/`，必须改 registry，等于解冻）
2. **第一个参比**：Phase A 先用 `Ecker2015_graphite_halfcell` 做 zero-fit（推荐），
   还是等自建参数集就绪再跑？
3. **窗口语义**：baseline 的 `discharge` 用 SINTEF 的**脱锂支**（推荐）还是锂化支？
4. **温度声明**：SINTEF 无温度列，记 25 ℃（目录声明 RT）是否接受？
5. **大文件策略**：`file_sha256` 全量哈希（慢但强）vs 头尾抽样哈希（快但弱）？

---

## 10. 不变量检查表（新代码必须遵守）

- [ ] `battery_sim/` 科学逻辑零改动；改动仅限 §8 的"可追加"项
- [ ] 回归门 ≥ 98 passed
- [ ] adapter 不 import pybamm
- [ ] 每个输出带 provenance（文件、单位换算、rate 归一化、符号约定）
- [ ] 参数一律标注 `effective` / `apparent`，不得称"材料本征参数"
- [ ] zero-fit 与参数辨识分阶段，辨识集/验证集分离
- [ ] 大文件流式读取，抽稀后入库；原始数据只读不写

---

# Phase A 执行记录（2026-09-10）

状态：**完成**。目标链路已跑通：`run_pipeline.py` 调用 SINTEF 石墨数据 → zero-fit SPM 仿真 → 输出。
`battery_sim/` 科学核心零改动（`registry.py` / `simulation/` / `evaluation/` /
`pybamm_factory.py` / `rates.py` 均未修改）。

## 落地内容

| 文件 | 说明 |
|---|---|
| `battery_sim/datasets/sintef_graphite.py` | **新增**：SintefGraphiteAdapter（流式读取 + 抽稀、规则化分支识别、逆 OCP 初始化、完整溯源） |
| `configs/datasets.yaml` | **追加** `sintef_graphite` 条目（半电池一等配置 + 温度声明 + 尺度警告 + rate 表） |
| `configs/chemistry.yaml` | **追加** `Graphite_LiMetal`（含槽位约定说明） |
| `external/pybamm-input-data/graphite_ocp_Ecker2015.csv` | **新增（vendored）**：PyBaMM 石墨 OCP 表，供逆 OCP 使用（BSD-3，README 记录来源与 sha256） |
| `tests/test_sintef_graphite.py` | **新增** 17 项测试（合成 parquet fixture，不依赖真实数据目录；2 项在真实数据存在时额外校验审计事实） |

## 关键实现决定（与计划的对应）

1. **槽位约定**：`Ecker2015_graphite_halfcell` 把石墨放在**正极槽位**（正极 OCP = 石墨，
   负极 OCP = 0 V + Li 金属动力学）。因此 `working_electrode: "positive"` 是 **PyBaMM 槽位**，
   物理工作电极另由 `physical_working_electrode: "graphite_negative"` 记录。
   （审计中修正了原计划里写 `negative` 的错误。）
2. **rate 表放在 adapter 内**：C/50 不在 `battery_sim/rates.py` 的 `CANONICAL_RATES` 中，
   而该文件冻结 → adapter 通过覆盖 `rate_info()` 自带 rate 表（`configs/datasets.yaml`
   的 `rates_meta`），未改任何现有文件。
3. **符号**：SINTEF 原始符号与平台一致（负 = 充电/锂化），因此**保留原始符号**，
   并在 provenance 中记录判定依据（负电流段驱动 3.0 V → 0.01 V = 锂化）。
4. **容量列**：文件内 `Cumulative Capacity / Ah` 为**逐步累积**（与梯形积分交叉校验，
   偏差 < 0.5%），直接使用并把两者都写入 provenance。
5. **温度**：文件无温度通道 → `ambient_temperature_source =
   declared_room_temperature_not_measured`（低于实测等级的显式标记）。
6. **文件校验**：全量 SHA256（用户决定），每次加载写入 provenance。
7. **内存**：两遍流式扫描（分类 → 取窗），`max_points` 抽稀，为 Phase B 的
   9100 万行 GITT 文件预留。

## 实测结果（zero-fit，未做任何拟合）

| 指标 | 值 |
|---|---|
| 窗口 | p-OCV cycle 1，静置段 tail(60 s) + 脱锂段（step 4） |
| 窗口时长 | 148 521 s ≈ 41.3 h |
| 实测支路电荷 | 1.785 mAh（容量列） vs 1.785 mAh（积分）✓ |
| rest OCV → x0 | 0.0824 V → x0 = 0.9640（逆 OCP） |
| RMSE(t) | **151.36 mV** |
| MAE(t) / bias(t) | 100.00 / −100.00 mV |
| coverage | 1.00 |
| Q_exp / Q_sim | 0.001785 / 0.001785 Ah（forced-current window） |

## 结果解读（必须随数字一起引用）

残差是**尺度伪影**，不是模型误差：

| 时间 | V_exp | V_sim | residual |
|---|---|---|---|
| 0 s | 0.0824 V | 0.0801 V | −2.3 mV |
| 末端 | 1.0000 V | 0.0785 V | −921.5 mV |

实验电极被完全脱锂（0.01 → 1.0 V），而参考参数集的电极面积是它的 **55.8 倍**、
面容量 **1.87 倍**，在**相同绝对电流**下模型看到的电流密度低 **~56 倍**，
因此模型几乎不脱锂、电压几乎不动（0.080 → 0.079 V）。

**禁止表述**："模型预测误差 151 mV" / "模型不适用石墨" / 任何 validation 措辞。
**允许表述**："Phase A 通路验证通过；该 RMSE 由参考参数集与目标电芯的尺度失配主导，
待 Phase C 生成几何匹配参数集后才有模型误差意义。"

## Phase A 未做（按用户范围）

- ❌ OCP / GITT 参数提取（Phase B）
- ❌ 参数集构建与几何匹配（Phase C）
- ❌ `parameter_summary.json` / `report.md` 产物（Phase D/E）
- ❌ DLR adapter（Phase D）

---

# Phase A.5 执行记录：geometry-aware zero-fit（2026-09-10）

目标：验证 Phase A 的"voltage frozen"是**纯尺度伪影**——用 SINTEF 实测电极几何替换参考
参数集的几何，**OCP / 扩散 / 动力学一律不动**，不拟合任何电压。

## 0. 先修了一个更根本的错误：符号约定

Phase A 的 adapter **保留了原始电流符号**，理由是"负电流=锂化=充电，与平台一致"。**这是错的**：

- cycler 约定（SINTEF 与 Birmingham 原始文件相同）：**负电流 = 放电**；
- 石墨‖Li 电池的**放电本身就是锂化**（Li 从锂金属溶出、插入石墨，V 从 ~3 V 降到 0.01 V）
  ——所以"负电流段驱动 3.0 V → 0.01 V"恰好证明它是**放电**，不是充电；
- 平台 canonical：**放电 = +** → 必须**翻转**原始符号（与 Birmingham adapter 一致）；
- 实测反证（本机 PyBaMM 探针）：石墨在正极槽位时，**正电流使 x 0.964→0.987（锂化）且
  V→0 V**；**负电流使 x→0.930（脱锂）且 V 上升**。

修正内容：
1. adapter **翻转符号**（`current_A = -raw`），`capacity_Ah` 改为对 canonical 电流积分；
2. provenance 重写：`raw = negative current = DISCHARGE`、`action = raw sign FLIPPED to canonical`、
   附 PyBaMM 方向探针结论；
3. **两个分支都暴露为 rate**（rule-based 识别，不猜 step 号）：
   - `pOCV-deli` 脱锂支（0.01→1.0 V）= 用户指定的主窗口；在平台约定下这是**充电方向**窗口
     （负电流）→ runner 面向放电的列（`Q_sim` / `capacity_error_pct` /
     `current_peak_discharge_A`）对它没有意义，V(t) 类指标有效；
   - `pOCV-lith` 锂化支（3.0→0.01 V）= 电池自身的**放电方向**，约定干净，作交叉校验；
4. 温度/单位不变；`x0` 规则增加**表边界回退**（新鲜态 rest OCV 2.97 V 高于参考 OCP 表顶
   1.4325 V 时，取表的脱锂边界并标注 `ocp_table_edge_fallback`）。

## 1. 几何覆盖（parameters/sintef_graphite_geometry.py）

| 参数 | 参考集 | A.5（由实测推导） |
|---|---|---|
| 电极面积 | 85.85 cm² | **1.5391 cm²**（14 mm 圆片） |
| 正极厚度 | 74 µm | **64 µm** |
| 活性物质体积分数 ε_am | 0.372403 | **0.2612** |
| 标称容量 | 156.25 mAh | **2.2017 mAh** |

推导（全部写入 `geometry_override.json`）：
- 面积 = π(d/2)²，d = **14 mm**（目录列名写 cm，实为 mm——**单位陷阱**，Phase A 的
  provenance 里曾因此算出 153.9 cm²，本次一并修正）
- 宽/高：保持参考电极长宽比（0.101/0.085）→ 只改尺度
- ε_am 主路线 = m_AM /(ρ_石墨 × 厚度 × 面积)，ρ_石墨 = 2260 kg/m³（与参考集自洽性交叉验证：
  31920 mol/m³ ↔ 372 mAh/g）；另两条交叉路线（载量列、面容量+c_max）一并报告，
  差异与**目录内部约 10% 不一致**（(涂层质量/载量) 与圆片面积不符）都写入 JSON，不静默修正
- 孔隙率、粒径：目录未测 → **保留参考值并显式标注**
- 容量 = 面积 × 厚度 × ε_am × c_max × F/3600

注入方式（**不改任何仓库文件**）：PyBaMM 的 `parameter_sets` 是惰性 EntryPoint 映射，
不可赋值 → 用一个**只读视图**对象替换模块属性，其中托管我们的派生集；
随后 `run_baseline_cell(..., parameter_set="sintef_graphite_geometry_v1")` 走**未修改的公共 runner**。

## 2. 结果（zero-fit，无任何拟合）

| 窗口 | 几何 | RMSE(t) | V_sim 跨度 | 冻结伪影 |
|---|---|---|---|---|
| `pOCV-deli`（脱锂） | 参考几何 | 150.06 mV | 1.6 mV | **PRESENT** |
| `pOCV-deli`（脱锂） | **实测几何** | **109.12 mV** | 116 mV | PARTIAL |
| `pOCV-lith`（锂化=放电） | 参考几何 | 875.75 mV | 620 mV | PARTIAL |
| `pOCV-lith`（锂化=放电） | **实测几何** | **81.39 mV** | 1289 mV | PARTIAL |

**结论：尺度修正确实消除了"voltage frozen"伪影**——放电方向窗口从 876 mV 降到 81 mV
（10.8×），模型电压跨度从 620 mV 增至 1289 mV；脱锂窗口从 150 mV 降到 109 mV。

## 3. 剩余残差不是尺度（Phase B 的动机）

| 现象 | 归因 |
|---|---|
| 锂化窗口：V_sim 起点 1.372 V vs 实验 3.016 V | **参考石墨 OCP 表最高只到 1.4325 V**，新鲜态（~3 V）落在表的有效范围之外 |
| 脱锂窗口：V_sim 终点 0.196 V vs 实验 1.000 V | 模型容量 2.20 mAh、支路电荷 1.785 mAh → Δx≈0.81，x 只走到 ~0.15；参考 OCP 要到 x≈0.004 才到 1.0 V → **OCP 形状/容量差异** |
| 两部分残差 | 均指向**OCP 曲线本身**，而非尺度 → **Phase B（从 p-OCV 提取实测 OCP、双支）** 的直接依据 |

## 4. 措辞（强制）

geometry-aware **zero-fit reference replay**：几何来自实测，OCP/扩散/动力学来自公开参考集，
**未对任何电压做拟合**，结果**不是**对该石墨的模型验证。剩余残差是 Phase B 的**假设**，
不是结论。禁止写"模型误差 81 mV"。

## 5. Phase A.5 未做（按范围）

- ❌ OCP / GITT 提取（Phase B）
- ❌ 全电池、DLR adapter（Phase D）
- ❌ 参数拟合（须独立立项 + 锁文件）

---

# Phase B0 执行记录：experiment-derived graphite OCP（2026-09-10）

目标：从 SINTEF p-OCV 提取**双支 OCP**，替换参考集的石墨 OCP（几何沿用 A.5，
扩散/动力学**不动**），验证 A.5 提出的两个残差来源：**OCP 范围不足** 与 **OCP 形状差异**。
本阶段**不做 GITT**。

## 1. 新增模块

| 文件 | 说明 |
|---|---|
| `extraction/ocp_extractor.py` | 纯 pandas：从 canonical p-OCV 记录提取双支 OCP；SOC 锚点 = 该循环**锂化支的电荷** Q_ref；输出 `SOC, Voltage, branch`（+ time_s/current_A/capacity_Ah 追溯列）与 provenance JSON |
| `parameters/sintef_graphite_ocp.py` | 派生参数集：参考集 + A.5 几何 + **实测 OCP**（三个变体：lith / deli / mean）；扩散/动力学/c_max/孔隙率/粒径全部保持不变（按对象同一性验证） |
| `scripts/graphite_phase_b0_compare.py` | 提取 → 注册 → 7 次零拟合回放（2 窗口 × 对照/变体）→ 残差分布与分区分析 |

`extraction/` 与 `parameters/` 均为**顶层新包**，`battery_sim/` 除 adapter 的既有 bug 修复外无改动。

## 2. 提取出的 OCP（cycle 1）

| 项 | 值 |
|---|---|
| Q_ref（锂化支电荷，SOC 锚点） | **1.9425 mAh** |
| 锂化支 | SOC 0 → 1，V **3.0003 → 0.00999 V**，1707 点 |
| 脱锂支 | SOC 1 → 0.0812，V **0.0967 → 1.0000 V**，1568 点 |
| 同 SOC 迟滞 | SOC 0.20: **134.8 mV**、0.50: **85.8 mV**、0.80: **64.7 mV**（均值 115.3 mV） |
| 交接间隙（非迟滞） | 86.7 mV（脱锂起点 − 锂化终点，含截止过冲与开电流极化） |
| C/50 极化估计（记录不施加） | 14.3 mV |

措辞：这是**实验导出的伪 OCP（pseudo-OCP）**——C/50 恒流 + 仅端点静置，曲线含
C/50 极化，因此拿它当模型 OCP 会**重复计入**该极化，残差是**保守（偏悲观）**估计。
**不是**材料常数，**不是**验证。

## 3. 对比结果（零拟合；几何固定在 A.5 实测值，只变 OCP）

| 窗口 | OCP | RMSE [mV] | MAE [mV] | bias [mV] | V_sim 跨度 |
|---|---|---|---|---|---|
| lith | Phase A（参考几何＋参考 OCP） | 875.75 | 867.93 | +866.28 | 620 mV |
| lith | **A5 对照**（实测几何＋参考 OCP） | **81.39** | 67.81 | +66.16 | 1289 mV |
| lith | **实测锂化支 OCP** | **45.05** | **7.75** | +4.95 | 1038 mV |
| deli | Phase A | 150.06 | 98.63 | −98.63 | 1.1 mV |
| deli | **A5 对照** | **109.12** | 61.86 | −61.86 | 116 mV |
| deli | **实测脱锂支 OCP** | **91.86** | **31.19** | −30.87 | 128 mV |
| deli | 双支平均 OCP | 397.42 | 144.10 | +114.06 | 2973 mV |

分区 MAE（按实验电压）：

| 区域 | lith 对照 → lith 实测 OCP | deli 对照 → deli 实测 OCP |
|---|---|---|
| V ≤ 0.15 V | 61.8 → **5.3** | 31.2 → **2.3** |
| 0.15–0.60 V | 105.8 → **17.8** | 79.5 → **46.9** |
| 0.60–1.43 V | 232.5 → **48.4** | 560.1 → **519.1** |
| V > 1.43 V（参考表无数据） | 1643.9 → 1936.5 | — |

## 4. 两个假设的裁决

**H1（OCP 范围不足）—— 成立 ✅**
- 放电方向窗口 81.4 → **45.1 mV**（×0.55）；MAE 67.8 → **7.75 mV**
- 低压区（≤0.15 V）61.8 → **5.3 mV**，中压区 105.8 → **17.8 mV**
- 即：把参考表覆盖不到的新鲜态（~3 V）纳入后，主体残差基本消失
- 唯一变差的区域：V > 1.43 V（1644 → 1937 mV）——这是新鲜态**近乎垂直**的稀释段，
  实测曲线在 ~0.06% SOC 内从 3.0 掉到 1.2 V，表分辨率不足导致少数点偏差极大
  （MAE 仅 7.75 mV、RMSE 45 mV，说明少数点主导 RMSE）→ **表格分辨率/采样问题，不是物理缺口**

**H2（OCP 形状差异）—— 部分成立 ⚠️**
- 脱锂窗口 109.1 → **91.9 mV**（×0.84），MAE 61.9 → **31.2 mV**
- 低压区 31.2 → **2.3 mV** ✓、中压区 79.5 → **46.9 mV** ✓
- **但高压端（0.6–1.43 V）仍为 519 mV** ✗ → 未解决
- 诊断：模型电极容量（几何导出 **2.20 mAh**）比实测支路电荷 **Q_ref = 1.94 mAh 高 13%**，
  同样时间下模型的 SOC 高于实验，因此电压偏低、无法走到 1.0 V。
  **这是容量/ε_am 一致性问题，不是 OCP 形状问题** → 下一步（B0.5/C）：
  用**实测 Q_ref** 反推 ε_am（直接测量量，非拟合），或把 c_max 与 Q_ref 对齐

**附加发现（双支平均不可用）**：mean OCP 变差到 397 mV —— 说明石墨两支的差异是**形状**
差异而非单纯偏移，**简单平均无效**，必须分支配对使用。

## 5. 过程中修掉的三个平台级问题

1. **抽稀丢端点**：`_read_window` 原用全局偏移抽稀，丢掉了新鲜态锂化支的**首个样本**
   （3.0 V = SOC 0 锚点），SOC 轴随之漂移 → 改为**按 (cycle, step) 分配预算 + 强制保留首末行**
   （`decimation` 字段记录该规则）。
2. **`load_raw` 未翻转符号**：OCP 提取依赖 canonical 符号（+ = 放电 = 锂化），已在
   `load_raw` 中统一翻转并写入 `attrs["sign_convention"]`。
3. **电压窗口必须来自实测**：参考集自带 Ecker 的 0–1.5 V 窗口，模型在 t=0 就触发
   "Maximum voltage" 事件（`SolverError`）→ 派生变体改用实测窗口 0.005 / 3.2 V，
   并在 `voltage_window_override` 记录理由；同时 x0 加 **1e-3 最小锂含量下限**
   （c=0 会使 j0→0、初始电压发散）。

## 6. 措辞（强制）

- OCP = **experiment-derived pseudo-OCP**；扩散/动力学仍是公开参考值
- 剩余高压端残差是 **Phase B1（GITT）或容量一致性** 的**假设**，不是结论
- 禁止写"模型误差 45 mV"或任何 validation 措辞

## 7. Phase B0 未做（按范围）

- ❌ GITT / D_s 提取（Phase B1）
- ❌ 容量一致化（用 Q_ref 反推 ε_am）—— 已定位为下一步
- ❌ 全电池、DLR adapter（Phase D）

---

# Phase B0.5 执行记录：容量一致化（2026-09-10）

目标：**容量一致化，而不是进一步拟合**。验证 B0 剩余误差（模型容量 2.2017 mAh vs 实测
参考电荷 1.9425 mAh）是否由**容量映射**导致，特别是 `0.60–1.43 V` 区间的残差。
本阶段**不做 GITT**。

## 1. 为什么容量会进入 OCP 对比（这一步是必须的，不是修饰）

B0 提取的 OCP 表横轴是**基于电荷的 SOC**：

```
Q_ref    = cycle 1 锂化支的电荷（新鲜态→下截止）= 1.9425 mAh   ← 实测
SOC_lith = Q / Q_ref
SOC_deli = 1 - |Q| / Q_ref
```

这张表只有在**模型自身的化学计量数 x 与 SOC 同义**时才能当作 `OCP(x)` 使用，即要求

```
Q_model = eps_am * L * A * c_max * F / 3600  ==  Q_ref
```

A.5 几何给出的 `Q_model = 2.201658 mAh`，**比 Q_ref 高 13.34%** → 模型的 x 比表 SOC **慢 1.13×**
→ 本应走到 `x = 0.08` 的脱锂支只走到 `x = 0.19`（V 停在 0.24 V 而非实测的 1.0 V）。
**这就是 B0 在 0.60–1.43 V 区间留下 519 mV 的原因。**

### 容量公式已实测标定（scripts/probe_b05_capacity.py）

| 量 | 值 |
|---|---|
| 几何公式 Q = eps_am·L·A·c_max·F/3600 | **2.2017 mAh** |
| 恒流 SPM 实测 d(x_体平均)/dt（1 h） | **2.2017 mAh（差 0.00%）** |
| 同一次求解的 d(x_表面)/dt | 1.7382 mAh（**−21%**） |

→ 容量必须取**体平均**锂含量；表面浓度因扩散未平衡（τ_diff ≈ R²/D ≈ 1.9e6 s ≫ 1 h）而领先，
不能用来定容量（它可以单独作为诊断量，B0.5 报告里保留了）。

## 2. 覆盖内容（parameters/sintef_graphite_capacity.py，新增）

| 项 | 变化 |
|---|---|
| `Positive electrode active material volume fraction` (ε_am) | **0.261218 → 0.230465**（×0.882274） |
| `Nominal cell capacity [A.h]` | 2.201658 → 1.942466 mAh（**仅记账**：测试断言只改该键不改变仿真电压） |
| OCP / 扩散 / 交换电流密度 / c_max / 孔隙率 / 粒径 / 电压窗口 | **对象同一性未变**（测试逐键 `is` 校验） |

- 目标值 `Q_target` **从 B0 提取的 provenance 文件读取**（实测电荷），不在代码里手抄数字；
- 等价活性物质载量一并报告（供极片工艺记录）：3.4362 mg/cm² → 3.0317 mg/cm²；
- 电极体积平衡 Σ=ε_am+孔隙率 0.5902 → 0.5595，仍 < 1（参考集未声明非活性体积分数）；
- 注入方式同 A.5：`pybamm.parameter_sets` 只读视图运行时注册，**公共 runner 零改动**。

## 3. 结果（零拟合；几何固定为 A.5 实测值）

三档对照：`A5_geom_only`（Ecker OCP）→ `B0_ocp`（实测 OCP）→ `B0p5_capmatch`（+容量一致化）。

| 窗口 | 变体 | Q_model [mAh] | RMSE [mV] | MAE [mV] | bias [mV] |
|---|---|---|---|---|---|
| lith | A5_geom_only | 2.202 | 81.39 | 67.81 | +66.16 |
| lith | B0_ocp | 2.202 | 45.05 | 7.75 | +4.95 |
| lith | **B0p5_capmatch** | **1.942** | **44.64** | **3.20** | −3.20 |
| deli | A5_geom_only | 2.202 | 109.12 | 61.86 | −61.86 |
| deli | B0_ocp | 2.202 | 91.86 | 31.19 | −30.87 |
| deli | **B0p5_capmatch** | **1.942** | **6.27** | **2.65** | +2.65 |

分区 MAE（按实验电压）：

| 区域 | lith: B0 → B0.5 | deli: B0 → B0.5 |
|---|---|---|
| V ≤ 0.15 V | 5.3 → **1.3** | 2.3 → **1.3** |
| 0.15–0.60 V | 17.8 → **5.8** | 46.9 → **2.9** |
| **0.60–1.43 V** | 48.4 → 63.3 ⚠️ | **519.1 → 35.8** ✅ |
| V > 1.43 V（抽稀陷阱，见 §4） | 1936.5 → 1936.5 | — |

## 4. SOC 轨迹（本阶段的核心证据）

| 窗口 | 变体 | x 起 | x 终（体平均） | x 终（表面） | 实验 SOC 终 | 末端错位 |
|---|---|---|---|---|---|---|
| lith | A5_geom_only | 0.0015 | 0.8836 | 0.8912 | 1.0000 | **−0.1164** |
| lith | B0_ocp | 0.0010 | 0.8831 | 0.8907 | 1.0000 | **−0.1169** |
| lith | **B0p5_capmatch** | 0.0010 | **0.9898** | 0.9984 | 0.9890 | **+0.0008** |
| deli | A5_geom_only | 0.9582 | 0.1474 | 0.1470 | 0.0812 | **+0.0662** |
| deli | B0_ocp | 0.9990 | 0.1882 | 0.1876 | 0.0812 | **+0.1070** |
| deli | **B0p5_capmatch** | 0.9990 | **0.0800** | 0.0798 | 0.0812 | **−0.0012** |

即：容量一致化把模型的 x 与实测电荷 SOC 的**末端错位从 0.107–0.117 压到 ≤0.0012**（<0.15% SOC）。
注意 A.5/B0 的脱锂支末端 x 反而**高于**实验（0.147/0.188 vs 0.081）——这就是"走不到 1.0 V"的直接原因。

## 5. 裁决

- **H2 未解部分（0.60–1.43 V，deli 窗口）——成立 ✅**：519.1 → **35.8 mV**（×0.069），
  整窗 RMSE 91.86 → **6.27 mV**（×0.068）、MAE → 2.65 mV；末端电压 0.237 → **1.060 V**（实验 1.000 V）。
  **确认：B0 在该区间的残差由容量映射（ε_am ↔ Q_ref 不一致）导致，不是 OCP 形状问题。**
- **lith 窗口**：整窗 MAE 7.75 → **3.20 mV**（×0.41）、SOC 错位 0.117 → 0.0008，但
  `0.60–1.43 V` 切片 48.4 → 63.3 mV **变差**——该切片是**新鲜态近垂直稀释段**，
  下条给出根因；覆盖率 0.989（模型在实测窗口结束前 1.1% 触及 0.005 V 下截止，因表面 x 领先体平均）。
- 措辞：**capacity-consistent ≠ fitted**；Q_ref 是实测电荷；仍是 zero-fit 参考复现，**不是验证**。

## 6. 顺带确证的一个抽稀陷阱（本轮最有价值的工程发现）

`0.60–1.43 V` 切片（lith 窗口）**不是**物理缺口，是**抽稀伪影**：

| 证据（scripts/probe_b05_dilute_resolution.py） | 值 |
|---|---|
| p-OCV 原始文件 | 189 340 行，采样 **10 s** |
| `adapter.load_raw` 抽稀 | **全局 stride = 10**（`DEFAULT_MAX_POINTS = 20 000`）→ 100 s/点 |
| 锂化支前 300 s 的原始样本 | **31 个**（V：3.000 → 1.786 → 1.621 → … → 0.885 V） |
| 抽稀后同区间存活 | **4 个**（t = 0, 90, 190, 280 s） |

→ 提取出的 OCP 表在 `3.0003 V → 1.2349 V` 之间**只有 1 个样本**，模型在该段的电压实际上是
跨越 1.77 V 间隔的线性内插 → `V > 1.43 V` 区间的 ~1937 mV 是**插值伪影**。

**建议（后续 extraction 精修，本阶段刻意不做，以免破坏 B0 对照的有效性）**：
OCP 提取前对分支起始段保留全分辨率（或对 `load_raw` 用分段预算而非全局 stride）。
这属于 Phase B0 extraction refinement，不属于 B0.5。

## 7. Phase B0.5 未做（按范围）

- ❌ GITT / D_s（Phase B1）
- ❌ OCP 表重提取（上述稀释段精修）——刻意留作独立步骤
- ❌ 全电池、DLR adapter（Phase D）

回归门 **160 passed**（144 + 16 新增容量模块测试）；commit 见 git log。

---

# Phase B0.6 执行记录：高保真 OCP 提取（v1 vs v2）· 2026-09-10

目标：修复 p-OCV 提取中**高压稀释段采样不足**的问题，产出一个可冻结的高质量 OCP。
**不改** PyBaMM 模型 / geometry correction / capacity correction / SOC 定义；不做 GITT。
v1 输出**原样保留**，v2 写入独立目录 `graphite_ocp_v2/`。

## 1. 缺陷（B0.5 已量化，本轮定位到根因）

| 环节 | 事实 |
|---|---|
| p-OCV 原始文件 | **189 340 行 / 10 s** 采样 |
| v1 的输入 | `adapter.load_raw` 全局 stride = 10 → **100 s/点** |
| 结果 | 锂化支 >1.4325 V **只剩 1 个样本**（原始数据该区间只有 **5 个**） |
| 后果 | v1 表在 `3.0003 → 1.2349 V` 之间只有 1 个样本 → **插值伪影** |

## 2. 修复（新增模块，全部 additive）

| 文件 | 作用 |
|---|---|
| `extraction/hires_trace.py` | **全分辨率**读取器：按 `configs/datasets.yaml` 的 `raw_dir`/`raw_file_template`/`programme` 解析文件，零抽稀，符号翻转到 canonical，并用**文件名 + SHA256 与 adapter 自身 provenance 交叉校验** |
| `extraction/ocp_extractor_v2.py` | branch-aware 采样 + v1 提取核心复用 + v1/v2 对比指标 |
| `scripts/graphite_phase_b06_compare.py` | 提取 → 注册两套参数集 → 双×双回放 → 报告与图 |
| `scripts/probe_b06_sampling.py` | 采样参数扫描（保真度/点数权衡） |
| `tests/test_hires_ocp.py` | 19 项测试（合成 parquet + stub adapter，不依赖 13 GB 数据） |

**branch-aware 采样规则**（三档，全部可覆盖、全部记录）：
1. **保真**：在 (SOC, V) 平面做**垂直距离 RDP**——保留"分段线性重建（正是 PyBaMM OCP Interpolant 的行为）
   与全分辨率曲线偏差 ≤ ε"的最小样本集；**首末点强制保留**；ε 阶梯（0.2 mV 起）保证点数上限。
2. **陡峭度下限**：|dV/dSOC| > 5 V/unit 的区间至少保留 12 个原始样本（同时保护将来对它求导的用途，
   如 GITT 的 dOCP/dSOC）。
3. **平台间距上限**：任何保留区间跨度 ≤ 0.005 SOC。

**实测标定**（scripts/probe_b06_sampling.py 扫描）：ε=0.2 mV / gap=0.005 / steep≥12 →
锂化支 16 160 → **933 点**、脱锂支 14 848 → **638 点**，**实测最大误差 0.199 / 0.192 mV**。

## 3. v1 vs v2（表层级，要求 3 的答案）

| 分支 | 版本 | 点数 | SOC 0–0.01 | 0.01–0.10 | 0.10–0.50 | 0.50–1.00 | **对实测曲线最大误差** |
|---|---|---|---|---|---|---|---|
| 锂化 | v1 | 1707 | **18** | 153 | 682 | 854 | **751.1 mV** |
| 锂化 | **v2** | **933** | **152** | 582 | 88 | 111 | **0.161 mV** |
| 脱锂 | v1 | 1568 | 0 | 33 | 682 | 853 | **5.83 mV** |
| 脱锂 | **v2** | **638** | 0 | 262 | 256 | 120 | **0.181 mV** |

按 SOC 分区的 v1 保真度（对实测曲线的最大偏差）：
锂化 `0–0.01` **1017.3 mV** / `0.01–0.10` 6.31 mV / `0.10–0.50` 0.09 mV / `0.50–1.00` 0.08 mV；
脱锂 `0.01–0.10` 0.17 mV / `0.10–0.50` 0.11 mV / **`0.50–1.00` 7.12 mV**。
→ v2 在两支、所有分区都把误差压到 **≤0.2 mV**。

v1 vs v2 的电压偏差：锂化 全域 max **751.1 mV**（均值 0.274）、SOC 0–0.1 密集网格 max **1011.1 mV**（峰值出现在
**SOC 7.5e-5**）；脱锂全域 max 5.83 mV。**注意：v1 的"1 709 点"里 682+854 点铺在平坦平台（冗余），
而最需要分辨率的地方只有 18 点——v2 点数少 45% 却严格更好，因为它把预算从平台搬到了陡峭段。**

## 4. 回放对比（B0.5_v1 vs B0.5_v2；容量一致化、几何固定，仅 OCP 表不同）

| 窗口 | 版本 | RMSE [mV] | MAE [mV] | bias [mV] | **沿模型 x 轨迹的表误差 mean / max [mV]** |
|---|---|---|---|---|---|
| lith | v1 | 44.64 | 3.20 | −3.20 | 0.041 / **8.161** |
| lith | **v2** | **44.74** | 3.21 | −3.21 | 0.016 / **0.160** |
| deli | v1 | 6.27 | 2.65 | +2.65 | 0.012 / 0.162 |
| deli | **v2** | **6.31** | 2.65 | +2.65 | 0.017 / 0.177 |

分区 MAE（mV）：lith `≤0.15 V` 1.27→1.27、`0.15–0.60` 5.83→5.81、`0.60–1.43`（18 点）63.32→64.19、
`>1.43`（**仅 1 点**）1936.47→1939.18；deli `≤0.15` 1.30→1.30、`0.15–0.60` 2.89→2.89、
`0.60–1.43`（40 点）35.80→35.99、`>1.43` **0 点**。

**结论（本轮最重要的判断）**：
- 表本身**确实修好了**：沿模型自身轨迹的表误差 **8.16 → 0.16 mV（↓51×）**；
- 但**回放指标几乎不动**（±0.1 mV）——因为模型的表面化学计量数从 `x₀ = 1.0e-3` 起步，
  **从不进入 v1 表被破坏最严重的 `SOC < 1e-3` 区间**（那里 v1 偏差可达 1017 mV）。
  换句话说：v1 的缺陷真实存在，但它的作用域**恰好落在模型轨迹之外**。
- 因此 B0.5 遗留的 lith 残差**不是表驱动的**：`V_exp > 1.43 V` 那一栏的 1936 mV 是 **1 个比较点**的统计量，
  由**初始状态**决定——实测首点 3.016 V，而模型因 `x₀ ≥ 1e-3` 的数值下限只能从 1.08 V 起步
  （参考石墨 OCP 在 `x = 1e-3` 处本来就只有 ~1.08 V）。**这是初始态问题，不是 OCP 表问题。**
- B0.6 的交付因此是"**冻结一个可信的 OCP**"：v2 表在全 SOC 范围内与实测曲线
  **偏差 ≤0.2 mV**，这是后续 GITT（需要 dOCP/dSOC）与任何再参数化工作的正确基础。

## 5. 措辞（强制）

v2 = **experiment-derived pseudo-OCP**（本电极、本温度下的准平衡响应），重采样自全分辨率实测；
**不是材料常数、不是拟合曲线、不是 validation**。回放仍是 zero-fit。
沿轨迹的表误差 ≠ 回放残差；**回放没变好不等于表没修好**，也不等于"采样不重要"。

## 6. Phase B0.6 未做（按范围）

- ❌ GITT / D_s（Phase B1）
- ❌ 任何 PyBaMM 模型 / 几何 / 容量改动
- ❌ **初始态修正**（`x₀ ≥ 1e-3` 下限导致的"新鲜态无法表达"）——已定位，属独立一步，需用户批准

回归门 **179 passed**（160 + 19）；commit 见 git log。

---

# Phase B1 执行记录：GITT → apparent D_s(SOC) · 2026-09-10

目标：从 SINTEF graphite R2032 的 GITT 数据提取 **apparent/effective 固相扩散系数 D_s(SOC)**
（**禁称** intrinsic diffusion coefficient），建立"Ecker2015 + SINTEF OCP + SINTEF D_s"派生参数集，
在 p-OCV 回放里与 Ecker 的 D 对比。全部 additive；`battery_sim/` 未改。

## 1. B1.0 分段：文件是多速率日志，不是一张平表（本阶段最关键的发现）

SINTEF "intelligent cell" 把**多个通道以不同采样率交错写在同一个文件里**，只靠
(Cycle Count, Step Index) 区分。实测（cell 063b77，programme `gitt`，**90 957 884 行**）：

| step | 内容 | 采样 | 证据 |
|---|---|---|---|
| 4 | **锂化脉冲串** | **1 s** | I = −44.1545 µA（std 0.0005 µA），103 个脉冲 |
| 10 | **脱锂脉冲串** | 1 s | I = +44.155 µA，95–96 个脉冲 |
| 2 | 静止段 | 100 Hz burst | I = 0，dt = 0.01 s |
| 3 | 静止段 | 10 s | I = 0 |
| 8/9 | 脱锂半程的对应通道 | 同上 | — |

**两个必须处理的后果**：
1. **step 的 t_min..t_max 不覆盖其全部行**。step 4 跨 309 h 但只有约 52 h 真的通电，脉冲之间的
   **9000 s 静置由其他通道记录**。因此对 step 4 单独做梯形积分会把静置也当成通电：
   **错误结果 9.8 mAh（4.5× 电芯容量）vs 正确 2.29 mAh**。脉冲/静置的切分必须来自**日志间隙**
   （dt > max(5×该通道平均 dt, 1.5 s)）。
2. 松弛电压只在静止通道上，必须**按"静置窗口"配对**——窗口边界是**任意通道上的下一个脉冲起点**
   （只按同一 step 划界会让某支的最后一个脉冲误吞下一支的静置，表现为"负松弛"）。

分段结果：**981 个脉冲**（锂化 502 / 脱锂 479），脉冲 **1799.98 s**、静置 **9000 s**、
每循环 Q_ref = **2.2926 / 2.1835 / 2.1961 / 2.1975 / 2.1813 mAh**（容量衰减 4.9%）、
SOC ∈ [0,1]、ΔV_pulse 与 ΔV_relax 反号（物理正确）、√t 拟合 R² 中位数 0.93。

## 2. B1.1 方程与实现

**Weppner & Huggins (1977)**，与 **PyBOP 26.3 `models/lithium_ion/weppner_huggins.py` 的前向关系逐字一致**
（已读源码核对）：

```
V(t) = U + U' · (2I / (3 Q_th)) · sqrt(t · tau_d / pi)
Q_th = F · eps_am · c_max · L · A   [A·s]        （PyBOP create_grouped_parameters）
tau_d = R^2 / D
```
反演：`tau_d = pi·(3 Q_th m / (2 I U'))²`，`m` 由脉冲上的 `V = a + m√t` 最小二乘得到（跳过前 60 s 的 IR）。
- `U'` 取**冻结的 B0.6 v2 OCP 表**的局部斜率（窗口 ≈1.5 个脉冲成分步长，**禁止外插出表范围**）；
- `Q_th` 取 **GITT 电芯自身**的几何（2.2464 mAh），不是参考集的；
- **OCP-free 交叉校验**：消去 U' 得 `D = (4/(9π))·(R²/τ)·(ΔE_τ/ΔE_s)²`。

**两个被测试抓出来的真 bug**（都已修）：
1. **单位**：W-H 关系里 Q_th 必须是 **A·s**（PyBOP 用库仑），最初传了 Ah → τ_d 差 3600²、D 差 ~1e7。
   前向模型测试（已知 D 反演）把它钉住了。修正后 D 落在 **1e-16~1e-13 m²/s**，物理量级合理。
2. **松弛窗口**见 §1 第 2 点。

## 3. 结果：D_s 提取出来了，但**没有通过一致性检查**

- 981 个脉冲中 D_s 可算 958，**接受 616**（拒绝：√t R²<0.90、OCP 在该窗口不局部线性、
  SOC 超出该支 OCP 表范围、方向与 I·U′ 矛盾）。
- 接受脉冲 D_s 分位：p01 **2.9e-18** / p50 **3.8e-16** / p99 **2.7e-13** m²/s。
- 参考集 Ecker2015 的 D：SOC 0.05→0.95 为 5.3e-13→9.0e-15，**中位数 1.22e-14 m²/s**。
  → GITT 提取值**比参考小约 30×**，且跨 SOC 散布达 5 个数量级。

**p-OCV 回放对比（几何/容量/OCP 完全相同，只换 D）**：

| 窗口 | Ecker D | SINTEF D_s | 变化 | 备注 |
|---|---|---|---|---|
| lith | 44.74 mV | **68.57 mV** | **+23.82** | 比较窗 1978→932 点 |
| deli | 6.31 mV | **373.96 mV** | **+367.65** | 模型撞到 3.2 V 上限、V_sim→3.107 V |

**裁决：两个窗口都变差**，deli 窗口模型因扩散受限而耗尽表面、冲上截止电压。
一阶 W-H 表面偏移量估计（Ecker vs GITT）：lith 10.75 → **98.94 mV**、deli 20.35 → **77.73 mV**，
即提取出的 D_s 预言了一个实测 C/50 p-OCV **并不存在**的极化。
→ **该 D_s 不采纳为模型的扩散系数**；派生参数集 `sintef_graphite_dsapp_*` 保留为**诊断变体**。

**这不代表**：① 参考 Ecker D 就是对的（它是为另一款电芯发表的拟合值，本文也从未验证）；
② 提取代码有问题——前向模型测试证明反演能精确还原已知 D。它说明的是
**单颗粒模型是这份数据的错误透镜**：多孔电极、电解液与伪 OCP 自身的极化都被算进了"固相扩散"里。
这正是所有 GITT "apparent" 扩散系数的固有局限。

## 4. 措辞（强制）

**apparent / effective solid diffusivity**，不是材料本征常数、不是 validation；D ∝ R²（R 来自参考集，
非本材料实测），且 D(T) 完全未表征（GITT 只在声明的室温下做）。

## 5. Phase B1 未做

- ❌ 多孔电极/电解质修正（只有修正后才可能把表观值变成可用的模型参数）
- ❌ 温度依赖、不同脉冲时长的敏感性扫描
- ❌ 全电池、DLR adapter（Phase D）

回归门 **193 passed**（179 + 14）；commit 见 git log。

---

# Phase B2 执行记录：GITT apparent D_s 可信度评估 · 2026-09-10

目标：**不做拟合、不改 D**，回答"GITT 派生的 apparent D_s 什么时候可以当模型输入"。
产出三件事：① 逐脉冲诊断 + 有效性标志；② 常数 D 敏感性（1e-17…1e-13，pOCV/0.5C/1C/2C，SPM/SPMe）；
③ 判据（Fo 数）。`battery_sim/` 科学核心未改。

## 0. 数据能支持什么（先说清）

本电芯只有 **p-OCV**（≈C/50，41 h）与 **GITT** 两个程序，**没有任何倍率数据**。因此：
p-OCV 回放列有真实验、可比 RMSE；**0.5C / 1C / 2C 三列是纯模型前向仿真**，只能界定"D 何时重要"，
不能证明模型复现了任何实测倍率结果。

## 1. 新增模块

| 文件 | 说明 |
|---|---|
| `extraction/ds_diagnostics.py` | 把 B1 的逐脉冲表投影为**七字段诊断表**（SOC / Ds_app / WH_fit_R2 / dE_pulse / dE_relax / OCP_slope / validity_flag）+ 拒绝原因码 + 每 SOC 汇整；阈值**从 `gitt_diffusivity.py` 导入**，诊断与提取不可能对门限产生分歧 |
| `parameters/sintef_graphite_ds_sweep.py` | 常数 D 敏感性格点（**只替换扩散键**，其余按对象同一性不变；`changed_keys_against(reference, pv) == [KEY_DIFFUSIVITY]` 由测试断言）。**不读取也不修改 B1 的 D_s(SOC) 表** |
| `scripts/graphite_phase_b2_sensitivity.py` | 诊断 → 注册 → pOCV 回放 × CC 族 × 2 模型 → 判据图与 `report.md` |
| `scripts/probe_b2_registry.py` | **set-id 完整性守卫**（见 §5） |
| `tests/test_ds_diagnostics.py` | 26 项（合成脉冲表 + 合成 B0 期提取产物，不依赖 13 GB 数据） |

## 2. 诊断结果（B2.1）

**616 / 981 脉冲通过**全部门（62.8%）。拒绝集中在该方法本身失效的地方，不是随机散布：

| 原因码 | 脉冲数 |
|---|---|
| `r2_below_threshold`（V 对 √t 不线性） | 258 |
| `ocp_not_locally_linear`（脉冲跨越的 OCP 段不局部线性） | 63 |
| `direction_inconsistent` | 45 |
| `ocp_slope_unavailable`（SOC 落在该支 OCP 表外） | 23 |
| `undefined` | 23 |

**支持反演的 SOC 区间**（该区间内 ≥50% 脉冲通过）：
- 锂化：SOC 0.06–0.26、0.46–0.54、0.64–1.00
- 脱锂：SOC 0.16–0.42、0.56–0.80、0.98–1.00

**失败区间有明确的物理原因**：① **稀释段**（近 SOC 0 及其镜像端）——OCP 近乎垂直，脉冲不再是
小扰动，且冻结表本身的分辨率被逼近极限；② **平台区**——OCP 平坦（U′→0），脉冲几乎不产生扩散过电位，
√t 回归在拟合噪声。

每个 SOC 箱内**存活值的 log10 跨度**：中位 0.43 十年、最大 2.85 十年
→ **曲线的 5 个数量级主要是"阶段之间的 SOC 结构"，不是同一阶段内的散布**。

## 3. 敏感性结果（B2.2）

### 3.1 p-OCV 回放（唯一有实验的一列）

| 模型 | 窗口 | 对照（原生 D(SOC)） | 最佳常数 D | 该 D 是否落在格点边界 |
|---|---|---|---|---|
| SPM | pOCV-lith | 44.74 mV | 45.36 mV @1e-13 | **是** |
| SPM | pOCV-deli | 6.31 mV | 8.53 mV @1e-13 | **是** |
| SPMe | pOCV-lith | 44.74 mV | 45.36 mV @1e-13 | **是** |
| SPMe | pOCV-deli | 6.26 mV | 8.44 mV @1e-13 | **是** |

常数 D 格点值：lith `1e-17:271.3 → 1e-13:45.4`（单调下降，无内点极小）；deli `1e-17:536.7 → 1e-16:618.3 → 1e-14:43.3 → 1e-13:8.5`。

两条判断：
1. **没有任何常数 D 能胜过 SOC 相关的参考曲线** → $D(SOC)$ 的**形状**（不只是量级）在回放中确实起作用；
2. 最小值落在**格点边界** → 近平衡协议**只能给 D 的下界**，永远钉不住量级。这是设计使然，不是数据缺陷。

**覆盖率警告（必须随数字引用）**：扩散过电位大到提前触及下截止的运行，只在其存活的那段窗口内评分，
其 RMSE 是在**最容易的一段**上算的、因而被低估。最弱的运行覆盖率低至 **0.12**；该效应方向使
"小 D 更差"的结论**保守**，不是乐观。

### 3.2 常流族（0.5C/1C/2C，纯模型）

初态与 pOCV-lith 窗口共用（x0=0.0010，实测静置 OCV 3.0161 V），四档只差电流。

| 模型 | 速率 | 可持续协议占比（对照） | 可持续占比（GITT 曲线） | 到截止容量（对照 / GITT）[mAh] | D_thr [m²/s] | Fo @ D_thr |
|---|---|---|---|---|---|---|
| SPM | C/50 | 0.990 | 0.474 | 1.923 / 0.920 | 1.32e-15 | 1.265 |
| SPM | 0.5C | 0.780 | 0.195 | 1.515 / 0.379 | 8.36e-15 | 0.321 |
| SPM | 1C | 0.628 | 0.176 | 1.221 / 0.342 | 9.56e-15 | 0.183 |
| SPM | 2C | 0.431 | 0.136 | 0.836 / 0.263 | （格点内未越过） | — |
| SPMe | 2C | 0.337 | 0.115 | 0.656 / 0.224 | 2.24e-14 | 0.215 |

**用 GITT 曲线后模型能完成的协议比例腰斩**（C/50：0.990→0.474；1C：0.628→0.176）——
这是"该 D 进了模型会把电池算得几乎不能用"的直接量化，与 B1 的回放恶化同源。

**两个可观测量**：① **可持续协议占比**（每个格点成员都有定义、对 D 单调）；
② **t=½t_protocol 处的 V**（固定*时间*下体平均锂含量与 D 无关，故它纯粹反映表面积分滞后）。
刻意**不**把"固定交付容量处的 V"当主指标——它会饱和：只有已平衡的运行才走到那个容量，
饿死的成员直接变成 NaN 而不再计入敏感性。

### 3.3 SPM vs SPMe

C/50、0.5C 两档两模型一致（差 ≤2 个百分点）；1C 开始分离；**2C 明显分离**
（对照可持续占比 0.431 vs 0.337、到截止容量 0.836 vs 0.656 mAh）——**电解液在此成为第二个限制**。
→ 扩散结论在 ≤C/2 对模型结构稳健；把 2C 外推到真实电芯必须用 SPMe/DFN。

## 4. 判据（B2.3）：何时可以用 GITT 的 D_s

$$Fo=\frac{D\,t}{R^{2}}=\frac{t_{protocol}}{\tau_d}$$

实测阈值落点：**Fo ≈ 0.18 – 1.27（中位 0.32）**，即敏感/不敏感的分界就在 Fo ~ 0.1–1，
与物理预期（Fo~1 为交叉点）一致。

| 区间 | 含义 | GITT $D_s$ 可用吗 |
|---|---|---|
| Fo ≳ 1 | 每一步粒子都平衡 | **可用，而且它几乎不重要**——任何合理 D 给同一答案，5 个数量级的 SOC 散布无害 |
| Fo ≈ 0.1–1 | 扩散与协议同时间尺度 | **勉强**：D 直接进入答案，量级与 SOC 形状都必须对 |
| Fo ≲ 0.1 | 表面饿死 | **不可用**：模型输出由 D 本身支配，D 错与物理错无法区分 |

**GITT 曲线自身落在哪里**：C/50 时 Fo 跨度 3.3e-03 – 2.7e+02（中位 0.21）、0.5C 1.3e-04 – 1.1e+01、
1C 6.6e-05 – 5.3e+00、2C 3.3e-05 – 2.7e+00 —— **跨过整个分界区**，所以它既在低 SOC 段"太慢而支配结果"，
又在高 SOC 段"快到无所谓"。这正是"不能把一条 5 个数量级的曲线当单一参数塞进模型"的定量表述。

## 5. 过程中发现并修掉的一个真 bug（值得单独记）

初版常数 D 的 set-id **不含分支**：`sintef_graphite_Dsweep_<D>_v2` 对锂化与脱锂是同一个 id
→ 后注册的分支**静默覆盖**先注册的 → 锂化窗口跑在**脱锂 OCP** 上；脱锂 OCP 表只覆盖 SOC 0.081–1.0，
在 SOC 0.001 处线性外插到 **4.489 V**，超过 3.2 V 上截止 → t=0 触发
`SolverError: Events ['Maximum voltage [V]'] are non-positive at initial conditions`。

修法：id 加分支 token（`..._lith_...` / `..._deli_...`）+ `register_constant_d_sweep` 加**重复 id 拒绝**；
`scripts/probe_b2_registry.py` 作为常驻守卫（它同时把这个失败模式本身打印出来：脱锂 OCP 在 x=0.001 处 4.489 V）。

## 6. 措辞（强制）

apparent/effective solid diffusivity，**不是**本征材料常数、**不是**"真实 D"；Fo 是**协议**与扩散系数的性质，
不是材料的性质；GITT 曲线是 dataset-associated 表观参数，不跨电芯/粒径/温度迁移；零拟合，
格点上任何 RMSE 极小值**只作观察、一律不采纳**为拟合值。

## 7. Phase B2 未做

- ❌ 任何拟合/优化（本阶段按设计不做）
- ❌ 多孔电极修正（B1.5）
- ❌ 初始态修正（B0.6 遗留：x0 下限 1e-3 使模型无法表达实测的 3.016 V 新鲜态）
- ❌ DLR adapter、全电池（Phase D）

---

# Phase B0.7 执行记录：初始态 / 比较窗起点修正 · 2026-09-10

目标：修掉 B0.6 唯一未解释的残差来源——p-OCV **lithiation** 窗口里 `V_exp > 1.43 V`
那一栏**只有 1 个比较点**却有 **1939 mV** 残差。**没有拟合**；修的是一个可复现的
初始态/时间原点错位。`battery_sim/` 科学核心未改（改的是分析层 proxy）。

## 1. 缺陷链（三步，全部可复现）

**① 实测静置 OCP 落在冻结 OCP 表之外**——表端点的值带着"通电瞬间的极化"：

| 窗口 | 实测静置 OCV | 表端点 | 差值 |
|---|---|---|---|
| lithiation | 3.0161 V | 表顶 3.0003 V | **+15.8 mV** |
| delithiation | 0.0824 V | 支底 0.0967 V | **−14.3 mV** |

→ **没有任何合法初始锂含量能复现实测静置 OCV**；模型只能停在表的端点。

**② lithiation 侧稀释段近乎垂直**：表的第一段 `SOC 0 → 6.2e-5` 对应 `3.0003 → 1.7865 V`，
即 `dV/dSOC ≈ −1.96e4 V/单位 SOC`。

**③ 而 x0 不能继续调小**——PyBaMM 的初始态初始化是**在已施加电流下**求解表面状态的，
其过电位随 `c_s → 0` 发散（scripts/graphite_phase_b07_initial_state.py 的 floor scan，
`initial_state_floor_scan.csv`）：

| $x_0$ | OCP($x_0$) [V] | 求解 $V(0)$ [V] | 初始过电位 | 可解 |
|---|---|---|---|---|
| 1e-2 | 0.5815 | 0.5796 | −1.9 mV | 是 |
| 3e-3 | 0.7510 | 0.7475 | −3.5 mV | 是 |
| **1e-3** | **1.0759** | **1.0701** | **−5.8 mV** | 是 |
| 3e-4 | 1.3979 | 1.5051 | **+107.1 mV** | 是 |
| 1e-4 | 1.6844 | 2.1370 | **+452.6 mV** | 是 |
| 3e-5 | 2.4118 | 3.1215 | **+709.7 mV** | 是（V 逼近 3.2 V 上截止） |
| 1e-5 / 1e-6 | 2.8041 / 2.9807 | — | — | **否**（初始端电压越过 3.2 V 截止） |

→ **1e-3 是"初始态干净"的最小下限**；把 x0 调到 1e-4 虽能把 V(0) 抬到 2.19 V，代价是
一个虚假的 +453 mV 初始过电位。**所以问题不能靠移动 x0 解决。**

**真正的错误是"比较起点"**：模型从 $x_0=10^{-3}$（V=1.077 V）出发，却和实验的 $t=0$
（实测 3.016 V）配对；两者的**状态**相差 0.1% SOC，而石墨在这段陡峭区 0.1% SOC 就是几百 mV。

## 2. 修法：比较窗起点规则（参数化、预注册、只看参数不看残差）

> 模型在声明初始态下的端电压是 OCP($x_0$)。沿窗口行进方向落在该值**远侧**的**前导**
> 样本处于模型可达状态空间之外，从比较窗移除并**逐条记录**。

实现在 `scripts/graphite_phase_b0_compare.py` 的 `OCPConsistentAdapter`
（新增 `trim_unrepresentable_prefix` 开关 + `_trim_prefix()` + `WINDOW_START_TOL_V = 1e-3`）；
`_curve()` / `ocp_at()` 抽出为公共辅助（`_x0_for` 的映射行为**逐位不变**，有测试断言）。

| 窗口 | 模型起点电压 | 方向 | 移除点数 | 移除时长 | 占比 | 移除电压范围 |
|---|---|---|---|---|---|---|
| lithiation | 1.0759 V | descending | 18 | 160 s | **0.099 %** | [1.0795, 3.0161] V |
| delithiation | 0.1108 V | ascending | 17 | 150 s | **0.101 %** | [0.0824, 0.1108] V |

## 3. 结果

| 模型 | 窗口 | 规则 | 点数 | RMSE [mV] | MAE [mV] | max\|res\| [mV] |
|---|---|---|---|---|---|---|
| SPM | pOCV-lith | off | 1978 | 44.741 | 3.210 | 1939.2 |
| SPM | pOCV-lith | **on** | 1980 | **1.627** | **1.200** | **13.3** |
| SPM | pOCV-deli | off | 2000 | 6.313 | 2.654 | 64.7 |
| SPM | pOCV-deli | **on** | 2000 | **2.849** | **1.726** | **26.2** |
| SPMe | pOCV-lith | off | 1978 | 44.743 | 3.335 | 1939.2 |
| SPMe | pOCV-lith | **on** | 1980 | **1.721** | 1.325 | 14.3 |
| SPMe | pOCV-deli | off | 2000 | 6.262 | 2.753 | 63.7 |
| SPMe | pOCV-deli | **on** | 2000 | **2.926** | 1.852 | 26.4 |

### 必须回答的诘问：是不是"删掉最差点"？

**不是。在完全相同的实验点上复算**（把 off 的轨迹按移除时长切齐到同一网格），改进依然存在，
且落在**一个点都没删掉**的区间（`region_mae_common_window.csv`）：

| 模型 | 窗口 | 同一批点 | off RMSE | on RMSE | 区域（点数）off → on |
|---|---|---|---|---|---|
| SPM | lith | 1960 | 2.629 | **1.627** | `0.15–0.60 V`(169) **5.809 → 1.382**；`0.60–1.43 V`(1) 16.979 → 5.188 |
| SPM | deli | 1983 | 6.283 | **2.849** | `0.15–0.60 V`(832) **2.892 → 1.827**；`0.60–1.43 V`(40) **35.995 → 14.559** |
| SPMe | lith | 1960 | 2.708 | **1.721** | `0.15–0.60 V` **5.931 → 1.507** |
| SPMe | deli | 1983 | 6.232 | **2.926** | `0.60–1.43 V` **35.474 → 14.684** |

**机制**：规则把模型的**时间原点对齐到实验的"状态"**，而不是对齐到实验的 $t=0$。
off 时模型在整个窗口上"提前"了 0.1% SOC；石墨在陡峭段 0.1% SOC 就是几到几十 mV。
所以改进来自**状态对齐**，不是删除——这正是那些"一个点都没删"的区间同样改善的原因。

## 4. 对既有结论的影响（一并更正）

| 窗口 | B0.5/B0.6 记录值 | B0.7 修正后 |
|---|---|---|
| SPM pOCV-lith | 44.74 mV | **1.63 mV** |
| SPM pOCV-deli | 6.31 mV | **2.85 mV** |
| SPMe pOCV-lith | 44.74 mV | **1.72 mV** |
| SPMe pOCV-deli | 6.26 mV | **2.93 mV** |

**关键含义：修正后 lithiation 窗口（≈1.6 mV）实际比 delithiation（≈2.9 mV）更好**——
与修正前的印象（44.7 vs 6.3）**正好相反**。之前"lith 差得多"是初始态伪影，不是模型或 OCP 缺陷。

**B2 已重跑**（其 pOCV 列经本 proxy）：lith 对照 44.74 → **1.63**、GITT 曲线 68.57 → **19.09**；
deli 对照 6.31 → **2.85**、GITT 370.84。**B2 的结论被强化**：GITT 曲线在 lith 窗口上从
"1.5× 差"变成 **11.7× 差**；"没有任何常数 D 能胜过 SOC 相关参考曲线"依旧成立
（lith 格点最小 3.94 > 对照 1.63；deli 4.76 > 2.85）。

**未受影响**：B0 的 OCP 表提取；B0.6 的表保真度（在 (SOC,V) 平面上对实测曲线）；
B1 的 GITT 分段与 apparent D_s（独立通路）；B2 的诊断与 CC 族（前向仿真，起点在模型可达范围内）。
B0/B0.5/B0.6/B1 的**回放列**若重跑会变（其历史数值保留在各自 commit 中）。

## 5. 回归门

**229 passed**（219 + 10 项 `tests/test_initial_state_rule.py`：规则两个方向、只删前缀、
noop 情形、审计字段、不看残差、`_x0_for` 映射逐位不变）。

## 6. 措辞（强制）

不是 fitting：规则只用**参数**（声明初始态的 OCP）决定移除哪一段，预先注册、与残差无关，
移除量逐条披露。被移除的 0.1% **不是"模型误差被藏起来"**，而是**模型状态空间之外的数据**——
模型最多只能表达 OCP($x_0$) 以下的端电压。zero-fit 回放依然**不是** validation。

---

# Phase B1.5 执行记录：GITT 脉冲的过电位预算 —— apparent D_s 到底被什么限制？· 2026-09-10

B1 的结论是**定性**的："单颗粒模型是这份数据的错误透镜——多孔电极、电解液与伪 OCP 自身的极化
都被算进了固相扩散"。本阶段把它做成**定量**，并且**修正了 B1 归因的主次**。

## 1. 方法：让模型自己说过电位花在哪

对每个有效脉冲的 SOC 分箱，用**实测电极几何**跑一条**实测协议的脉冲**（SPM/SPMe/DFN），
在脉冲末刻分解端电压：

```
eta_total = V            - OCP(x_avg)         总极化
eta_solid = OCP(x_surf)  - OCP(x_avg)         固相扩散部分
eta_other = eta_total    - eta_solid          动力学 + 电解液 + 欧姆（合并）
f_solid   = |eta_solid| / |eta_total|
```

关键前提：**参照必须是模型自己的 OCP**（否则会引入常数偏移——测试里专门断言了 `|eta_total|<50 mV`）。
另外：`X-averaged positive particle stoichiometry` 在 PyBaMM 里仍是 **r 分辨**的（shape (n_r,n_t)），
必须用 `Average positive particle stoichiometry`（x 与 r 都平均）——这是一个已写进模块注释与测试的坑。

`extraction/gitt_pulse_budget.py`（纯诊断，pybamm 惰性导入；extraction 层里唯一需要 pybamm 的成员）
+ `scripts/graphite_phase_b15_porous_electrode.py`（33 个 SOC 分箱 × 3 模型 = 99 行）。

## 2. 三个时钟

| 量 | 值 |
|---|---|
| $\tau_{pulse}$（实测协议） | **1800 s** |
| $\tau_{solid}=R^2/D$（参考 $D$） | 15 397 s |
| $\tau_{solid}$（B1 的 GITT $D_s$） | 496 235 s |
| $\tau_{elyte}=L^2/D_{e,eff}$ | **未估计**（见下） |

$D_e$ **无法在模型之外求值**：参考集把 $D_e$ 定义成经电导率（本身是 $c_e$ 的函数）的 Nernst–Einstein
关系，$\text{FunctionParameter}$ 在无模型上下文时抛 `NotImplementedError`。
**因此改为直接测量电解液的作用**（§3），这比引一个文献 $D_e$ 更强。这一点写进了 `timescales.json` 的
`electrolyte_tau_note`。

## 3. 判决（99 行预算表）

**（a）电解液不是主因——这一条修正了 B1 的归因。**

| 量 | 结果 |
|---|---|
| $|\eta_{elyte}|/|\eta_{pol}|$ | **中位 0.001，最大 0.19** |
| SPMe vs SPM 的 $\eta_{pol}$ 差 | 中位 **0.13 mV**（就是电解液那一项） |
| DFN vs SPMe | 几乎逐位相同 |

→ 在这个电流（≈C/50 的脉冲）与 64 µm 电极下，**电解液过电位可以忽略**。
"多孔电极/电解液污染了固相扩散"这个假设**不成立**。

**（b）最大的单项误差是"拟合的形式"，不是物理。**

W-H 假设脉冲是叠加在**恒定**平衡电压上的 $\sqrt t$ 斜坡。实际不是：脉冲期间体平均锂含量线性前进，
平衡电压**线性漂移**：

$$V(t)=\underbrace{U(x_0)+U'\frac{I}{Q_{th}}t}_{\text{平衡（线性）}}
+\underbrace{U'\frac{2I}{3Q_{th}}\sqrt{\frac{t\tau_s}{\pi}}}_{\text{扩散（}\sqrt t\text{）}}$$

**只拟合 $a+m\sqrt t$ 无法把两者分开**。把模型自己的脉冲（真值已知）按同样方式读一遍：

| 读法 | 扩散信号被高估（中位） | 对 $D$ 的后果 |
|---|---|---|
| 一阶 $a+m\sqrt t$ | **2.9 ×** | $D$ 偏小 **9 ×** |
| 二阶 $a+bt+m\sqrt t$ | 1.2 × | $D$ 偏小 **1.5 ×** |

**两阶拟合的 $R^2$ 都 ≥0.95**（单看 SOC=0.1：一阶 $R^2$=0.987 却把 0.24 mV 的真值读成 14.5 mV）
→ **B1 的 $R^2\ge0.90$ 门在原理上不可能发现这个问题**，因为门限测的是"拟合得好不好"，
而问题是"**拟合的形式错了**"。

**（c）剩下的量级项是固相占比。**

- 中位 $f_{solid}$ = **0.089**（范围 0.000–0.707）；按支分：**锂化 0.30–0.35、脱锂 0.0078**。
- $D_{app}=D_{true}f^2$ 的预言 vs 实测：**平移 +0.90 dex**（≈8 倍）——量级对；
  **形状不对**（log-log 斜率 0.03、r=0.07），因为实测偏置同时被"拟合形式偏差（随 $U'$）"与
  $f_{solid}$ 驱动，而 $f^2$ 只含后者。

## 4. 修正后的因果链（这是本阶段真正的产出）

| 排序 | 机制 | 量级 |
|---|---|---|
| 1 | **一阶 $\sqrt t$ 拟合被平衡漂移污染** | 信号 ×2.9 → $D$ ÷9 |
| 2 | **固相只占过电位的一部分**（$f_{solid}^2$） | $D$ ÷(1/0.089²)≈÷126 |
| 3 | 电解液/多孔电极 | ≤19%，中位 0.1% —— **不是主因** |
| — | 粒径 $R$ 取参考集 | $D\propto R^2$，系统性未定量 |

**因此 $"D_s$ 不能直接作为 SPM 固相扩散参数" 的结论成立，但原因与 B1 说的不同**：
不是多孔电极污染，而是**（1）反演的函数形式错了 +（2）固相信号本来只占一小部分**。

## 5. 可操作结论

| 条件 | 结论 |
|---|---|
| 只用一阶 $\sqrt t$ 反演 | **不可用**（形式上就偏 ÷9 起） |
| 用二阶（线性漂移 + $\sqrt t$）反演，且 $f_{solid}\to1$ | 有意义 |
| $f_{solid}\ll1$（平台区/动力学主导，尤其脱锂支 0.008） | **不可用**：$D_{app}$ 是过电位除以了错误的物理量 |
| 要定量精度 | 必须做**过电位分解**（本阶段的做法），或改用多孔电极模型直接拟合同一协议 |

## 6. 措辞（强制）

$f_{solid}$ 是**模型量**：依赖模型结构（SPM/SPMe/DFN）、参考集的电解质物性、孔隙率与 $R$；
它说明的是"**按本模型**，这条脉冲里多少过电位能归到固相扩散"，**不是材料的本征性质**。
本阶段**不做任何拟合、不修改 B1 的 $D_s$ 表、不产出新的"可用参数"**。

## 7. Phase B1.5 未做

- ❌ 用二阶反演**重做**整条 $D_s(SOC)$ 表（需要把 981 条脉冲波形重新取出并重拟合 → 独立一步）
- ❌ 用模型直接拟合 GITT 协议反演 $D$（PyBOP 的 `GITTFit` 路线）
- ❌ 孔隙率/粒径实测（目录未提供）

---

# Phase B1.6 —— 用二阶（含平衡漂移）拟合重做整条 $D_s(SOC)$ 表

**范围**：把 B1.5 指出的**拟合形式偏差**落地修正，重做整条表并回放检验。
不改 OCP / 几何 / 容量 / 门限；不做拟合（不拿实测电压反推参数）。

## 1. 实现（additive）

| 文件 | 作用 |
|---|---|
| `extraction/gitt_extractor.py`（改） | 新增 `_fit_quadratic_sqrt_t`（$V=a+bt+m\sqrt t$，$t$ 做中心化+按脉宽缩放以改善条件数，列的**列空间不变**故 $m$ 即原始 $\sqrt t$ 系数）；**一次扫描同时产出两种拟合**，一阶列名/含义完全不变 |
| `extraction/gitt_diffusivity_v2.py`（新） | 同一 W-H 反演，`m` 取二阶系数；**门限、`local_ocp_slope`、SOC 分箱全部从 `gitt_diffusivity.py` import**（单一真源，测试断言不会分歧）；附逐脉冲"一阶 vs 二阶"对比与**漂移诊断** |
| `scripts/graphite_phase_b16_ds_v2.py`（新） | 分割 → v1/v2 两表 → 回归自检 → 注册两套后缀参数集 → 三方 replay → `report.md` |
| `tests/test_gitt_ds_v2.py`（新，18 项） | 含**定义类测试**（见 §5） |

产物：`outputs/analysis/graphite_phaseB16/`（`v1/`、`v2/`、`ds_form_comparison.json`、
`report.md`、2 图、6 组 run）。**v1 与 v2 目录同名同列**，故 B1 的参数集构建器
（`parameters/sintef_graphite_ds.py`）只换 `ds_dir` 即可读，无需改一行。

## 2. 回归自检（必要条件）

重算的 v1 表与冻结的 B1 表**逐行一致**（74 行，最大相对差 **2.2e-16**）→
分割与反演路径未被改动，两张表的差别只可能来自拟合形式。

## 3. 结果

| 量 | v1（一阶） | v2（二阶） |
|---|---|---|
| 接受脉冲 | 616 / 981 | **851 / 981** |
| 中位 $D_s$（各自接受集） | 3.782e-16 | 8.805e-17 m²/s |
| **共同集（614 条）中位** | 3.803e-16 | **2.155e-16 m²/s** |

- **配对**统计（同一批 614 条脉冲，逐条 $D_{v2}/D_{v1}$）：中位 **0.427×**，仅 26% 单条变大，
  跨度 0.12–6.27×；**群体**统计（中位数之比）：**0.567×**。两者同号。
- 参考值 Ecker2015 中位 **1.219e-14 m²/s** → 修正后仍低 **57×**（整表 70–334×）。
- **replay**（同一冻结集，只换扩散）：lith **19.09 → 29.71 mV**，deli **370.84 → 466.17 mV**
  （对照 Ecker D：1.63 / 2.85 mV）→ **两窗都更差，不采纳**。

## 4. 方向与 B1.5 的模型预言相反（本阶段最重要的发现）

B1.5 用**模型脉冲**测得：一阶拟合把扩散信号高估中位 2.9× → 去掉漂移后 $D$ 应**升**约 9×。
**实测相反**：一阶斜率只有二阶的 **0.474×** → $D$ 反而降 **2.3×**。

**原因（漂移诊断）**：纯平衡漂移应为 $\mathrm{d}U/\mathrm{d}t=U'I/Q_{th}$；
实测拟合出的线性项是该值的 **-4.6×**（中位），且**符号只在 19% 的脉冲上与平衡漂移一致**。
→ 这一项装的**不是平衡漂移**，而是缓慢的**非平衡松弛**（电荷转移、多孔电极弛豫、伪 OCP 自身沉降），
它同时带走了本属于 $\sqrt t$ 的曲率。

**结论**：拟合形式的偏差**方向与大小都是数据依赖的**，
模型脉冲上的标定（2.9× / ÷9）**不能迁移到真实电极**——只有实测才知道。

## 5. 两个方法学收获（都可复用）

1. **验收统计量必须"配对 vs 群体"并列**：本数据上同一问题的两个合法汇总差 **2×**
   （0.427 配对中位 vs 0.567 中位数之比），因为修正**异质**——26% 的脉冲变大、其余变小，
   且"变大"的集中在 SOC 0.85、"变小"的集中在 SOC 0.55。只报一个数就是选择性陈述。
2. **比值类列必须配"定义类测试"**：本轮抓到真 bug——配对比值的指数写反
   （$D=R^2/\tau_d$、$\tau_d\propto m^2$，故 $D_{v2}/D_{v1}=(m_{lin}/m_{quad})^{2}$，不是它的倒数）。
   "列存在/有限"的测试**抓不到**这种错；必须让它与**独立算出的 $D_{v2}/D_{v1}$** 逐条对齐
   （`scripts/probe_b16_common_set.py` 常驻做这件事，实测最大相对差 2.9e-15）。

## 6. 裁决与措辞

**B1.6 关闭了"拟合形式"这条线**：两种函数形式不同的一阶/二阶反演，对同一条 GITT 列车
给出**同一质性结论**——单颗粒 W-H 反演的 apparent $D_s$ 比参考值低 1–2 个数量级、
且不能改善回放；而两者在数值上差 1.8–2.3×，**这个跨度本身就是这份数据上
"任何单颗粒 GITT 扩散系数"的诚实误差棒**。

措辞：仍然是 **apparent/effective**，不是材料常数、不是验证；修掉一个已知的函数形式偏差
**不等于**把值变成了可用参数（本数据集上反而更差）。

## 7. 仍未做的（B1.6 收口之后）

- ❌ PyBOP `GITTFit` 路线（直接对 GITT 协议做模型拟合）
- ❌ 多孔电极/SPMe 层面的扩散反演（B1.5 已证明电解液 ≤19%，但多孔结构本身未建模）
- ❌ 孔隙率/粒径实测（用户的商业石墨已有规格书粒径，但那只用于用户自制半电池，**不得回填本线**）
