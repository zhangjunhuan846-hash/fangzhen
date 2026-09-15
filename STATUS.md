# STATUS.md — 唯一可信状态页

> 本文件是平台状态的**唯一真源**。任何其它文档（README / HANDOFF / docs/*.md）里的
> 状态描述、测试数、阶段结论，若与本文件冲突，**以本文件为准**。
>
> 维护规则：只允许在本文件写"已验证"的数字。每个数字必须写明**验证方式**与**验证日期**。
> 不允许写"应该""大约""计划中"。

---

## 版本

```text
Platform version:       v0.1 (run_pipeline.py 自述版本；尚无语义化版本号)
Last verified commit:   12a6cd9  (2026-09-15, "feat: add traceable runtime parameter overrides")
origin/main:            ee45d62  (本地领先 1 个 commit，**尚未 push**)
Working tree:           见「已知限制 #1」
STATUS.md last updated: 2026-09-15
```

---

## 工程门（Engineering gates）

```text
G0 环境可复现        PARTIAL  — 本机可跑；未在干净机器上验证过
G1 数据接入          PASS     — 2026-09-15 实测
G2 SPM/SPMe/DFN 回放 PASS     — 2026-09-15 实测
G3 provenance        PASS     — 2026-09-15 实测
```

### G0 环境可复现 — PARTIAL

- **PASS 的部分**：本机（WSL Ubuntu / conda env `pybamm`）按 README 可完整跑通，
  PyBaMM 26.8.0 / PyBOP 26.3 / numpy 2.3.5 / pandas 3.0.5。
- **未验证的部分**：**没有在干净 clone 的机器上跑过**。因此不能声称"新机器能跑起来"。
- **已知的环境陷阱**（不在任何安装文档里，只存在于脚本与经验中）：
  - Windows 侧 Python **没有 pandas**，仿真必须走 WSL。这是一个硬分叉，新人不看代码发现不了。
  - Windows git 的 `credential.helper` 与 `refs/remotes/origin/main` 需要修复才能 push；
    修复脚本为 `scripts/dev/apply_env_fixes.sh`。**"新 clone 需重跑此脚本"这件事写在脚本注释里，
    没写在 README 里。**

### G1 数据接入 — PASS

验证方式（2026-09-15）：

```bash
python -m user_tools.import_dataset --package examples/half_cell_demo
```

结果：679 行转 canonical / 12 项校验 / 严重 0 / 警告 2 / 匹配参数集
`Jackowska2025_2mAh_cm2` (grade B) / 输出 `outputs/user_datasets/demo_birmingham_cover5`。

### G2 SPM/SPMe/DFN 回放 — PASS

验证方式（2026-09-15）：

```bash
python run_pipeline.py --list-datasets
python run_pipeline.py baseline --dataset sintef_graphite --model SPM
python -m user_tools.run_baseline --package examples/half_cell_demo --models DFN
```

已注册数据集 6 个：`chen2020` / `calce_cs2` / `calce_20r` /
`birmingham_ncm920305` / `calce_a123` / `sintef_graphite`。

### G3 provenance — PASS

单次 baseline 落盘 8 个产物（石墨 SPM / cell4ccc47 实测）：

```text
metrics.csv
run_metadata.json                  （24 个键）
<rate>_time_aligned.csv
<rate>_Vt.png
<rate>_parameter_mapping.json
```

`run_metadata.json` 含：`parameter_set` / `parameter_source` / `parameter_repo_commit` /
`pybamm_version` / `working_electrode` / `model_options` / `capacity_metric_type` /
`capacity_is_predictive` / `capacity_metric_note` / `parameter_overrides_requested` /
`parameter_match` / `timestamp` / `runtime_s`（共 24 项）。

**本门是全平台做得最扎实的部分**：`surrogate` / `zero-fit` / `not a validation run`
等标注直接进入机器可读字段，而不是只写在散文里。

---

## 科学门（Scientific gates）

```text
G4 OCP/GITT 提取         PASS（受限）  — 见下方限定
G5 参数辨识              NOT DONE      — 平台自身代码零拟合代码
G6 held-out 预测         NOT DONE
G7 再生状态泛化          NOT STARTED
G8 优化闭环              NOT DONE
```

### G4 OCP/GITT 提取 — PASS（受限）

已完成且有封版值：双支 OCP 派生、容量一致化、GITT 按日志间隙分段、表观 D_s 反演。

**限定条件（必须一起引用，否则会误读）**：

- D_s 反演已得出**否定性结论**：单颗粒模型是这份数据的错误透镜。
  共同集 614 条中位 `2.155e-16`，比参考低 57×；一阶/二阶两种函数形式给出同一质性结论。
  → **"能提取"不等于"提取出的东西是物理参数"。**
- `B1` 与 `B1.6` 是**诊断**，不是验证。
- 实验反演出的 D_s 是 **apparent / effective**，不是本征材料常数。

### G5 参数辨识 — NOT DONE

**证据（2026-09-15，全仓搜索）**：

```bash
grep -rn "import pybop\|from pybop" --include="*.py" \
  battery_sim/ parameters/ extraction/ user_tools/
# → 0 命中
grep -rln "minimize|curve_fit|least_squares|Parameterisation|FittingProblem|Optimisation" \
  battery_sim/ parameters/ extraction/ user_tools/
# → 0 命中
```

平台自身代码中**没有任何拟合**。所有命中均在 `.venv/`（第三方库内部）。

**环境侧已就绪**：PyBOP 26.3 已安装且可 import。但注意 ——
**26.3 的 API 与公开教程不一致**，以下名字在 26.3 中**不存在**：

| 教程里的写法 | 26.3 实际 |
|---|---|
| `pybop.FittingProblem` | `pybop.Problem(simulator, cost)` |
| `pybop.Parameterisation` | `pybop.Parameters` / `pybop.Parameter` |
| `pybop.Optimisation` | `pybop.optimisers.*`（scipy / pints） |
| — | `pybop.ScipyOptimise` 亦不存在，须走子模块 |

直接相关的现成工具（26.3 自带）：
`pybop.lithium_ion.SPDiffusion`、`pybop.lithium_ion.WeppnerHuggins`、
`pybop.applications.gitt_methods`。

→ **任何照抄网上 PyBOP 示例的代码都不能直接运行。**

### G5 的历史路障：一个已修掉的假拒绝（2026-09-15 发现并修复）

参数覆盖能力表把 `particle_diffusivity` 全局声明为 **CURVE**（标量一律拒绝）。
但**表示形式是 (参数, 参数集) 的属性，不是全局属性**：

| pybamm 键 | Chen2020 | Ecker2015_graphite_halfcell |
|---|---|---|
| `Positive particle diffusivity [m2.s-1]` | **float = 4e-15** | **function** |
| `Positive electrode exchange-current density [A.m-2]` | function | function |

后果：在 Chen2020 上，一个**本来就是 float** 的 `D_s` 会被以
`unsupported_parameter_representation` **误拒** —— 而它正是第一版辨识向量里最该辨识的那个。
拒绝理由看起来完全合理，不会有任何告警。

**已修**（2026-09-15）：参数表示不再按名字全局声明，改为按 `(参数, 参数集)` 运行时解析。
见下一节。

---

## 能力分级：`consumed` 是一个歧义词，已拆成五级

一个参数要能进入辨识，必须**依次**过五关。把前几关混成一句"被消费了"，
会同时犯两种错：**误拒**可用的参数，和**放过**根本不起作用的参数。
两者都实测到过。

```text
representable → accepted → resolved → numerically_active → identifiable
```

| 级别 | 问题 | 判定方式 | 实测反例 |
|---|---|---|---|
| **representable** | 平台能否**表达**这种参数形式？ | 探测该键在**当前参数集**里的类型 | `D_s` 在 Chen2020 是 float，在石墨集是 function |
| **accepted** | 安全检查是否放行这个覆盖？ | 能力表 + 单位/模型适用性 | — |
| **resolved** | 模型构建时是否**查找**该参数？ | 删键看能否构建 | SPM 会解析 `porosity` |
| **numerically_active** | 改它是否**真的改变**预测？ | 覆盖后看解是否移动 | SPM 下 `porosity` **逐位不变** |
| **identifiable** | 能否从数据中把它与其它参数**区分**？ | G5 的 identifiability 分析 | **尚待验证** |

**关键区分：`resolved` 会高报，必须用 `numerically_active` 才能下结论。**
判"适用模型"那张表记录的是 `numerically_active`，不是 `resolved`。

| 参数 · 条件 | representable | accepted | resolved | numerically_active | identifiable |
|---|---|---|---|---|---|
| $D_s$ · Chen2020 · SPM/SPMe/DFN | ✓ | ✓ | ✓ | **✓**（RMSE −25.63 / −21.88 / −21.88） | 尚待 G5 |
| $\epsilon_{am}$ · Chen2020 · SPM | ✓ | ✓ | ✓ | **✓**（RMSE −38.31） | 尚待 G5 |
| $R_{ohm}$ · Chen2020 **默认 options** | ✓ | ✓ | ✓ | **✗**（delta 恰好 `0.000000`） | — |
| $R_{ohm}$ · Chen2020 **+ `contact resistance: "true"`** | ✓ | ✓ | ✓ | **✓**（−37.63 / −31.70 / −31.66） | 尚待 G5 |
| `porosity` · SPM | ✓ | ✗ | ✓ | **✗**（delta 恰好 `0.000000`） | — |
| $k_0$ · Chen2020 | ✗（函数） | ✗ | — | — | — |
| `temperature` · Chen2020 / 石墨 | ✓ | ✓ | ✓ | **✗**（PyBaMM 构建期折入） | — |

**`numerically_active` 可以是"带条件的"** —— `R_ohm` 就是唯一的确证案例：
默认配置下位移**恰好 `0.000000`**，开启 `contact resistance` 后位移 **−37.6 mV**。
所以它必须**分两行记录**，写成单一状态就是错的。

**已隔离验证**（`tests/test_contact_resistance_option.py`，11 项）：通过
`_run_one_replay` 显式传 `model_options`，**不改 `configs/datasets.yaml`**。
该文件表达"这个数据集默认怎么跑"，不承担能力探针的职责；测试里有一条
断言把这个隔离契约**钉死**（配置块里出现 `contact resistance` 即失败）。

**附带钉住一个坑**：该 option 的值必须是**字符串** `"true"`，传布尔 `True` 会被 PyBaMM
以 `OptionError` 拒绝。这个错误曾被宽泛的 `except` 吞掉，导致探针"成功"跑出
"参数惰性"的假结论 —— 现在它是测试而非注释。

**两处诚实边界**：
- "resolved 用删键法、numerically_active 用覆盖法"这两个探针**不可互换**，
  混用会得出错误结论（删键法会高报：它说 SPM 解析 `porosity`，而覆盖它逐位不变）。
- $D_s$ / $\epsilon_{am}$ 的 `numerically_active` 已证，但 **`identifiable` 尚待 G5** ——
  位移大只说明"能动"，不说明"能从数据里与其它参数区分开"。

### G6 / G7 / G8 — 未完成

`G6` 依赖 G5；`G7` 依赖回收石墨数据到位；`G8` 依赖 G5+G6。

---

## 测试状态

```text
pytest:        329 passed, 5 warnings
failures:      0
duration:      100.16s
last run date: 2026-09-15  (提交前复跑)
command:       python -m pytest -q   (WSL, conda env pybamm)
```

**文档中的测试数已过期，勿引用**（2026-09-15 核对）：

| 文件 | 写的数 | 实际 |
|---|---|---|
| `README.md` | 293 | **329** |
| `HANDOFF.md` | 88 | **329** |

两个数字互不相同，且都与实际不符。已改为指向本文件，不再写死数字。
**引用测试数时只引用本文件的 329。**

---

## 已知限制

1. **`initial_state` 仍未实现，44.64 mV 缺口未闭合。**
   当前 48.36 mV 是公共接口的诚实结果。闭合需要把初值策略放进 request
   （与"顶层只有四个字段"冲突），属独立设计任务。

2. **覆盖 API 已提交但未 push。**
   `12a6cd9 feat: add traceable runtime parameter overrides`（+753/−0）在本地 `main` 上，
   `origin/main` 还停在 `ee45d62`。
   → **任何人 clone 远程仓库仍看不到这个 API。** 需要 push 才对导师可见。

3. **跑一次 pipeline 会改动被 git 跟踪的产物文件。**
   `outputs/` 有 418 个文件在版本控制内。一次 baseline 会改 6 个文件。
   实测差异内容：`timestamp`、`runtime_s`，以及 schema 新增的
   `parameter_overrides_requested` / `parameter_overrides_applied` / `parameter_override_sources`。
   **数值结果逐位不变**（`150.05925543689233` / `875.752828973872` 完全一致）——
   即**结果可复现，但产物不可复现（含时间戳）**。
   → 长期建议：`outputs/` 不入 git，只保留少数 golden regression artifacts。
   命名口径：`timestamp`/`runtime_s` 是 **execution metadata**（本该变），
   RMSE/模型版本/参数集 commit/覆盖记录/输入 hash/solver 设置才是 **science payload**（该冻结）。

4. **`_PARAM_SET_ABSENT_KNOWN` 已降级为"离线近似"。**
   探针可用时缺失判定走真实的 `KEY_ABSENT`；这份硬编码名单只在
   `validate_request`（平台无关层）无探针时兜底。

5. **Agent 侧 bridge 耦合平台输出布局**（依赖 `{rate_slug}_time_aligned.csv`）。
   平台输出目录结构一旦调整，Agent 侧会静默失效。

6. **Agent 仓库没有 `.git`**（当初 tarball 解压）→ 它的改动**无法提交**，
   也没有 upstream commit ancestry。上游 `opqrst-chen/Battery-Sim-Agent` 的写权限未确认。
   **不要直接在 tarball 上 `git init`**——那会丢掉来源历史。

7. **石墨线的 `Ecker2015_graphite_halfcell` 参考集半径与其自身不一致**
   （用户商业石墨 D50 = 17.58 µm vs 参考集 13.7 µm，差 1.56×；因 D ∝ R²，
   对 D 是 2.4× 量级）。**这不是 bug，是已知系统性不确定度，必须在论文里报。**

---

## 一句话状态

> 工程基础设施（G0–G4）已可用且 provenance 扎实；**科学闭环（G5–G8）尚未开始**。
> 平台当前是 **zero-fit 回放与诊断平台**，不是参数辨识平台。
> 下一阶段应停止扩功能，直接做 **G5 → G6**。
>
> **G5 的两个路障已拆**（2026-09-15）：
> ① 参数表示改为按 `(参数, 参数集)` 运行时解析 → Chen2020 的 $D_s$ 不再被假拒；
> ② `requested` / `applied` / `source` 三件套已补齐并提交（`12a6cd9`，**未 push**）。
>
> **G5 第一版向量应收缩为 $\theta=\{D_s,\epsilon_{am}\}$**，甚至先只做 $\{D_s\}$：
> 先跑 **synthetic recovery**（人为设定 $D_s^{true}$ 生成曲线，看能否从不同初值恢复），
> 验证 `optimizer → override → PyBaMM → cost → recovered` 整条 plumbing，
> 再上真实数据。$k_0$ 是函数型，本平台暂无法表达，**不要进第一版**。
