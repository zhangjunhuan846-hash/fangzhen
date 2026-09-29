# -*- coding: utf-8 -*-
"""MODULE_GRAPH.yaml（单模块级依赖图）与代码实况的一致性测试。

为什么要有：老师指出「要细化得看代码」「模块和模块之间就成了关键」。
依赖图如果不与代码同步，它就会在下次重构后变成错的 —— 而错的依赖图比没有更糟。

本测试把「图必须与代码一致」变成红灯。
纯标准库，不 import pybamm、不需要网络。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GRAPH_YAML = ROOT / "MODULE_GRAPH.yaml"
SCANNER = ROOT / "scripts" / "scan_module_graph.py"
CHECKER = ROOT / "scripts" / "check_module_graph.py"


@pytest.fixture(scope="module")
def graph_text() -> str:
    assert GRAPH_YAML.is_file(), f"MODULE_GRAPH.yaml 不存在：{GRAPH_YAML}"
    return GRAPH_YAML.read_text(encoding="utf-8")


def test_graph_yaml_exists():
    assert GRAPH_YAML.is_file()


def test_scanner_and_checker_exist():
    assert SCANNER.is_file(), f"缺少扫描器：{SCANNER}"
    assert CHECKER.is_file(), f"缺少校验器：{CHECKER}"


def test_graph_records_the_single_module_granularity(graph_text):
    """图必须是单模块级，不能退回目录级。"""
    assert "in_degree" in graph_text
    assert "battery_sim.paths" in graph_text


def test_graph_names_the_top_hub(graph_text):
    """最高被依赖的模块必须被点名 —— 它是 paths.py，不是整个 battery_sim/。"""
    assert "battery_sim.paths" in graph_text
    assert re.search(r"in_degree:\s*16", graph_text), "paths.py 的 in-degree 应为 16"


def test_graph_records_cross_layer_direction(graph_text):
    """跨层依赖方向必须被记录，且要区分 lazy 与 module 级。"""
    assert "cross_layer:" in graph_text
    assert "lazy" in graph_text
    assert "protocol_replay" in graph_text


def test_graph_records_the_fixed_back_dependency(graph_text):
    """geometry_channel 的模块级反向依赖**已修**（2026-09-29）。

    这条原先断言 "ok: false"（存在未修问题）。修复后它必须变为
    记录"已修 + 修复前后实测差异"，否则图就成了过期的告警。
    """
    assert "governance.geometry_channel" in graph_text
    assert "已修" in graph_text, "必须记录该问题已修复"
    # 修复的实质证据要写进图里，供后来人核对
    assert "0" in graph_text and "6" in graph_text, (
        "应记录修复前后的实测差异（导入期牵连 6 → 0 个内核模块）"
    )


def test_graph_has_no_unfixed_layering_problem(graph_text):
    """当前不应存在未修的分层问题（ok: false）。"""
    assert "ok: false" not in graph_text, (
        "MODULE_GRAPH.yaml 里仍有 ok: false 的未修项。"
        "若确为新引入的问题，请先修复；若不是，请更新该条目"
    )


def test_graph_documents_the_research_vs_industry_marks(graph_text):
    """科研/工业双档只标注不展开 —— 标记必须存在。"""
    assert "research_vs_industry" in graph_text
    assert "industry" in graph_text


def test_scanner_runs_and_reports_module_count():
    proc = subprocess.run(
        [sys.executable, str(SCANNER)], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"扫描器失败：{proc.stderr}"
    assert "单模块级依赖图" in proc.stdout
    m = re.search(r"（(\d+) 个模块）", proc.stdout)
    assert m and int(m.group(1)) >= 70, f"模块数异常：{proc.stdout[:200]}"


def test_scanner_json_mode_is_valid():
    import json
    proc = subprocess.run(
        [sys.executable, str(SCANNER), "--json"], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    for key in ("modules", "graph", "in_degree", "cycles", "isolated", "leaves"):
        assert key in data, f"JSON 缺少字段：{key}"
    assert data["in_degree"]["battery_sim.paths"] == 16


def test_checker_passes_on_current_tree():
    """端到端：图与代码必须一致（rc=0）。图漂移了这里会红。"""
    proc = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"依赖图校验未通过（rc={proc.returncode}）：\n{out}"


def test_checker_reports_kind_for_every_back_dependency():
    """校验器必须对每条反向依赖都报出 kind（不是只报个总数）。

    修复后全平台已无 `[module]` 级反向依赖，所以旧断言
    "输出里必须同时有 [module] 和 [lazy]" 不再成立。
    但**不能因此就删掉这条测试** —— 那等于放任 kind 检查退化成装饰。
    改成：每条反向依赖都必须带一个 kind 标记。
    """
    proc = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    out = proc.stdout or ""
    dep_lines = [l for l in out.splitlines() if "反向依赖 kind" in l]
    assert dep_lines, "校验器应逐条报告反向依赖的 kind"
    assert all("[lazy]" in l or "[module]" in l for l in dep_lines), (
        f"每条反向依赖都必须标出 kind。实际：{dep_lines}"
    )
    assert all("kind 一致" in l for l in dep_lines), "逐条都必须给出判定结论"


def test_checker_kind_check_actually_fails_on_a_wrong_declaration():
    """用**变造输入**证明 kind 检查真的会红（否则它就是个装饰）。

    做法：把图里 geometry_channel 那条声明的 kind 改成 module 级，
    校验器必须 FAIL —— 因为实测是 lazy。
    这是唯一能在"当前没有任何 module 级反向依赖"的情况下
    证明该检查仍有牙齿的办法。
    """
    import tempfile

    real = GRAPH_YAML.read_text(encoding="utf-8")
    # 找到 geometry_channel 那条的 kind 行，把 lazy 谎报成 module
    tainted = real.replace(
        'kind: "lazy（函数体内 import）"',
        'kind: "module（文件顶部 import）"',
        1,
    )
    assert tainted != real, (
        "没能变造出错误的 kind 声明 —— 图的写法变了，本测试需同步更新"
    )

    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "MODULE_GRAPH.yaml"
        fake.write_text(tainted, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(CHECKER), "--graph", str(fake)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, (
        "谎报 kind（把 lazy 说成 module）时校验器必须失败，"
        f"否则该检查没有问题检测能力。输出：{out}"
    )


# ------------------------------------------------------------------
# 防回退：geometry_channel 的模块级反向依赖已修（2026-09-29, v0.1.1）
# ------------------------------------------------------------------
def test_checker_reports_geometry_channel_as_lazy():
    """原为 [module] 的反向依赖，修复后必须被扫描器判读为 [lazy]。

    这一条是**防回退**：若有人把 load_metadata 的 import 挪回文件顶部，
    扫描器会重新判成 [module]，此处立刻红。
    """
    proc = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    out = proc.stdout or ""
    line = [l for l in out.splitlines() if "geometry_channel" in l]
    assert line, "校验输出里应出现 geometry_channel 这条反向依赖"
    joined = "\n".join(line)
    assert "[lazy]" in joined, (
        "geometry_channel -> material_metadata 必须是 lazy 级；"
        f"实际输出：{joined}"
    )
    assert "[module]" not in joined, (
        "geometry_channel 又变回模块级 import 了（导入期牵连内核）—— "
        f"这正是要防的回退。实际输出：{joined}"
    )


def test_governance_geometry_channel_does_not_pull_battery_sim_at_import():
    """行为级验证：`import governance.geometry_channel` 不许牵连任何内核模块。

    这是修复的**实质**，比字符串匹配更硬：不关心 import 写在哪，
    只关心导入期到底拉起了什么。
    """
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import governance.geometry_channel  # noqa: F401\n"
        "pulled = sorted(m for m in set(sys.modules) - before"
        " if m.startswith('battery_sim'))\n"
        "print(len(pulled))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(ROOT),
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"导入失败：{proc.stderr}"
    n = int(proc.stdout.strip().splitlines()[-1])
    assert n == 0, (
        f"import governance.geometry_channel 牵连了 {n} 个 battery_sim 模块；"
        "治理层与内核在导入期不应焊接"
    )


def test_graph_no_longer_claims_an_unfixed_problem(graph_text):
    """图必须反映已修复的事实，不能再留着 `ok: false` 这条未修记录。"""
    assert "ok: false" not in graph_text, (
        "MODULE_GRAPH.yaml 里仍有 ok: false 的未修项；"
        "若确为再次引入的新问题，请先修复并同步更新该条目"
    )
    assert "已修" in graph_text, "应记录该问题已修复（含日期与版本）"

