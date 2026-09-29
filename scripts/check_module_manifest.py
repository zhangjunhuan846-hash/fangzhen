# -*- coding: utf-8 -*-
"""清单校验：让 MODULES.yaml 从"一份文档"变成"一个契约"。

三件事：
  1. 清单里登记的路径**真的存在**吗？（防清单腐烂）
  2. 标为 core 的模块**真的有测试覆盖**吗？（防"自称核心却没测试"）
  3. scripts/ 下**有没有未登记的文件**？（防下一个探针悄悄溜进来）

退出码：0 = 全过；1 = 有 FAIL。可以直接进 CI。

只读。不修改任何文件。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "MODULES.yaml"
TESTS = ROOT / "tests"
SCRIPTS = ROOT / "scripts"

FAILS: list[str] = []
WARNS: list[str] = []
OKS: list[str] = []


def load_manifest_text() -> str:
    if not MANIFEST.is_file():
        print(f"FATAL: 找不到 {MANIFEST}")
        sys.exit(1)
    return MANIFEST.read_text(encoding="utf-8")


def gather_test_text() -> dict[str, str]:
    out = {}
    if not TESTS.is_dir():
        return out
    for p in sorted(TESTS.glob("*.py")):
        out[p.name] = p.read_text(encoding="utf-8", errors="replace")
    return out


def module_is_tested(rel_path: str, test_text: dict[str, str]) -> list[str]:
    """返回提及该模块的测试文件名列表。与 .scan_coverage.py 同口径。

    三种命中方式（脚本类模块常只以路径字符串出现，故必须支持第三种）：
      a) 点号模块名      governance.noise_floor
      b) 仓库内相对路径  governance/noise_floor.py
      c) 纯文件名        noise_floor.py  ← 脚本类模块（scripts/xxx.py）靠这条
    """
    p = Path(rel_path)
    stem = p.stem
    dotted = rel_path[:-3].replace("/", ".") if rel_path.endswith(".py") else ""
    basename = p.name
    hits = []
    for name, txt in test_text.items():
        if dotted and (dotted in txt or f"from {dotted} import" in txt):
            hits.append(name)
            continue
        if rel_path in txt:
            hits.append(name)
            continue
        # 纯文件名：对 scripts/ 下的脚本适用（如 "scan_module_graph.py"）
        if basename.endswith(".py") and basename in txt:
            hits.append(name)
            continue
        # 目录型条目：看目录名是否作为包被 import
        if not dotted and len(stem) >= 6 and re.search(rf"\b{re.escape(stem)}\b", txt):
            hits.append(name)
    return hits


def main() -> int:
    text = load_manifest_text()
    test_text = gather_test_text()

    if not test_text:
        WARNS.append("tests/ 目录为空或不存在 ⇒ 无法验证『删了会不会红』判据")

    # ---------- 检查 1：清单里出现的路径是否真实存在 ----------
    # 只检查看起来像仓库内相对路径的（含 / 或以已知顶层目录开头）
    TOP = ("battery_sim", "governance", "extraction", "identification", "analysis",
           "user_tools", "configs", "templates", "examples", "parameters",
           "external", "scripts", "tests", "docs", "outputs")
    declared: set[str] = set()
    for m in re.finditer(r"^\s*-?\s*(?:path|content):\s*(.+)$", text, re.M):
        raw = m.group(1).strip().strip('"').strip("'")
        for tok in re.split(r"\s+", raw):
            tok = tok.strip().rstrip(",")
            if not tok or tok.startswith("#"):
                continue
            if "/" not in tok:
                continue
            head = tok.split("/")[0]
            if head not in TOP:
                continue
            declared.add(tok)

    for rel in sorted(declared):
        if "*" in rel:
            continue  # 通配条目单独检查
        target = ROOT / rel
        if target.exists():
            OKS.append(f"存在: {rel}")
        else:
            FAILS.append(f"清单登记了不存在的路径: {rel}")

    # ---------- 检查 3：scripts/ 未登记文件 ----------
    if SCRIPTS.is_dir():
        on_disk = sorted(
            p.relative_to(SCRIPTS).as_posix()
            for p in SCRIPTS.rglob("*.py")
            if "__pycache__" not in str(p)
        )
        # 清单里写到 scripts 的部分
        declared_scripts = set()
        for m in re.finditer(r"^\s*-?\s*path:\s*scripts/(\S+)$", text, re.M):
            declared_scripts.add(m.group(1))
        # 通配声明（清单用 glob 概括的部分）
        wildcard_families = ("probe_", "_", "audit", "dev", "lfp_", "halfcell_birmingham",
                             "graphite", "identification", "sensitivity", "runners", "adapters")

        # 清单中"逐条登记"的顶层脚本（explicit 节 + 单列 path 条目）
        explicit_top = set()
        for m in re.finditer(r"^\s*-\s*([a-z0-9_]+\.py):\s", text, re.M | re.I):
            explicit_top.add(m.group(1))
        for m in re.finditer(r"^\s*-\s*path:\s*scripts/([A-Za-z0-9_]+\.py)$", text, re.M):
            explicit_top.add(m.group(1))

        def covered_by_wildcard(rel: str) -> bool:
            base = rel.split("/")[-1]
            if base in explicit_top:
                return True
            if base.startswith("probe_") or base.startswith("_"):
                return True
            if base.startswith("graphite_phase_") and base.endswith(".py"):
                return True
            if any(rel.startswith(w) for w in ("audit/", "dev/", "lfp_", "halfcell_birmingham/",
                                               "graphite/", "identification/", "sensitivity/",
                                               "runners/", "adapters/")):
                return True
            return False

        unregistered = [r for r in on_disk
                        if r not in declared_scripts and not covered_by_wildcard(r)]
        total_unwept = len(unregistered)
        if total_unwept:
            WARNS.append(
                f"scripts/ 下有 {total_unwept} 个文件既未按路径登记、也不属于任何通配族 —— "
                f"新模块应在此处显式登记：{unregistered[:8]}"
                + (" ..." if total_unwept > 8 else "")
            )
        else:
            OKS.append(f"scripts/ 全部 {len(on_disk)} 个文件都有归属（显式登记或通配族）")

    # ---------- 检查 2：core 条目是否真的有测试 ----------
    core_block = text.split("optional:", 1)[0]
    core_paths = re.findall(r"^\s*- path:\s*(\S+)", core_block, re.M)
    for rel in core_paths:
        rel = rel.strip().strip('"').strip("'")
        if rel.startswith("Batter") or rel.startswith("C:") or rel.startswith("repos"):
            continue  # 外部仓库，不在本脚本职责内
        if "*" in rel:
            continue
        hits = module_is_tested(rel, test_text)
        if hits:
            OKS.append(f"core 有测试: {rel}  <- {len(hits)} 个测试文件")
        else:
            # 允许显式声明为"结构性依赖"的例外
            idx = text.find(f"- path: {rel}")
            ctx = text[idx:idx + 900] if idx >= 0 else ""
            if "无测试" in ctx or "test_hook: null" in ctx or "结构性" in ctx:
                WARNS.append(f"core 无测试（已声明例外）: {rel}")
            else:
                FAILS.append(f"标为 core 但没有任何测试提及，且未声明例外: {rel}")

    # ---------- 输出 ----------
    print("=" * 76)
    print("MODULES.yaml 清单校验")
    print("=" * 76)
    for s in OKS:
        print(f"  [OK]   {s}")
    for s in WARNS:
        print(f"  [WARN] {s}")
    for s in FAILS:
        print(f"  [FAIL] {s}")
    print("-" * 76)
    print(f"合计：OK {len(OKS)} / WARN {len(WARNS)} / FAIL {len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
