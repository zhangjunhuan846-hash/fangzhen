# examples/frozen_results —— 少量冻结产物

**政策**：这里只放**少量**能说明结论的东西，**不放全部 CSV**。

为什么：`outputs/` 里的产物每次跑都会重写，而 `outputs/fitting/` 又被 `.gitignore`
刻意排除（"只留冻结的小数值表"）。把产物整体纳入版本控制会让仓库膨胀，等真实实验
数据进来之后更明显。所以这里只放三件：一份 summary、一份报告、一张图。

| 文件 | 来自 | 内容 |
|---|---|---|
| `g6_2a_summary.json` | `outputs/fitting/g6.2a/g6_2a_report.json`（裁剪） | G6.2a 接口门的判据、逐窗口逐形状一行结论、形状差异，**不含**逐点代价曲线 |
| `g6_2a_report.md` | `outputs/reports/g6_2a_shape_interface.md` | 自动生成的参数报告（判定词只有五个，`k0`/`Rct` 写 `not_measured`） |
| `g6_1c_excitation_map_charge.png` | `outputs/fitting/g6.1c/` | 充电扫程 237 窗口的激励地图（四面板） |

**复核方式**：每个 gate 都能**单命令复现**，耗时写在各自文档里
（G6.2a 246 次仿真 45 s；G6.1c 10009 次仿真 25 min）。所以这里放的是
**结论的索引**，不是数据的替代品——要核对某个具体数字就重跑那个命令。

**不要**往这里加：逐窗口大 CSV、逐点代价曲线、`run_metadata.json` 全量。
它们属于"可重跑产物"，不属于"随版本发布的最小证据"。
