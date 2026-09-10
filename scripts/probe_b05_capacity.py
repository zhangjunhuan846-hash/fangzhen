#!/usr/bin/env python3
"""
Phase B0.5 probe: where does the model's electrode capacity actually come
from, and does scaling eps_am move it 1:1?

Questions
  1. which parameter keys carry the Li inventory (volume fractions, c_max)?
  2. does the geometric formula  Q = eps_am * L * A * c_max * F / 3600
     agree with a MEASURED dx/dt from an actual constant-current solve?
  3. how does the reference set's DECLARED nominal capacity compare?
  4. what does mutating eps_am do to the volume-fraction balance?
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pybamm  # noqa: E402

from parameters.sintef_graphite_geometry import (  # noqa: E402
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (  # noqa: E402
    OCP_DELI_ID,
    load_ocp_tables,
    register_variants,
)

F = 96485.33212

KEYS_OF_INTEREST = [
    "Electrode height [m]",
    "Electrode width [m]",
    "Positive electrode thickness [m]",
    "Positive electrode active material volume fraction",
    "Positive electrode porosity",
    "Positive electrode inactive material volume fraction",
    "Positive electrode volume fraction",
    "Maximum concentration in positive electrode [mol.m-3]",
    "Initial concentration in positive electrode [mol.m-3]",
    "Nominal cell capacity [A.h]",
    "Positive particle radius [m]",
    "Positive particle diffusivity [m2.s-1]",
    "Lower voltage cut-off [V]",
    "Upper voltage cut-off [V]",
]

print("=" * 78)
print("1. parameter keys")
print("=" * 78)
ref = pybamm.ParameterValues(REFERENCE_SET)
for k in KEYS_OF_INTEREST:
    present = k in ref
    val = ref[k] if present else None
    if isinstance(val, (int, float, np.floating)):
        print(f"  {k:60s} = {val!r}")
    else:
        print(f"  {k:60s} : {'MISSING' if not present else type(val).__name__}")

# any other key mentioning 'volume fraction' / 'porosity'
print("\n  -- all volume-fraction / porosity keys in the reference set --")
for k in ref.keys():
    kl = str(k).lower()
    if "volume fraction" in kl or "porosity" in kl:
        v = ref[k]
        print(f"     {k:62s} = {v!r}")

print()
print("=" * 78)
print("2. geometric capacity vs measured dx/dt")
print("=" * 78)


def geo_capacity_Ah(pv) -> float:
    area = float(pv["Electrode height [m]"]) * float(pv["Electrode width [m]"])
    return (
        float(pv["Positive electrode thickness [m]"])
        * float(pv["Positive electrode active material volume fraction"])
        * area
        * float(pv["Maximum concentration in positive electrode [mol.m-3]"])
        * F
        / 3600.0
    )


register_geometry()
register_variants()

for set_id in (REFERENCE_SET, GEOMETRY_PARAMETER_SET_ID, OCP_DELI_ID):
    pv = pybamm.ParameterValues(set_id)
    area = float(pv["Electrode height [m]"]) * float(pv["Electrode width [m]"])
    q_geo = geo_capacity_Ah(pv)
    q_decl = float(pv["Nominal cell capacity [A.h]"])
    print(f"  {set_id}")
    print(f"     area            = {area * 1e4:.4f} cm2")
    print(f"     thickness       = {float(pv['Positive electrode thickness [m]']) * 1e6:.2f} um")
    print(f"     eps_am          = {float(pv['Positive electrode active material volume fraction']):.6f}")
    print(f"     c_max           = {float(pv['Maximum concentration in positive electrode [mol.m-3]']):.1f} mol/m3")
    print(f"     Q geometric     = {q_geo * 1e3:.4f} mAh")
    print(f"     Q declared      = {q_decl * 1e3:.4f} mAh")
    print(f"     ratio geo/decl  = {q_geo / q_decl:.4f}")

# --- empirical: constant current, measure dx/dt -------------------
print("\n  -- empirical dx/dt with a constant current (SPM) --")
pv = pybamm.ParameterValues(GEOMETRY_PARAMETER_SET_ID)
c_max = float(pv["Maximum concentration in positive electrode [mol.m-3]"])
pv["Initial concentration in positive electrode [mol.m-3]"] = 0.5 * c_max
pv["Current function [A]"] = -43.28e-6      # negative = delithiation
I = -43.28e-6
model = pybamm.lithium_ion.SPM({"working electrode": "positive"})

print("     -- candidate state variables --")
for v in model.variables:
    vl = str(v).lower()
    if "stoichiometry" in vl or (
        "positive particle" in vl and "concentration" in vl
    ) or "total lithium" in vl:
        print(f"        {v}")

sim = pybamm.Simulation(model, parameter_values=pv)
t_eval = np.linspace(0.0, 3600.0, 11)
sol = sim.solve(t_eval=t_eval)


def _scalar(var: str) -> np.ndarray:
    arr = np.asarray(sol[var].entries, float)
    return np.squeeze(arr)


x_surf = _scalar(
    "X-averaged positive particle surface concentration [mol.m-3]"
) / c_max
x_avg = _scalar("Average positive particle stoichiometry")
n_li = _scalar("Total lithium in positive electrode [mol]")
eps_am = float(pv["Positive electrode active material volume fraction"])
L = float(pv["Positive electrode thickness [m]"])
area = float(pv["Electrode height [m]"]) * float(pv["Electrode width [m]"])
x_from_nli = n_li / (eps_am * L * area * c_max)
dt_s = float(t_eval[-1] - t_eval[0])


def _q_from(x):
    dx = float(x[-1] - x[0])
    return abs(I) * dt_s / 3600.0 / abs(dx), dx


q_surf, dx_surf = _q_from(x_surf)
q_avg, dx_avg = _q_from(x_avg)
q_nli, dx_nli = _q_from(x_from_nli)
q_geo = geo_capacity_Ah(pv)

print("     x(end) per definition:")
print(f"        surface       x {x_surf[0]:.6f} -> {x_surf[-1]:.6f}  (dx={dx_surf:+.6f})")
print(f"        volume-avg    x {x_avg[0]:.6f} -> {x_avg[-1]:.6f}  (dx={dx_avg:+.6f})")
print(f"        from n_Li     x {x_from_nli[0]:.6f} -> {x_from_nli[-1]:.6f}  (dx={dx_nli:+.6f})")
print(f"     Q from surface  dx/dt = {q_surf * 1e3:.4f} mAh "
      f"({100 * (q_surf / q_geo - 1):+.2f} % vs geometric)")
print(f"     Q from vol-avg  dx/dt = {q_avg * 1e3:.4f} mAh "
      f"({100 * (q_avg / q_geo - 1):+.2f} % vs geometric)")
print(f"     Q from n_Li     dx/dt = {q_nli * 1e3:.4f} mAh "
      f"({100 * (q_nli / q_geo - 1):+.2f} % vs geometric)")
print(f"     Q geometric           = {q_geo * 1e3:.4f} mAh")

print()
print("=" * 78)
print("3. volume-fraction balance when eps_am is scaled")
print("=" * 78)
print(f"  reference : eps_am + porosity = "
      f"{float(ref['Positive electrode active material volume fraction']) + float(ref['Positive electrode porosity']):.6f}")
g = pybamm.ParameterValues(GEOMETRY_PARAMETER_SET_ID)
print(f"  A.5       : eps_am + porosity = "
      f"{float(g['Positive electrode active material volume fraction']) + float(g['Positive electrode porosity']):.6f}")
for scale in (0.8823,):
    eps = float(g["Positive electrode active material volume fraction"]) * scale
    print(f"  x{scale}    : eps_am = {eps:.6f} -> sum with porosity = "
          f"{eps + float(g['Positive electrode porosity']):.6f}")

print()
print("=" * 78)
print("4. OCP tables near the ends (resolution check)")
print("=" * 78)
tables = load_ocp_tables()
for name, tbl in tables.items():
    t = tbl.sort_values("SOC")
    print(f"  {name}: SOC {t['SOC'].min():.4f}..{t['SOC'].max():.4f}, "
          f"V {t['Voltage'].min():.4f}..{t['Voltage'].max():.4f}, n={len(t)}")
    print(f"     first 4 rows:\n{t.head(4).to_string(index=False)}")
    print(f"     last 4 rows:\n{t.tail(4).to_string(index=False)}")
