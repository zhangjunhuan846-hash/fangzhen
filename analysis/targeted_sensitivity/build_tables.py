# ============================================================
# Phase A2 — table build step
#
# Reads the per-(run,param,factor) cached replays produced by
# simulate.py plus the frozen A1 time-aligned outputs, then
# computes the four output tables:
#
#   sensitivity_long.csv                 time-resolved S_p(t)
#   sensitivity_run_parameter_summary.csv   per (run,param) metrics
#   residual_alignment_matrix.csv           wide cos/proj matrix
#   conditioned_response.csv                bias/centered + ratio splits
#
# Metrics (definitions, matching the A2 task brief):
#   S_p(t) = [V(p(1+d)) - V(p(1-d))] / (2 d)   in mV per unit
#             fractional parameter change (d = 0.20)
#   response_rms_mV            = sqrt(mean(S_p^2))
#   cosine_alignment           = (e.S_p)/(||e|| ||S_p||)   raw vectors
#   projection_fraction        = ||Proj_{S_p} e||^2 / ||e||^2
#                                = cos^2(theta)  (single-direction
#                                span projection; LOCAL LINEAR
#                                DIAGNOSTIC, NOT fitted variance
#                                explained)
#   response_bias_mV / centered_response_rms_mV = mean(S_p) / std(S_p)
#   *_response_ratio           = RMS(S_p|condition) / RMS(S_p|all)
#     condition bins follow the A1 atlas rules (run-level edges):
#     high-|I|        = 3rd tercile of |I|
#     high-|dI/dt|    = > 90th percentile of |dI/dt|
#     late-progress   = elapsed_fraction >= 0.8
#
# No fitting.  battery_sim/ untouched (read-only).
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import residual_atlas as atlas  # noqa: E402
import simulate as sim  # noqa: E402
from common import DELTA, FACTORS, PARAMETERS, selected_runs  # noqa: E402

OUT = ROOT / "outputs" / "analysis" / "targeted_sensitivity"
OUT.mkdir(parents=True, exist_ok=True)

RUN_SHORT = {
    "chen2020/02/C0p5": "Chen2020 C2",
    "chen2020/02/C1p5": "Chen2020 1p5C",
    "calce_cs2/33/C0p5": "CS2 33 0p5C",
    "calce_20r/2/DST_50SOC": "20R DST50",
    "calce_20r/2/DST_80SOC": "20R DST80",
    "calce_a123/007/DST": "A123 007",
    "calce_a123/008/DST": "A123 008",
}


def _short(run_id: str) -> str:
    return RUN_SHORT.get(run_id, run_id.split("/")[-1])


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if x.size else float("nan")


def load_S(run, pid: str) -> np.ndarray:
    """Central-difference response vector (mV per unit fractional
    change), evaluated on the stored time-aligned grid."""
    v_hi = sim.solve_case(run, None, pid, FACTORS[1])["v_grid"]
    v_lo = sim.solve_case(run, None, pid, FACTORS[0])["v_grid"]
    return (v_hi - v_lo) * 1000.0 / (2.0 * DELTA)


def build_all():
    runs = selected_runs()
    summary_rows = []
    long_frames = []
    cond_rows = []

    for run0 in runs:
        rid = run0["run_id"]
        run = dict(run0)
        run["parameter_match_grade"] = atlas._pm(run["dataset"])["grade"]

        # shared run-level arrays (A1 definitions, locked)
        rf = atlas._read_run(run)
        t = rf["t"]
        e = rf["res_mV"]
        I = rf["I"]
        prog = rf["elapsed_frac"]
        n = t.size

        # residual reference stats
        rmse_all = float(np.sqrt(np.mean(e ** 2)))
        bias_all = float(np.mean(e))
        std_all = float(np.std(e))

        # condition masks (run-level edges, A1 binning rules)
        masks = {
            "high_current": np.abs(I) >= np.quantile(np.abs(I), 2.0 / 3.0),
            "high_transition": np.abs(rf["dI_dt"]) >= np.quantile(
                np.abs(rf["dI_dt"]), 0.9),
            "late_progress": prog >= 0.8,
        }

        # ---- residual-conditioned reference row ----
        cr = {
            "dataset": run["dataset"], "cell": run["cell"],
            "window": run["rate_slug"], "run_id": rid,
            "run_short": _short(rid), "protocol": run["protocol"],
            "parameter_match_grade": run["parameter_match_grade"],
            "kind": "residual", "parameter": "",
            "vector_rms_mV": rmse_all,
            "vector_bias_mV": bias_all,
            "vector_centered_rms_mV": std_all,
        }
        for key, col in [("high_current", "high_current_rms_mV"),
                         ("high_transition", "high_transition_rms_mV"),
                         ("late_progress", "late_progress_rms_mV")]:
            m = masks[key]
            cr[col] = _rms(e[m]) if m.sum() >= 5 else np.nan
            cr[col.replace("_rms_mV", "_ratio")] = (
                float(_rms(e[m]) / rmse_all)
                if m.sum() >= 5 and rmse_all > 1e-9 else np.nan
            )
        cr["n_points"] = n
        cond_rows.append(cr)

        # ---- per-parameter rows ----
        for pid in PARAMETERS:
            S = load_S(run, pid)
            valid = np.isfinite(S) & np.isfinite(e)
            if valid.sum() == 0:
                raise RuntimeError(
                    f"{rid}/{pid}: no valid overlap between perturbed "
                    f"replays and residual grid"
                )
            s = S[valid]
            ee = e[valid]

            rec = {
                "dataset": run["dataset"], "cell": run["cell"],
                "window": run["rate_slug"], "run_id": rid,
                "run_short": _short(rid), "protocol": run["protocol"],
                "parameter_match_grade": run["parameter_match_grade"],
                "parameter": pid, "delta": DELTA,
                "n_points": int(valid.sum()),
                "coverage_fraction": float(valid.mean()),
            }

            # 1) response magnitude
            rms_p = float(np.sqrt(np.mean(s ** 2)))
            rec["response_rms_mV"] = rms_p

            # 2) residual-sensitivity alignment (raw vectors)
            ne = float(np.linalg.norm(ee))
            ns = float(np.linalg.norm(s))
            if ne > 0 and ns > 0:
                dot = float(np.dot(ee, s))
                rec["cosine_alignment"] = dot / (ne * ns)
                rec["projection_fraction"] = dot ** 2 / (
                    np.dot(ee, ee) * np.dot(s, s))
                # affine R2 (intercept allowed): how much of the
                # residual VARIANCE around its mean the S_p shape
                # explains once a free vertical offset is allowed
                b = np.dot(ee - ee.mean(), s - s.mean()) / np.dot(
                    s - s.mean(), s - s.mean())
                a = ee.mean() - b * s.mean()
                ss_res = float(np.sum((ee - (a + b * s)) ** 2))
                ss_tot = float(np.sum((ee - ee.mean()) ** 2))
                rec["affine_r2"] = 1.0 - ss_res / ss_tot if ss_tot > 0 \
                    else np.nan
            else:
                rec["cosine_alignment"] = np.nan
                rec["projection_fraction"] = np.nan
                rec["affine_r2"] = np.nan

            # 3) bias / centered decomposition of the RESPONSE vector
            rec["response_bias_mV"] = float(np.mean(s))
            rec["centered_response_rms_mV"] = float(np.std(s))

            # 4) conditioned response ratios
            cond_map = {
                "high_current": "high_current_response_ratio",
                "high_transition": "high_transition_response_ratio",
                "late_progress": "late_progress_response_ratio",
            }
            for key, col in cond_map.items():
                m = masks[key] & valid
                if m.sum() >= 5 and rms_p > 1e-9:
                    rec[col] = float(np.sqrt(np.mean(S[m] ** 2)) / rms_p)
                else:
                    rec[col] = np.nan

            # residual reference (per-run constants)
            rec["residual_RMSE_mV"] = rmse_all
            rec["residual_Bias_mV"] = bias_all
            rec["residual_std_mV"] = std_all
            summary_rows.append(rec)

            # conditioned response row
            rr = {
                "dataset": run["dataset"], "cell": run["cell"],
                "window": run["rate_slug"], "run_id": rid,
                "run_short": _short(rid), "protocol": run["protocol"],
                "parameter_match_grade": run["parameter_match_grade"],
                "kind": "response", "parameter": pid,
                "vector_rms_mV": rms_p,
                "vector_bias_mV": rec["response_bias_mV"],
                "vector_centered_rms_mV": rec["centered_response_rms_mV"],
            }
            for key, col in [("high_current", "high_current_rms_mV"),
                             ("high_transition", "high_transition_rms_mV"),
                             ("late_progress", "late_progress_rms_mV")]:
                m = masks[key] & valid
                rr[col] = (_rms(S[m]) if m.sum() >= 5 else np.nan)
                rr[col.replace("_rms_mV", "_ratio")] = (
                    float(_rms(S[m]) / rms_p)
                    if m.sum() >= 5 and rms_p > 1e-9 else np.nan
                )
            rr["n_points"] = int(valid.sum())
            cond_rows.append(rr)

            # time-resolved long rows
            long_frames.append(pd.DataFrame({
                "dataset": run["dataset"], "cell": run["cell"],
                "window": run["rate_slug"], "run_id": rid,
                "run_short": _short(rid), "protocol": run["protocol"],
                "parameter_match_grade": run["parameter_match_grade"],
                "parameter": pid, "delta": DELTA,
                "time_s": t,
                "residual_mV": e,
                "response_mV_per_unit": S,
                "abs_current_A": np.abs(I),
                "progress_fraction": prog,
                "valid": valid,
                "response_rms_mV": rec["response_rms_mV"],
                "cosine_alignment": rec["cosine_alignment"],
                "projection_fraction": rec["projection_fraction"],
            }))

    summary = pd.DataFrame(summary_rows)
    long = pd.concat(long_frames, ignore_index=True)
    cond = pd.DataFrame(cond_rows)

    # ---- alignment matrix (rows = parameters; cols = runs x cos/proj)
    specs = sim.load_parameter_specs()
    mat_rows = []
    for pid in PARAMETERS:
        mrow = {"parameter": pid, "group": specs[pid]["group"]}
        for r in runs:
            rid = r["run_id"]
            rec = next(x for x in summary_rows
                       if x["run_id"] == rid and x["parameter"] == pid)
            tag = _short(rid).replace(" ", "_")
            mrow[f"cos_{tag}"] = rec["cosine_alignment"]
            mrow[f"proj_{tag}"] = rec["projection_fraction"]
            mrow[f"rms_{tag}"] = rec["response_rms_mV"]
        mat_rows.append(mrow)
    matrix = pd.DataFrame(mat_rows)

    # ---- write ----
    long.to_csv(OUT / "sensitivity_long.csv", index=False)
    summary.to_csv(OUT / "sensitivity_run_parameter_summary.csv",
                   index=False)
    matrix.to_csv(OUT / "residual_alignment_matrix.csv", index=False)
    cond.to_csv(OUT / "conditioned_response.csv", index=False)

    print("sensitivity_long rows:", len(long))
    print("summary rows:", len(summary))
    print("conditioned rows:", len(cond))
    print("wrote ->", OUT)
    return summary


def main():
    summary = build_all()
    cols = ["run_short", "parameter", "response_rms_mV",
            "cosine_alignment", "projection_fraction"]
    top = summary.sort_values("response_rms_mV", ascending=False).head(12)
    print(top[cols].to_string(index=False,
                              float_format=lambda x: f"{x:.3f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
