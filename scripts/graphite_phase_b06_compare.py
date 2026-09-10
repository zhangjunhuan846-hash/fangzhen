#!/usr/bin/env python3
# ============================================================
# Phase B0.6 driver: freeze a HIGH-FIDELITY OCP
#
#   Problem (measured in Phase B0.5):
#     the v1 extraction was fed the adapter's DECIMATED trace, so the
#     lithiation table carried exactly ONE sample above 1.43 V
#     (raw: 5 samples) and jumped 3.0003 -> 1.2349 V between its first
#     two rows.
#
#   Fix (this phase):
#     read the raw file at FULL resolution (no global stride, verified
#     against the adapter's own file + SHA256), run the SAME v1
#     extraction core (SOC definition untouched) and then select the
#     samples with a BRANCH-AWARE rule: fidelity-bounded decimation
#     (vertical RDP in the (SOC, V) plane), a steepness floor and a
#     plateau gap cap.
#
#   Nothing else changes: no PyBaMM model edit, no geometry change, no
#   capacity change, no SOC-definition change.  v1 outputs are never
#   touched -- v2 goes to its own graphite_ocp_v2/ directory.
#
#   Then the capacity-matched replay (Phase B0.5) is re-run with both
#   tables so the table change is the ONLY difference:
#       B0.5_v1  measured OCP v1 + measured geometry + capacity matched
#       B0.5_v2  measured OCP v2 + measured geometry + capacity matched
#
# Outputs (outputs/analysis/graphite_phaseB06/):
#   graphite_ocp_v2/{graphite_ocp_lithiation.csv, ..._delithiation.csv,
#                    ocp_extraction_provenance.json, ocp_extraction_summary.json}
#   ocp_v1_vs_v2.json / .md / fig_ocp_v1_vs_v2.png
#   replay_summary.json / comparison_b05_v1_vs_v2.md / fig_replay_v1_vs_v2.png
#   runs/<window>_<version>/...
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

from extraction.ocp_extractor_v2 import (  # noqa: E402
    SOC_BANDS,
    compare_tables,
    extract_ocp_v2,
    table_stats,
    write_comparison,
    write_ocp_v2,
)
from parameters.sintef_graphite_capacity import (  # noqa: E402
    CAPACITY_MATCHED_IDS,
    electrode_capacity_Ah,
    register_capacity_variants,
)
from parameters.sintef_graphite_geometry import (  # noqa: E402
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (  # noqa: E402
    load_ocp_tables,
    register_variants,
)
from scripts.graphite_phase_b0_compare import (  # noqa: E402
    REGIONS,
    OCPConsistentAdapter,
)
from scripts.graphite_phase_b05_compare import (  # noqa: E402
    _metrics,
    _region_mae,
    _solve_track,
)

B0_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB0"
OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06"
V2_DIR = OUT_DIR / "graphite_ocp_v2"

DATASET = "sintef_graphite"
CELL = "4ccc47"
RATE_FOR_EXTRACTION = "pOCV-deli"      # any rate of the p-OCV programme

WINDOWS = {
    "lith": ("pOCV-lith", "lithiation"),
    "deli": ("pOCV-deli", "delithiation"),
}
VERSIONS = {
    "v1": {"suffix": "", "dir": B0_DIR},
    "v2": {"suffix": "_v2", "dir": V2_DIR},
}
COLORS = {"v1": "#E24B4A", "v2": "#1D9E75"}


# ------------------------------------------------------------------
def _run_case(adapter, model, rate, parameter_set, dest: Path) -> Path:
    from battery_sim.simulation.baseline import run_baseline_cell

    result = run_baseline_cell(
        adapter, model_name=model, cell=CELL, rate=rate,
        parameter_set=parameter_set, plot=True, quiet=False,
    )
    run_dir = Path(result["output_dir"])
    slug = rate.replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{slug}_time_aligned.csv"
    mapping = {
        target.name: target,
        f"{slug}_Vt.png": dest / f"{slug}_Vt.png",
        "metrics.csv": dest / f"{slug}_metrics.csv",
        "run_metadata.json": dest / f"{slug}_run_metadata.json",
    }
    for name, out in mapping.items():
        src = run_dir / name
        if src.is_file() and src.resolve() != out.resolve():
            shutil.copy2(src, out)
    for p in dest.glob("*_time_aligned.csv"):
        if p.name != target.name:
            p.unlink()
    return target


def _table_error_along_trajectory(
    x_model: np.ndarray,
    table: pd.DataFrame,
    reference: pd.DataFrame,
) -> dict:
    """
    |V_table(x) - V_measured(x)| along the model's OWN stoichiometry
    trajectory.  This is how much the TABLE contributes to the replay,
    separated from initial state / kinetics / polarisation.
    """
    def _asc(frame):
        s = frame.sort_values("SOC", kind="stable")
        soc = s["SOC"].to_numpy(float)
        v = s["Voltage"].to_numpy(float)
        keep = np.concatenate(([True], np.diff(soc) > 0))
        return soc[keep], v[keep]

    r_soc, r_v = _asc(reference)
    t_soc, t_v = _asc(table)
    lo, hi = max(r_soc[0], t_soc[0]), min(r_soc[-1], t_soc[-1])
    x = np.asarray(x_model, float)
    inside = (x >= lo) & (x <= hi)
    if not inside.any():
        return {"n": 0}
    xi = x[inside]
    d = np.abs(np.interp(xi, t_soc, t_v) - np.interp(xi, r_soc, r_v)) * 1e3
    return {
        "n": int(len(xi)),
        "n_outside_common_range": int((~inside).sum()),
        "mean_mV": float(d.mean()),
        "p95_mV": float(np.percentile(d, 95)),
        "max_mV": float(d.max()),
        "x_at_max": float(xi[int(np.argmax(d))]),
    }


# ------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--cell", default=CELL)
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)

    # ---------------- 1. v2 extraction (full resolution) ----------
    result = extract_ocp_v2(adapter, args.cell, RATE_FOR_EXTRACTION, cycle=1)
    paths = write_ocp_v2(result, OUT_DIR, extra_provenance={
        "definition_unchanged_from": (
            "outputs/analysis/graphite_phaseB0 (v1)"
        ),
    })
    print(f"[B0.6] v2 tables -> {V2_DIR.relative_to(ROOT)}")
    full = result["full_resolution"]
    print(f"[B0.6] full-resolution points: "
          f"{result['provenance']['n_points_full_resolution']}")
    for br in ("lithiation", "delithiation"):
        d = result["provenance"]["resampling"][br]
        print(f"        {br:14s} {d['n_in']:6d} -> {d['n_out']:5d} pts | "
              f"measured max err "
              f"{d['achieved_vertical_error_mV']['max']:.4f} mV")

    # ---------------- 2. v1 vs v2 table comparison ----------------
    v1_tables = load_ocp_tables(B0_DIR)
    v2_tables = load_ocp_tables(V2_DIR)
    v1_prov = json.loads(
        (B0_DIR / "ocp_extraction_provenance.json").read_text(encoding="utf-8")
    )
    report = compare_tables(
        v1_tables["lithiation"], v1_tables["delithiation"],
        v2_tables["lithiation"], v2_tables["delithiation"],
        result["provenance"],
        reference_lith=full["lithiation"],
        reference_deli=full["delithiation"],
    )
    report["q_ref_v1_Ah"] = v1_prov.get("soc_reference_charge_Ah")
    report["q_ref_v2_Ah"] = result["provenance"]["soc_reference_charge_Ah"]
    report["q_ref_relative_difference"] = abs(
        report["q_ref_v2_Ah"] - report["q_ref_v1_Ah"]
    ) / report["q_ref_v1_Ah"]
    write_comparison(report, OUT_DIR / "ocp_v1_vs_v2.json")
    print(f"[B0.6] Q_ref v1 vs v2 relative difference: "
          f"{report['q_ref_relative_difference']:.3e}")

    # ---------------- 3. register both table sets -----------------
    register_geometry(args.cell)
    ids_v1 = register_variants(args.cell, B0_DIR)
    ids_v2 = register_variants(args.cell, V2_DIR, set_id_suffix="_v2")
    cap_v1 = register_capacity_variants(args.cell, B0_DIR)
    cap_v2 = register_capacity_variants(args.cell, V2_DIR,
                                        set_id_suffix="_v2")
    print(f"[B0.6] registered v1 {cap_v1} | v2 {cap_v2}")

    import pybamm

    q_eps = {}
    for tag, cfg in VERSIONS.items():
        pv = pybamm.ParameterValues(cap_v1["delithiation"] if tag == "v1"
                                    else cap_v2["delithiation"])
        q_eps[tag] = {
            "Q_model_mAh": electrode_capacity_Ah(pv) * 1e3,
            "eps_am": float(
                pv["Positive electrode active material volume fraction"]
            ),
        }

    # ---------------- 4. replay matrix ----------------------------
    summary = {
        "dataset": DATASET,
        "cell": args.cell,
        "model": args.model,
        "phase": "B0.6 high-fidelity OCP (only the OCP table changes)",
        "table_change": {
            "v1_input": "adapter.decimated trace (global stride 10)",
            "v2_input": "full-resolution trace (no stride)",
            "v1_sampling": "every sample of the decimated trace",
            "v2_sampling": (
                "vertical-RDP fidelity bound + steepness floor + "
                "plateau gap cap"
            ),
            "soc_definition_unchanged": True,
            "q_ref_relative_difference": report["q_ref_relative_difference"],
            "capacity_matched": q_eps,
        },
        "headline_table": report["headline"],
        "windows": {},
    }

    tables_for = {"v1": v1_tables, "v2": v2_tables}
    set_for = {"v1": cap_v1, "v2": cap_v2}

    for win, (rate, branch) in WINDOWS.items():
        block = {}
        for tag in VERSIONS:
            proxy = OCPConsistentAdapter(adapter, branch, tables_for[tag])
            set_id = set_for[tag][branch]
            csv = _run_case(proxy, args.model, rate, set_id,
                            OUT_DIR / "runs" / f"{win}_{tag}")
            x0_map = list(proxy.mapping_log)
            m = _metrics(csv)
            reg = _region_mae(csv)

            # table fidelity along the model's own trajectory
            df = proxy.load_processed_discharge(args.cell, rate)
            tr = _solve_track(adapter, df, args.model, set_id)
            table_err = _table_error_along_trajectory(
                tr["x_surface"], tables_for[tag][branch], full[branch]
            )

            block[tag] = {
                "parameter_set": set_id,
                "q_model_mAh": tr["q_model_Ah"] * 1e3,
                "x0_mapping": x0_map,
                "x_start_surface": float(tr["x_surface"][0]),
                "x_end_surface": float(tr["x_surface"][-1]),
                "metrics": m,
                "region_mae_mV": reg,
                "table_error_along_model_trajectory_mV": table_err,
            }
            print(f"[B0.6] {win} {tag}: RMSE {m['rmse_mV']:.2f} mV | "
                  f"MAE {m['mae_mV']:.2f} | table error along x "
                  f"{table_err.get('max_mV', float('nan')):.2f} mV max")

        a, b = block["v1"], block["v2"]
        block["verdict"] = {
            "control": "B0.5_v1 (measured OCP v1 + capacity matched)",
            "intervention": "B0.5_v2 (measured OCP v2 + capacity matched)",
            "rmse_before_mV": a["metrics"]["rmse_mV"],
            "rmse_after_mV": b["metrics"]["rmse_mV"],
            "rmse_delta_mV": b["metrics"]["rmse_mV"] - a["metrics"]["rmse_mV"],
            "mae_before_mV": a["metrics"]["mae_mV"],
            "mae_after_mV": b["metrics"]["mae_mV"],
            "mae_delta_mV": b["metrics"]["mae_mV"] - a["metrics"]["mae_mV"],
            "region_mae_before_mV": {
                lb: a["region_mae_mV"][lb]["mae_mV"] for lb, _l, _h in REGIONS
            },
            "region_mae_after_mV": {
                lb: b["region_mae_mV"][lb]["mae_mV"] for lb, _l, _h in REGIONS
            },
            "region_n_points": {
                lb: a["region_mae_mV"][lb]["n_points"] for lb, _l, _h in REGIONS
            },
            "table_error_before_mV": a[
                "table_error_along_model_trajectory_mV"
            ],
            "table_error_after_mV": b[
                "table_error_along_model_trajectory_mV"
            ],
        }
        summary["windows"][win] = block

    with (OUT_DIR / "replay_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ---------------- 5. figures ----------------------------------
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # (a) table comparison
    fig, axes = plt.subplots(2, 4, figsize=(19, 7.4))
    for i, branch in enumerate(("lithiation", "delithiation")):
        ref = full[branch].sort_values("SOC")
        v1 = v1_tables[branch].sort_values("SOC")
        v2 = v2_tables[branch].sort_values("SOC")

        ax = axes[i, 0]
        ax.plot(ref["SOC"], ref["Voltage"], "-", color="#B4B2A9", lw=2.4,
                label=f"full resolution (n={len(ref)})")
        ax.plot(v1["SOC"], v1["Voltage"], "o", ms=4.5, mfc="none",
                color=COLORS["v1"], label=f"v1 (n={len(v1)})")
        ax.plot(v2["SOC"], v2["Voltage"], "o", ms=2.2,
                color=COLORS["v2"], label=f"v2 (n={len(v2)})")
        ax.set_xlim(-0.002, 0.012 if branch == "lithiation" else 0.25)
        ax.set_yscale("log")
        ax.set_xlabel("SOC")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{branch}: dilute-stage zoom")
        ax.legend(fontsize=7)

        ax = axes[i, 1]
        ax.plot(ref["SOC"], ref["Voltage"], "-", color="#B4B2A9", lw=2.4,
                label="full resolution")
        ax.plot(v1["SOC"], v1["Voltage"], "o", ms=3.0, mfc="none",
                color=COLORS["v1"], label="v1")
        ax.plot(v2["SOC"], v2["Voltage"], "o", ms=2.0,
                color=COLORS["v2"], label="v2")
        ax.set_xlim(float(ref["SOC"].min()), 1.0)
        ax.set_ylim(0.0, 1.05 if branch == "delithiation" else 3.1)
        ax.set_xlabel("SOC")
        ax.set_title(f"{branch}: full table")
        ax.legend(fontsize=7)

        ax = axes[i, 2]
        for frame, tag in ((ref, "full"), (v1, "v1"), (v2, "v2")):
            s = frame.sort_values("SOC")
            soc = s["SOC"].to_numpy(float)
            v = s["Voltage"].to_numpy(float)
            d = np.abs(np.diff(v)) / np.diff(soc)
            c = {"full": "#B4B2A9", "v1": COLORS["v1"],
                 "v2": COLORS["v2"]}[tag]
            ax.plot(soc[1:], d, "-" if tag == "full" else "o",
                    ms=2.6 if tag != "full" else 0, color=c, lw=1.4,
                    label=tag)
        ax.set_yscale("log")
        ax.set_xlim(0.0, 0.1 if branch == "lithiation" else 1.0)
        ax.set_xlabel("SOC")
        ax.set_ylabel("|dV/dSOC| [V per unit SOC]")
        ax.set_title("local slope")
        ax.legend(fontsize=7)

        ax = axes[i, 3]
        labels = [b[0] for b in SOC_BANDS]
        xs = np.arange(len(labels))
        st1 = table_stats(v1)
        st2 = table_stats(v2)
        ax.bar(xs - 0.2, [st1["bands"][lb]["n_points"] for lb in labels],
               0.4, color=COLORS["v1"], label="v1")
        ax.bar(xs + 0.2, [st2["bands"][lb]["n_points"] for lb in labels],
               0.4, color=COLORS["v2"], label="v2")
        ax.set_yscale("log")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=7)
        ax.set_ylabel("points in band")
        ax.set_title("point density by SOC band")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_ocp_v1_vs_v2.png", dpi=150)
    plt.close(fig)

    # (b) replay comparison
    n = len(WINDOWS)
    fig, axes = plt.subplots(n, 3, figsize=(15.5, 3.5 * n))
    if n == 1:
        axes = axes.reshape(1, 3)
    for i, (win, (rate, branch)) in enumerate(WINDOWS.items()):
        slug = rate.replace("-", "")
        blk = summary["windows"][win]
        d1 = pd.read_csv(OUT_DIR / "runs" / f"{win}_v1" /
                         f"{slug}_time_aligned.csv")
        d2 = pd.read_csv(OUT_DIR / "runs" / f"{win}_v2" /
                         f"{slug}_time_aligned.csv")
        ax = axes[i, 0]
        ax.plot(d1["time_s"] / 3600.0, d1["voltage_exp_V"], "k-", lw=1.7,
                label="experiment")
        ax.plot(d1["time_s"] / 3600.0, d1["voltage_sim_V"],
                color=COLORS["v1"], lw=1.2,
                label=f"B0.5_v1 — {blk['v1']['metrics']['rmse_mV']:.2f} mV")
        ax.plot(d2["time_s"] / 3600.0, d2["voltage_sim_V"],
                color=COLORS["v2"], lw=1.2,
                label=f"B0.5_v2 — {blk['v2']['metrics']['rmse_mV']:.2f} mV")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{win} — replay with OCP v1 vs v2")
        ax.legend(fontsize=7)

        ax = axes[i, 1]
        ax.plot(d1["time_s"] / 3600.0, d1["residual_V"] * 1e3,
                color=COLORS["v1"], lw=1.0, label="v1")
        ax.plot(d2["time_s"] / 3600.0, d2["residual_V"] * 1e3,
                color=COLORS["v2"], lw=1.0, label="v2")
        ax.axhline(0.0, color="k", lw=0.6)
        ax.set_title("residual [mV]")
        ax.legend(fontsize=7)

        ax = axes[i, 2]
        labels = [lb for lb, _l, _h in REGIONS]
        xs = np.arange(len(labels))
        v = blk["verdict"]
        ax.bar(xs - 0.2, [v["region_mae_before_mV"][lb] for lb in labels],
               0.4, color=COLORS["v1"], label="v1")
        ax.bar(xs + 0.2, [v["region_mae_after_mV"][lb] for lb in labels],
               0.4, color=COLORS["v2"], label="v2")
        ax.set_yscale("log")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=7)
        ax.set_ylabel("MAE [mV]")
        ax.set_title("residual by experimental-voltage region")
        ax.legend(fontsize=7)
        for j in range(3):
            axes[i, j].set_xlabel("time [h]" if j < 2 else "")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_replay_v1_vs_v2.png", dpi=150)
    plt.close(fig)

    # ---------------- 6. reports ----------------------------------
    hl = report["headline"]
    table_lines = [
        "# Phase B0.6 — high-fidelity OCP extraction (v1 vs v2)",
        "",
        f"- dataset `{DATASET}` / cell `{args.cell}`",
        "- v1 input: adapter's DECIMATED trace (global stride 10 -> 100 s)",
        "- v2 input: FULL-RESOLUTION trace (10 s, no stride), verified "
        "against the adapter's own file name + SHA256",
        "- SOC definition / Q_ref anchor / branch classification: "
        "**unchanged** (same extraction core)",
        f"- Q_ref: v1 {report['q_ref_v1_Ah'] * 1e3:.6f} mAh vs v2 "
        f"{report['q_ref_v2_Ah'] * 1e3:.6f} mAh "
        f"(relative difference {report['q_ref_relative_difference']:.2e})",
        "",
        "## The defect this fixes",
        "",
        f"- points above 1.43 V in the lithiation table: **v1 "
        f"{hl['lithiation_n_points_above_1p43V_v1']}** -> **v2 "
        f"{hl['lithiation_n_points_above_1p43V_v2']}**",
        "  (the measurement itself only carries 5 samples there, so v2 is "
        "now AT the data's own resolution)",
        f"- v2 keeps all branch endpoints: sampling is fidelity-bounded, "
        f"not stride-bounded",
        "",
        "## Point density and fidelity",
        "",
        "| branch | version | n points | SOC 0-0.01 | 0.01-0.10 | "
        "0.10-0.50 | 0.50-1.00 | max err vs measured [mV] |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for branch in ("lithiation", "delithiation"):
        blk = report["branches"][branch]
        for tag in ("v1", "v2"):
            st = blk[tag]
            fid = blk.get("fidelity_vs_measured_mV", {})
            band = st["bands"]
            err = (fid.get(tag, {}).get("full_overlap", {})
                   .get("max_abs_mV", float("nan")) if fid else float("nan"))
            table_lines.append(
                f"| {branch} | {tag} | {st['n_points']} | "
                f"{band['0.000-0.01']['n_points']} | "
                f"{band['0.010-0.10']['n_points']} | "
                f"{band['0.100-0.50']['n_points']} | "
                f"{band['0.500-1.00']['n_points']} | {err:.3f} |"
            )
    table_lines += [
        "",
        "## Voltage deviation between the two tables [mV]",
        "",
        "| branch | SOC range | v1 vs v2 max | v1 vs v2 mean |",
        "|---|---|---|---|",
    ]
    for branch in ("lithiation", "delithiation"):
        dev = report["branches"][branch]["deviation_v1_minus_v2_mV"]
        for key, label in (("full_overlap", "full overlap"),
                           ("soc_0_to_0p1_dense", "SOC 0 - 0.1 (dense)")):
            d = dev[key]
            table_lines.append(
                f"| {branch} | {label} | {d['max_abs_mV']:.3f} | "
                f"{d['mean_abs_mV']:.3f} |"
            )
    replay_lines = [
        "# Phase B0.6 — replay: B0.5_v1 vs B0.5_v2 (high-fidelity OCP)",
        "",
        "## Replay: B0.5_v1 vs B0.5_v2 (capacity matched, geometry fixed)",
        "",
        "| window | version | RMSE [mV] | MAE [mV] | bias [mV] | "
        "table error along the model's x: mean / max [mV] |",
        "|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for tag in ("v1", "v2"):
            e = blk[tag]
            m = e["metrics"]
            te = e["table_error_along_model_trajectory_mV"]
            replay_lines.append(
                f"| {win} | {tag} | **{m['rmse_mV']:.2f}** | "
                f"{m['mae_mV']:.2f} | {m['bias_mV']:.2f} | "
                f"{te.get('mean_mV', float('nan')):.3f} / "
                f"{te.get('max_mV', float('nan')):.3f} |"
            )
    replay_lines += [
        "",
        "## Residual by experimental-voltage region (MAE, mV)",
        "",
        "| window | region | n points | v1 | v2 | change |",
        "|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        for label, _lo, _hi in REGIONS:
            replay_lines.append(
                f"| {win} | {label} | {v['region_n_points'][label]} | "
                f"{v['region_mae_before_mV'][label]:.2f} | "
                f"{v['region_mae_after_mV'][label]:.2f} | "
                f"{v['region_mae_after_mV'][label] - v['region_mae_before_mV'][label]:+.2f} |"
            )
    replay_lines += ["", "## Verdicts", ""]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        replay_lines += [
            f"**{win}** — {v['control']} → {v['intervention']}",
            f"- RMSE {v['rmse_before_mV']:.2f} → {v['rmse_after_mV']:.2f} mV "
            f"({v['rmse_delta_mV']:+.2f}); MAE {v['mae_before_mV']:.2f} → "
            f"{v['mae_after_mV']:.2f} mV ({v['mae_delta_mV']:+.2f})",
            f"- table error along the model's own trajectory: max "
            f"{v['table_error_before_mV'].get('max_mV', float('nan')):.2f} → "
            f"{v['table_error_after_mV'].get('max_mV', float('nan')):.2f} mV; "
            f"mean "
            f"{v['table_error_before_mV'].get('mean_mV', float('nan')):.3f} → "
            f"{v['table_error_after_mV'].get('mean_mV', float('nan')):.3f} mV",
            "",
        ]
    replay_lines += [
        "## Wording (mandatory)",
        "",
        "The v2 table is an **experiment-derived pseudo-OCP** for this "
        "electrode at the declared room temperature, re-sampled from the "
        "full-resolution measurement. It is not a material constant, not "
        "a fitted curve and **not** validation. The replay is still "
        "zero-fit: diffusivity, kinetics and the C/50-polarisation "
        "character of the curve are unchanged.",
        "",
        "## Not done here",
        "",
        "- GITT / D_s (Phase B1)",
        "- any PyBaMM model, geometry or capacity change",
        "",
    ]
    (OUT_DIR / "ocp_v1_vs_v2.md").write_text(
        "\n".join(table_lines), encoding="utf-8"
    )
    (OUT_DIR / "comparison_b05_v1_vs_v2.md").write_text(
        "\n".join(table_lines[:-1] + ["", "---", ""] + replay_lines),
        encoding="utf-8",
    )

    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        print(f"[B0.6] {win}: RMSE {v['rmse_before_mV']:.2f} -> "
              f"{v['rmse_after_mV']:.2f} mV | MAE {v['mae_before_mV']:.2f} -> "
              f"{v['mae_after_mV']:.2f} mV")
    print(f"[B0.6] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
