# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B1.1: APPARENT solid diffusivity D_s(SOC) from GITT
#
# NOT an intrinsic material property.  What comes out of a GITT
# analysis is a model-dependent, geometry-dependent, polydisperse-
# averaged value: it is the particle radius squared divided by a
# diffusion time constant fitted to a one-dimensional single-particle
# model.  It is reported as `apparent`/`effective`, never as
# "the diffusion coefficient".
#
# EQUATION (Weppner & Huggins, J. Electrochem. Soc. 124(10) 1569, 1977)
#   For a step that is short compared with the particle diffusion time
#   the surface stoichiometry of a spherical particle follows
#
#       sto_surf(t) = (2 I / (3 Q_th)) * sqrt(t * tau_d / pi)
#       V(t)        = U + U' * sto_surf(t)
#
#   with  Q_th = F * eps_am * c_max * L * A   [A.s]  (electrode capacity)
#         tau_d = R^2 / D                     [s]
#         U'   = dOCP/dsto                    [V]
#
#   This is EXACTLY the model PyBOP ships for GITT fitting
#   (pybop/models/lithium_ion/weppner_huggins.py, PyBOP 26.3), so the
#   forward relation is not invented here.  Inverting the fit
#
#       V(t) = a + m*sqrt(t)   ->   m = U' (2I/(3Q_th)) sqrt(tau_d/pi)
#       tau_d = pi * (3 Q_th m / (2 I U'))**2
#       D     = R^2 / tau_d
#
#   The slope m is obtained by least squares over the pulse with the
#   first IR_SKIP seconds removed (the ohmic jump is not diffusional).
#
# THREE THINGS THAT DECIDE WHETHER THE NUMBER MEANS ANYTHING
#   1. U' must come from the SAME OCP the model uses -- here the frozen
#      Phase B0.6 high-fidelity table, evaluated as a local slope over
#      about one pulse-composition step.
#   2. Q_th must belong to the cell that was measured, not to the
#      reference set.
#   3. Q_th, R and U' are all *sources of systematic, not statistical,
#      uncertainty*: they are reported with their provenance and are
#      NOT folded into the fit uncertainty.
#
# A SECOND, OCP-FREE ESTIMATOR IS REPORTED AS A CROSS-CHECK
#   Eliminating U' between the pulse law and the equilibrium step
#   (Delta sto = I tau / Q_th, Delta E_tau = U' Delta sto) gives
#
#       D = (4/(9 pi)) * (R^2 / tau) * (Delta E_tau / Delta E_s)^2
#
#   with Delta E_s = m sqrt(tau) (the diffusional part of the pulse
#   overpotential) and Delta E_tau the measured relaxation.  Agreement
#   between the two routes is evidence that the Weppner-Huggins regime
#   actually holds for that pulse; disagreement is reported, not hidden.
#
# This module imports numpy/pandas only -- never pybamm.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

FARADAY_C_MOL = 96485.33212

# reference-set particle radius: NOT measured for this cell
REFERENCE_RADIUS_SOURCE = (
    "Positive particle radius [m] of Ecker2015_graphite_halfcell "
    "(13.7 um) - a REFERENCE-SET value, NOT measured for this cell; "
    "D scales with R^2 so this is the largest systematic uncertainty"
)
EQUATION_REFERENCE = (
    "Weppner & Huggins, J. Electrochem. Soc. 124(10) 1569 (1977); "
    "forward relation identical to PyBOP 26.3 "
    "pybop/models/lithium_ion/weppner_huggins.py "
    "(V = U + U'*(2I/(3Q_th))*sqrt(t*tau_d/pi)), inverted here"
)

# a pulse is flagged when the sqrt(t) law does not describe it
MIN_R2 = 0.90
# minimum |U'| to avoid dividing by a flat OCP
MIN_ABS_UPRIME = 1e-3
# a window this curved means the OCP is not locally linear over the
# pulse step, where the Weppner-Huggins linearisation is not valid
MAX_WINDOW_CURVATURE_MV = 100.0
# minimum knots for the local slope fit (widened until reached)
MIN_SLOPE_KNOTS = 5
SLOPE_HALFWIDTH_FACTOR = 1.5


def _ascending(frame: pd.DataFrame) -> pd.DataFrame:
    s = frame.sort_values("SOC", kind="stable").reset_index(drop=True)
    keep = np.concatenate(([True], np.diff(s["SOC"].to_numpy(float)) > 0))
    return s.loc[keep].reset_index(drop=True)


def local_ocp_slope(
    table: pd.DataFrame,
    soc: float,
    *,
    halfwidth: float,
    min_knots: int = MIN_SLOPE_KNOTS,
) -> dict:
    """
    dOCP/dSOC at ``soc`` from a least-squares line through the table
    knots inside +/- ``halfwidth`` (widened until ``min_knots`` are in
    the window).  The window is set by the pulse's own composition
    step, so it adapts between the plateau and the steep stages.
    """
    s = _ascending(table)
    soc_arr = s["SOC"].to_numpy(float)
    v_arr = s["Voltage"].to_numpy(float)
    lo, hi = float(soc_arr[0]), float(soc_arr[-1])
    if not (lo <= soc <= hi):
        return {"slope": float("nan"), "n_knots": 0,
                "halfwidth": float("nan"), "r2": float("nan"),
                "curvature_mV": float("nan"), "outside_table": True,
                "table_soc_range": [lo, hi]}
    hw = float(halfwidth)
    for _ in range(60):
        sel = np.abs(soc_arr - soc) <= hw
        if sel.sum() >= min_knots:
            break
        hw *= 1.5
    n = int(sel.sum())
    if n < 2:
        return {"slope": float("nan"), "n_knots": n, "halfwidth": hw,
                "r2": float("nan"), "curvature_mV": float("nan")}
    x, y = soc_arr[sel], v_arr[sel]
    xm, ym = x.mean(), y.mean()
    sxx = float(np.sum((x - xm) ** 2))
    if sxx <= 0:
        return {"slope": float("nan"), "n_knots": n, "halfwidth": hw,
                "r2": float("nan"), "curvature_mV": float("nan")}
    slope = float(np.sum((x - xm) * (y - ym)) / sxx)
    resid = y - (ym + slope * (x - xm))
    sst = float(np.sum((y - ym) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / sst if sst > 0 else float("nan")
    return {
        "slope": slope,
        "n_knots": n,
        "halfwidth": float(hw),
        "outside_table": False,
        "table_soc_range": [lo, hi],
        "r2": r2,
        # spread of the window's voltage: a large value means the OCP is
        # far from locally linear there, where W-H is not valid
        "curvature_mV": float(np.ptp(y) * 1e3),
    }


def compute_ds_app(
    segments: pd.DataFrame,
    ocp_tables: Dict[str, pd.DataFrame],
    *,
    particle_radius_m: float,
    q_th_Ah: float,
    particle_radius_source: str = REFERENCE_RADIUS_SOURCE,
    active_mass_source: str = "",
    equation_reference: str = EQUATION_REFERENCE,
    cycles: Optional[List[int]] = None,
) -> Dict[str, object]:
    """
    Apparent D_s(SOC) for every GITT pulse.

    Returns {"pulses": DataFrame (one row per pulse),
             "table": DataFrame (SOC, Ds_app_cm2_s, uncertainty, ...),
             "provenance": dict}.
    """
    seg = segments.copy()
    if cycles is not None:
        seg = seg[seg["cycle"].isin(cycles)].copy()
    if seg.empty:
        raise ValueError("no GITT pulses selected")

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
        m = float(p["sqrt_t_slope_V_per_sqrt_s"])
        d_m = float(p["sqrt_t_slope_stderr"])
        r2 = float(p["sqrt_t_r2"])
        flags: List[str] = []

        if not np.isfinite(m) or m == 0 or not np.isfinite(u_prime) \
                or abs(u_prime) < MIN_ABS_UPRIME or I == 0:
            D_pulse = tau_d = rel_u = float("nan")
            flags.append("undefined: |U'| below threshold or no slope")
        else:
            # V = U + U' (2I/(3Q_th)) sqrt(t tau_d/pi)
            #   -> m = U' (2I/(3Q_th)) sqrt(tau_d/pi)
            # Q_th enters in AMPERE-SECONDS, exactly as PyBOP builds it
            # (Q_th = F * alpha * c_max * L * A [C = A.s]).  Using the
            # Ah value here is a 3600^2 error in tau_d and therefore
            # ~1e7 in D -- the forward-model test guards this.
            q_th_as = q_th * 3600.0
            tau_d = np.pi * (3.0 * q_th_as * m / (2.0 * I * u_prime)) ** 2
            D_pulse = R ** 2 / tau_d if tau_d > 0 else float("nan")
            rel_u = 2.0 * d_m / abs(m) if (np.isfinite(d_m) and m != 0) \
                else float("nan")

        # sign consistency: V must move the way I*U' says
        if np.isfinite(u_prime) and I != 0 and np.isfinite(m):
            if np.sign(m) != np.sign(I * u_prime):
                flags.append("sign: dV/dt direction disagrees with I*U'")

        # ---- OCP-free cross-check -------------------------------
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

        # expected equilibrium step from U' (consistency of the
        # relaxation with the frozen OCP)
        dEtau_expected = (u_prime * I * tau / 3600.0 / q_th
                          if np.isfinite(u_prime) else float("nan"))

        if slope.get("outside_table"):
            flags.append(
                "SOC_mid outside the branch OCP table "
                f"({slope.get('table_soc_range')}) - no U' available"
            )
        if r2 < MIN_R2:
            flags.append(f"sqrt(t) fit weak (R2={r2:.3f})")
        if np.isfinite(slope["curvature_mV"]) and \
                slope["curvature_mV"] > MAX_WINDOW_CURVATURE_MV:
            flags.append(
                f"OCP not locally linear over the pulse step "
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
            "dE_s_mV": dEs * 1e3 if np.isfinite(dEs) else float("nan"),
            "dE_tau_expected_mV": dEtau_expected * 1e3
            if np.isfinite(dEtau_expected) else float("nan"),
            "sqrt_t_slope_V_per_sqrt_s": m,
            "sqrt_t_slope_stderr": d_m,
            "sqrt_t_r2": r2,
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

    # ---- SOC-resolved table (median per SOC bin, both branches) ----
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

    provenance = {
        "calculation": "extraction/gitt_diffusivity.py::compute_ds_app",
        "quantity": (
            "APPARENT / EFFECTIVE solid-state diffusivity, NOT an "
            "intrinsic material coefficient: it is R^2 divided by a "
            "diffusion time constant fitted to a one-dimensional "
            "single-particle model of ONE particle size"
        ),
        "equation_reference": equation_reference,
        "equation_solved": (
            "tau_d = pi*(3 Q_th m / (2 I U'))**2 ; D = R^2/tau_d ; "
            "m from a least-squares fit of V = a + m*sqrt(t) over the "
            "pulse with the first samples removed"
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
            "Ds_app_rel_uncertainty = 2 * sigma(m)/|m| from the sqrt(t) "
            "regression; it covers ONLY the fit noise.  Q_th, R and U' "
            "contribute systematic uncertainty that is NOT included "
            "and is reported separately (D scales with R^2 and with "
            "Q_th^2/U'^2)"
        ),
        "n_pulses": int(len(pulses)),
        "n_defined": int((pulses["Ds_app_m2_s"].notna()
                          & (pulses["Ds_app_m2_s"] > 0)).sum()),
        "n_accepted": int(ok.sum()),
        "n_rejected": int(len(pulses) - ok.sum()),
        "flags": {
            "min_r2": MIN_R2,
            "min_abs_u_prime": MIN_ABS_UPRIME,
        },
        "branch_note": (
            "lithiation pulses use the lithiation OCP branch and "
            "delithiation pulses the delithiation branch, so each D "
            "is paired with the same hysteresis branch the model uses"
        ),
        "wording": (
            "apparent/effective D_s(SOC) from GITT under the "
            "Weppner-Huggins single-particle model; not a material "
            "constant, not validation"
        ),
    }
    return {"pulses": pulses, "table": table, "provenance": provenance}


def write_ds_app(
    result: Dict[str, object],
    out_dir: Path | str,
    *,
    extra_provenance: Optional[dict] = None,
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    pulses: pd.DataFrame = result["pulses"]  # type: ignore[assignment]
    table: pd.DataFrame = result["table"]    # type: ignore[assignment]
    paths["pulses"] = out / "gitt_ds_app_pulses.csv"
    pulses.to_csv(paths["pulses"], index=False)
    paths["table"] = out / "graphite_Ds_app.csv"
    table.to_csv(paths["table"], index=False)
    prov = dict(result["provenance"])  # type: ignore[arg-type]
    if extra_provenance:
        prov.update(extra_provenance)
    paths["provenance"] = out / "gitt_ds_app_provenance.json"
    with paths["provenance"].open("w", encoding="utf-8") as fh:
        json.dump(prov, fh, indent=2, ensure_ascii=False)
    return paths
