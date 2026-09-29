# 参数可辨识性报告 — synthetic_recycled_graphite/SYN-fresh

- 分析模式：`benchmark` —— 允许 synthetic truth / truth recovery
- 判据：**1 mV** 水平上的带宽上限 **0.300 dex**；扫描 ±1 dex（共 2.0 dex）
- 输入产物：`examples/synthetic_recycled_graphite（合成夹具）`

## 判定

| 参数 | 判定 | 依据协议 | 带宽 (dex) | 分辨率 (dex) | 证据 | 说明 |
|---|---|---|---|---|---|---|
| `Ds[GITT#w2]` | **not identifiable** | `SYN-fresh/GITT#w2` | 0.5199 | 0.100 | GITT | 未截断但 0.520 dex > 判据 0.300 dex：该参数对观测确有影响，但在 1 mV 水平上约束不够（分辨率 0.1000 dex）；峰值 15.334 mV；3 段 |
| `Ds[GITT#w4]` | **identifiable** | `SYN-fresh/GITT#w4` | 0.1870 | 0.100 | GITT | 未截断且 0.187 dex <= 判据 0.300 dex（水平 1 mV），可以引用数值（分辨率 0.1000 dex）；峰值 12.935 mV；3 段 |
| `Ds[GITT#w6]` | **identifiable** | `SYN-fresh/GITT#w6` | 0.0282 | 0.100 | GITT | 未截断且 0.028 dex <= 判据 0.300 dex（水平 1 mV），可以引用数值（分辨率 0.1000 dex）；峰值 28.104 mV；3 段 |
| `k0` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |
| `Rct` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |

## 一句话汇总

```text
synthetic_recycled_graphite/SYN-fresh
  Ds[GITT#w2]: not identifiable  (SYN-fresh/GITT#w2)  [有影响但带宽超过判据，不许报数]
  Ds[GITT#w4]: identifiable  (SYN-fresh/GITT#w4)
  Ds[GITT#w6]: identifiable  (SYN-fresh/GITT#w6)
  k0  : not_measured  [这份数据里没有对应激励，不许给判定]
  Rct : not_measured  [这份数据里没有对应激励，不许给判定]
```

## 边界（引用结论时必须一起引用）

- 带宽是 **model-to-model** 量：观测由同一个模型在同尺度下产生，没有实验噪声、也没有模型形式差异 ⇒ 这是**理想条件下的最好情况**。
- 判据 0.300 dex 与水平 1 mV 都是**声明**值，不是数据的噪声水平（本条记录里没有噪声模型）。
- **数据是合成夹具，不是实验样品**：三个状态的差异是一个写下来的 D_s 倍率 + 高斯噪声，由平台自己的回放路径生成。
- 本步只证明链路（metadata → adapter → canonical → PyBaMM → report）通了，不构成任何关于回收石墨的结论。
- 夹具未做 footprint 缩放（模型就是生成数据的那颗电芯）；真实半电池请用 scale_alignment='check' 让尺度对齐门先判一次。
