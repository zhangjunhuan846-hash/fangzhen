# 参数可辨识性报告 — dlr_gitt/Hydra.0b

- 分析模式：`material` —— 真实材料分析，禁止 synthetic truth / truth recovery
- 判据：**1 mV** 水平上的带宽上限 **0.300 dex**；扫描 ±1 dex（共 2.0 dex）
- 输入产物：`outputs/fitting/g6.1c/g6_1c_window_map_discharge.csv`
- `dataset_role`: `benchmark`

## 扫描概况

- 窗口 239 个，其中可回放 225 个；0 个在整个扫描区间内连 1 mV 都推不到
- 未截断 70 个；其中带宽低于判据的 **0 个**

## 判定

| 参数 | 判定 | 依据协议 | 带宽 (dex) | 分辨率 (dex) | 证据 | 说明 |
|---|---|---|---|---|---|---|
| `Ds` | **not identifiable** | `GITT-discharge#t224` | 0.3261 | 0.050 | GITT | 未截断但 0.326 dex > 判据 0.300 dex：该参数对观测确有影响，但在 1 mV 水平上约束不够（分辨率 0.0500 dex）；该窗口有 17 个探针点不可达（模型有效域边缘）；x0 = 0.9778；实测脉冲 \|dV\| = 12.4 mV |
| `k0` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |
| `Rct` | **not_measured** | — | — | — | EIS | 本数据集没有 EIS 测量（缺 EIS） |

## 一句话汇总

```text
dlr_gitt/Hydra.0b
  Ds  : not identifiable  (GITT-discharge#t224)  [有影响但带宽超过判据，不许报数]
  k0  : not_measured  [这份数据里没有对应激励，不许给判定]
  Rct : not_measured  [这份数据里没有对应激励，不许给判定]
```

## 边界（引用结论时必须一起引用）

- 分析模式 'material' 但 dataset_role='benchmark'：可以做真实材料的一致性检查，**不构成对该材料参数集的验证**（参数集非为它标定）
- 带宽是 **model-to-model** 量：观测由同一个模型在同尺度下产生，没有实验噪声、也没有模型形式差异 ⇒ 这是**理想条件下的最好情况**。
- 判据 0.300 dex 与水平 1 mV 都是**声明**值，不是数据的噪声水平（本条记录里没有噪声模型）。
