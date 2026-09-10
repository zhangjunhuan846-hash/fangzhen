"""Decisive sign check: which PyBaMM current sign delithiates graphite?"""
import sys
from pathlib import Path

import numpy as np
import pybamm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parameters.sintef_graphite_geometry import build_parameter_values  # noqa: E402

model = pybamm.lithium_ion.SPM({"working electrode": "positive"})

for sign, label in ((+1.0, "+43 uA (canonical discharge)"),
                    (-1.0, "-43 uA (canonical charge)")):
    pv = build_parameter_values("4ccc47")
    cmax = pv["Maximum concentration in positive electrode [mol.m-3]"]
    pv["Initial concentration in positive electrode [mol.m-3]"] = 0.964 * cmax
    pv["Current function [A]"] = sign * 43.28e-6
    sim = pybamm.Simulation(model, parameter_values=pv)
    try:
        sol = sim.solve(t_eval=np.linspace(0, 7200, 25))
        V = np.asarray(sol["Terminal voltage [V]"].entries, dtype=float)
        c = np.asarray(
            sol["X-averaged positive particle concentration [mol.m-3]"].entries,
            dtype=float,
        )
        x = c.mean(axis=0) / cmax if c.ndim > 1 else c / cmax
        print(f"{label:32s} V {V[0]:.4f} -> {V[-1]:.4f} V | "
              f"x {float(x[0]):.4f} -> {float(x[-1]):.4f} | "
              f"{'LITHIATION' if x[-1] > x[0] else 'DELITHIATION'}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label:32s} stopped early: {type(exc).__name__}: {exc}")
