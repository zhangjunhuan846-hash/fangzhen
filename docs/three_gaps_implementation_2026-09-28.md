# 三个缺口的填法（2026-09-28）

> **性质**：这是**实施记录**，不是新判据。它把 `preregistration_annex_A` §4.1 与
> `annex_B` §A3 里已经写明是缺口的三件事，落成可运行的机制。
> **不改预注册的任何判据**；新模块全部 additive，`v0.1.0-platform`（`ee2fb36`）未移动。
>
> 日期：2026-09-28 ｜ **2026-09-29 增补**：`settings_hash` 缺字段硬门（+9 项测试）
> ｜ 测试：`700 passed`（冻结基线 613 + 三缺口 78 + 硬门 9），零失败
> ｜ 平台核心（runner / evaluator / factory / registry / rates / paths）**改动 0 行**

---

## 0. 一页速查

| # | 缺口 | 出处在哪 | 现在有什么 | 还差什么（只有你能做） |
|---|---|---|---|---|
| 1 | 几何实测值到模型**没有通路** | annex A §4.1（"本轮最大的真实缺口"） | `governance/geometry_channel.py` + `user_tools/geometry_channel.py` | **填四个实测量**（D50 / 涂层厚度 / 载量 / 面积） |
| 2 | 静置噪声底 `σ_noise` **0 命中** | annex B §A3 | `governance/noise_floor.py` + `user_tools/sigma_noise.py` | **Step 0 空跑 30 min**（不需要样品、不需要设备） |
| 3 | 数值设置指纹 `settings_hash` **不存在** | 三层模型比对必需（此前未列） | `governance/settings_hash.py` | 跑 M0/M1/M2 时逐层记录 |

前两个是**已在文档里承认的缺口**；第三个是本次新识别并补上的，理由见 §3。

---

## 1. 缺口 1：几何实测值 → 模型参数

### 缺口是什么（原文）

> `electrode.mass_loading_mg_cm2` / `coating_thickness_um` / `area_cm2` /
> `particle.d50_um` 四个键在仓库里**只出现在 `material_metadata.py`**（校验与摘要打印），
> **没有任何代码把它们变成 `parameter_overrides`**。
> —— `preregistration_annex_A_parameter_provenance.md` §4.1

**后果不是"不够规范"，是结论不可归因**：模型默认沿用
`Ecker2015_graphite_halfcell` 的 `R_p = 13.70 µm`。若实测 D50/2 = 8.79 µm，
`τ ∝ R²` ⇒ **`D_s` 读数差 2.4×**。也就是**粒径变化会被读成"扩散变化"**。

### 现在有什么

`governance/geometry_channel.py` —— 四个实测量 → 两个 PyBaMM 键 + 逐键来源。

```python
from governance.geometry_channel import geometry_override_channel, radius_report_line

rec = geometry_override_channel("templates/commercial_graphite_ht/metadata/CG-AR.yaml")
if rec["incomplete"]:
    print(rec["reason"])          # 报缺哪几项，不猜
else:
    overrides = rec["parameter_overrides"]           # 可直接传给 parameter_overrides
    sources   = rec["parameter_override_sources"]    # 可直接传给 parameter_override_sources
    print(radius_report_line(rec))                   # ★ 必须进报告
```

命令行（**今天就能跑**，现在会报"不完整"，那是正确结果）：

```bash
python -m user_tools.geometry_channel --series templates/commercial_graphite_ht/metadata
#  → 4 份，完整 0，不完整 4；退出码 1（不是错误，是"数据还没到"）

python -m user_tools.geometry_channel --metadata .../CG-AR.yaml --out outputs/geometry/CG-AR.json
#  → 填齐后：给出 overrides + 逐键来源 + 报告行；退出码 0
```

**四条设计纪律**（都有测试钉住）：

1. **缺一项就整块不给**（all-or-nothing）。`R_p` 与 `L` 同时进 `τ = D·t/R²`，
   只换一部分会得到一个**既不是参数集几何、也不是实测几何**的混合态，事后无法复算。
2. **每键必带来源**：值 / 来自哪个 metadata 文件 / 公式。
3. **只覆盖它该覆盖的**。`eps_am` / `porosity` **不碰** —— 那两者要按 annex A §3.1 的
   固定公式用载量、真密度、配方算，本通路不猜（`not_covered` 里显式列出）。
4. **与尺度对齐门互斥，冲突即拒**。`scale_alignment='align'` 写的是
   `Electrode height/width [m]`（缩放 footprint 面积），本通路写的是 `R_p` / 厚度。
   同时生效 ⇒ **容量被缩放两次**。这类"两个都对但合起来错"的组合必须在入口拦：

   ```bash
   python -m user_tools.geometry_channel --series ... --scale-alignment align
   #  → 退出码 2，逐条说明为什么冲突
   ```

### ★ 还差什么（只有你能做）

**填那四个数**，写进 `templates/commercial_graphite_ht/metadata/<样品>.yaml`：

```yaml
electrode:
  mass_loading_mg_cm2: <实测>
  coating_thickness_um: <实测，千分尺，不是标称>
  area_cm2: <冲片几何面积>
particle:
  d50_um: <本样品重测；不是规格书值>
```

⚠️ **D50 必须每样品重测**。规格书 D50 是**处理前**的粉，热处理的失重与破碎会改粒径。
不重测 ⇒ 不许解释跨样品 `D_s` 差异（这条是 `README` §0 红线 1，现在有了机器读法：
`run_record.yaml` 的 `gates.L1_geometry_channel_complete`）。

**填齐后必须做的事**：把 `radius_report_line()` 那行贴进报告。
不打印就等于把粒径变化读成扩散变化。

---

## 2. 缺口 2：静置电压噪声底 `σ_noise`

### 缺口是什么（原文）

> 预注册的负对照 **N1**（零激励窗口代价面精确平坦）与"静置是否够长"
> 都依赖噪声底；**没有 `σ_noise`，这条判据是空的**。
> 而它必须用**空跑**测（Step 0 空跑 30 min）。
> —— `preregistration_annex_B_preflight_gaps.md` §A3

### 现在有什么

`governance/noise_floor.py` + `user_tools/sigma_noise.py`。

```bash
# 先看 CSV 长什么样（不确定列名时）
python -m user_tools.sigma_noise --csv step0_rest.csv --inspect

# 标定（k 是判据倍数，要预注册）
python -m user_tools.sigma_noise --csv step0_rest.csv --k 3
#  → σ_noise = X.XXXX mV；N1 判据：max|ΔV| <= 3 × σ_noise = Y.YYY mV
#  → outputs/noise_floor/step0_rest.md  (贴进方案)
#  → outputs/noise_floor/step0_rest.json (run_record 的 sigma_noise_mV 从这里取)
```

**三个容易做错的地方，实现里都处理了**：

| 坑 | 处理 | 为什么重要 |
|---|---|---|
| 对原始序列直接取 `std` | **先去线性趋势**（最小二乘），对残差取尺度 | 静置有残余漂移；不去的 `std` 会把**漂移算成噪声**，系统性高估 |
| 用 `std` | 默认 **MAD × 1.4826**（稳健） | 偶发跳点（接触不良/采样毛刺）会让 `std` 膨胀 |
| sigma 小于仪器分辨率 | **报出分辨率下限** `q/√12` | 否则 N1 会被一个"看起来很小"的分辨率**满足掉** |

`std` 与 MAD **两个都算出来并列报** —— 这是发现跳点最快的方式。

**这一条现在就能做完，不依赖任何样品、任何设备到货。**

### ★ 还差什么（只有你能做）

1. **做 Step 0 空跑**：不装样（或装一颗不工作的电芯），静置 30 min，记电压序列。
2. **定 `k`**。判据形式是 `max|ΔV| ≤ k·σ_noise`，`k` 必须**预注册**写入
   `configs/noise_floor_prereg.yaml`（出厂 `k: null`）。见下面 §2.5。
3. 把 `sigma_noise_mV` 与 `k` 填进 `templates/commercial_graphite_ht/run_record.yaml`。
4. ⚠️ 若标定 JSON 里 `resolution_limited: true`，**这个 sigma 反映的是仪器分辨率，
   不是噪声** —— N1 的结论必须一起引用这条。

### 🔧 2026-09-29 修复：`k` 从「脚本默认值」改为「预注册量」

**原文在这里写的是**："现在脚本默认按 `k=3` 示例，并会在报告里标注'未指定 k，这是示例'"。
**这句话有两处不实**（写的时候就错了，本次据实订正）：

| 原说法 | 实测 |
|---|---|
| 脚本"会标注"未指定 | `render_noise_floor_report` 的签名是 `k: float = 3.0` —— 一个**无标记的默认值**，报告里读起来像"我们定了 k=3"。那句"注：未指定 `--k`"只加在 CLI 的 md 输出里，**`governance/` 层直接调用时完全没有** |
| 报告与 JSON 一致 | CLI 在无 `--k` 时**报告按 3×σ 渲染**，但 JSON 写 `"k": null` 且**没有** `criterion` 键 —— 两份产物互相矛盾，引用哪一份都会得出不同结论 |

这与 `settings_hash` 的缺失字段**同一类缺陷**：*一个看起来像决定的默认值，
比没有默认值更危险*。

**改法（三条，都有测试钉住）**：

1. `calibrated_threshold_mV(k)` 接受 `k=None` ⇒ 返回里带
   `is_preregistered: False` + `example_k`，且 `statement` 明写"k 尚未预注册，
   判据尚未成立"。⚠️ **不抛错** —— 标定 σ 与预注册 k 是两件独立的事，
   不该因为 k 没定就挡住 σ 的产出。选"显式标记"而非"抛错"，理由写在这一句里。
2. 新增 `configs/noise_floor_prereg.yaml`（出厂 `k: null`）+ `load_preregistered_k()`
   （文件缺失或字段为空 ⇒ 返回 `None`，**不猜**）。`k` 的来源优先级：
   命令行 `--k` > 预注册文件 > 无；**来源本身记进产物**（`k_source`）。
3. CLI 的**报告与 JSON 用同一个 `k`**：无 k 时 JSON 里 `criterion` 为 `null`
   并附 `criterion_unavailable_reason`（写明去哪儿补）。

**为什么这个顺序不能颠倒**：判据必须先定 `k`、后用空跑数据算 σ。
先看 σ 再挑 `k` 会让判据退化成事后拟合 —— 这正是预注册要防的事。
所以模板文件里除了 `k` 还留了 `rationale` / `preregistered_on` / `preregistered_by`，
**不许只填一个数字**。

**新增测试**：`tests/test_noise_floor.py` 17 → **27**（`k` 语义 10 项）、
新建 `tests/test_sigma_noise_cli.py` **15 项**（报告/JSON 一致性、单位一致、
坏输入 fail loud、产物只落在指定路径）。其中 `test_shipped_template_has_no_decided_k`
会在仓库里的预注册文件被"转正"时立刻失败。

---

## 3. 缺口 3：数值设置指纹 `settings_hash`

### 为什么这是缺口（本次新识别）

M0 / M1 / M2 **都是零自由参数**（纯递进参数化，不拟合）。这意味着三层之间的
**任何**差异都会被原封不动归给"参数化的增益"。而三层里唯一允许变的就是参数 ——
**网格、时间步、求解器容差、模型选项必须逐位相同**。

如果 M1 与 M2 之间还改了网格，"M2 比 M1 好"这句话就读不出来，因为差异里混着
离散化误差。**而这类差异在电压曲线上看不出来** —— 所以必须由指纹拦，不能靠人自觉。

这与 `scale_alignment` 的教训同源：两次"参数惰性"的真因都不在参数上。

### 现在有什么

`governance/settings_hash.py` —— 三组输入的指纹：

```python
from governance.settings_hash import settings_payload, assert_same_settings

p = settings_payload(solver_cfg=..., model_options=..., t_eval=..., model_name="DFN")
res = assert_same_settings({"M0": p0, "M1": p1, "M2": p2})
# 不一致 ⇒ ValueError，且**逐字段列出是哪一项变了**（只报"不一致"是无法修的）
```

**四个刻意的设计决定**：

1. **类型带标签**。`1e-6` 与 `"1e-6"` 必须算出不同指纹。这不是文学问题：
   PyBaMM 对 `contact resistance` 要求**字符串** `"true"`，传布尔 `True` 会被
   `OptionError` 拒绝 —— 两者行为不同，绝不能算同一支。同理 `int 1` 与 `float 1.0` 分开。
   *(这一条在开发中被测试抓出一处真 bug：helper 先做了数值规范化，类型标签打在
   已字符串化的值上，等于白打。已修。)*
2. **不引入新输入**。所有输入都能从**已写进现有产物**的字段取到
   （`run_metadata.json` 的 `solver` 块、`model_options`、时间对齐 CSV 的时间列），
   所以可以**事后对已有的 run 复算**，不需要重跑。
3. **只答"同不同"，不答"该不该同"** —— 所以同时给逐字段明细。
4. **浮点规范化到固定有效位**，否则 `1.0e-6` 与 `1e-06` 会算出不同指纹
   （同一个设置被报成不同 = 最坏的一类假阳性；三层比对会被永久拒绝）。

**已声明的边界**（`KNOWN_LIMITS`，必须与结论一起引用）：

- PyBaMM **默认空间网格**（npts / 离散方式）**没有**进指纹 —— 平台不显式设置它。
  若将来有人显式传值，必须同时更新本模块（测试钉住这条）。
- PyBaMM **版本**没进指纹 —— 见 `run_metadata.json` 的 `pybamm_version`，须一起看。
- 指纹只描述**怎么算**，不描述**算哪颗电芯**。

#### 🔧 2026-09-29 修复：缺字段不再静默补默认值

**问题（本次核实新发现）**：`payload_from_run_metadata()` 原实现对缺失字段
**静默套用模块默认值**（`solver_fingerprint(None)` → `IDAKLUSolver` / `rtol=atol=1e-6`）。
而 `solver` / `model_options` 是 **2026-09-28 才写进产物**的 —— 实测**全部 21 份**
历史 `run_metadata.json` **没有一份带 `solver` 块**。后果：

```text
21 份历史产物 → 只有 4 个唯一指纹
  f4ddab4009918178 ← 13 份（calce_20r / calce_a123 / calce_cs2 / chen2020 … 异构）
  ...
```

**13 份不同数据集、不同电芯的 run 共用同一指纹**，而它们当时的求解器设置**不可知**。
⇒ 若用它做三层比对，会得到**虚假的"相同"**。这是本项目最不能接受的**静默失效**，
也违反 `SOUL.md` 的 *fail loud, never silent*。

**修复**（`governance/settings_hash.py`）：

| 新增 | 作用 |
|---|---|
| `REQUIRED_METADATA_FIELDS = ("solver", "model_options", "model")` | 单一事实来源 |
| `missing_fingerprint_fields(meta) -> list` | 列出缺失字段（**空 dict 也算缺失**：它同样没告诉我们任何设置） |
| `MissingSettingsError` | 缺字段时抛的错，**逐条说明缺了什么、为什么、怎么办** |
| `payload_from_run_metadata(..., on_missing=)` | `"raise"`（**默认**）/ `"mark"`（返回 `__unfingerprintable__` 标记供显式排除）/ `"default"`（旧行为，**已弃用**，但 `used_defaults` 会进哈希，使"套默认值"与"真用默认值"**不可混淆**） |

**实测修复效果**（对那 21 份真实历史产物）：

```text
历史产物: 21 份
  默认抛错（拒绝复算）: 21
  mark 模式可显式排除  : 21
  字段完整可复算       : 0
```

⇒ **全部被拒，零份静默给出指纹。** 报错首行示例：

```text
这份 run_metadata.json 缺少指纹所需的字段，**不能复算指纹**：
  缺失：['solver']
  原因：solver / model_options 是 2026-09-28 才写进产物的；
  更早的 run 没有记录它们，所以它们当时的设置**不可知**。
  ⇒ 若在此处套用默认值，会得到一个描述『默认值』而非『那次 run』...
```

**新增测试 9 项**（`tests/test_settings_hash.py`），其中一条是**针对真实产物的回归**：
`test_the_21_real_historical_artifacts_cannot_be_fingerprinted` ——
它遍历 `outputs/platform/**/run_metadata.json`，断言**全部**被拒。
若将来有人给旧产物补了 `solver` 块，这条会失败 ⇒ 那时产物格式已变，文档与本测试须同步更新。

### ★ 还差什么（只有你能做）

跑 M0/M1/M2 时**逐层记录** `settings_hash_per_level`（三层各一个），并在
`settings_identical_across_levels` 写 `true/false`。若 `false`：
**不许下"M2 比 M1 好"的结论**，并把 `assert_same_settings` 的报错原文粘贴进
`settings_diff_detail`。

⚠️ **指纹只能对新跑的 run 用**。对 2026-09-28 之前的历史产物复算会**抛错**
（这是修复后的正确行为，见上）。

---

## 4. 测试

新增 4 个测试文件，**78 项**，全部 additive：

| 文件 | 项数 | 钉住什么 |
|---|---|---|
| `tests/test_geometry_channel.py` | 25 | 缺项整块不给 · 换算口径只有一种（D50/2） · 每键带来源 · 报告行必带 R · **与尺度对齐门不相交** · 不 import 冻结内核（AST 检查） |
| `tests/test_noise_floor.py` | 24 | 已知噪声可恢复 · **去趋势开关必须有效**（关掉时 sigma 必须显著变大——否则它是装饰） · MAD 顶住跳点 · 分辨率下限必报 · 点太少即抛错 |
| `tests/test_settings_hash.py` | **35** | 同设置同指纹（含浮点写法） · **真改了设置必须变且指出哪一项** · bool/str/int/float 不许合并 · 已声明边界写在代码里 · **缺字段不许静默补默认值**（9 项，2026-09-29 新增，含对 21 份真实历史产物的回归） |
| `tests/test_gap_wiring.py` | 13 | **产物里有这些字段**（模块存在不算填上缺口） · 标定字段全部有落点 · **两个 CLI 真能跑** |

**全量回归（WSL + PyBaMM 26.8，平台权威环境）**：

```text
700 passed, 5 warnings in 114.53s
  ← 冻结基线 613 + 三缺口 78 + 缺字段硬门 9 = 700，零失败
```

**原 613 项无一失败** —— 三个模块都是 additive，未触碰冻结内核。
（2026-09-28 首轮为 691；2026-09-29 加上 `settings_hash` 缺字段硬门后为 **700**。）

---

## 5. 现在的动手顺序

```text
今天就能做（零实验成本，不阻塞任何人）
  ① σ_noise 空跑 30 min → python -m user_tools.sigma_noise --csv ... --k <定下来的 k>
     （annex B §A3，N1 判据的唯一输入）
  ② 定 M0-M3 与 L1-L3 的对应表，并把 M3 的自由参数数写实 = 1，子集 = {a0}
     （annex A §2：本轮唯一放开的辨识量是 a0）

数据到手当天
  ③ 填四个实测量 → python -m user_tools.geometry_channel --series ...
     填齐后把 radius_report_line() 贴进报告
  ④ 跑 M0/M1/M2 时逐层记 settings_hash_per_level
     ⚠️ 只能对新跑的 run 用。对 2026-09-28 之前的历史产物复算会**抛错**
        （修复后的正确行为：那些 run 没记录 solver，设置不可知）

已有的、不要重做（annex B §5）
  · 判据冻结（M1/M1b/M2/M3/M4/N1，五词判定，负结果是结果）
  · 参数来源矩阵（A–E 五类）
  · 电芯级分工（01=GITT、02=identification、03=1C holdout）
  · 留出集的数据层强制门（governance/dataset_roles.py）
  · QC 判据（含脉冲协议分级 4 条）

未做的三条（清单第八/九节推荐的"只做三件事"，见 `借鉴清单_落地核实_2026-09-29.md`）
  · 随机负对照（gate_control）—— 唯一能挡回"你是不是筛掉噪声"那一击
  · 层契约（layer_contract）—— 参数集必须只增，现在无人守
  · batch 升级为 error —— 导师要求的"2 炉独立处理"现在靠人写一句话
```

---

## 6. 一句话

**三个缺口里，两个（σ_noise、四个实测量）是"填数"，一个是"接线"（settings_hash）。
机制现在都有了、都有测试、都接进了 `run_record.yaml` —— 剩下的全部是人手里的数。**
