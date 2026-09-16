# Battery-Sim-Agent 只读审计报告

**审计对象**：`C:\Users\24330\WorkBuddy\Battery-Sim-Agent`（`opqrst-chen/Battery-Sim-Agent` 的本地副本）
**审计时间**：2026-09-12
**审计方式**：只读。未修改任何代码/配置/数据/测试。全部结论来自实际文件读取与实跑。
**运行环境**：WSL Ubuntu(zjh) / conda env `pybamm` / PyBaMM **26.8.0** / pytest 9.1.1

---

## 第一部分：真实调用链

### 1.1 总体结论（先说最重要的）

**这条链在当前仓库里不存在。**

用户描述的链路是：

```
数据集/实验文件 → 数据读取/adapter → Agent → SimulationRequest 构造
→ model_name/param_set/params/protocol → PyBaMM model/solver → SimResult → evaluation/output
```

逐项在仓库全文检索的结果：

| 检索词 | 命中 |
|---|---|
| `SimulationRequest` | **0**（`--include=*.py/*.yaml/*.md` 全仓，排除 `outputs/`） |
| `SimResult` | **0** |
| `sintef` / `SINTEF` / `graphite` / `half.cell` / `halfcell` | **0** |

平台侧（`C:\Users\24330\WorkBuddy\仿真模拟`）同样检索：`SimulationRequest` / `SimResult` **均为 0 命中**。

→ **`SimulationRequest` 与 `SimResult` 是"导师提出的目标契约"，不是现有代码。** 本报告第二、五部分只能审计"现有代码离这个契约有多远"，而不是审计一个已实现契约的正确性。

### 1.2 实际存在的两条链

**（A）Agent 链 —— `battery_agent/`（这是"Agent"那一环的实机代码）**

```
generate_simulated_data/output/*.yaml          ← "数据集"（模拟数据设置，非实验数据）
  └─ run_exp.py  load_yaml()                   逐 key 起子进程
      └─ battery_agent/pipeline.py  main()
          ├─ read_yaml(args.yaml_path)  → ori_settings = settings[test_id]
          ├─ RESULTS_DIR 格式化 + copytree 代码快照
          └─ first_cycle_pipeline(RESULTS_DIR, ts, ori_settings)
              │  或 degradation_pipeline(...)
              ├─ utils/data.py : load_simulated_battery_data(ori_settings, cycle_len)
              │     → 自己跑一次 PyBaMM，产出"伪实验数据" cycle_data（list[dict]）
              │     ※ 真实数据路径是 load_battery_data()，读
              │       ./real_world_data/CALCE_CS2_33.pkl —— **该目录在 .gitignore 中且本机不存在**
              ├─ pybamm_runner.py : simulate_capacity(new_params, ori_data, param_name,
              │                                        model_name, experiment, ori_settings, ...)
              │     ├─ models dict {SPM,SPMe,DFN} → model = models[model_name]
              │     ├─ param = pybamm.ParameterValues(param_name)    ← param_set 是**字符串名**
              │     ├─ param.update(parameters)                       ← params 覆盖
              │     ├─ experiment = make_cccv(...)  （ori_settings 存在时）
              │     │  或 **硬编码 CALCE 全电池协议**（ori_settings 不存在时）
              │     └─ sim.solve(solver=CasadiSolver(mode="safe", dt_max=60))
              ├─ utils/plot.py : plot_multiple_curves(sim, ori_data, ...)
              │     → (context: str, detail_info: list[dict])
              ├─ utils/exp.py : calculate_loss(sim, ori_data, cycle_idx)
              │     → dict{Q_rmse,Q_mape,I_rmse,I_mape,V_rmse,V_mape}
              └─ return **tuple** (见 §5)

LLM 侧：
      ├─ utils/llm.py generate_first_cycle_message(...) → messages
      └─ utils/llm.py call_llm_for_params_to_update(task=TASK, ...)
            ├─ call_llm()  → openai 兼容端点（configs/llm.yaml，**本机缺失**）
            └─ parse.parse_suggestion() → contract.validate_suggestion() → Suggestion
                                          ↑ 这是唯一真正的"契约"，但它管的是
                                            **LLM 输出的参数名/值域**，与 SimulationRequest 无关
```

**（B）基线链 —— `baseline/bayesian_optimization*/`、`baseline/cma_es*/`**
六份结构几乎相同的 PyBaMM 优化器副本，各自有独立的 `BO/pybamm_runner.py`、`configs/`、`scripts/`。与 Agent 链**代码不共享**。

### 1.3 README 与真实代码的一致性

| README 说法 | 实际代码 | 判定 |
|---|---|---|
| `pybamm==25.6.0`（第 43 行） | `requirements.txt` 写 `pybamm==25.6.0`；**本机 env 是 26.8.0** | ⚠️ 未在声明版本上验证；API 兼容性未测 |
| 「`battery_agent/` 主 LLM agent」 | 属实 | ✅ |
| 「Results land under RESULTS_DIR（默认 `./exp_results/single/{id}/{time_stamp}/`）」 | `configs/exp.yaml` 的模板是 `./exp_results/single/{id}/{time_stamp}`；但 `pipeline.py:38-39` 只 format 了 `{id}` 和 `{time_stamp}`，**与模板占位符一致** | ✅ |
| 「`script/` Convenience entry-point shell scripts」 | `script/run_first_cycle.sh`、`run_degradation.sh` 存在 | ✅ |
| 「Three benchmark families derived from PyBaMM's DFN model」 | 属实 | ✅ |
| 安装说明 `cp battery_agent/configs/llm.yaml.example → llm.yaml` | `.example` 存在 | ✅ |
| **README 完全没有提到** `contract.py` / `parse.py` / `tests/` | 三者都存在，且 `docs/BORROW_NOTES.md` 记录了这是本地加固 | ⚠️ README 未同步 |

**重要**：`docs/BORROW_NOTES.md` 第 66 行明确写「**没有改**：`baseline/`、`generate_simulated_data/`、`pybamm_runner.py`、`params.py`、`utils/data.py`、`configs/`」。已核实属实——**契约层只覆盖 LLM 输出解析，仿真侧一行未动**。

---

## 第二部分：SimulationRequest 输入契约审计

### A. model_name

**现有实现**：`pybamm_runner.py:94-99`
```python
models = {
    'SPM':  pybamm.lithium_ion.SPM(options=options),
    'SPMe': pybamm.lithium_ion.SPMe(options=options),
    'DFN':  pybamm.lithium_ion.DFN(options=options),
}
model = models[model_name]
```

| 检查项 | 结论 |
|---|---|
| 支持哪些模型 | 三个：`SPM` / `SPMe` / `DFN`（`dict` key `models`） |
| SPM/SPMe/DFN 是否都能 dispatch | ✅ 三个 key 都在，实跑 `models['DFN']` 成功 |
| 未知 model_name | ❌ **裸 `KeyError`**（实测 `model_name="SPMe_fake"` → `KeyError: 'SPMe_fake'`），无友好报错、无候选提示 |
| options 是否被 model_name 唯一确定 | ❌ **否**。`options` 由函数参数独立决定，与 model_name 正交 |
| 是否存在隐藏 SEI options | ⚠️ **是，且有两套不一致的默认** |

**隐藏 options —— 两套默认值，互相不一致（实测）**

| 位置 | SEI | SEI film resistance | SEI porosity change |
|---|---|---|---|
| `pybamm_runner.py:89-93`（`simulate_capacity` 的默认） | `"reaction limited"` | `"distributed"` | 未设（→ `"false"`） |
| `pybamm_runner.py:14` → `configs/pybamm.yaml:12-20`（`build_simulation` 的 `MODEL_OPTIONS`） | `"reaction limited"` | **`"average"`** | **`"true"`** |

→ **同一个 `model_name` 会因为走哪个函数而跑出不同的物理模型**（SEI film resistance 的 `distributed` vs `average` 是两种不同的空间处理；`SEI porosity change` 直接改变孔隙率演化）。这是"同一 model_name 可能跑出不同物理模型"的**实证**。

同时，`configs/pybamm.yaml:11` 定义了 `MODEL_NAME: "DFN"`，但**没有任何代码读它**；两条 pipeline 读的是 `pybamm_configs['DFN']`（`first_cycle_pipeline.py:53`、`degradation_pipeline.py:70`）——即把 `"DFN"` 当成 **key 名**去查配置。`pybamm.yaml` 里并没有名为 `DFN` 的 key，实跑会 `KeyError`。这是一个**在真实数据路径上必然触发的崩溃点**（见 P0-3）。

### B. param_set

| 检查项 | 结论 |
|---|---|
| 是名称还是完整参数对象 | **名称（字符串）**。`pybamm_runner.py:101` `pybamm.ParameterValues(param_name)`；默认 `"Chen2020"`（`configs/pybamm.yaml:10`） |
| 如何加载 | PyBaMM 内置 parameter set 注册表，按字符串名查 |
| 基础参数来源是否明确 | ⚠️ **部分**。对 `Prada2013` / `ORegan2022` 会**静默补入 Chen2020 缺失键**（`pybamm_runner.py:102-108`）→ 参数集变成"Prada2013 ∪ Chen2020"，**没有任何 provenance 记录**，产物里看不出来源是混合的 |
| 哪些参数会被 params 覆盖 | `param.update(parameters)`（`:112`）——**参数名匹配即覆盖，无白名单、无值域、无来源标注** |
| 是否有多个地方重复改 ParameterValues | ⚠️ **是，四处**：`pybamm_runner.build_simulation:41-44`（两次 update）、`pybamm_runner.simulate_capacity:101-112`、`utils/data.load_simulated_battery_data:117-129`、以及六个 `baseline/*/BO/pybamm_runner.py` 各自的副本 |

### C. params 字段支持矩阵

逐项对照用户列出的实验参数（`pybamm_runner.simulate_capacity` 的 `parameters` 直通 `param.update`）：

| 实验参数 | 代码是否支持 | 是否真进 PyBaMM | 说明 |
|---|---|---|---|
| `initial_soc` / `initial_stoichiometry` | ⚠️ **仅以浓度形式间接存在** | ⚠️ 间接 | 无 `initial_soc` / `initial_stoichiometry` 这些**名字**（全仓 0 命中）。只能用 `Initial concentration in negative/positive electrode [mol.m-3]`（`params.py:14-15, 46-47`）。**且初始 stoichiometry 由 浓度/c_max 隐含决定，不是一个可独立输入的参数** |
| `temperature` | ✅ 以 PyBaMM 键存在 | ⚠️ 见下 | `Ambient temperature [K]` / `Initial temperature [K]` 在 Chen2020 中 = 298.15。**属于 `SEARCH_KEYS_DEGRADATION` 白名单**，所以 LLM 可以改它 |
| `electrode_thickness` | ✅ | ✅ | `Negative/Positive electrode thickness [m]` |
| `electrode_area` | ❌ **无此参数** | — | PyBaMM 用 `Electrode width [m]` × `Electrode height [m]`。**没有 area 这个可输入量**，必须由两维相乘得到（见 §4 与 P1-1） |
| `active_material_loading` | ❌ **无此参数** | — | 只有 `... active material volume fraction`（体积分数，无量纲），**不是面载量 mg/cm²**。两者不可互换 |
| `electrode_porosity` | ✅ | ✅ | `Negative/Positive electrode porosity` |
| `particle_radius` | ✅ | ✅ | `Negative/Positive particle radius [m]` |
| `OCP(SOC)` | ⚠️ **存在但是函数/插值对象** | ⚠️ | `Negative electrode OCP [V]` / `Positive electrode OCP [V]` 在 Chen2020 里是**函数对象**（`pybamm.ParameterValues` 内的 callable），**不是标量**。`param.update()` 能不能接受替换为自定义函数——代码没有做过这件事，也没有任何代码路径从实验 OCP 生成函数 |
| `apparent_Ds(SOC)` | ❌ **无此入口** | — | 只有 `Negative/Positive particle diffusivity [m2.s-1]`（在 Chen2020 中是**常数**）。**没有 SOC 依赖的函数形式入口**，也没有任何从 GITT 反演 D 的代码 |

**逐条回答用户重点检查项：**

1. **哪些字段代码现在支持？** 厚度、孔隙率、粒径、活性物体积分数、Bruggeman、导电率、双电层电容、初始/最大浓度、温度（仅 degradation 白名单）。**全都是标量。**
2. **哪些只是理论上说支持、实际没进 PyBaMM？**
   - `initial_soc` / `initial_stoichiometry`：**名字不存在**，无直接入口。
   - `electrode_area`：**不存在**。
   - `active_material_loading`：**不存在**（只有体积分数）。
   - `OCP(SOC)` / `apparent_Ds(SOC)`：**没有任何从数据构造函数的代码路径**。
3. **params 覆盖 param_set 的优先级在哪里实现？** `pybamm_runner.py:112` `param.update(parameters)`。**无优先级分层**——后写的覆盖先写的，没有任何"实验数据优先于 param_set"的规则，也没有记录哪个键被覆盖了。
4. **单位有没有统一？** ❌ **没有**。全部依赖 PyBaMM 键名里的单位后缀（`[m]`/`[mol.m-3]`/`[S.m-1]`）。**没有任何输入校验**：传 `1.5391`（cm²）到 `[m]` 字段不会被拦，只会静默算错（实证见 §4.1）。
5. **是否区分标量参数和函数/曲线参数？** ❌ **完全不区分**。`param.update()` 对两者一视同仁，且 `contract.BOUNDS` 只覆盖**标量**的 15 个键，函数类参数**完全在护栏之外**。
6. **OCP(SOC)、Ds(SOC) 能否真正传入 PyBaMM？** 技术上 PyBaMM 支持（`param.update` 传 callable），**但本代码库没有任何地方这么做**，也没有数据、没有插值、没有执行。→ **当前答案为"不能"**。
7. **数据中没有的参数是否会产生默认值/猜测值？** ⚠️ **会，且这是最危险的一条**：
   - `params.py:1-16` `initial_params` 与 `params.py:37-65` `initial_params_for_first_cycle` 是**硬编码的猜测量**，两条 pipeline 都会无条件把它们 update 进参数集（`first_cycle_pipeline.py:54` / `degradation_pipeline.py:71` `param_groups_list = [initial_params_for_first_cycle.copy()]`）。
   - 因此**"实验数据里没有 → 保留 param_set"这条规则在当前代码里不成立**：实际是"实验数据里没有 → 用 `initial_params_for_first_cycle` 里那个硬编码数字覆盖 param_set"。
   - 实测：`initial_params` 与 `initial_params_for_first_cycle` 的**每一个键都存在于 Chen2020**（missing = 0），所以这些覆盖**不会报错**，只会静默生效。例：Chen2020 的 `Initial concentration in negative electrode [mol.m-3]` 是 **29866.0**，被 `initial_params` 覆盖成 **17800.0**（stoichiometry 从 Chen2020 的值变成 **0.962**）。
8. **最终能否输出 effective parameters？** ⚠️ **部分能，但有坑**：`simulate_capacity:114` `log_params = {k: param[k] for k in search_keys if k in param}` —— 只记 `search_keys`（默认=9 个结构参数，`SEARCH_KEYS` at `:16-26`）。**不是完整 effective parameters**：被覆盖的初始浓度、c_max、Bruggeman、温度等**全都不在记录范围内**。而 `context` 只把它拼成**自由文本**（`:155` `context += f'Current parameters are: {log_params}'`），**没有结构化落盘**。

### D. initial state

老师已决定初始状态放 `params` 里。**当前代码没有遵守这个决定。**

| 检查项 | 结论 |
|---|---|
| `initial_soc` 是否真正传给 PyBaMM solve/init | ❌ **该名字不存在**。`pybamm.Simulation(...)` 构造与 `sim.solve()` 调用**都没有任何 initial-state 入参**（`pybamm_runner.py:134-139`）。初始状态**只能**通过 `ParameterValues` 里的 `Initial concentration in ...` 间接生效 |
| `initial_stoichiometry` 是否真正改变初始电极浓度 | ⚠️ **可以间接改变**（改初始浓度），但**不存在独立参数**；且改浓度时会与 c_max 交互（若 > c_max 则 PyBaMM 会报错，代码无预校验） |
| 是否只是存在 JSON 字段但实际没作用 | **不存在这样的字段**——因为根本没有 `initial_soc` 字段 |
| full cell 与 half-cell 初始化语义是否区分 | ❌ **完全不区分**。代码里没有 `working electrode` 选项的设置（`build_simulation` 与 `simulate_capacity` 都只传 SEI 相关 options）；且初始浓度键名是**全电池语义**的 `Negative/Positive electrode`，**没有 half-cell 语义下的"工作电极/对电极"区分**。半电池需要的 `Initial concentration in positive electrode` 语义在此代码中完全缺失 |

### E. protocol

| 检查项 | 现有实现 |
|---|---|
| 电流 / C-rate | ✅ `ori_settings['charge_c_rate']` / `['discharge_c_rate']` → `utils/data.make_cccv`（`:82-96`） |
| 充放电方向 | ⚠️ **写死在 `make_cccv` 的字符串里**：`"Charge at ..."` / `"Discharge at ..."`，无方向开关 |
| cutoff voltage | ⚠️ **从 param_set 读**：`v_min = param["Lower voltage cut-off [V]"]`、`v_max = param["Upper voltage cut-off [V]"]`（`pybamm_runner.py:117-118`、`utils/data.py:126-127`）。Chen2020 是 2.5 / 4.2 V |
| pulse duration | ❌ **不存在**。协议里没有 pulse，只有 CC-CV + rest |
| rest duration | ⚠️ **写死**：`"Rest for 1 second"` / `"Rest for 90 second"`（`utils/data.make_cccv`）。**另一套又不同**：`configs/pybamm.yaml` 的 `SINGLE_CYCLE` 是 `120 / 120 / 90 / 90 seconds`。**两套 rest 时长不一致，且都不是可输入参数** |
| cycle number | ✅ `cycle_len` 参数（但 `simulate_capacity` 里传给 `make_cccv` 的是 `cycle_idxs[-1]+1`，即由 `INDEX_TO_SEARCH` 反推，而非显式 cycle 数） |
| temperature（protocol 中） | ❌ **protocol 里没有温度**。温度只在 param_set（`Ambient/Initial temperature [K]`）里，**且与 protocol 无任何一致性校验** |

**重点发现的隐藏默认 protocol：**

1. **`simulate_capacity` 里有一段硬编码的全电池协议**（`pybamm_runner.py:121-131`）：
   ```python
   # default protocol for CALCE battery
   experiment = pybamm.Experiment([(
       "Rest for 120 second", "Charge at C/2 until 4.2 V", ...
       "Discharge at C/2 until 2.7 V", "Rest for 90 second",
   )] * 2)
   ```
   触发条件：`ori_settings` 不是 dict **或** 传入的 `experiment` 不是 `pybamm.Experiment` 实例。
   → **`4.2 V` / `2.7 V` 是硬编码的锂离子全电池条件**（正是用户要找的）。
   → 注释自己写「for CALCE battery」（CALCE 的 LFP 与 LCO 截止电压不同），**换任何电池都是错的**。
   → `configs/pybamm.yaml` 的 `SINGLE_CYCLE` 是另一套（`120/120/90/90` + `Hold at 4.2 V until 50 mA`）→ **两套默认协议并存**。

2. **`build_simulation` 的 `EXPERIMENT` 也从 `configs/pybamm.yaml` 来**（`pybamm_runner.py:10-12`），同样是 4.2 / 2.7 V，且 `[SINGLE_CYCLE] * EXP_CYCLES`。

3. **half-cell 会错误使用 full-cell protocol**：`simulate_capacity` 的 `make_cccv` 路径用 `v_max/v_min` 从 param_set 取，`pybamm.yaml` 路径用硬编码 4.2/2.7。**两条路径都没有 half-cell 分支**。石墨‖Li 半电池需要 ~1.0 V 上限（vs Li/Li⁺），用 4.2 V 是物理错误。

4. **protocol 与 params 的 temperature 冲突无检测**：protocol 里没有温度字段（见上），所以不存在"冲突检测"——**冲突表现为"温度完全由 param_set 决定，用户从 protocol 侧无法控制"**。

---

## 第三部分：实验数据 → params 的来源链审计

用户要求每个 params 字段都能记录：`parameter_name / value|curve / unit / source / method / confidence`。

**结论：这套溯源机制在当前代码里完全不存在。**

| 溯源字段 | 现状 |
|---|---|
| `parameter_name` | ✅ 只作为 PyBaMM 键名字符串存在 |
| `value` or `curve` | ✅ 值存在；**`curve` 无任何支持**（见 §2.C.5） |
| `unit` | ⚠️ **仅隐含在键名后缀里**，无独立字段，无校验 |
| `source` | ❌ **无**。`contract.ParamUpdate` 只有 `name` + `value` 两个字段（`:114-117`），**没有 source** |
| `method` | ❌ **无** |
| `confidence` / `quality flag` | ❌ **无** |

**"实验数据里有 → 覆盖 param_set"**：❌ **未实现为规则**。实际逻辑是 `initial_params_for_first_cycle`（硬编码）无条件覆盖 param_set，再由 LLM 提议的值覆盖它。**没有"先看实验数据、有则用、无则留"的分支。**

**"绝对禁止 missing → Agent 自己生成一个合理数值"**：❌ **这条禁令当前被违反**——`initial_params` / `initial_params_for_first_cycle` 就是人写的"看起来合理的数值"，且无条件生效（见 §2.C.7）。虽然它们不是 LLM 生成的，但**从最终 effective parameters 的视角，来源同样不可追溯**。

**特别审计项：**

| 项目 | 现状 |
|---|---|
| electrode thickness 单位 | ✅ `[m]` 在键名里；`initial_params_for_first_cycle` 用 `7.65e-05`（76.5 µm）合理 |
| electrode diameter / area 单位 | ⚠️ **无 diameter/area 参数**。`Electrode width [m]` + `Electrode height [m]`。**Chen2020 = 1.58 m × 0.065 m = 0.1027 m²**（这是卷绕电芯的展开尺寸），而 `initial_params` 写 `0.0368`、`initial_params_for_first_cycle` 写 `0.04` —— **量级相差 43× / 40×，且代码不报错**（实证见 §4.1） |
| loading 单位 | ❌ 无 loading 参数，只有体积分数（无量纲） |
| current sign convention | ⚠️ **不统一，至少三处不同**：<br>① `utils/data.load_simulated_battery_data:140` `current_in_A = -sol[...]`（**取了负号**）<br>② `utils/exp.calculate_loss:118` `current = -sim.solution...`（**取了负号**）<br>③ `utils/plot.py` 内部另有一套（未逐一核对）<br>→ 负号靠"约定俗成"散落在各调用点，**没有单一定义处**，也没有测试守护 |
| temperature 来源 | ⚠️ 只来自 param_set 的 `Ambient/Initial temperature [K]`；**无实验数据来源**，无 provenance |
| OCP 数据来源 | ❌ **无**。只有 Chen2020 内置函数，**没有任何代码从实验 p-OCV 构造 OCP** |
| apparent Ds 数据来源 | ❌ **无**。只有 Chen2020 常数值 diffusivity，**没有 GITT 反演代码** |

---

## 第四部分：graphite‖Li half-cell 专项审计（case study）

### 4.0 前置结论：这条路径在本仓库**不存在**

- `sintef` / `graphite` / `half.cell` 在 `Battery-Sim-Agent` 全仓 **0 命中**。
- SINTEF graphite 的**数据与 adapter 在你自己的平台项目里**：`C:\Users\24330\WorkBuddy\仿真模拟\battery_sim\datasets\sintef_graphite.py`，数据文件是 `data\sintef__sintef-graphite-R2032-intelligent-*.bdf.parquet`（4 个）。
- **两个仓库之间没有任何代码引用关系**（无 import、无 subprocess、无共享 config）。

→ **用户列的 10 个检查项，在 `Battery-Sim-Agent` 里全部无法用"该仓库的代码"回答**，因为对应代码不在这个仓库。下面逐项标注"在哪、现状如何"。

| # | 检查项 | 现状 |
|---|---|---|
| 1 | 电极直径 14 解释为 mm 而非 cm | **不在本仓库**。平台侧 `battery_sim/datasets/sintef_graphite.py` 处理；项目 memory 已记录该坑（"metadata 直径列名写 cm 实为 mm"）。**本仓库无相关代码可审** |
| 2 | electrode area 是否正确计算 | ❌ **本仓库无 area 计算**。且如上所述 `Electrode width` 被两条 pipeline 用 0.0368/0.04 覆盖（与 Chen2020 的 1.58 差 43×），**任何依赖几何面积的量都会错** |
| 3 | 原始电流符号 → 平台统一符号是否正确转换 | ⚠️ 本仓库只有"负号散落在 `utils/data.py:140` 与 `utils/exp.py:118`"的**局部约定**，**没有统一的符号转换层**，也没有 half-cell 的锂化/去锂化方向翻转 |
| 4 | graphite lithiation / delithiation 方向 | ❌ **本仓库无 half-cell 方向处理** |
| 5 | graphite 对应哪个 electrode slot | ❌ **本仓库无此概念**。`build_simulation` 与 `simulate_capacity` **都没有设置 `working electrode` option**（实测：三模型的 `options['working electrode']` 全部保持默认 `'both'`），因此**无法表达 half-cell 的槽位语义** |
| 6 | OCP 函数是否绑定到正确 electrode | ❌ **本仓库无 OCP 绑定逻辑**（不构造 OCP，只用 Chen2020 内置的） |
| 7 | initial stoichiometry 方向是否与 OCP 定义一致 | ❌ **本仓库无 stoichiometry 参数**（见 §2.C），方向一致性无从谈起 |
| 8 | GITT 参数是否明确称 apparent/effective Ds | ❌ **本仓库无 GITT 代码、无 Ds 参数**。措辞风险不在本仓库 |
| 9 | 是否把 GITT rest endpoint 错当真正 OCP | ❌ **本仓库无 GITT 处理** |
| 10 | 大型 parquet 是否 streaming/filtering | ❌ **本仓库不读 parquet**（`data_path` 是 `.pkl`：`utils/data.py:36` `./real_world_data/CALCE_CS2_33.pkl`）。parquet 在平台侧 |

**→ 第四部分对这个仓库的审计结论：无对应实现，无法通过。** 若老师明天要试的是 graphite‖Li 半电池，**这个仓库不是入口**。

---

## 第五部分：SimResult 审计

### 5.1 成功与失败的数据结构 —— 实证结果

**没有 `SimResult`。返回的是裸 `tuple`，且成功/失败形状不同。**

实跑（`return_detail=True, return_loss=True`）：

```
成功：len=5, (True,          context:str, capacity:float, detail_info:list[dict], loss:list[dict])
失败：len=5, (False, str(e), 0,           {},                            {})
```

长度**碰巧**都是 5，但**类型完全不同**：

| 位置 | 成功时 | 失败时 | 是否同构 |
|---|---|---|---|
| 0 `is_success` | `True` | `False` | ✅ |
| 1 | 拼装的 `context: str`（含参数表 + 逐 cycle 容量文字） | `str(e)` 异常自由文本 | ❌ **语义不同**（一个是业务描述，一个是异常） |
| 2 `capacity` | `float`（实跑 5.0613） | **`0`（哨兵值）** | ❌ **与"真算出 0"不可分** |
| 3 `detail_info` | `list[dict]`（实跑） | **`{}`（dict）** | ❌ **类型不同** |
| 4 `loss` | `list[dict]` | **`{}`（dict）** | ❌ **类型不同** |

**当 `return_loss=False` 时**（成功 `:168-171`，失败 `:211-216`）：
```
成功：len=4  (True, context, capacity, detail_info)
失败：len=4  (False, str(e), 0, {})
```
**位置 3 分别是 `list[dict]` 与 `dict`** —— 与 `return_loss=True` 时的错位模式**又不一样**。

### 5.2 逐项对照用户要求的字段

| 要求字段 | 现状 |
|---|---|
| `status` | ⚠️ 只有位置 0 的 `bool`，**没有 status 枚举**（无 timeout / infeasible / convergence_failure 之分） |
| `time` | ⚠️ 不在返回值里。只在 `detail_info` 内部的嵌套 dict 里（实跑 `detail_info[0]['simulated']['Charge Constant Current']['voltage'|'time'...]`），**且没有 `current`/`capacity` 的同级统一字段名** |
| `voltage` | ⚠️ 同上，埋在 `detail_info` 的三层嵌套里 |
| `current` | ⚠️ 同上 |
| `capacity` | ⚠️ 只有**最后一个 cycle 的标量**（`:159-160`），**不是序列** |
| `termination_reason` | ❌ **完全不存在**。PyBaMM 的 `solution.termination` 从未被读取 |
| `diagnostics` | ❌ **完全不存在**作为结构字段；失败时是 `str(e)` 自由文本 |

### 5.3 用户明确要查的项

| 检查项 | 结论 |
|---|---|
| 是否还存在 tuple 返回 | ✅ **是**，`pybamm_runner.py:205` 与 `:218` `return tuple(parts)`；且 `build_simulation` 返回 `(sim, param)` 元组 |
| 成功 5 项、失败 3 项之类不一致 | ⚠️ **更隐蔽**：长度都是 5，但**位置 1/3/4 的类型与语义不同**。另外 `build_simulation` 的 `solve_simulation`（`:56-64`）失败时返回 **`(None, None)`** —— 另一套完全不同的形状 |
| 是否还使用 `capacity=0` / `None` 作失败标记 | ✅ **两个都用**：`capacity=0`（`:209`）；`solve_simulation` 用 `(None, None)`（`:64`） |
| exception 是否直接转成自由文本 | ✅ **是**：`:208` `print(f"An error occurred: {e}")` + `:209` `str(e)`。实跑失败样本的内容是 **`'list index out of range'`** —— 一个**完全无信息量**的异常（甚至不是仿真失败，是调用方 `ori_data` 不够长导致的索引越界） |
| `termination_reason` 是否结构化 | ❌ 不存在 |
| `diagnostics` 是否含 solver/model/parameter/protocol 错误 | ❌ 不存在。**失败时连是哪个环节失败都分不出**（实跑证明：仿真没失败，是参数校验失败，但对外只有 `'list index out of range'`） |
| t/V/I/Q 单位是否固定 | ❌ **无声明**。PyBaMM 内部单位是固定的（s / V / A / A·h），但**返回值里没有任何单位字段**，且 `detail_info` 的键名（`'voltage'` / `'time'` / `'current'`）连单位后缀都没有 |
| 电流正负号定义是否固定 | ❌ **没有固定定义**（见 §3：负号散落在 `utils/data.py:140`、`utils/exp.py:118`，各自决定） |

---

## 第六部分：Solver 与可复现性

| 检查项 | 现状 | 位置 |
|---|---|---|
| solver 类型 | `pybamm.CasadiSolver` | `pybamm_runner.py:46`、`:139`、`utils/data.py:134` |
| rtol | ❌ **未设置**（用 PyBaMM 默认 1e-6） | — |
| atol | ❌ **未设置**（用 PyBaMM 默认 1e-6） | — |
| `dt_max` | ✅ **写死 60** | `:46`、`:139`、`utils/data.py:134` |
| `max_step` | ❌ 未设置 | — |
| solver mode | ✅ **写死 `"safe"`** | `:46`、`:139`、`utils/data.py:134` |
| 是否写死 | ✅ **全部写死**，且**三处重复**，无配置项 | — |
| 是否记录进 provenance | ❌ **完全不记录**。`context` 只拼参数与容量，**没有任何 solver 设置**。代码快照（`pipeline.py:48-52` copytree）能间接溯源，但**无法知道"这次跑用的 dt_max 是多少"** | — |
| 相同 SimulationRequest 能否稳定复现同一结果 | ⚠️ **仿真部分确定（CasadiSolver 是确定性求解器）；但整条 Agent 链不可复现**：<br>① LLM 温度 `TEMPERATURE: 0.7` 非 0（`llm.yaml.example`）<br>② 无随机种子<br>③ `parse.vote_merge` 在多票时取**中位数**，票数不同结果不同<br>④ 两条 pipeline 都定义了 `start_time = time.time()`（`first_cycle_pipeline.py:63`、`degradation_pipeline.py:83`）但**从未使用**，无耗时记录 | — |

---

## 第七部分：测试运行结果（只运行，未修改）

```bash
# 环境：WSL Ubuntu / conda env `pybamm` / PyBaMM 26.8.0 / pytest 9.1.1
cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent
python -m pytest tests -q
```

**输出：**
```
...............................................                          [100%]
47 passed in 0.21s
```

| 项 | 结果 |
|---|---|
| 1. pytest 总数 | **47** |
| 2. passed / failed / skipped | **47 / 0 / 0** |
| 3. 每个失败测试对应模块 | **无失败** |
| 4. 是否有 golden regression test | ❌ **无**。没有任何"给定输入 → 固定期望输出"的回归基线 |
| 5. 是否有 contract/schema test | ✅ **有，且质量高**。`tests/test_contract.py`（329 行，38 项）+ `tests/test_pipeline_wiring.py`（120 行，9 项）。覆盖 ```json 围栏 / 缺 payload / 白名单外名字 / 越界值 / NaN·inf·bool·str / 重复参数 / 一个合法混一个非法（整体拒绝）/ 修复预算耗尽 / 多数票不过半，含 2 条**定义类测试**。**但**：管的是 **LLM 输出契约**，**不是 SimulationRequest/SimResult 契约** |
| 6. 是否有真实 SINTEF smoke test | ❌ **无**。且**本仓库不含 SINTEF 数据、不含 SINTEF 代码** |

**注意（环境相关）**：仓库声明 `pybamm==25.6.0`（README + requirements.txt），本机 env 是 **26.8.0**。测试**不需要 pybamm**（契约层是纯标准库，`test_pipeline_wiring.py` 刻意用源码级扫描避免 import），所以 47 passed **不能证明仿真路径在 26.8 上正确**。

**Windows 原生环境无法运行测试**：`C:\Users\24330\.workbuddy\binaries\python\versions\3.13.12\python.exe` 与 `miniconda3\python.exe` **都没有 pytest**。

---

## 第八部分：最小 smoke test（实跑）

### 8.1 选用的 case

`generate_simulated_data/output/simulated_data_setting_single_new_filtered.yaml` 的 `test_id=2`。

**选它的理由**：这是仓库里**唯一自包含**的路径——`ori_settings` 是 dict，所以不需要 LLM、不需要 `configs/llm.yaml`、不需要 `real_world_data/CALCE_CS2_33.pkl`（该目录在 `.gitignore` 中且本机不存在）。数据是 `load_simulated_battery_data` **现场用 PyBaMM 生成的**。

### 8.2 Agent 实际构造的等价 SimulationRequest

**注意：以下不是代码里的对象，是我从调用参数反推的等价描述。**

```yaml
model_name: "DFN"                 # 来源：yaml 条目 settings['model_name']
                                  # ※ 但模型 options 不由此唯一确定（见 §2.A）
param_set:  "Chen2020"            # 来源：yaml 条目 settings['param_name']
params:
  # --- 来自"实验数据"（其实是现场仿真的伪数据 settings['parameter_change']）---
  "Negative electrode thickness [m]": 6.39e-05     # source: yaml parameter_change
  # --- 来自硬编码 initial_params_for_first_cycle（params.py:37-65）---
  "Nominal cell capacity [A.h]": 1.1                # 覆盖 Chen2020 的 5.0
  "Electrode width [m]": 0.04                       # 覆盖 Chen2020 的 1.58  ← 40×
  "Negative/Positive electrode active material volume fraction": 0.61 / 0.62
  "Negative electrode thickness [m]": 7.65e-05      # ※ 被上面的 6.39e-05 覆盖
  "Positive electrode thickness [m]": 6.8e-05
  "Maximum concentration in negative/positive electrode [mol.m-3]": 28700 / 49943
  "Initial concentration in negative/positive electrode [mol.m-3]": 24108 / 21725
  "Negative/Positive electrode Bruggeman coefficient (electrode)": 0.0 / 0.0    # ← 0.0 可疑
  "Negative/Positive electrode Bruggeman coefficient (electrolyte)": 2.914 / 1.83
  "Separator Bruggeman coefficient (electrolyte)": 1.5
  "Separator porosity": 0.5
  "Separator thickness [m]": 2.5e-05
  "Negative/Positive electrode charge transfer coefficient": 0.5 / 0.5
  "Negative/Positive electrode conductivity [S.m-1]": 100.0 / 10.0
  "Negative/Positive electrode double-layer capacity [F.m-2]": 0.2 / 0.2
  "Negative/Positive electrode porosity": 0.33 / 0.32
  "Negative/Positive particle radius [m]": 5e-06 / 3e-06
protocol:
  # 由 make_cccv(charge_c_rate=0.2, charge_v_cut=4.2, discharge_c_rate=0.2,
  #              discharge_v_cut=2.5, cycle_len=2) 生成
  - "Rest for 1 second"
  - "Charge at 0.2C until 4.2 V"      # v_max 来自 Chen2020 Upper voltage cut-off
  - "Rest for 1 second"
  - "Hold at 4.2 V until C/20"
  - "Rest for 90 second"
  - "Discharge at 0.2C until 2.5 V"   # v_min 来自 Chen2020 Lower voltage cut-off
  - "Rest for 90 second"
  # × 2 cycles
```

**model_options（隐藏，未被 request 表达）**：
```yaml
"SEI": "reaction limited"
"SEI film resistance": "distributed"      # ← 与 configs/pybamm.yaml 的 "average" 不一致
# 其余全部落到 PyBaMM 默认
```

### 8.3 effective parameters（用户要求输出）

**无法完整输出。** 代码只暴露 `log_params`（`simulate_capacity:114`，仅 9 个结构参数）：

```python
{k: param[k] for k in search_keys if k in param}   # search_keys = pybamm_runner.SEARCH_KEYS 的 9 项
```

实测该字典**不包含**：被覆盖的初始浓度、c_max、Bruggeman、孔隙率、温度、导电率、双电层电容、particle radius（`particle radius` 在 9 项里但**只在 `if k in param` 成立时记录**）。
**且它只进 `context` 自由文本**，不落盘为结构化字段。

### 8.4 实跑 SimResult（原样输出）

```
ori_data cycles: 2
CAP_real (伪实验容量): 3.8084493834331288  A·h
SUCCESS:            True
SUCCESS_n:          5
CAP_sim:            5.061350913710094      A·h
LOSS: [{'Q_rmse': 1.2529015302769655,
        'Q_mape': 32.89794360211601,      # %
        'I_rmse': 0.8200386046665811,
        'I_mape': 35.98095208055279,
        'V_rmse': 1.698052925921233,
        'V_mape': 6.355783275302396}]
DETAIL_TYPE: list
DETAIL_KEYS: [{'cycle_idx': 1, 'simulated': {'Charge Constant Current': {'voltage': [...], ...}}}, ...]
```

### 8.5 值的来源分解（用户明确要求）

| 值 | 来源 | 是否人为默认 |
|---|---|---|
| `model_name = "DFN"` | yaml 条目（模拟数据设置） | ❌ 不算默认，但**options 的部分成员是默认** |
| `param_set = "Chen2020"` | yaml 条目 | 否 |
| `Negative electrode thickness = 6.39e-05` | yaml `parameter_change` | 否（但这是**仿真生成的伪数据**，不是实验） |
| 其余 21 个 params | **`params.py:37-65` 硬编码** | ✅ **是人为默认值**，无条件覆盖 Chen2020 |
| `Electrode width = 0.04` | `initial_params_for_first_cycle` | ✅ **是**，且与 Chen2020 的 1.58 **差 40×** |
| `Bruggeman coefficient (electrode) = 0.0` | `initial_params` | ✅ **是**。`0.0` 意味着 Bruggeman 修正**完全关闭**（有效传输率 = 1）—— 物理上可疑，且无注释说明 |
| `v_max = 4.2 V` / `v_min = 2.5 V` | **Chen2020 param_set** | ❌ 不是硬编码，但**是从参数集里"借"来的**，不是显式协议输入 |
| 协议 rest 时长 `1/1/90/90 s` | `utils/data.make_cccv` 写死 | ✅ **是** |
| solver `CasadiSolver(mode="safe", dt_max=60)` | `pybamm_runner.py:139` 写死 | ✅ **是** |
| `rtol` / `atol` | **未设置 → PyBaMM 默认 1e-6** | ✅ **是隐藏默认** |
| SEI options | `pybamm_runner.py:89-93` 写死 | ✅ **是隐藏默认** |

### 8.6 smoke test 的重要副产物：一个实证的物理错误

**`Q_mape = 32.9%`、`V_rmse = 1.70 V` —— 对一个"仿真 vs 仿真"（同一台求解器、同一个参数集，只有一个参数差）的对比，这个误差大得离谱。**

原因已定位：**`Electrode width` 被 `initial_params_for_first_cycle` 从 1.58 改成 0.04，面积从 0.1027 m² 变成 0.0026 m²（缩小 40×），同时 `Nominal cell capacity` 从 5.0 改成 1.1 A·h。** 这导致模拟容量 5.06 A·h 与目标 3.81 A·h 差 33%。

**关键点**：这个错误**不会报任何错**，会静默产出"看起来正常"的曲线和一组 loss 数字，然后**被当作有效反馈送进 LLM 的 prompt**（`first_cycle_pipeline.py:102` `cycle_description += context`）。

---

## 第九部分：老师明天试之前的审计报告

### A. 当前是否可以给老师试

# ❌ NOT READY

理由（三条独立、任一条都足以 NOT READY）：

1. **用户描述的 `SimulationRequest → SimResult` 契约在本仓库完全不存在**（`SimulationRequest`/`SimResult` 全仓 0 命中）。老师如果按这个契约验收，**会找不到任何对应的代码入口**。
2. **graphite‖Li 半电池路径在本仓库完全不存在**（`sintef`/`graphite`/`half.cell` 全仓 0 命中）。老师如果试半电池，**这个仓库不是入口**。
3. **真实数据路径必然崩溃**（`pybamm_configs['DFN']` 是 `KeyError`，见 P0-3），而模拟数据路径**静默产出物理错误的数字**（`Electrode width` 差 40×，Q_mape 32.9%，见 §8.6）。

### B. 阻断问题 P0

**P0-1｜`SimulationRequest` / `SimResult` 契约不存在**
- 文件：全仓（`grep -rn "SimulationRequest\|SimResult" --include=*.py/*.yaml/*.md` → 0）
- 影响：**输入输出契约失效**。导师 2026-09-12 给出的"契约骨架"在代码里没有任何对应实现。
- 需要的只是"对齐认知"：现状是 `simulate_capacity(...) -> tuple`，离冻结结构差"单一返回类型 + 结构化字段"这一整层。

**P0-2｜成功/失败返回结构不同构，且失败信息无诊断价值**
- 文件/行：`battery_agent/pybamm_runner.py:166-218`
- 证据：
  - 成功 `(True, context:str, capacity:float, detail_info:list, loss:list)`
  - 失败 `(False, str(e), 0, {}, {})` —— `detail_info` 从 `list` 变 `dict`，`loss` 从 `list` 变 `dict`，`capacity` 用 `0` 当哨兵
  - `solve_simulation`（`:56-64`）失败时是第三种形状 `(None, None)`
- 实跑：失败样本 `res[1] == 'list index out of range'`，`res[2] == 0`。**调用方无法区分"仿真失败"与"仿真算出 0"，也无法知道失败在哪个环节。**
- 影响：**输入输出契约失效** + 不可诊断。

**P0-3｜真实数据路径必然 `KeyError`**
- 文件/行：`battery_agent/pipeline/first_cycle_pipeline.py:53`、`degradation_pipeline.py:70`
- 代码：`model_name = pybamm_configs['DFN']`
- 问题：`configs/pybamm.yaml` 里**没有名为 `DFN` 的 key**（只有 `DEFAULT_PARAMS_SET` / `MODEL_NAME` / `MODEL_OPTIONS` / `SINGLE_CYCLE`），所以 `ori_settings is None`（即**真实数据路径**）时 `KeyError: 'DFN'`。
- 佐证：`configs/pybamm.yaml:11` 定义了 `MODEL_NAME: "DFN"`，但**没有任何代码读它** —— 说明这里本意是 `pybamm_configs['MODEL_NAME']`。
- 影响：**跑不起来**。

**P0-4｜半电池会用全电池协议（物理错误）**
- 文件/行：`battery_agent/pybamm_runner.py:121-131`（硬编码 `4.2 V` / `2.7 V`）、`:117-118`（从 param_set 取 v_max/v_min）、`configs/pybamm.yaml:1-8`
- 证据：`simulate_capacity` 的 `ori_settings` 非 dict 或 `experiment` 类型不对时，落到注释写着 `# default protocol for CALCE battery` 的硬编码段。**没有任何 half-cell 分支**。
- 影响：**结果物理错误**。石墨‖Li 用 4.2 V 上限会过充到锂沉积以外的电压区间。
- 另注：`build_simulation` 的默认 `experiment`（`:10-12` 读 `configs/pybamm.yaml`）是**另一套** 4.2 V 协议，两套并存。

**P0-5｜`initial_params_for_first_cycle` 无条件覆盖 param_set，且可静默改变几何面积 40×**
- 文件/行：`battery_agent/params.py:37-65`；注入点 `first_cycle_pipeline.py:54`、`degradation_pipeline.py:71`；生效点 `pybamm_runner.py:112`
- 实证：`Electrode width` 从 Chen2020 的 **1.58 m** 覆盖为 **0.04 m**（`:39`），`Nominal cell capacity` 从 **5.0** 覆盖为 **1.1 A·h**（`:38`）。**实测 Q_mape 32.9%**（§8.6）。
- 影响：**结果物理错误**（几何量级错），且**静默**——不报错，数字"看起来正常"，还会进 LLM prompt。

### C. 重要问题 P1

**P1-1｜`model_options` 不随 `model_name` 确定，且两套默认互相矛盾**
- `pybamm_runner.py:89-93`（`reaction limited` + `distributed` + 未设 porosity change → `false`）
- vs `pybamm_runner.py:14` → `configs/pybamm.yaml:12-20`（`reaction limited` + **`average`** + **`true`**）
- 同一个 `model_name` 走不同函数 → 不同物理模型。

**P1-2｜无单位校验、无参数名白名单**
- `pybamm_runner.py:112` `param.update(parameters)`
- 实测：传 `{"No such param [x]": 1.0}` → **不报错**（`param.update` 默认允许新键）。传 cm² 到 `[m]` 字段也不会被拦。
- 唯一的白名单是 `contract.SEARCH_KEYS`，**只管 LLM 输出的名字**，不管进入 PyBaMM 的名字。

**P1-3｜电流符号约定分散，无单一定义**
- 取负号处：`utils/data.py:140`、`utils/exp.py:118`；`utils/plot.py` 内部另有约定。
- 无单一符号定义处，无测试守护。half-cell 锂化/去锂化方向无处表达。

**P1-4｜solver 与容差写死、重复三处、不进 provenance**
- `pybamm_runner.py:46`、`:139`、`utils/data.py:134`
- `rtol`/`atol` **未设置**（隐藏默认 1e-6）；`dt_max=60`、`mode="safe"` 写死。
- `context` 里**无 solver 信息**，无法事后知道这次跑用的什么设置。

**P1-5｜`Prada2013`/`ORegan2022` 静默拼接 Chen2020 缺失键**
- `pybamm_runner.py:102-108`、`utils/data.py:118-124`
- 参数集变成并集，**provenance 无记录**。产物里看不出"这个值来自 Chen2020 而不是 Prada2013"。

**P1-6｜rest 时长两套不一致，且都写死**
- `utils/data.py:87-95`：`1 / 1 / 90 / 90 second`
- `configs/pybamm.yaml:1-8`：`120 / 120 / 90 / 90 seconds` + `Hold at 4.2 V until 50 mA`
- 不可配置、不一致、无记录。

**P1-7｜`effective parameters` 只记 9 项且不成结构化落盘**
- `pybamm_runner.py:114` `log_params = {k: param[k] for k in search_keys if k in param}`；`:155` 拼进 `context` 字符串
- 被覆盖的初始浓度、c_max、Bruggeman、温度、导电率等**全部不可见**。用户要求的"最终 effective parameters"**当前无法输出**。

**P1-8｜LLM 链不可复现**
- `TEMPERATURE: 0.7`（`llm.yaml.example`）；无随机种子；`vote_merge` 取中位数（`parse.py:211-213`）→ 票数变化即结果变化。
- 无 `llm.yaml` 时**两条 pipeline 都无法启动**（`utils/llm.py:37` 模块级 `get_configs("llm")`）。

**P1-9｜`Exponential/inf` 与 `0.0` Bruggeman 等可疑值无护栏**
- `params.py:48-49` `Bruggeman coefficient (electrode) = 0.0`（关闭修正）
- `contract.BOUNDS` 只覆盖 15 个标量键（`:81-99`），**`electrode Bruggeman` 不在其中**（只有 `electrolyte` 版在）。

### D. 次要问题 P2

- **P2-1**：README 未提到 `contract.py` / `parse.py` / `tests/` / `docs/BORROW_NOTES.md`，与真实仓库不一致。
- **P2-2**：声明 `pybamm==25.6.0`，本机 env 是 26.8.0，未在声明版本验证。
- **P2-3**：Windows 原生环境**无 pytest**（两个 python 都没有），只能在 WSL 跑。
- **P2-4**：`first_cycle_pipeline.py:63`、`degradation_pipeline.py:83` 的 `start_time = time.time()` **定义了从不使用**。
- **P2-5**：`utils/llm.py:202` `print('response_format', ...)`、`:129` `print(messages)` 等遗留调试 print；`utils/llm.py:281` `logger.info(f"[Info] LLM Messages: {messages}")` 会把完整 prompt 打进日志。
- **P2-6**：`utils/exp.py:202-244`、`utils/llm.py:371-407` 保留两组 DEPRECATED 死函数（已标注，但仍在文件里）。
- **P2-7**：`baseline/` 下 **6 份近乎重复的 `pybamm_runner.py`**，任何修复需要 ×6。
- **P2-8**：`build_simulation` / `solve_simulation`（`pybamm_runner.py:30-64`）在两条 pipeline 里**被 import 但从未调用**（`first_cycle_pipeline.py:13`、`degradation_pipeline.py:12`），是死路径。
- **P2-9**：`pipeline.py:16` `--multi_modal` 用 `type=bool`，命令行传 `--multi_modal False` 会被解析成 `True`（argparse 经典坑）。

### E. 已确认正常的部分

| 项 | 证据 |
|---|---|
| **契约层（LLM 输出）质量高** | `contract.py` + `parse.py`：单一 schema、白名单、值域、两种历史写法归一化、全有或全无校验、一次知情修复后抛错、代码侧严格多数合并。`docs/BORROW_NOTES.md` 记录了每一条的动机与原代码位置 |
| **47 项测试全绿** | `pytest tests -q` → `47 passed in 0.21s`，含 2 条定义类测试 |
| **无空转重试循环** | `test_no_retry_until_non_empty_loop_remains` 守护；两条 pipeline 均已删除 `while not param_groups_list` |
| **两套解析已统一** | `test_llm_module_routes_through_the_contract` 守护；`degradation` 不再错传 `mode="first_cycle"` |
| **渲染后的 prompt 落盘** | `first_cycle_pipeline.py:144`、`degradation_pipeline.py:173` `{"round":..., "rendered_prompt": messages}` |
| **每次实验自带代码快照** | `pipeline.py:48-52` `shutil.copytree` → `RESULTS_DIR/code/`。**这个习惯很好**，是本仓库最值得保留的工程实践 |
| **三模型 dispatch 表存在** | `pybamm_runner.py:94-98`，SPM/SPMe/DFN 三个 key 可查（实跑 DFN 成功） |
| **`make_cccv` 的 C-rate/截止电压是参数化的** | `utils/data.py:82-96` 接受 `charge_c_rate`/`v_cut` 等，`ori_settings` 路径下确实生效（实跑协议字符串正确反映 0.2C / 4.2 V / 2.5 V） |
| **smoke test 能跑通** | `test_id=2` 全链路无异常返回，`is_success=True`，detail/loss 均产出（实跑记录见 §8.4） |
| **`initial_params*` 的键全部存在于 Chen2020** | 实测 missing = 0，所以覆盖**不会**因未知键报错（问题在于值本身，见 P0-5） |

### F. 明天老师实际测试的推荐命令

**⚠️ 前置说明（必须先看，否则会白跑）**

1. 本仓库**没有** `SimulationRequest`/`SimResult`，也**没有** SINTEF/graphite 半电池代码。**老师若按那套契约验收，会找不到入口。**
2. 真实数据路径（`--test_id` 不传）**会崩溃**（P0-3）。**因此下面只给模拟数据路径。**
3. **必须先建 `battery_agent/configs/llm.yaml`**（`.gitignore` 忽略了它，本机不存在），否则 `utils/llm.py:37` 模块级 `get_configs("llm")` 直接 `FileNotFoundError`。
4. 仿真必须在 **WSL 的 `pybamm` conda env** 里跑（Windows 侧无 pybamm）。

**命令 1：证明契约层守得住（最稳，不依赖 pybamm / 不依赖 llm.yaml / 不需要网络）**

```bash
wsl.exe -d Ubuntu -e bash -lc 'cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && python -m pytest tests -q'
# 期望：47 passed in 0.21s
```

**命令 2：单 case 全链路（需要 llm.yaml + LLM 端点可达）**

```bash
# 先在 Windows 侧建配置（示例端点，按实际改）
cp battery_agent/configs/llm.yaml.example battery_agent/configs/llm.yaml

wsl.exe -d Ubuntu -e bash -lc 'cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && python battery_agent/pipeline.py --pipeline_name first_cycle_pipeline --test_id 2 --yaml_path ./generate_simulated_data/output/simulated_data_setting_single_new_filtered.yaml'
# 产物：./exp_results/single/2/<time_stamp>/（含 code/ 快照、exp.log、params.jsonl、all_messages.jsonl）
```

**命令 3：只验证 PyBaMM 仿真段，绕开 LLM（最接近"契约 smoke test"的可用形式）**

```bash
wsl.exe -d Ubuntu -e bash -lc 'cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent/battery_agent && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && python -c "
import yaml, matplotlib; matplotlib.use(\"Agg\")
from pybamm_runner import simulate_capacity
from utils.data import load_simulated_battery_data
st = yaml.safe_load(open(\"../generate_simulated_data/output/simulated_data_setting_single_new_filtered.yaml\"))[2]
ori = load_simulated_battery_data(st, cycle_len=2)
r = simulate_capacity({}, ori, param_name=st[\"param_name\"], model_name=st[\"model_name\"], cycle_idxs=[1], is_plot=False, is_save=False, save_dir=\".\", return_detail=True, return_loss=True, ori_settings=st)
print(\"success:\", r[0]); print(\"capacity:\", r[2]); print(\"loss:\", r[4])
"'
# 期望：success: True / capacity ≈ 5.061 / loss 里 Q_mape ≈ 32.9
# ※ 这个 32.9% 就是 P0-5 的现场证据，建议当着老师面看这一行
```

**不推荐、但 README 里有的命令**（会崩或需额外条件，列出来是为了说明为什么不能用）：

| README 命令 | 为什么不能用 |
|---|---|
| `python battery_agent/pipeline.py --pipeline_name first_cycle_pipeline --test_id 2`（省略 `--yaml_path`） | 默认 `yaml_path` 是 `./generate_simulated_data/output/simulated_data_setting_single_new_filtered.yaml`，**恰好存在**，所以这条能跑；但 `--test_id` 省略时为 `None` → `ori_settings=None` → **P0-3 KeyError** |
| `python battery_agent/pipeline.py --pipeline_name degradation_pipeline --test_id 1 --yaml_path .../simulated_data_setting_SEI.yaml` | `degradation_pipeline` 的 `loss` 是 `list[dict]`，但 `degradation_pipeline.py:133-134` 用 `loss[list_idx].items()` 迭代 —— 结构上有隐患，未实跑验证 |
| `bash script/run_first_cycle.sh` / `run_degradation.sh` | 脚本内容未核对；且同样需要 `llm.yaml` |
| `python run_exp.py --config ... --worker ./battery_agent/pipeline.py` | 依赖上面那条能跑通；且 `--max-proc` 缺省 = CPU 数，会并发起大量 PyBaMM 进程 |
| 任何 `baseline/*/` 命令 | 六个副本各自独立，未在本轮审计范围内 |

---

## 附：本轮审计的边界声明

- **只读**：未修改任何代码/配置/数据/测试文件。唯一写入的是本报告。
- **未执行**：未运行 LLM 调用（无 `llm.yaml`，也未配置端点）；未运行 `baseline/` 下任何代码。
- **未验证**：`pybamm==25.6.0`（声明版本）下的行为；`real_world_data/CALCE_CS2_33.pkl` 真实数据路径（文件不存在）；`Prada2013`/`ORegan2022` 参数集路径；`degradation_pipeline` 的完整轮次。
- **测试未修**：47 passed 全绿，无失败需要处理。
