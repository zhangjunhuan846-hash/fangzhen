# Half-cell Pilot H1 — Phase H1-A：公开 pristine LFP‖Li 候选源准入筛选

**日期**：2026-09-08（H0 Birmingham 封板 tag `v0.4-halfcell-h0`，commit `7d46241` 之后）
**范围**：仅 source screening（资料审计），**不写 adapter、不跑 PyBaMM、不改 `battery_sim/`**。
**产出**：`outputs/analysis/lfp_h1/candidate_sources.csv`（候选准入表）+ 本文档。
**下一 Gate**：H1-B（data replay gate，仅对短名单数据做 adapter 级验证）——需用户批准后再开。

---

## 0. H1 目标回顾（收窄版）

> 找一个**匹配等级足够高、值得作为 recycled-LFP reference 的公开 pristine LFP‖Li half-cell**：
> 实验曲线、实验条件、几何、材料参数与参数来源形成可追溯链，然后在 **zero fitting / as-published**
> 条件下由 v0.4 平台复现。

准入等级（沿用用户定义）：

- **A — exact matched**：同一工作给出 raw 曲线 + 几何 + 材料参数 + 模型参数 + 协议。
- **B — experimentally matched**：曲线/几何/loading/协议同源完整，少数基础材料参数引用外部文献。
- **C — composite matched**：实验 A + 参数 B + 电解液 C，仅可用于 interoperability/sensitivity。

---

## 1. 筛选过程与证据链

检索入口（全部于 2026-09-08 执行）：

- Zenodo SINTEF Battery Lab 社区 / "sintef-lfp-R2032-gelon" 精确检索；
- DigitalCommons UConn REIL；ISU-UConn + eTransportation 29:100593；
- IOP JES / JPhysEnergy 的 LFP P2D 建模文献（ae94f3、ae3b77、acfc66、Safari 系）；
- HF/Zenodo 的 AURORA-2025（BDF/BattINFO）及各种 figshare/mendeley/IEEE DataPort 汇总页；
- 本地 `data/raw/LIB/` 全域检查（已有 `LFP_LiMetal/SINTEF_R2032/raw/` 一份 p-ocv parquet，今日 09:45 落盘）。

**逐源证据已落表**：`candidate_sources.csv`（8 行：2 短名单 + 6 淘汰/仅作参数锚）。字段含
raw curve、protocol、current、cutoff、temperature、loading、thickness、porosity、particle radius、
OCP、D_s、k0、electrolyte、parameter provenance、match grade、fatal missing fields、本地证据。

### 最重要的负面结论

**截至检索日，公开生态中不存在满足 A 级的 pristine LFP‖Li 体系**（同时公开 raw 曲线 + 同源几何 +
完整 P2D 参数集的可直接复现体）。与 Birmingham NCM920305 的差异是结构性的：

- NCM 侧有 Jackowska-2025 将 raw + 参数集 + 模型结果一并发布的案例；LFP‖Li 侧最接近的
  已发布完整 P2D 参数表的论文（ae94f3 / acfc66）**均未落盘 raw 时间-电流-电压文件**（figures+tables only），
  无法构成 H1-D 的 as-published reproduction 基线；
- 常见"半电池 LFP"公开数据多为材料学实验（图+摘要容量），或全电池（AURORA 2025、CALCE A123、
  Prada2013 参数集），不满足 LFP‖Li half-cell 需求。

---

## 2. 候选准入表（完整见 CSV，短名单如下）

### 短名单 #1 — SINTEF R2032 LFP‖Li（primary）

| 字段 | 值 |
|---|---|
| 记录 | Zenodo 10.5281/zenodo.19107295（v1；newer 20086298），"Half-Cell OCV of Several LIB AM…" |
| 电极 | 商用电极 LFP-NMP-1（vendor gelon），**d=14 mm（A≈1.54 cm²）**，干厚 **78 µm**，标称面容量 **2.0 mAh/cm²** |
| 电压/温度 | **2.50–3.65 V**；RT（记录正文 "room temperature"，未给数值） |
| 协议（LFP 8 只） | p-ocv、p-ocvhold、GITT、gitthold 各 ×2 只 ×5 圈；C/50 级慢扫（本地产 p-ocv 实测 |I|≤61.6 µA / ~3.1 mAh） |
| 本地证据 | p-ocv `d07eb6` parquet **md5=3efea83a… == Zenodo v1 官方值**；`meta/metadata.csv`（19.5 kB）已取并解析 |
| OCP | 同源自己的 p-ocv/GITT 电荷-放电 trace（含两相平台与迟滞，可作 OCP 曲线源） |
| D_s | 同源 GITT 文件可推导（尚未下载；每文件 350–373 MB） |
| 缺口 | 孔隙率、活性 wt%、粒径、k0、电解液均未公开（商用电极）→ 完整 P2D 组装需文献锚；记录内无多 C-rate CC |
| 等级 | **B**（experimentally matched；基础动力学/孔隙参数外引 → 复合组装用于 P2D） |

**评注**：这套数据是"数据+几何+协议+同源 OCV/GITT"四要素齐全的开放体系，与 H1 需要的
OCP/stoich-endpoint/capacity 参考完全契合；面容量 2.0 mAh/cm² 与目标电极族接近。
LFP 两相特征（平坦平台）会在 p-ocv trace 中直接可见，是检验半电池 wiring 与初始化的好靶子。

### 短名单 #2 — ISU-UConn（secondary）

| 字段 | 值 |
|---|---|
| 记录 | DigitalCommons UConn REIL Datasets 6（CC-BY），"ISU-UConn LFP/Graphite Emulated Degradation Dataset" |
| 内容 | 50 只 CR2032：**8× LFP‖Li half cell + 7× graphite‖Li + 35 全电池**；MTI 单面涂布 LFP/石墨电极、Celgard 2400、Sigma-Aldrich 电解液 |
| 协议 | 半电池 CC **C/20**（3 只石墨 C/30）；raw 数据 LFP_Data.xlsx（10.8 MB） |
| 配套 | Li et al., *eTransportation* 29:100593（2026）——empirical 半电池 **dV/dQ model fitting**（LLI/LAM 诊断），**非 P2D 参数化** |
| 等级 | **B-**（曲线+材料+协议同源；OCP 可自 C/20 拟准；P2D 的 k0/Ds/孔隙率缺） |
| 注意 | 直链下载被 403（DigitalCommons 反爬），README 细节（cutoff/面载量）尚未核实 → H1-B 前需先下载并读 README |

### 仅作"参数文献锚"（不入选 raw replay）

- **ae94f3**（JES 2025，LFP‖Li 2032，P2D+PSD+SOC 相关 D_s；C/10–1C 倍率扫 + GITT）：参数表完整公开
  （ε_e=0.45、c_smax=22 820、j0=50 A/m²、粒径分布），**raw 未落盘** → C 级，作 attribution 锚。
- **acfc66**（JPhys Energy 2023，LFP‖Li 16 mm，校准 P2D）：Rp=1 µm、Ds=3.7e-16、k0=0.12e-11、ε_e=0.254、
  OCP 自测自 C/50 —— 完整表公开，**raw 未落盘** → C 级，作 k0/孔隙率组装锚。

### 已淘汰（原因见 CSV）

Gotion 超高密度 LFP（有倍率扫但 raw 未公开）、Safari/Delacourt LRCS（半电池建模经典但 figures-only）、
AURORA-2025（199 只 CR2032 是 **full cell**，LFP/Gr 与 NMC/Gr）、PyBaMM Prada2013（全电池参数集、无半电池 raw）。

---

## 3. H1 建议走向（待用户批准）

1. **进入 H1-B data replay gate（对象 = SINTEF LFP-NMP-1）**：以本地 p-ocv 文件做 adapter 级验证——
   窗口/容量重建/倍率分辨率/初始 V/元数据对齐到 Zenodo 记录与 metadata.csv 声明（2.0 mAh/cm²、2.50–3.65 V、
   5 cycles）。若时间允许并行下载 GITT（b89ab5/b26620）用于 D_s 推导。**仍不写进平台、不跑模型**。
2. 组装 P2D 参数：孔隙率/粒径/k0 的 attribution 锚 = acfc66（k0、Rp、ε_e）与 ae94f3（PSD、Ds(x)、j0）；
   LFP OCP = 同源 p-ocv trace（H1 自带最强项）。
3. **H1-D 前必须显式设定"as-published"定义**：SINTEF 记录本身不发布模型参数，故 H1-D 的 zero-fitting
   复现语义 = "以记录公开几何+同源 OCP/GITT 组装的最小 DFN，对 p-ocv 曲线做 reproduction"，参数缺口与
   组装来源逐项记录（沿用 H0 的 parameter_mapping JSON 模式）。
4. ISU-UConn 作为第二候选，在 SINTEF 接线失败时才顶上；若需要多倍率 CC 再议（当前两短名单都是慢速单率）。

**铁律延续**：H1 期间不 optimization / 不 fitting；LFP 两相效应（平台、迟滞）只作为"待检验的模型结构
假设"记录，不预设单相 DFN 一定能复现；不用 SINTEF 数据去拟合出"材料常数"。
