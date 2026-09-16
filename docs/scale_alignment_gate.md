# 尺度对齐门（Scale alignment gate）

> **一句话：`Q_model != Q_measured` 会让任何参数看起来"惰性"，而它看起来和"协议不激发"
> 一模一样。所以对齐必须是**辨识之前的一步流程**，不是某个脚本里的一段。**

代码：`governance/scale_alignment.py`　｜　强制入口：`battery_sim/simulation/protocol_replay.py`
测试：`tests/test_scale_alignment.py`

---

## 1. 它为什么必须是一级概念

同一个坑踩了两次，**两次的输出长得完全一样**：

| | 模型（参数集描述的电芯） | 记录实际通过的电荷 | 比值 | 当时的读数 |
|---|---|---|---|---|
| **G5** p-OCV 分支 | 202.398 mAh | 1.7846 mAh | **113×** | "准平衡不激发固相扩散" |
| **G6** DLR GITT | 202.398 mAh | 6.5277 mAh | **31×** | "C/10 脉冲只动 0.4 mV" |

两条结论都是**错的**，而且都是同一个原因：

```text
标称 "C/10" 的脉冲
   在 31× 失配的模型上实际跑的是 C/309        -> 瞬态小 43 倍
在 113× 失配的模型上实际跑的是 C/4670       -> 瞬态几乎为零
```

**判别它到底是"参数没进模型（接线问题）"还是"模型不在同一尺度"**——
把电流整体缩放，看响应是否成比例（G6 实测）：

| 电流倍数 | 施加电流 | sim dV_pulse |
|---|---|---|
| ×1 | 6.5526e-04 A | −0.3943 mV |
| ×10 | 6.5526e-03 A | −4.0192 mV（×10.2）|
| ×100 | 6.5526e-02 A | −29.9199 mV（×75.9）|

成比例 ⇒ **电流确实进了模型** ⇒ 是尺度问题。

> 关键：**这两个原因在输出里不可区分**。残差小、曲线平、参数不动 ——
> 无论根因是"没激励"还是"激励被缩小了 31 倍"，看到的都是同一件事。
> 靠人眼分不开，只能由流程顺序强制分开。

---

## 2. 顺序本身就是结论

```text
Dataset
  |
  v
Geometry audit          参数集自己说自己描述的是多大一颗电芯
  |
  v
Capacity alignment      Q_model == Q_measured        <- 本模块
  |
  v
Protocol excitation     只有对齐之后，"协议是否激发"才是一个问题
  |
  v
Parameter inference     最后才轮到辨识
```

顺序写成机器可读的常量（`PIPELINE_STAGES`），并有测试钉住它：

```python
from governance.scale_alignment import PIPELINE_STAGES
# ('dataset', 'geometry_audit', 'capacity_alignment',
#  'protocol_excitation', 'parameter_inference')
```

**为什么顺序不能换**：跳过前三步直接做第四步，得到的"参数不可辨识"里
混着尺度失配的贡献，**无法归因**——你不能说它是物理的，也不能说它是数值的。
石墨、LFP 回收、硬碳钠电都会踩同一个坑，因为**参数集描述的电芯与手上的电芯
永远不是同一颗**。

---

## 3. 门检查什么：两个 C-rate

这是整个门最实用的一件产物。同一个窗口有两个 C-rate：

```text
c_rate_on_cell            = I_pulse / Q_measured          -> 0.1004   （读数怎么写的）
c_rate_on_model_unscaled  = I_pulse / Q_model             -> 0.003237 （模型实际跑的）
```

**只有第二个决定固相扩散是否被激发**，而报告里历来只写第一个。

```
dlr_gitt / GITT-discharge#t120
  模型容量        : 202.398 mAh  (Ecker2015_graphite_halfcell)
  实测电荷        : 6.5277 mAh   （扫程，见 §4）
  verdict         : MISALIGNED   (31.0x, +1.491 dex, 容差 ±0.05 dex)
  C-rate 读数     : C/10.0
  C-rate 在模型上 : C/309        <- 只有这一个决定物理
```

---

## 4. 两个附属结论（都是踩出来的）

### ① 容量基准必须是**扫程**，不是单个脉冲

一次 pulse-rest 三元组的电荷**只是那一个脉冲**（0.0271 mAh）。
拿它当电芯容量会把模型缩到 **1/7400**，直接撞上电压截止，
产出的瞬态量全是 `NaN` —— **读起来正好像"参数惰性"**。

→ 数据集**声明** `capacity_reference_protocol: "GITT-discharge"`，
契约测试钉住（`test_measured_charge_comes_from_the_record_sweep`）。

### ② 缩放的是电极 footprint，不是 ε_am / 厚度

要达到 31× 的容量比，`ε_am` 会掉到 **0.012**、厚度掉到 **2.4 µm** —— 物理上荒谬。
缩放面积（长宽各 ×√scale，保持长宽比）得到的几何仍在合理范围
（DLR：长宽各 ×0.1796 → 约 18.2 × 15.3 mm）。

---

## 5. 接口

```python
from governance.scale_alignment import audit, assert_aligned, alignment_overrides

rec = audit(adapter, protocol_id, cell)          # 完整记录，含两个 C-rate，不抛异常
rec["verdict"]                                   # "aligned" | "misaligned"

assert_aligned(adapter, protocol_id, cell)       # 不对齐则抛 ScaleMisalignment

al = alignment_overrides(adapter, protocol_id, cell)
replay(parameter_overrides=al["overrides"],      # 放进任何回放的覆盖位
       parameter_override_sources=al["source"])  # 溯源与其它覆盖同构
```

**`ScaleMisalignment` 是独立异常类型，不是 `ValueError`** —— 尺度失配是**可修的**
（返回值里带配方），参数名写错不是。两者混进同一类型，就是它们被混为一谈的开始。

### 强制点在哪里

平台冻结内核（runner / evaluator / factory / registry / `rates.py` / `paths.py`）**一行未改**。
强制放在**新增的** protocol replay 入口上：

```python
run_protocol_replay(..., scale_alignment=None)   # 默认 "check"：不对齐就拒绝跑
run_protocol_replay(..., scale_alignment="align")   # 自动施加 footprint 配方
run_protocol_replay(..., scale_alignment="assume")  # 声明"我知道自己在做什么"
```

`assume` 会在 `run_metadata.json` 里留下
`scale_alignment.verdict == "assumed_by_caller"`，并明写"没有证据表明它真的对齐"——
**豁免是可以的，静默不可以。**

`align` 模式下若调用方自己已经覆盖了 footprint 键，**直接报错**而不是覆盖：
两个来源喂同一个数，溯源链就断在那儿了。

---

## 6. 边界（必须一起引用）

- **对齐是构造出来的前提，不是测量。** DLR 电芯的几何（面积、厚度、负载）**没有数据手册**，
  footprint 是按**实测电荷**反推的。对齐之后模型**每安时对应的倍率**是对的，
  **但它的面积、厚度、负载不一定与真实电芯相同** —— 只能说"尺度对了"，
  不能说"几何对了"。
- **容差是声明，不是推导。** `±0.05 dex ≈ ±12 %` 的任务是拦住 31× / 113× 这一量级，
  不是拦住 5 % 的批次差异。有测试专门证明它是声明值
  （`test_verdict_is_a_declared_tolerance_not_a_hidden_constant`：
  同一组数字，容差放宽到 5 dex，verdict 必须翻面）。
- **对齐不修复模型形式误差。** 它只保证激励落在正确的刻度上；
  模型对不对是另一件事（G5.2 的全部内容）。
- **不适用于已经同尺度的回放。** 参数集就是该电芯自己的时候
  （例如 `chen2020` 配它自己的数据），正确动作是 `scale_alignment="assume"` 并把
  理由写出来，而不是让 footprint 被缩到 0.03 —— 那会引入一个新的失配。
