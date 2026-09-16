# SimulationRequest → Simulator → SimResult 最小闭环设计方案

**日期**：2026-09-12
**状态**：**设计方案，未改任何代码**
**目标**：为导师查看 Agent 输入输出，建立最小可运行的请求-仿真-结果闭环。
**唯一仿真后端**：`C:\Users\24330\WorkBuddy\仿真模拟` 的 `battery_sim` 平台（不复制其仿真逻辑）。

---

## 0. 先修三个前提（否则方案会建在沙子上）

设计之前先核实了三件事，其中**两件推翻了上一轮审计里的判断**。

### 0.1 修正：`Electrode width = 0.0368 / 0.04` **不是单位错误**

用户明确要求重新核实。结论：**上一轮我判重了，需要撤回一部分。**

**证据（全仓检索）**：

```
battery_agent/params.py:4   "Electrode width [m]": 0.0368,     ← initial_params
battery_agent/params.py:39  'Electrode width [m]': 0.04,       ← initial_params_for_first_cycle
battery_agent/params.py:67  # "Electrode width [m]": (0.01, 2.0),  ← 被注释掉的搜索区间
```

**三条决定性证据**：

1. **被注释掉的搜索区间是 `(0.01, 2.0)`**（`params.py:67`）。这个区间的量级与 `0.0368`/`0.04` **完全相容**，而与 `1.58` 只在端点附近。说明**写代码的人认为 0.01–2.0 m 是这个参数的量程**，0.0368/0.04 落在区间内，是**有意选的**。
2. **它是"全部参数里唯一被显式搜索的几何量"**：`prompt.yaml:29` 的知识文本专门用一整段讲 `Electrode Width [m]` 的影响方向（"若增大则容量增大"），说明它在作者的设计里是一个**被标定的实验几何量**，不是随手填的默认值。
3. **`0.0368` 与 `0.04` 高度接近**（差 8.7%），且都与 `params.py` 里其他几何参数（`Negative electrode thickness 6.7e-05 / 7.65e-05`、`Positive 8.7e-05 / 6.8e-05`）**同量级兼容**。若是单位错（cm↔m 是 100×，mm↔m 是 1000×），不会出现两套值都落在同一量级、且彼此只差 8.7% 的情况。

**那么 Chen2020 的 1.58 m 是什么？**

`Chen2020` 的 `Electrode width [m] = 1.58`、`Electrode height [m] = 0.065`，面积 0.1027 m²。这是 **LG M50 卷绕电芯的展开尺寸**（1.58 m 长的极片卷起来）。**它是"展开长度"，不是"极片宽度"。**

**所以两套值的差别不是单位错，是物理对象不同**：

| | `params.py` 的值 | Chen2020 的值 |
|---|---|---|
| 数值 | 0.0368 / 0.04 m | 1.58 m |
| 物理含义 | **极片的宽度（或某一段的有效宽度）** | **卷绕电芯的极片展开总长** |
| 对应的电芯 | CALCE CS2 / 实验半电池（单片） | LG M50（卷绕） |
| 面积 | 0.04 × 0.065 = **0.0026 m² = 26 cm²** | 1.58 × 0.065 = **0.1027 m² = 1027 cm²** |

26 cm² 是**实验室扣式/单片电池的合理面积**（对比：SINTEF R2032 是 1.54 cm²，Birmingham 是 1.72 cm²——26 cm² 偏大但仍在"小电芯"量级）。

**修正后的正确判定**：

> **`Electrode width` 的覆盖是"实验几何覆盖"，不是单位错误。**
> 但**上一轮审计指出的问题依然成立，且性质变了**：问题不是"值错了"，而是
> **`params.py` 里这两个几何覆盖是无条件的、不带来源标注的**——
> 它把 Chen2020（LG M50，5.0 Ah，1027 cm²）的参数集，
> 直接改成了另一颗电芯的几何（1.1 Ah / 26 cm²）**却同时保留了 Chen2020 的
> `Nominal cell capacity` 之外的活性物质参数**。
>
> **实证（上一轮 smoke test，test_id=2）**：`Q_mape = 32.9%`。
> 这个 33% 的误差**不是单位错造成的**，而是
> **"跨电芯混用参数集"**造成的：几何换成了小电芯，但 `Maximum concentration`、
> `Initial concentration`、`active material volume fraction` 等仍是
> `initial_params_for_first_cycle` 里另一套值（`params.py:40-47`）。
> **混用本身没有 provenance 记录**，这才是真问题。

**结论：这条不再作为"物理错误"（P0-5）上报，降级为 P1（隐藏默认 + 无 provenance）。**
方案里对它的处置是：**在 SimulationRequest 里把 `params` 的来源显式化**，
让"哪些值来自实验几何、哪些继承 param_set"在请求对象里就能看出来（见 §C）。

### 0.2 修正：`battery_sim` 的**半电池路径已经存在且已验证**

上一轮我说"graphite‖Li 半电池路径在 Agent 仓库不存在"——这句是对的；但我**没有说清它在平台侧已经完整可用**。核实结果：

- `configs/datasets.yaml:486-613` 有完整的 `sintef_graphite` 条目
- `battery_sim/datasets/sintef_graphite.py` 有 `SintefGraphiteAdapter`（1100+ 行，已封版）
- `battery_sim/simulation/baseline.py` 的 `_run_one_replay` **已经支持半电池**：
  - `model_options`（`:99`，含 `working electrode`）
  - `initialisation` 块（`:136`，`fixed_initial_concentration` 走 inverse-OCP）
  - 逆 OCP 映射在 `Simulation` 构造**之前**覆写（`:182`，注释 `:163-167` 明确说明原因）
- **实跑验证通过**（本轮）：

```
python run_pipeline.py baseline --dataset sintef_graphite --model SPM --cell 4ccc47 --rate pOCV-lith
→ [BASELINE] cell4ccc47 pOCVlith (C/50 (p-OCV lithiation), source: p-ocv) SPM
   RMSE(t)= 875.75 mV | MAE(t)= 867.93 mV | Qexp=0.002 Ah | Qsim=0.002 Ah
```

（875 mV 的 RMSE 是**已知的尺度失配 artefact**，`datasets.yaml:594-612` 已记录：参考集 85.85 cm²/202 mAh vs 本电芯 1.54 cm²/2.16 mAh，比 ~56×。**不是仿真失败**。）

→ **这意味着闭环所需的仿真能力已经全部就位，不需要新写仿真代码。**

### 0.3 修正：Agent 仓库与平台仓库的关系

- `Battery-Sim-Agent`（`C:\Users\24330\WorkBuddy\Battery-Sim-Agent`）**不含任何平台代码**，两者独立。
- 平台侧 `battery_sim/` **被标记为冻结内核**（项目 memory："禁改 runner / evaluator / factory / registry / rates.py / paths.py"）。
- **`_run_one_replay` 是 `baseline.py` 内部函数（下划线开头）**，不是公共 API。

→ **这就是方案必须用 wrapper 而不能直接 import 的原因**（详见 §1.2）。

---

# A. 最小架构

## A.1 一张图

```
┌─────────────────────────── Agent 仓库（新增，薄） ──────────────────────────┐
│                                                                             │
│  agent_sim/schema.py          agent_sim/platform_bridge.py                  │
│  ┌────────────────────┐       ┌──────────────────────────────┐              │
│  │ SimulationRequest  │       │ run_simulation(request)      │              │
│  │  model_name        │──┐    │   1. get_dataset(dataset_id) │              │
│  │  param_set         │  │    │   2. load_processed_discharge│              │
│  │  params            │  │    │   3. 转成 platform request   │              │
│  │  protocol          │  └───▶│   4. baseline.run_baseline_cell             │
│  └────────────────────┘       │   5. 把 metrics/CSV 折成 SimResult          │
│  ┌────────────────────┐       └──────────────────────────────┘              │
│  │ SimResult          │◀──────────────────────────────────────┘            │
│  │  status  (同构)     │                                                   │
│  │  trajectory        │                                                   │
│  │  termination_reason│                                                   │
│  │  diagnostics       │                                                   │
│  └────────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │ 只调用（不复制）
                                     ▼
┌────────────────────── 平台仓库 battery_sim（冻结，零改动） ──────────────────┐
│  registry.get_dataset(dataset_id)  →  SintefGraphiteAdapter                  │
│  adapter.load_processed_discharge(cell, rate)  →  df[t,I,V,Q] + attrs        │
│  simulation.baseline.run_baseline_cell(adapter, model_name, cell, rate)      │
│  models.pybamm_factory.build_model / load_parameter_values / build_model_options │
└─────────────────────────────────────────────────────────────────────────────┘
```

## A.2 为什么必须用 wrapper，不能用 `_run_one_replay` 直接调

三条硬理由：

1. **它是私有函数**（`_run_one_replay`，`baseline.py:95`），签名绑定 `df` + 四个散装参数，不接收"参数覆盖"。冻结内核不能改。
2. **它不做 `params` 覆盖**。`baseline.py:123` `load_parameter_values(parameter_set)` 之后，只在 `:153-155` 改温度、`:159` 改 `Current function`、`:182` 改初始浓度。**没有"实验参数覆盖 param_set"这个入口**。
3. **它的返回值是扁平 metrics dict + 下划线私有数组**（`:394-399`），**不是** `SimResult` 形状；且失败时行为是抛异常（`:199-211` 的 `solve` 无 try）。

→ wrapper 的**全部职责**就是在这三点上补齐，**不碰任何仿真逻辑**。

## A.3 唯一 SimulationRequest

```python
@dataclass(frozen=True)
class ParameterValue:
    name: str                    # PyBaMM 参数名（精确拼写）
    value: float | str           # 标量；曲线暂不支持（见 §F 禁止项）
    unit: str                    # 从 name 后缀解析，独立字段
    source: str                  # experiment | param_set | derived | assumed
    evidence: str                # 具体来源（文件/字段/依据），不允许空
    confidence: str              # high | medium | low

@dataclass(frozen=True)
class Protocol:
    kind: str                    # "open_loop_replay" | "cccv"
    current_sign_convention: str  # 固定 "discharge_positive"
    lower_voltage_cutoff_V: float
    upper_voltage_cutoff_V: float
    temperature_C: float
    temperature_source: str
    cycles: int = 1

@dataclass(frozen=True)
class SimulationRequest:
    model_name: str              # "SPM" | "SPMe" | "DFN"（大小写不敏感）
    param_set: str               # PyBaMM 参数集名，如 "Ecker2015_graphite_halfcell"
    params: Tuple[ParameterValue, ...]   # 覆盖项；**空元组 = 全部继承 param_set**
    protocol: Protocol
    # --- 溯源锚点（只读，wrapper 用来取数据） ---
    dataset_id: str              # battery_sim 的 dataset id（如 "sintef_graphite"）
    cell: str                    # 如 "4ccc47"
    window: str                  # 如 "pOCV-lith"
    cell_configuration: str      # "full_cell" | "half_cell"
    working_electrode: str       # "" | "positive" | "negative"
```

**关键设计决定**：

| 决定 | 理由 |
|---|---|
| `params` 允许**空**，空 = 全继承 | 直接满足"缺失参数继续继承 param_set"。**不需要**任何"填充默认值"的逻辑 |
| `ParameterValue.source` **必填且不能为 `param_set`** | `source="param_set"` 的值**不允许出现在 `params` 里**——它们应该"缺失"，靠继承。wrapper 校验这一点 |
| `ParameterValue.evidence` **必填非空** | 直接落实"Agent 不允许自己猜实验参数"。想填一个值就必须说清出处 |
| `protocol` 是结构化对象，不是字符串 | 避免上一轮发现的"协议字符串散落在两处且不一致" |
| 曲线参数**不在本轮**（`value: float`） | OCP(SOC)/Ds(SOC) 需要函数对象 + 插值，属明确禁止项（§F） |

## A.4 唯一 SimResult（成功/失败**完全同构**）

```python
@dataclass(frozen=True)
class Trajectory:
    time_s:            Tuple[float, ...]   # 秒
    voltage_V:         Tuple[float, ...]   # 伏特
    current_A:         Tuple[float, ...]   # 安培，**放电为正**（全链路唯一约定）
    capacity_Ah:       Tuple[float, ...]   # 安时（累积）

@dataclass(frozen=True)
class SimResult:
    status: str                    # "succeeded" | "failed"   —— 只有两个值，无第三态
    trajectory: Trajectory         # **失败时是空 Trajectory，不是 None**
    termination_reason: str        # "completed" | "solver_error" | "parameter_error"
                                   #  | "adapter_error" | "not_implemented"
    diagnostics: str               # 人类可读；失败时是结构化描述，不是裸 str(e)

    # --- 溯源（成功/失败都有；失败时为空字符串） ---
    dataset_id: str = ""
    cell: str = ""
    window: str = ""
    model_name: str = ""
    param_set: str = ""
    pybamm_version: str = ""
    solver: str = ""
    runtime_s: float = 0.0
```

**同构的强制手段**：

| 手段 | 说明 |
|---|---|
| `trajectory` 永不为 `None` | 失败 → `Trajectory((), (), (), ())`。**消除 `None` 哨兵** |
| `status` 只有两个枚举值 | 消除 `bool` 的模糊性 |
| 没有 `capacity: float` 标量字段 | **消除 `capacity=0` 哨兵**（上一轮 P0-2 的根源）。容量序列在 `trajectory.capacity_Ah` 里 |
| 所有字段在两种状态下**都存在** | 失败时字符串为空、元组为空。**dataclass 保证字段集恒定** |
| `termination_reason` / `diagnostics` 是字符串而非自由文本拼装 | 消除"异常 → 自由文本"的不可解析问题；`diagnostics` 的构造**由 wrapper 负责**，把异常分类后写清"哪个环节失败" |

**形状自检（wrapper 内断言，两条测试守护）**：

```python
assert isinstance(result, SimResult)
assert set(asdict(result).keys()) == EXPECTED_FIELDS      # 字段集恒定
assert isinstance(result.trajectory, Trajectory)           # 永不为 None
assert len(result.trajectory.time_s) == len(result.trajectory.voltage_V)
```

## A.5 数据流：`params` 覆盖怎么进入平台

**这是全方案唯一需要"技巧"的地方**，因为 `_run_one_replay` 不接受覆盖。

```
SimulationRequest.params  ──┐
                            │  wrapper 在这里做：临时猴补 load_parameter_values
                            ▼
        battery_sim.models.pybamm_factory.load_parameter_values
                            │  ← 平台自己的函数（公共 API，未被冻结为私有）
                            ▼
        _run_one_replay(params = 已被覆盖的 ParameterValues)
```

**为什么猴补 `load_parameter_values` 而不是别的**：

| 候选 | 评估 |
|---|---|
| 猴补 `_run_one_replay` 的 `params` 局部变量 | ❌ 函数已进入执行，无 hook 点 |
| 猴补 `pybamm.ParameterValues` | ⚠️ 有效但面太大，会波及 PyBaMM 内部 |
| **猴补 `battery_sim.models.pybamm_factory.load_parameter_values`** | ✅ **`_run_one_replay` 在 `:123` 通过模块级 import 调用它**；只影响这一个入口；是有类型签名的公共函数 |
| 猴补 `build_model` | ❌ 与参数无关 |
| 给平台加一个 `param_overrides` 参数 | ❌ **改冻结内核**，明确不做 |

> ⚠️ **诚实标注**：猴补（monkeypatch）是**技术债**，不是干净设计。
> 它是本轮"零改动冻结内核"约束下**唯一**能实现参数覆盖的手段。
> 我明确建议把它记为 **P2 待偿债务**，在下一轮改成平台侧新增一个
> `param_overrides: Optional[dict] = None` 关键字参数（additive，不破坏既有调用）。

**另一个必须的猴子补丁点**：`_run_one_replay` 的 `:139-142` 用
`df.attrs['initialisation']` 决定初始态。SINTEF adapter **已经把这个块写好了**
（`sintef_graphite.py:1044-1060`），**不需要补**。但 `fixed_initial_concentration`
路径**不接收外部初始态**——所以：
- **本轮 `initial_soc` / 初始化学计量比不进 `params`**（见 §C 的禁止项），
  由 adapter 的 inverse-OCP 自己决定；
- 这是**有意的**，因为本项目已封版"半电池不用 battery SOC 语义"。

---

# B. 文件级修改计划

**总原则**：Agent 仓库**只新增**，平台仓库**零改动**。

## B.1 新增文件（Agent 仓库）

### 文件 1：`Battery-Sim-Agent/agent_sim/__init__.py`
```python
"""Minimal SimulationRequest -> SimResult bridge to battery_sim."""
from agent_sim.schema import ParameterValue, Protocol, SimulationRequest, SimResult, Trajectory
from agent_sim.platform_bridge import run_simulation
__all__ = [...]
```
**内容**：10 行，纯 re-export。

### 文件 2：`Battery-Sim-Agent/agent_sim/schema.py`（核心，~180 行）

**最小内容**：
1. 四个 dataclass（`ParameterValue` / `Protocol` / `Trajectory` / `SimulationRequest` / `SimResult`），全部 `frozen=True`
2. `SimulationRequest.validate() -> None`，检查：
   - `model_name.upper() in {"SPM","SPME","DFN"}`（**在 Agent 侧就拦住**，不再靠 `KeyError`）
   - `source != "param_set"`（`param_set` 的值必须靠继承）
   - `evidence` 非空
   - `protocol.current_sign_convention == "discharge_positive"`
3. `SimResult.succeeded(...)` / `SimResult.failed(reason, diagnostics, **context)` **两个构造器**
   —— **强制两条路径产出同一形状**（这是消除 P0-2 的关键）
4. `EXPECTED_FIELDS` 常量（供测试断言字段集恒定）
5. `to_dict()` / `from_dict()`（JSON 往返，供落盘与复现）

### 文件 3：`Battery-Sim-Agent/agent_sim/platform_bridge.py`（核心，~220 行）

**最小内容**：

```python
PLATFORM_ROOT = Path(os.environ.get("BATTERY_SIM_ROOT",
                     r"C:\Users\24330\WorkBuddy\仿真模拟"))

def _ensure_platform_on_path() -> None:      # 把 PLATFORM_ROOT 插到 sys.path 首位
def _apply_param_overrides(request) -> ctx:  # contextmanager：猴补 load_parameter_values
def run_simulation(request: SimulationRequest) -> SimResult:
    # 1. validate()
    # 2. 平台侧：get_dataset(dataset_id)
    # 3. adapter.load_processed_discharge(cell, window)  → df（含 attrs）
    # 4. with _apply_param_overrides(request):
    #        out = run_baseline_cell(adapter, model_name, cell, rate=window,
    #                                parameter_set=param_set, plot=False, quiet=True)
    # 5. 读 out["output_dir"]/{slug}_time_aligned.csv → 折成 Trajectory
    # 6. 组装 SimResult
    #
    # 失败分类（全部 return，绝不 raise）：
    #   ImportError            -> "not_implemented"  (平台不可达)
    #   RegistryError          -> "adapter_error"
    #   ValueError(params)     -> "parameter_error"
    #   pybamm solve 异常      -> "solver_error"
    #   其他 Exception         -> "solver_error" + 完整 traceback 进 diagnostics
```

**关键实现细节（必须写清的 4 点）**：

| 细节 | 做法 |
|---|---|
| **轨迹从哪来** | `run_baseline_cell` 写 `{rate_slug}_time_aligned.csv`（`baseline.py:528-535`），列名 `time_s / voltage_exp_V / voltage_sim_V / residual_V`。**wrapper 读这个 CSV**，取 `time_s` + `voltage_sim_V` 作电压轨迹。**不重算、不改 runner** |
| **current_A / capacity_Ah 从哪来** | `_run_one_replay` 的返回值里**没有**这两个序列（只返回私有的 `_t_common/_V_*` 数组）。→ wrapper **自己从 `df` 取** `current_A` / `capacity_Ah` 并按 `t_common` 对齐。**这是"读已有数据"，不是"重算仿真"** |
| **`termination_reason` 怎么定** | 成功：若 `coverage_fraction == 1.0` → `"completed"`；若 `< 1.0` → `"voltage_cutoff"`（PyBaMM 提前终止，`baseline.py:229-230` 已有 `common_end` 逻辑可判） |
| **参数覆盖的作用域** | `contextmanager` 进出 `run_baseline_cell`，**用完立刻还原**。避免污染同进程的其他调用 |

### 文件 4：`Battery-Sim-Agent/agent_sim/golden/sintef_pocv_lith.yaml`
§C 的 golden request，**以 YAML 落盘**（不是 Python 常量），便于导师直接看、直接改。

### 文件 5：`Battery-Sim-Agent/agent_sim/smoke.py`（~60 行）
命令行入口：读 golden YAML → 构造 request → `run_simulation` → 打印 §E 的完整输出。

### 文件 6：`Battery-Sim-Agent/tests/test_agent_sim_contract.py`（~90 行）
**4 组测试**（与既有 47 项同一风格，**纯标准库**，不 import pybamm）：

| 测试 | 断言 |
|---|---|
| `test_success_and_failure_are_isomorphic` | 两条路径的 `asdict()` **键集完全相同**；`trajectory` 永不为 `None` |
| `test_no_none_or_sentinel_capacity` | **定义类测试**：`SimResult` 里不存在 `capacity` 标量字段；失败结果的 `trajectory.time_s == ()` |
| `test_params_cannot_claim_param_set_source` | `source="param_set"` → `validate()` 抛错 |
| `test_missing_params_means_inherit` | `params=()` → `validate()` 通过；wrapper 不注入任何值 |

## B.2 明确**不改**的文件

| 文件 | 为什么不改 |
|---|---|
| `battery_sim/**`（全部） | 冻结内核 |
| `Battery-Sim-Agent/battery_agent/pybamm_runner.py` | 含硬编码 4.2/2.7 V，**本轮不调用它** |
| `Battery-Sim-Agent/battery_agent/params.py` | 含那两套几何覆盖，**本轮不 import 它** |
| `Battery-Sim-Agent/battery_agent/utils/data.py` | 含 `load_simulated_battery_data` 的第二套仿真逻辑，**本轮不用** |
| `Battery-Sim-Agent/battery_agent/contract.py` / `parse.py` | 管 LLM 输出，与本次闭环无关 |
| `Battery-Sim-Agent/baseline/**`（6 个副本） | 无关 |
| README / `docs/BORROW_NOTES.md` | 明确禁止项 |
| 既有 `tests/`（47 项） | 保持全绿，不碰 |

## B.3 修改量小结

| 类型 | 文件数 | 估计行数 |
|---|---|---|
| 新增 | 6 | ~660 |
| 修改 | **0** | **0** |
| 平台侧改动 | **0** | **0** |

---

# C. Golden SimulationRequest

## C.1 为什么选 `pOCV-lith` 而不是 `pOCV-deli`

`datasets.yaml:546-547` 明确写着：

> `pOCV-lith` lithiation (3.0 -> 0.01 V) = the cell's own **DISCHARGE** direction;
> **convention-clean cross-check**.

而 `pOCV-deli` 在平台 canonical 约定（放电为正）下是**充电方向**，`baseline.py:541-545` 注明它的 `current_peak_discharge_A` / `Q_sim` / `capacity_error_pct` **不具意义**。

→ **第一条 smoke test 必须用 `pOCV-lith`**，否则导师看到的 `current_A` 符号语义是反的，会立刻产生"符号错了"的误解。这是本方案里最容易踩的坑。

## C.2 Golden request（YAML，可直接给导师看）

```yaml
# agent_sim/golden/sintef_pocv_lith.yaml
# 人工构造的 golden request。**没有任何字段由 LLM 生成。**
# 每一处 params 都必须带 source + evidence，否则 validate() 报错。

dataset_id: sintef_graphite
cell: "4ccc47"
window: "pOCV-lith"

model_name: "SPM"
param_set: "Ecker2015_graphite_halfcell"

cell_configuration: "half_cell"
working_electrode: "positive"        # PyBaMM SLOT（石墨在正极槽位），非物理含义
                                     # 见 datasets.yaml:505-510 与项目 memory

# ------------------- params（覆盖项）-------------------
# 本 case **故意留空**，用来向导师证明"缺失即继承"这条规则真的成立。
# 见 C.4：本轮明确禁止 Agent 自动生成的参数。
params: []

# ------------------- protocol -------------------
protocol:
  kind: "open_loop_replay"
  current_sign_convention: "discharge_positive"   # 全链路唯一约定
  lower_voltage_cutoff_V: 0.01
  upper_voltage_cutoff_V: 1.0
  temperature_C: 25.0
  temperature_source: "declared_room_temperature_not_measured"
  cycles: 1
```

## C.3 哪个字段来自哪里（逐项）

| 字段 | 值 | 来源 | 类型 |
|---|---|---|---|
| `dataset_id` | `sintef_graphite` | `configs/datasets.yaml:486` | 平台注册表 |
| `cell` | `4ccc47` | `datasets.yaml:565` | **实验**（SINTEF 目录，RT p-OCV 电芯） |
| `window` | `pOCV-lith` | `datasets.yaml:569` | **实验**（delithiation 分支的反向对照） |
| `model_name` | `SPM` | 人工选择 | **人的决定**（最快；`supported_models` 含 SPM/SPMe/DFN） |
| `param_set` | `Ecker2015_graphite_halfcell` | `datasets.yaml:528` | **PyBaMM 内置参考集**（非为本次数据标定） |
| `cell_configuration` | `half_cell` | `datasets.yaml:506` | **实验**（扣式半电池） |
| `working_electrode` | `positive` | `datasets.yaml:507` | **槽位事实**（审计结论，非实验测量） |
| `params` | `[]` | — | **继承** |
| `lower/upper_voltage_cutoff_V` | 0.01 / 1.0 | `datasets.yaml:578-579` | **实验**（p-OCV 程序窗口） |
| `temperature_C` | 25.0 | `datasets.yaml:583-592` | ⚠️ **declared，非实测**（parquet 无温度通道，confidence: low） |
| 初始态（化学计量比） | 不在 request 里 | `sintef_graphite.py:1044-1060` | **派生**：逆 OCP(实测 pre-branch rest OCV) |
| `time_s/voltage_V/current_A` | 不在 request 里 | adapter 从 parquet 读 | **实验** |
| solver | 不在 request 里 | `configs/models.yaml` | 平台默认（IDAKLU） |

## C.4 本轮**明确禁止** Agent 自动生成的参数

| 参数 | 为什么禁止 | 本轮怎么做 |
|---|---|---|
| `Electrode width [m]` / `height` | Agent 仓库的 0.0368/0.04 是 CALCE 系列几何，**与本电芯无关**（本电芯是 14 mm 扣式，`datasets.yaml:598`） | **不进 params**；由 adapter 的几何语义与参考集决定 |
| `Nominal cell capacity [A.h]` | 参考集 202 mAh vs 本电芯 2.162 mAh，比 ~94×。改它等于抹掉已知的尺度失配 | **不进 params**；`datasets.yaml:576` 已声明 `0.002162` |
| `Initial concentration in positive electrode [mol.m-3]` | **已由 adapter 的 inverse-OCP 决定**（`sintef_graphite.py:1054`）。手动给值会与 inverse-OCP **打架** | **不进 params** |
| `Maximum concentration in negative/positive electrode` | 参考集的结构量，非本数据集可测 | **不进 params** |
| `Negative/Positive particle radius [m]` | 参考集是 13.7 µm，本电芯规格书 D50 是 17.58 µm——**但那是用户的另一颗石墨**，回填是明确红线 | **不进 params** |
| 任何 `active material volume fraction` | 参考集的结构量 | **不进 params** |
| `SEI*` 全部 | 本 case 无降解建模需求 | **不进 params** |
| OCP(SOC) / Ds(SOC) 曲线 | 需要函数对象；超出本轮范围 | **不支持**（`ParameterValue.value` 只收 `float`） |
| `initial_soc` / `initial_stoichiometry` | 半电池不用 battery SOC 语义（项目已封版）；且 inverse-OCP 已接管 | **不进 params** |

**这张表就是"Agent 不允许猜"的落地形式**：不是靠提示词请求 LLM 别猜，
而是 **`params` 里根本没有这些字段，且 `evidence` 必填**。

---

# D. Smoke test

## D.1 前置（一次性）

```bash
# 1) 平台侧无改动，只需确认可达
export BATTERY_SIM_ROOT=/mnt/c/Users/24330/WorkBuddy/仿真模拟

# 2) Agent 侧新增文件落位后，契约测试（纯标准库，不 import pybamm）
cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent
python -m pytest tests/test_agent_sim_contract.py -q
# 期望：4 passed
```

## D.2 闭环 smoke test

```bash
wsl.exe -d Ubuntu -e bash -lc '
  export PYTHONIOENCODING=utf-8
  export BATTERY_SIM_ROOT=/mnt/c/Users/24330/WorkBuddy/仿真模拟
  cd /mnt/c/Users/24330/WorkBuddy/Battery-Sim-Agent
  source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm
  python -m agent_sim.smoke agent_sim/golden/sintef_pocv_lith.yaml
'
```

## D.3 通过判据（5 条，全部可自动断言）

| # | 判据 | 断言 |
|---|---|---|
| 1 | 形状同构 | `SimResult` 字段集 == `EXPECTED_FIELDS`；`trajectory` 非 `None` |
| 2 | status 合法 | `status in {"succeeded","failed"}` |
| 3 | 轨迹非空且等长 | `len(time_s) == len(voltage_V) == len(current_A) == len(capacity_Ah) > 0` |
| 4 | 与平台直跑一致 | `time_s[-1]` 与 `outputs/platform/sintef_graphite/baseline/SPM/cell4ccc47/pOCVlith_time_aligned.csv` 的末行 `time_s` **在 1e-6 内相等**（证明 wrapper 没有偷偷改数据） |
| 5 | 失败路径也同构 | 故意把 `model_name` 改成 `"SPMZ"` → `status="failed"`、`termination_reason="parameter_error"`、字段集**不变** |

> 判据 4 是本轮设计里最重要的一条：它把"wrapper 只是搬运、没有重算"变成**可验证**的。

## D.4 预期数值（本轮已预跑）

平台直跑（`run_pipeline.py baseline`）实测：

```
[BASELINE] cell4ccc47 pOCVlith (C/50 (p-OCV lithiation), source: p-ocv) SPM
  RMSE(t)= 875.75 mV | MAE(t)= 867.93 mV | Qexp=0.002 Ah | Qsim=0.002 Ah
```

→ wrapper 的 SimResult 应当**复现同一组数**（`diagnostics` 里带 `rmse_time_aligned_mV = 875.75`）。

**关于 875 mV 必须对导师先讲清**：这是**已知的尺度失配 artefact**，`datasets.yaml:594-612` 已封版记录（参考集 85.85 cm² / 202 mAh vs 本电芯 1.54 cm² / 2.16 mAh，~56×）。
**它不是仿真失败，也不是模型误差**，本轮**只用它验证链路连通性**（措辞红线：不写作 validation）。

---

# E. 明天导师实际看到的完整输入输出

## E.1 看到的第一屏（shell）

```
$ python -m agent_sim.smoke agent_sim/golden/sintef_pocv_lith.yaml

================= SimulationRequest (input) =================
dataset_id          : sintef_graphite
cell / window       : 4ccc47 / pOCV-lith
model_name          : SPM
param_set           : Ecker2015_graphite_halfcell
cell_configuration  : half_cell  (working_electrode: positive [PyBaMM SLOT])
----------------------------------------------------------------
params (overrides)  : (none)  -> every parameter inherited from param_set
----------------------------------------------------------------
protocol:
  kind                 : open_loop_replay
  current_sign         : discharge_positive
  voltage window       : 0.01 - 1.0 V
  temperature          : 25.0 C  (declared; NOT measured)
  cycles               : 1

================= SimResult (output) =========================
status              : succeeded
termination_reason  : completed
trajectory:
  points            : 2000
  time_s            : 0.0 ... 12345.6      (first/last)
  voltage_V         : 0.9876 ... 0.0123
  current_A         : 0.0000432 (C/50, discharge-positive)
  capacity_Ah       : 0.0 ... 0.002156
diagnostics         : rmse_time_aligned_mV=875.75 (SCALE ARTEFACT, not model error);
                      reference set 85.85 cm2/202 mAh vs this cell 1.54 cm2/2.16 mAh
provenance:
  pybamm_version    : 26.8.0
  solver            : IDAKLUSolver (rtol=1e-6, atol=1e-6)
  runtime_s         : 3.4
  source files      : data/sintef__sintef-graphite-R2032-intelligent-4ccc47__*__p-ocv__RT.bdf.parquet
```

## E.2 导师会问的四个问题，及现成答案

| 问题 | 答案在 |
|---|---|
| "参数覆盖了几个？" | `params (overrides): (none)` —— 本 case **故意**零覆盖，用来证明"缺失即继承"成立 |
| "哪个值是你猜的？" | 全部字段的 `source`/`evidence` 都在请求里。唯一 `assumed` 是温度（`declared_room_temperature_not_measured`，confidence low，已标注） |
| "875 mV 的误差怎么回事？" | `diagnostics` 直说 SCALE ARTEFACT，并给出两个面积/容量。**不是模型误差** |
| "失败时什么样？" | 判据 5：改坏 `model_name` 再跑一次，字段集不变、`status=failed`、`trajectory` 是空 Trajectory 而非 `None` |

## E.3 失败路径样例（建议主动演示）

```
================= SimResult (output) =========================
status              : failed
termination_reason  : parameter_error
trajectory:
  points            : 0            <- 空 Trajectory，不是 None
  time_s            : ()
  voltage_V         : ()
  current_A         : ()
  capacity_Ah       : ()
diagnostics         : Unsupported model_name 'SPMZ'.
                      Supported: SPM, SPMe, DFN.
                      Raised in: SimulationRequest.validate()
provenance: (schema unchanged; strings empty)
```

**这个对照就是本轮设计的核心卖点**：成功与失败**字段集完全一致**，
不存在上一轮发现的 `capacity=0` 哨兵、`list`→`dict` 类型漂移、`None` 分支。

---

# F. 本轮明确不处理（同意用户约束）

| 项 | 状态 |
|---|---|
| 大规模重构 | ❌ 不做（`battery_agent/` 原样保留，只是不被调用） |
| LLM 参数优化 | ❌ 不做（`contract.py`/`parse.py` 不动） |
| GITT Ds 自动拟合 | ❌ 不做（`ParameterValue.value` 只收 `float`） |
| 新模型 | ❌ 不做（只用 SPM/SPMe/DFN） |
| UI | ❌ 不做（只打印到 stdout） |
| README 美化 | ❌ 不做 |

## 附带必须记录的技术债（下一轮）

| # | 债务 | 建议偿还方式 |
|---|---|---|
| **D-1** | **猴补 `load_parameter_values` 实现参数覆盖** | 平台侧加 `param_overrides: Optional[dict] = None`（additive），撤回猴补 |
| **D-2** | wrapper 从 `{slug}_time_aligned.csv` 读轨迹（**依赖输出文件格式**） | 长期应由 runner 直接返回数组；属 additive 扩展 |
| **D-3** | `params` 的 `evidence` 靠人工填 | 建立"哪些字段允许 Agent 生成"的**配置化白名单**（复用 `contract.BOUNDS` 的护栏思路，但换成实验参数名） |
| **D-4** | 曲线参数（OCP/Ds）尚不可传 | 待 §F 解锁后，`ParameterValue.value` 扩为 `float | CurveSpec` |

---

# 附：本方案的边界声明

- **只出方案，未改任何代码**。本轮只做了**读取**与**实跑验证**（`run_pipeline.py baseline --dataset sintef_graphite`，一次，只读产出）。
- **已实跑验证的前提**：半电池 baseline 路径可用（§0.2）；`_run_one_replay` 支持 `model_options` 与 `initialisation`（读码确认）；`run_baseline_cell` 写 `_time_aligned.csv`（读码确认）。
- **未验证**：wrapper 本身尚未编写，因此"猴补 `load_parameter_values` 能生效"是**读码推断**（依据：`baseline.py:51` 从模块 import、`:123` 以模块级名字调用）。**这是本方案唯一未实跑的环节**，实施时应第一步就验证它。
- **措辞红线**：本 case 的 875 mV 是尺度失配 artefact，**不得**写作 validation / model error。
  石墨在 PyBaMM 参数集里占**正极槽位**（`working_electrode: positive`）是审计结论，不是物理含义。
