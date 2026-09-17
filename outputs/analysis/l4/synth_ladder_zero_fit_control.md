# L4 倍率预测验收 — synth_ladder_holdout

**链路判定：PASS**（synth_ladder_holdout/C1 用 synth_ladder_ident/C0p2 辨识的参数预测）

## 一句话结论

模型在**未参与辨识的倍率** C1 上，与实测电压的 RMSE = **20.09 mV**（覆盖 100.0%，82 个比较点）。这只说明链路可跑、参数可迁移到该倍率，**不等于**这套参数是物理正确的（见下面「口径」）。

## 输入

- 辨识侧：`synth_ladder_ident` / 倍率 `C0p2`（role = `identification`）—— in-sample 对照
- 目标侧：`synth_ladder_holdout` / 倍率 `C1`（role = `validation`）—— 留出集
- 模型：`SPM`，参数集 `Ecker2015_graphite_halfcell`
- 参数覆盖：Positive particle diffusivity [m2.s-1]
- 参数来源：SYNTHETIC FIXTURE 负对照：不做任何覆盖（等于零拟合回放）

## 结果

| 量 | 辨识倍率（in-sample） | 留出倍率（预测） |
| --- | --- | --- |
| 倍率 | `C0p2` | `C1` |
| RMSE / mV | 16.05 | **20.09** |
| MAE / mV | 11.09 | 15.35 |
| bias / mV | 11.05 | 15.33 |
| 最大偏差 / mV | 32.87 | 52.22 |
| 覆盖 | 100.0% | 100.0% |
| 回放起点偏移 / mV | -0.3 | -0.3 |

「回放起点偏移」是**接线**检查：半电池回放必须从实测静置 OCV 反演出的初值出发。若这个数很大，先修初值再接结论 —— 否则量到的是初值差，不是模型误差。

### 两个 C-rate 必须并列

- `c_rate_on_cell` = **4.4444**（由记录的 max/median 电流与实测扫程电荷算出）
- `c_rate_on_model_unscaled` = **1.0000**（按参数集标称容量算出）
- 模型标称容量 156.250 mAh vs 电芯声明容量 156.250 mAh ⇒ 比值 1.00×，判定 `aligned`（容差 ±0.05 dex）
- 本次窗口只走了模型容量的 22.5%（部分窗口的 GCD 天然小于满容量，这个数是**信息**不是判据）
- **只有第二个数决定固相扩散是否被激发。**只报第一个数是「C/10 变成 C/309」那次事故的写法。

## 口径（写死在渲染器里，避免被略过）

1. **这是倍率外推，不是独立样品验证。** 同一样品的两个倍率是同一次实验的两段；跨样品泛化要靠平行样品（设计里每组 ≥3 颗）另行检验。
2. **拟合好 ≠ 参数对 ≠ 物理可迁移。** G5.2 已实测：在错误的模型假设下，真值**不是**最优解（偏 −25 % 的参数拟合反而好 3.4×）。所以「预测误差小」只说明这套参数在这个倍率上自洽。
3. **被判定的角色是声明出来的，不是证明出来的。** 本报告只证明「没有把目标倍率用于辨识」这件事被代码拦过（governance.dataset_roles）。

## 运行产物

- 辨识侧：`/mnt/c/Users/24330/WorkBuddy/仿真模拟/outputs/platform/synth_ladder_ident/baseline/SPM/cellSYN-LADDER`
- 目标侧：`/mnt/c/Users/24330/WorkBuddy/仿真模拟/outputs/platform/synth_ladder_holdout/baseline/SPM/cellSYN-LADDER`
- 两者的 `run_metadata.json` 里 `parameter_overrides_applied` 是**实际生效**的覆盖（与请求分开记录，见 baseline 的 v0.7 契约）。
