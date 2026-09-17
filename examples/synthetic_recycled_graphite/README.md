# examples/synthetic_recycled_graphite —— 合成夹具（**不是实验数据**）

**注意：这一目录里的每一个数都是模型生成的。**
三个样品（`SYN-fresh` / `SYN-spent` / `SYN-regenerated`）之间的"差异"是一个
**写下来的 D_s 倍率**（1.0 / 0.35 / 0.65）加高斯噪声（σ = 0.3 mV），由**平台自己的
回放路径**生成 —— 生成器：`scripts/dev/make_synthetic_recycled_graphite.py`（4.5 s）。

- **用途**：在真实数据到来前，把 `metadata → adapter → canonical → PyBaMM → report`
  这条链跑通，并让"格式契约"有一份可执行的说明。
- **不许**用它证明任何关于回收石墨的结论。端到端脚本按 **benchmark 模式**出报告，
  并在报告里写明数据是合成的。
- 夹具未做 footprint 缩放（模型就是生成数据的那颗电芯）；真实半电池请保留
  `scale_alignment="check"` 让尺度对齐门先判一次。

## 目录

```
metadata/<sample_id>.yaml          每样品一份（含 recycling 块：身份可追踪）
raw/electrochemistry/<sample>_gcd.csv
raw/electrochemistry/<sample>_gitt.csv
raw/structure/                     空（夹具没有 XRD/Raman/BET）
processed/ocp_graphite.csv         OCP 反演表（两列，无表头）
```

## CSV 格式（adapter 现在只认这个）

```
time_s,current_A,voltage_V,temperature_C,phase,window
```

- `current_A`：**放电为正**（平台约定；Basytec 那类"负=放电"必须先翻转）
- `phase`：`rest` / `discharge` / `pulse`（相当于仪器的 `Command` 列 ——
  相位来自数据，不靠电流符号猜）
- `window`：GITT 窗口编号（1..6）；GCD 留空

夹具里每个 GITT 窗口是 **rest → pulse → rest**（各 600 s），因为平台的活动门与瞬态
指标要用脉冲前的静置算 pre-pulse leakage。

**真实仪器导出几乎肯定不是这个格式**：编码、表头行数、相位列名、单位、符号都要
先按 `docs/adding_a_dataset.md` §2 问清，然后只改 adapter 的
`_read_table` / `normalise_source_table` 两处 —— 切窗口、积分容量、协议解析、
契约校验、初值反演都是平台自带的。

## 重新生成 / 端到端

```bash
python scripts/dev/make_synthetic_recycled_graphite.py     # 重生成夹具
python scripts/dev/recycled_graphite_e2e.py                # 五步端到端（约 10 s）
```

实测（2026-09-17）：GCD 回放与记录对照 RMSE **55.7 / 64.3 / 82.0 mV**
（fresh / regenerated / spent —— 损伤最重的样品偏差最大）；GITT 三个窗口的 1 mV
带宽 **0.52 / 0.19 / 0.03 dex**（窗口越靠后、石墨越满锂，分辨率越好）。
这两个数只说明**链路**按预期工作，不是材料结论。
