# ============================================================
# Phase A2 — interpretation step (NO FITTING, NO SIMULATION)
#
# Turns the 6 runs x 9 parameters metric table into the seven
# report items required by the Phase A2 brief.  This step only
# ranks and gates; it never estimates, regresses or optimises a
# parameter value.  It reads CSVs already on disk and performs no
# PyBaMM solve.
#
# ------------------------------------------------------------------
# TWO DIFFERENT METRIC FAMILIES — DO NOT INTERCHANGE
# ------------------------------------------------------------------
#   RAW          cosine_alignment, projection_fraction
#                computed on the UNCENTRED vectors e(t), S_p(t).
#                projection_fraction = cos^2(theta) on uncentred
#                vectors, therefore it INCLUDES the shared DC
#                (mean-offset) component.  For bias-dominated runs
#                this inflates the value: any nearly-constant
#                response automatically "aligns" with a nearly
#                -constant residual.
#                -> purpose: total co-directionality
#                   (offset + shape together).
#
#   CENTERED     affine_r2 == centered cosine^2
#                R^2 of e ~ a + b*S_p with a free intercept, i.e.
#                the squared Pearson correlation of (e, S_p) after
#                removing both means.  The shared DC component is
#                projected out.
#                -> purpose: SHAPE-ONLY agreement.
#
#   Both are reported side by side everywhere.  A high raw value
#   with a low centred value means "co-linear with the residual
#   OFFSET", not "reproduces the residual SHAPE".
#
# ------------------------------------------------------------------
# GATES
# ------------------------------------------------------------------
#   Pre-registered BEFORE the first look at results:
#     ALIGN_GATE   |cos(e, S_p)|        >= 0.70
#     PROJ_GATE    projection_fraction  >= 0.49   (= 0.70^2)
#     MAG_GATE     coverage_20pct       >= 0.10
#   Added AFTER the first pass (NOT pre-registered — disclosed in
#   the report) because raw cos/proj were found to be DC-inflated:
#     SHAPE_GATE   affine_r2 (centred)  >= 0.50
#     AMP_GATE     coverage_20pct       >= 1.00   (a +/-20 % move
#                  can span the whole residual RMS within the
#                  local linear range)
#
#   coverage_20pct = 0.20 * response_rms_mV / residual_RMSE_mV
#                  = fraction of the residual RMS that a +/-20 %
#                    change of the parameter can move.
#
# ------------------------------------------------------------------
# VOCABULARY RULES (frozen)
# ------------------------------------------------------------------
#   ALLOWED : "candidate model direction"
#             "strongly shape-aligned, amplitude-insufficient
#              candidate model direction"
#             "magnitude-viable, shape-unconfirmed"
#             "within the local +/-20 % single-parameter
#              perturbation range the tested kinetic/transport
#              parameter block is insufficient to explain the
#              observed residual magnitude"
#
#   FORBIDDEN (never write these):
#     "the residual is not determined by these parameter values"
#     "therefore the error is model-structure error"
#     "identified parameter" / "identified <name> error"
#     "root cause" / "fitted variance explained"
# ============================================================

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

from common import SELECTION_RATIONALE, A123_SELECTION  # noqa: E402

OUT = ROOT / "outputs" / "analysis" / "targeted_sensitivity"

# --- gates ---------------------------------------------------------
ALIGN_GATE = 0.70      # pre-registered
PROJ_GATE = 0.49       # pre-registered
MAG_GATE = 0.10        # pre-registered
SHAPE_GATE = 0.50      # added after first pass (disclosed)
AMP_GATE = 1.00        # added after first pass (disclosed)
WEAK = 0.30            # pre-registered

DELTA_COVER = 0.20     # the perturbation actually applied (+-20 %)

# Confounders that this block does NOT test.  Listed verbatim in the
# report for every B-grade (surrogate parameter set) run, so that a
# null result cannot be read as "the physics is fine".
CONFOUNDERS_NOT_TESTED = [
    "OCP",
    "stoichiometry window",
    "active-material inventory",
    "initial-state mapping",
    "multi-parameter interaction",
    "nonlinear large perturbations",
    "other resistance terms",
]

# The exact phrase that MUST be used whenever a run has no candidate
# direction.  It is deliberately scoped to the perturbation range
# actually tested.
NULL_STATEMENT = (
    "Within the local +/-20% single-parameter perturbation range, "
    "the tested kinetic/transport parameter block is insufficient "
    "to explain the observed residual magnitude."
)


def centred_metrics_from_long() -> pd.DataFrame:
    """Signed centred cosine + centred cos^2, recomputed from the
    time-resolved table.  Pure pandas, no solve.

    centred cos^2 must reproduce affine_r2 (they are the same
    quantity); the difference is carried as an audit column.
    """
    lg = pd.read_csv(OUT / "sensitivity_long.csv")
    lg = lg[lg["valid"]] if "valid" in lg.columns else lg
    rows = []
    for (rid, par), g in lg.groupby(["run_id", "parameter"]):
        e = g["residual_mV"].to_numpy(float)
        s = g["response_mV_per_unit"].to_numpy(float)
        ec, sc = e - e.mean(), s - s.mean()
        ne, ns = float(np.linalg.norm(ec)), float(np.linalg.norm(sc))
        if ne > 0 and ns > 0:
            cc = float(np.dot(ec, sc) / (ne * ns))
        else:
            cc = np.nan
        rows.append(dict(run_id=rid, parameter=par,
                         centred_cosine=cc,
                         centred_projection_fraction=cc * cc
                         if np.isfinite(cc) else np.nan))
    return pd.DataFrame(rows)


def classify(row) -> str:
    """Two-axis gate: raw (offset+shape) AND centred (shape only)."""
    raw_pass = (abs(row["cosine_alignment"]) >= ALIGN_GATE
                and row["projection_fraction"] >= PROJ_GATE)
    shape_pass = row["affine_r2"] >= SHAPE_GATE
    mag_pass = row["coverage_20pct"] >= MAG_GATE

    if not raw_pass:
        if abs(row["cosine_alignment"]) < WEAK:
            return "weak_or_inconsistent"
        return "shape_unconfirmed"
    if shape_pass and mag_pass:
        # Shape confirmed and lever above the minimum bar — still only
        # a DIRECTION, and the amplitude is separately qualified.
        return ("strongly_shape_aligned_amplitude_insufficient_"
                "candidate_model_direction"
                if row["coverage_20pct"] < AMP_GATE
                else "candidate_model_direction")
    if shape_pass and not mag_pass:
        return "shape_aligned_magnitude_short"
    if mag_pass and not shape_pass:
        return "magnitude_viable_shape_unconfirmed"
    return "shape_unconfirmed"


def main() -> int:
    df = pd.read_csv(OUT / "sensitivity_run_parameter_summary.csv")
    df["coverage_20pct"] = (
        DELTA_COVER * df["response_rms_mV"] / df["residual_RMSE_mV"]
    )
    df["abs_cos"] = df["cosine_alignment"].abs()

    cen = centred_metrics_from_long()
    df = df.merge(cen, on=["run_id", "parameter"], how="left")
    # audit: affine_r2 and centred cos^2 are the same quantity
    df["affine_vs_centred_abs_diff"] = (
        df["affine_r2"] - df["centred_projection_fraction"]).abs()

    df["class"] = df.apply(classify, axis=1)
    df["magnitude_rank_in_run"] = (
        df.groupby("run_id")["response_rms_mV"]
        .rank(ascending=False, method="min").astype(int)
    )
    df = df.sort_values(["run_id", "response_rms_mV"],
                        ascending=[True, False])
    df.to_csv(OUT / "candidate_directions.csv", index=False)

    # Wide side-by-side matrix: raw (DC-included) and centred (shape-only)
    # for every run x parameter.  Companion to residual_alignment_matrix.csv,
    # which carries the raw family only.
    run_ids = sorted(df["run_id"].unique())
    cols = {}
    for _, r in df.iterrows():
        cols.setdefault(r["parameter"], {})[r["run_id"]] = r
    wide = []
    for par in sorted(cols):
        rec = {"parameter": par}
        for rid in run_ids:
            r = cols[par].get(rid)
            if r is None:
                continue
            rec[f"{rid}::raw_cos"] = round(float(r["cosine_alignment"]), 4)
            rec[f"{rid}::raw_proj"] = round(float(r["projection_fraction"]), 4)
            rec[f"{rid}::centred_cos"] = round(float(r["centred_cosine"]), 4)
            rec[f"{rid}::centred_r2"] = round(float(r["affine_r2"]), 4)
            rec[f"{rid}::cover20"] = round(float(r["coverage_20pct"]), 4)
        wide.append(rec)
    pd.DataFrame(wide).to_csv(OUT / "centred_shape_matrix.csv", index=False)

    runs = list(df["run_id"].unique())
    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 74)
    emit("Phase A2 - Residual-guided Targeted Sensitivity (6 runs x 9 params)")
    emit("delta = 0.20 central difference | local linear diagnostic only")
    emit("NO fitting, NO optimisation, NO new simulation in this step")
    emit("=" * 74)
    emit(f"[0] completion: {len(runs)} runs x "
         f"{df['parameter'].nunique()} parameters = {len(df)} cells, "
         f"valid = {int(df['coverage_fraction'].ge(0.999).sum())}/{len(df)}")
    emit(f"    A123 representative: {A123_SELECTION['chosen']} "
         f"({A123_SELECTION['criterion']})")
    emit(f"    audit: max|affine_r2 - centred_cos^2| = "
         f"{df['affine_vs_centred_abs_diff'].max():.2e} "
         f"(the two are the same quantity)")
    emit("")
    emit("METRIC FAMILIES (different questions, both reported):")
    emit("  RAW      cosine_alignment / projection_fraction = cos^2 on")
    emit("           UNCENTRED vectors -> includes the shared DC")
    emit("           component; inflated for bias-dominated runs.")
    emit("           Purpose: total co-directionality (offset + shape).")
    emit("  CENTERED affine_r2 = centred cosine^2 (R^2 of e ~ a + b*S),")
    emit("           DC component projected out.")
    emit("           Purpose: SHAPE-ONLY agreement.")
    emit("")

    for rid in sorted(runs):
        sub = df[df["run_id"] == rid].copy()
        r0 = sub.iloc[0]
        bias_frac = (r0["residual_Bias_mV"] ** 2
                     / r0["residual_RMSE_mV"] ** 2)
        emit("-" * 74)
        emit(f"{rid}   [{r0['run_short']} | grade {r0['parameter_match_grade']}"
             f" | {r0['protocol']}]")
        emit(f"  residual: RMSE {r0['residual_RMSE_mV']:.1f} mV | "
             f"Bias {r0['residual_Bias_mV']:.1f} mV | "
             f"std {r0['residual_std_mV']:.1f} mV | "
             f"bias^2/RMSE^2 = {bias_frac:.2f}")
        emit(f"  rationale: {SELECTION_RATIONALE.get(rid, '')}")

        top_rms = sub.nlargest(3, "response_rms_mV")
        top_cos = sub.reindex(sub["abs_cos"].sort_values(
            ascending=False).index).head(3)
        top_proj = sub.nlargest(3, "projection_fraction")
        top_shape = sub.nlargest(3, "affine_r2")

        emit("  top-3 response magnitude [mV per unit frac. change]:")
        for _, r in top_rms.iterrows():
            emit(f"      {r['parameter']:<8} rms={r['response_rms_mV']:8.2f}"
                 f"  cover20={r['coverage_20pct']:5.2f}"
                 f"  cos={r['cosine_alignment']:+.3f}"
                 f"  centredR2={r['affine_r2']:+.3f}")
        emit("  top-3 RAW |alignment| (sign preserved; DC-inflated):")
        for _, r in top_cos.iterrows():
            emit(f"      {r['parameter']:<8} cos={r['cosine_alignment']:+.3f}"
                 f"  proj={r['projection_fraction']:5.3f}"
                 f"  | centredR2={r['affine_r2']:5.3f}"
                 f"  rms={r['response_rms_mV']:8.2f}"
                 f"  cover20={r['coverage_20pct']:5.2f}")
        emit("  top-3 RAW projection fraction (= cos^2, uncentred):")
        for _, r in top_proj.iterrows():
            emit(f"      {r['parameter']:<8} proj={r['projection_fraction']:5.3f}"
                 f"  cos={r['cosine_alignment']:+.3f}"
                 f"  | centredR2={r['affine_r2']:5.3f}")
        emit("  top-3 CENTERED shape metric (affine_r2 = centred cos^2):")
        for _, r in top_shape.iterrows():
            emit(f"      {r['parameter']:<8} centredR2={r['affine_r2']:5.3f}"
                 f"  | raw cos={r['cosine_alignment']:+.3f}"
                 f"  proj={r['projection_fraction']:5.3f}"
                 f"  rms={r['response_rms_mV']:8.2f}"
                 f"  cover20={r['coverage_20pct']:5.2f}")

        cand = sub[sub["class"].str.contains("candidate_model_direction")]
        short = sub[sub["class"] == "shape_aligned_magnitude_short"]
        mv = sub[sub["class"] == "magnitude_viable_shape_unconfirmed"]
        weak = sub[sub["class"] == "weak_or_inconsistent"]
        emit("  classification:")
        if len(cand):
            for _, r in cand.iterrows():
                emit(f"      {r['parameter']:<8} "
                     f"-> strongly shape-aligned, amplitude-insufficient "
                     f"candidate model direction "
                     f"(raw cos {r['cosine_alignment']:+.3f}, "
                     f"raw proj {r['projection_fraction']:.3f}, "
                     f"centredR2 {r['affine_r2']:.3f}, "
                     f"cover20 {r['coverage_20pct']:.3f})")
        else:
            emit("      candidate model direction : NONE")
        emit(f"      shape-aligned, magnitude short      : "
             f"{list(short['parameter']) if len(short) else 'NONE'}")
        emit(f"      magnitude-viable, shape-unconfirmed : "
             f"{list(mv['parameter']) if len(mv) else 'NONE'}")
        emit(f"      weak / inconsistent with e(t)       : "
             f"{list(weak['parameter']) if len(weak) else 'NONE'}")

        if len(cand) == 0:
            emit(f"  >> {NULL_STATEMENT}")
            emit(f"     (best raw |cos|={sub['abs_cos'].max():.2f}, "
                 f"best centredR2={sub['affine_r2'].max():.2f}, "
                 f"best cover20={sub['coverage_20pct'].max():.2f})")
        if str(r0["parameter_match_grade"]).upper().startswith("B"):
            emit("  >> untested confounders for this B-grade (surrogate) run:")
            for c in CONFOUNDERS_NOT_TESTED:
                emit(f"       - {c}")
        emit("")

    emit("=" * 74)
    emit("GATES  pre-registered: |cos| >= %.2f, proj >= %.2f, cover20 >= %.2f"
         % (ALIGN_GATE, PROJ_GATE, MAG_GATE))
    emit("       added after first pass (disclosed): centredR2 >= %.2f, "
         "amplitude-sufficient cover20 >= %.2f" % (SHAPE_GATE, AMP_GATE))
    emit("       projection_fraction = cos^2 on UNCENTRED vectors ->")
    emit("       inflated by the shared DC component for bias-dominated runs;")
    emit("       the centred metric is reported alongside for that reason.")
    emit("=" * 74)

    (OUT / "interpret_report.txt").write_text(
        "\n".join(lines), encoding="utf-8")
    (OUT / "interpret_gates.json").write_text(json.dumps({
        "pre_registered": {
            "align_gate_abs_cos": ALIGN_GATE,
            "projection_gate": PROJ_GATE,
            "magnitude_gate_coverage_20pct": MAG_GATE,
            "weak_below_abs_cos": WEAK,
        },
        "added_after_first_pass_disclosed": {
            "shape_gate_centred_r2": SHAPE_GATE,
            "amplitude_sufficient_gate_coverage_20pct": AMP_GATE,
            "reason": ("projection_fraction = cos^2 on uncentred vectors is "
                       "inflated by the shared DC component for "
                       "bias-dominated runs; a centred shape gate was "
                       "therefore required before any direction may be "
                       "called a candidate."),
        },
        "coverage_definition": ("0.20 * response_rms_mV / residual_RMSE_mV"),
        "metric_families": {
            "raw_cosine_and_projection": {
                "vectors": "uncentred e(t), S_p(t)",
                "includes_dc_component": True,
                "purpose": "total co-directionality (offset + shape)",
                "caveat": ("inflated when both vectors are dominated by a "
                           "constant offset"),
            },
            "centred_shape_metric": {
                "definition": ("affine_r2 = R^2 of e ~ a + b*S_p with free "
                               "intercept = squared Pearson correlation of "
                               "(e, S_p) = centred cosine^2"),
                "includes_dc_component": False,
                "purpose": "shape-only agreement",
                "caveat": "no information about amplitude adequacy",
            },
        },
        "confounders_not_tested": CONFOUNDERS_NOT_TESTED,
        "null_statement_wording": NULL_STATEMENT,
        "fits_performed": 0,
        "simulations_run": 0,
        "vocabulary_allowed": [
            "candidate model direction",
            "strongly shape-aligned, amplitude-insufficient candidate "
            "model direction",
            "magnitude-viable, shape-unconfirmed",
        ],
        "vocabulary_forbidden": [
            "residual is not determined by these parameter values",
            "therefore the error is model-structure error",
            "identified parameter",
            "root cause",
            "fitted variance explained",
        ],
    }, indent=2), encoding="utf-8")
    print("wrote", OUT / "candidate_directions.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
