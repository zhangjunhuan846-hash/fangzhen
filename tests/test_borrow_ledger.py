"""借鉴溯源台账（governance/borrow_ledger.py）的**反腐烂**测试。

台账最容易坏的方式不是写错，而是**变成一厢情愿的文档**：
声称"落地了"但文件已删、声称"有测试钉住"但测试已改名。
本文件的作用就是让台账**没法**腐烂 —— 每一条声称都在这里被 grep 核对。

测试分三类：

  * **自洽性**：台账本身的结构约束（key 唯一、四类性质都有、迁移必须写改动）
  * **声称可核对**：`landed_in` 的文件真存在、`test_hook` 的函数真在测试里
  * **诚实性**：未落地的条目**不许**有 `landed_in`；失败必须能被看见
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from governance.borrow_ledger import (
    KIND_ADOPTED,
    KIND_INSPIRED,
    KIND_LABELS,
    KIND_PORTED,
    KIND_REJECTED,
    KIND_REJECTED_STATUS_LABEL,
    LEDGER,
    STATUS_LABELS,
    STATUS_LANDED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    BorrowEntry,
    entries_by_kind,
    entries_by_status,
    render_ledger,
    status_label,
    summary,
)

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"


# ------------------------------------------------------------------
# 一、自洽性
# ------------------------------------------------------------------
def test_ledger_is_not_empty():
    assert LEDGER, "台账不能是空的 —— 空台账看不出学没学到东西"


def test_keys_are_unique():
    keys = [e.key for e in LEDGER]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    assert not dup, f"key 重复：{dup}"


def test_every_entry_has_a_lesson_and_an_upstream():
    for e in LEDGER:
        assert e.lesson.strip(), f"{e.key} 没写学到了什么"
        assert e.upstream.strip(), f"{e.key} 没写上游"


def test_upstream_ref_is_specific_not_just_a_repo_name():
    """上游引用必须到**文件**级别。

    只写仓库名等于没写 —— 那是"我看过这个仓库"，不是"我学了哪一句"。
    判据：引用里必须出现一个看起来像文件路径的片段。
    """
    has_path = re.compile(r"[\w\-./]+\.(py|md|json|yaml|yml|txt|cff)|:[\d\-]")
    for e in LEDGER:
        if e.kind == KIND_REJECTED:
            # 明确不学的条目允许只写仓库名（我们本来就没进去读细节）
            continue
        assert has_path.search(e.upstream_ref), (
            f"{e.key} 的 upstream_ref 没有文件级路径：{e.upstream_ref!r} —— "
            "只写仓库名无法核对"
        )


def test_all_four_kinds_are_represented():
    """四类性质都必须出现。只列『学到什么』是半个故事。"""
    kinds = {e.kind for e in LEDGER}
    assert kinds == {KIND_PORTED, KIND_ADOPTED, KIND_INSPIRED, KIND_REJECTED}, (
        f"缺少性质：{sorted(set(KIND_LABELS) - kinds)}"
    )


def test_rejected_entries_are_present_and_explained():
    """『决定不学』这一栏必须非空且有理由。"""
    rejected = entries_by_kind(KIND_REJECTED)
    assert len(rejected) >= 3, "至少要列出几条明确不学的 —— 否则像看到什么学什么"
    for e in rejected:
        assert len(e.note.strip()) > 20, f"{e.key} 的『不学』没有给出理由"


def test_ported_entries_must_document_the_deviation():
    """**迁移必须写清改了什么。**

    上游不是为了我们的问题写的，迁移必然有改动；
    不写出来的迁移等于隐藏假设。
    """
    for e in entries_by_kind(KIND_PORTED):
        assert e.deviation.strip(), (
            f"{e.key} 标为 ported（迁移），但没写 deviation —— "
            "迁移必须说明相对上游改了什么"
        )


def test_status_values_are_from_the_declared_set():
    for e in LEDGER:
        assert e.status in STATUS_LABELS, f"{e.key} 的状态未声明：{e.status!r}"


def test_kind_values_are_from_the_declared_set():
    for e in LEDGER:
        assert e.kind in KIND_LABELS, f"{e.key} 的性质未声明：{e.kind!r}"


# ------------------------------------------------------------------
# 二、声称可核对 —— 这一组是"反腐烂"的核心
# ------------------------------------------------------------------
def _all_source_text() -> str:
    """项目里所有 py 源码拼起来（用于搜测试函数名）。"""
    parts = []
    for path in ROOT.rglob("*.py"):
        if any(seg in path.parts for seg in (".venv", "__pycache__", ".git")):
            continue
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
    return "\n".join(parts)


@pytest.mark.parametrize("entry", [e for e in LEDGER if e.landed_in])
def test_landed_files_actually_exist(entry: BorrowEntry):
    """声称落地的文件必须真存在。"""
    for rel in entry.landed_in:
        path = ROOT / rel
        assert path.exists(), f"{entry.key} 声称落在 {rel}，但文件不存在"


@pytest.mark.parametrize(
    "entry", [e for e in LEDGER if e.test_hook]
)
def test_claimed_test_hooks_exist_somewhere(entry: BorrowEntry):
    """声称钉住它的测试函数必须真能被 grep 到。

    这是台账最容易腐烂的地方：改了测试名，台账就成了假话。
    """
    blob = _all_source_text()
    for hook in entry.test_hook:
        assert f"def {hook}(" in blob, (
            f"{entry.key} 声称由 {hook} 钉住，但全项目找不到这个测试函数 —— "
            "测试改名了就必须同步台账"
        )


@pytest.mark.parametrize("entry", [e for e in LEDGER if e.landed_in])
def test_landed_files_are_python_and_parseable(entry: BorrowEntry):
    """落地文件必须能解析 —— 防止台账指向一个坏文件。"""
    for rel in entry.landed_in:
        path = ROOT / rel
        if path.suffix != ".py":
            continue
        ast.parse(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# 三、诚实性 —— 未落地的不许假装落地
# ------------------------------------------------------------------
def test_pending_entries_have_no_landed_files():
    for e in entries_by_status(STATUS_PENDING):
        assert not e.landed_in, (
            f"{e.key} 标为 pending（未落地），却写了 landed_in={e.landed_in} —— "
            "状态与事实矛盾"
        )


def test_landed_entries_must_be_pinned_by_a_test():
    """**没有测试的落地不算落地。**

    一个机制如果没有测试钉住，它会在某次重构里静默消失，
    而台账还会一直说它存在。所以 landed 必须有 test_hook。
    """
    unpinned = [e.key for e in entries_by_status(STATUS_LANDED) if not e.test_hook]
    assert not unpinned, (
        f"这些条目标为已落地但没有测试钉住：{unpinned} —— "
        "要么补测试，要么改成 partial"
    )


def test_summary_counts_add_up():
    """四栏必须恰好覆盖全表：landed + partial + pending + rejected == total。

    这一条在 2026-09-29 被改过口径：原先 ``pending`` 是**字面**
    ``status == pending`` 的条数，把 4 条「明确不学」也算进去了，
    于是 ``landed + partial + pending`` 看似"加得起来"，
    但把"主动决定不做"读成了"欠账"。
    现在 ``pending`` 排除 rejected，四栏才是不重不漏的划分。
    """
    s = summary()
    assert s["landed"] + s["partial"] + s["pending"] + s["rejected"] == s["total"], (
        "四栏不覆盖全表：有人会被算漏或被算两次"
    )
    assert s["unpinned_landed"] == [], (
        f"有已落地但无测试的条目：{s['unpinned_landed']}"
    )


def test_rejected_entries_are_not_counted_as_pending_work():
    """「明确不学」不许混进 pending —— 那是决定，不是欠账。"""
    s = summary()
    literal_pending = [e for e in LEDGER if e.status == STATUS_PENDING]
    assert s["pending"] == len(literal_pending) - s["rejected"], (
        "summary()['pending'] 没有排除「明确不学」的条目 —— "
        "汇报时『主动不学』会被读成『还没做』"
    )
    assert s["pending"] >= 0


def test_rejected_entries_render_as_not_applicable_not_as_unfinished():
    """渲染层面也要分开：rejected 的条目状态列不能是 `❌ 未落地`。"""
    for e in entries_by_kind(KIND_REJECTED):
        label = status_label(e)
        assert label != STATUS_LABELS[STATUS_PENDING], (
            f"{e.key} 是「明确不学」，却渲染成『未落地』"
        )
        assert label == KIND_REJECTED_STATUS_LABEL
    # 反过来：非 rejected 的条目仍走正常状态标签
    for e in LEDGER:
        if e.kind != KIND_REJECTED:
            assert status_label(e) == STATUS_LABELS[e.status]


def test_rendered_table_does_not_lie_about_rejected_rows():
    """表格里那 4 行「明确不学」的状态列必须是"不适用"。"""
    md = render_ledger()
    for e in entries_by_kind(KIND_REJECTED):
        rows = [ln for ln in md.splitlines() if e.lesson in ln]
        assert rows, f"{e.key} 没出现在表里"
        for row in rows:
            assert "不适用" in row, (
                f"『明确不学』那一行写成了别的状态：{row}"
            )


def test_two_discovered_gaps_are_recorded_as_landed():
    """两个被找出来的缺口（settings_hash、几何通路）**必须**在台账里。

    如果哪天它们从台账消失，说明有人在"清理"时把溯源也清掉了。
    """
    landed_keys = {e.key for e in entries_by_status(STATUS_LANDED)}
    assert "settings_fingerprint" in landed_keys
    assert any(k in landed_keys for k in ("verdict_closed_set", "noise_floor_before_threshold"))


# ------------------------------------------------------------------
# 四、渲染与 CLI
# ------------------------------------------------------------------
def test_render_ledger_produces_a_table():
    md = render_ledger()
    assert md.startswith("|"), "应当以 markdown 表头开头"
    # 表头一行 + 分隔一行 + 条目若干行
    assert len(md.splitlines()) == len(LEDGER) + 2


def test_render_ledger_only_landed_is_a_strict_subset():
    full = render_ledger().splitlines()
    only = render_ledger(only_landed=True).splitlines()
    assert len(only) < len(full)
    assert len(only) == len(entries_by_status(STATUS_LANDED)) + 2


def test_cli_help_runs():
    """CLI 必须能跑 —— 台账要能被直接贴进汇报。"""
    from governance.borrow_ledger import main

    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0


def test_cli_unknown_key_returns_error_code():
    from governance.borrow_ledger import main

    assert main(["--key", "no_such_key"]) == 2


def test_module_does_not_import_the_simulation_stack():
    """台账是纯文档结构，不许依赖仿真栈。"""
    src = (ROOT / "governance" / "borrow_ledger.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in tree.body:  # 只看模块级
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    banned = {"pybamm", "pandas", "numpy", "battery_sim"}
    assert not (mods & banned), f"台账顶层不得依赖：{sorted(mods & banned)}"


def test_governance_package_still_importable():
    """新增模块不许把 governance 包弄坏。"""
    import governance  # noqa: F401
    import governance.analysis_mode  # noqa: F401
    import governance.borrow_ledger  # noqa: F401
    import governance.dataset_roles  # noqa: F401
    import governance.geometry_channel  # noqa: F401
    import governance.noise_floor  # noqa: F401
    import governance.scale_alignment  # noqa: F401
    import governance.settings_hash  # noqa: F401
