#

范围：`data/` 新下载的石墨相关数据集（SINTEF / DLR / ISU-UConn / Oxford）  
方法：只读探测（parquet schema + 统计 + 段结构分析），未做任何转换或写入  
脚本：`scripts/triage_graphite_datasets.py`、`scripts/triage_graphite_pocv.py`、  
`scripts/triage_graphite_rest.py`

---

## 0. 结论速览

| 数据集                       | 体系                           | 关键测量                            | 能不能用                   | 判定               |
| ------------------------- | ---------------------------- | ------------------------------- | ---------------------- | ---------------- |
| **SINTEF graphite R2032** | Graphite‖Li 半电池（R2032）       | p-OCV、p-OCV hold、GITT、GITT hold | ✅ **直接用**              | 与 Phase 0 方案高度吻合 |
| **DLR LiGrHydra0b**       | Li-石墨 半电池（Basytec）           | GITT-OCV（26 天）、POCV             | ✅ 可用（次要）               | 25 ℃，带温度通道       |
| **ISU-UConn Emulation**   | 8 LFP 半 + **7 石墨半** + 35 全电池 | C/20（3 个石墨半电池 C/30）             | ⚠️ **只有 README，数据未下载** | 方法论参考价值最高        |
| Oxford NCA/graphite       | NCA/石墨 全电池                   | 降解                              | ⏳ 未审计                  | 266 MB .mat      |
| LFP4graphite GITT zip     | LFP/石墨 全电池                   | CC/EV/GITT                      | ⏳ 未审计                  | 54 MB            |

来源：这批文件来自 **SINTEF 维护的公开电池数据集目录**  
（Zenodo，DOI `10.5281/zenodo.18214281`，v0.6.1，标题 "Battery Datasets for  
Testing Data Pipelines and Workflow Automation"），目录同时收录 SINTEF 自家  
R2032 智能电芯数据与 DLR 的 Basytec 测试数据。

---

## 1. SINTEF graphite R2032（重点）

**文件**（`data/`）：

| 文件                                   | 行数             | 大小     | 程序         |
| ------------------------------------ | -------------- | ------ | ---------- |
| `...063b77__20250514__gitt__RT`      | **90,957,884** | 340 MB | GITT       |
| `...3f39a2__20250528__gitthold__RT`  | 89,383,026     | 335 MB | GITT hold  |
| `...4ccc47__20250514__p-ocv__RT`     | 189,340        | 3.0 MB | p-OCV      |
| `...677295__20250514__p-ocvhold__RT` | 206,500        | 3.4 MB | p-OCV hold |

**列**：`Test Time [s] / Unix Time [s] / Current [A] / Voltage [V] /
Cycle Count / Step Index / Cumulative Capacity [Ah]`

**体系判定（证据）**：电压窗口 **0.01 – 1.00 V**，首圈锂化起始 ≈ **3.0 V**  
（新鲜态低锂含量），p-OCV 电流 ≈ **±43.3 µA** → **Graphite‖Li 半电池**成立。

**电极几何（来自 `metadata.csv`，Gr-AQ-1）**：

| 项      | 值                       |
| ------ | ----------------------- |
| 直径     | 14 mm                   |
| 干厚     | 64 µm                   |
| 活性物质占比 | 90.98 %                 |
| 理论容量   | 372 mAh/g               |
| 活性物质质量 | 5.5 – 6.1 mg            |
| 面容量    | **1.33 – 1.48 mAh/cm²** |
| 载量     | 0.0036 – 0.0040 g/cm²   |

**测量结构（实测）**：

*p-OCV（5 圈）*：每圈  
`锂化 −43.3 µA（44–46 h，至 0.01 V）→ 静置 8 h → 脱锂 +43.3 µA（41–46 h，至 1.0 V）→ 静置 8 h`  
→ **双支 OCP 齐备** ✅

*GITT*：`脉冲 1800 s（30 min）@ 43.3 µA → 静置 9000 s（2.5 h）`，循环  
ΔSOC/脉冲 ≈ **3.6 %** ✅（满足 ≤5 % 判据）

### 1.1 与我们 Phase 0 方案的逐条核对

| 方案要求                  | SINTEF 实际                                            | 判定        |
| --------------------- | ---------------------------------------------------- | --------- |
| Graphite‖Li 半电池       | ✅ 0.01–1.0 V vs Li                                   | 通过        |
| 双支 OCP（充/放各一支）        | ✅ p-OCV 两项都有                                         | 通过        |
| 单脉冲 ΔSOC ≤ 5 %        | ✅ ≈ 3.6 %                                            | 通过        |
| 静置达准平衡 dV/dt < 1 mV/h | 锂化支 **+0.7~0.84 mV/h 通过**；脱锂支 **−1.8~−2.0 mV/h 未通过** | ⚠️ 见 §1.2 |
| 电极几何齐全                | ✅ 载量/厚度/面容量/占比                                       | 通过        |
| 倍率验证数据                | ❌ 无                                                  | 缺（需自测或另找） |
| 平行样                   | 目录中另有 `...3ac228__gitt`（20250528）**本机未下载**           | 建议补下      |

### 1.2 两个必须记录的数据特征

**(a) 脱锂支静置未达准平衡。** p-OCV 脱锂支（V ≈ 0.89 V）静置末端仍有  
**≈ −1.9 mV/h** 漂移（5 圈中 3 圈超出 1 mV/h 判据），锂化支则稳定在  
+0.7~0.84 mV/h（通过）。含义：**直接拿脱锂支静置末值当 OCP 会有约  
2 mV 量级偏差**；用作 OCP 参考时应保留这一残差，或对静置段做外推。

**(b) GITT 静置段松弛幅度大。** 30 min 脉冲后的 2.5 h 静置中电压仍在  
显著漂移（中段可达数百 mV，低 SOC/新鲜态尤甚），说明**静置末端不等于  
准平衡 OCV**。这不影响 GITT 用于扩散拟合（PyBOP 是拟合脉冲+松弛的  
瞬态），但**不要**把 GITT 静置末值当作 OCP 使用——OCP 请用 p-OCV。

### 1.3 数据工程问题（入库前必须处理）

1. **91 M 行 / 8 Hz 采样 / 121 天**：不能整表读入内存，也不能进 git。  
   需要**分段流式提取器 + 降采样**，canonical preview 只存抽稀后的曲线。
2. **符号约定**：负电流 = 锂化（充电）；平台 canonical 为 `discharge = +`，  
   适配器必须做符号翻转（与 Birmingham 半电池同类处理）。
3. **温度通道缺失**：标 RT 但无温度列 → 溯源只能记"文献声明 RT (25 ℃)"。
4. 首圈首次静置（3.0 V 端）dV/dt ≈ 29 mV/h，属新鲜态初始平衡过程，  
   不能当有效 OCP 点。

---

## 2. DLR LiGrHydra0b（Basytec）

| 文件                                                      | 行数      | 大小     | 内容                                |
| ------------------------------------------------------- | ------- | ------ | --------------------------------- |
| `DLR__LiGrHydra0b__20221114__GITT__25degC__Basytec.txt` | 315,319 | 62 MB  | GITT-OCV（2022-11-14 → 12-10，26 天） |
| `DLR__LiGrHydra0b__20230131__POCV__25degC__Basytec.txt` | —       | 9.3 MB | POCV                              |

- 表头：`Time[h] / DataSet / t-Set[h] / Line / Command / U[V] / I[A] /
  Ah[Ah/kg] / Ah-Charge / Ah-Discharge / Ah-Step / Ah-Step[Ah/kg] / Ah-Set /
  Ah-Set[Ah/kg] / T1[°C] / Cyc-Count / State`
- 起始 `U = 0.775 V`（石墨部分锂化区），**带温度通道** T1[°C] ✅
- 容量按 **Ah/kg**（活性物质归一）→ 换取算前需活性物质质量
- 用途：**交叉校验**（第二套独立石墨半电池 GITT），或做解析器兼容性验证

---

## 3. ISU-UConn Emulated Degradation Dataset

**只有 README，数据文件未下载**（`data/` 下无对应 csv/zip）。

README 内容摘要（Zhang et al. 2026）：

- 50 颗 CR2032 实验室电芯：**8 个 LFP 半电池 + 7 个石墨半电池 + 35 个全电池**
- 材料：MTI 的 LFP / 石墨单面涂层极片，Celgard 2400，Sigma-Aldrich 电解液  
  （1 M LiPF6 in EC:DEC 1:1 + 2 wt% VC）
- 半电池：12 mm 极片 + 250 µm 锂片（15.6 mm）+ 80 µL 电解液
- 面容量：LFP 1.932 mAh/cm²，石墨 1.903 mAh/cm²
- 倍率：多数 C/20，**3 个石墨半电池 C/30**
- 全电池含 PE SOC 100/90/80/0% 与 LAM_NE / LAM_PE / LLI 等退化模式设计

**方法论参考（重要）**：配套论文  
Li, T. et al. *Benchmarking half-cell model fitting approaches for  
lithium-ion battery degradation diagnostics*, eTransportation (2026),  
DOI `10.1016/j.etran.2026.100593`  
—— 正是我们 Phase 1/2 要做的"半电池模型拟合"的方法学基准，建议精读。

---

## 4. 建议的下一步（按优先级）

1. **用 SINTEF 石墨数据把整条链跑通**（推荐先做）：  
   导入 → 双支 OCP → GITT/PyBOP 提 D_s → `Ecker2015_graphite_halfcell` zero-fit  
   → 出误差报告。好处：在自测数据出来之前把**石墨半电池通路**验证完，  
   同时给平台加上石墨匹配条目。
2. **补下缺失文件**：`...3ac228__gitt`（做平行样）、`...1d5628__p-ocv`、  
   `...a29c1f__p-ocvhold`；以及 ISU-UConn 的真实数据包。
3. **审计 DLR + Oxford**：DLR 做交叉校验；Oxford（NCA/石墨全电池降解）另立线。
4. 数据归位与整理：把散放在 `data/` 根目录的文件按  
   `data/raw/LIB/<体系>/<数据集>/` 规范移动（本报告不含移动操作）。

---

## 5. 措辞守则（本数据集相关）

- SINTEF / DLR 参数属**公开参考数据**，用它们辨识出的参数是  
  **apparent / effective** 值，不是"材料常数"；
- 它们**不是**你的商业石墨参数集（grade B 参考）；你的自测数据才有资格  
  定义 `commercial_graphite_v1`；
- p-OCV 脱锂支有 ≈2 mV 量级未平衡残差，引用其 OCP 时必须披露。
