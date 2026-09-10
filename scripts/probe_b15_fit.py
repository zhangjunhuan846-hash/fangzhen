#!/usr/bin/env python3
"""
Phase B1.5 probe 2: is the sqrt(t) fit contaminated by the equilibrium drift?

The W-H inversion fits V = a + m*sqrt(t) over the pulse and reads m as the
diffusional signal.  But over a pulse the volume-averaged stoichiometry
advances linearly in time, so the EQUILIBRIUM voltage drifts LINEARLY in t:

    V(t) = U(x0) + U' (I/Q_th) t          <- equilibrium drift, linear in t
           + U' (2I/(3Q_th)) sqrt(t tau_s/pi)   <- diffusion, sqrt(t)

A two-parameter fit in sqrt(t) alone cannot separate them, and on graphite's
steep stages the linear term is the bigger one.  This probe checks it on the
model's OWN pulse, where the true solid-diffusion overpotential is known:

  fit 1: V = a + m sqrt(t)      -> dE_1term = m sqrt(tau)
  fit 2: V = a + b t + m sqrt(t) -> dE_2term = m sqrt(tau)

and compares both with the model's actual eta_solid = OCP(x_surf) - OCP(x_avg).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
SUFFIX = "_v2"
CELL = "063b77"

from extraction.gitt_pulse_budget import VARS, ocp_lookup, _series   # noqa: E402
from parameters.sintef_graphite_capacity import (                     # noqa: E402
    CAPACITY_MATCHED_IDS, register_capacity_variants,
)
from parameters.sintef_graphite_geometry import (                     # noqa: E402
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)

register_geometry(CELL)
register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
register_capacity_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)

import pybamm                                                          # noqa: E402
from battery_sim.models.pybamm_factory import (                        # noqa: E402
    build_model, load_parameter_values,
)

SET = CAPACITY_MATCHED_IDS["lithiation"] + SUFFIX
tables = load_ocp_tables(V2_DIR)
ocp = ocp_lookup(tables["lithiation"])
pv0 = load_parameter_values(SET)
c_max = float(pv0["Maximum concentration in positive electrode [mol.m-3]"])
CONC = "Initial concentration in positive electrode [mol.m-3]"

I = 4.415e-5
TAU = 1800.0
IR_SKIP = 60.0

print(f"{'SOC':>5} {'dE_solid':>9} {'dE_1term':>9} {'dE_2term':>9} "
      f"{'b(fit2)':>10} {'drift':>8} {'r2_1':>6} {'r2_2':>6}")
for soc in (0.1, 0.3, 0.5, 0.7, 0.9):
    pv = load_parameter_values(SET)
    pv[CONC] = soc * c_max
    pv["Current function [A]"] = I
    for k in ("Ambient temperature [K]", "Initial temperature [K]"):
        if k in pv:
            pv[k] = 298.15
    sim = pybamm.Simulation(
        build_model("SPMe", options={"working electrode": "positive"}),
        parameter_values=pv)
    sol = sim.solve(t_eval=np.linspace(0.0, TAU, 181))
    t = np.asarray(sol.t, float)
    n_t = t.size
    V = _series(sol, VARS["V"], n_t)
    xa = _series(sol, VARS["x_avg"], n_t)
    xs = _series(sol, VARS["x_surf"], n_t)
    dE_solid = abs(ocp(xs[-1]) - ocp(xa[-1])) * 1e3

    sel = t >= IR_SKIP
    tt, vv = t[sel], V[sel]
    r = np.sqrt(tt)
    # fit 1: a + m sqrt(t)
    c1 = np.polyfit(r, vv, 1)
    dE1 = abs(c1[0] * np.sqrt(TAU)) * 1e3
    res1 = vv - np.polyval(c1, r)
    r2_1 = 1 - res1.var() / vv.var()
    # fit 2: a + b t + m sqrt(t)
    A = np.column_stack([np.ones_like(r), tt, r])
    c2, *_ = np.linalg.lstsq(A, vv, rcond=None)
    dE2 = abs(c2[2] * np.sqrt(TAU)) * 1e3
    res2 = vv - A @ c2
    r2_2 = 1 - res2.var() / vv.var()
    drift = abs(c2[1] * TAU) * 1e3
    print(f"{soc:>5.2f} {dE_solid:>9.3f} {dE1:>9.3f} {dE2:>9.3f} "
          f"{c2[1]:>10.3e} {drift:>8.1f} {r2_1:>6.4f} {r2_2:>6.4f}")
print()
print("dE in mV; 'drift' is the linear-term swing over the pulse, in mV")
print("dE_solid is the model's TRUE solid-diffusion overpotential")
