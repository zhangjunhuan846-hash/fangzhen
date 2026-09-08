"""Probe PyBaMM 26.8 handling of the author diffusivity-scaling key
and the default Simulation solver, to feed the H5 mapping audit."""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np

ROOT = "/mnt/c/Users/24330/WorkBuddy/仿真模拟"
REPO = os.path.join(ROOT, "external", "Jackowska-2025-JPS")

import pybamm  # noqa: E402

print("pybamm", pybamm.__version__)
root = os.path.dirname(pybamm.__file__)
print("root:", root)

# 1) find deprecated-key alias tables in the installed package
hits = []
for dirpath, _dirnames, filenames in os.walk(root):
    for fn in filenames:
        if fn.endswith(".py"):
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if "diffusivity scaling factor" in line:
                            hits.append((p, i, line.strip()[:160]))
            except OSError:
                pass
print("\n--- source lines mentioning 'diffusivity scaling factor' ---")
for p, i, ln in hits[:40]:
    print(f"{p.replace(root,'')}:{i}: {ln}")

# 2) construct the author ParameterValues and check which of the two
#    candidate keys it actually stores
sys.path.insert(0, REPO)
import Jackowska2025  # noqa: E402

pv = pybamm.ParameterValues(Jackowska2025.get_parameter_values_2mAh_cm2())
print("\n--- keys after construction ---")
for k in sorted(pv.keys()):
    if "scaling factor" in k or "diffusivity" in k.lower():
        print(" ", k, "=", pv[k])

# 3) default solver used by Simulation
try:
    sim = pybamm.Simulation(
        pybamm.lithium_ion.DFN({"working electrode": "positive"}),
        parameter_values=pv,
    )
    print("\nSimulation default solver:", type(sim.solver).__name__)
except Exception as exc:  # noqa: BLE001
    print("\nSimulation build failed:", type(exc).__name__, exc)

# 4) does build_model-style plain DFN (no options) still map to the
#    full-cell default?
m = pybamm.lithium_ion.DFN()
print("plain DFN options:", m.options.get_name_printable() if hasattr(m.options, "get_name_printable") else m.options)
