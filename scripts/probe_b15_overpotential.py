#!/usr/bin/env python3
"""
Phase B1.5 probe 1: can the model decompose the GITT pulse overpotential?

B1's conclusion was qualitative: "the single-particle model is the wrong
lens - porous-electrode, electrolyte and pseudo-OCP polarisation are all
being charged to solid diffusion".  This phase tests it quantitatively by
asking the model itself how much of a GITT pulse's overpotential is
actually solid diffusion.

If solid diffusion is a fraction f of the pulse overpotential, then
inverting the TOTAL as if it were all solid diffusion gives
    D_app = D_true * f^2
because the W-H signal scales as 1/sqrt(D).  With the B1 result
(D_app ~ 30x smaller than the reference) that predicts f ~ 0.18 - a
number this phase can check.

This probe just lists the candidate variables and their end-of-pulse
values on the real geometry.
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

from parameters.sintef_graphite_capacity import (                     # noqa: E402
    CAPACITY_MATCHED_IDS,
    register_capacity_variants,
)
from parameters.sintef_graphite_geometry import (                     # noqa: E402
    derive_geometry, read_structure, register as register_geometry,
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

pv = load_parameter_values(CAPACITY_MATCHED_IDS["lithiation"] + SUFFIX)
geom = derive_geometry(read_structure(CELL))
print("measured geometry of the GITT/Gr cell:")
for k, v in geom.items():
    if not isinstance(v, (dict, list)):
        print(f"  {k} = {v}")
print(f"  porosity (reference, not measured) = "
      f"{pv['Positive electrode porosity']}")
_brug = "Positive electrode Bruggeman coefficient (electrolyte)"
print(f"  brug_e (reference) = {pv.get(_brug, 'n/a')}")
print(f"  c_max = {pv[CMAX]} mol/m3")
print()

OPTIONS = {"working electrode": "positive"}
model = build_model("DFN", options=OPTIONS)
cands = [str(v) for v in model.variables.keys()]
keys = ("overpotential", "ohmic", "polarisation", "concentration",
        "potential", "surface concentration", "X-averaged positive")
print("candidate overpotential / loss variables:")
for v in sorted(cands):
    if any(k.lower() in v.lower() for k in keys) and "X-averaged" in v:
        print("   ", v)
print()

# a GITT pulse: 44.1545 uA for 1800 s from the pOCV-lith start state
I = 4.41545e-5
p = load_parameter_values(CAPACITY_MATCHED_IDS["lithiation"] + SUFFIX)
p[CONC] = 1e-3 * float(p[CMAX])
p["Current function [A]"] = I
for k in ("Ambient temperature [K]", "Initial temperature [K]"):
    if k in p:
        p[k] = 298.15

for name in ("SPM", "SPMe", "DFN"):
    m = build_model(name, options=OPTIONS)
    sim = pybamm.Simulation(m, parameter_values=p)
    try:
        sol = sim.solve(t_eval=np.linspace(0.0, 1800.0, 19))
    except Exception as exc:
        print(f"{name}: SOLVE FAILED {type(exc).__name__}: {str(exc)[:90]}")
        continue
    V = np.asarray(sol["Terminal voltage [V]"].entries, float).reshape(-1)
    print(f"{name}: V(0)={V[0]:.5f} -> V(1800s)={V[-1]:.5f} V  "
          f"|dV| = {1e3 * abs(V[-1] - V[0]):.2f} mV")
    for v in sorted(str(x) for x in m.variables.keys()):
        if "overpotential" in v.lower() and "X-averaged" in v:
            try:
                arr = np.asarray(sol[v].entries, float).reshape(-1)
                print(f"     {v:62s} end = {1e3 * arr[-1]:+8.2f} mV")
            except Exception:
                pass
