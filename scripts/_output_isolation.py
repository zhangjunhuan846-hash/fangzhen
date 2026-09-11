# ============================================================
# 相位脚本的公共工具：把平台的运行输出重定向到本阶段的产物目录
#
# 为什么需要
#   公共 runner（run_baseline_cell / benchmark / sensitivity）按
#   `battery_sim.paths.PLATFORM_OUTPUT_ROOT` 解析运行目录，也就是仓库里
#   **被跟踪**的 `outputs/platform/`。相位脚本每跑一次就把那些文件重写一遍
#   （只差 runtime/timestamp），于是每次提交前都得先
#   `git checkout -- outputs/platform/` —— 一个反复踩、又完全没必要的坑。
#
#   把根目录在**进程内**重定向到本阶段的产物目录即可，
#   **不改任何冻结代码**——与 tests/conftest.py 用的是同一手法。
#
# 用法（放在入口，不要放模块顶层：被别的脚本 import 时不该生效）
#
#   if __name__ == "__main__":
#       from scripts._output_isolation import isolate_platform_outputs
#       isolate_platform_outputs(OUT_DIR / "platform_runs")
#       raise SystemExit(main())
#
# 注意：`simulation/benchmark.py` 是**按值** import 该常量的，
# 所以它的模块属性也要一起改，否则 benchmark 仍会写回仓库。
# ============================================================

from __future__ import annotations

from pathlib import Path


def isolate_platform_outputs(target: Path | str) -> Path:
    """把平台运行目录指向 ``target``（进程内生效），返回该路径。"""
    import battery_sim.paths as paths

    root = Path(target)
    root.mkdir(parents=True, exist_ok=True)
    paths.PLATFORM_OUTPUT_ROOT = root

    try:
        from battery_sim.simulation import benchmark
    except Exception:                       # pragma: no cover - import guard
        benchmark = None
    if benchmark is not None and hasattr(benchmark, "PLATFORM_OUTPUT_ROOT"):
        benchmark.PLATFORM_OUTPUT_ROOT = root
    return root
