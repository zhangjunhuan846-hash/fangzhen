# 参数可辨识性报告 — dlr_gitt/Hydra.0b_A

- 分析模式：`material` —— 真实材料分析，禁止 synthetic truth / truth recovery
- 判据：**1 mV** 水平上的带宽上限 **0.300 dex**；扫描 ±1 dex（共 2.0 dex）
- 输入产物：`(G6.2a shape scan)`
- `dataset_role`: `benchmark`

## 判定

| 参数 | 判定 | 依据协议 | 带宽 (dex) | 分辨率 (dex) | 证据 | 说明 |
|---|---|---|---|---|---|---|
| `Ds[constant]` | **identifiable** | `GITT-charge#t475` | 0.0988 | 0.050 | GITT | 未截断且 0.099 dex <= 判据 0.300 dex（水平 1 mV），可以引用数值（分辨率 0.0500 dex）；峰值 model-to-model RMSE 64.802 mV |
| `Ds[linear]` | **identifiable** | `GITT-charge#t475` | 0.0359 | 0.050 | GITT | 未截断且 0.036 dex <= 判据 0.300 dex（水平 1 mV），可以引用数值（分辨率 0.0500 dex）；峰值 model-to-model RMSE 58.394 mV |
| `Ds[three_region]` | **identifiable** | `GITT-charge#t475` | 0.1371 | 0.050 | GITT | 未截断且 0.137 dex <= 判据 0.300 dex（水平 1 mV），可以引用数值（分辨率 0.0500 dex）；峰值 model-to-model RMSE 38.207 mV |
| `k0` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |
| `Rct` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |

## 一句话汇总

```text
dlr_gitt/Hydra.0b_A
  Ds[constant]: identifiable  (GITT-charge#t475)
  Ds[linear]: identifiable  (GITT-charge#t475)
  Ds[three_region]: identifiable  (GITT-charge#t475)
  k0  : not_measured  [这份数据里没有对应激励，不许给判定]
  Rct : not_measured  [这份数据里没有对应激励，不许给判定]
```

## 边界（引用结论时必须一起引用）

- 分析模式 'material' 但 dataset_role='benchmark'：可以做真实材料的一致性检查，**不构成对该材料参数集的验证**（参数集非为它标定）
- 带宽是 **model-to-model** 量：观测由同一个模型在同尺度下产生，没有实验噪声、也没有模型形式差异 ⇒ 这是**理想条件下的最好情况**。
- 判据 0.300 dex 与水平 1 mV 都是**声明**值，不是数据的噪声水平（本条记录里没有噪声模型）。
- 本门只验接口（override → 模型 → provenance → 报告），**不构成任何 D_s(x) 形状的辨识结论**。
- 形状幅度按 RMS 归一化后可比（1 dex 扫描）；three_region 只用了**一个**方向（两端 vs 中段），不是三个自由系数。
