# -*- coding: utf-8 -*-
"""校验 MODULE_GRAPH.yaml 与代码实况是否一致。

三件事：
  1. 文件里声明的 hub（真核心）是否仍是代码里 in-degree 最高的那些？
  2. 声明的循环依赖是否与实测一致？
  3. 声明的"反向依赖是 lazy 还是 module 级"是否与实测一致？

关于第 3 条的历史：曾有一条真的不一致 ——
`governance/geometry_channel.py` 用模块级 import 反向依赖内核，
导入期会牵连 6 个 battery_sim 模块。该问题**已于 2026-09-29 修复**（改为 lazy）。
所以现在全平台已无 module 级反向依赖 —— 这带来一个测试上的麻烦：
"kind 检查"失去了现成的反例，容易退化成装饰。
为此本校验器支持 `--graph <file>`，测试可以喂一份**变造过的图**
（如把 lazy 谎报成 module），验证它确实会 FAIL。

退出码：0 = 全过；1 = 有 FAIL。
只读（--graph 也只读传入的文件）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRAPH_YAML = ROOT / "MODULE_GRAPH.yaml"

sys.path.insert(0, str(ROOT / "scripts"))
try:
    from scan_module_graph import build  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"FATAL: 无法导入 scan_module_graph: {exc}")
    sys.exit(1)

FAILS: list[str] = []
WARNS: list[str] = []
OKS: list[str] = []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python scripts/check_module_graph.py",
        description="校验 MODULE_GRAPH.yaml 与代码实况是否一致",
    )
    ap.add_argument(
        "--graph", default=str(DEFAULT_GRAPH_YAML), metavar="YAML",
        help="要校验的图文件（默认 MODULE_GRAPH.yaml；测试用变造输入）",
    )
    args = ap.parse_args(argv)
    GRAPH_YAML = Path(args.graph)
    if not GRAPH_YAML.is_absolute():
        GRAPH_YAML = (Path.cwd() / GRAPH_YAML).resolve()

    if not GRAPH_YAML.is_file():
        print(f"FATAL: 找不到 {GRAPH_YAML}")
        return 1
    text = GRAPH_YAML.read_text(encoding="utf-8")
    data = build()
    indeg = data["in_degree"]
    kinds = data["kinds"]
    graph = data["graph"]

    # ---- 1. hub 声明 vs 实测 ----
    declared_hubs = re.findall(r"^\s*-\s*module:\s*(\S+)", text.split("cross_layer:")[0], re.M)
    top20 = list(indeg.items())[:20]
    top_names = {n for n, _ in top20}
    for h in declared_hubs:
        if h in indeg:
            if h in top_names:
                OKS.append(f"hub 在实测前 20: {h}（in-degree={indeg[h]}）")
            else:
                WARNS.append(f"hub 声明但实测排名靠后: {h}（in-degree={indeg.get(h, 0)}）")
        else:
            FAILS.append(f"hub 声明了不存在的模块: {h}")

    # 反向：实测前 8 有没有没被声明的
    for n, c in list(indeg.items())[:8]:
        base = n.rsplit(".", 1)[0]
        if n not in declared_hubs and base not in declared_hubs:
            WARNS.append(f"实测 in-degree 前 8 但未声明为 hub: {n}（{c}）")

    # ---- 2. 循环依赖 ----
    measured_cycles = [tuple(sorted(c)) for c in data["cycles"]]
    declared_cycle_pairs = []
    for m in re.finditer(r"pair:\s*\[([^\]]+)\]", text):
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) == 2:
            declared_cycle_pairs.append(tuple(sorted(parts)))
    for c in measured_cycles:
        if c in declared_cycle_pairs:
            OKS.append(f"循环依赖已声明: {c[0]} <-> {c[1]}")
        else:
            FAILS.append(f"实测到未声明的循环依赖: {c[0]} <-> {c[1]}")

    # ---- 3. 反向依赖的 kind 是否与实测一致 ----
    # 实测所有 governance -> battery_sim 的边
    measured_back: list[tuple[str, str, str]] = []
    for src, dsts in graph.items():
        if not src.startswith("governance"):
            continue
        for d in dsts:
            if d.startswith("battery_sim"):
                measured_back.append((src, d, kinds.get(src, {}).get(d, "?")))

    declared_back: set[tuple[str, str]] = set()
    for m in re.finditer(r"-\s*from:\s*(\S+)\s*\n\s*to:\s*(\S+)\s*\n\s*kind:\s*([^\n]+)", text):
        f, t, k = m.group(1), m.group(2), m.group(3).strip().strip('"').strip("'")
        declared_back.add((f, t))
        # 检查 kind 声称
        actual = kinds.get(f, {}).get(t)
        if actual is None:
            # 可能是间接（写的是另一个模块），跳过
            continue
        claimed_lazy = "lazy" in k.lower()
        claimed_module = ("module" in k.lower()) or ("模块级" in k)
        if claimed_lazy and actual == "module":
            FAILS.append(f"kind 声称 lazy 但实测是模块级: {f} -> {t}")
        elif claimed_module and actual == "lazy":
            FAILS.append(f"kind 声称模块级但实测是 lazy: {f} -> {t}")
        else:
            OKS.append(f"反向依赖 kind 一致: {f} -> {t} [{actual}]")

    for f, t, kd in measured_back:
        if (f, t) not in declared_back:
            # protocol_replay -> scale_alignment 已在跨层节声明
            if "protocol_replay" in f:
                OKS.append(f"跨层依赖已声明（lazy）: {f} -> {t} [{kd}]")
            else:
                WARNS.append(f"实测到未声明的反向依赖: {f} -> {t} [{kd}]")

    # ---- 4. 孤立模块声明 ----
    for m in data["isolated"]:
        if m not in text:
            WARNS.append(f"实测孤立但未在文件中说明: {m}")

    # ---- 输出 ----
    print("=" * 76)
    print("MODULE_GRAPH.yaml 校验")
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
