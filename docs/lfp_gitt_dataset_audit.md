# LFP/graphite CC+GITT+EV 数据集审计（Pozzato 2022）

状态：**审计 + canonical 预览完成**；未进平台（v0.4 冻结未触碰），未跑 PyBaMM。
审计脚本：`scripts/lfp_gitt_audit.py`（0 pybamm）。
产物：`outputs/analysis/lfp_gitt_audit/`（audit_per_leg.csv / implied_nominal_capacity.csv /
gitt_pulse_audit.csv / audit_summary.json / fig_cc_gitt_preview.png / fig_profiles_preview.png /
canonical_preview/*.csv ×22）。

## 1. 溯源

- 作者 Gabriele Pozzato（README 最后修改 2022-08-16），Zenodo 公开数据集
  "Constant current experiments, electric vehicle real-driving profiles, and GITT
  experiments for a LiFePO4/graphite battery cell"。
- 原始 zip 保留在 `data/LFP4graphite....zip`；解压至
  `data/raw/LIB/LFP_Graphite/LFP4graphite_CC_GITT_EV/`（13 个 .mat + README.rtf + cell_properties.png）。

## 2. 结构（实测，README 个别措辞与实际不符，以实测为准）

| 组 | 文件 | 顶层结构 | 字段 |
|---|---|---|---|
| const_current_data | cc_0_08 / cc_0_17 | charge + discharge 子结构 | current/voltage/**soc_start(标量)**/time |
| GITT_data | gitt_{0_17C,0_33C,0_5C,1C} | charge + discharge 子结构 | current/voltage/**soc(向量)**/time |
| real_world_data | profile_1..7 | 顶层平铺变量 | current/voltage/time/soc_start(标量) |

- 符号约定：**discharge = +current, charge = −current**（README 声明 + 实测一致，
  与平台 canonical 约定**原生相同，无需翻转**）。
- 单位：current [A]，voltage [V]，soc [-]，time [s]。

## 3. 审计结论

- **22 个 leg 全部解析成功**；13/13 文件。
- **标称容量 Q_nom ≈ 49.0 Ah**（双路由交叉证实）：
  - 电流路由：C/12 → 4.084 A ×12 = 49.0；C/6 → 8.165 A ×6 = 49.0；1C → 49.0 A。
    隐含容量散布 [48.996, 49.228] Ah。
  - soc 路由：GITT 的 soc 向量 ≡ soc0 ± ∫|I|dt/Q_nom（8/8 leg 线性拟合 RMS ≤1.2e-3，
    1/Q_nom = 0.0204 /Ah → Q_nom = 49.0 Ah）。
- **电芯**：~49 Ah LFP/石墨软包，V 窗口 2.50–3.60 V（profile_7 最低触到 2.400 V，见 §5）。
- **时间轴**：CC 1 s 采样、profiles 0.1 s；GITT C/3/C/2/1C 为 1 s（含 dt=0 重复点，
  见 §5）；**gitt_0_17C 为 0.1 s × 810 万点/leg（225 h），canonical 预览已按
  MAX_PREVIEW_POINTS=200k 降采样并在 attrs 记录 stride**。
- **GITT 脉冲结构**：C/3、C/2、1C 每档充/放各 ~25–29 个放电脉冲 + **4 h（14400 s）恒定
  弛豫**，脉冲-弛豫结构规整，适合 HFR/SOC 提取与后续 D_s 分析。C/6 档采样过密且含
  μA 级噪声电流（0.03 A），脉冲计数被噪声打断（审计如实记录，不影响 V(t) 使用）。

## 4. 与平台/既有资产的化学匹配

- LFP/石墨全电池 → 若进平台，参数集 = **Prada2013**（grade B surrogate，同 A123 路线）；
  但注意容量尺度差异大（Prada2013 标定 2.3 Ah vs 本电芯 49 Ah，几何完全不同）。
- **GITT 数据类型 = H1-C 中被 DEFER 的 D_s 数据类型**——本数据集是后续
  V2（diffusion attribution / 多倍率）最直接的公开锚点候选。
- OCP 迟滞：CC 充/放双支均有完整曲线（~30–50 mV 迟滞可见），与 SINTEF 双支结构同类，
  可作迟滞研究的第二个数据源。

## 5. 数据质量问题（进 canonical 前必须处理）

1. **重复时间戳**：GITT C/3（58 处 dt≤0）、C/2（~58）、1C（48–59 处）与 profiles 1/4/5
   （1–2 处）存在 dt=0 重复点 → 导入需去重（user_tools 已有同款逻辑可复用）。
2. **profile_7 电压下探 2.400 V**，低于该体系常规 2.5 V 截止 → 使用前确认是否为
   实验意图（深放电）或传感器毛刺。
3. **C/6 GITT 的 μA 级噪声电流**：任何基于 |I| 阈值的脉冲/工况分段须先做电流去噪。
4. README 说 CC 带 soc 向量，**实际是 soc_start 标量**；只有 GITT 有 soc 向量。

## 6. 下一步（待批）

- 候选 A：把 CC + GITT legs 转成平台 canonical（复用 user_tools 校验门），
  以 Prada2013 做 zero-fit baseline（CC legs），GITT 留作 D_s 归因素材。
- 候选 B：只保留审计产物，待自己的 regenerated-LFP 数据到位后一并进 V2。
- 无论哪条：平台 runner/evaluator 仍冻结，不改动。
