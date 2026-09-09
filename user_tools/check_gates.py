#!/usr/bin/env python3
# ============================================================
# S6 参数门 + S4 校验门的负例自测
#
# 目的：证明"没有合理参数 -> SIMULATION = NOT AVAILABLE"
#       而不是偷偷换一个参数集来跑。
# 本脚本 0 pybamm、0 仿真，纯规则检查。
#
# 运行：python -m user_tools.check_gates
# ============================================================

from __future__ import annotations

from user_tools.spec import parameter_gate

CASES = [
    ("LFP 全电池", {
        "chemistry": "LFP", "cell_configuration": "full_cell",
    }, True, "Prada2013"),
    ("NMC 全电池", {
        "chemistry": "NMC", "cell_configuration": "full_cell",
    }, True, "Chen2020"),
    ("LCO 全电池（不支持）", {
        "chemistry": "LCO", "cell_configuration": "full_cell",
    }, False, None),
    ("NMC 正半电池 2.0 mAh/cm2（设计匹配）", {
        "chemistry": "NMC", "cell_configuration": "half_cell",
        "working_electrode": "positive",
        "counter_electrode": "lithium_metal",
        "active_material_loading": 2.0,
    }, True, "Jackowska2025_2mAh_cm2"),
    ("NMC 正半电池 5.0 mAh/cm2（设计不匹配）", {
        "chemistry": "NMC", "cell_configuration": "half_cell",
        "working_electrode": "positive",
        "counter_electrode": "lithium_metal",
        "active_material_loading": 5.0,
    }, False, None),
    ("NMC 正半电池未填面容量", {
        "chemistry": "NMC", "cell_configuration": "half_cell",
        "working_electrode": "positive",
        "counter_electrode": "lithium_metal",
    }, False, None),
    ("LFP 半电池（不支持）", {
        "chemistry": "LFP", "cell_configuration": "half_cell",
        "working_electrode": "positive",
        "counter_electrode": "lithium_metal",
        "active_material_loading": 2.0,
    }, False, None),
    ("未填化学体系", {
        "chemistry": "", "cell_configuration": "full_cell",
    }, False, None),
]


def main() -> int:
    print("=" * 74)
    print("  S6 parameter compatibility gate -- 正例/负例自测")
    print("=" * 74)
    ok = True
    for name, exp, expect_avail, expect_ps in CASES:
        g = parameter_gate(exp)
        got_avail = bool(g["available"])
        got_ps = g["parameter_set"]
        good = (got_avail == expect_avail) and (
            expect_ps is None or got_ps == expect_ps
        )
        ok = ok and good
        status = "OK " if good else "BAD"
        print(f"  [{status}] {name}")
        print(
            f"          -> available={got_avail} "
            f"parameter_set={got_ps} "
            f"level={g['level']} grade={g['grade']} "
            f"fitted={g['fitted_to_dataset']}"
        )
        if not g["available"] and g["blockers"]:
            for b in g["blockers"]:
                print(f"             blocker: {b}")
    print("=" * 74)
    print("  结论：" + ("全部符合预期 ✓" if ok else "存在不符合预期项 ✗"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
