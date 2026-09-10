# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B2.1: apparent-D_s(SOC) DIAGNOSTICS + validity flags
#
# WHAT THIS MODULE DOES
#   Projects the per-pulse GITT analysis of Phase B1 into a tidy
#   diagnostic table, one row per pulse, with the seven fields the
#   Phase B2 brief asks for
#
#       SOC, Ds_app, WH_fit_R2, dE_pulse, dE_relax,
#       OCP_slope, validity_flag
#
#   plus the reason codes behind every rejection and a per-SOC
#   rollup.  Nothing is recomputed and nothing is fitted: the
#   numbers come from `outputs/analysis/graphite_phaseB1/`
#   (gitt_ds_app_pulses.csv), which is the audited output of the
#   Weppner-Huggins inversion.
#
# WHY A SEPARATE DIAGNOSTIC TABLE
#   A single D_s number hides why it should not be trusted.  The
#   validity question is not "is D_s in a plausible range" but "did
#   the Weppner-Huggins regime actually hold for this pulse", and
#   that is answered by the four independent signals below.  Keeping
#   them in one row per pulse is what makes the extraction auditable.
#
# THE FOUR SIGNALS BEHIND validity_flag
#   1. WH_fit_R2            - is V linear in sqrt(t) over the pulse?
#                             (the W-H short-time solution predicts
#                             linearity; a low R^2 means it does not
#                             describe this pulse)
#   2. OCP_slope            - U' = dOCP/dSOC of the FROZEN Phase B0.6
#                             table.  If the pulse's SOC sits outside
#                             the table there is no U' at all, and the
#                             inversion is undefined.
#   3. OCP local linearity  - dE_s = U' dSOC assumes U' is constant
#                             across the pulse step; a large voltage
#                             spread across the fit window violates it.
#   4. direction            - dV/dt must have the sign of I * U'.
#
# plus a dimensionless one that the model side cares about:
#   Fo_pulse = D tau_pulse / R^2   (Fourier number over the pulse)
# The W-H short-time expansion requires Fo << 1; Fo is reported so the
# regime assumption can be checked directly instead of assumed.
#
# This module imports numpy/pandas only -- never pybamm.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from extraction.gitt_diffusivity import (
    MAX_WINDOW_CURVATURE_MV,
    MIN_ABS_UPRIME,
    MIN_R2,
)

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_B1_DIR = "outputs/analysis/graphite_phaseB1"

# The seven fields the Phase B2 brief names, in brief order.
REQUIRED_FIELDS = (
    "SOC",
    "Ds_app_m2_s",
    "WH_fit_R2",
    "dE_pulse_mV",
    "dE_relax_mV",
    "OCP_slope_V_per_soc",
    "validity_flag",
)

VALID = "valid"
REJECTED = "rejected"

# reason codes -> human-readable text
REASON_TEXT: Dict[str, str] = {
    "undefined": (
        "D_s not defined: no usable sqrt(t) slope or U' below threshold"
    ),
    "r2_below_threshold": (
        "V is not linear in sqrt(t) over the pulse at the required level"
    ),
    "ocp_slope_unavailable": (
        "pulse SOC outside the branch OCP table, so U' does not exist"
    ),
    "ocp_not_locally_linear": (
        "OCP not locally linear across the pulse step, so the "
        "linearised W-H step is invalid"
    ),
    "direction_inconsistent": (
        "measured dV/dt direction disagrees with I * U'"
    ),
}

# pre-registered thresholds, imported from the Phase B1 inversion so the
# diagnostic and the extraction can never disagree about them
THRESHOLDS = {
    "min_r2": MIN_R2,
    "min_abs_u_prime": MIN_ABS_UPRIME,
    "max_window_curvature_mV": MAX_WINDOW_CURVATURE_MV,
}


def _reasons(row: pd.Series) -> List[str]:
    """Independent rejection reasons for one pulse (order is fixed)."""
    reasons: List[str] = []
    d = row.get("Ds_app_m2_s", np.nan)
    r2 = row.get("WH_fit_R2", np.nan)
    uprime = row.get("OCP_slope_V_per_soc", np.nan)
    curv = row.get("u_prime_window_curvature_mV", np.nan)
    flags = str(row.get("_flags", "") or "")

    if not np.isfinite(d) or d <= 0:
        reasons.append("undefined")
    if np.isfinite(r2) and r2 < THRESHOLDS["min_r2"]:
        reasons.append("r2_below_threshold")
    if not np.isfinite(uprime) or abs(uprime) < THRESHOLDS["min_abs_u_prime"]:
        reasons.append("ocp_slope_unavailable")
    if np.isfinite(curv) and curv > THRESHOLDS["max_window_curvature_mV"]:
        reasons.append("ocp_not_locally_linear")
    if "sign:" in flags:
        reasons.append("direction_inconsistent")
    return reasons


def load_pulses(
    b1_dir: Path | str = DEFAULT_B1_DIR,
    *,
    filename: str = "gitt_ds_app_pulses.csv",
) -> pd.DataFrame:
    """Per-pulse Phase B1 table (the audited inversion output)."""
    d = Path(b1_dir)
    if not d.is_absolute():
        d = ROOT / d
    path = d / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Phase B1 pulse table not found: {path} "
            f"(run scripts/graphite_phase_b1_compare.py first)"
        )
    return pd.read_csv(path)


def build_diagnostics(
    b1_dir: Path | str = DEFAULT_B1_DIR,
    *,
    branch: Optional[str] = None,
) -> pd.DataFrame:
    """
    Tidy per-pulse diagnostic table.

    Columns (the seven required ones first):
      SOC                    midpoint SOC of the pulse, on the same
                             charge-based axis as the frozen OCP
      Ds_app_m2_s            apparent/effective solid diffusivity
      Ds_app_cm2_s           same, cm^2/s
      WH_fit_R2              R^2 of V = a + m sqrt(t) over the pulse
      dE_pulse_mV            measured pulse overpotential (V_end - V_start)
      dE_relax_mV            measured relaxation overpotential
      OCP_slope_V_per_soc    U' from the frozen OCP table
      validity_flag          valid | rejected
    plus branch, cycle, pulse_id, the rejection reasons and the
    dimensionless Fourier number over the pulse.
    """
    src = load_pulses(b1_dir)
    if branch is not None:
        src = src[src["branch"] == branch]
    if src.empty:
        raise ValueError(f"no pulses for branch '{branch}'")

    ren = src.rename(columns={
        "SOC_mid": "SOC",
        "sqrt_t_r2": "WH_fit_R2",
        "delta_V_pulse_mV": "dE_pulse_mV",
        "delta_V_relax_mV": "dE_relax_mV",
        "u_prime_V_per_soc": "OCP_slope_V_per_soc",
    }).copy()
    ren["_flags"] = src["flags"].to_numpy()

    ren["rejection_reasons"] = [
        ";".join(_reasons(r)) for _, r in ren.iterrows()
    ]
    ren["validity_flag"] = np.where(
        ren["rejection_reasons"] == "", VALID, REJECTED
    )
    ren["is_valid"] = ren["validity_flag"] == VALID

    # dimensionless regime check of the W-H short-time expansion:
    # Fo_pulse = D tau / R^2 must be << 1 for the sqrt(t) law
    tau = ren["pulse_time_s"].to_numpy(float)
    R = ren["R_m"].to_numpy(float)
    D = ren["Ds_app_m2_s"].to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        ren["Fo_pulse"] = D * tau / R ** 2
        ren["tau_d_s_from_D"] = R ** 2 / D

    if "ds_app_rel_uncertainty" in src.columns:
        ren["Ds_app_rel_uncertainty"] = src["ds_app_rel_uncertainty"].to_numpy()

    # The seven brief-mandated fields come FIRST, in the brief's order,
    # built from REQUIRED_FIELDS itself so they can never drift apart.
    missing = [c for c in REQUIRED_FIELDS if c not in ren.columns]
    if missing:
        raise KeyError(
            f"per-pulse table is missing required diagnostic fields: "
            f"{missing}"
        )
    extra_cols = [
        "Ds_app_cm2_s", "is_valid", "rejection_reasons",
        "branch", "cycle", "pulse_id",
        "SOC_start", "SOC_end", "I_A", "pulse_time_s", "relax_time_s",
        "capacity_increment_mAh", "sqrt_t_slope_V_per_sqrt_s",
        "u_prime_halfwidth_soc", "u_prime_window_curvature_mV",
        "u_prime_knots", "dE_s_mV", "dE_tau_expected_mV",
        "Ds_app_relax_m2_s", "relax_over_pulse_sqrt_ratio",
        "Ds_app_rel_uncertainty", "tau_d_s_from_D", "Fo_pulse",
        "Q_th_Ah", "R_m",
    ]
    cols = list(REQUIRED_FIELDS) + [c for c in extra_cols if c in ren.columns]
    return ren[cols].sort_values(["branch", "SOC"]).reset_index(drop=True)


def diagnostics_by_soc(
    diag: pd.DataFrame,
    *,
    bin_width: float = 0.02,
) -> pd.DataFrame:
    """
    Per-(branch, SOC bin) rollup: how many pulses survive, and how far
    apart the surviving D_s values are.  The spread is reported in
    decades ON PURPOSE - the whole point of Phase B2 is that a single
    median hides a curve spanning orders of magnitude.
    """
    rows: List[dict] = []
    for branch, g in diag.groupby("branch", sort=True):
        b = np.round(g["SOC"].to_numpy(float) / bin_width) * bin_width
        for centre in sorted(set(b.tolist())):
            sub = g[b == centre]
            val = sub[sub["is_valid"]]
            dv = val["Ds_app_m2_s"].to_numpy(float)
            dv = dv[np.isfinite(dv) & (dv > 0)]
            rows.append({
                "branch": branch,
                "SOC": float(centre),
                "n_pulses": int(len(sub)),
                "n_valid": int(len(val)),
                "valid_fraction": float(len(val) / len(sub)),
                "Ds_median_m2_s": float(np.median(dv)) if dv.size else np.nan,
                "Ds_p05_m2_s": float(np.percentile(dv, 5)) if dv.size else np.nan,
                "Ds_p95_m2_s": float(np.percentile(dv, 95)) if dv.size else np.nan,
                "Ds_decades_spanned": (
                    float(np.log10(np.percentile(dv, 95)
                                   / np.percentile(dv, 5)))
                    if dv.size > 1 else np.nan
                ),
                "WH_fit_R2_median": float(val["WH_fit_R2"].median())
                if len(val) else np.nan,
                "OCP_slope_median_V_per_soc": (
                    float(val["OCP_slope_V_per_soc"].median())
                    if len(val) else np.nan
                ),
                "Fo_pulse_median": float(val["Fo_pulse"].median())
                if len(val) else np.nan,
            })
    return pd.DataFrame(rows).sort_values(["branch", "SOC"]).reset_index(
        drop=True
    )


def diagnostics_provenance(
    diag: pd.DataFrame,
    *,
    b1_dir: Path | str = DEFAULT_B1_DIR,
) -> Dict[str, object]:
    """Audit block for the diagnostic table."""
    d = Path(b1_dir)
    if not d.is_absolute():
        d = ROOT / d
    prov_path = d / "gitt_ds_app_provenance.json"
    upstream = json.loads(prov_path.read_text(encoding="utf-8")) \
        if prov_path.is_file() else {}
    n = int(len(diag))
    nv = int(diag["is_valid"].sum())
    reasons: Dict[str, int] = {}
    for r in diag.loc[~diag["is_valid"], "rejection_reasons"]:
        for code in str(r).split(";"):
            if code:
                reasons[code] = reasons.get(code, 0) + 1
    return {
        "calculation": "extraction/ds_diagnostics.py::build_diagnostics",
        "source": (
            f"{d.name}/gitt_ds_app_pulses.csv (Phase B1 Weppner-Huggins "
            f"inversion, itself derived from the Phase B1.0 GITT "
            f"segmentation and the frozen Phase B0.6 OCP tables)"
        ),
        "quantity": upstream.get("quantity"),
        "equation_reference": upstream.get("equation_reference"),
        "ocp_slope_source": upstream.get("U_prime_source"),
        "particle_radius_source": upstream.get("particle_radius_source"),
        "thresholds": dict(THRESHOLDS),
        "thresholds_note": (
            "imported from extraction/gitt_diffusivity.py so the "
            "diagnostic and the extraction cannot disagree about the "
            "acceptance gates"
        ),
        "reason_codes": REASON_TEXT,
        "n_pulses": n,
        "n_valid": nv,
        "n_rejected": n - nv,
        "valid_fraction": float(nv / n) if n else float("nan"),
        "rejection_counts": reasons,
        "Fo_pulse_note": (
            "Fo_pulse = D tau_pulse / R^2 is the Fourier number over one "
            "pulse; the Weppner-Huggins short-time expansion requires "
            "Fo << 1, and it is reported rather than assumed"
        ),
        "wording": (
            "the diagnostic table reports WHY an apparent D_s should or "
            "should not be trusted; it neither re-derives nor fits D_s, "
            "and no value here is an intrinsic material property"
        ),
    }


def write_diagnostics(
    diag: pd.DataFrame,
    by_soc: pd.DataFrame,
    provenance: Dict[str, object],
    out_dir: Path | str,
    *,
    prefix: str = "Ds",
) -> Dict[str, Path]:
    out = Path(out_dir)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "diagnostics": out / f"{prefix}_diagnostics.csv",
        "by_soc": out / f"{prefix}_diagnostics_by_soc.csv",
        "provenance": out / f"{prefix}_diagnostics_provenance.json",
    }
    diag.to_csv(paths["diagnostics"], index=False)
    by_soc.to_csv(paths["by_soc"], index=False)
    with paths["provenance"].open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, ensure_ascii=False)
    return paths
