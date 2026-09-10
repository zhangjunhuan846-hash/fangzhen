# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B1.5: GITT pulse OVERPOTENTIAL BUDGET
#
# WHY THIS EXISTS
#   Phase B1 inverted each GITT pulse with the Weppner-Huggins (W-H)
#   single-particle law and got an apparent D_s that is ~30x smaller than
#   the reference value and spans five decades over SOC.  B1's conclusion
#   was qualitative: "the single-particle model is the wrong lens -
#   porous-electrode, electrolyte and pseudo-OCP polarisation are all
#   being charged to solid diffusion".
#
#   This module makes that quantitative.  The W-H inversion reads the
#   WHOLE pulse polarisation as if it were solid diffusion:
#
#       eta_total(t) = U' * (2I/(3 Q_th)) * sqrt(t * tau_s / pi)
#       =>  tau_s = pi * (3 Q_th m / (2 I U'))^2 ,  D_app = R^2 / tau_s
#
#   Writing f for the share of the pulse polarisation that actually IS
#   solid diffusion, the W-H signal scales as 1/sqrt(D), so inverting the
#   total instead of the solid part biases the result by
#
#       D_app = D_true * f^2
#
#   f = 1 is the regime the method claims; f << 1 is the regime this
#   dataset is in, and f^2 is then the missing factor.  B1 measured
#   D_app/D_ref ~ 1/30, which predicts f ~ 0.18 - a number the model can
#   be asked directly.
#
# HOW IT IS MEASURED (no fitting, no new parameters)
#   For a given state, run ONE pulse of the measured protocol on the
#   measured geometry and decompose the terminal voltage at the pulse end:
#
#       eta_total   = V            - OCP(x_avg)
#       eta_solid   = OCP(x_surf)  - OCP(x_avg)
#       eta_other   = eta_total    - eta_solid      (kinetics + electrolyte
#                                                    + ohmic, lumped)
#       f_solid     = |eta_solid| / |eta_total|
#
#   The equilibrium reference is OCP(x_avg) - i.e. the model's own volume
#   average - so the split needs no assumption beyond the frozen OCP
#   table.  A W-H prediction for eta_solid is computed alongside from
#   tau_s = R^2/D_model, which checks the closed form itself.
#
# This module imports pybamm LAZILY and is the ONE member of the
# extraction layer that needs it (the budget is defined by the model).
# Treating it as the "wrong lens" test is the whole point.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

FARADAY_C_MOL = 96485.33212

CONC_KEY = "Initial concentration in positive electrode [mol.m-3]"
CMAX_KEY = "Maximum concentration in positive electrode [mol.m-3]"
RADIUS_KEY = "Positive particle radius [m]"
THICKNESS_KEY = "Positive electrode thickness [m]"
POROSITY_KEY = "Positive electrode porosity"
BRUGG_KEY = "Positive electrode Bruggeman coefficient (electrolyte)"
DE_KEY = "Electrolyte diffusivity [m2.s-1]"

# NOTE on the particle variables: in PyBaMM the name "X-averaged ... particle
# concentration" is averaged over the electrode thickness x but is STILL
# resolved over the particle radius r (shape (n_r, n_t)).  The scalars this
# budget needs are "Average positive particle stoichiometry" (averaged over
# x AND r, the equilibrium reference) and "X-averaged positive particle
# surface stoichiometry" (the surface value, averaged over x).
VARS = {
    "V": "Terminal voltage [V]",
    "x_avg": "Average positive particle stoichiometry",
    "x_surf": "X-averaged positive particle surface stoichiometry",
    "D_eff": "X-averaged positive particle effective diffusivity [m2.s-1]",
    "eta_rxn": "X-averaged positive electrode reaction overpotential [V]",
    "eta_ele": "X-averaged electrolyte overpotential [V]",
    "c_e": "X-averaged positive electrolyte concentration [mol.m-3]",
    "eta_conc_particle": "Positive particle concentration overpotential [V]",
}
OPTIONAL_VARS = {
    "eta_conc": "X-averaged battery concentration overpotential [V]",
}
OPTIONAL_VARS = {
    "eta_conc": "X-averaged battery concentration overpotential [V]",
}

# D_e is deliberately NOT evaluated symbolically: every published lithium-ion
# set defines it through the electrolyte CONDUCTIVITY, itself a function of
# (c_e, T), so the expression cannot be evaluated outside a model context
# (NotImplementedError on the conductivity FunctionParameter).  The
# electrolyte's role is therefore MEASURED from the model instead of
# estimated from a literature diffusivity - which is stronger evidence.
ELECTROLYTE_TAU_NOTE = (
    "tau_electrolyte is NOT estimated: the reference set defines D_e via the "
    "electrolyte conductivity as a function of c_e, so it cannot be evaluated "
    "outside a model context.  The electrolyte's contribution is measured "
    "directly instead (dE_electrolyte_mV and dc_e_relative)."
)


def ocp_lookup(ocp_table: pd.DataFrame):
    """Linear OCP(stoichiometry) from the frozen table; scalar in, scalar
    out, array in, array out."""
    srt = ocp_table.sort_values("SOC")
    soc = srt["SOC"].to_numpy(float)
    vol = srt["Voltage"].to_numpy(float)

    def f(x):
        arr = np.asarray(x, dtype=float)
        out = np.interp(arr, soc, vol)
        return float(out) if arr.ndim == 0 else out

    return f


def sqrt_t_fits(
    t: np.ndarray, V: np.ndarray, *, tau: float, ir_skip_s: float = 60.0,
) -> Dict[str, float]:
    """
    What a Weppner-Huggins inversion would READ from this pulse.

    The W-H law assumes the pulse response is a sqrt(t) ramp on top of a
    constant equilibrium voltage.  It is not: over a pulse the
    volume-averaged stoichiometry advances linearly in time, so the
    equilibrium voltage drifts LINEARLY in t alongside the sqrt(t)
    diffusional term,

        V(t) = U(x0) + U'(I/Q_th) t                      (equilibrium)
               + U'(2I/(3Q_th)) sqrt(t tau_s/pi)          (diffusion)

    A two-parameter fit in sqrt(t) alone cannot separate those, and on
    graphite's steep stages the linear term dominates.  This returns

        dE_1term  = m1 sqrt(tau)   from  V = a + m1 sqrt(t)
        dE_2term  = m2 sqrt(tau)   from  V = a + b t + m2 sqrt(t)
        drift_mV  = |b| tau        the linear term's swing

    so the bias of the usual one-term read can be measured on a pulse
    whose true solid-diffusion overpotential is known from the model.
    """
    sel = np.asarray(t, dtype=float) >= float(ir_skip_s)
    tt = np.asarray(t, dtype=float)[sel]
    vv = np.asarray(V, dtype=float)[sel]
    if tt.size < 4:
        return {"dE_1term_mV": float("nan"), "dE_2term_mV": float("nan"),
                "drift_mV": float("nan"), "r2_1term": float("nan"),
                "r2_2term": float("nan"), "m1": float("nan"),
                "m2": float("nan"), "b": float("nan")}
    r = np.sqrt(tt)
    c1 = np.polyfit(r, vv, 1)
    res1 = vv - np.polyval(c1, r)
    r2_1 = 1.0 - float(res1.var() / vv.var()) if vv.var() > 0 else float("nan")
    A = np.column_stack([np.ones_like(r), tt, r])
    c2, *_ = np.linalg.lstsq(A, vv, rcond=None)
    res2 = vv - A @ c2
    r2_2 = 1.0 - float(res2.var() / vv.var()) if vv.var() > 0 else float("nan")
    root_tau = float(np.sqrt(float(tau)))
    return {
        "dE_1term_mV": abs(float(c1[0]) * root_tau) * 1e3,
        "dE_2term_mV": abs(float(c2[2]) * root_tau) * 1e3,
        "drift_mV": abs(float(c2[1]) * float(tau)) * 1e3,
        "r2_1term": r2_1,
        "r2_2term": r2_2,
        "m1": float(c1[0]),
        "m2": float(c2[2]),
        "b": float(c2[1]),
    }


def _series(sol, name: str, n_t: int) -> Optional[np.ndarray]:
    """
    A variable as a 1-D series over time.

    Variables that are still spatially resolved - e.g. the r-resolved
    particle concentration - are averaged over their spatial axes so the
    result is comparable with the scalar ones and always has one entry
    per time point.
    """
    try:
        arr = np.asarray(sol[name].entries, dtype=float)
    except Exception:  # noqa: BLE001 - variable may not exist for a model
        return None
    if arr.ndim == 1:
        series = arr
    else:
        if arr.shape[-1] != n_t and arr.shape[0] == n_t:
            arr = np.swapaxes(arr, 0, -1)
        series = arr.reshape(-1, arr.shape[-1]).mean(axis=0)
    if series.size != n_t and series.size > 0:
        series = np.interp(np.linspace(0.0, 1.0, n_t),
                           np.linspace(0.0, 1.0, series.size), series)
    return series


def pulse_budget(
    *,
    model_name: str,
    parameter_set: str,
    ocp_table: pd.DataFrame,
    soc_start: float,
    current_A: float,
    pulse_time_s: float,
    ambient_C: float = 25.0,
    n_eval: int = 181,
    ir_skip_s: float = 60.0,
    parameter_overrides: Optional[Dict[str, object]] = None,
) -> dict:
    """
    Run one GITT-like pulse from ``soc_start`` and decompose its
    polarisation.  Returns a flat dict of measurements plus provenance.

    ``ir_skip_s`` mirrors the B1 inversion: the sqrt(t) slope is fitted
    after the first ``ir_skip_s`` seconds, so the budget is compared at
    the same point.

    ``parameter_overrides`` exists so a caller can ask counterfactual
    questions ("what if D were 100x smaller?") without registering a new
    named set; it is used by the tests to check that the solid share of
    the polarisation responds to the diffusivity in the expected
    direction.
    """
    import pybamm

    from battery_sim.models.pybamm_factory import (
        build_model, load_parameter_values,
    )

    pv = load_parameter_values(parameter_set)
    c_max = float(pv[CMAX_KEY])
    pv[CONC_KEY] = float(soc_start) * c_max
    pv["Current function [A]"] = float(current_A)
    for k in ("Ambient temperature [K]", "Initial temperature [K]"):
        if k in pv:
            pv[k] = float(ambient_C) + 273.15
    for key, value in (parameter_overrides or {}).items():
        if key not in pv:
            raise KeyError(
                f"parameter set '{parameter_set}' has no key '{key}'; "
                f"refusing to add a parameter the model does not expect"
            )
        pv[key] = value

    model = build_model(model_name,
                        options={"working electrode": "positive"})
    sim = pybamm.Simulation(model, parameter_values=pv)
    sol = sim.solve(t_eval=np.linspace(0.0, float(pulse_time_s), int(n_eval)))

    t = np.asarray(sol.t, dtype=float)
    n_t = int(t.size)
    got: Dict[str, Optional[np.ndarray]] = {
        k: _series(sol, v, n_t) for k, v in VARS.items()
    }
    for k, v in OPTIONAL_VARS.items():
        got[k] = _series(sol, v, n_t)
    for k in ("V", "x_avg", "x_surf"):
        if got[k] is None:
            raise KeyError(f"model '{model_name}' has no variable for {k}")

    ocp = ocp_lookup(ocp_table)
    V, xa, xs = got["V"], got["x_avg"], got["x_surf"]
    ocp_avg = ocp(xa)
    ocp_surf = ocp(xs)

    eta_total = V - ocp_avg                 # total polarisation [V]
    eta_solid = ocp_surf - ocp_avg          # solid-diffusion part [V]
    end = -1
    # index closest to the end of the IR skip, for the sqrt(t) comparison
    k_ir = int(np.searchsorted(t, float(ir_skip_s)))

    R = float(pv[RADIUS_KEY])
    D_end = float(got["D_eff"][end]) if got["D_eff"] is not None \
        else float("nan")
    # Q_th in AMPERE-SECONDS, exactly as the W-H relation needs it:
    # Q_th = F * eps_am * c_max * L * A, which the capacity-matched set
    # publishes as its Nominal cell capacity (Phase B0.5 aligned it).
    q_th_as = float(pv["Nominal cell capacity [A.h]"]) * 3600.0
    tau_s = R ** 2 / D_end if np.isfinite(D_end) and D_end > 0 \
        else float("nan")

    # W-H prediction of the solid part from the model's OWN diffusivity
    u_prime = float("nan")
    try:
        srt = ocp_table.sort_values("SOC")
        s0, v0 = srt["SOC"].to_numpy(float), srt["Voltage"].to_numpy(float)
        hw = max(1e-3, 2.0 * abs(float(xa[end]) - float(xa[0])))
        sel = np.abs(s0 - float(xa[0])) <= hw
        if sel.sum() >= 2:
            u_prime = float(np.polyfit(s0[sel], v0[sel], 1)[0])
    except Exception:  # noqa: BLE001
        pass

    eta_solid_wh = (abs(u_prime) * (2 * abs(float(current_A))
                                    / (3 * q_th_as))
                    * np.sqrt(float(pulse_time_s) * tau_s / np.pi)
                    if np.isfinite(u_prime) and np.isfinite(tau_s)
                    else float("nan"))

    f_solid = (abs(float(eta_solid[end])) / abs(float(eta_total[end]))
               if abs(float(eta_total[end])) > 0 else float("nan"))

    # what the usual one-term sqrt(t) read would extract from this pulse,
    # and what a two-term (linear drift + sqrt t) read would
    fits = sqrt_t_fits(t, V, tau=float(pulse_time_s), ir_skip_s=ir_skip_s)
    dE_solid_mV = 1e3 * float(eta_solid[end])
    bias_1 = (dE_solid_mV / fits["dE_1term_mV"]) ** 2 \
        if abs(fits["dE_1term_mV"]) > 0 else float("nan")
    bias_2 = (dE_solid_mV / fits["dE_2term_mV"]) ** 2 \
        if abs(fits["dE_2term_mV"]) > 0 else float("nan")

    return {
        "model": model_name,
        "parameter_set": parameter_set,
        "soc_start": float(soc_start),
        "current_A": float(current_A),
        "pulse_time_s": float(pulse_time_s),
        "x_avg_start": float(xa[0]),
        "x_avg_end": float(xa[end]),
        "x_surf_end": float(xs[end]),
        "x_surf_excess": float(xs[end] - xa[end]),
        "OCP_avg_start_V": float(ocp_avg[0]),
        "OCP_avg_end_V": float(ocp_avg[end]),
        "V_start_V": float(V[0]),
        "V_end_V": float(V[end]),
        "dV_total_mV": 1e3 * float(V[end] - V[0]),
        "dE_equilibrium_mV": 1e3 * float(ocp_avg[end] - ocp_avg[0]),
        "dE_polarisation_mV": 1e3 * float(eta_total[end]),
        "dE_solid_mV": 1e3 * float(eta_solid[end]),
        "dE_other_mV": 1e3 * float(eta_total[end] - eta_solid[end]),
        "dE_reaction_mV": 1e3 * float(got["eta_rxn"][end])
        if got["eta_rxn"] is not None else float("nan"),
        "dE_electrolyte_mV": 1e3 * float(got["eta_ele"][end])
        if got["eta_ele"] is not None else float("nan"),
        "dE_concentration_var_mV": 1e3 * float(got["eta_conc"][end])
        if got.get("eta_conc") is not None else float("nan"),
        "dE_solid_pybamm_mV": 1e3 * float(got["eta_conc_particle"][end])
        if got.get("eta_conc_particle") is not None else float("nan"),
        "c_e_start_mol_m3": float(got["c_e"][0])
        if got["c_e"] is not None else float("nan"),
        "c_e_end_mol_m3": float(got["c_e"][end])
        if got["c_e"] is not None else float("nan"),
        "dc_e_mol_m3": float(got["c_e"][end] - got["c_e"][0])
        if got["c_e"] is not None else float("nan"),
        "dc_e_relative": float(
            (got["c_e"][end] - got["c_e"][0]) / got["c_e"][0])
        if got["c_e"] is not None and abs(float(got["c_e"][0])) > 0
        else float("nan"),
        "f_solid": float(f_solid),
        "D_bias_predicted": float(f_solid ** 2) if np.isfinite(f_solid)
        else float("nan"),
        # the fit-form diagnosis: what a W-H read of THIS pulse returns
        **fits,
        "D_bias_of_1term_fit": float(bias_1),
        "D_bias_of_2term_fit": float(bias_2),
        "dE_solid_over_dE_1term": (
            float(dE_solid_mV / fits["dE_1term_mV"])
            if abs(fits["dE_1term_mV"]) > 0 else float("nan")
        ),
        "dE_solid_over_dE_2term": (
            float(dE_solid_mV / fits["dE_2term_mV"])
            if abs(fits["dE_2term_mV"]) > 0 else float("nan")
        ),
        "R_m": R,
        "D_eff_at_end_m2_s": D_end,
        "tau_solid_s": tau_s,
        "Fourier_solid": float(D_end * float(pulse_time_s) / R ** 2)
        if np.isfinite(D_end) else float("nan"),
        "u_prime_V_per_soc": u_prime,
        "Q_th_As": float(q_th_as),
        "dE_solid_WH_predicted_mV": 1e3 * eta_solid_wh
        if np.isfinite(eta_solid_wh) else float("nan"),
        "dE_polarisation_at_ir_skip_mV": 1e3 * float(eta_total[k_ir]),
        "n_eval": int(n_eval),
        "ir_skip_s": float(ir_skip_s),
    }


def timescales(
    *,
    parameter_set: str,
    R_m: float,
    L_m: float,
    porosity: float,
    brug: float,
    d_solid_m2_s: float,
    d_solid_gitt_median_m2_s: float,
    t_pulse_s: float,
    d_electrolyte_m2_s: Optional[float] = None,
) -> Dict[str, object]:
    """
    The clocks that decide which process limits a GITT pulse:

      tau_pulse     the protocol
      tau_solid     R^2 / D_s            (particle)
      tau_elyte     L^2 / D_e_eff        (electrode cross-section),
                    D_e_eff = D_e * eps^brug

    The W-H short-time law needs t << tau_solid.  ``d_electrolyte_m2_s``
    is optional on purpose: no published set can supply it outside a model
    context (see ELECTROLYTE_TAU_NOTE), so the electrolyte's role is
    measured in ``pulse_budget`` rather than estimated here.
    """
    out: Dict[str, object] = {
        "L_m": float(L_m),
        "porosity": float(porosity),
        "bruggeman": float(brug),
        "tau_pulse_s": float(t_pulse_s),
        "tau_solid_at_reference_D_s": (
            R_m ** 2 / float(d_solid_m2_s)
            if np.isfinite(d_solid_m2_s) and d_solid_m2_s > 0
            else float("nan")
        ),
        "tau_solid_at_the_gitt_median_D_s": (
            R_m ** 2 / float(d_solid_gitt_median_m2_s)
            if np.isfinite(d_solid_gitt_median_m2_s)
            and d_solid_gitt_median_m2_s > 0 else float("nan")
        ),
        "electrolyte_tau_note": ELECTROLYTE_TAU_NOTE,
        "note": (
            "tau_solid uses R from the reference set (not measured of this "
            "material) - a systematic caveat"
        ),
    }
    if d_electrolyte_m2_s is not None and d_electrolyte_m2_s > 0:
        d_e_eff = float(d_electrolyte_m2_s) * float(porosity) ** float(brug)
        out["electrolyte_diffusivity_m2_s"] = float(d_electrolyte_m2_s)
        out["electrolyte_eff_diffusivity_m2_s"] = d_e_eff
        out["tau_electrolyte_s"] = L_m ** 2 / d_e_eff
    else:
        out["electrolyte_diffusivity_m2_s"] = float("nan")
        out["electrolyte_eff_diffusivity_m2_s"] = float("nan")
        out["tau_electrolyte_s"] = float("nan")
    for key in ("tau_solid_at_reference_D_s",
                "tau_solid_at_the_gitt_median_D_s", "tau_electrolyte_s"):
        tau = out[key]
        out[f"Fo_pulse_over_{key}"] = (
            float(t_pulse_s) / tau if np.isfinite(tau) and tau > 0
            else float("nan")
        )
    return out


def write_budget(result: Dict[str, object], out_dir: Path | str) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "gitt_pulse_budget.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    return path
