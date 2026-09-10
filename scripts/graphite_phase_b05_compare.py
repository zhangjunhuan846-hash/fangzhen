#!/usr/bin/env python3
# ============================================================
# Phase B0.5 driver: CAPACITY consistency (not more fitting)
#
#   Phase B0's measured OCP table has a CHARGE-BASED SOC axis
#   (SOC = Q / Q_ref, Q_ref = 1.9425 mAh measured).  The model's own
#   stoichiometry only means the same thing if its Li inventory
#
#       Q_model = eps_am * L * A * c_max * F / 3600
#
#   equals Q_ref.  It was 2.2017 mAh -> x lagged the table SOC by
#   1.13x, which is why the delithiation replay stopped at x ~ 0.19
#   (0.24 V) instead of reaching the measured 1.0 V.  Phase B0.5
#   scales eps_am by Q_ref / Q_model and nothing else:
#
#     OCP  / diffusivity / kinetics / voltage window : UNCHANGED
#                                                     (object identity)
#
#   This is a capacity-CONSISTENT correction, not a fit: Q_ref is a
#   measured charge (from the Phase B0 extraction provenance).
#
# Comparison matrix (geometry ALWAYS the measured Phase A.5 geometry):
#   A5_geom_only   Ecker OCP          + measured geometry   (A.5 control)
#   B0_ocp         measured OCP       + measured geometry   (B0 result)
#   B0p5_capmatch  measured OCP       + measured geometry + capacity match
#
# Windows: pOCV-lith (lithiation branch) and pOCV-deli (delithiation
# branch), each paired with the OCP table of its own branch.
#
# Outputs (outputs/analysis/graphite_phaseB05/):
#   capacity_override.json          the deliverable override payload
#   runs/<window>_<variant>/        platform runner outputs per case
#   soc_trajectory_<window>.csv     experiment vs model SOC(x) trajectories
#   residual_summary.json           metrics, per-region MAE, verdicts
#   comparison.md                   human-readable report
#   fig_b05.png                     voltage / residual / SOC / region figure
#
# The SOC tracking pass re-solves each case in-process to expose the
# model's INTERNAL stoichiometry.  It is a diagnostic side-car: the
# headline metrics always come from the unmodified public runner, and
# the two V(t) curves are cross-checked against each other.
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.models.pybamm_factory import (  # noqa: E402
    build_model,
    build_model_options,
    load_parameter_values,
)
from battery_sim.simulation.baseline import (  # noqa: E402
    _filter_and_downsample,
)
from parameters.sintef_graphite_capacity import (  # noqa: E402
    CAPACITY_MATCHED_IDS,
    electrode_capacity_Ah,
    register_capacity_variants,
    write_capacity_summary,
)
from parameters.sintef_graphite_geometry import (  # noqa: E402
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (  # noqa: E402
    OCP_DELI_ID,
    OCP_LITH_ID,
    register_variants,
)

# The x0 policy and the voltage regions must be IDENTICAL to Phase B0,
# otherwise the two phases are not comparable -> import them.
from scripts.graphite_phase_b0_compare import (  # noqa: E402
    REGIONS,
    OCPConsistentAdapter,
)

OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB05"
B0_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB0"
DATASET = "sintef_graphite"
CELL = "4ccc47"

# window -> (rate id, branch, [(variant tag, parameter set id, uses proxy)])
WINDOWS: Dict[str, tuple] = {
    "lith": ("pOCV-lith", "lithiation", [
        ("A5_geom_only", GEOMETRY_PARAMETER_SET_ID, False),
        ("B0_ocp", OCP_LITH_ID, True),
        ("B0p5_capmatch", CAPACITY_MATCHED_IDS["lithiation"], True),
    ]),
    "deli": ("pOCV-deli", "delithiation", [
        ("A5_geom_only", GEOMETRY_PARAMETER_SET_ID, False),
        ("B0_ocp", OCP_DELI_ID, True),
        ("B0p5_capmatch", CAPACITY_MATCHED_IDS["delithiation"], True),
    ]),
}

COLORS = {
    "A5_geom_only": "#8A8A87",
    "B0_ocp": "#378ADD",
    "B0p5_capmatch": "#1D9E75",
}
LABELS = {
    "A5_geom_only": "A.5 geometry only (Ecker OCP)",
    "B0_ocp": "B0 measured OCP",
    "B0p5_capmatch": "B0.5 measured OCP + capacity matched",
}


# ------------------------------------------------------------------
# metrics (recomputed from the platform's time-aligned csv)
# ------------------------------------------------------------------
def _metrics(csv: Path) -> dict:
    df = pd.read_csv(csv)
    res = df["residual_V"].to_numpy(float)
    v_exp_span = float(
        (df["voltage_exp_V"].max() - df["voltage_exp_V"].min()) * 1000.0
    )
    v_sim_span = float(
        (df["voltage_sim_V"].max() - df["voltage_sim_V"].min()) * 1000.0
    )
    q = np.percentile(res * 1000.0, [5, 25, 50, 75, 95])
    return {
        "n_points": int(len(df)),
        "rmse_mV": float(np.sqrt(np.mean(res ** 2)) * 1000.0),
        "mae_mV": float(np.mean(np.abs(res)) * 1000.0),
        "bias_mV": float(np.mean(res) * 1000.0),
        "max_abs_mV": float(np.max(np.abs(res)) * 1000.0),
        "residual_std_mV": float(np.std(res) * 1000.0),
        "residual_quantiles_mV": {
            "p05": float(q[0]), "p25": float(q[1]), "p50": float(q[2]),
            "p75": float(q[3]), "p95": float(q[4]),
        },
        "v_exp_start_V": float(df["voltage_exp_V"].iloc[0]),
        "v_exp_end_V": float(df["voltage_exp_V"].iloc[-1]),
        "v_sim_start_V": float(df["voltage_sim_V"].iloc[0]),
        "v_sim_end_V": float(df["voltage_sim_V"].iloc[-1]),
        "v_exp_span_mV": v_exp_span,
        "v_sim_span_mV": v_sim_span,
        "v_sim_span_ratio": float(v_sim_span / v_exp_span)
        if v_exp_span else float("nan"),
    }


def _region_mae(csv: Path) -> dict:
    df = pd.read_csv(csv)
    out = {}
    for label, lo, hi in REGIONS:
        sel = df[(df["voltage_exp_V"] > lo) & (df["voltage_exp_V"] <= hi)]
        out[label] = {
            "n_points": int(len(sel)),
            "mae_mV": float(np.mean(np.abs(sel["residual_V"])) * 1000.0)
            if len(sel) else float("nan"),
        }
    return out


# ------------------------------------------------------------------
# platform run
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
    dest_names = {
        f"{slug}_time_aligned.csv": target,
        f"{slug}_Vt.png": dest / f"{slug}_Vt.png",
        "metrics.csv": dest / f"{slug}_metrics.csv",
        "run_metadata.json": dest / f"{slug}_run_metadata.json",
    }
    for name, out in dest_names.items():
        src = run_dir / name
        if not src.is_file():
            continue
        if src.resolve() != out.resolve():
            shutil.copy2(src, out)
    for p in dest.glob("*_time_aligned.csv"):
        if p.name != target.name:
            p.unlink()
    return target


# ------------------------------------------------------------------
# SOC tracking side-car (model-internal stoichiometry)
# ------------------------------------------------------------------
def _model_options(adapter):
    """Same translation the public runner performs (half-cell options)."""
    extra = adapter.config.extra or {}
    cfg = str(extra.get("cell_configuration") or "full_cell")
    if cfg.strip() in ("", "full_cell"):
        return None
    we = str(extra.get("working_electrode") or "").strip()
    return build_model_options(
        cell_configuration=f"half_cell_{we}",
        working_electrode=we,
        extra_model_options=extra.get("model_options"),
    )


def _solve_track(adapter, df, model_name: str, set_id: str) -> dict:
    """
    Re-solve one case in-process to expose the model's internal
    stoichiometry x (surface and volume average).

    Mirrors the public runner's setup exactly (same downsampling, same
    temperature handling, same fixed-initial-concentration override) so
    its V(t) can be cross-checked against the runner's output.
    """
    import pybamm

    t_exp = df["time_s"].to_numpy(float)
    I_exp = df["current_A"].to_numpy(float)
    V_exp = df["voltage_V"].to_numpy(float)
    t_exp, I_exp, V_exp = _filter_and_downsample(t_exp, I_exp, V_exp)

    params = load_parameter_values(set_id)

    ambient_C = float(
        df["temperature_ambient_C"].dropna().median()
        if "temperature_ambient_C" in df.columns else 25.0
    )
    ambient_K = ambient_C + 273.15
    if "Ambient temperature [K]" in params:
        params["Ambient temperature [K]"] = ambient_K
    if "Initial temperature [K]" in params:
        params["Initial temperature [K]"] = ambient_K

    params["Current function [A]"] = pybamm.Interpolant(
        t_exp, I_exp, pybamm.t
    )

    init = df.attrs.get("initialisation") or {}
    x0 = float("nan")
    if str(init.get("method")) == "fixed_initial_concentration":
        conc = str(init["concentration_parameter"])
        cmax_key = str(init["max_concentration_parameter"])
        x0 = float(init["stoichiometry_from_ocp"])
        params[conc] = x0 * float(params[cmax_key])

    model = build_model(model_name, options=_model_options(adapter))
    solution = pybamm.Simulation(model, parameter_values=params).solve(
        t_eval=t_exp
    )
    t_sim = np.asarray(solution.t, float)
    V_sim = np.asarray(solution["Terminal voltage [V]"].entries, float)

    def _series(name: str):
        return np.squeeze(np.asarray(solution[name].entries, float))

    return {
        "t": t_exp,
        "V_exp": V_exp,
        "V_sim": np.interp(t_exp, t_sim, V_sim),
        "x_surface": np.interp(
            t_exp, t_sim, _series("X-averaged positive particle surface stoichiometry")
        ),
        "x_average": np.interp(
            t_exp, t_sim, _series("Average positive particle stoichiometry")
        ),
        "x0": x0,
        "t_sim_end_s": float(t_sim[-1]),
        "q_model_Ah": electrode_capacity_Ah(params),
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

    # ---------------- 1. derived parameter sets ----------------
    register_geometry(args.cell)                 # A.5 geometry-only control
    register_variants(args.cell)                 # B0 OCP variants
    cap_ids = register_capacity_variants(args.cell)
    cap_json = write_capacity_summary(OUT_DIR, args.cell)
    print(f"[B0.5] capacity-matched sets: {cap_ids}")

    capacities = {}
    import pybamm  # noqa: E402

    for set_id in (GEOMETRY_PARAMETER_SET_ID, OCP_LITH_ID, OCP_DELI_ID,
                   CAPACITY_MATCHED_IDS["lithiation"],
                   CAPACITY_MATCHED_IDS["delithiation"]):
        pv = pybamm.ParameterValues(set_id)
        capacities[set_id] = {
            "Q_model_mAh": electrode_capacity_Ah(pv) * 1e3,
            "eps_am": float(
                pv["Positive electrode active material volume fraction"]
            ),
            "nominal_declared_mAh": float(pv["Nominal cell capacity [A.h]"]) * 1e3,
        }
    q_target = capacities[CAPACITY_MATCHED_IDS["delithiation"]]["Q_model_mAh"]
    print(f"[B0.5] Q_model: A.5/B0 {capacities[GEOMETRY_PARAMETER_SET_ID]['Q_model_mAh']:.4f} mAh "
          f"-> matched {q_target:.4f} mAh (Q_ref)")

    tables = {
        "lithiation": pd.read_csv(B0_DIR / "graphite_ocp_lithiation.csv"),
        "delithiation": pd.read_csv(B0_DIR / "graphite_ocp_delithiation.csv"),
    }

    summary = {
        "dataset": DATASET,
        "cell": args.cell,
        "model": args.model,
        "phase": "B0.5 capacity consistency (zero-fit, nothing fitted)",
        "capacity": {
            "q_target_mAh": q_target,
            "q_target_source": (
                "Phase B0 extraction provenance (measured lithiation-branch "
                "charge Q_ref)"
            ),
            "sets": capacities,
        },
        "geometry": "Phase A.5 measured geometry, FIXED for every case",
        "comparison_design": (
            "A5_geom_only -> B0_ocp changes ONLY the OCP; "
            "B0_ocp -> B0p5_capmatch changes ONLY the model capacity"
        ),
        "windows": {},
    }

    soc_frames = {}

    for win, (rate, branch, variants) in WINDOWS.items():
        win_block = {}
        track_rows = []
        for tag, set_id, use_proxy in variants:
            proxy = (OCPConsistentAdapter(adapter, branch, tables)
                     if use_proxy else adapter)
            csv = _run_case(proxy, args.model, rate, set_id,
                            OUT_DIR / "runs" / f"{win}_{tag}")
            x0_mapping = (list(proxy.mapping_log) if use_proxy
                          else "adapter default (inverse-OCP on the "
                               "reference table)")
            m = _metrics(csv)
            reg = _region_mae(csv)

            case_df = proxy.load_processed_discharge(args.cell, rate)
            tr = _solve_track(adapter, case_df, args.model, set_id)

            # cross-check: the side-car must reproduce the runner's V(t).
            # The runner truncates at min(t_exp, t_sim) because the
            # simulation can terminate early, so compare on ITS grid.
            plat = pd.read_csv(csv)
            v_cross = float(np.max(np.abs(
                np.interp(plat["time_s"].to_numpy(float), tr["t"], tr["V_sim"])
                - plat["voltage_sim_V"].to_numpy(float)
            )))

            # experiment SOC from the measured charge, model SOC from x
            t_a = case_df["time_s"].to_numpy(float)
            I_a = case_df["current_A"].to_numpy(float)
            q_cum = np.concatenate(
                ([0.0], np.cumsum(
                    0.5 * (I_a[1:] + I_a[:-1]) * np.diff(t_a)
                ))
            ) / 3600.0
            soc0 = 0.0 if branch == "lithiation" else 1.0
            soc_exp_all = soc0 + q_cum / (q_target * 1e-3)
            soc_exp = np.interp(tr["t"], t_a - t_a[0], soc_exp_all)

            # the model can terminate before the measured window ends
            # (voltage event).  Every end-of-window number is reported at
            # the COMMON end so model and experiment refer to one time,
            # and held/extrapolated values are never plotted.
            keep = tr["t"] <= tr["t_sim_end_s"] + 1e-9
            x_avg = tr["x_average"][keep]
            x_srf = tr["x_surface"][keep]
            soc_k = soc_exp[keep]

            win_block[tag] = {
                "parameter_set": set_id,
                "q_model_mAh": tr["q_model_Ah"] * 1e3,
                "metrics": m,
                "region_mae_mV": reg,
                "track": {
                    "x0": tr["x0"],
                    "x_start": float(x_avg[0]),
                    "x_end_average": float(x_avg[-1]),
                    "x_end_surface": float(x_srf[-1]),
                    "x_span_average": float(x_avg[-1] - x_avg[0]),
                    "soc_end_experiment": float(soc_k[-1]),
                    "soc_end_experiment_full_window": float(soc_exp[-1]),
                    "soc_end_error_average": float(x_avg[-1] - soc_k[-1]),
                    "soc_end_error_surface": float(x_srf[-1] - soc_k[-1]),
                    "v_cross_check_max_abs_diff_V": v_cross,
                    "simulation_end_s": tr["t_sim_end_s"],
                    "window_end_s": float(tr["t"][-1]),
                    "coverage_of_window": float(
                        tr["t_sim_end_s"] / tr["t"][-1]
                    ),
                },
                "x0_mapping": x0_mapping,
            }

            track_rows.append(pd.DataFrame({
                "variant": tag,
                "time_s": tr["t"][keep],
                "soc_experiment": soc_k,
                "soc_model_average": x_avg,
                "soc_model_surface": x_srf,
                "voltage_sim_V": tr["V_sim"][keep],
                "voltage_exp_V": tr["V_exp"][keep],
            }))
        summary["windows"][win] = win_block
        soc_frames[win] = pd.concat(track_rows, ignore_index=True)
        soc_frames[win].to_csv(
            OUT_DIR / f"soc_trajectory_{win}.csv", index=False
        )

        # ---- verdict ----
        b0 = win_block["B0_ocp"]
        b5 = win_block["B0p5_capmatch"]
        verdict = {
            "control": "B0_ocp (measured OCP, capacity NOT matched)",
            "intervention": "B0p5_capmatch (eps_am -> Q_ref)",
            "q_model_before_mAh": b0["q_model_mAh"],
            "q_model_after_mAh": b5["q_model_mAh"],
            "rmse_before_mV": b0["metrics"]["rmse_mV"],
            "rmse_after_mV": b5["metrics"]["rmse_mV"],
            "rmse_ratio": b5["metrics"]["rmse_mV"]
            / b0["metrics"]["rmse_mV"],
            "mae_before_mV": b0["metrics"]["mae_mV"],
            "mae_after_mV": b5["metrics"]["mae_mV"],
            "bias_before_mV": b0["metrics"]["bias_mV"],
            "bias_after_mV": b5["metrics"]["bias_mV"],
            "v_sim_end_before_V": b0["metrics"]["v_sim_end_V"],
            "v_sim_end_after_V": b5["metrics"]["v_sim_end_V"],
            "v_exp_end_V": b0["metrics"]["v_exp_end_V"],
            "x_end_before": b0["track"]["x_end_average"],
            "x_end_after": b5["track"]["x_end_average"],
            "soc_end_experiment": b5["track"]["soc_end_experiment"],
            "region_mae_delta_mV": {
                label: b5["region_mae_mV"][label]["mae_mV"]
                - b0["region_mae_mV"][label]["mae_mV"]
                for label, _lo, _hi in REGIONS
            },
            "region_mae_before_mV": {
                label: b0["region_mae_mV"][label]["mae_mV"]
                for label, _lo, _hi in REGIONS
            },
            "region_mae_after_mV": {
                label: b5["region_mae_mV"][label]["mae_mV"]
                for label, _lo, _hi in REGIONS
            },
        }
        hi_label = "0.60<V_exp<=1.43"
        verdict["region_0p60_1p43_before_mV"] = (
            b0["region_mae_mV"][hi_label]["mae_mV"]
        )
        verdict["region_0p60_1p43_after_mV"] = (
            b5["region_mae_mV"][hi_label]["mae_mV"]
        )
        verdict["region_0p60_1p43_improved"] = bool(
            verdict["region_0p60_1p43_after_mV"]
            < verdict["region_0p60_1p43_before_mV"]
        )
        summary["windows"][win]["verdict"] = verdict

    with (OUT_DIR / "residual_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ---------------- figure ----------------
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(WINDOWS)
    fig, axes = plt.subplots(n, 4, figsize=(19, 3.6 * n))
    if n == 1:
        axes = axes.reshape(1, 4)
    for i, (win, (rate, branch, variants)) in enumerate(WINDOWS.items()):
        blk = summary["windows"][win]
        slug = rate.replace("-", "")
        ref = pd.read_csv(OUT_DIR / "runs" / f"{win}_A5_geom_only" /
                          f"{slug}_time_aligned.csv")

        ax = axes[i, 0]
        ax.plot(ref["time_s"] / 3600.0, ref["voltage_exp_V"], "k-", lw=1.7,
                label="experiment")
        for tag, _sid, _p in variants:
            d = pd.read_csv(OUT_DIR / "runs" / f"{win}_{tag}" /
                            f"{slug}_time_aligned.csv")
            ax.plot(d["time_s"] / 3600.0, d["voltage_sim_V"],
                    color=COLORS[tag], lw=1.2,
                    label=f"{LABELS[tag]} — {blk[tag]['metrics']['rmse_mV']:.1f} mV")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{win} ({branch}) — capacity consistency")
        ax.legend(fontsize=7)

        ax = axes[i, 1]
        for tag, _sid, _p in variants:
            d = pd.read_csv(OUT_DIR / "runs" / f"{win}_{tag}" /
                            f"{slug}_time_aligned.csv")
            ax.plot(d["time_s"] / 3600.0, d["residual_V"] * 1000.0,
                    color=COLORS[tag], lw=1.0, label=LABELS[tag])
        ax.axhline(0.0, color="k", lw=0.6)
        ax.set_title("residual [mV]")
        ax.legend(fontsize=7)

        ax = axes[i, 2]
        for tag, _sid, _p in variants:
            s = soc_frames[win][soc_frames[win]["variant"] == tag]
            ax.plot(s["time_s"] / 3600.0, s["soc_model_average"],
                    color=COLORS[tag], lw=1.1,
                    label=f"{tag} model x (avg)")
        s0 = soc_frames[win][soc_frames[win]["variant"] == variants[0][0]]
        ax.plot(s0["time_s"] / 3600.0, s0["soc_experiment"], "k--", lw=1.4,
                label="experiment SOC = Q/Q_ref")
        ax.set_ylabel("SOC / stoichiometry")
        ax.set_title("SOC trajectory (model x vs measured charge)")
        ax.legend(fontsize=7)

        ax = axes[i, 3]
        labels = [lb for lb, _l, _h in REGIONS]
        xs = np.arange(len(labels))
        w = 0.38
        ax.bar(xs - w / 2,
               [blk["B0_ocp"]["region_mae_mV"][lb]["mae_mV"] for lb in labels],
               w, color=COLORS["B0_ocp"], label="B0 measured OCP")
        ax.bar(xs + w / 2,
               [blk["B0p5_capmatch"]["region_mae_mV"][lb]["mae_mV"]
                for lb in labels],
               w, color=COLORS["B0p5_capmatch"], label="B0.5 + capacity matched")
        ax.set_yscale("log")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=7)
        ax.set_ylabel("MAE [mV]")
        ax.set_title("residual by experimental-voltage region")
        ax.legend(fontsize=7)

        for j in range(4):
            axes[i, j].set_xlabel("time [h]" if j < 3 else "")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_b05.png", dpi=150)
    plt.close(fig)

    # ---------------- comparison.md ----------------
    lines = [
        "# Phase B0.5 — capacity consistency (SINTEF graphite R2032 ‖ Li)",
        "",
        f"- dataset `{DATASET}` / cell `{args.cell}` / model {args.model}",
        "- geometry: Phase A.5 measured geometry, **fixed in every case**",
        "- OCP / diffusivity / kinetics / voltage window: **unchanged**",
        "- intervention: `eps_am` scaled so that `Q_model == Q_ref` "
        "(a MEASURED charge), nothing fitted to any voltage",
        "",
        "## Why capacity enters the OCP comparison",
        "",
        "The Phase B0 OCP table's abscissa is a charge-based SOC "
        f"(SOC = Q / Q_ref, Q_ref = {q_target:.4f} mAh). It can only be read",
        "as `OCP(x)` if the model's stoichiometry x means the same thing, "
        "i.e. if",
        "",
        "```",
        "Q_model = eps_am * L * A * c_max * F / 3600  ==  Q_ref",
        "```",
        "",
        "(validated against a measured volume-averaged dx/dt from a "
        "constant-current solve: 0.00 % difference). With the Phase A.5 "
        f"geometry Q_model was "
        f"{capacities[GEOMETRY_PARAMETER_SET_ID]['Q_model_mAh']:.4f} mAh, so "
        f"x lagged the table SOC by "
        f"{capacities[GEOMETRY_PARAMETER_SET_ID]['Q_model_mAh'] / q_target:.4f}×.",
        "",
        "| parameter set | eps_am | Q_model [mAh] | declared nominal [mAh] |",
        "|---|---|---|---|",
    ]
    for set_id, c in capacities.items():
        lines.append(
            f"| `{set_id}` | {c['eps_am']:.6f} | {c['Q_model_mAh']:.4f} | "
            f"{c['nominal_declared_mAh']:.4f} |"
        )
    lines += [
        "",
        f"`Nominal cell capacity [A.h]` is only a bookkeeping follow-on: a "
        "test asserts the particle equation depends on `eps_am` alone.",
        "",
        "## Results (zero-fit; nothing fitted to any voltage)",
        "",
        "| window | variant | Q_model [mAh] | RMSE [mV] | MAE [mV] | bias [mV] | "
        "V_sim end [V] | coverage |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for tag, _sid, _p in WINDOWS[win][2]:
            e = blk[tag]
            m = e["metrics"]
            lines.append(
                f"| {win} | {tag} | {e['q_model_mAh']:.3f} | "
                f"**{m['rmse_mV']:.2f}** | {m['mae_mV']:.2f} | "
                f"{m['bias_mV']:.2f} | {m['v_sim_end_V']:.4f} | "
                f"{e['track']['coverage_of_window']:.3f} |"
            )
    lines += [
        "",
        "## Residual by experimental-voltage region (MAE, mV)",
        "",
        "The last region label is inherited from Phase B0, where the",
        "*published* table had no data above 1.43 V; with the measured OCP",
        "the table covers that range, so the label is historical only.",
        "",
        "| window | region | B0 measured OCP | B0.5 + capacity matched | change |",
        "|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        for label, _lo, _hi in REGIONS:
            lines.append(
                f"| {win} | {label} | {v['region_mae_before_mV'][label]:.2f} | "
                f"{v['region_mae_after_mV'][label]:.2f} | "
                f"{v['region_mae_delta_mV'][label]:+.2f} |"
            )
    lines += [
        "",
        "## SOC trajectory (the point of this phase)",
        "",
        "| window | variant | x start (avg) | x end (avg) | x end (surface) | "
        "exp SOC end | end error (avg) |",
        "|---|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for tag, _sid, _p in WINDOWS[win][2]:
            t = blk[tag]["track"]
            lines.append(
                f"| {win} | {tag} | {t['x_start']:.4f} | "
                f"{t['x_end_average']:.4f} | {t['x_end_surface']:.4f} | "
                f"{t['soc_end_experiment']:.4f} | "
                f"{t['soc_end_error_average']:+.4f} |"
            )
    lines += [
        "",
        "## Verdicts",
        "",
    ]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        lines += [
            f"**{win}** — {v['control']} → {v['intervention']}",
            f"- Q_model {v['q_model_before_mAh']:.4f} → "
            f"{v['q_model_after_mAh']:.4f} mAh",
            f"- RMSE {v['rmse_before_mV']:.2f} → {v['rmse_after_mV']:.2f} mV "
            f"(×{v['rmse_ratio']:.2f}); MAE {v['mae_before_mV']:.2f} → "
            f"{v['mae_after_mV']:.2f} mV",
            f"- V_sim end {v['v_sim_end_before_V']:.4f} → "
            f"{v['v_sim_end_after_V']:.4f} V (experiment "
            f"{v['v_exp_end_V']:.4f} V)",
            f"- model x end {v['x_end_before']:.4f} → {v['x_end_after']:.4f} "
            f"(experiment SOC end {v['soc_end_experiment']:.4f})",
            f"- 0.60–1.43 V region MAE {v['region_0p60_1p43_before_mV']:.2f} "
            f"→ {v['region_0p60_1p43_after_mV']:.2f} mV "
            f"({'improved' if v['region_0p60_1p43_improved'] else 'NOT improved'})",
        ]
        if not v["region_0p60_1p43_improved"]:
            lines.append(
                "  - this slice is the decimated dilute stage (see the "
                "caveat below): only one table sample lives above 1.43 V, "
                "so its MAE is dominated by interpolation and is unstable "
                "between variants. The window's overall MAE still fell "
                f"{v['mae_before_mV']:.2f} -> {v['mae_after_mV']:.2f} mV "
                f"(x{v['mae_after_mV'] / v['mae_before_mV']:.2f})."
            )
        lines.append("")
    lines += [
        "## Wording (mandatory)",
        "",
        "Capacity-CONSISTENT, not fitted: `Q_ref` is a measured charge, "
        "`eps_am` is the only physics parameter changed, and OCP / "
        "diffusivity / kinetics / voltage window are unchanged by object "
        "identity. This is still a zero-fit reference replay and **not** "
        "validation of the model for this graphite. Any residual that "
        "survives is a hypothesis for Phase B1 (GITT), not a conclusion.",
        "",
        "## Caveat found in this phase: the dilute stage is DECIMATED",
        "",
        "The lithiation window's `0.60 < V_exp <= 1.43` slice is the "
        "near-vertical dilute stage of a fresh cell. Diagnostic "
        "`scripts/probe_b05_dilute_resolution.py`: the raw p-OCV file holds "
        "31 samples in the first 300 s of the branch (V 3.000 -> 0.885 V at "
        "10 s spacing), but `adapter.load_raw` decimates the 189 340-row "
        "file with a GLOBAL stride of 10 (DEFAULT_MAX_POINTS = 20 000), so "
        "only 4 of them survive (t = 0, 90, 190, 280 s). The extracted OCP "
        "table therefore jumps 3.0003 -> 1.2349 V between its first two "
        "samples, and the residual above 1.43 V is an interpolation "
        "artefact of that gap - not a physical finding. Fixing it means "
        "re-extracting the OCP with the branch start kept at full "
        "resolution (a Phase B0 extraction refinement), which is "
        "deliberately NOT done here so that the B0 control stays valid.",
        "",
        "The lithiation window's matched run also covers "
        f"{summary['windows']['lith']['B0p5_capmatch']['track']['coverage_of_window']:.3f} "
        "of the measured window: with the capacity corrected the model "
        "reaches the lower voltage cut-off just before the measured end "
        "(the surface stoichiometry leads the volume average).",
        "",
    ]
    (OUT_DIR / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        print(f"[B0.5] {win}: Q {v['q_model_before_mAh']:.3f} -> "
              f"{v['q_model_after_mAh']:.3f} mAh | RMSE "
              f"{v['rmse_before_mV']:.2f} -> {v['rmse_after_mV']:.2f} mV "
              f"(x{v['rmse_ratio']:.2f}) | 0.6-1.43V region "
              f"{v['region_0p60_1p43_before_mV']:.1f} -> "
              f"{v['region_0p60_1p43_after_mV']:.1f} mV")
        for tag, _sid, _p in WINDOWS[win][2]:
            t = blk[tag]["track"]
            print(f"        {tag:15s} x_end(avg) {t['x_end_average']:.4f} "
                  f"| exp SOC end {t['soc_end_experiment']:.4f} "
                  f"| V cross-check {t['v_cross_check_max_abs_diff_V']:.2e} V")
    print(f"[B0.5] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
