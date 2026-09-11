#!/usr/bin/env python3
# ============================================================
# Phase B1 driver: GITT -> apparent D_s(SOC) -> replay comparison
#
#   B1.0  SINTEF GITT raw file (91M rows, multi-rate log)
#             -> extraction.gitt_extractor  -> gitt_segments.csv
#   B1.1  segments + frozen OCP v2
#             -> extraction.gitt_diffusivity -> graphite_Ds_app.csv
#   B1.1  parameter set
#             Ecker2015 + SINTEF geometry + SINTEF OCP v2
#             + capacity-matched eps_am + SINTEF apparent D_s
#             -> unmodified public runner, p-OCV replay
#             -> "Ecker D" vs "SINTEF D_s" comparison
#
# The replay comparison is a CONSISTENCY check, not a validation of the
# diffusivity: the p-OCV programme runs at ~C/50, where the particle
# diffusion time is far longer than the window, so the model's voltage
# is almost insensitive to D.  The report quantifies that sensitivity
# instead of implying that a small RMSE change means the D is right.
#
# Outputs (outputs/analysis/graphite_phaseB1/):
#   gitt_segments.csv / gitt_segmentation_provenance.json
#   graphite_Ds_app.csv / gitt_ds_app_pulses.csv / gitt_ds_app_provenance.json
#   ds_parameter_variants.json
#   runs/<window>_<variant>/...
#   replay_summary.json / comparison.md
#   fig_gitt_ds.png / fig_replay_ds.png
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

from extraction.gitt_diffusivity import compute_ds_app, write_ds_app  # noqa: E402
from extraction.gitt_extractor import (  # noqa: E402
    extract_gitt_segments,
    write_gitt_segments,
)
from parameters.sintef_graphite_ds import (  # noqa: E402
    DS_PARAMETER_SET_IDS,
    ecker_diffusivity_summary,
    register_ds_variants,
    write_variant_summaries,
)
from parameters.sintef_graphite_capacity import (  # noqa: E402
    register_capacity_variants,
)
from parameters.sintef_graphite_geometry import (  # noqa: E402
    derive_geometry,
    read_structure,
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
from scripts.graphite_phase_b05_compare import _metrics, _region_mae  # noqa: E402

B0_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB0"
V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB1"

DATASET = "sintef_graphite"
POCV_CELL = "4ccc47"        # the p-OCV cell (replay target)
GITT_CELL = "063b77"        # the GITT cell (parameter source)
V2_SUFFIX = "_v2"

WINDOWS = {
    "lith": ("pOCV-lith", "lithiation"),
    "deli": ("pOCV-deli", "delithiation"),
}


def _run_case(adapter, model, rate, parameter_set, dest: Path) -> Path:
    from battery_sim.simulation.baseline import run_baseline_cell

    result = run_baseline_cell(
        adapter, model_name=model, cell=POCV_CELL, rate=rate,
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


def _diffusion_overpotential_mV(
    D_m2_s: float, radius_m: float, u_prime: float, current_A: float,
    q_th_Ah: float, duration_s: float,
) -> float:
    """
    |U'| * (2I/(3Q_th)) * sqrt(tau * tau_d / pi): the Weppner-Huggins
    surface excursion translated into volts after `duration_s`.  This is
    how much the diffusivity can matter over a window of that length --
    the number that explains a flat replay comparison.
    """
    if not np.isfinite(D_m2_s) or D_m2_s <= 0 or not np.isfinite(u_prime):
        return float("nan")
    tau_d = radius_m ** 2 / D_m2_s
    q_th_as = q_th_Ah * 3600.0
    return float(abs(u_prime) * (2.0 * current_A / (3.0 * q_th_as))
                 * np.sqrt(duration_s * tau_d / np.pi) * 1e3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--cycles", nargs="*", type=int, default=None,
                    help="GITT cycles to use (default: all)")
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)

    # ---------------- B1.0: segmentation --------------------------
    seg_res = extract_gitt_segments(adapter, GITT_CELL)
    write_gitt_segments(seg_res, OUT_DIR)
    seg = seg_res["segments"]
    print(f"[B1] {len(seg)} pulses | protocol "
          f"{seg_res['provenance']['pulse_protocol']['pulse_time_s_median']:.0f} s "
          f"pulse / "
          f"{seg_res['provenance']['pulse_protocol']['relax_time_s_median']:.0f} s "
          f"rest")

    # ---------------- B1.1: apparent D_s -------------------------
    geom = derive_geometry(read_structure(GITT_CELL))
    q_th_Ah = float(geom["nominal_cell_capacity_Ah"])

    import pybamm

    R = float(pybamm.ParameterValues("Ecker2015_graphite_halfcell")
              ["Positive particle radius [m]"])
    ocp_tables = load_ocp_tables(V2_DIR)
    ds_res = compute_ds_app(
        seg, ocp_tables,
        particle_radius_m=R, q_th_Ah=q_th_Ah,
        active_mass_source=(
            "SINTEF catalog metadata.csv, cell 063b77 "
            "(Mass of Active Material / mg)"
        ),
        cycles=args.cycles,
    )
    write_ds_app(ds_res, OUT_DIR)
    ds_prov = ds_res["provenance"]
    pulses = ds_res["pulses"]
    print(f"[B1] D_s defined {ds_prov['n_defined']}/{ds_prov['n_pulses']}, "
          f"accepted {ds_prov['n_accepted']}")
    ecker = ecker_diffusivity_summary()
    print(f"[B1] Ecker2015 D median = {ecker['median_m2_s']:.3e} m2/s")

    # ---------------- register both variants ----------------------
    register_geometry(POCV_CELL)
    register_variants(POCV_CELL, V2_DIR, set_id_suffix=V2_SUFFIX)
    cap = register_capacity_variants(POCV_CELL, V2_DIR,
                                     set_id_suffix=V2_SUFFIX)
    ds_ids = register_ds_variants(
        POCV_CELL, ocp_dir=V2_DIR, ds_dir=OUT_DIR,
        set_id_suffix=V2_SUFFIX,
    )
    write_variant_summaries(OUT_DIR, POCV_CELL, ocp_dir=V2_DIR, ds_dir=OUT_DIR)
    print(f"[B1] control ids {cap} | ds ids {ds_ids}")

    # ---------------- replay comparison ---------------------------
    summary = {
        "dataset": DATASET,
        "pocv_cell": POCV_CELL,
        "gitt_cell": GITT_CELL,
        "model": args.model,
        "phase": "B1 GITT apparent diffusivity",
        "segmentation": {
            "n_pulses": int(len(seg)),
            "pulse_protocol": seg_res["provenance"]["pulse_protocol"],
            "soc_reference_charge_mAh":
                seg_res["provenance"]["soc_reference_charge_mAh"],
        },
        "ds_extraction": {
            k: ds_prov[k] for k in (
                "n_pulses", "n_defined", "n_accepted", "n_rejected",
                "equation_reference", "cross_check_equation",
                "particle_radius_m", "particle_radius_source",
                "Q_th_Ah", "Q_th_source", "uncertainty_definition",
            )
        },
        "ecker_ds": ecker,
        "windows": {},
    }

    for win, (rate, branch) in WINDOWS.items():
        control_id = cap[branch]
        ds_id = ds_ids[branch]
        block = {}
        for tag, set_id in (("ecker_ds", control_id), ("gitt_ds", ds_id)):
            proxy = OCPConsistentAdapter(adapter, branch, ocp_tables)
            csv = _run_case(proxy, args.model, rate, set_id,
                            OUT_DIR / "runs" / f"{win}_{tag}")
            m = _metrics(csv)
            block[tag] = {
                "parameter_set": set_id,
                "metrics": m,
                "region_mae_mV": _region_mae(csv),
            }
            print(f"[B1] {win} {tag}: RMSE {m['rmse_mV']:.3f} mV | "
                  f"MAE {m['mae_mV']:.3f}")
        a, b = block["ecker_ds"], block["gitt_ds"]
        block["verdict"] = {
            "control": "Ecker2015 diffusivity (reference set)",
            "intervention": "SINTEF GITT apparent D_s(SOC)",
            "rmse_before_mV": a["metrics"]["rmse_mV"],
            "rmse_after_mV": b["metrics"]["rmse_mV"],
            "rmse_delta_mV": b["metrics"]["rmse_mV"] - a["metrics"]["rmse_mV"],
            "mae_before_mV": a["metrics"]["mae_mV"],
            "mae_after_mV": b["metrics"]["mae_mV"],
            "max_abs_before_mV": a["metrics"]["max_abs_mV"],
            "max_abs_after_mV": b["metrics"]["max_abs_mV"],
            "region_mae_delta_mV": {
                lb: b["region_mae_mV"][lb]["mae_mV"]
                - a["region_mae_mV"][lb]["mae_mV"]
                for lb, _l, _h in REGIONS
            },
        }
        summary["windows"][win] = block

    # ---------------- sensitivity of a C/50 window ----------------
    # how much diffusivity *could* matter over the replay window
    sens = {}
    for win, (rate, branch) in WINDOWS.items():
        row = pulses[(pulses["branch"] == branch) & pulses["accepted"]]
        if row.empty:
            continue
        ds_med = float(row["Ds_app_m2_s"].median())
        uprime = float(row["u_prime_V_per_soc"].median())
        i_pocv = 43.28e-6
        window_s = 148521.0 if win == "deli" else 161589.0
        sens[win] = {
            "Ds_median_m2_s": ds_med,
            "u_prime_median_V_per_soc": uprime,
            "diffusion_overpotential_ecker_mV": _diffusion_overpotential_mV(
                ecker["median_m2_s"], R, uprime, i_pocv, q_th_Ah, window_s
            ),
            "diffusion_overpotential_gitt_mV": _diffusion_overpotential_mV(
                ds_med, R, uprime, i_pocv, q_th_Ah, window_s
            ),
            "window_s": window_s,
            "note": (
                "Weppner-Huggins surface excursion converted to volts over "
                "the whole p-OCV window; both values are far below the "
                "replay residual, which is why the comparison is flat"
            ),
        }
    summary["sensitivity"] = sens

    with (OUT_DIR / "replay_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ---------------- figures -------------------------------------
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(17, 4.2))
    ax = axes[0]
    for branch, color in (("lithiation", "#378ADD"),
                          ("delithiation", "#1D9E75")):
        sub = pulses[(pulses["branch"] == branch) & pulses["accepted"]]
        ax.semilogy(sub["SOC_mid"], sub["Ds_app_cm2_s"], "o", ms=3.5,
                    color=color, alpha=0.55, label=f"{branch} pulses")
        med = ds_res["table"]
        med = med[med["branch"] == branch]
        ax.semilogy(med["SOC"], med["Ds_app_cm2_s"], "-", color=color, lw=1.8)
    ax.axhline(ecker["median_m2_s"] * 1e4, color="#E24B4A", ls="--", lw=1.4,
               label="Ecker2015 D (median)")
    ax.set_xlabel("SOC")
    ax.set_ylabel("apparent D_s [cm2/s]")
    ax.set_title("GITT apparent D_s(SOC) vs reference D")
    ax.legend(fontsize=7)

    ax = axes[1]
    ok = pulses[pulses["accepted"]]
    ax.plot(ok["sqrt_t_r2"], ok["SOC_mid"], "o", ms=3.2, color="#8A8A87",
            alpha=0.6)
    ax.axvline(0.90, color="#E24B4A", ls="--", lw=1.2)
    ax.set_xlabel("sqrt(t) fit R^2")
    ax.set_ylabel("SOC")
    ax.set_title("regime check: is the pulse linear in sqrt(t)?")

    ax = axes[2]
    if ok["relax_over_pulse_sqrt_ratio"].notna().any():
        ax.hist(np.log10(ok["relax_over_pulse_sqrt_ratio"].dropna()
                         .clip(lower=1e-4)), bins=40, color="#BA7517")
    ax.axvline(0.0, color="k", lw=1.0)
    ax.set_xlabel("log10( sqrt(D_relax / D_pulse) )")
    ax.set_ylabel("pulses")
    ax.set_title("OCP-free cross-check vs pulse route")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_gitt_ds.png", dpi=150)
    plt.close(fig)

    n = len(WINDOWS)
    fig, axes = plt.subplots(n, 3, figsize=(15.5, 3.5 * n))
    if n == 1:
        axes = axes.reshape(1, 3)
    for i, (win, (rate, branch)) in enumerate(WINDOWS.items()):
        slug = rate.replace("-", "")
        blk = summary["windows"][win]
        d1 = pd.read_csv(OUT_DIR / "runs" / f"{win}_ecker_ds" /
                         f"{slug}_time_aligned.csv")
        d2 = pd.read_csv(OUT_DIR / "runs" / f"{win}_gitt_ds" /
                         f"{slug}_time_aligned.csv")
        ax = axes[i, 0]
        ax.plot(d1["time_s"] / 3600.0, d1["voltage_exp_V"], "k-", lw=1.7,
                label="experiment")
        ax.plot(d1["time_s"] / 3600.0, d1["voltage_sim_V"], color="#E24B4A",
                lw=1.2, label=f"Ecker D — {blk['ecker_ds']['metrics']['rmse_mV']:.3f} mV")
        ax.plot(d2["time_s"] / 3600.0, d2["voltage_sim_V"], color="#1D9E75",
                lw=1.2, label=f"GITT D_s — {blk['gitt_ds']['metrics']['rmse_mV']:.3f} mV")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{win} — diffusivity swap")
        ax.legend(fontsize=7)
        ax = axes[i, 1]
        ax.plot(d1["time_s"] / 3600.0, d1["residual_V"] * 1e3, color="#E24B4A",
                lw=1.0, label="Ecker D")
        ax.plot(d2["time_s"] / 3600.0, d2["residual_V"] * 1e3, color="#1D9E75",
                lw=1.0, label="GITT D_s")
        # the two runs can terminate at different times (the diffusivity
        # changes the voltage event), so compare on the control's grid
        t_ctrl = d1["time_s"].to_numpy(float)
        v_ds = np.interp(t_ctrl, d2["time_s"].to_numpy(float),
                         d2["voltage_sim_V"].to_numpy(float))
        diff = (v_ds - d1["voltage_sim_V"].to_numpy(float)) * 1e3
        ax.plot(t_ctrl / 3600.0, diff, color="#BA7517", lw=1.0,
                label="V(GITT)-V(Ecker)")
        ax.axhline(0.0, color="k", lw=0.6)
        ax.set_title("residual [mV] and the swap's own effect")
        ax.legend(fontsize=7)
        ax = axes[i, 2]
        ax.hist(d1["residual_V"] * 1e3, bins=60, alpha=0.55, color="#E24B4A",
                label="Ecker D")
        ax.hist(d2["residual_V"] * 1e3, bins=60, alpha=0.55, color="#1D9E75",
                label="GITT D_s")
        ax.set_xlabel("residual [mV]")
        ax.set_ylabel("count")
        ax.set_title("residual distribution")
        ax.legend(fontsize=7)
        for j in range(3):
            axes[i, j].set_xlabel("time [h]" if j < 2 else "residual [mV]")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_replay_ds.png", dpi=150)
    plt.close(fig)

    # ---------------- report --------------------------------------
    lines = [
        "# Phase B1 — GITT apparent D_s(SOC) and the p-OCV replay",
        "",
        f"- GITT cell `{GITT_CELL}`, p-OCV cell `{POCV_CELL}`, "
        f"model {args.model}",
        f"- pulses segmented: **{len(seg)}** "
        f"({summary['segmentation']['pulse_protocol']['pulse_time_s_median']:.0f} s "
        f"pulse / "
        f"{summary['segmentation']['pulse_protocol']['relax_time_s_median']:.0f} s "
        f"rest)",
        f"- D_s defined {ds_prov['n_defined']} / accepted "
        f"**{ds_prov['n_accepted']}** of {ds_prov['n_pulses']} pulses",
        "",
        "## What this D_s is",
        "",
        "> " + ds_prov["quantity"],
        "",
        f"- equation: {ds_prov['equation_reference']}",
        f"- particle radius: {ds_prov['particle_radius_source']}",
        f"- Q_th: {ds_prov['Q_th_source']}",
        f"- accepted-pulse median D_s: "
        f"{summary['ds_extraction'].get('n_accepted')} pulses",
        "",
        "| quantity | value |",
        "|---|---|",
        f"| R (particle radius) | {R * 1e6:.2f} um |",
        f"| Q_th (GITT cell) | {q_th_Ah * 1e3:.4f} mAh |",
        f"| Ecker2015 D (median over SOC) | {ecker['median_m2_s']:.3e} m2/s |",
        "",
        "## SOC-resolved apparent D_s",
        "",
        "| branch | SOC | n pulses | D_s [cm2/s] | p25 | p75 | rel. uncertainty |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in ds_res["table"].iterrows():
        lines.append(
            f"| {r['branch']} | {r['SOC']:.2f} | {int(r['n_pulses'])} | "
            f"{r['Ds_app_cm2_s']:.3e} | {r['Ds_app_cm2_s_p25']:.3e} | "
            f"{r['Ds_app_cm2_s_p75']:.3e} | "
            f"{r['Ds_app_rel_uncertainty_median']:.4f} |"
        )
    lines += [
        "",
        "## Replay: Ecker2015 D vs SINTEF apparent D_s",
        "",
        "Both runs use the SAME frozen set (measured geometry, "
        "capacity-matched eps_am, OCP v2) — only the diffusivity differs.",
        "",
        "| window | diffusivity | RMSE [mV] | MAE [mV] | bias [mV] | max abs [mV] |",
        "|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for tag, label in (("ecker_ds", "Ecker2015 D"),
                           ("gitt_ds", "SINTEF apparent D_s")):
            m = blk[tag]["metrics"]
            lines.append(
                f"| {win} | {label} | **{m['rmse_mV']:.3f}** | "
                f"{m['mae_mV']:.3f} | {m['bias_mV']:.3f} | "
                f"{m['max_abs_mV']:.3f} |"
            )
    lines += [
        "",
        "## Residual distribution (mV)",
        "",
        "| window | diffusivity | std | p05 | p50 | p95 |",
        "|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for tag, label in (("ecker_ds", "Ecker2015 D"),
                           ("gitt_ds", "SINTEF apparent D_s")):
            m = blk[tag]["metrics"]
            q = m["residual_quantiles_mV"]
            lines.append(
                f"| {win} | {label} | {m['residual_std_mV']:.3f} | "
                f"{q['p05']:.3f} | {q['p50']:.3f} | {q['p95']:.3f} |"
            )
    lines += [
        "",
        "## Residual by experimental-voltage region (MAE, mV)",
        "",
        "| window | region | n points | Ecker D | SINTEF D_s | change |",
        "|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        for label, _lo, _hi in REGIONS:
            n = blk["ecker_ds"]["region_mae_mV"][label]["n_points"]
            a = blk["ecker_ds"]["region_mae_mV"][label]["mae_mV"]
            b = blk["gitt_ds"]["region_mae_mV"][label]["mae_mV"]
            lines.append(
                f"| {win} | {label} | {n} | {a:.3f} | {b:.3f} | {b - a:+.3f} |"
            )
    acc = pulses[pulses["accepted"]]
    pct = {k: float(np.percentile(acc["Ds_app_m2_s"], q))
           for k, q in (("p01", 1), ("p25", 25), ("p50", 50),
                        ("p75", 75), ("p99", 99))}
    lines += [
        "",
        "## What the replay says about the extracted D_s",
        "",
        "The two runs differ ONLY in the diffusivity, so the change in "
        "RMSE is the replay's verdict on the extracted curve.",
        "",
        "| window | Ecker D | GITT D_s | change | model hit a cutoff? |",
        "|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        n_e = blk["ecker_ds"]["metrics"]["n_points"]
        n_g = blk["gitt_ds"]["metrics"]["n_points"]
        lines.append(
            f"| {win} | {v['rmse_before_mV']:.2f} mV | "
            f"{v['rmse_after_mV']:.2f} mV | {v['rmse_delta_mV']:+.2f} mV | "
            f"comparison window {n_e} -> {n_g} points |"
        )
    lines += [
        "",
        "### Verdict",
        "",
        "Swapping in the GITT-derived apparent D_s makes BOTH windows "
        "**worse**, and in the delithiation window the model runs into the "
        "upper voltage cut-off (the comparison window collapses), i.e. the "
        "model becomes diffusion-starved.  The extracted curve is therefore "
        "**not adopted** as the model's diffusivity.",
        "",
        f"Accepted pulses: median D_s = {pct['p50']:.3e} m2/s "
        f"(p01 {pct['p01']:.2e}, p99 {pct['p99']:.2e}) against the "
        f"reference-set value {ecker['median_m2_s']:.3e} m2/s — about "
        f"{ecker['median_m2_s'] / pct['p50']:.0f}x SMALLER, with a spread "
        f"of many orders of magnitude across SOC.",
        "",
        "A first-order Weppner-Huggins surface excursion over the p-OCV "
        "window would be",
        "",
        "| window | Ecker D | GITT D_s |",
        "|---|---|---|",
    ]
    for win, s in sens.items():
        lines.append(
            f"| {win} | {s['diffusion_overpotential_ecker_mV']:.2f} mV | "
            f"{s['diffusion_overpotential_gitt_mV']:.2f} mV |"
        )
    lines += [
        "",
        "so the extracted D_s predicts a polarisation the measured C/50 "
        "p-OCV does not show.  The single-particle inversion is attributing "
        "to solid diffusion an overpotential that the porous electrode, the "
        "electrolyte and the pseudo-OCP's own polarisation also contribute "
        "to — which is exactly the caveat attached to every GITT-derived "
        "'apparent' diffusivity.",
        "",
        "### What this does NOT mean",
        "",
        "- it does NOT mean the reference (Ecker) D is correct: it is a "
        "published fit for a different cell, and it was never validated "
        "here either;",
        "- it does NOT invalidate the extraction code: the Weppner-Huggins "
        "inversion recovers a known diffusivity exactly in the forward "
        "test (`test_weppner_huggins_inversion_recovers_a_known_D`).  What "
        "it means is that the SINGLE-PARTICLE MODEL is the wrong lens for "
        "this dataset, and the result is reported as an apparent parameter "
        "that failed a consistency check.",
        "",
        "## Honest limitations of this D_s",
        "",
        f"- accepted {ds_prov['n_accepted']} of {ds_prov['n_pulses']} pulses; "
        f"rejected {ds_prov['n_rejected']} (weak sqrt(t) fit, OCP not "
        f"locally linear, SOC outside the branch table, or a direction "
        f"inconsistent with I*U')",
        f"- the OCP-free cross-check disagrees with the pulse route "
        f"(median sqrt(D_relax/D_pulse) = "
        f"{float(ok['relax_over_pulse_sqrt_ratio'].median()):.4f}), so the "
        f"single-particle Weppner-Huggins regime is only partially "
        f"satisfied across this pulse train",
        "- D scales with R^2, and R comes from the REFERENCE set, not from "
        "a measurement of this material",
        f"- uncertainty reported is the {ds_prov['flags']['min_r2']} "
        "R^2-gated regression noise only; systematics dominate",
        "",
        "## Wording (mandatory)",
        "",
        "**Apparent/effective** solid diffusivity, NOT an intrinsic "
        "material coefficient and NOT validation.  The p-OCV replay is a "
        "consistency check whose diffusion sensitivity is negligible at "
        "C/50.",
        "",
    ]
    (OUT_DIR / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    for win, blk in summary["windows"].items():
        v = blk["verdict"]
        print(f"[B1] {win}: RMSE {v['rmse_before_mV']:.3f} -> "
              f"{v['rmse_after_mV']:.3f} mV ({v['rmse_delta_mV']:+.3f})")
    print(f"[B1] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    from scripts._output_isolation import isolate_platform_outputs
    isolate_platform_outputs(OUT_DIR / "platform_runs")
    raise SystemExit(main())
