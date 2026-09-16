# SimulationRequest → Simulator → SimResult 最小闭环：设计收敛版

- 日期：2026-09-12
- 状态：**设计收敛稿**（本轮不改任何代码）
- 取代：`docs/architecture/simulation_request_design.md`（其 monkey-patch 方案**作废**）
- 读者：明天要看 Agent 输入输出的导师

---

## 0. 三条口径先定死（后面所有数字都依赖它）

| 事项 | 结论 | 证据 |
|---|---|---|
| monkey patch 方案 | **取消**。改为平台侧显式参数覆盖入口 | 本稿 §B |
| `Electrode width [m] = 0.0368 / 0.04` | **P1 / `unknown_source`**，不判 bug，也不判"合理" | §B.0 |
| 当前唯一能对外演示的 SINTEF case | `pOCV-lith` + `sintef_graphite_ocp_lith_capmatch_v1`，**但必须走公开入口**；RMSE 44.64 mV 是**脚本内**结果 | §D / §E / §F |

---

## A. 修正后的最小架构

### A.1 数据流（三层，边界明确）

```
[实验侧]                          [Agent 侧]                       [平台侧 battery_sim]
                          ┌──────────────────────┐
  CSV / metadata  ──────► │  SimulationRequest   │
                          │  (冻结契约, §A.2)     │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  Simulator           │  ← 唯一新增胶水层
                          │  (bridge, §C.2)      │
                          └──────────┬───────────┘
                                     │ 只调公开入口
                                     │ run_baseline_cell(..., parameter_overrides=)
                          ┌──────────▼───────────┐
                          │ battery_sim baseline │  ← 平台，只加一个形参
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
  ◄────────────────────── │  SimResult           │
                          │  (冻结契约, §A.3)     │
                          └──────────────────────┘
```

**关键约束**：Agent 侧**不复制**任何仿真逻辑。`Simulator` 只做四件事——(1) 校验 request；
(2) 把 request 翻译成 `run_baseline_cell` 的实参；(3) 调它；(4) 把返回的 DataFrame
归一成 `SimResult`。所有 OCP / 浓度 / 初值 / 求解器语义**一律由平台决定**。

### A.2 `SimulationRequest`（冻结）

```python
@dataclass(frozen=True)
class SimulationRequest:
    model_name: str                       # "SPM" | "SPMe" | "DFN"
    param_set:  str                       # pybamm 参数集 id（可含运行时注册集）
    params:     dict[str, float] = {}     # 稀疏覆盖；空 = 完全继承 param_set
    protocol:   Protocol
    dataset_id: str | None = None         # 走"实验回放"时必须给
    cell:       str | None = None
    rate:       str | None = None
    initial_state: dict | None = None     # {"method": ..., ...}；None = 用 adapter 的
    overrides:  dict[str, float] = {}     # → 平台 parameter_overrides（见 §B）
```

**`params` vs `overrides` 的分工（重要，导师最容易问）**：

- `params` = **实验/材料侧**想改的物理量（电极厚度、面积、孔隙率、容量…）。来源必须是
  实验 metadata 或材料规格书，每条都要有 provenance。
- `overrides` = **Agent 侧**想试的假设（本轮**恒为空**）。
- 两者都空 → 纯继承。
- 两者合并后由 bridge 一次性交给 `parameter_overrides=`。
  合并顺序：`param_set` → `params` → `overrides`（后者覆盖前者），
  并在 `SimResult.diagnostics.effective_overrides` 里**逐条回显实际生效值**。

**协议**：

```python
@dataclass(frozen=True)
class Protocol:
    kind: str          # "experiment_replay"（实验数据回放）| "cc"（解析协议）
    # kind="experiment_replay"：协议完全由 (dataset_id, cell, rate) 的实验轨迹决定
    # kind="cc"：下面两个字段生效
    current_A:        float | None = None
    voltage_limits_V: tuple[float, float] | None = None
```

> 本轮**只实现 `experiment_replay`**。`cc` 字段占位、不实现、不测——避免"提了但没做"。

### A.3 `SimResult`（冻结，成功/失败**完全同构**）

```python
@dataclass(frozen=True)
class SimResult:
    status: str                   # "success" | "failure"
    trajectory: pd.DataFrame      # 恒定 schema，见下
    termination_reason: str       # 恒定非空字符串
    diagnostics: dict             # 恒定 dict，失败时也必须齐键

    # 恒定 schema：time_s float64, voltage_V float64,
    #             current_A float64, capacity_Ah float64
    # 失败时 = 0 行但列齐全的空表（dtype 不变）
```

**与现有 Agent 代码的差异（这是审计里 P0-2 的正解）**：

| | 现状 `pybamm_runner.simulate_capacity` | 本设计 `SimResult` |
|---|---|---|
| 成功 | `(True, context:str, capacity:float, detail:list, loss:list)` | 同一 dataclass |
| 失败 | `(False, str(e), 0, {}, {})` | **同一** dataclass |
| 失败时 capacity | `0` —— 与"真算出 0"**不可分** | 不设 capacity 标量；行数为 0 |
| `solve_simulation` | 失败 `return None, None`（第三种形状） | 不存在第三种 |

`termination_reason` 取值集合固定：
`"completed"` / `"voltage_limit_reached"` / `"solver_failure"` / `"adapter_error"` /
`"contract_violation"`。**没有空字符串、没有 None**。

`diagnostics` 恒定键（失败时值为 None / 空 dict，键不缺席）：
`dataset_id, cell, rate, model_name, param_set, effective_overrides,
n_points, rmse_time_aligned_mV, mae_time_aligned_mV, bias_time_aligned_mV,
initial_method, initial_state, runtime_s, source_files`

---

## B. 平台侧最小 additive 修改

### B.0 `Electrode width` 复核结论（用户 3 次要求，最终口径）

**结论：P1，标记 `unknown_source`。既不判 bug，也不判"合理"。**

查到的**全部**事实：

1. **首次进入位置**：`battery_agent/params.py`。
   - `initial_params_for_first_cycle`（27 键）：`'Electrode width [m]': 0.04`
   - `initial_params`（10 键）：`"Electrode width [m]": 0.0368`
   - 第 67 行有一条**被注释掉**的搜索界：`"Electrode width [m]": (0.01, 2.0)`
2. **`initial_params_for_first_cycle` 的谱系可定**：与 PyBaMM `Ai2020` 逐键比对，
   **27 键中 25 键完全一致**（厚度 7.65e-05 / 6.8e-05、体积分数 0.61 / 0.62、
   颗粒半径 5e-06 / 3e-06 等）。**仅 2 键被改**：
   - `Nominal cell capacity` 2.28 → **1.1**（= CALCE CS2 的容量）
   - `Electrode width` 0.047 → **0.04**
   → 即：这是 **Ai2020 参数集被手工改了 2 个值**，改的人是谁、依据什么，
     **仓库里没有任何记录**。
3. **`initial_params`（10 键）无谱系**：与 `Ai2020` / `Ramadass2004` / `Chen2020`
   逐键比对，命中 **0/10 / 0/10 / 0/10**。**无来源**。
4. **Ai2020 自身的几何是** `width 0.047 m × height 0.051 m = 23.97 cm²`。
   所以"0.04 m 是卷绕长度、不能和 Chen2020 的 1.58 m 比"这个我上一轮的说法
   **是错的**：Ai2020 不是卷绕电池，`width` 和 `height` 是同一量纲的两个边。
5. **没有 git 历史**：Agent 仓库**没有 `.git`**（`ls .git` → No such file）。
   上游 commit 记录、blame、PR 讨论**全部不可得**。
6. **与 SINTEF 无关**：SINTEF graphite R2032 是 14 mm 圆片 ≈ **1.5394 cm²**；
   `0.04 × 0.065 = 26 cm²` 显然不是这颗电池的电极面积。
   → **绝不能把这两个值回填进 SINTEF 线派生出的任何参数集**（用户红线）。

**为什么保持 P1 而不是 P0**：目前**没有任何一处代码路径**真的把这个值送进一次
成功求解并产出结论（`first_cycle_pipeline` 在 `pybamm_configs['DFN']` 就 KeyError
挂了，见审计报告 §I）。所以它不构成"已发生的错误结果"，只是**未溯源的高风险常量**。

**为什么不判"合理"**：用户明确要求——
> 不要根据搜索范围或数值量级推断其正确。

搜索界 `(0.01, 2.0)` 是**被注释掉的**，不构成设计意图的证据；数值量级 0.04 m
在 0.01–2.0 内也不能证明单位对。**在找到 provenance 之前，唯一诚实的标记是
`unknown_source`。**

**建议动作（不属本轮）**：问导师这个值来自哪篇文献/哪份数据；或直接废弃
`initial_params*`，让 Agent 只接受实验 metadata 提供的几何。

### B.1 需要改的位置与行数

**唯一改动点：`battery_sim/simulation/baseline.py`，2 处，合计约 14 行。**

#### 改动 1 —— `_run_one_replay` 增加形参（第 95–100 行区）

```python
def _run_one_replay(
    df: pd.DataFrame,
    model_name: str,
    parameter_set: str,
    model_options: Optional[dict] = None,
    parameter_overrides: Optional[dict] = None,   # ← 新增 1 行
) -> dict:
```

#### 改动 2 —— 在 `params = load_parameter_values(parameter_set)`（第 123 行）之后，
把覆盖应用上去（新增约 13 行）

```python
    params = load_parameter_values(parameter_set)

    # ---- additive: explicit parameter override path ----
    # Applied AFTER the set is loaded and BEFORE any temperature /
    # current / initial-concentration logic, so that downstream code
    # sees one single effective ParameterValues object.
    applied_overrides: list = []
    if parameter_overrides:
        unknown = [k for k in parameter_overrides if k not in params]
        if unknown:
            raise KeyError(
                f"parameter_overrides: keys not in parameter set "
                f"'{parameter_set}': {sorted(unknown)}"
            )
        for key, value in parameter_overrides.items():
            applied_overrides.append(
                {"key": key, "old": params[key], "new": value}
            )
            params[key] = value
    # ---- end additive ----
```

然后把 `applied_overrides` 挂进返回 dict（与既有 `_mapping_rows` 同样方式，
第 ~395 行区新增 1 行 `"_applied_overrides": applied_overrides or None,`）。

#### 改动 3 —— `run_baseline_cell` 透传（第 406–414 行 + 490 行）

```python
def run_baseline_cell(
    adapter,
    model_name: str,
    cell: str,
    rate: Optional[str] = None,
    parameter_set: Optional[str] = None,
    plot: bool = True,
    quiet: bool = False,
    parameter_overrides: Optional[dict] = None,   # ← 新增 1 行
) -> dict:
```

调用处（第 490 行）新增 1 行 `parameter_overrides=parameter_overrides,`。

### B.2 改动量的诚实说明

| 位置 | 行数 |
|---|---|
| `_run_one_replay` 签名 | 1 |
| 覆盖应用块（含 KeyError 校验） | 13 |
| 返回值多一个键 | 1 |
| `run_baseline_cell` 签名 | 1+1 |
| 调用点透传 | 1 |
| **`baseline.py` 合计** | **约 18 行** |

**但"平台侧"不止 `baseline.py`**，诚实列全：

| 文件 | 性质 | 行数 |
|---|---|---|
| `battery_sim/simulation/baseline.py` | 新增形参 + 覆盖逻辑 | ~18 |
| `tests/test_parameter_overrides.py` | **新增**测试文件 | ~70 |
| **合计** | | **~88 行** |

**不需要改**：`run_pipeline.py` / `runner` / `evaluator` / `factory` / `registry` /
`rates.py` / `paths.py` / `configs/*.yaml` / 任何 adapter。

**为什么这是 additive 而不是改行为**：

- 默认 `parameter_overrides=None` → `if parameter_overrides:` 为假 → **零行为变化**。
- 现有的 `run_pipeline.py baseline` 与 288 项门值测试**全部不受影响**（可回归验证）。
- 覆盖**不做静默兜底**：键不在参数集里就 `KeyError`（不猜、不忽略、不新建键）。
- 覆盖**必须可见**：`_applied_overrides` 逐条回显 `old → new`，
  写进 CSV 元数据与 `SimResult.diagnostics`。

**契约测试（4 条，写进 `tests/test_parameter_overrides.py`）**：

1. `parameter_overrides=None` 与不传该参数 → `_run_one_replay` 返回**逐元素相同**的结果
   （保行为不变）。
2. 覆盖一个已存在的键 → 返回的 `_applied_overrides` 里 `old != new`，且
   `params[key] == new`。
3. 覆盖一个不存在的键 → `KeyError`，消息里含该键名。
4. **定义类测试**：覆盖 `Nominal cell capacity [A.h]` 后，
   `params["Nominal cell capacity [A.h]"]` 的读回值必须**等于**传入值
   （防"传了但没生效"）。这条是"列存在/有限"抓不到的那类检查。

---

## C. Agent 侧最小修改

### C.1 压缩前后对比（用户要求重估）

| 上一版（6 文件 / ~660 行） | 收敛版（4 文件 / ~250 行） |
|---|---|
| `schema.py` + `validators.py` + `simulator.py` + `adapter.py` + `golden.py` + 测试 | `contract.py` + `simulator.py` + 测试 |

**删除的东西及理由**：
- 独立 `validators.py` → 合并进 `contract.py`。校验规则不足以独立成模块。
- `adapter.py`（实验数据适配）→ **完全删除**。实验数据的读取是**平台 adapter 的职责**
  （`get_dataset(dataset_id).load_processed_discharge`），Agent 侧再包一层就是复制逻辑。
- 独立 `golden.py` → 改成测试里的常量（见 §D/§E）。它只是数据，不是模块。

### C.2 四个文件

#### 文件 1（新增）`battery_agent/sim_contract.py` — ~110 行

`SimulationRequest` / `Protocol` / `SimResult` 三个 dataclass；
`TERMINATION_REASONS` 常量；
`SimResult.empty_failure(reason, diagnostics)` 构造器（保证失败路径也齐列齐键）；
`validate_request(req) -> list[str]`（纯校验，返回错误列表，不抛）。

**必须点名 `model_name` 白名单**：`{"SPM", "SPMe", "DFN"}`。现状是裸
`models[model_name]` → `KeyError`，消息里没有可用信息。

#### 文件 2（新增）`battery_agent/simulator.py` — ~90 行

```python
def simulate(request: SimulationRequest) -> SimResult:
    """唯一入口。Agent 侧不实现任何仿真语义。"""
```

职责：
1. `validate_request` 失败 → `SimResult.empty_failure("contract_violation", ...)`。
2. 走**平台公开入口**拿到 adapter：
   `from battery_sim.registry import get_dataset`。
3. 合并 `params | overrides` → `parameter_overrides`。
4. `run_baseline_cell(adapter, model_name=..., cell=..., rate=...,
   parameter_set=req.param_set, plot=False, quiet=True,
   parameter_overrides=merged or None)`。
5. 读输出 CSV → 归一成恒定 schema 的 `trajectory`；
   从返回 dict 的 `_applied_overrides` 取 `effective_overrides`。
6. 异常 → `SimResult.empty_failure("solver_failure" / "adapter_error", ...)`。

**注意（导师会问）**：`run_baseline_cell` 目前**返回的是 dict**（`output_dir` /
`metrics` DataFrame / `runtime_s`），轨迹在它写出的 CSV 里。
本轮**不要求平台改这个返回结构**——bridge 从 `output_dir` 读
`{rate_slug}_time_aligned.csv`（列 `time_s, voltage_exp_V, voltage_sim_V, residual_V`），
重命名并补 `current_A` / `capacity_Ah`。
**这是一个已知的不优雅**，明确记录为后续项，不在本轮修。

#### 文件 3（新增）`tests/test_sim_contract.py` — ~30 行

- `SimResult.empty_failure` 的列名/dtype 与成功时**逐列相同**（同构性测试）。
- `validate_request` 拒绝未知 `model_name`、空 `param_set`、`experiment_replay`
  却缺 `dataset_id`。

#### 文件 4（新增）`tests/test_simulator_smoke.py` — ~20 行

Case A + Case B（见 §D / §E）。**需要在 WSL pybamm env 下跑**（Windows 无 pybaMM）。

**合计 Agent 侧：约 250 行。**

---

## D. Case A —— 纯继承（`params: {}`）

```python
SimulationRequest(
    model_name="SPM",
    param_set="sintef_graphite_ocp_lith_capmatch_v1",
    params={},                      # 空 = 完全继承
    protocol=Protocol(kind="experiment_replay"),
    dataset_id="sintef_graphite", cell="4ccc47", rate="pOCV-lith",
    initial_state=None,             # 用 adapter 自己的 initialisation
)
```

**前置条件（必须写进测试，否则跑不通）**：
`param_set` 是**运行时注册集**，必须在 import 后先注册：

```python
from parameters import register_variants, register_capacity_variants, register
register_variants(); register_capacity_variants(); register()
```

（已实测：注册前 `in pybamm.parameter_sets` 为 `False`，注册后为 `True`。）

**期望 golden 结果**（来自 `outputs/analysis/graphite_phaseB05/residual_summary.json`，
`windows.lith.B0p5_capmatch`）：

| 字段 | 期望值 |
|---|---|
| `status` | `"success"` |
| `termination_reason` | 非空字符串（允许 `voltage_limit_reached`，该窗 coverage 0.9893） |
| `n_points` | 与平台 CSV 行数一致 |
| `rmse_time_aligned_mV` | **44.64** |
| `mae_time_aligned_mV` | **3.20** |
| `bias_time_aligned_mV` | **-3.20** |
| `diagnostics.effective_overrides` | **空**（证明"没传覆盖 = 真没覆盖"） |
| `diagnostics.initial_method` | `"fixed_initial_concentration"` |
| `diagnostics.initial_state.x0` | **0.001**（`clamped_to_table_edge=True`） |

> **Case A 的证明目标**：`params={}` 时，Agent 没有往参数里塞任何私货，
> 而模型仍然跑出与平台脚本一致的结果。这是"继承是对的"的**唯一**证据。

---

## E. Case B —— 单标量覆盖（证明覆盖真的生效）

从 SINTEF metadata 里挑**provenance 清楚**的量。首选
**`Positive electrode thickness [m] = 6.4e-05`（64 µm，实测）**。

理由：它是 SINTEF 元数据直接给的量（配 `external/` 里的材料表），
不是从别处借的；且它**不在** capmatch 集新改的那几个键里，覆盖它不会和
容量一致化打架。

```python
SimulationRequest(
    model_name="SPM",
    param_set="sintef_graphite_ocp_lith_capmatch_v1",
    params={"Positive electrode thickness [m]": 6.4e-05},   # 幂等覆盖
    protocol=Protocol(kind="experiment_replay"),
    dataset_id="sintef_graphite", cell="4ccc47", rate="pOCV-lith",
)
```

**这里有个诚实问题，必须说清**：capmatch 集**本身就已经是** 6.4e-05
（实测值 `thick:6.4e-05`）。所以"覆盖前 6.4e-05 → 覆盖后 6.4e-05"**值不变**，
证明不了"求解器用了覆盖值"。

**因此 Case B 必须用两段式，而不是单跑一次**：

**B-1（证明覆盖真的改变结果）**：覆盖成**明显不同的值**，
例如 `{"Positive electrode thickness [m]": 1.2e-04}`（64 µm → 120 µm）。
期望：
- `diagnostics.effective_overrides[0]` 里 `old == 6.4e-05`、`new == 1.2e-04`；
- `rmse_time_aligned_mV != 44.64`（**必须不同**）；
- `Q_model` 随之改变（厚度进入 `Q_model = eps_am·L·A·c_max·F/3600`）。

**B-2（证明"幂等覆盖也不炸"）**：覆盖成 6.4e-05 本身。
期望 `effective_overrides` 里 `old == new == 6.4e-05`，
且 RMSE **逐位等于** Case A 的 44.64 mV。

> 这才是"证明覆盖生效"的完整逻辑：B-1 证明覆盖**有作用**，
> B-2 证明覆盖**无副作用**。只跑 B-2 是自欺。

**红线**：B-1 的 120 µm 是**为了测试机制**而设的人造值，
**不是** SINTEF 的物理参数，**不得**写进任何结论、报告或参数集。

---

## F. 导师明天实际要跑的那一条命令

**决策依据**：`run_pipeline.py` **没有** `--parameter-set` 覆盖参数
（它只读 `cfg.parameter_set`）。所以：

- 若想让导师跑**平台原生**命令，只能得到 `Ecker2015_graphite_halfcell`
  → `pOCV-lith` 实测 RMSE **875.75 mV**。这**只是链路连通性证明，不是精度证明**。
- 44.64 mV 这个数目前**只在 B0.5 相位脚本内部**产出
  （`run_baseline_cell(..., parameter_set=<capmatch>)` 是脚本直接传的）。

### 因此，给导师的**唯一**命令是 Agent 侧的一个演示脚本：

```bash
wsl.exe -d Ubuntu -e bash -lc \
  'cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent && \
   source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && \
   export PYTHONPATH=/mnt/c/Users/24330/WorkBuddy/仿真模拟:$PYTHONPATH && \
   python demo_simrequest.py'
```

`demo_simrequest.py`（Agent 仓库根，~50 行）做三件事，全部打印：

1. **Case A**：`params={}` → 打印 `status / termination_reason /
   n_points / rmse / mae / effective_overrides(=[])`。
2. **Case B-1**：覆盖厚度 120 µm → 打印同组字段 + `effective_overrides` 的
   `old → new`，并打印 `RMSE_A != RMSE_B1`。
3. **Case B-2**：覆盖厚度 64 µm → 打印 `RMSE_B2 == RMSE_A`（逐位）。

**并且打印失败路径**：故意传 `model_name="XYZ"` →
打印 `status="failure"`、`termination_reason="contract_violation"`、
`trajectory` 的**列名与空行数**，让导师看到成功/失败**同构**。

### 必须同时给导师的**免责声明**（写进脚本输出头部，不藏）

> - 44.64 mV 是 **zero-fit 参考回放**在**容量一致化**参数集下的结果，
>   **不是**模型对该石墨的验证（B0.5 原文明确：surrogate ≠ validation）。
> - Agent 仓库**当前没有任何可跑通真实数据的公开入口**：真实数据路径在
>   `first_cycle_pipeline`/`degradation_pipeline` 的 `pybamm_configs['DFN']`
>   处 `KeyError` 崩溃（`pybamm.yaml` 无 `DFN` 键）。
> - Agent 侧新增的只是**契约 + 桥**，仿真能力**全部**来自 `battery_sim`。

---

## G. 改动文件与代码量估算

| # | 文件 | 仓库 | 动作 | 行数 |
|---|---|---|---|---|
| 1 | `battery_sim/simulation/baseline.py` | 平台 | 改（additive） | ~18 |
| 2 | `tests/test_parameter_overrides.py` | 平台 | 新增 | ~70 |
| 3 | `battery_agent/sim_contract.py` | Agent | 新增 | ~110 |
| 4 | `battery_agent/simulator.py` | Agent | 新增 | ~90 |
| 5 | `tests/test_sim_contract.py` | Agent | 新增 | ~30 |
| 6 | `tests/test_simulator_smoke.py` | Agent | 新增 | ~20 |
| 7 | `demo_simrequest.py` | Agent | 新增（演示用） | ~50 |
| | **合计** | | | **~390** |

**平台侧净增 ~88 行，其中 `baseline.py` 本体仅 ~18 行，且默认路径零行为变化。**
（上一版估计 660 行 → 收敛到 390 行，主要是删掉重复的实验数据适配层与独立校验模块。）

**不做（用户明确排除）**：大重构 / LLM 参数寻优 / GITT Ds 自动拟合 /
新模型 / UI / README 美化 / `run_baseline_cell` 返回结构调整。

---

## 附：本轮为验证以上判断而跑的只读探测

| 探测 | 结论 |
|---|---|
| `scripts/dev/probe_registration.py` | 运行时注册生效：`BEFORE:False` → `AFTER:True`；几何 `H×W=1.5394 cm²`、`thick=6.4e-05`、`Qnom=1.9424659e-03`、`c_max=31920` |
| `scripts/dev/probe_case_b.py` | 三个 case 的 RMSE 与 B0.5 冻结报告**不一致**，原因见下 |
| 读 `scripts/graphite_phase_b05_compare.py` | 找到不一致的**根因**（见下） |

**RMSE 不一致的根因（已定位，不是 bug）**：
B0.5 脚本对 `use_proxy=True` 的变体改用 `OCPConsistentAdapter`，
它在**该变体自己的 OCP 表上**做逆 OCP 求 `x0`，并施加
`X0_MARGIN` 裁剪：lithiation 的 `x0` 被裁到 **0.001**
（`clamped_to_table_edge=True`，`x0_before_margin=0.0`）；
delithiation 裁到 **0.999**（`x0_before_margin=1.0`）。
我的 `probe_case_b.py` **直接传了 platform adapter**，没走 proxy，
所以初值不同 → RMSE 不同（287.24 vs 6.27 等）。
**两条都对，但只有走 proxy 的那条与 B0.5 报告可比。**
→ 这同时说明：**初值策略是 B0.5 结论的组成部分，不能被 bridge 丢掉。**
本设计因此把 `initial_state` 留成显式字段（§A.2），并规定 demo 脚本必须
复现 B0.5 的 proxy 语义，否则 44.64 mV 无法复现。
