# ============================================================
# 测试：平台运行输出的隔离
#
# 背景：公共 runner 把结果写进**被跟踪**的 outputs/platform/。
# 两个地方必须挡住这件事：
#   1. pytest —— tests/conftest.py 的会话级夹具；
#   2. 相位脚本 —— scripts/_output_isolation.py。
# 这里给两者各配一条守卫，免得哪天被改回去而没人发现。
# ============================================================

from pathlib import Path

import battery_sim.paths as paths

from scripts._output_isolation import isolate_platform_outputs

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_session_keeps_platform_outputs_out_of_the_repo():
    """
    回归守卫：测试期间平台输出根**不能**落在仓库的 outputs/ 里，
    否则每次跑测试都会把被跟踪的运行目录改脏。
    """
    root = Path(paths.PLATFORM_OUTPUT_ROOT).resolve()
    repo_outputs = (ROOT / "outputs").resolve()
    assert not str(root).startswith(str(repo_outputs)), (
        f"平台输出根仍在仓库内：{root}。"
        f"检查 tests/conftest.py 的 _isolate_platform_outputs 是否失效。"
    )


def test_isolate_platform_outputs_repoints_both_copies(tmp_path):
    """
    paths 与 benchmark 各持一份该常量（后者是按值 import 的），
    漏掉任何一份都会让 benchmark 模式继续写回仓库。
    """
    original_paths = paths.PLATFORM_OUTPUT_ROOT
    from battery_sim.simulation import benchmark

    original_bench = benchmark.PLATFORM_OUTPUT_ROOT
    target = tmp_path / "runs"
    try:
        returned = isolate_platform_outputs(target)
        assert returned == target
        assert target.is_dir()                      # 目录被创建
        assert paths.PLATFORM_OUTPUT_ROOT == target
        assert benchmark.PLATFORM_OUTPUT_ROOT == target

        # 由它解析出来的运行目录也必须落在新根之下
        run_dir = paths.platform_output_dir("demo", "baseline", "SPM", "c1")
        assert target in run_dir.parents
    finally:
        paths.PLATFORM_OUTPUT_ROOT = original_paths
        benchmark.PLATFORM_OUTPUT_ROOT = original_bench


def test_isolate_platform_outputs_is_idempotent(tmp_path):
    original_paths = paths.PLATFORM_OUTPUT_ROOT
    from battery_sim.simulation import benchmark

    original_bench = benchmark.PLATFORM_OUTPUT_ROOT
    target = tmp_path / "runs"
    try:
        isolate_platform_outputs(target)
        isolate_platform_outputs(target)            # 再调一次不应出错
        assert paths.PLATFORM_OUTPUT_ROOT == target
        assert benchmark.PLATFORM_OUTPUT_ROOT == target
    finally:
        paths.PLATFORM_OUTPUT_ROOT = original_paths
        benchmark.PLATFORM_OUTPUT_ROOT = original_bench


def test_every_phase_driver_isolates_its_outputs():
    """
    所有会跑公共 runner 的相位脚本都必须在入口调用隔离，
    否则重跑任何一个都会把 outputs/platform/ 改脏。
    """
    scripts = sorted((ROOT / "scripts").glob("graphite_phase_*.py"))
    assert scripts, "没有找到相位脚本？"
    missing = []
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        if "run_baseline_cell" not in text and "_run_case" not in text:
            continue                                # 不跑 runner 的脚本不适用
        if "isolate_platform_outputs" not in text:
            missing.append(path.name)
    assert missing == [], (
        f"这些相位脚本会跑公共 runner 但没有隔离输出：{missing}。"
        f"在入口加 isolate_platform_outputs(OUT_DIR / 'platform_runs')。"
    )
