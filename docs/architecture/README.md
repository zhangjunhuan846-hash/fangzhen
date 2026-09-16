# docs/architecture — 为什么这么设计

这一目录放的是**设计与审计**，不是运行文档，也不是科学结论：

| 文件 | 是什么 | 为什么留下它 |
|---|---|---|
| `agent_audit.md` | 对 `opqrst-chen/Battery-Sim-Agent`（另一个仓库，LLM Agent 做参数辨识）的接口审计 | 说明"Agent ↔ 平台"的契约为什么要求成功/失败严格同构、禁止哨兵值 |
| `simulation_request_design.md` | `SimulationRequest → Simulator → SimResult` 最小闭环的**第一版**设计（monkey-patch 路线） | 被取代，但"为什么不能 monkey patch"的记录在这里 |
| `simulation_request_convergence.md` | 同一闭环的**设计收敛稿**（现行口径） | 取代上一份；三条口径先定死，后面所有数字都依赖它 |

**注意**：这三份是 2026-09-12 的产物，早于 G5/G6 全部方法学工作。
里面提到的接口形状**可能已经落后于代码**——以代码与 `STATUS.md` 为准，
发现不一致时先改这里，不要反过来改代码。

运行/接入类文档在 `docs/` 根目录：

- `adding_a_dataset.md` —— 接新数据的 4 步 + 格式问题清单
- `scale_alignment_gate.md` —— 尺度对齐门（Q_model == Q_measured）
- `g5.*.md` / `g6.*.md` —— 各阶段的判据与结论（每个文件自带"边界"一节）
- `../STATUS.md` —— **唯一可信状态页**：版本、判据、测试数、已知限制
