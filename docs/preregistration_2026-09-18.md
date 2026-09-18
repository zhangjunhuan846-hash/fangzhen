# 预注册：CG-AR 的 L1–L4 验收（**判据冻结**）

> **性质**：在看 CG-AR 正式结果**之前**把判据、数据分工、放行条件写死。
> 这是**判据冻结**，不是代码冻结 —— 两者是两件事，必须分开记录（见 §1）。
> **一旦开跑，§3 的判据不得事后修改**；只能通过 §5 的版本化 amendment 新增，并写清
> 「改动发生在看结果之前还是之后」。
> 日期：2026-09-18 定稿 ｜ 适用范围：CG-AR（第一颗通过 L1–L4 的样品）

---

## 1. 版本三元组：每次正式 run 必须记录

| 项 | 值 | 说明 |
| --- | --- | --- |
| `software_baseline` | `v0.1.0-platform` | **代码**状态的名字 |
| `software_commit` | `ee2fb36` | 该 tag 指向的 commit；**从此不再移动** |
| `protocol_docs_commit` | 本次 run 时的 HEAD（例 `cc76f30`） | **判据规则**在哪一版文档里 |
| `preregistration` | 本文件 | 判据冻结的那一份 |
| `sample_id` / `cell_id` | 例 `CG-AR` / `CG-AR-03` | 电芯级，不是样品级（见 §2） |
| `dataset_hash` | 见下 | 数据目录的内容指纹 |
| `analysis_date` | YYYY-MM-DD | 跑分析那天 |

**为什么必须写两个 commit**：`v0.1.0-platform` 指向某个**代码**状态，而 L1–L4 的
**规则**随后续文档演进。论文 Methods 若只写「使用 v0.1.0-platform」，读者无法知道
当时采用的是哪一版判据。反过来，只写 docs commit 也不够 —— 代码基线要能回溯到具体 SHA。

**`dataset_hash` 的算法**（不新增字段，一条命令即可复现；在 WSL 里跑）：

```bash
cd data/raw/graphite_ht/CG-AR && \
  find . -type f | LC_ALL=C sort | xargs sha256sum | sha256sum
```

（对「排序后的 (相对路径, 文件哈希) 列表」再取一次 sha256。**只统计原始数据目录**，
不含 `processed/` 与 `outputs/`。）

每跑一次正式分析，就复制 `templates/commercial_graphite_ht/run_record.yaml` 填一份存档。

---

## 2. 数据分工（**组装前定死**，L4 的 holdout 必须是独立平行电芯）

| 电芯 | 实验轨迹 | 用途 |
| --- | --- | --- |
| **CG-AR-01** | formation → OCV 双支 → **双向 GITT** | L2 / L3 的参数与 bandwidth map |
| **CG-AR-02** | formation → 0.2C / 0.5C（**不跑 1C**） | identification / 辅助验证 |
| **CG-AR-03** | formation → **直接 1C**（必要时加 2C） | **L4 独立协议验证** |
| CG-AR-04（资源允许时） | 重复 GITT | 重复性（同一轨迹两次，量化带宽图的可重复性） |

**为什么必须拆电芯**：GITT 本身很长；若把 1C 压在同一颗电芯的最后，前面的嵌/脱锂历史、
SEI 继续演化与累计循环都会进入 1C 的结果里。这样得到的只是
**同一电芯历史条件下的 protocol holdout**，不能称为独立泛化验证。

**这句话可以写、也只能这样写**：

> 参数来自一套实验轨迹（CG-AR-01/02）；1C 数据在参数冻结前未参与任何辨识，
> 且来自**独立平行电芯**（CG-AR-03）。

**若最终只有 1 颗电芯**（所有段压在一起）：L4 的结果**只能**写成
「同一电芯历史条件下的 protocol holdout」，**不得**出现「独立验证 / 泛化验证」字样。
这条是措辞判据，写在冻结文件里，避免事后辩解。

三条红线（不满足就不许下相应结论，细则见
`templates/commercial_graphite_ht/README.md` §0）：

1. **D50 没实测** ⇒ 不解释跨样品 `D_s` 差异（`D ∝ R²`）。
2. **`protocol_type` / `pulse_duration_s` 没声明** ⇒ GITT QC 结论不作正式证据。
3. **`nominal_capacity_Ah` 无来源明确的实测值** ⇒ 不声称 L4 过尺度一致性
   （并记 `capacity_source` 与取值 cycle，例 `formation cycle 3 reversible capacity`）。

---

## 3. 判据（冻结，开跑后不得修改）

### 3.1 放行顺序

```text
L1 -> L2 -> L3 -> L4      某一级不过，不许绕过；CG-AR 不过，不铺 600/800/900
```

### 3.2 L1 数据可信性

- 四组 metadata 的 7 个人填量补齐；`material_metadata --series` 错误 = **0**
- **D50 实测**（每样品重测）；`protocol_type` + `pulse_duration_s` 已声明；
  `nominal_capacity_Ah` + `capacity_source` + 取值 cycle 已记录
- ≥3 颗平行电池：先看**原始值**与一致性（不看拟合，不看 RMSE）
- 判据：以上**逐项有值且无缺失**；QC 的 FAIL 数 = 0

### 3.3 L2 回放可信性（**只用 CG-AR**）

必须逐项有值、且无异常标记：

| 项 | 异常门槛（越过即判 L2 不过） |
| --- | --- |
| 起始 OCV / x0 | 回放起点与记录起点差 > **30 mV** |
| 容量尺度 | 两个 C-rate 必须并列；尺度判定 ≠ `aligned` |
| 电流方向 | `CURRENT_SIGN_CONFLICT` |
| 覆盖率 | < **80 %** |
| termination | 未记录终止原因（或与声明协议不符） |

**RMSE 只记录，不作判据。** 这里不过，不铺另外三组。

### 3.3b L3 参数信息量（CG-AR-01，双向分别跑）

产出形态 = **逐窗口 bandwidth map + 五词判定**，不是一条漂亮的 `D_s(x)`。

冻结的统计量（与 G6.1c 同口径）：水平 **1 mV**；`B` = 使 model-to-model RMSE 回到
1 mV 所需的 `a0` 位移（dex）；扫描半宽 **±1.0 dex**（全宽 2.0 dex）；
**上限 0.30 dex**；中位分辨率 ≤ **0.10 dex**。

判据族沿用 `docs/g6.1c_excitation_map.md` 的**预先登记编号**：

| # | 判据 | 阈值 |
| --- | --- | --- |
| **M1** | 存在性：至少一个窗口 `B ≤ 0.30` dex，且**未被截断** | ≥1 |
| M1b | 同上，参考点换成 `a0 = −0.5`（G6.1c 里是冒烟后追加，标 secondary） | 同 M1 |
| **M2** | 筛选性：按**实测** `|dV_pulse|` 的 top-10 与按 `B` 的 top-10 重叠 | ≥ 5 |
| M3 | 单侧性：全部窗口的曲率不对称量中位数 < 0 | — |
| M4 | 分辨率：`B` 的中位分辨率 ≤ 0.10 dex | — |
| N1 | 负对照：零激励窗口代价面**精确平坦**且两侧都被截断 | — |

⚠️ **编号只到 M4 / N1，没有 M5–M9** —— 引用时不要凭印象补号。

五词判定：`identifiable` / `not identifiable` / `bounded` / `unconstrained`
（+ 显式 `not_measured`）。**`D_s` 只有 `identifiable` 才报数值；`bounded` 只报界。**

### 3.4 L4 预测（冻结参数，预测 CG-AR-03 的 1C）

- 入口：`python -m identification.rate_prediction`（四道门：角色 / 尺度 / 覆盖率 / 初值接线）
- 参数**一个都不回改**（回改即整条 L4 作废）
- 判据 = **四道门全过 + 如实报 RMSE**。
  **不设「RMSE 必须小于 X mV」的门** —— 判据不是 RMSE 低。
- 目标倍率的记录来自 **CG-AR-03**（独立平行电芯），不是 01/02 的某一段。

### 3.5 措辞（内部枚举 ≠ 稿件用词）

| 内部 | 稿件 |
| --- | --- |
| `bounded` | 只报界（不给点估计） |
| `not_measured`（EIS/k0/Rct） | **measured, but not inferred by the current pipeline** |
| `benchmark` 角色数据上的比较 | surrogate，**不构成验证** |
| 同一电芯不同倍率 | 倍率外推（protocol holdout），**不是**独立验证 |

---

## 4. 什么算有效结果（这是 falsification test，不是必须成功的 demo）

- **有效正结果**：L1–L4 全过。
- **有效负结果**：QC / 尺度 / 初值 / 独立 holdout 四道门都过，但 L3 出现大量
  `bounded`/`unconstrained`，或 L4 预测失败 ⇒ **仍然是有效科学结果**，照实报。
  这不是假想：**G6.1c 在公开石墨数据上已经出现过**（放电扫程 239 个窗口一个都不合格）。
- **不可接受的做法**：靠继续改平台、改判据、回头调参，把它"修到通过"。
- **报负结果时必须同时报出哪一道门是干净通过的** —— 否则读者无法区分
  「模型不行」与「链路没接对」。

---

## 5. 变更程序（判据只能这样改）

1. 新版本：`docs/preregistration_<date>_v2.md`（本文件不改写）。
2. 逐条写明：改了哪一条 / 为什么 / **改动发生在看到结果之前还是之后**（这一句必须写）。
3. 看到结果之后再新增的判据，一律标 **secondary**，不参与结论
   （沿用 G6.1c 里 M1b 的做法）。
4. 平台侧任何改动走 **`v0.1.1`** 或实验分支；`v0.1.0-platform` **不再移动**。

---

## 6. 一页速查

```text
代码：冻结（v0.1.0-platform = ee2fb36）
判据：冻结（本文件）
先只做 CG-AR；不过 L1–L4 就不铺 CG-600/800/900
holdout = CG-AR-03 的 1C（独立平行电芯），参数冻结前不参与辨识
负结果是结果
```
