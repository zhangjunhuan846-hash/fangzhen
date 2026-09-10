#!/usr/bin/env python3
"""
Phase B0.7 probe 3: what does the model ACTUALLY start from?

Probe 2 showed V(0) departing from OCP(x0) as x0 shrinks
(x0=1e-4: OCP 1.6844 V but V(0) 2.1370 V).  Either the initial
concentration override is not reaching the model, or the OCP the model
evaluates is not the table I am comparing against.  This prints the
model's own state at t = 0.
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
OCP = "Positive electrode OCP [V]"

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

tables = load_ocp_tables(V2_DIR)
lith = tables["lithiation"].sort_values("SOC")
soc_t, vol_t = lith["SOC"].to_numpy(float), lith["Voltage"].to_numpy(float)

OPTIONS = {"working electrode": "positive"}
pv_probe = load_parameter_values(cap["lithiation"])
c_max = float(pv_probe[CMAX])
ocp_fn = pv_probe[OCP]

print("table-based OCP vs the model's OCP function:")
for x in (1e-3, 1e-4, 1e-5):
    node = ocp_fn(pybamm.Scalar(x))
    got = float(np.asarray(node.evaluate()).reshape(-1)[0])
    print(f"  x={x:.0e}  np.interp={np.interp(x, soc_t, vol_t):.4f}  "
          f"model OCP fn={got:.4f}")

print("\nmodel state at t = 0 (one 120 s solve):")
for x0 in (1e-3, 1e-4, 1e-5):
    pv = load_parameter_values(cap["lithiation"])
    pv[CONC] = x0 * c_max
    pv["Current function [A]"] = 4.328e-5
    print(f"  -- x0 = {x0:.0e}: set c_init = {pv[CONC]:.6g} "
          f"(= x0*c_max = {x0 * c_max:.6g})")
    model = build_model("SPM", options=OPTIONS)
    sim = pybamm.Simulation(model, parameter_values=pv)
    try:
        sol = sim.solve(t_eval=np.linspace(0.0, 120.0, 3))
    except Exception as exc:
        print(f"     solve FAILED: {type(exc).__name__}: "
              f"{str(exc)[:90]}")
        continue
    V = np.asarray(sol["Terminal voltage [V]"].entries, float).reshape(-1)
    xa = np.asarray(sol["X-averaged positive particle concentration "
                        "[mol.m-3]"].entries, float).reshape(-1) / c_max
    xs = np.asarray(sol["X-averaged positive particle surface concentration "
                        "[mol.m-3]"].entries, float).reshape(-1) / c_max
    print(f"     V(0)={V[0]:.4f}  x_avg(0)={xa[0]:.6e}  x_surf(0)={xs[0]:.6e}")
    print(f"     OCP(x_surf(0)) = {np.interp(xs[0], soc_t, vol_t):.4f} V  "
          f"-> implied overpotential = "
          f"{1e3 * (V[0] - np.interp(xs[0], soc_t, vol_t)):+.1f} mV")
