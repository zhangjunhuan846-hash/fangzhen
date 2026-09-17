# Self-Service Layer Release Checklist

> Self-Service Data Onboarding Layer（S1–S10）· 交付前自检清单
> 日期：2026-09-08
> 状态口径：软件功能完成；Windows 真人双击 UAT 待完成

## 状态

```text
PASS:    importer                        —— generic csv/xls/xlsx → canonical（显式映射+单位+符号）
PASS:    validation                      —— 12 项校验，FAIL 阻断 simulation
PASS:    canonical conversion            —— importer ≡ 专用 adapter（numerically equivalent within
                                           floating-point tolerance：max|Δt|=0s, |ΔI|=1e-16 A, |ΔV|=0 V）
PASS:    simulation dispatch path        —— user_tools.adapter → run_baseline_cell，battery_sim/ 零改动
PASS:    platform regression previously verified —— 88 tests passed（同 Phase A2 前）
PENDING: Windows double-click UAT        —— 需真人（你或师姐）在真实 Windows 双击
                                           「导入并检查数据.bat」「运行仿真.bat」各一次
```

## 关键口径说明（勿回退）

- **importer 等价门**不是 byte-identical：存在浮点差（ΔI = 1e-16 A）。正确表述为
  *numerically equivalent within floating-point tolerance* 或 *canonical equivalence gate
  passed within numerical tolerance*。
- **BAT**：底层 WSL 执行路径已端到端验证、BAT 命令链已静态验证；**Windows 双击真人验收 pending**，
  在真实 cmd.exe 双击跑通前，禁止写 "BAT 100% end-to-end verified"。
- **parameter-match taxonomy**：未扩展 A/B/C 之外的新等级。NMC 正半电池 Jackowska 用
  `grade = "B"` + 结构化 provenance：
  ```yaml
  provenance: matched_study
  electrode_design: matched_2mAh_cm2
  fitted_to_user_dataset: false
  executable_reproduction: partial
  ```
- **protocol 与实际倍率分开记录**：
  ```text
  source_protocol_label = CC_Cover5     （cycler 档位名，原始数据自带标签）
  effective_c_rate     ≈ 0.221           （= max|I| / nominal_capacity，平台换算）
  ```
  二者不必相等；勿把原始标签读成精确倍率。
- **experiment sheet 共 21 个字段**（dataset_name … initial_soc）。
  2026-09-17 新增四个：`working_electrode_material`（体系锚定电压窗要用）、
  `protocol_type`（闭集；决定 QC 严厉程度）、`pulse_duration_s` /
  `relax_duration_s`（GITT 时长核对）。旧数据包缺这些键不会报错
  （读不到就是空），但会少两项检查 —— 见
  `docs/chemistry_windows_and_gitt_qc.md`。

## 文件位置

- 新代码：`user_tools/`
- 模板包：`user_dataset_template/`（raw/ + dataset_info.xlsx + 两个 BAT）
- 使用说明：`docs/师姐使用说明.md`
- Demo 等价门证据：`outputs/user_datasets/demo_birmingham_cover5/equivalence_gate.json`
- Demo 校验报告：`outputs/user_datasets/demo_birmingham_cover5/validation_report.html`
- Demo baseline 指标：`outputs/user_datasets/demo_birmingham_cover5/baseline_metrics.csv`

## 本 QA 轮未运行（遵守冻结）

PyBaMM / 新 baseline / fitting / sensitivity / H1-D0 / 新数据集 —— 均未运行。
`battery_sim/` 科学核心改动 = 0。
