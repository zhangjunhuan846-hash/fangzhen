# 独立复现运行说明

目标：让无历史上下文的执行者原样运行当前文档命令，检查文档与现有环境、输出一致性。不要修改脚本或依赖；发现失败就报告。不得覆盖主运行或原始数据。

Windows PowerShell；项目根目录 `C:/Users/24330/WorkBuddy/仿真模拟`；本地CPU运行。环境说明 `.aris/compute/local-wsl-ubuntu.md`、spec为 `.aris/compute/resource_budget_spec.json`。

原样执行：

```powershell
wsl.exe -d Ubuntu --cd '/mnt/c/Users/24330/WorkBuddy/仿真模拟' -- env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 /home/zjh/miniforge3/envs/pybamm/bin/python -m user_tools.workbench.budget_benchmark --out outputs/analysis/resource_budget_20261014_reproduction --seeds 50 --budget 12 --threshold 360
```

输出目录已存在时脚本会拒绝覆盖，这是预期保护行为。仅当这个新目录不存在时运行；若已存在请停止报告，不更改参数或改写输出。

完成后，比较主输出 `outputs/analysis/resource_budget_20261014` 和本次 `..._reproduction` 中 summary.csv、ablations.csv、campaigns.csv、traces.csv、decisions.jsonl 的字节SHA-256。应全部相同。result.json包含运行耗时，不能要求整文件字节相同；其中config/summary/ablations/campaigns/traces应相同。仅写独立复现目录中的REPRODUCTION_CHECK.md和REPRODUCTION_CHECK.json，报告退出码、时间、文档偏差和对比结果。
