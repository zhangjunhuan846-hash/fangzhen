# 商用石墨热处理梯度（CG-AR → CG-600 → CG-800 → CG-900）

> 这条梯度的科学问题：**热处理条件的变化，能不能被模型参数定量描述？**
> 自变量 = 处理温度；观测量 = 结构表征 + 电化学；输出 = 参数判定 + 预留倍率的预测检验。

实验设计与协议见 `docs/graphite_heat_treatment_test_plan.md`（v2）。
本目录只做一件事：**让这批数据做完当天就能进平台**，而不是做完发现少了一组对照。

---

## 0. 数据到手当天：三条红线（不满足就不许下相应结论）

平台从 2026-09-17 起冻结（`v0.1.0-platform` = `ee2fb36`，**不再移动**）。
之后的验收对象是**真实数据能不能过 L1→L4**，不是代码。下面三条是**结论级**的红线：

| # | 缺什么 | 就不许做什么 |
|---|---|---|
| 1 | **D50 实测**（每个样品重测，不是规格书值） | 不许解释**跨样品**的 `D_s` 差异。`D ∝ R²`，而参数集 R_p 13.70 µm 与本批实测 D50/2 差 1.56× ⇒ `D_s` 差 2.4×；不重测就等于把"粒径变化"读成"扩散变化" |
| 2 | **`protocol_type` + `pulse_duration_s` 声明** | 不许把 GITT 的 QC 结论当**正式证据**。没声明时四条判据会退化成 WARN —— 恰好把最该严的地方放松了 |
| 3 | **`nominal_capacity_Ah` 的实测值 + `capacity_source` + 取值 cycle** | 不许声称 L4 已过尺度一致性。写清来源，例：`formation cycle 3 reversible capacity`；半年后才答得出"这个容量从哪一圈来" |

## 0.1 推进顺序（不许因为某一级失败就绕过去）

```text
L1 数据可信性   四组 metadata / D50 / 载量厚度面积 / 电解液 / Li 对电极 / protocol 声明补齐
                （≥3 颗平行电池：先看**原始值**与一致性）
                        |
L2 回放可信性   **只拿 CG-AR 做**：起始 OCV/x0、容量尺度、电流方向、覆盖率、termination
                —— 这里不过，不铺另外三组
                        |
L3 参数信息量   CG-AR **双向** GITT -> 逐窗口 bandwidth map（不是急着报一条漂亮的 D_s(x)）
                然后再跑 600/800/900
                        |
L4 预测         冻结 identification 得到的参数，直接预测**未参与辨识**的 1C
                —— 不许因为 1C 误差大就回去调参数（那样就不是 holdout 了）
```

**为什么 CG-AR 先跑通整条链再铺开**：平台已经复杂到足以让一个真实数据问题产生很多
"看起来像物理结果"的假象。先用未处理的商业石墨把「实测 → QC → 回放 → 可辨识地图 →
冻结参数 → 1C 预测」走一遍，才能把**实验问题**与**材料差异**拆开；600/800/900 的意义
也才从软件测试变成科研问题。

---

## 1. 四个样品

| sample_id | 处理 | 角色 | 为什么必须有 |
|---|---|---|---|
| **CG-AR** | 未处理（as-received） | **参照系** | 「处理有没有用」只能靠**处理组 vs 未处理对照**；规格书数值不能替代它 |
| **CG-600** | 600 °C 惰性 | 处理组 | 轻度：去表面官能团 / 无定形残碳 |
| **CG-800** | 800 °C 惰性 | 处理组 | 中度：结构部分恢复 |
| **CG-900** | 900 °C 惰性 | 处理组 | 高温：可能重构，也可能烧损（看气氛） |

**四条文件必须同时满足**（`validate_series` 会检查）：
sample_id 唯一；每份都声明工艺史；工艺**至少有一样不同**（否则不是梯度）；
电极几何在样品间一致（否则电极差异会混进参数差异）。

### 1.1 电芯级分工（**组装前定死**）+ 每次 run 的记录

≥3 颗平行电芯**不是**"同一套测试做三遍"：L4 的 holdout 必须落在**另一颗电芯**上。

| 电芯 | 实验轨迹 | 用途 |
|---|---|---|
| **CG-AR-01** | formation → OCV 双支 → **双向 GITT** | L2 / L3 参数与 bandwidth map |
| **CG-AR-02** | formation → 0.2C / 0.5C（**不跑 1C**） | identification / 辅助验证 |
| **CG-AR-03** | formation → **直接 1C**（必要时加 2C） | **L4 独立协议验证** |
| 04（资源允许） | 重复 GITT | 重复性 |

若把 1C 压在同一颗电芯最后，前面各段的嵌/脱锂历史与累计循环都会进入 1C 结果 ⇒
那只是**同一颗电芯的 protocol holdout**，不能写成独立验证。

**每次正式 run 复制一份** `run_record.yaml` 填好存档（字段解释在该文件里）。
最低限度必须同时记两个 commit：`software_commit`（代码状态，`v0.1.0-platform` =
`ee2fb36`，**不再移动**）与 `protocol_docs_commit`（当时的**判据规则**在哪一版文档里）。
论文 Methods 只写 tag 是不够的 —— 判据随后续文档演进。

判据本身在 `docs/preregistration_2026-09-18.md`（**已冻结**：开跑后不得修改，
只能按 §5 版本化 amendment 新增）。**「CG-AR 跑不过」是有效结果**，
不是必须修到通过的 demo。

---

## 2. 数据放哪里（约定路径）

```
data/raw/graphite_ht/<SAMPLE_ID>/
├── raw/electrochemistry/     ← 仪器导出（本模板已按下面这些名字登记）
│   ├── formation_gcd.csv         化成 C/20 × 2 圈（首圈容量、首效）
│   ├── ocp_c20.csv               C/20 充 + C/20 放，**双支分别保存**
│   ├── gitt.csv                  C/10，10 min 脉冲 + 30 min 静置，充放双向
│   ├── gcd_0p1C.csv              0.1C 恒流充放电（容量基准）
│   ├── rate_0p2C.csv             0.2C
│   ├── rate_0p5C.csv             0.5C
│   ├── rate_1C.csv               1C ← **Level 4 留出集**
│   ├── rate_2C.csv               2C
│   └── eis.csv                   100 kHz–10 mHz，10/50/90 % SOC
├── raw/structure/            ← XRD / Raman / BET（+ SEM 粒径）
├── processed/                ← 平台生成的 canonical 表
└── metadata/                 ← 本模板的四个 yaml 放这里（四份文件放一起才算一条梯度）
```

**这些是约定路径，不是已存在的文件。** 自动化只负责按名字找；
文件不在时 `--require-data` 会报出来（见下）。仪器导出的**格式**几乎肯定
和平台现有 adapter 不同 —— 那一步只改 adapter 的两个方法，
见 `docs/adding_a_dataset.md` §2 的 10 个格式问题。

---

## 3. 拿到数据后的第 0 天：三件事

```bash
# 1) 元数据契约（先跑这个：它会逐条列出只有人能填的那 7 个数）
python -m battery_sim.datasets.material_metadata --series templates/commercial_graphite_ht/metadata

# 2) 数据目录与文件是否就位
python -m battery_sim.datasets.recycled_graphite --root data/raw/graphite_ht/CG-AR --require-data

# 3) 端到端（契约 → canonical → 回放 → 参数报告）
python scripts/dev/recycled_graphite_e2e.py --root data/raw/graphite_ht/CG-AR
```

三条都通之后才谈分析。**「跑通」的判据不是 RMSE 低**，见设计文档的验收阶梯 L1–L4。

---

## 4. 模板里哪些是**故意留空**的

每份 yaml 跑一遍会报**恰好 7 个错误**，全是只有实验者才知道的实测量：

```
source / electrode.mass_loading_mg_cm2 / electrode.coating_thickness_um /
electrode.area_cm2 / particle.d50_um / cell.counter_electrode / cell.electrolyte
```

**故意不预填**的原因：预填一个"看起来合理"的数，比留空危险得多 ——
它会安静地进入容量的尺度换算（`Q_model == Q_measured`），
而 **D ∝ R²**，粒径错一倍 = D_s 差 4 倍。

`cell:` 里另有三项**已预填、且不要清空**的锚定声明：`working_electrode_material`
（`graphite`）、`counter_electrode_type`（`lithium_metal`）、`voltage_window_V`
（`[0.005, 1.5]`）。它们不是测量值而是**设计决定**：平台靠它们把"这个体系该用哪个
电压窗口"锚定住（规则表见 `docs/chemistry_windows_and_gitt_qc.md`）。
清空不会报错，只会让窗口检查**被跳过** —— 而「跳过 ≠ 通过」。
⚠️ 顺带记住：`cell.counter_electrode`（自由文本，写给人和审稿人看）与
`cell.counter_electrode_type`（闭集，写给规则表看）**是两个字段，必须都填**。

已预填的是**设计决定**（不是测量值）：样品编号、工艺条件、测量清单与角色、
电极与电芯规格。⚠️ 工艺条件（温度/气氛/时长/升温速率/降温）填的是**设计值**，
做完必须逐项对照管式炉运行记录核实，**以运行记录为准**。

---

## 5. 三个最容易犯的错

1. **把处理条件只写进 sample_id**（`CG_800_Ar_2h`）：那样「两个都叫 800 °C」
   的样品（一个 Ar、一个空气）无法区分 —— 这正是 `processing` 块存在的理由。
2. **拿 1C 曲线回头调参数**：1C 是预留的预测检验集，一旦进入拟合，
   Level 4 就永远无法回答"模型能不能外推"。
3. **不重测粒径**：热处理的失重与破碎会改变粒径，而平台里 D ∝ R²。
   规格书的 D50 = 17.58 µm 是**处理前**的粉。
