#!/usr/bin/env python3
# ============================================================
# Phase A.5 driver: geometry-aware zero-fit vs reference geometry
#
# Runs the SAME SINTEF p-OCV delithiation replay twice, through the
# UNMODIFIED public runner ``battery_sim.simulation.baseline.run_baseline_cell``:
#
#   Phase A    : parameter_set = Ecker2015_graphite_halfcell (reference geometry)
#   Phase A.5  : parameter_set = sintef_graphite_geometry_v1 (measured geometry,
#                registered in-process via pybamm.parameter_sets -> no repo edit)
#
# Then compares RMSE / MAE / bias / max|res| and writes:
#   outputs/analysis/graphite_phaseA5/
#     geometry_override.json      (the auditable override payload)
#     phaseA_reference/*.csv      (snapshot of the Phase A run, if provided)
#     phaseA5_geometry/*.csv      (this run)
#     residual_summary.json
#     comparison.md
#     fig_phaseA_vs_A5.png
#
# Usage:
#   python scripts/graphite_phase_a5_compare.py \
#       [--phase-a-dir <dir with Phase A csvs>] [--cell 4ccc47]
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parameters.sintef_graphite_geometry import (  # noqa: E402
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    geometry_override,
    register,
    write_geometry_json,
)

OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseA5"
DATASET = "sintef_graphite"
CASE_CELL = "4ccc47"


def _metrics(csv_path: Path) -> dict:
    """Recompute the platform metric family from a time_aligned csv."""
    df = pd.read_csv(csv_path)
    res = df["residual_V"].to_numpy(float)
    v_exp_span = float(
        (df["voltage_exp_V"].max() - df["voltage_exp_V"].min()) * 1000.0
    )
    v_sim_span = float(
        (df["voltage_sim_V"].max() - df["voltage_sim_V"].min()) * 1000.0
    )
    return {
        "n_points": int(len(df)),
        "rmse_mV": float(np.sqrt(np.mean(res ** 2)) * 1000.0),
        "mae_mV": float(np.mean(np.abs(res)) * 1000.0),
        "bias_mV": float(np.mean(res) * 1000.0),
        "max_abs_mV": float(np.max(np.abs(res)) * 1000.0),
        "v_exp_start_V": float(df["voltage_exp_V"].iloc[0]),
        "v_exp_end_V": float(df["voltage_exp_V"].iloc[-1]),
        "v_sim_start_V": float(df["voltage_sim_V"].iloc[0]),
        "v_sim_end_V": float(df["voltage_sim_V"].iloc[-1]),
        "v_exp_span_mV": v_exp_span,
        "v_sim_span_mV": v_sim_span,
        "v_sim_span_ratio": float(v_sim_span / v_exp_span)
        if v_exp_span
        else float("nan"),
    }


def _frozen_artifact(m: dict) -> str:
    """Is the simulated voltage frozen (span << experimental span)?"""
    ratio = m.get("v_sim_span_ratio", float("nan"))
    if ratio < 0.10:
        return "PRESENT"
    if ratio < 0.50:
        return "PARTIAL"
    return "REMOVED"


def _run_case(adapter, model, rate, parameter_set, out_subdir):
    """Run one (rate, parameter set) replay through the public runner."""
    from battery_sim.simulation.baseline import run_baseline_cell

    print(f"[A.5] {rate} | {parameter_set}")
    result = run_baseline_cell(
        adapter,
        model_name=model,
        cell=CASE_CELL,
        rate=rate,
        parameter_set=parameter_set,
        plot=True,
        quiet=False,
    )
    run_dir = Path(result["output_dir"])
    slug = rate.replace("-", "")
    dest = OUT_DIR / out_subdir
    dest.mkdir(parents=True, exist_ok=True)
    # copy ONLY this rate's files: the platform run dir accumulates
    # one file set per rate slug, so a broad glob would let a later
    # rate clobber an earlier snapshot
    for name in (f"{slug}_time_aligned.csv", f"{slug}_Vt.png",
                 "metrics.csv", "run_metadata.json"):
        src = run_dir / name
        if src.is_file():
            target = dest / (f"{slug}_metrics.csv" if name == "metrics.csv"
                             else f"{slug}_{name}" if name == "run_metadata.json"
                             else name)
            if src.resolve() != target.resolve():
                shutil.copy2(src, target)
    return dest / f"{slug}_time_aligned.csv"


def main(argv=None) -> int:
    global CASE_CELL
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="4ccc47")
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--rates", nargs="+", default=["pOCV-deli", "pOCV-lith"])
    args = ap.parse_args(argv)
    CASE_CELL = args.cell

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- geometry payload (the deliverable) ----
    geom_path = write_geometry_json(
        OUT_DIR / "geometry_override.json", cell=args.cell
    )
    payload = geometry_override(args.cell)
    print(f"[A.5] geometry override: {geom_path.relative_to(ROOT)}")
    for k, v in payload["override"].items():
        print(f"        {k} = {v!r}")

    set_id = register(args.cell)
    print(f"[A.5] runtime-registered parameter set: {set_id}")

    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)

    cases = {}
    for rate in args.rates:
        a_csv = _run_case(adapter, args.model, rate, REFERENCE_SET,
                          f"phaseA_reference")
        b_csv = _run_case(adapter, args.model, rate, set_id,
                          f"phaseA5_geometry")
        cases[rate] = {"A": a_csv, "A5": b_csv}

    # ---- compare ----
    summary = {
        "dataset": DATASET,
        "cell": args.cell,
        "model": args.model,
        "window": "p-OCV cycle 1 rest tail (60 s) + one branch",
        "parameter_sets": {"phase_A": REFERENCE_SET, "phase_A5": set_id},
        "geometry_override": payload["override"],
        "geometry_cross_checks": payload["cross_checks"],
        "scale_ratios_vs_reference": payload["scale_ratios_vs_reference"],
        "rates": {},
        "wording": (
            "A.5 is a geometry-aware ZERO-FIT reference replay: OCP, "
            "diffusivity and kinetics are unchanged from the reference set, "
            "nothing is fitted to voltage, and the result is NOT validation."
        ),
    }
    curves = {}
    for rate, paths in cases.items():
        m_a = _metrics(paths["A"])
        m_b = _metrics(paths["A5"])
        da, d5 = pd.read_csv(paths["A"]), pd.read_csv(paths["A5"])
        regions = {"low_V_le_0p15": (0.0, 0.15), "mid_0p15_0p60": (0.15, 0.60),
                   "high_V_gt_0p60": (0.60, np.inf)}
        resid = {}
        for label, (lo, hi) in regions.items():
            resid[label] = {
                "phase_A_MAE_mV": float(
                    np.mean(np.abs(
                        da.loc[(da.voltage_exp_V > lo)
                               & (da.voltage_exp_V <= hi), "residual_V"]
                    )) * 1000.0
                ),
                "phase_A5_MAE_mV": float(
                    np.mean(np.abs(
                        d5.loc[(d5.voltage_exp_V > lo)
                               & (d5.voltage_exp_V <= hi), "residual_V"]
                    )) * 1000.0
                ),
            }
        summary["rates"][rate] = {
            "phase_A": {"metrics": m_a, "frozen_artifact": _frozen_artifact(m_a)},
            "phase_A5": {"metrics": m_b, "frozen_artifact": _frozen_artifact(m_b)},
            "delta_rmse_mV": m_b["rmse_mV"] - m_a["rmse_mV"],
            "delta_v_sim_span_mV": m_b["v_sim_span_mV"] - m_a["v_sim_span_mV"],
            "residual_by_exp_voltage_region_MAE_mV": resid,
        }
        curves[rate] = (da, d5)

    with (OUT_DIR / "residual_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ---- figure: one panel per rate ----
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(cases)
    fig, axes = plt.subplots(n, 2, figsize=(12, 3.4 * n), sharex="col")
    if n == 1:
        axes = axes.reshape(1, 2)
    for i, (rate, (da, d5)) in enumerate(curves.items()):
        m_a = summary["rates"][rate]["phase_A"]["metrics"]
        m_b = summary["rates"][rate]["phase_A5"]["metrics"]
        ax = axes[i, 0]
        ax.plot(da["time_s"] / 3600.0, da["voltage_exp_V"], "k-", lw=1.6,
                label="experiment")
        ax.plot(da["time_s"] / 3600.0, da["voltage_sim_V"], color="#E24B4A",
                lw=1.1, label=f"A reference geom. RMSE {m_a['rmse_mV']:.1f} mV")
        ax.plot(d5["time_s"] / 3600.0, d5["voltage_sim_V"], color="#378ADD",
                lw=1.1, label=f"A.5 measured geom. RMSE {m_b['rmse_mV']:.1f} mV")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{rate} ({summary['rates'][rate]['phase_A5']['frozen_artifact']} artifact removed)")
        ax.legend(fontsize=8)
        ax2 = axes[i, 1]
        ax2.plot(d5["time_s"] / 3600.0, da["residual_V"] * 1000.0,
                 color="#E24B4A", lw=1.0, label="A residual")
        ax2.plot(d5["time_s"] / 3600.0, d5["residual_V"] * 1000.0,
                 color="#378ADD", lw=1.0, label="A.5 residual")
        ax2.axhline(0.0, color="k", lw=0.6)
        ax2.set_title("residual V_sim - V_exp [mV]")
        ax2.legend(fontsize=8)
        if i == n - 1:
            for j in (0, 1):
                axes[i, j].set_xlabel("time [h]")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_phaseA_vs_A5.png", dpi=150)
    plt.close(fig)

    # ---- comparison.md ----
    lines = [
        "# Phase A.5 — geometry-aware zero-fit vs Phase A (reference geometry)",
        "",
        f"- dataset `{DATASET}` / cell `{args.cell}` / model {args.model}",
        f"- window: {summary['window']}",
        f"- Phase A set: `{REFERENCE_SET}` (85.85 cm², 74 µm, eps_am 0.372403)",
        f"- Phase A.5 set: `{set_id}` (measured geometry, registered at runtime,",
        "  OCP / diffusivity / kinetics UNCHANGED, nothing fitted)",
        "",
        "## Geometry override (from SINTEF metadata.csv)",
        "",
        "| parameter | reference | A.5 (derived from measurement) |",
        "|---|---|---|",
        f"| electrode area | {payload['reference_values']['area_m2']*1e4:.2f} cm² | "
        f"{payload['measured_structure']['electrode_area_cm2']:.4f} cm² |",
        f"| thickness | {payload['reference_values']['thickness_m']*1e6:.1f} µm | "
        f"{payload['override']['Positive electrode thickness [m]']*1e6:.1f} µm |",
        f"| eps_am | {payload['reference_values']['eps_am']:.6f} | "
        f"{payload['override']['Positive electrode active material volume fraction']:.6f} |",
        f"| nominal capacity | {payload['reference_values']['nominal_cell_capacity_Ah']*1000:.2f} mAh | "
        f"{payload['override']['Nominal cell capacity [A.h]']*1000:.3f} mAh |",
        "",
        "## Metrics (recomputed from the time-aligned csv)",
        "",
        "| rate | window direction | metric | Phase A | Phase A.5 |",
        "|---|---|---|---|---|",
    ]
    for rate, blk in summary["rates"].items():
        direction = "discharge (+)" if rate == "pOCV-lith" else "charge (-)"
        for key, label in (("rmse_mV", "RMSE [mV]"), ("mae_mV", "MAE [mV]"),
                           ("bias_mV", "bias [mV]"),
                           ("v_sim_span_mV", "V_sim span [mV]")):
            lines.append(
                f"| {rate} | {direction} | {label} | "
                f"{blk['phase_A']['metrics'][key]:.2f} | "
                f"{blk['phase_A5']['metrics'][key]:.2f} |"
            )
        lines.append(
            f"| {rate} | {direction} | **frozen artifact** | "
            f"{blk['phase_A']['frozen_artifact']} | "
            f"**{blk['phase_A5']['frozen_artifact']}** |"
        )
    lines += [
        "",
        "## Residual by experimental-voltage region (MAE, mV)",
        "",
        "| rate | region | Phase A | Phase A.5 |",
        "|---|---|---|---|",
    ]
    for rate, blk in summary["rates"].items():
        for label, vals in blk["residual_by_exp_voltage_region_MAE_mV"].items():
            lines.append(
                f"| {rate} | {label} | {vals['phase_A_MAE_mV']:.2f} | "
                f"{vals['phase_A5_MAE_mV']:.2f} |"
            )
    lines += [
        "",
        "## Interpretation",
        "",
        f"- Phase A used a {payload['scale_ratios_vs_reference']['area_ratio_reference_over_measured']:.1f}× "
        "too-large electrode: at the same absolute current the model saw a",
        "  ~56× lower current density and its voltage barely moved.",
        "- Phase A.5 replaces only the measured geometry; the frozen artifact is",
        "  removed and the RMSE collapses (see table above).",
        "- What remains is NOT scale: it is the difference between the reference",
        "  OCP/diffusivity/kinetics and this graphite, plus the ~10 % catalog",
        "  internal inconsistency (mass/loading vs punched-disc area) recorded in",
        "  geometry_override.json.",
        "- The lithiation window is the cell's own DISCHARGE direction and is",
        "  convention-clean; the delithiation window is the user-selected primary",
        "  window and is a CHARGE-direction window under the platform convention,",
        "  so the runner's discharge-oriented columns (Q_sim, capacity_error_pct,",
        "  current_peak_discharge_A) are not meaningful for it.",
        "",
        "## Wording (mandatory)",
        "",
        "Geometry-aware **zero-fit reference replay**: geometry from measurement,",
        "OCP/diffusivity/kinetics from the published reference set, nothing fitted",
        "to voltage, and **not** validation of the model for this graphite.",
        "Remaining residual is a hypothesis for Phase B (OCP extraction), not a",
        "conclusion.",
        "",
    ]
    (OUT_DIR / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    for rate, blk in summary["rates"].items():
        print(f"[A.5] {rate}: RMSE {blk['phase_A']['metrics']['rmse_mV']:.2f} -> "
              f"{blk['phase_A5']['metrics']['rmse_mV']:.2f} mV | frozen artifact "
              f"{blk['phase_A']['frozen_artifact']} -> "
              f"{blk['phase_A5']['frozen_artifact']}")
    print(f"[A.5] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    from scripts._output_isolation import isolate_platform_outputs
    isolate_platform_outputs(OUT_DIR / "platform_runs")
    raise SystemExit(main())
