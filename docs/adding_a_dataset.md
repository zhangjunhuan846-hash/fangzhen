# 接入一份新数据：4 步 + 一份格式问答清单

> 目标：**实验数据 → dataset adapter → protocol 解析 → scale alignment → PyBaMM replay → identifiability → 参数报告**，
> 全程**不改核心**。自检全绿 + 跑通一次 replay = 接完。

## 0. 平台对数据集的全部要求

一份数据集只要满足这几条，仿真层就能消费它：

| 要求 | 在哪定义 | 缺了会怎样 |
|---|---|---|
| canonical 四列 `time_s / current_A / voltage_V / capacity_Ah` | `battery_sim/datasets/base.py` | 仿真层没有输入 |
| **放电为正**的符号约定 | `battery_sim/datasets/template.py` | 不报错，只是"放电"变"充电" |
| 时间列**相对窗口起点、从 0 开始** | 同上 | 不报错，整条剖面平移 |
| 实测初始 OCV（V） | `get_initial_state` | 模型从错误 SOC 出发（曾有 44.64 mV 缺口） |
| 实测环境温度（°C） | `get_ambient_temperature` | 温度依赖参数用错 |
| `extra.source`（数据从哪来） | `configs/datasets.yaml` | 构造 adapter 时**直接报错** |
| 材料几何（载量/厚度/粒径/面积） | `battery_sim/datasets/material_metadata.py` | 真实材料分析不能做（D ∝ R²） |

通用骨架与自检在 `battery_sim/datasets/template.py`；录制型协议（GITT / p-OCV / 循环）
的 schema 在 `battery_sim/excitation/protocol.py`。

## 1. 四步

```bash
# 1) 复制模板
cp battery_sim/datasets/template.py battery_sim/datasets/<new_name>.py

# 2) 改类名（registry 按 PascalCase(adapter) + "Adapter" 解析）
#    <new_name>  ->  <NewName>Adapter

# 3) 填 4 个 hook（其余方法模板已实现，别重写）
#      read_source_table(cell)                  读源文件，原样返回
#      normalise_source_table(raw, cell)        列重命名 / 单位 / 符号，集中一处
#      select_discharge_window(raw, cell, rate) 切出这一条放电，返回 canonical 四列
#      read_initial_state(cell)                 实测 OCV（V）
#      read_ambient_temperature(cell)           实测温度（°C）；或 yaml 里写 extra.ambient_temperature_C

# 4) configs/datasets.yaml 加一条（必须写 extra.source），然后自检
python -m battery_sim.datasets.template --check <dataset_id>
```

自检会逐条打印：元数据 → 单元 → 每条放电（行数/电压范围/容量）→ 初值/温度 →
容量一致化对比 → 录制型协议能力。**exit code 0 才算接完。**

也可以单独校验一个 canonical CSV（不经过 adapter）：

```bash
python -m battery_sim.datasets.template --canonical outputs/.../some_window.csv
```

## 2. 写代码前必须回答的格式问题

每一条都会**静默**出错（不抛异常，只是结论变脏），所以必须先问清楚再动手。

| # | 问题 | 为什么致命 | 怎么确认 |
|---|---|---|---|
| 1 | 文件编码？Latin-1 / GBK / UTF-8-BOM | 表头错位、列名带乱码 → 按名取列失败 | `python -c "print(open(f,'rb').read()[:200])"` 看字节 |
| 2 | 几行表头？有没有单位行？ | 单位行会被当数据 | 直接看前 5 行 |
| 3 | 分隔符与小数点（`,` / `;` / 逗号做小数） | 整列变字符串 | 同上 |
| 4 | **相位从哪来**：有 `Command` / `Step` 列吗？ | 没有相位就只能靠电压/电流猜，猜错就切错窗口 | 找仪器自带的步骤列 |
| 5 | **电流符号**：放电为正还是负？ | 平台约定**放电为正**；反了激励方向全反 | **在数据内验证**：canonical `I>0` 的时刻电压应当在下降 |
| 6 | 单位：mV/V、mA/A、mAh/Ah、mg vs g | 电压若按 mV 读入，过电位整体差 1000 倍 | 自检会 warn（> 6 V 判为可疑） |
| 7 | 时间基准：绝对时间戳还是相对秒？采样均匀吗？ | 绝对时间戳会让整条剖面平移，电压上看不出来 | 自检检查首点是否为 0、是否严格递增 |
| 8 | 容量列是**积分出来的**还是仪器给的？ | 两列若指不同窗口，容量一致化会算错尺度 | 自检对账：容量跨度 vs ∫I dt |
| 9 | 一个文件里有几个 step？怎么切？ | 多条协议混在一起 → 切错就回放了错的东西 | 统计 step 编号的分布，别只取第一段 |
| 10 | 温度记在哪一列？是环境还是表面？ | 模型里的 ambient 与环境温度不是一回事 | 看仪器通道名 |

**DLR GITT 的三条实测坑**（`battery_sim/datasets/dlr_gitt.py`）：① 文件是 **Latin-1**；
② 相位只能从 **`Command` 列**取；③ Basytec 约定**负=放电**，必须翻转，
且翻转要在数据内验证（canonical `I>0` 与 V 下降同时发生）。

## 3. `dataset_role` 怎么选（治理层会拦）

| 角色 | 允许 calibrate | 允许 evaluate | 什么时候用 |
|---|---|---|---|
| `identification` | ✅ | ✅ | 参数就是**为这份数据**标定的 |
| `validation` | ❌ | ✅ | 想验证迁移能力；把它拿去调参会被 `RoleViolation` 拦下 |
| `benchmark` | ❌ | ✅ | 参数集**不是**为该数据集标定的（surrogate）⇒ 比较**不构成验证** |
| `prediction` | ❌ | ✅ | 只做预测评估 |

顺手在同一个 config 块里写 `dataset_role_note`，说明"为什么它是这个角色"。

## 4. 尺度对齐不是可选项

参数集描述的是**一颗电芯**。拿它去回放另一颗电芯时，同样的安培数是不同的 C-rate，
而**尺度失配与"参数惰性"在输出里完全不可区分**（同一个坑平台踩过两次：G5 113×、G6 31×）。

```bash
# 回放入口默认会检查并对齐（check / align / assume）
python -c "from governance.scale_alignment import audit; print(audit('Ecker2015_graphite_halfcell'))"
```

必看的一行是**两个 C-rate 并列**：`c_rate_on_cell`（读数写的）与
`c_rate_on_model_unscaled`（模型实际跑的）——**只有后者决定固相扩散是否被激发**。
详见 `docs/scale_alignment_gate.md`。

## 5. 材料元数据（真实材料必需）

```bash
cp templates/recycled_graphite/metadata.example.yaml data/raw/LIB/<你的样品>.yaml
# 填完再校验；缺字段会逐条列出，errors = 0 才能开始分析
python -m battery_sim.datasets.template --metadata data/raw/LIB/<你的样品>.yaml
```

参数来源用固定词表（`gitt_fitting / eis_fitting / ocv_derived / literature_prior /
inferred / parameter_set_default / user_override / not_measured`），
因为审稿人一定会问"这个参数怎么来的"，答案必须是可归因的一个词。

## 6. 出报告

```bash
python -m identification.parameter_report \
    --windows outputs/fitting/g6.1c/g6_1c_window_map_charge.csv \
    --dataset dlr_gitt --cell Hydra.0d --protocol-prefix GITT-charge \
    --level-mV 1.0 --limit-dex 0.30 --scan-half-dex 1.0 \
    --mode material --techniques GITT \
    --out outputs/reports/<你的报告>.md
```

判定词只有五个：`identifiable / bounded / not identifiable / unconstrained / not_measured`。
`material` 模式下 synthetic truth、truth recovery 一类字段**会被直接拒绝**（`ModeViolation`），
所以"把模拟结果写成实验结论"这件事在这一层被关掉了。

## 7. 什么算"接完"

- [ ] `python -m battery_sim.datasets.template --check <dataset_id>` 退出码 0
- [ ] 每条放电都通过 canonical 契约（含符号与时间基准）
- [ ] 材料元数据 `errors = 0`
- [ ] `run_protocol_replay`（若这份数据有录制型协议）能跑通至少一个窗口
- [ ] 报告里每个参数要么有判定、要么明确写 `not_measured`（不许留白）
- [ ] `dataset_role` + `dataset_role_note` 已声明

## 8. 常见坑（都是实测踩过的）

- **不许 `import pybamm`**：adapter 是纯数据 I/O 层，这是"换数据集不用动核心"的代价。
- **别重写 `load_discharge`**：它是唯一挂了契约校验的入口，重写等于绕过检查。
- **录制型协议是"覆盖才叫有能力"**：基类定义了 `load_protocol` / `load_processed_protocol`
  并抛 `NotImplementedError`，所以 `hasattr` **恒为真**；判定必须写
  `type(adapter).X is not Base.X`。模板刻意**不覆盖**它们。
- **一条文件里多个 step 不要只取第一段**（SINTEF 的 `gitt` 通道实为 C/44 CC-CV，
  347/347 batch 含多 step，误当 GITT 用了一整轮才发现）。
- **多对象脚本不要写死输出文件名**（曾扫 p-OCV 时覆盖 gitt 结果）。
- **Windows 上 `Path.write_text()` 会把 `\n` 翻成 `\r\n`**：写文件用
  `write_text(..., newline="")` 或 `write_bytes()`。

---

相关文档：`docs/scale_alignment_gate.md`（尺度对齐门）、
`docs/g6.1c_excitation_map.md`（协议与可辨识性的实测关系）、
`templates/recycled_graphite/`（回收石墨空模板）。
