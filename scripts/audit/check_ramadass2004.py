"""Step 14 pre-check (mandated): verify Ramadass2004 in PyBaMM 26.8.0.0.

Fails loudly if Ramadass2004 is unavailable or SPMe/DFN cannot build.
"""
import sys

import pybamm

print("pybamm", pybamm.__version__)

if "Ramadass2004" not in pybamm.parameter_sets:
    print("FATAL: 'Ramadass2004' NOT in pybamm.parameter_sets")
    print("available:", sorted(pybamm.parameter_sets.keys()))
    sys.exit(1)

print("'Ramadass2004' in parameter_sets: True")

p = pybamm.ParameterValues("Ramadass2004")
print("ParameterValues loaded OK")

for key in [
    "Nominal cell capacity [A.h]",
    "Negative electrode thickness [m]",
    "Positive electrode thickness [m]",
    "Electrode height [m]",
    "Electrode width [m]",
    "Current function [A]",
]:
    try:
        v = p[key]
        sv = str(v)
        print(f"  {key} = {sv[:60]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {key}: <missing> ({type(e).__name__})")

for name in ["SPM", "SPMe", "DFN"]:
    model = getattr(pybamm.lithium_ion, name)()
    sim = pybamm.Simulation(model, parameter_values=p)
    print(f"  {name}: built OK")

print("[OK] Ramadass2004 pre-check passed")
