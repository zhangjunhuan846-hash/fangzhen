# L4 倍率预测验收：用低倍率辨识的参数预测另一个倍率

> 入口：`python -m identification.rate_prediction`（新文件 `identification/rate_prediction.py`）
> 夹具：`examples/synthetic_rate_ladder/`（合成，不是实验数据）
> 生成器：`scripts/dev/make_synthetic_rate_ladder.py`

## 为什么需要它

平台到 v0.1 能证明的是**回放**：把实测电流喂进去，模型走出接近的电压。
那**不构成预测能力** —— 回放用的是同一段数据，参数也可能是从它里面调出来的。
论文的看点是这条链：

```text
低倍率（辨识集） -> 参数（D_s 等） -> 高倍率（留出集） -> 与实测比
```

所以这个脚本只做一件事：把「辨识」与「被预测的倍率」当成两份**分别声明**的数据集，
在**角色门**与**尺度门**后面跑一次回放，把误差如实报出来，并拒绝三种会让结论失效的情形。

## 四道门（缺一个，报告就不能引用）

| 门 | 拦什么 | 行为 |
| --- | --- | --- |
| 角色门 | 目标数据集的 `dataset_role` 是 `identification` | **拒绝**（拿辨识集当留出集 = 对自己评分）。确实只验链路要显式 `--allow-identification-target` + 理由，理由进报告 |
| 角色门（弱） | 目标是 `benchmark` / 未声明 | 允许，但报告写明「参数集非为它标定 ⇒ 不构成验证」/「无法证明它不是辨识集」 |
| 尺度门 | 模型标称容量 vs **电芯声明容量** | `|log10(比)| > 0.05 dex` -> `ScaleMisaligned`（`--alignment assume` 可继续但记录豁免） |
| 覆盖门 | 目标倍率的比较区间覆盖率 < 0.80 | **记失败，不给 RMSE 结论**（在残片上打分会让错参数看起来很好） |
| 初值接线门 | 回放起点与记录起点差 > 30 mV | **记失败**：这是初值没带上，不是模型误差（见下） |

**尺度判据用的是电芯标称容量，不是窗口电荷**。这个区别必须写下来：
一份只跑 30 % DoD 的 GCD，窗口电荷本来就只有容量的 0.3 倍，
拿它当分母会把"正常的部分窗口"误判成尺度失配（首版真踩到了，已修）。
平台真正要挡的是「模型是 156 mAh 的电芯、记录来自 2 mAh 硬币电池」那一类
（G6 的 31×、G5 的 113×）。

## 用法

夹具（两分钟跑完，含负对照）：

```bash
python -m identification.rate_prediction \
  --fit-dataset synth_ladder_ident  --fit-rate C0p2 \
  --fit-root examples/synthetic_rate_ladder/ident \
  --target-dataset synth_ladder_holdout --target-rate C1 \
  --target-root examples/synthetic_rate_ladder/holdout \
  --overrides examples/synthetic_rate_ladder/overrides_truth.json \
  --roles-config examples/synthetic_rate_ladder/datasets_roles.yaml \
  --target-nominal-capacity-Ah 0.15625 --fit-nominal-capacity-Ah 0.15625
```

真实石墨（数据到位、`datasets.yaml` 合并了 `_holdout_1C` 条目之后）：

```bash
python -m identification.rate_prediction \
  --fit-dataset graphite_ht_cg_800 --fit-rate C0p2 \
  --target-dataset graphite_ht_cg_800_holdout --target-rate C1 \
  --overrides outputs/analysis/l4/cg800_identified.json
```

`--overrides` 是**唯一**的参数入口：

```json
{
  "provenance": "从 CG-800 的 0.1C + GITT 辨识（<命令/日期>）",
  "overrides": {
    "Ds": {"shape": "constant", "amplitude_dex": -0.42},
    "Contact resistance [Ohm]": 12.5
  },
  "sources": {"Ds": {"source": "gitt_fitting", "note": "apparent D_s；R 用 D50/2"}}
}
```

- `Ds` 是石墨半电池扩散系数的简写，会展开成真正的 pybamm 键；其余键写错会 `KeyError`（不静默）。
- 函数型参数只能走 `{shape, amplitude_dex}` 形态（内部就是
  `identification.representations.shape_override`）：JSON 放不下 callable，
  而"看起来像数字"的覆盖会让 pybamm 去覆盖另一个量。
- 形状名取自 `SHAPE_NAMES`（constant / linear / three-region）。

## 报告里写死的三条口径

1. **这是倍率外推，不是独立样品验证。** 同一样品的两个倍率是同一次实验的两段；
   跨样品泛化要靠平行样品（设计里每组 ≥3 颗）另行检验。
2. **拟合好 ≠ 参数对 ≠ 物理可迁移。** G5.2 实测：错误模型假设下真值**不是**最优解
   （偏 −25 % 的参数拟合反而好 3.4×）。
3. **被判定的角色是声明出来的，不是证明出来的。** 报告只证明
   「没有把目标倍率用于辨识」这件事被 `governance/dataset_roles` 拦过。

## 实测结果（2026-09-17，合成倍率梯夹具）

| 运行 | 目标倍率 C1 的 RMSE | 覆盖 | 判定 |
| --- | --- | --- | --- |
| 真值参数（D_s ×0.35，即生成夹具用的那套） | **3.27 mV** | 100 % | PASS |
| 零拟合负对照（不做覆盖） | **20.09 mV** | 100 % | PASS（但差 6×） |
| 目标声明成 `identification` | — | — | **拒绝**（角色门） |

负对照差 6 倍说明这条链**有分辨力**，不是"什么参数都过得去"。
夹具也不是成绩：真值是脚本里写死的倍率，只能验链路。

## 首轮暴露的真实缺口（已修，记录在案）

首版跑夹具时真值参数也给出 **59.9 mV**，看着像"模型不对"。两个原因，都不是模型：

1. **GCD 路径没带初值。** `RecycledGraphiteAdapter` 实现了
   `initialisation_block()`，但模板默认的 `load_processed_discharge` 只挂
   `contract_check` / `canonical_convention`；于是半电池回放从**参数集默认初值**
   出发（实测起点 1.453 V，而记录起点 0.745 V）。协议路径一直带着这个块，
   GCD 路径漏了。修法：在 adapter 里覆盖 `load_processed_discharge` 挂上它
   （与 sintef / dlr / birmingham 各自的做法一致）。
   这条对**真实石墨实验同样致命**：0.1C GCD 回放以前是拿错初值跑的。
2. **稀相端初值反演病态。** 夹具原先从 x0 = 0.01 出发，而石墨 OCP 在稀相端极陡
   （本参数集实测 OCP(0.01) = 0.780 V、OCP(0.10) = 0.218 V）。400 点表的
   分辨率就足以造出 **90 mV** 的起点差。修法：夹具换到良态工作点 x0 = 0.40
   （斜率 ~1.2 mV 每 0.01 x）。**真实实验的推论**：若从极稀相端起步，
   初值反演的误差会直接进 RMSE，报告里要连带给出静置 OCV 与反演出的 x0。

这两条现在都有门看着（初值接线门 30 mV），所以同类故障下次会被拦在报告之前。

## 已知边界

- **`--alignment align` 不存在**：GCD 回放路径不吃 footprint 配方。
  尺度失配的正解是换几何/容量匹配的参数集，不是在回放里缩电流。
- 尺度判定需要**声明**标称容量（注册数据集从 `configs/datasets.yaml` 读；
  未注册数据用 `--*-nominal-capacity-Ah`）。给不出就判"未知"，
  报告里不许写成 aligned。
- 目标倍率与辨识倍率**必须来自同一份电芯记录体系**；脚本不检查这一点
  （无法自动判断），报告里必须写清是哪颗电芯。
