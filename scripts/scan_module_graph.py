# -*- coding: utf-8 -*-
"""扫出单模块级依赖图。静态 AST 分析，不 import 被分析模块（不拉起 pybamm）。

用法：
    python scripts/scan_module_graph.py            # 人读报告
    python scripts/scan_module_graph.py --json     # 机器读（供 check_module_graph.py）

退出码：0。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKGS = ("battery_sim", "governance", "extraction", "identification", "analysis", "user_tools")


def module_name(p: Path) -> str:
    rel = p.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect() -> dict[str, Path]:
    mods: dict[str, Path] = {}
    for pkg in PKGS:
        d = ROOT / pkg
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            if "__pycache__" in str(p):
                continue
            mods[module_name(p)] = p
    return mods


def _resolved_relative(mod: str, level: int, node_module: str | None) -> str:
    """把相对 import 拼成绝对名。"""
    pkg_of = mod.rsplit(".", 1)[0] if "." in mod else ""
    base = pkg_of
    for _ in range(level - 1):
        base = base.rsplit(".", 1)[0] if "." in base else base
    if node_module:
        return f"{base}.{node_module}" if base else node_module
    return base


def deps_of(path: Path, known: set[str]) -> tuple[set[str], dict[str, str]]:
    """返回 (依赖模块集合, {依赖模块: 'module'|'lazy'})。

    lazy = 出现在函数/方法体内的 import（不在模块顶层）。
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set(), {}

    this_mod = module_name(path)
    found: dict[str, str] = {}

    # 记录所有函数/方法体内的行号范围
    lazy_ranges: list[tuple[int, int]] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(n, "end_lineno", n.lineno) or n.lineno
            lazy_ranges.append((n.lineno, end))

    def is_lazy(lineno: int) -> bool:
        return any(a <= lineno <= b for a, b in lazy_ranges)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                nm = a.name
                if nm in known or nm.split(".")[0] in PKGS:
                    kind = "lazy" if is_lazy(node.lineno) else "module"
                    found[nm] = "lazy" if found.get(nm) == "lazy" else kind
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                nm = _resolved_relative(this_mod, node.level, node.module)
            else:
                nm = node.module or ""
            if not nm:
                continue
            if nm.split(".")[0] not in PKGS:
                continue
            kind = "lazy" if is_lazy(node.lineno) else "module"
            found[nm] = "lazy" if found.get(nm) == "lazy" else kind
            for a in node.names:
                cand = f"{nm}.{a.name}"
                if cand in known:
                    found[cand] = "lazy" if found.get(cand) == "lazy" else kind

    found.pop(this_mod, None)
    return set(found), found


def build() -> dict:
    mods = collect()
    known = set(mods)
    graph: dict[str, list[str]] = {}
    kinds: dict[str, dict[str, str]] = {}
    for name, path in mods.items():
        ds, kd = deps_of(path, known)
        graph[name] = sorted(ds)
        kinds[name] = kd

    indeg: dict[str, int] = defaultdict(int)
    for dsts in graph.values():
        for d in dsts:
            indeg[d] += 1

    cycles = []
    for a, ds in graph.items():
        for b in ds:
            if a in graph.get(b, []):
                pair = sorted([a, b])
                if pair not in cycles:
                    cycles.append(pair)

    isolated = sorted(n for n in graph if not graph[n] and indeg.get(n, 0) == 0)
    leaves = sorted(n for n in graph if not graph[n] and indeg.get(n, 0) > 0)

    return {
        "modules": len(mods),
        "graph": graph,
        "kinds": kinds,
        "in_degree": dict(sorted(indeg.items(), key=lambda kv: (-kv[1], kv[0]))),
        "cycles": cycles,
        "isolated": isolated,
        "leaves": leaves,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    data = build()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    W = 76
    print("=" * W)
    print(f"单模块级依赖图（{data['modules']} 个模块）")
    print("=" * W)

    print("\n【被依赖最多 —— 真核心】")
    for n, c in list(data["in_degree"].items())[:20]:
        print(f"  {c:3d}  <- {n}")

    print("\n【循环依赖】")
    if data["cycles"]:
        for a, b in data["cycles"]:
            print(f"  {a}  <->  {b}")
    else:
        print("  （无）")

    print("\n【叶子：不依赖别人、但被依赖】")
    for n in data["leaves"]:
        print(f"  {data['in_degree'].get(n, 0):3d}  <- {n}")

    print("\n【孤立：没人依赖、也不依赖别人】")
    for n in data["isolated"]:
        print(f"       {n}")

    print("\n【治理层被依赖 & 反向依赖（分层实况）】")
    for src, dsts in sorted(data["graph"].items()):
        gov = [d for d in dsts if d.startswith("governance")]
        if gov:
            kd = data["kinds"].get(src, {})
            tags = ", ".join(f"{d}[{kd.get(d, '?')}]" for d in gov)
            print(f"  {src}  ->  {tags}")
        if src.startswith("governance"):
            back = [d for d in dsts if d.startswith("battery_sim")]
            if back:
                kd = data["kinds"].get(src, {})
                tags = ", ".join(f"{d}[{kd.get(d, '?')}]" for d in back)
                print(f"  ⚠ {src}  ->  {tags}   ← 反向依赖")

    return 0


if __name__ == "__main__":
    sys.exit(main())
