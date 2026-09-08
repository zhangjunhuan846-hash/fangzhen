# v0.3 封版报告 — Dynamic-protocol generalization（CALCE INR18650-20R）

日期：2026-09-08　|　状态：**封版**（55 → 64 tests，v0.2 zero-regression gate 通过）

## 0a. 冻结项：initial-state 语义（封版前最后补充）

动态窗口的 replay 并不是完整实验历史的重放：

```text
完整原实验:  charge → rest → trim discharge to target SOC → rest → DST/FUDS/US06
平台 replay: initial_soc = 0.5 / 0.8  →  只 replay 动态段 I(t)
```

两者不是同一物理初始化。因此所有动态窗口的 metrics 与 run_metadata 显式携带
`initial_state` 语义块（本封版补丁已实装进 metrics.csv，additive 列）：

```json
{
  "initial_state": {
    "type": "nominal_soc",
    "value": 0.5,
    "source": "CALCE protocol target (filename SOC label)",
    "history_replayed": false,
    "is_exact_electrochemical_state": false
  }
}
```

（80% SOC 窗口同理，value=0.8。）

**解读禁令**：Chen2020 surrogate 中 nominal SOC → electrode stoichiometry
的映射不是 20R 自己的映射，且前序历史未重放。因此不得由
`DST_50SOC RMSE=152.79 mV < DST_80SOC RMSE=275.57 mV` 得出"模型在高 SOC
泛化更差"——RMSE 差同时混有 surrogate 参数失配、SOC–stoichiometry 映射失配、
历史未重放、模型动态响应误差四重来源。当前所有动态 RMSE 只能作为
**software regression / unfitted replay baseline**。

该补丁为 additive 接口扩展（adapter provenance + baseline 结果列），
重跑全部 6 窗口后 RMSE 逐位不变（152.79 / 275.57 / 151.06 / 271.04 /
172.33 / 287.59 mV），v0.3 到此彻底封版。

## 0. 一句话结论

DST / FUDS / US06 三个动态工况经新 adapter 进入**同一个** baseline replay
runner / evaluator / 输出 schema，runner 与 evaluator 的科学计算逻辑修改数
= **0**；全部 64 tests 通过；Chen2020 与 CALCE CS2 的 v0.2 golden 逐位不变。

```text
Chen2020 CC (Maccor CSV)   ─ Chen2020Adapter ─┐
CALCE CS2 CC (Arbin xlsx)  ─ CalceCs2Adapter ─┼→ run_baseline_cell（protocol-agnostic）
CALCE 20R DST/FUDS/US06    ─ Calce20RAdapter ─┘        ↓
                                                    同一 evaluator / metrics.csv / run_metadata.json
```

## 1. Step 18 数据审计（docs/v03_step18_calce20r_audit.md）

- 6 个动态文件 = DST/FUDS/US06 × {50,80}% SOC，Arbin .xls，每文件单一连续
  profile（无跨文件拼接、无时间重置、无 NaN、无重复时间戳）。
- 原始符号：charge=+ / discharge=− → adapter 翻转为平台 canonical。
- 动态段规则识别（混合符号电流 + |I|峰≥1A + 点数最大）在 6/6 文件命中 Step 7，
  未写死任何 step 号。
- 文件内无温度列 → 25°C 假设由 config 持有（source: CALCE archive 命名
  `SP2_25C_*`，confidence: medium）。
- 陷阱同 CS2：Arbin 累计容量列禁用；近零 dt 事件点保留并保证输出
  `np.diff(time_s)>0`。

## 2. Dynamic canonical schema（Step 19）

runner 只见 `t, I(t), Vexp(t)`（+ config 持有的 ambient T）。协议信息全部在
metadata/provenance：`protocol_id / profile_kind=dynamic / source_file /
source_cycle / source_step / source_soc_percent / initial_soc`。
**没有引入任何 DST-specific 或 US06-specific 字段。**

canonical 窗口 id：`DST50/DST80/FUDS50/FUDS80/US0650/US0680`
（rate_slug：`DST_50SOC`…；`--protocol DST` 在 CLI 层展开为两个窗口）。

## 3. 电流符号与时间轴（Step 20）

canonical 符号验证：放电峰 +4.0 A（2C）、充电 −2.0 A（FUDS −2.14 A），
net discharge 为正，全部 6 窗口严格递增时间断言通过。

## 4. 参数集审计（docs/v03_calce20r_parameter_audit.md）

- 20R = Samsung SDI 2.0 Ah，NMC/石墨，18650，2.5–4.2 V（与数据一致）。
- **Chen2020 = B 级 compatible_surrogate**（同化学家族 NMC/石墨 + 电压窗口
  2.5–4.2 V 实测一致；容量 5.0 vs 2.0 Ah 是结构性 surrogate 偏差，已记录）。
- Mohtat2020/ORegan2022（石墨-SiOx 负极/4.4V 窗口）、Ecker2015（C）、
  Prada2013（LFP，C）等均不采用。
- 所有结果均为 **unfitted surrogate baseline**；初始 SOC 取自文件名 SOC 标签
  （low confidence，provenance 显式记录）。

## 5. Dynamic replay metrics（Step 24）

新增（additive）：`residual_std_mV`、`current_rms_A`、
`current_peak_discharge_A`、`current_peak_charge_A`（后三项为 protocol
characterization，不是模型评分）。未做频域/脉冲/阻抗指标。

## 6. 容量语义（Step 25）

全部窗口保持 `capacity_metric_type: forced_current_window`、
`capacity_is_predictive: false`。未输出任何"预测容量精度"。

## 7. 三条 CLI 完整输出（Step 23，同一 runner）

```text
python run_pipeline.py --dataset calce_20r --mode baseline --model SPMe --cell 2 --protocol DST
  DST_50SOC  RMSE(t)= 152.79 mV | MAE=134.23 | max|e|=989.7 | std=73.2  | Ipk +4.0/−2.0 A | coverage 1.00
  DST_80SOC  RMSE(t)= 275.57 mV | MAE=263.41 | max|e|=1231.8 | std=81.0 | Ipk +4.0/−2.0 A | coverage 1.00
--protocol FUDS
  FUDS_50SOC RMSE(t)= 151.06 mV | MAE=135.22 | std=… | Ipk +4.0/−2.14 A | coverage 1.00
  FUDS_80SOC RMSE(t)= 271.04 mV | MAE=260.31 | Ipk +4.0/−2.14 A | coverage 1.00
--protocol US06
  US06_50SOC RMSE(t)= 172.33 mV | MAE=148.85 | Ipk +4.0/−0.86 A | coverage 1.00
  US06_80SOC RMSE(t)= 287.59 mV | MAE=274.16 | Ipk +4.0/−0.86 A | coverage 1.00
```

禁止项遵守：没有 `run_dst.py/run_fuds.py/run_us06.py`，没有
`if protocol == "DST"` 分支——runner 全程 protocol-agnostic。

RMSE 解读：151–288 mV 属 unfitted surrogate 预期量级（B 级参数集 + 容量
5.0/2.0 Ah 结构偏差 + 50% vs 80% SOC 起点差异）；**这些数值仅作为 v0.3 软件
regression reference 锁定，不作为物理验证结论**。

## 8. Tests（Step 26）

`tests/test_calce20r.py`，9 个用例（要求的 9 个名称全部实现）：
registry / file_reading / current_sign / time_monotonic / protocol_list /
dst / fuds / us06 / dynamic_cli（CLI 实跑 DST 并断言同一 runner 输出 schema
与容量语义）。golden 锁定：n_points、duration、起止电压、峰值电流、积分
电量、source file，然后锁定 surrogate RMSE。

**全套：64 passed（v0.2 的 55 + v0.3 的 9），0 failed, 0 skipped。**

## 9. v0.2 zero-regression gate（Step 27）

| Golden | 期望 | 实测 | 状态 |
|---|---|---|---|
| Chen2020 reproduction SPMe cell02 | 82.33 / 115.81 / 70.02 / 46.84 mV | 82.33 / 115.81 / 70.02 / 46.84 mV | ✅ 逐位一致 |
| CALCE CS2_33 baseline SPMe | ≈200.37 mV | 200.365 mV | ✅ 不变 |
| CALCE CS2_35 baseline SPMe | ≈269.93 mV | 269.929 mV | ✅ 不变 |

## 10. core-code modification count（v0.3 验收指标）

| 层 | 科学计算逻辑修改 | 接口扩展（允许） |
|---|---|---|
| runner `battery_sim/simulation/baseline.py` | **0** | ① initial_soc 从 df.attrs 读取（缺省 1.0，CC 数据集行为逐位不变）② rate 参数接受窗口列表 ③ result dict 新增 additive metrics/protocol 列 |
| evaluator `battery_sim/evaluation/*` | **0** | 无 |
| model factory `battery_sim/models/*` | **0** | 无 |
| registry `battery_sim/registry.py` | **0** | 无（纯 config 驱动发现） |
| reproduction / benchmark / sensitivity runner | **0** | 无 |
| 既有 adapter（chen2020/calce_cs2） | **0** | 无 |

新增文件：`battery_sim/datasets/calce_20r.py`、`tests/test_calce20r.py`、
configs/datasets.yaml 的 `calce_20r` 条目、`run_pipeline.py` 的 `--protocol`
参数（--rate 别名）、审计脚本 `scripts/audit_20r_step18.py`、两份审计文档。

## 11. v0.3 完成后停止

未做（按任务书）：A123、LFP、parameter fitting、sensitivity 扩展、thermal、
SIB、GUI。下一步（另行启动）：v0.4 chemistry generalization（NMC/LCO → LFP，
A123），完成四个维度泛化证明后平台封版，转入科学问题研究。
