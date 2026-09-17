# 合成倍率梯夹具（SYNTHETIC）

**不是实验数据。** 两个目录的曲线由平台自己的回放路径用写死的 D_s 倍率（×0.35）生成，唯一用途是把 L4 预测链（辨识侧参数 → 留出倍率 → 与记录比）跑通，并让角色门/尺度门/覆盖率门都有东西可拦。

两点必须知道的事实（否则会被读成 bug）：

1. **1C 那一档会先撞到参数集的电压下限**（`Lower voltage cut-off`），所以它只走了更小的 DoD、比较区间也更短。这正是倍率能力的物理来源，不是夹具生成出错。
2. 初值取的是平台上 x0 = 0.40（**不是** 0.01）：稀相端 OCP 太陡，反演误差会被放大成几十 mV 的起点差。

```bash
python -m identification.rate_prediction \
  --fit-dataset synth_ladder_ident --fit-rate C0p2 --fit-root examples/synthetic_rate_ladder/ident \
  --target-dataset synth_ladder_holdout --target-rate C1 --target-root examples/synthetic_rate_ladder/holdout \
  --overrides examples/synthetic_rate_ladder/overrides_truth.json \
  --roles-config examples/synthetic_rate_ladder/datasets_roles.yaml \
  --target-nominal-capacity-Ah 0.15625 --fit-nominal-capacity-Ah 0.15625
```

负对照（应当明显更差，用来证明这条链有分辨力）：

```bash
python -m identification.rate_prediction \
  <同上> --overrides examples/synthetic_rate_ladder/overrides_zero_fit_control.json
```
