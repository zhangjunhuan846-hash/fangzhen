# 本平台 vs Battery-Sim-Agent：逐轴缺口核对

日期：2026-09-18 ｜ 对象：`github.com/opqrst-chen/Battery-Sim-Agent`（本机副本 `WorkBuddy/Battery-Sim-Agent`）
方法：只写**核过的**事实，每条给证据位置。**没有改平台任何代码。**

相关文档：`docs/architecture/agent_audit.md`（只读审计）、`simulation_request_design.md`（契约设计）、
`simulation_request_convergence.md`（收敛过程）。

---

## 0. 先把两件事分开：这是两类不同的东西

| | **Battery-Sim-Agent** | **本平台（fangzhen）** |
|---|---|---|
| 定位 | KDD 2026 论文**参考实现**（方法 + 仿真基准 + 优化基线） | 数据治理 + 物理判据的**基础设施** |
| 目标函数 | 把参数**反演准**（loss 降低 / 真值恢复率） | 判定**哪些参数在这份数据里能被定住**，并记录每个值的来源 |
| 上游历史 | **单个 `Init` 提交**（`354f2dd`，2026-05-28）；另有 `0b530c8` "Initial commit"（2026-03-11，LICENSE） | 完整提交历史 + tag + bundle |
| 许可 | MIT | 自有 |
| 规模 | 6 套优化基线 + 3 族仿真基准 + LLM 闭环 | adapter / 治理 / 辨识 / 预注册 |

⇒ 「还差什么」必须**分轴**答，且**方向**要写清：有些是本平台缺，有些是那边缺。

---

## 1. 本平台确实缺的（4 条）

### ① 「参数是否被模型消费」的守卫 —— **本平台缺第三支惰性**

本平台对"写了参数却没效果"有两支分类，各有对应代码：

| 支 | 机制 | 代码 |
|---|---|---|
| ① 协议不激发 | 活性门（峰值展开单调、零电流对照逐位 0） | `battery_sim/excitation/`、`battery_sim/simulation/protocol_replay.py` |
| ② 尺度失配 | 两个 C-rate 并列 + `ScaleMisalignment` | `governance/scale_alignment.py` |

Agent 侧补出了**第三支**：③ **当前这层模型根本不读这个键**。
实证（`docs/SIMREQUEST_IMPLEMENTATION.md` §Parameter-capability closure）：`porosity` 在 SPM 下被写进参数集、
被记进日志、**RMSE 逐位不变**（零效果）。同一份审计还proved了两条相邻故障：
`exchange_current_density` 收到标量后**静默替换了一个函数**（RMSE 48.3611 → 48.4173 mV）、
`electrode_area` 这类"模型确实消费、但这个参数集没有这个键"的写法。

本平台现状：`parameter_overrides` 只做**键不在参数集 → `KeyError`**（`battery_sim/simulation/baseline.py`），
**没有"这个键被当前模型消费吗"这一层**。

为什么值得补：③ 的**症状与 ① 无法区分**——都是"改了参数、轨迹不动"。
本平台的活性门是在**协议维度**上判的（"模型对参数有没有响应"），
而"参数被写进去了但这一层模型不用"是**另一类**故障，会伪装成"协议不激发"。
Agent 侧把它们按 `unknown → curve → not-consumed → set-absent` 排序，**顺序是有用的**：
曲线型参数没有 `models` 字段，先查"模型是否消费"会把**值类型错**误诊成"模型忽略它"。

### ② 单位层（affine）

Agent 侧踩过：把 `degC → K` 当**乘法**算，35 °C 变成 **9560.25 K** —— 一个"看起来成功"的错答案。
修法是单位声明为 `(scale, offset)` 对（`UNIT_AFFINE`），且整条桥**只有一条换算路径**；
用普通比例表声明 `degC` 会被测试断言拦下。

本平台现状：`grep UNIT_TO_SI / UNIT_AFFINE / affine` → **零命中**。单位只出现在 QC 的 mV 陷阱检查里。
⇒ 平台没有"声明单位 + 单一换算路径"这一层。**接真实仪器文件时这是高风险位**
（工作站导出单位写法五花八门，且有 offset 的单位一旦当乘法处理就是静默错值）。

### ③ 优化器与多目标这一层

| Agent 有 | 本平台对应物 |
|---|---|
| 单目标 BO / 多目标 BO / 退化 BO / 真实数据 BO / 单目标 CMA-ES / 多目标 CMA-ES（6 套，各自 `configs/` + 运行脚本） | `identification/forward.py`（PyBOP 驱动，**单目标**） |
| `loss/` 工厂：`voltage` / `capacity` / `current` / `total` 可组合 | 代价只有一种（重叠段电压残差） |
| `scripts/extract_parameter_bounds.py` 从数据提取参数上下界 | 无（边界散落在测试与常量里） |

⇒ 本平台缺"多算法、多目标可比"的那一层。
**但这不是第一篇论文的必需品** —— 导师已明确"不扩 Agent、不加 ML"。

### ④ 仿真基准**库**（不是夹具）

Agent 有 `generate_simulated_data/`：单参数 100 例 / 多参数 100 例 / SEI 5 例，
且**按「仿真失败」与「与默认容量差 < 1 %」过滤**（`filter_settings.py`），预生成 yaml 随仓库发布。

本平台有合成夹具（`examples/synthetic_rate_ladder/`、`examples/synthetic_recycled_graphite/`），
但**没有"按设置批量生成 + 过滤 + 成库"的生成器**。差别在规模：
G6.1c 那次可辨识性地图要扫 **239 个窗口**，单例夹具撑不起这种统计。

---

## 2. 反过来：本平台已经有的，那边没有（这是"谁的结论更硬"的差别）

| 维度 | Battery-Sim-Agent | 本平台 |
|---|---|---|
| **可辨识性判定** | **完全没有**。评估 = 参数恢复得多准 / loss 降多少 | 五词判定 + 1 mV 带宽地图（G6.1b/1c）；**`bounded` 只报界** |
| **"拟合好 ≠ 参数对"** | 无对应机制 | G5 实证：**真值不是最优解**（错误模型假设下偏 −25 % 的参数拟合反而好 3.4×）；谷是**脊不是碗**；电压只约束 τ_d = R_p²/D_s |
| **尺度对齐门** | 不需要（sim-vs-sim 天然同尺度）—— **一旦接真实数据就必须有** | `ScaleMisalignment` + 两个 C-rate 并列（踩过 113× 与 31× 两次） |
| **数据治理** | 无对应物 | canonical schema、13 项 QC、脉冲协议分级、体系锚定电压窗 |
| **角色分离 / 留出** | 基准是 sim-vs-sim，无 holdout 概念 | `dataset_role`（标定即报错）+ L4 四道门（角色/尺度/覆盖率/初值接线） |
| **判据预注册 + 溯源** | 无 | `preregistration_2026-09-18.md` + 附件 A + `software_commit`/`protocol_docs_commit` 三元组 |

**唯一"该抄的"是它的代码快照习惯**：`pipeline.py` 每次把整个 `battery_agent/` 目录复制进 `RESULTS_DIR/code/`，
所以任何一次历史实验都自带当时的代码。本平台有 `run_metadata.json` 与 commit 记录，但没有这个习惯。

---

## 3. ⚠️ 必须马上澄清：导师点那个 URL 看到的是**上游原版**

实测（2026-09-18，WebFetch 上游仓库页）：

- 最新提交 **`354f2dd` "Init"，2026-05-28**（另有 `0b530c8` "Initial commit"，2026-03-11，仅 LICENSE）
- 上游顶层只有：`assets/ baseline/ battery_agent/ generate_simulated_data/ script/ .gitignore LICENSE README.md read_test_result.ipynb requirements.txt run_exp.py`
- **没有** `contract.py`、`parse.py`、`param_capability.py`、`sim_contract.py`、`simulator.py`、
  `demo_simrequest.py`、`scripts/`、`tests/`、`docs/`

⇒ 本地那一整套（输出契约加固 + SimRequest 契约 + 参数能力守卫，**222 项测试**）**上游一个字都没有**。
把 URL 给导师 = 给他原版，那里面还留着：`while not param_groups_list` 的最长 **10000 秒空转**、
`first_cycle`/`degradation` 两套互不兼容的解析、`capacity=0` 当失败哨兵。

**要让他看到加固版，只有两条路**：给本地副本，或把本地改动推到自己的 fork / 分支。
⚠️ 而本地副本**不是 git 仓库**（当初用 tarball 解压，Windows 上 `git clone` 会被 schannel 掐断）
⇒ **那 222 项测试与契约代码目前没有任何版本控制备份**。

---

## 4. 结论

1. **不缺"优化到 loss 低"这件事**：本平台已经有 `forward.py`；③④ 属于"要不要跟它比论文"，
   而导师的答复是**先把 CG-AR 跑完**，不扩 Agent、不加 ML。
2. **该在接真实数据前补的是 ① 与 ②**：两条都是**守卫**，不是新功能，且都属 `v0.1.1`/实验分支的范畴
   （`v0.1.0-platform` = `ee2fb36` 不动）。① 可直接用"覆盖后轨迹逐位不变"作判据（零成本、无物理假设）；
   ② 要先把真实仪器导出的单位写法收齐再定表。
3. **③④ 是本平台的下一阶段，不是这一轮**。
4. **若论文叙事要把它作为对照**，本平台的差异化位置很清楚：
   **它回答"参数能不能被反演准"，本平台回答"这个参数在这份数据里到底能不能被定住、以及它凭什么值得信"。**
   前者需要 sim-vs-sim 基准，后者需要真实数据 + 可辨识性地图 —— 两者不是替代关系。

---

## 5. 附：本地 Agent 副本的当前状态（供参考，不在本平台范围内）

```
路径：C:\Users\24330\WorkBuddy\Battery-Sim-Agent   （非 git 仓库，tarball 快照 + 本地改动）
测试：python -m pytest tests -q  ->  222 passed in 17.19s   （2026-09-18 实测）
文档：docs/BORROW_NOTES.md（借鉴笔记：6 类问题 → 代码位置 → 改法）
      docs/SIMREQUEST_IMPLEMENTATION.md（SimRequest/SimResult 最小实现 + 不收敛的那个数）
未做：白名单与 prompt 知识文本的参数集要不要对齐（BORROW_NOTES §5，等用户决定）
```
