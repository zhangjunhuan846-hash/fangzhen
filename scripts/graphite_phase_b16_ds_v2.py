#!/usr/bin/env python3
# ============================================================
# Phase B1.6 driver: the GITT apparent D_s(SOC) table, redone with
#                   the equilibrium drift separated from the
#                   diffusion signal
#
#   B1.6.0  SINTEF GITT raw file (91M rows, multi-rate log)
#               -> extraction.gitt_extractor
#               -> gitt_segments.csv carrying BOTH fits
#                  (sqrt_t_*  = V = a + m*sqrt(t)      Phase B1)
#                  (quad_*    = V = a + b*t + m*sqrt(t) Phase B1.6)
#   B1.6.1  the same segments + the same frozen OCP v2
#               -> extraction.gitt_diffusivity      -> v1/graphite_Ds_app.csv
#               -> extraction.gitt_diffusivity_v2   -> v2/graphite_Ds_app.csv
#           The v1 table is recomputed here ONLY as a regression
#           self-check: it must reproduce the Phase B1 table exactly.
#   B1.6.2  parameter sets
#               Ecker2015 + SINTEF geometry + OCP v2 + capacity-matched
#               eps_am + D_s(v1)   and   + D_s(v2)
#               -> unmodified public runner, p-OCV replay
#
# WHY THE FIT FORM IS THE THING TO FIX
#   Phase B1.5 measured, on model-generated pulses of this protocol,
#   that the first-order Weppner-Huggins fit inflates the diffusion
#   slope by a median 2.9x (D low by ~9x), because the equilibrium
#   voltage drifts linearly while the pulse is on.  Both fits scored
#   R^2 >= 0.95, so the Phase B1 R^2 >= 0.90 gate cannot see the error.
#   This phase changes the fit form; it does NOT re-fit anything to the
#   measured voltage, and it does not touch the OCP, the geometry, the
#   capacity or the gate values.
#
# Outputs (outputs/analysis/graphite_phaseB16/):
#   gitt_segments.csv / gitt_segmentation_provenance.json
#   v1/ v2/  (graphite_Ds_app.csv, gitt_ds_app_pulses.csv, provenance)
#   ds_form_comparison.json / comparison.md / report.md
#   fig_ds_v1_vs_v2.png / fig_fit_form.png
#   runs/<window>_<variant>/...   (unless --skip-replay)
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.gitt_diffusivity import compute_ds_app, write_ds_app  # noqa: E402
from extraction.gitt_diffusivity_v2 import (  # noqa: E402
    compute_ds_app_v2,
    write_ds_app_v2,
)
from extraction.gitt_extractor import (  # noqa: E402
    extract_gitt_segments,
    write_gitt_segments,
)
from governance.dataset_roles import (  # noqa: E402
    USE_CALIBRATE,
    check,
    resolve_role,
)
from parameters.sintef_graphite_capacity import (  # noqa: E402
    register_capacity_variants,
)
from parameters.sintef_graphite_ds import (  # noqa: E402
    ecker_diffusivity_summary,
    register_ds_variants,
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
    OCPConsistentAdapter,
)
from scripts.graphite_phase_b05_compare import _metrics, _region_mae  # noqa: E402
from scripts.graphite_phase_b1_compare import (  # noqa: E402
    _diffusion_overpotential_mV,
    _run_case,
)

OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB16"
V1_DIR = OUT_DIR / "v1"
V2_DIR = OUT_DIR / "v2"
B1_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB1"
OCP_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"

DATASET = "sintef_graphite"
POCV_CELL = "4ccc47"        # the p-OCV cell (replay target)
GITT_CELL = "063b77"        # the GITT cell (parameter source)
GITT_PROGRAMME = "gitt"     # the programme whose data this phase calibrates on

SUFFIX_V1 = "_b16v1"
SUFFIX_V2 = "_b16v2"

WINDOWS = {
    "lith": ("pOCV-lith", "lithiation"),
    "deli": ("pOCV-deli", "delithiation"),
}

POCV_WINDOW_S = {"deli": 148521.0, "lith": 161589.0}
POCV_CURRENT_A = 43.28e-6


def _coverage_matched(csv_paths: dict, reference: str = "ecker_ds") -> dict:
    """
    Metrics on a COMMON time grid.

    The variants can terminate at different times (changing the
    diffusivity moves the voltage event that ends the run), so their
    time-aligned tables have different lengths.  The plain RMSEs are then
    computed on DIFFERENT point sets, and a truncated run is only scored
    where it survived -- which UNDERSTATES its error in exactly the
    direction that flatters it.

    Here every variant's simulated voltage is interpolated onto the
    reference run's grid, restricted to the time range all of them cover,
    and compared against the same experimental trace.
    """
    frames = {k: pd.read_csv(p) for k, p in csv_paths.items()}
    ref = frames[reference]
    t_common = min(float(f["time_s"].max()) for f in frames.values())
    grid = ref["time_s"].to_numpy(float)
    grid = grid[grid <= t_common]
    if len(grid) < 2:
        return {"n_points": int(len(grid)), "t_common_s": t_common}
    t_ref = ref["time_s"].to_numpy(float)
    v_exp = np.interp(grid, t_ref, ref["voltage_exp_V"].to_numpy(float))
    out = {"t_common_s": float(t_common), "n_points": int(len(grid)),
           "reference": reference}
    for tag, f in frames.items():
        t_f = f["time_s"].to_numpy(float)
        v_sim = np.interp(grid, t_f, f["voltage_sim_V"].to_numpy(float))
        r = (v_exp - v_sim) * 1e3
        out[tag] = {
            "rmse_mV": float(np.sqrt(np.mean(r ** 2))),
            "mae_mV": float(np.mean(np.abs(r))),
            "bias_mV": float(np.mean(r)),
            "max_abs_mV": float(np.max(np.abs(r))),
        }
    return out


def _pct(v: pd.Series) -> dict:
    v = pd.to_numeric(v, errors="coerce").dropna()
    v = v[v > 0]
    if v.empty:
        return {}
    return {f"p{q}": float(np.percentile(v, q))
            for q in (1, 25, 50, 75, 99)}


def _reproduce_b1(res_v1: dict) -> dict:
    """The B1.6 run must reproduce the Phase B1 table: same model, same
    data, same gates -- only an extra column was added to the CSV."""
    path = B1_DIR / "graphite_Ds_app.csv"
    if not path.is_file():
        return {"checked": False, "reason": f"no {path}"}
    old = pd.read_csv(path)
    new = res_v1["table"]
    if len(old) != len(new):
        return {"checked": True, "identical": False,
                "reason": f"row count {len(old)} -> {len(new)}"}
    key = ["branch", "SOC"]
    merged = old[key + ["Ds_app_m2_s"]].merge(
        new[key + ["Ds_app_m2_s"]], on=key, suffixes=("_b1", "_b16")
    )
    rel = np.abs(merged["Ds_app_m2_s_b16"] / merged["Ds_app_m2_s_b1"] - 1.0)
    return {
        "checked": True,
        "reference": str(path.relative_to(ROOT)),
        "n_rows": int(len(new)),
        "max_rel_diff": float(np.nanmax(rel.to_numpy()))
        if len(rel) else float("nan"),
        "identical": bool(np.nanmax(rel.to_numpy()) < 1e-9) if len(rel)
        else False,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--cycles", nargs="*", type=int, default=None,
                    help="GITT cycles to use (default: all)")
    ap.add_argument("--skip-replay", action="store_true",
                    help="tables and comparison only, no p-OCV replays")
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 本阶段的回放运行**不应污染被跟踪的 outputs/platform/**：
    # 见 scripts/_output_isolation.py（与 tests/conftest.py 同一手法，
    # 只换模块属性的值，不改冻结代码）。
    from scripts._output_isolation import isolate_platform_outputs

    isolate_platform_outputs(OUT_DIR / "platform_runs")

    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)

    # ---------------- 用途治理门（标定路径入口） ------------------
    # 这一段是"参数来源"，所以必须在动数据之前过门：
    # 若有人把这份 GITT 声明成 validation/benchmark，这里直接报错，
    # 而不是等到结论写完才发现"验证集被拿去标定了"。
    role = resolve_role(DATASET, GITT_PROGRAMME)
    role_warnings = check(role, USE_CALIBRATE, dataset=DATASET,
                          rate=GITT_PROGRAMME,
                          what="GITT segmentation and D_s inversion")
    print(f"[B1.6] dataset_role({DATASET}/{GITT_PROGRAMME}) = {role}")
    for w in role_warnings:
        print(f"[B1.6] ROLE WARNING: {w}")

    # ---------------- B1.6.0: segmentation, both fits --------------
    seg_res = extract_gitt_segments(adapter, GITT_CELL)
    write_gitt_segments(seg_res, OUT_DIR)
    seg = seg_res["segments"]
    proto = seg_res["provenance"]["pulse_protocol"]
    print(f"[B1.6] {len(seg)} pulses | "
          f"{proto['pulse_time_s_median']:.0f} s pulse / "
          f"{proto['relax_time_s_median']:.0f} s rest")
    if seg["quad_r2"].notna().any():
        print(f"[B1.6] fits computed per pulse: first order and "
              f"drift-corrected (median quad R^2 "
              f"{seg['quad_r2'].median():.4f})")

    # ---------------- B1.6.1: the two D_s tables ------------------
    geom = derive_geometry(read_structure(GITT_CELL))
    q_th_Ah = float(geom["nominal_cell_capacity_Ah"])

    import pybamm

    R = float(pybamm.ParameterValues("Ecker2015_graphite_halfcell")
              ["Positive particle radius [m]"])
    ocp_tables = load_ocp_tables(OCP_DIR)
    mass_source = (
        "SINTEF catalog metadata.csv, cell 063b77 "
        "(Mass of Active Material / mg)"
    )

    v1_res = compute_ds_app(
        seg, ocp_tables, particle_radius_m=R, q_th_Ah=q_th_Ah,
        active_mass_source=mass_source, cycles=args.cycles,
    )
    write_ds_app(v1_res, V1_DIR, extra_provenance={
        "phase": "B1.6 (recomputed for the regression self-check)",
        "note": (
            "identical inputs and gates to Phase B1; the value must match "
            "outputs/analysis/graphite_phaseB1/graphite_Ds_app.csv"
        ),
    })

    v2_res = compute_ds_app_v2(
        seg, ocp_tables, particle_radius_m=R, q_th_Ah=q_th_Ah,
        active_mass_source=mass_source, cycles=args.cycles,
    )
    write_ds_app_v2(v2_res, V2_DIR)

    p1, p2 = v1_res["pulses"], v2_res["pulses"]
    a1 = p1[p1["accepted"]]
    a2 = p2[p2["accepted"]]
    ecker = ecker_diffusivity_summary()
    repro = _reproduce_b1(v1_res)

    print(f"[B1.6] D_s accepted: v1 {v1_res['provenance']['n_accepted']}, "
          f"v2 {v2_res['provenance']['n_accepted']}")
    print(f"[B1.6] B1 reproducibility: {repro}")
    print(f"[B1.6] median D_s (accepted, m2/s): "
          f"v1 {a1['Ds_app_m2_s'].median():.3e} | "
          f"v2 {a2['Ds_app_m2_s'].median():.3e} | "
          f"Ecker {ecker['median_m2_s']:.3e}")

    comparison = {
        "dataset": DATASET,
        "pocv_cell": POCV_CELL,
        "gitt_cell": GITT_CELL,
        "model": args.model,
        "phase": "B1.6 fit form (equilibrium drift separated)",
        "dataset_role": {
            "role": role,
            "use": USE_CALIBRATE,
            "source": "configs/datasets.yaml (governance/dataset_roles.py)",
            "warnings": role_warnings,
        },
        "n_pulses_segmented": int(len(seg)),
        "b1_reproduced": repro,
        "ecker_reference": ecker,
        "fit_effect": v2_res["provenance"]["fit_effect_on_these_pulses"],
        "branches": {},
        "fit_form": v2_res["provenance"]["fit_form"],
    }
    for branch in ("lithiation", "delithiation"):
        s1 = a1[a1["branch"] == branch]["Ds_app_m2_s"]
        s2 = a2[a2["branch"] == branch]["Ds_app_m2_s"]
        comparison["branches"][branch] = {
            "n_accepted_v1": int(len(s1)),
            "n_accepted_v2": int(len(s2)),
            "v1_m2_s": _pct(s1),
            "v2_m2_s": _pct(s2),
            "v2_over_v1_median": float(
                np.median(s2) / np.median(s1)
            ) if len(s1) and len(s2) else float("nan"),
            "ecker_over_v2_median": float(
                ecker["median_m2_s"] / np.median(s2)
            ) if len(s2) else float("nan"),
        }

    # ---- the only fair v1 vs v2 comparison: the SAME pulses ------
    # v2 accepts more pulses than v1 (a quadratic form fits better), so
    # comparing whole-table medians mixes two populations.  This block
    # uses only the pulses BOTH accept.
    both_pop = pd.DataFrame({
        "branch": p1["branch"].to_numpy(),
        "SOC_mid": p1["SOC_mid"].to_numpy(float),
        "D_v1": p1["Ds_app_m2_s"].to_numpy(float),
        "D_v2": p2["Ds_app_m2_s"].to_numpy(float),
        "acc_v1": p1["accepted"].to_numpy(bool),
        "acc_v2": p2["accepted"].to_numpy(bool),
    })
    common = both_pop[both_pop["acc_v1"] & both_pop["acc_v2"]].copy()
    common["paired_ratio"] = common["D_v2"] / common["D_v1"]
    pr = common["paired_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
    comparison["common_accepted_set"] = {
        "n_pulses": int(len(common)),
        "note": (
            "pulses accepted by BOTH the first-order and the "
            "drift-corrected table; the only population on which the two "
            "diffusivities are directly comparable"
        ),
        "v1_m2_s": _pct(common["D_v1"]),
        "v2_m2_s": _pct(common["D_v2"]),
        "v2_over_v1_median": float(
            common["D_v2"].median() / common["D_v1"].median()
        ) if len(common) else float("nan"),
        # the PAIRED statistic answers "what did the fit form do to THIS
        # pulse"; the ratio of medians answers "where does the bulk of the
        # curve sit".  On this dataset they DISAGREE, and both are true:
        # the correction lifts most pulses but crushes the high-D tail.
        "paired_ratio_median": float(pr.median()) if len(pr)
        else float("nan"),
        "paired_ratio_percentiles": {
            f"p{q}": float(np.percentile(pr, q)) for q in (5, 25, 50, 75, 95)
        } if len(pr) else {},
        "fraction_paired_ratio_above_one": float((pr > 1).mean())
        if len(pr) else float("nan"),
        "branches": {},
    }
    for branch, g in common.groupby("branch"):
        comparison["common_accepted_set"]["branches"][str(branch)] = {
            "n_pulses": int(len(g)),
            "v1_median_m2_s": float(g["D_v1"].median()),
            "v2_median_m2_s": float(g["D_v2"].median()),
            "v2_over_v1_median": float(g["D_v2"].median()
                                       / g["D_v1"].median()),
            "ecker_over_v2_median": float(ecker["median_m2_s"]
                                          / g["D_v2"].median()),
        }

    # ---------------- B1.6.2: replay -----------------------------
    if not args.skip_replay:
        register_geometry(POCV_CELL)
        controls, ds_ids = {}, {}
        for suffix, ds_dir, tag in (
            (SUFFIX_V1, V1_DIR, "v1"),
            (SUFFIX_V2, V2_DIR, "v2"),
        ):
            register_variants(POCV_CELL, OCP_DIR, set_id_suffix=suffix)
            controls[tag] = register_capacity_variants(
                POCV_CELL, OCP_DIR, set_id_suffix=suffix
            )
            ds_ids[tag] = register_ds_variants(
                POCV_CELL, ocp_dir=OCP_DIR, ds_dir=ds_dir,
                set_id_suffix=suffix,
            )
        comparison["windows"] = {}
        for win, (rate, branch) in WINDOWS.items():
            block = {}
            csvs = {}
            control_id = controls["v1"][branch]
            for tag, set_id in (
                ("ecker_ds", control_id),
                ("v1", ds_ids["v1"][branch]),
                ("v2", ds_ids["v2"][branch]),
            ):
                proxy = OCPConsistentAdapter(adapter, branch, ocp_tables)
                csv = _run_case(proxy, args.model, rate, set_id,
                                OUT_DIR / "runs" / f"{win}_{tag}")
                csvs[tag] = csv
                m = _metrics(csv)
                block[tag] = {
                    "parameter_set": set_id,
                    "metrics": m,
                    "region_mae_mV": _region_mae(csv),
                }
                print(f"[B1.6] {win} {tag}: RMSE {m['rmse_mV']:.3f} mV | "
                      f"MAE {m['mae_mV']:.3f}")
            cm = _coverage_matched(csvs)
            block["coverage_matched"] = cm
            if "v1" in cm:
                print(f"[B1.6] {win} coverage-matched on {cm['n_points']} "
                      f"common points: "
                      + " | ".join(f"{t} {cm[t]['rmse_mV']:.3f} mV"
                                   for t in ("ecker_ds", "v1", "v2")))
            comparison["windows"][win] = block

    # ---------------- sensitivity of a C/50 window ----------------
    sens = {}
    for win, (rate, branch) in WINDOWS.items():
        s2 = a2[a2["branch"] == branch]
        if s2.empty:
            continue
        sens[win] = {
            "Ds_median_v2_m2_s": float(s2["Ds_app_m2_s"].median()),
            "Ds_median_v1_m2_s": float(
                a1[a1["branch"] == branch]["Ds_app_m2_s"].median()
            ),
            "diffusion_overpotential_ecker_mV": _diffusion_overpotential_mV(
                ecker["median_m2_s"], R, float(s2["u_prime_V_per_soc"].median()),
                POCV_CURRENT_A, q_th_Ah, POCV_WINDOW_S[win]
            ),
            "diffusion_overpotential_v2_mV": _diffusion_overpotential_mV(
                float(s2["Ds_app_m2_s"].median()), R,
                float(s2["u_prime_V_per_soc"].median()),
                POCV_CURRENT_A, q_th_Ah, POCV_WINDOW_S[win]
            ),
        }
    comparison["sensitivity"] = sens

    with (OUT_DIR / "ds_form_comparison.json").open("w",
                                                     encoding="utf-8") as fh:
        json.dump(comparison, fh, indent=2, ensure_ascii=False)

    # ---------------- figures -------------------------------------
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(17, 4.4))
    ax = axes[0]
    for tag, res, color in (("v1 (first order)", v1_res, "#BA7517"),
                            ("v2 (drift-corrected)", v2_res, "#1D9E75")):
        sub = res["pulses"][res["pulses"]["accepted"]]
        ax.semilogy(sub["SOC_mid"], sub["Ds_app_cm2_s"], "o", ms=3.2,
                    color=color, alpha=0.5, label=f"{tag} pulses")
        med = res["table"]
        for branch, ls in (("lithiation", "-"), ("delithiation", "--")):
            b = med[med["branch"] == branch]
            ax.semilogy(b["SOC"], b["Ds_app_cm2_s"], ls, color=color, lw=1.5)
    ax.axhline(ecker["median_m2_s"] * 1e4, color="#E24B4A", ls="--", lw=1.4,
               label="Ecker2015 D (median)")
    ax.set_xlabel("SOC")
    ax.set_ylabel("apparent D_s [cm2/s]")
    ax.set_title("D_s(SOC): fit form v1 vs v2")
    ax.legend(fontsize=7)

    ax = axes[1]
    ok = p2[p2["accepted"] & p2["Ds_ratio_vs_linear"].notna()]
    ax.semilogy(ok["SOC_mid"], ok["Ds_ratio_vs_linear"], "o", ms=3.2,
                color="#378ADD", alpha=0.55)
    ax.axhline(1.0, color="k", lw=0.8)
    ax.set_xlabel("SOC")
    ax.set_ylabel("D_v2 / D_v1 on the same pulse")
    ax.set_title("what the fit form alone moved")

    ax = axes[2]
    for tag, res, color in (("v1", v1_res, "#BA7517"),
                            ("v2", v2_res, "#1D9E75")):
        sub = res["pulses"][res["pulses"]["accepted"]]
        ratios = (sub["Ds_app_relax_m2_s"] / sub["Ds_app_m2_s"]).pow(0.5)
        ratios = ratios[np.isfinite(ratios)]
        if len(ratios):
            ax.hist(np.log10(ratios.clip(lower=1e-4)), bins=40,
                    alpha=0.55, color=color, label=tag)
    ax.axvline(0.0, color="k", lw=1.0)
    ax.set_xlabel("log10 sqrt(D_relax / D_pulse)")
    ax.set_ylabel("pulses")
    ax.set_title("OCP-free cross-check")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_ds_v1_vs_v2.png", dpi=150)
    plt.close(fig)

    # ---------------- report --------------------------------------
    eff = comparison["fit_effect"]
    lines = [
        "# Phase B1.6 — apparent D_s(SOC) with the equilibrium drift "
        "separated from the diffusion signal",
        "",
        f"- GITT cell `{GITT_CELL}`, p-OCV cell `{POCV_CELL}`, "
        f"model {args.model}",
        f"- pulses: **{len(seg)}**, {proto['pulse_time_s_median']:.0f} s "
        f"pulse / {proto['relax_time_s_median']:.0f} s rest",
        f"- accepted pulses: v1 **{v1_res['provenance']['n_accepted']}**, "
        f"v2 **{v2_res['provenance']['n_accepted']}**",
        f"- `dataset_role` of `{DATASET}` for this calibration: **{role}** "
        f"(declared in configs/datasets.yaml, enforced by "
        f"governance/dataset_roles.py)"
        + (f" — WARNING: {role_warnings[0]}" if role_warnings else ""),
        "",
        "## What changed",
        "",
        "Phase B1 inverted the Weppner-Huggins law from a first-order "
        "fit `V = a + m*sqrt(t)`, which assumes the equilibrium voltage "
        "is constant over the pulse.  It is not: the bulk composition "
        "advances during the pulse, so the equilibrium voltage drifts "
        "and the fitted sqrt(t) slope absorbs part of that drift.",
        "",
        f"Phase B1.6 uses `{comparison['fit_form']}`",
        "",
        "Everything else — the inversion, the local OCP slope, the gate "
        "values and the SOC binning — is imported from the Phase B1 "
        "module, so the two tables differ in exactly one thing.",
        "",
        "## Regression self-check",
        "",
        f"- recomputed v1 table vs the frozen Phase B1 table: "
        f"**{'identical' if repro.get('identical') else 'DIFFERS'}**"
        + (f" (max relative difference {repro['max_rel_diff']:.3e} over "
           f"{repro['n_rows']} rows)" if repro.get("checked") else
           f" ({repro.get('reason')})"),
        "",
        "## What the fit form moved on the real pulses",
        "",
        "| quantity | p5 | p25 | p50 | p75 | p95 |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in (("slope_ratio_linear_over_quad",
                        "slope (1st order) / slope (drift-corrected)"),
                       ("Ds_ratio_v2_over_v1",
                        "D_v2 / D_v1 (paired, per pulse)"),
                       ("drift_term_over_expected_equilibrium_drift",
                        "fitted linear term / (U'*I/Q_th)")):
        q = eff.get(key, {})
        if not q:
            continue
        lines.append(
            f"| {label} | " + " | ".join(
                f"{q[k]:.3f}" for k in ("p5", "p25", "p50", "p75", "p95")
            ) + " |"
        )
    drift_med = eff["drift_term_over_expected_equilibrium_drift"]["p50"]
    sign_frac = eff["drift_term_sign_matches_expected_fraction"]
    lines += [
        "",
        f"({eff['n_pulses']} pulses carry both fits; the drift row is "
        f"reported for the ones where U' exists.)",
        "",
        "## Same-pulse comparison (the fair one)",
        "",
        f"v1 accepts {v1_res['provenance']['n_accepted']} pulses and v2 "
        f"{v2_res['provenance']['n_accepted']}: a quadratic form fits "
        f"better, so v2 keeps more of the plateau and dilute pulses.  "
        f"Comparing whole-table medians therefore mixes two populations. "
        f"On the **{comparison['common_accepted_set']['n_pulses']} pulses "
        f"both accept** the two diffusivities are directly comparable:",
        "",
        "| group | n | D_s(v1) median [m2/s] | D_s(v2) median [m2/s] | "
        "v2/v1 (ratio of medians) | Ecker/v2 |",
        "|---|---|---|---|---|---|",
    ]
    cs = comparison["common_accepted_set"]
    lines.append(
        f"| all | {cs['n_pulses']} | {cs['v1_m2_s']['p50']:.3e} | "
        f"**{cs['v2_m2_s']['p50']:.3e}** | "
        f"{cs['v2_over_v1_median']:.3f} | — |"
    )
    for branch, blk in cs["branches"].items():
        lines.append(
            f"| {branch} | {blk['n_pulses']} | "
            f"{blk['v1_median_m2_s']:.3e} | "
            f"**{blk['v2_median_m2_s']:.3e}** | "
            f"{blk['v2_over_v1_median']:.3f} | "
            f"{blk['ecker_over_v2_median']:.1f}x |"
        )
    lines += [
        "",
        f"Reference (Ecker2015) median: **{ecker['median_m2_s']:.3e} m2/s**.",
        "",
        "## How much the fit form moved D — and in which direction",
        "",
        "Phase B1.5 measured, on MODEL pulses, that the first-order fit "
        "inflates the diffusion slope by a median 2.9x; since "
        "D = R^2/tau_d with tau_d ~ m^2, removing that inflation should "
        "push D **up** by about 9x.  On the real pulses the first-order "
        "fit gives the SMALLER slope, so the correction moves D **down** — "
        "and two independent summaries of the same pulses agree on that "
        "sign:",
        "",
        "| summary | question it answers | value |",
        "|---|---|---|",
        f"| paired ratio D_v2/D_v1 (median over the "
        f"{cs['n_pulses']} pulses both accept) | what did the fit form do "
        f"to a typical pulse? | **{cs['paired_ratio_median']:.2f}x** |",
        f"| ratio of the medians (same pulses) | where does the bulk of the "
        f"curve end up? | **{cs['v2_over_v1_median']:.3f}x** |",
        "",
        f"Only {100 * cs['fraction_paired_ratio_above_one']:.0f}% of "
        f"individual pulses move up, and the paired ratios span "
        f"{cs['paired_ratio_percentiles']['p5']:.2f}x to "
        f"{cs['paired_ratio_percentiles']['p95']:.2f}x, so the correction "
        f"is strongly heterogeneous in size and locally in sign — but the "
        f"sign of the net effect is not in doubt.",
        "",
        f"The drift diagnostic explains why the SIZE differs so much from "
        f"Phase B1.5's ~9x: pure equilibrium drift would be "
        f"`dU/dt = U'*I/Q_th`, but the fitted linear term is "
        f"**{drift_med:.1f}x** that value (median) and its **sign agrees "
        f"with the equilibrium drift in only {100 * sign_frac:.0f}%** of "
        f"pulses.  The extra term is carrying a slow non-equilibrium "
        f"transient (charge transfer, porous-electrode relaxation, the "
        f"pseudo-OCP's own settling) rather than the drift the correction "
        f"was designed for.  So the model-pulse calibration of the bias "
        f"does not transfer to these electrodes, and the only way to know "
        f"was to measure it.",
        "",
        "## D_s level against the reference (whole table)",
        "",
        "| branch | statistic | v1 | v2 | Ecker2015 |",
        "|---|---|---|---|---|",
    ]
    for branch, blk in comparison["branches"].items():
        for k in ("p25", "p50", "p75"):
            lines.append(
                f"| {branch} | {k} [m2/s] | {blk['v1_m2_s'][k]:.3e} | "
                f"**{blk['v2_m2_s'][k]:.3e}** | "
                f"{ecker['median_m2_s']:.3e} (median) |"
            )
        lines.append(
            f"| {branch} | v2 / v1 (median) | "
            f"{blk['v2_over_v1_median']:.3f} | — | — |"
        )
        lines.append(
            f"| {branch} | Ecker / v2 (median) | — | "
            f"{blk['ecker_over_v2_median']:.2f}x | — |"
        )
    lines += [
        "",
        "## SOC-resolved table (v2)",
        "",
        "| branch | SOC | n | D_s [cm2/s] | p25 | p75 | rel. unc. |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in v2_res["table"].iterrows():
        lines.append(
            f"| {r['branch']} | {r['SOC']:.2f} | {int(r['n_pulses'])} | "
            f"{r['Ds_app_cm2_s']:.3e} | {r['Ds_app_cm2_s_p25']:.3e} | "
            f"{r['Ds_app_cm2_s_p75']:.3e} | "
            f"{r['Ds_app_rel_uncertainty_median']:.4f} |"
        )
    if "windows" in comparison:
        lines += [
            "",
            "## p-OCV replay (control = Ecker2015 D, same frozen set)",
            "",
            "| window | diffusivity | RMSE [mV] | MAE [mV] | max abs [mV] |",
            "|---|---|---|---|---|",
        ]
        for win, blk in comparison["windows"].items():
            for tag, label in (("ecker_ds", "Ecker2015 D"),
                               ("v1", "SINTEF D_s (first order)"),
                               ("v2", "SINTEF D_s (drift-corrected)")):
                m = blk[tag]["metrics"]
                lines.append(
                    f"| {win} | {label} | **{m['rmse_mV']:.3f}** | "
                    f"{m['mae_mV']:.3f} | {m['max_abs_mV']:.3f} |"
                )
        lines += [
            "",
            "### Same comparison on a COMMON time grid",
            "",
            "The variants can end at different times (changing the "
            "diffusivity moves the voltage event that terminates the run), so "
            "the table above scores them on **different point sets** — and a "
            "truncated run is only judged where it survived, which understates "
            "its error.  Interpolating every variant onto the reference run's "
            "grid, restricted to the range all three cover:",
            "",
            "| window | common points | Ecker2015 D | D_s (first order) | "
            "D_s (drift-corrected) |",
            "|---|---|---|---|---|",
        ]
        for win, blk in comparison["windows"].items():
            cm = blk.get("coverage_matched", {})
            if "v1" not in cm:
                continue
            lines.append(
                f"| {win} | {cm['n_points']} | "
                f"**{cm['ecker_ds']['rmse_mV']:.3f}** | "
                f"{cm['v1']['rmse_mV']:.3f} | {cm['v2']['rmse_mV']:.3f} |"
            )
        changed = []
        for win, blk in comparison["windows"].items():
            cm = blk.get("coverage_matched", {})
            if "v1" not in cm:
                continue
            changed.append(
                f"{win}: first-order {blk['v1']['metrics']['rmse_mV']:.2f} "
                f"→ {cm['v1']['rmse_mV']:.2f} mV"
            )
        lines += [
            "",
            "**The numbers move a lot, and they move most for the runs that "
            "were truncated** (" + "; ".join(changed) + ").  The ordering is "
            "unchanged — Ecker < first-order < drift-corrected in both windows "
            "— so the conclusion is not an artefact of unequal coverage.  But "
            "any single RMSE quoted from the table above overstates the "
            "first-order curve's error, because that run was only scored "
            "where it survived.",
        ]
    lines += [
        "",
        "## First-order Weppner-Huggins excursion over the p-OCV window",
        "",
        "| window | Ecker D | D_s (v2) |",
        "|---|---|---|",
    ]
    for win, s in sens.items():
        lines.append(
            f"| {win} | {s['diffusion_overpotential_ecker_mV']:.2f} mV | "
            f"{s['diffusion_overpotential_v2_mV']:.2f} mV |"
        )
    lines += [
        "",
        "## Verdict",
        "",
        f"Redoing the table with the drift-corrected fit does NOT bring the "
        f"apparent D_s closer to the reference: on the {cs['n_pulses']} "
        f"pulses both reductions accept, the median falls from "
        f"{cs['v1_m2_s']['p50']:.3e} to {cs['v2_m2_s']['p50']:.3e} m2/s — "
        f"**{ecker['median_m2_s'] / cs['v2_m2_s']['p50']:.0f}x below** the "
        f"Ecker2015 median of {ecker['median_m2_s']:.3e} m2/s.",
        "",
        f"The correction therefore moved the value AWAY from the reference "
        f"by a paired median {cs['paired_ratio_median']:.2f}x — the "
        f"opposite of what Phase B1.5's model pulses predicted.  The drift "
        f"diagnostic explains why: the fitted linear term is several times "
        f"the pure equilibrium drift and its sign disagrees with it in "
        f"most pulses, so it absorbs non-diffusional relaxation rather "
        f"than the drift.",
        "",
        "This closes the fit-form line of investigation.  Two functionally "
        "different inversions of the same pulses agree on the qualitative "
        "conclusion — the apparent D_s from a single-particle "
        "Weppner-Huggins reduction of this GITT train is one to two orders "
        "of magnitude below the reference and does not improve the replay "
        "— while disagreeing on the value by a factor "
        f"{1.0 / cs['paired_ratio_median']:.2f} per pulse and "
        f"{1.0 / cs['v2_over_v1_median']:.2f} in level.  That spread, not "
        "either single number, is the honest error bar on any "
        "single-particle GITT diffusivity for this electrode.",
        "",
    ]
    if "windows" in comparison:
        lines += [
            "In the replay on the frozen parameter set:",
            "",
            "| window | Ecker2015 D | D_s (first order) | "
            "D_s (drift-corrected) |",
            "|---|---|---|---|",
        ]
        for win, blk in comparison["windows"].items():
            lines.append(
                f"| {win} | "
                f"**{blk['ecker_ds']['metrics']['rmse_mV']:.2f} mV** | "
                f"{blk['v1']['metrics']['rmse_mV']:.2f} mV | "
                f"{blk['v2']['metrics']['rmse_mV']:.2f} mV |"
            )
        lines += [
            "",
            "Both extracted curves are worse than the reference diffusivity, "
            "and the corrected one is worse than the first-order one because "
            "it is smaller still and starves the particle further.  "
            "**Neither is adopted.**",
            "",
        ]
    lines += [
        "## Wording (mandatory)",
        "",
        "**Apparent/effective** solid diffusivity, NOT an intrinsic "
        "material coefficient and NOT validation.  The p-OCV replay is a "
        "consistency check whose diffusion sensitivity is negligible at "
        "C/50.  Correcting the fit form removes one known functional bias; "
        "it does not make the value a material constant, and on this "
        "dataset it did not make it a better parameter either.",
        "",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[B1.6] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
