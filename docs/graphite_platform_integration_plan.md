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
