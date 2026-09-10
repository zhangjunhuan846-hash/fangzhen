# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B1.6: APPARENT solid diffusivity D_s(SOC) from GITT,
#             with the equilibrium drift separated from the
#             diffusion signal
#
# WHAT CHANGES AGAINST PHASE B1
#   Phase B1 inverted the Weppner-Huggins law from a first-order
#   fit of the pulse,
#
#       V(t) = a + m*sqrt(t)
#
#   which assumes the EQUILIBRIUM voltage is constant while the pulse
#   is on.  It is not: the bulk-average lithium content advances roughly
#   linearly during the pulse, so U(t) drifts linearly and the fitted
#   sqrt(t) slope absorbs part of that drift.  Phase B1.5 measured the
#   effect directly on model-generated pulses of this same 1800 s /
#   C-rate protocol: the first-order slope inflated the diffusion term
#   by a median 2.9x, i.e. D low by about 9x, and -- crucially -- the
#   R^2 of both fits stayed above 0.95, so the Phase B1 gate
#   (R^2 >= 0.90) CANNOT detect the wrong form.
#
#   This module uses the drift-corrected fit
#
#       V(t) = a + b*t + m*sqrt(t)
#
#   and inverts the SAME Weppner-Huggins relation with the `m` of that
#   fit.  The equation, the inversion, the OCP slope and every
#   acceptance gate are shared with Phase B1 -- imported, not copied --
#   so the two tables differ in exactly one thing: the fit form.
#
# STILL APPARENT, NOT INTRINSIC
#   Nothing here repairs the deeper problem found in B1/B1.5: a
#   single-particle model cannot separate solid diffusion from the
#   porous-electrode and pseudo-OCP contributions, and R comes from the
#   reference set rather than from a measurement.  Removing the
#   known functional bias is a necessary bookkeeping step, not a
#   validation of the value.
#
# This module imports numpy/pandas only -- never pybamm.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# the OCP slope and the acceptance gates are imported from the Phase B1
# module on purpose: there must be exactly one definition of each, and a
# test asserts the two modules agree on their values.
from extraction.gitt_diffusivity import (
    EQUATION_REFERENCE,
    MAX_WINDOW_CURVATURE_MV,
    MIN_ABS_UPRIME,
    MIN_R2,
    MIN_SLOPE_KNOTS,
    REFERENCE_RADIUS_SOURCE,
    SLOPE_HALFWIDTH_FACTOR,
    local_ocp_slope,
)

ROOT = Path(__file__).resolve().parents[1]

SLOPE_COLUMN = "quad_sqrt_t_slope_V_per_sqrt_s"
STDERR_COLUMN = "quad_sqrt_t_slope_stderr"
R2_COLUMN = "quad_r2"
T_SLOPE_COLUMN = "quad_t_slope_V_per_s"
LINEAR_SLOPE_COLUMN = "sqrt_t_slope_V_per_sqrt_s"
LINEAR_R2_COLUMN = "sqrt_t_r2"

FIT_DESCRIPTION = (
    "V(t) = a + b*t + m*sqrt(t), fitted over the pulse with the first "
    "IR_SKIP seconds removed; the linear term carries the equilibrium "
    "drift caused by the bulk composition advancing during the pulse, "
    "so `m` is the diffusional part alone.  Phase B1 instead used "
    "V(t) = a + m*sqrt(t)."
)

EQUATION_REFERENCE_V2 = (
    EQUATION_REFERENCE
    + ".  Phase B1.6 keeps the same Weppner-Huggins inversion but takes "
      "`m` from the drift-corrected fit V = a + b*t + m*sqrt(t)"
)


def compute_ds_app_v2(
    segments: pd.DataFrame,
    ocp_tables: Dict[str, pd.DataFrame],
    *,
    particle_radius_m: float,
    q_th_Ah: float,
    particle_radius_source: str = REFERENCE_RADIUS_SOURCE,
    active_mass_source: str = "",
    equation_reference: str = EQUATION_REFERENCE_V2,
    cycles: Optional[List[int]] = None,
) -> Dict[str, object]:
    """
    Apparent D_s(SOC) for every GITT pulse, from the drift-corrected fit.

    Same inputs, same gates and same output tables as
    ``extraction.gitt_diffusivity.compute_ds_app``; the only difference
    is which fitted slope is inverted.  Each row also carries the
    first-order result, so the effect of the fit form is visible pulse
    by pulse.
    """
    seg = segments.copy()
    if cycles is not None:
        seg = seg[seg["cycle"].isin(cycles)].copy()
    if seg.empty:
        raise ValueError("no GITT pulses selected")
    for col in (SLOPE_COLUMN, STDERR_COLUMN, R2_COLUMN):
        if col not in seg.columns:
            raise KeyError(
                f"segmentation has no '{col}': it was produced by the "
                f"Phase B1 extractor, which stores only the first-order "
                f"fit.  Re-run extraction.gitt_extractor first."
            )

    q_th = float(q_th_Ah)
    if q_th <= 0:
        raise ValueError("q_th_Ah must be positive")
    R = float(particle_radius_m)
    if R <= 0:
        raise ValueError("particle_radius_m must be positive")

    rows: List[dict] = []
    for _, p in seg.iterrows():
        branch = str(p["branch"])
        tbl = ocp_tables[branch]
        soc_mid = 0.5 * (float(p["SOC_start"]) + float(p["SOC_end"]))
        step_soc = abs(float(p["SOC_end"]) - float(p["SOC_start"]))
        slope = local_ocp_slope(tbl, soc_mid,
                                halfwidth=max(SLOPE_HALFWIDTH_FACTOR * step_soc,
                                              1e-4))
        u_prime = slope["slope"]
        tau = float(p["pulse_time_s"])
        I = float(p["I_A"])
        m = float(p[SLOPE_COLUMN])
        d_m = float(p[STDERR_COLUMN])
        r2 = float(p[R2_COLUMN])
        b_drift = float(p[T_SLOPE_COLUMN]) if T_SLOPE_COLUMN in seg.columns \
            else float("nan")
        m_lin = float(p[LINEAR_SLOPE_COLUMN]) \
            if LINEAR_SLOPE_COLUMN in seg.columns else float("nan")
        r2_lin = float(p[LINEAR_R2_COLUMN]) \
            if LINEAR_R2_COLUMN in seg.columns else float("nan")
        flags: List[str] = []

        if not np.isfinite(m) or m == 0 or not np.isfinite(u_prime) \
                or abs(u_prime) < MIN_ABS_UPRIME or I == 0:
            D_pulse = tau_d = rel_u = float("nan")
            flags.append("undefined: |U'| below threshold or no slope")
        else:
            # identical inversion to Phase B1, only `m` differs:
            #   m = U' (2I/(3Q_th)) sqrt(tau_d/pi)
            #   tau_d = pi (3 Q_th m / (2 I U'))^2 ;  D = R^2 / tau_d
            # Q_th enters in AMPERE-SECONDS, exactly as PyBOP builds it.
            q_th_as = q_th * 3600.0
            tau_d = np.pi * (3.0 * q_th_as * m / (2.0 * I * u_prime)) ** 2
            D_pulse = R ** 2 / tau_d if tau_d > 0 else float("nan")
            rel_u = 2.0 * d_m / abs(m) if (np.isfinite(d_m) and m != 0) \
                else float("nan")

        if np.isfinite(u_prime) and I != 0 and np.isfinite(m):
            if np.sign(m) != np.sign(I * u_prime):
                flags.append("sign: dV/dt direction disagrees with I*U'")

        # ---- OCP-free cross-check (unchanged from B1) -------------
        dEs = m * np.sqrt(tau) if np.isfinite(m) else float("nan")
        dEtau = float(p["delta_V_relax_V"]) if np.isfinite(
            p["delta_V_relax_V"]) else float("nan")
        if np.isfinite(dEs) and np.isfinite(dEtau) and dEs != 0:
            D_relax = (4.0 / (9.0 * np.pi)) * (R ** 2 / tau) \
                * (dEtau / dEs) ** 2
            ratio = float(np.sqrt(D_relax / D_pulse)) \
                if np.isfinite(D_pulse) and D_pulse > 0 else float("nan")
        else:
            D_relax = ratio = float("nan")

        # ---- what the fit form changed on THIS pulse --------------
        if np.isfinite(m) and np.isfinite(m_lin) and m != 0:
            slope_ratio = float(m_lin / m)
            # D = R^2/tau_d with tau_d ~ m^2, so D_v2/D_v1 = (m_lin/m_quad)^2.
            # A LARGER drift-corrected slope means a SMALLER diffusivity --
            # the sign of this column is a finding, not a detail.
            D_ratio_vs_linear = float(slope_ratio ** 2)
        else:
            slope_ratio = D_ratio_vs_linear = float("nan")

        # ---- is the fitted linear term really the equilibrium drift? ---
        # Pure equilibrium drift would be dU/dt = U' * dSOC/dt with
        # dSOC/dt = I/Q_th (Q_th in A.s, so I/(Q_th*3600) in 1/s).  If
        # the fitted linear coefficient is far larger than that, the term
        # is carrying a slow NON-equilibrium transient, not the drift the
        # correction was designed for -- which is exactly what decides
        # the SIGN of the correction.
        dUdt_expected = (u_prime * I / (q_th * 3600.0)) \
            if np.isfinite(u_prime) else float("nan")
        if np.isfinite(b_drift) and np.isfinite(dUdt_expected) \
                and dUdt_expected != 0:
            drift_over_expected = float(b_drift / dUdt_expected)
        else:
            drift_over_expected = float("nan")

        if slope.get("outside_table"):
            flags.append(
                "SOC_mid outside the branch OCP table "
                f"({slope.get('table_soc_range')}) - no U' available"
            )
        if r2 < MIN_R2:
            flags.append(f"quadratic fit weak (R2={r2:.3f})")
        if np.isfinite(slope["curvature_mV"]) and \
                slope["curvature_mV"] > MAX_WINDOW_CURVATURE_MV:
            flags.append(
                "OCP not locally linear over the pulse step "
                f"({slope['curvature_mV']:.0f} mV across the window)"
            )
        accepted = (
            np.isfinite(D_pulse) and D_pulse > 0
            and r2 >= MIN_R2
            and not slope.get("outside_table", True)
            and np.isfinite(slope["curvature_mV"])
            and slope["curvature_mV"] <= MAX_WINDOW_CURVATURE_MV
            and np.sign(m) == np.sign(I * u_prime)
        )

        rows.append({
            "cycle": int(p["cycle"]),
            "pulse_id": int(p["pulse_id"]),
            "branch": branch,
            "SOC_start": float(p["SOC_start"]),
            "SOC_end": float(p["SOC_end"]),
            "SOC_mid": float(soc_mid),
            "I_A": I,
            "pulse_time_s": tau,
            "relax_time_s": float(p["relax_time_s"]),
            "capacity_increment_mAh": float(p["capacity_increment_mAh"]),
            "delta_V_pulse_mV": float(p["delta_V_pulse_V"]) * 1e3,
            "delta_V_relax_mV": dEtau * 1e3 if np.isfinite(dEtau)
            else float("nan"),
            "quad_sqrt_t_slope_V_per_sqrt_s": m,
            "quad_sqrt_t_slope_stderr": d_m,
            "quad_t_slope_V_per_s": b_drift,
            "quad_r2": r2,
            "linear_sqrt_t_slope_V_per_sqrt_s": m_lin,
            "linear_sqrt_t_r2": r2_lin,
            "slope_ratio_linear_over_quad": slope_ratio,
            "Ds_ratio_vs_linear": D_ratio_vs_linear,
            "dUdt_expected_V_per_s": dUdt_expected,
            "t_slope_over_expected_drift": drift_over_expected,
            "u_prime_V_per_soc": u_prime,
            "u_prime_knots": slope["n_knots"],
            "u_prime_halfwidth_soc": slope["halfwidth"],
            "u_prime_window_curvature_mV": slope["curvature_mV"],
            "Q_th_Ah": q_th,
            "R_m": R,
            "tau_d_s": tau_d if np.isfinite(tau_d) else float("nan"),
            "Ds_app_m2_s": D_pulse,
            "Ds_app_cm2_s": D_pulse * 1e4 if np.isfinite(D_pulse)
            else float("nan"),
            "Ds_app_rel_uncertainty": rel_u,
            "Ds_app_cm2_s_uncertainty": (
                D_pulse * 1e4 * rel_u
                if np.isfinite(D_pulse) and np.isfinite(rel_u) else float("nan")
            ),
            "Ds_app_relax_m2_s": D_relax,
            "Ds_app_relax_cm2_s": D_relax * 1e4 if np.isfinite(D_relax)
            else float("nan"),
            "relax_over_pulse_sqrt_ratio": ratio,
            "accepted": bool(accepted),
            "flags": "; ".join(flags),
        })

    pulses = pd.DataFrame(rows)
    ok = pulses["Ds_app_m2_s"].notna() & (pulses["Ds_app_m2_s"] > 0)
    ok = ok & pulses["accepted"]

    # ---- SOC-resolved table: identical binning to Phase B1 --------
    tab_rows: List[dict] = []
    for branch in ("lithiation", "delithiation"):
        sub = pulses[(pulses["branch"] == branch) & ok]
        if sub.empty:
            continue
        bins = np.round(sub["SOC_mid"] / 0.02) * 0.02
        for b in sorted(bins.unique()):
            g = sub[bins == b]
            if g.empty:
                continue
            med = float(g["Ds_app_m2_s"].median())
            lo = float(np.percentile(g["Ds_app_m2_s"], 25))
            hi = float(np.percentile(g["Ds_app_m2_s"], 75))
            tab_rows.append({
                "branch": branch,
                "SOC": float(b),
                "n_pulses": int(len(g)),
                "Ds_app_m2_s": med,
                "Ds_app_cm2_s": med * 1e4,
                "Ds_app_cm2_s_p25": lo * 1e4,
                "Ds_app_cm2_s_p75": hi * 1e4,
                "Ds_app_rel_uncertainty_median": float(
                    g["Ds_app_rel_uncertainty"].median()
                ),
                "Ds_app_cm2_s_uncertainty": float(
                    g["Ds_app_cm2_s_uncertainty"].median()
                ),
                "SOC_lo": float(g["SOC_mid"].min()),
                "SOC_hi": float(g["SOC_mid"].max()),
            })
    table = pd.DataFrame(tab_rows).sort_values(
        ["branch", "SOC"]).reset_index(drop=True) if tab_rows \
        else pd.DataFrame(columns=["branch", "SOC", "Ds_app_cm2_s"])

    # ---- the fit form's own effect, measured on these pulses ------
    both = pulses[ok & pulses["Ds_ratio_vs_linear"].notna()]
    drift = pulses[ok & pulses["t_slope_over_expected_drift"].notna()]
    same_sign = (np.sign(drift["quad_t_slope_V_per_s"])
                 == np.sign(drift["dUdt_expected_V_per_s"]))
    fit_effect = {
        "n_pulses": int(len(both)),
        "slope_ratio_linear_over_quad": _q(
            both["slope_ratio_linear_over_quad"]),
        "Ds_ratio_v2_over_v1": _q(both["Ds_ratio_vs_linear"]),
        "drift_term_over_expected_equilibrium_drift": _q(
            drift["t_slope_over_expected_drift"]),
        "drift_term_sign_matches_expected_fraction": (
            float(same_sign.mean()) if len(same_sign) else float("nan")
        ),
        "note": (
            "ratios of the first-order slope to the drift-corrected one on "
            "the SAME pulse samples.  D = R^2/tau_d with tau_d ~ m^2, so "
            "Ds_ratio = (slope ratio)^2 is exactly the factor by which the "
            "fit form alone moves the diffusivity -- and a ratio BELOW 1 "
            "means the correction makes D SMALLER.  The last two rows ask "
            "whether the fitted linear term is actually the EQUILIBRIUM "
            "drift the correction assumes: pure drift would be "
            "dU/dt = U'*I/Q_th, so a ratio far from 1 (or a sign that "
            "disagrees with it) means the term is carrying a slow "
            "NON-equilibrium transient instead."
        ),
    }

    provenance = {
        "calculation": "extraction/gitt_diffusivity_v2.py::compute_ds_app_v2",
        "quantity": (
            "APPARENT / EFFECTIVE solid-state diffusivity, NOT an "
            "intrinsic material coefficient: it is R^2 divided by a "
            "diffusion time constant fitted to a one-dimensional "
            "single-particle model of ONE particle size"
        ),
        "fit_form": FIT_DESCRIPTION,
        "fit_form_correction_vs_phase_B1": (
            "Phase B1 inverted the same law from a first-order V = a + "
            "m*sqrt(t) fit, which cannot represent the linear drift of "
            "the equilibrium voltage during the pulse.  Phase B1.5 "
            "measured that inflation as a median 2.9x on model pulses, "
            "while BOTH fits kept R^2 >= 0.95 -- so the Phase B1 R^2 gate "
            "cannot detect the wrong form, which is why the fit form had "
            "to be changed here rather than filtered on."
        ),
        "equation_reference": equation_reference,
        "equation_solved": (
            "tau_d = pi*(3 Q_th m / (2 I U'))**2 ; D = R^2/tau_d ; "
            "m from a least-squares fit of V = a + b*t + m*sqrt(t) over "
            "the pulse with the first samples removed"
        ),
        "shared_with_phase_B1": (
            "the inversion, the local OCP slope, the gates (R^2 >= "
            f"{MIN_R2}, |U'| >= {MIN_ABS_UPRIME}, window curvature <= "
            f"{MAX_WINDOW_CURVATURE_MV} mV, sign of I*U') and the 0.02 "
            "SOC binning are IMPORTED from extraction/gitt_diffusivity.py, "
            "so the B1 and B1.6 tables differ in exactly one thing: the "
            "fitted slope"
        ),
        "cross_check_equation": (
            "D = (4/(9 pi)) (R^2/tau) (dE_tau/dE_s)^2 -- OCP-free, "
            "obtained by eliminating U' between the pulse law and the "
            "equilibrium composition step"
        ),
        "particle_radius_m": R,
        "particle_radius_source": particle_radius_source,
        "Q_th_Ah": q_th,
        "Q_th_units": (
            "used in AMPERE-SECONDS in the Weppner-Huggins relation "
            "(Q_th = F eps_am c_max L A, as PyBOP builds it); the Ah "
            "value is converted by x3600"
        ),
        "Q_th_source": (
            "F * eps_am * c_max * L * A from the SINTEF catalog metadata "
            "of THIS GITT cell (mass-based eps_am, measured thickness "
            "and disc area) with c_max from the reference set"
        ),
        "active_mass_source": active_mass_source,
        "I_source": "GITT pulse current (canonical sign, discharge = +)",
        "U_prime_source": (
            "local slope of the frozen Phase B0.6 high-fidelity OCP "
            "table, branch-matched, fitted over ~1.5 pulse composition "
            "steps"
        ),
        "uncertainty_definition": (
            "Ds_app_rel_uncertainty = 2 * sigma(m)/|m| from the quadratic "
            "regression; it covers ONLY the fit noise.  Q_th, R, U' and "
            "the unmodelled porous-electrode contributions are systematic "
            "and are NOT included"
        ),
        "fit_effect_on_these_pulses": fit_effect,
        "n_pulses": int(len(pulses)),
        "n_defined": int((pulses["Ds_app_m2_s"].notna()
                          & (pulses["Ds_app_m2_s"] > 0)).sum()),
        "n_accepted": int(ok.sum()),
        "n_rejected": int(len(pulses) - ok.sum()),
        "flags": {
            "min_r2": MIN_R2,
            "min_abs_u_prime": MIN_ABS_UPRIME,
            "min_slope_knots": MIN_SLOPE_KNOTS,
        },
        "branch_note": (
            "lithiation pulses use the lithiation OCP branch and "
            "delithiation pulses the delithiation branch, so each D "
            "is paired with the same hysteresis branch the model uses"
        ),
        "wording": (
            "apparent/effective D_s(SOC) from GITT under the "
            "Weppner-Huggins single-particle model with the equilibrium "
            "drift separated from the diffusion signal; not a material "
            "constant, not validation"
        ),
    }
    return {"pulses": pulses, "table": table, "provenance": provenance}


def _q(series: pd.Series) -> Dict[str, float]:
    """
    Percentile summary of a ratio series.

    Signed on purpose: the sign of a ratio is itself a finding here
    (which way the fit form moved the value), so nothing is dropped
    except non-finite entries.
    """
    v = pd.to_numeric(series, errors="coerce")
    v = v[np.isfinite(v)]
    if v.empty:
        return {}
    return {
        f"p{q}": float(np.percentile(v, q))
        for q in (5, 25, 50, 75, 95)
    }


def write_ds_app_v2(
    result: Dict[str, object],
    out_dir: Path | str,
    *,
    extra_provenance: Optional[dict] = None,
) -> Dict[str, Path]:
    """
    Same file names and same table columns as Phase B1, so the Phase B1
    parameter-set builder (`parameters/sintef_graphite_ds.py`) can read
    a B1.6 table through a ``ds_dir`` argument without any change.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    pulses: pd.DataFrame = result["pulses"]      # type: ignore[assignment]
    table: pd.DataFrame = result["table"]        # type: ignore[assignment]
    paths["pulses"] = out / "gitt_ds_app_pulses.csv"
    pulses.to_csv(paths["pulses"], index=False)
    paths["table"] = out / "graphite_Ds_app.csv"
    table.to_csv(paths["table"], index=False)
    prov = dict(result["provenance"])            # type: ignore[arg-type]
    if extra_provenance:
        prov.update(extra_provenance)
    paths["provenance"] = out / "gitt_ds_app_provenance.json"
    with paths["provenance"].open("w", encoding="utf-8") as fh:
        json.dump(prov, fh, indent=2, ensure_ascii=False)
    return paths
