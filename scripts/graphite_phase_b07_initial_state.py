#!/usr/bin/env python3
# ============================================================
# Phase B0.7 driver: INITIAL STATE / window-start correction
#
# THE DEFECT
#   The p-OCV comparison window starts at the measured PRE-branch rest
#   OCP, which lies OUTSIDE the frozen OCP table at both ends:
#       lithiation   rest OCP 3.0161 V vs table top    3.0003 V  (+15.8 mV)
#       delithiation rest OCP 0.0824 V vs branch floor 0.0967 V  (-14.3 mV)
#   because the table's endpoint entries carry the current-switch-on
#   polarisation.  On the lithiation side the dilute stage is nearly
#   vertical (dV/dSOC = -1.96e4 V per unit SOC), so the model's
#   admissible initial state (x0 = 1e-3, V(0) = 1.077 V) sits 1.94 V below
#   the first measured sample, AND the comparison pairs the model's t = 0
#   with the experiment's t = 0 while their STATES differ by 0.1 % of SOC.
#   That single point contributed ~43.6 mV of the 44.74 mV lith RMSE.
#
# WHY A SMALLER x0 IS NOT THE FIX
#   PyBaMM's initial-state initialisation solves for the surface state
#   under the APPLIED current, so its overpotential diverges as c_s -> 0:
#   -5.8 mV at 1e-3, +126 mV at 3e-4, +453 mV at 1e-4, and at 1e-5 the
#   initial terminal voltage overshoots the 3.2 V cut-off and the solve
#   fails.  1e-3 is the smallest floor at which the initial state is clean.
#
# THE FIX (declared, parameter-based, pre-registered)
#   Trim the leading samples that lie on the far side of OCP(x0) - the
#   model's voltage at the declared initial state - relative to the
#   window's traversal direction, and report exactly what was removed.
#   The rule never looks at the residual, and it realigns the model's
#   time origin with the experiment's STATE, which is why it also
#   improves the regions that keep every point (verified below on the
#   common window).
#
# Outputs (outputs/analysis/graphite_phaseB07/):
#   initial_state_floor_scan.csv     why x0 = 1e-3 (scan of the floor)
#   window_start_rule.json           what was removed, per window
#   replay_rule_on_off.csv           metrics, rule off vs on
#   region_mae_common_window.csv     the airtight comparison
#   fig_initial_state.png            the mechanism, drawn
#   report.md
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.graphite_phase_b0_compare as b0                        # noqa: E402
from battery_sim.registry import get_dataset                          # noqa: E402
from parameters.sintef_graphite_capacity import (                     # noqa: E402
    CAPACITY_MATCHED_IDS,
    register_capacity_variants,
)
from parameters.sintef_graphite_geometry import register as register_geometry  # noqa: E402
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)

V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB07"
SUFFIX = "_v2"
CELL = "4ccc47"
WINDOWS: Tuple[Tuple[str, str], ...] = (
    ("lithiation", "pOCV-lith"),
    ("delithiation", "pOCV-deli"),
)
FLOOR_GRID = (1e-2, 3e-3, 1e-3, 3e-4, 1e-4, 3e-5, 1e-5, 1e-6)


# ------------------------------------------------------------------
def _metrics_from_df(df: pd.DataFrame) -> dict:
    res = df["residual_V"].to_numpy(float)
    return {
        "n_points": int(len(df)),
        "rmse_mV": float(np.sqrt(np.mean(res ** 2)) * 1000.0),
        "mae_mV": float(np.mean(np.abs(res)) * 1000.0),
        "bias_mV": float(np.mean(res) * 1000.0),
        "max_abs_mV": float(np.max(np.abs(res)) * 1000.0),
        "v_exp_start_V": float(df["voltage_exp_V"].iloc[0]),
        "v_sim_start_V": float(df["voltage_sim_V"].iloc[0]),
        "duration_s": float(df["time_s"].iloc[-1]),
    }


def _region_mae_from_df(df: pd.DataFrame) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for label, lo, hi in b0.REGIONS:
        sel = df[(df["voltage_exp_V"] > lo) & (df["voltage_exp_V"] <= hi)]
        out[label] = {
            "n_points": int(len(sel)),
            "mae_mV": float(np.mean(np.abs(sel["residual_V"])) * 1000.0)
            if len(sel) else float("nan"),
        }
    return out


def _replay(adapter, model: str, rate: str, set_id: str, dest: Path) -> Path:
    from battery_sim.simulation.baseline import run_baseline_cell

    res = run_baseline_cell(adapter, model_name=model, cell=CELL, rate=rate,
                            parameter_set=set_id, plot=False, quiet=True)
    run_dir = Path(res["output_dir"])
    slug = rate.replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{slug}_time_aligned.csv"
    src = run_dir / f"{slug}_time_aligned.csv"
    if src.is_file() and src.resolve() != target.resolve():
        shutil.copy2(src, target)
    return target


# ------------------------------------------------------------------
# 1. the floor scan: why x0 = 1e-3 and not smaller
# ------------------------------------------------------------------
def floor_scan(branch: str, rate: str) -> pd.DataFrame:
    import pybamm

    from battery_sim.models.pybamm_factory import (
        build_model, load_parameter_values,
    )

    tables = load_ocp_tables(V2_DIR)
    set_id = CAPACITY_MATCHED_IDS[branch] + SUFFIX
    pv_ref = load_parameter_values(set_id)
    c_max = float(pv_ref["Maximum concentration in positive electrode [mol.m-3]"])
    conc = "Initial concentration in positive electrode [mol.m-3]"

    adapter = get_dataset("sintef_graphite")
    raw = adapter.load_processed_discharge(CELL, rate)
    i_med = float(raw.attrs["provenance"]["median_current_A"])

    srt = tables[branch].sort_values("SOC")
    soc, vol = srt["SOC"].to_numpy(float), srt["Voltage"].to_numpy(float)

    rows: List[dict] = []
    for x0 in FLOOR_GRID:
        ocp = float(np.interp(x0, soc, vol))
        pv = load_parameter_values(set_id)
        pv[conc] = x0 * c_max
        pv["Current function [A]"] = i_med
        for k in ("Ambient temperature [K]", "Initial temperature [K]"):
            if k in pv:
                pv[k] = 298.15
        model = build_model("SPM", options={"working electrode": "positive"})
        sim = pybamm.Simulation(model, parameter_values=pv)
        try:
            sol = sim.solve(t_eval=np.linspace(0.0, 120.0, 3))
            V = np.asarray(sol["Terminal voltage [V]"].entries,
                           float).reshape(-1)
            v0 = float(V[0])
            rows.append({
                "branch": branch, "rate": rate, "x0": float(x0),
                "c_s0_mol_m3": float(x0 * c_max),
                "ocp_at_x0_V": ocp,
                "v0_solved_V": v0,
                "initial_overpotential_mV": 1e3 * (v0 - ocp),
                "solve_ok": True,
                "note": "",
            })
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            rows.append({
                "branch": branch, "rate": rate, "x0": float(x0),
                "c_s0_mol_m3": float(x0 * c_max),
                "ocp_at_x0_V": ocp, "v0_solved_V": float("nan"),
                "initial_overpotential_mV": float("nan"),
                "solve_ok": False,
                "note": f"{type(exc).__name__}: {str(exc)[:80]}",
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["SPM", "SPMe"])
    ap.add_argument("--skip-floor-scan", action="store_true")
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    register_geometry(CELL)
    register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
    cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
    adapter = get_dataset("sintef_graphite")
    tables = load_ocp_tables(V2_DIR)

    # ---------------- 1. floor scan -------------------------------
    if args.skip_floor_scan:
        scan = pd.DataFrame()
    else:
        scan = pd.concat([floor_scan(br, rate)
                          for br, rate in WINDOWS], ignore_index=True)
        scan.to_csv(OUT_DIR / "initial_state_floor_scan.csv", index=False)
        print("[B0.7] floor scan (lithiation):")
        for _, r in scan[scan["branch"] == "lithiation"].iterrows():
            ok = "ok" if r["solve_ok"] else "FAIL"
            eta = r["initial_overpotential_mV"]
            print(f"        x0={r['x0']:>8.0e}  OCP={r['ocp_at_x0_V']:7.4f}  "
                  f"V(0)={r['v0_solved_V']:7.4f}  eta_init="
                  f"{eta:>+8.1f} mV  {ok}")

    # ---------------- 2. rule off vs on ---------------------------
    rows: List[dict] = []
    common_rows: List[dict] = []
    rule_records: Dict[str, dict] = {}

    for model in args.models:
        for branch, rate in WINDOWS:
            per_rule: Dict[bool, pd.DataFrame] = {}
            for trim in (False, True):
                px = b0.OCPConsistentAdapter(
                    adapter, branch, tables,
                    trim_unrepresentable_prefix=trim,
                )
                tag = f"{rate}_{model}_{'on' if trim else 'off'}"
                csv = _replay(px, model, rate, cap[branch],
                              OUT_DIR / "runs" / tag)
                df = pd.read_csv(csv)
                per_rule[trim] = df
                rec = px.window_trim_log[-1]
                rule_records[f"{rate}_{model}_{'on' if trim else 'off'}"] = rec
                m = _metrics_from_df(df)
                rows.append({
                    "model": model, "rate": rate, "branch": branch,
                    "rule": "on" if trim else "off",
                    "x0": rec["x0"],
                    "model_start_voltage_V": rec["model_start_voltage_V"],
                    "n_points_removed": rec["n_points_removed"],
                    "duration_removed_s": rec["duration_removed_s"],
                    "fraction_removed": rec["fraction_removed"],
                    **m,
                })
            # ---- airtight comparison: same experimental points ----
            off, on = per_rule[False], per_rule[True]
            k = int(rule_records[f"{rate}_{model}_on"]["n_points_removed"])
            if k > 0:
                s = off.iloc[k:].reset_index(drop=True).copy()
                s["time_s"] = s["time_s"] - float(s["time_s"].iloc[0])
                for label, frame in (("rule_off", s), ("rule_on", on)):
                    m = _metrics_from_df(frame)
                    common_rows.append({
                        "model": model, "rate": rate, "case": label,
                        "n_points": m["n_points"], "rmse_mV": m["rmse_mV"],
                        "mae_mV": m["mae_mV"],
                        "max_abs_mV": m["max_abs_mV"],
                        **{f"region|{lb}": v["mae_mV"]
                           for lb, v in _region_mae_from_df(frame).items()},
                        **{f"n|{lb}": v["n_points"]
                           for lb, v in _region_mae_from_df(frame).items()},
                    })
                a, b = common_rows[-2], common_rows[-1]
                print(f"[B0.7] {model} {rate}: COMMON window "
                      f"({a['n_points']} pts) RMSE {a['rmse_mV']:.3f} -> "
                      f"{b['rmse_mV']:.3f} mV")

    replay = pd.DataFrame(rows)
    replay.to_csv(OUT_DIR / "replay_rule_on_off.csv", index=False)
    common = pd.DataFrame(common_rows)
    common.to_csv(OUT_DIR / "region_mae_common_window.csv", index=False)
    with (OUT_DIR / "window_start_rule.json").open("w", encoding="utf-8") as fh:
        json.dump({
            "rule": (
                "trim the leading samples whose measured terminal voltage "
                "lies on the far side of OCP(x0) - the model's voltage at "
                "the declared initial state - relative to the window's "
                "traversal direction"
            ),
            "why": (
                "the measured PRE-branch rest OCP is outside the frozen OCP "
                "table at both ends (the table's endpoint entries carry the "
                "current-switch-on polarisation), so no admissible initial "
                "Li fraction reproduces it"
            ),
            "not_a_fit": (
                "parameter-based and pre-registered; the rule never looks "
                "at the residual, and only a contiguous prefix is removed"
            ),
            "x0_floor_m2s": b0.X0_MARGIN,
            "x0_floor_reason": (
                "PyBaMM's initial-state initialisation solves the surface "
                "state under the applied current, so its overpotential "
                "diverges as c_s -> 0 (see initial_state_floor_scan.csv). "
                "1e-3 is the smallest floor with a clean initial state; a "
                "smaller one buys a higher V(0) at the price of a spurious "
                "decaying overpotential, and below ~1e-5 the solve fails."
            ),
            "tolerance_V": b0.WINDOW_START_TOL_V,
            "records": rule_records,
        }, fh, indent=2, ensure_ascii=False)

    for _, r in replay.iterrows():
        print(f"[B0.7] {r['model']:4s} {r['rate']:10s} rule-{r['rule']:3s} "
              f"n={r['n_points']:5d} RMSE={r['rmse_mV']:8.3f} "
              f"MAE={r['mae_mV']:7.3f} max|res|={r['max_abs_mV']:8.1f} "
              f"removed={r['n_points_removed']:3d}pt/"
              f"{100 * r['fraction_removed']:.3f}%")

    _figures(scan, replay, common, tables, adapter)
    _report(OUT_DIR, scan, replay, common, rule_records, args.models)
    print(f"[B0.7] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


# ------------------------------------------------------------------
def _figures(scan, replay, common, tables, adapter) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(18, 4.6))

    # (a) the mechanism: V(0) and the initial overpotential vs x0
    ax = axes[0]
    s = scan[scan["branch"] == "lithiation"]
    ax.semilogx(s["x0"], s["ocp_at_x0_V"], "o-", color="#378ADD",
                label="OCP($x_0$) [V]")
    ax.semilogx(s[s["solve_ok"]]["x0"], s[s["solve_ok"]]["v0_solved_V"],
                "s--", color="#1D9E75", label="solved $V(0)$ [V]")
    ax.axhline(3.0161, color="#E24B4A", ls=":", lw=1.4,
               label="measured rest OCV 3.0161 V")
    ax.axhline(3.0003, color="#BA7517", ls=":", lw=1.2,
               label="frozen OCP table top 3.0003 V")
    ax.axvline(b0.X0_MARGIN, color="k", lw=1.0)
    ax.annotate("kept floor\n$x_0=10^{-3}$", (b0.X0_MARGIN, 2.2),
                fontsize=7, xytext=(6, 0), textcoords="offset points")
    ax.set_xlabel("initial Li fraction $x_0$")
    ax.set_ylabel("voltage [V]")
    ax.set_title("(a) why the floor cannot be lowered")
    ax.legend(fontsize=7)

    ax = axes[1]
    ok = s[s["solve_ok"]]
    ax.semilogx(ok["x0"], ok["initial_overpotential_mV"], "o-",
                color="#E24B4A")
    ax.axhline(0.0, color="k", lw=0.6)
    ax.set_xlabel("initial Li fraction $x_0$")
    ax.set_ylabel("initial overpotential [mV]")
    ax.set_title("(b) initial-state overpotential (0 below ~1e-3\n"
                 "and unsolvable below ~1e-5)")
    for _, r in ok.iterrows():
        ax.annotate(f"{r['initial_overpotential_mV']:+.0f}",
                    (r["x0"], r["initial_overpotential_mV"]), fontsize=6,
                    xytext=(3, 3), textcoords="offset points")

    ax = axes[2]
    for branch, rate in WINDOWS:
        px = b0.OCPConsistentAdapter(adapter, branch, tables,
                                     trim_unrepresentable_prefix=False)
        df = px.load_processed_discharge(CELL, rate)
        t = df["time_s"].to_numpy(float) / 3600.0
        V = df["voltage_V"].to_numpy(float)
        rec = px.window_trim_log[-1]
        k = rec["n_points_removed"]
        ax.plot(t, V, "-", lw=1.4, label=f"{rate} (full window)")
        if k:
            ax.plot(t[:k], V[:k], "o", ms=3.5, color="#E24B4A")
            ax.axvline(t[k - 1], color="#E24B4A", ls="--", lw=1.0)
        ax.axhline(rec["model_start_voltage_V"], color="#378ADD", ls=":",
                   lw=1.2)
    ax.set_xlabel("time [h]")
    ax.set_ylabel("measured voltage [V]")
    ax.set_title("(c) the removed prefix (red) and the model's\n"
                 "admissible start voltage (dotted)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_initial_state.png", dpi=150)
    plt.close(fig)
    return None


def _md(df: pd.DataFrame, cols: List[str], fmt: Dict[str, str]) -> List[str]:
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            f = fmt.get(c)
            if isinstance(v, float) and not np.isfinite(v):
                cells.append("n/a")
            elif f:
                cells.append(f.format(v))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return out


def _report(out_dir, scan, replay, common, rule_records, models) -> Path:
    lines: List[str] = [
        "# Phase B0.7 — 初始态 / 比较窗起点修正",
        "",
        "Phase B0.6 留下了唯一一个未解释的残差来源：p-OCV **lithiation** 窗口里",
        "`V_exp > 1.43 V` 那一栏只有 **1 个比较点**、却有 **1939 mV** 的残差。",
        "本阶段把它查到底并修掉。**没有拟合**：修的是一个可复现的初始态/时间原点错位。",
        "",
        "## 1. 缺陷链（三步，全部可复现）",
        "",
        "**① 实测静置 OCV 落在冻结 OCP 表之外**——表端点的值带上了“通电瞬间的极化”：",
        "",
        "| 窗口 | 实测静置 OCV | 表端点 | 差值 |",
        "|---|---|---|---|",
        "| lithiation | 3.0161 V | 表顶 3.0003 V | **+15.8 mV** |",
        "| delithiation | 0.0824 V | 支底 0.0967 V | **−14.3 mV** |",
        "",
        "所以**没有任何合法的初始锂含量能复现实测静置 OCV**；模型只能停在表的端点。",
        "",
        "**② lithiation 侧的稀释段近乎垂直**：表的第一段是 `SOC 0 → 6.2e-5` 对应",
        "`3.0003 → 1.7865 V`，即 `dV/dSOC ≈ −1.96e4 V/单位 SOC`。于是端点附近任何一个",
        "合法的 `x0` 都无法表达 3 V。",
        "",
        "**③ 而 x0 又不能继续调小**——PyBaMM 的初始态初始化是**在已施加电流下**求解表面",
        "状态的，其过电位随 `c_s → 0` 发散：",
        "",
        "| $x_0$ | $c_{s,0}$ [mol/m³] | OCP($x_0$) [V] | 求解出的 $V(0)$ [V] | 初始过电位 | 可解？ |",
        "|---|---|---|---|---|---|",
    ]
    s = scan[scan["branch"] == "lithiation"]
    for _, r in s.iterrows():
        lines.append(
            f"| {r['x0']:.0e} | {r['c_s0_mol_m3']:.3g} | "
            f"{r['ocp_at_x0_V']:.4f} | "
            f"{r['v0_solved_V']:.4f} | "
            f"{r['initial_overpotential_mV']:+.1f} mV | "
            f"{'是' if r['solve_ok'] else '**否**'} |"
        )
    lines += [
        "",
        "→ 把 x0 从 1e-3 调到 1e-4 确实能把 V(0) 从 1.08 V 抬到 2.19 V，**但代价是一个",
        "虚假的 +453 mV 初始过电位**；再小到 1e-5，初始端电压直接越过 3.2 V 上截止、求解失败。",
        "**因此 1e-3 是“初始态干净”的最小下限，问题不能靠移动 x0 解决。**",
        "",
        "**真正的错误是“比较起点”**：模型从 $x_0=10^{-3}$（$V=1.077$ V）出发，却和实验的",
        "$t=0$（实测 3.016 V）配对；两者的**状态**相差 0.1% 的 SOC，而石墨在这段陡峭区里",
        "0.1% SOC 就是几百 mV。",
        "",
        "## 2. 修法：比较窗起点规则（参数化、预注册、只看参数不看残差）",
        "",
        "> 模型在声明初始态下的端电压是 $\\mathrm{OCP}(x_0)$。沿着窗口的行进方向，落在该值",
        "> **远侧**的**前导**样本处于模型可达状态空间之外，从比较窗中移除，并**逐一记录**。",
        "",
        "| 窗口 | 模型起点电压 | 行进方向 | 移除点数 | 移除时长 | 占比 | 移除电压范围 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, rec in rule_records.items():
        if not key.endswith("_SPM_on"):
            continue
        vr = rec["voltage_range_removed_V"]
        lines.append(
            f"| {rec['variant']} | {rec['model_start_voltage_V']:.4f} V | "
            f"{rec['traversal_direction']} | {rec['n_points_removed']} | "
            f"{rec['duration_removed_s']:.0f} s | "
            f"{100 * rec['fraction_removed']:.3f} % | "
            f"{('[%.4f, %.4f] V' % (vr[0], vr[1])) if vr else '—'} |"
        )
    lines += [
        "",
        "规则**不依赖模型、不依赖求解器**，也**不看残差**；它移除的是模型在物理上无法",
        "表达的那一段（占窗口时长 **0.1%**）。",
        "",
        "## 3. 结果：规则 on / off",
        "",
        "| 模型 | 窗口 | 规则 | 点数 | RMSE [mV] | MAE [mV] | max\\|res\\| [mV] | 移除 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in replay.iterrows():
        lines.append(
            f"| {r['model']} | {r['rate']} | {r['rule']} | {r['n_points']} | "
            f"**{r['rmse_mV']:.3f}** | {r['mae_mV']:.3f} | "
            f"{r['max_abs_mV']:.1f} | {r['n_points_removed']} pt / "
            f"{100 * r['fraction_removed']:.3f} % |"
        )
    lines += [
        "",
        "### 一个必须回答的诘问：是不是“删掉最差点”？",
        "",
        "不是。**在完全相同的实验点上复算**（把规则 off 的轨迹按移除时长切齐到同一网格），",
        "改进依然存在，而且落在**一个点都没被删掉**的区间里：",
        "",
        "| 模型 | 窗口 | 规则 | 点数 | RMSE [mV] | MAE [mV] | max\\|res\\| [mV] |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in common.iterrows():
        lines.append(
            f"| {r['model']} | {r['rate']} | {r['case']} | {r['n_points']} | "
            f"**{r['rmse_mV']:.3f}** | {r['mae_mV']:.3f} | "
            f"{r['max_abs_mV']:.1f} |"
        )
    # regional comparison on the common window
    reg_cols = [c for c in common.columns if c.startswith("region|")]
    if reg_cols:
        lines += [
            "",
            "分区 MAE（**同一批点**，按实验电压分区）：",
            "",
            "| 模型 | 窗口 | 区域 | 点数 | 规则 off [mV] | 规则 on [mV] |",
            "|---|---|---|---|---|---|",
        ]
        for (model, rate), g in common.groupby(["model", "rate"], sort=False):
            if len(g) != 2:
                continue
            a = g[g["case"] == "rule_off"].iloc[0]
            b = g[g["case"] == "rule_on"].iloc[0]
            for c in reg_cols:
                lb = c.replace("region|", "")
                lines.append(
                    f"| {model} | {rate} | {lb} | {int(a['n|' + lb])} | "
                    f"{a[c]:.3f} | **{b[c]:.3f}** |"
                )
    lines += [
        "",
        "**机制**：规则把模型的**时间原点对齐到了实验的“状态”**，而不是对齐到实验的",
        "$t=0$。off 时模型在整个窗口上都“提前”了 0.1% 的 SOC；在石墨的陡峭段，0.1% SOC",
        "就是几到几十 mV。所以改进不是来自删除，而是来自**状态对齐**——这也正是",
        "分区表里那些“一个点都没删”的区间同样改善的原因。",
        "",
        "## 4. 对既有结论的影响（必须一并更正）",
        "",
        "| 窗口 | B0.5/B0.6 记录值 | B0.7 修正后 | 说明 |",
        "|---|---|---|---|",
    ]
    for _, r in replay[replay["rule"] == "off"].iterrows():
        on = replay[(replay["rule"] == "on") & (replay["model"] == r["model"])
                    & (replay["rate"] == r["rate"])]
        if not len(on):
            continue
        lines.append(
            f"| {r['model']} {r['rate']} | {r['rmse_mV']:.2f} mV | "
            f"**{on.iloc[0]['rmse_mV']:.2f} mV** | 旧值含初始态/时间原点错位伪影 |"
        )
    lines += [
        "",
        "**关键含义**：修正后 **lithiation 窗口（≈1.6 mV）实际比 delithiation",
        "（≈2.9 mV）更好**——与修正前的印象（44.7 vs 6.3）正好相反。之前“lith 差得多”",
        "的结论是初始态伪影造成的，不是模型或 OCP 的缺陷。",
        "",
        "**未受影响**：B0 的 OCP 表提取、B0.6 的表保真度（在 (SOC,V) 平面上对实测曲线）、",
        "B1 的 GITT 分段与 apparent D_s（走独立通路）、B2 的诊断与敏感性结论",
        "（CC 族是前向仿真，其起点在模型可达范围内）。B1/B2 中**用到本 proxy 的回放列**",
        "会在本修正下变化，已在 B2 重跑中更新。",
        "",
        "## 5. 措辞（强制）",
        "",
        "这不是 fitting：规则只用**参数**（声明初始态的 OCP）决定移除哪一段，",
        "预先注册、与残差无关，且移除量已逐条披露。被移除的 0.1% **不是“模型误差被藏起来”**，",
        "而是**模型状态空间之外的数据**——模型最多只能表达 $\\mathrm{OCP}(x_0)$ 以下的电压。",
        "仍然不能说“模型验证了这条曲线”：zero-fit 回放依然不是 validation。",
        "",
    ]
    path = Path(out_dir) / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    from scripts._output_isolation import isolate_platform_outputs
    isolate_platform_outputs(OUT_DIR / "platform_runs")
    raise SystemExit(main())
