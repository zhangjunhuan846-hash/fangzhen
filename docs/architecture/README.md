# docs/architecture — 为什么这么设计

这一目录放的是**设计与审计**，不是运行文档，也不是科学结论：

| 文件 | 是什么 | 为什么留下它 |
|---|---|---|
| `agent_audit.md` | 对 `opqrst-chen/Battery-Sim-Agent`（另一个仓库，LLM Agent 做参数辨识）的接口审计 | 说明"Agent ↔ 平台"的契约为什么要求成功/失败严格同构、禁止哨兵值 |
| `simulation_request_design.md` | `SimulationRequest → Simulator → SimResult` 最小闭环的**第一版**设计（monkey-patch 路线） | 被取代，但"为什么不能 monkey patch"的记录在这里 |
| `simulation_request_convergence.md` | 同一闭环的**设计收敛稿**（现行口径） | 取代上一份；三条口径先定死，后面所有数字都依赖它 |
| `agent_platform_gap.md` | 逐轴缺口核对（2026-09-18） | 分轴列出"谁缺什么"，并纠正"上游优化器是自研"的误解 |
| `agent_platform_fusion.md` | 融合的**一般方案**（Agent 提案 / 平台判定） | 三层（契约 / 判据 / 治理）只做前两层的理由 |
| `recycled_graphite_agent_fusion_plan.md` | 融合方案**落到当前回收石墨实验**上（2026-09-28） | 结论：这个实验里 Agent 没有位置；该做的是两件守卫 + L3 带宽图当白名单 |
| `recycled_graphite_agent_fusion_wiring.md` | **整条实验计划的融合接线图**（2026-09-28，**接缝 A/B/C 已落地**） | 六步测试序列 + L1–L4 逐段分工；Agent 的三个真实插入点；三个接缝的修法与实测 |
| `module_layering_and_intake.md` | **模块三档判据与新模块接入协议**（2026-09-29） | 回答"哪些模块必要"——判据不是"重不重要"而是**"删了会不会红"**；含**单模块级依赖图**结论（真核心是 `paths.py`；1 处模块级反向依赖应改） |
| `PACKAGING.md` | **打包成 Project 的边界**（2026-09-29） | 五个 block + 五条排除；13 GB `data/`、非 git 仓库、环境不可移植三个障碍与解法 |

**注意**：前五份是 2026-09-12 的产物，早于 G5/G6 全部方法学工作。
里面提到的接口形状**可能已经落后于代码**——以代码与 `STATUS.md` 为准，
发现不一致时先改这里，不要反过来改代码。

**模块清单的可执行部分在仓库根目录**（不在 `docs/`）：

- `MODULES.yaml` —— 清单本体（三档 + 接入协议 + 打包）**【目录级】**
- `MODULE_GRAPH.yaml` —— **单模块级依赖图**（真核心排名、跨层方向、孤立模块）**【文件级】**
- `scripts/check_module_manifest.py` + `scripts/scan_module_graph.py` + `scripts/check_module_graph.py` —— 三个校验/扫描器，`rc=0` 才算过
- `tests/test_module_manifest.py`（9 项）+ `tests/test_module_graph.py`（11 项）—— 把"清单不腐烂""图不漂移"变成红灯

运行/接入类文档在 `docs/` 根目录：

- `adding_a_dataset.md` —— 接新数据的 4 步 + 格式问题清单
- `scale_alignment_gate.md` —— 尺度对齐门（Q_model == Q_measured）
- `g5.*.md` / `g6.*.md` —— 各阶段的判据与结论（每个文件自带"边界"一节）
- `../STATUS.md` —— **唯一可信状态页**：版本、判据、测试数、已知限制
