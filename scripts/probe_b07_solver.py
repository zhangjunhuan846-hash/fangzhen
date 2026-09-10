#!/usr/bin/env python3
"""
Phase B0.7 probe 2: why does a very small initial Li fraction fail, and can
the solver be made to tolerate it?

x0 = 1e-3 -> V(0) = 1.077 V   (what the blind clip produces today)
x0 = 1e-4 -> V(0) = 2.186 V   (works)
x0 = 1e-5 -> V(0) ~ 1.80 V    (SolverError)
x0 = 1e-6 -> V(0) ~ 2.98 V    (SolverError)

If the failure is solver tolerance (the dilute stage is nearly vertical:
dV/dSOC ~ -2e4 V per unit SOC, so a 1e-6 change in x0 is a 20 mV change in
V) then it is tunable.  If it is the exchange current density going to
zero (j0 ~ sqrt(c_s)) then it is a physical degeneracy and the honest
answer is a documented floor plus a disclosed first-point exclusion.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
SUFFIX = "_v2"
CELL = "4ccc47"
CONC = "Initial concentration in positive electrode [mol.m-3]"
CMAX = "Maximum concentration in positive electrode [mol.m-3]"

from battery_sim.registry import get_dataset                          # noqa: E402
from parameters.sintef_graphite_capacity import register_capacity_variants  # noqa: E402
from parameters.sintef_graphite_geometry import register as register_geometry  # noqa: E402
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)

register_geometry(CELL)
register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)

import pybamm                                                          # noqa: E402
from battery_sim.models.pybamm_factory import (                        # noqa: E402
    build_model, load_parameter_values,
)

adapter = get_dataset("sintef_graphite")
tables = load_ocp_tables(V2_DIR)
lith = tables["lithiation"].sort_values("SOC")
soc = lith["SOC"].to_numpy(float)
vol = lith["Voltage"].to_numpy(float)
c_max = None

print("OCP interpolation at tiny x0 (the table's first segment):")
for x in (1e-3, 3e-4, 1e-4, 3e-5, 1e-5, 3e-6, 1e-6, 1e-7):
    v = float(np.interp(x, soc, vol))
    print(f"   x0 = {x:.0e}  ->  OCP = {v:.4f} V")

pv0 = load_parameter_values(cap["lithiation"])
c_max = float(pv0[CMAX])
print(f"\nc_max = {c_max:.2f} mol/m3  ->  c_s(x0) = x0 * c_max")
print(f"  j0 ~ sqrt(c_s):  sqrt(c_s(1e-3)) = {np.sqrt(1e-3 * c_max):.4f}, "
      f"sqrt(c_s(1e-6)) = {np.sqrt(1e-6 * c_max):.6f}  "
      f"({np.sqrt(1e-3 / 1e-6):.1f}x smaller)")

OPTIONS = {"working electrode": "positive"}

print("\n--- direct solve, 3 output points, default vs tight solver ---")
for tol in (None, 1e-8):
    print(f"  solver tolerance: {'default' if tol is None else tol:>8}")
    for x0 in (1e-3, 1e-4, 1e-5, 1e-6, 1e-7):
        pv = load_parameter_values(cap["lithiation"])
        pv[CONC] = x0 * c_max
        pv["Current function [A]"] = 4.328e-5
        model = build_model("SPM", options=OPTIONS)
        if tol is None:
            sim = pybamm.Simulation(model, parameter_values=pv)
        else:
            sim = pybamm.Simulation(
                model, parameter_values=pv,
                solver=pybamm.IDAKLUSolver(rtol=tol, atol=tol),
            )
        try:
            sol = sim.solve(t_eval=np.linspace(0.0, 120.0, 3))
            V = np.asarray(sol["Terminal voltage [V]"].entries,
                           float).reshape(-1)
            print(f"    x0={x0:.0e}  V(0)={V[0]:8.4f}  V(120s)={V[-1]:8.4f}  OK")
        except Exception as exc:
            msg = str(exc).replace("\n", " ")[:150]
            print(f"    x0={x0:.0e}  FAILED {type(exc).__name__}: {msg}")
