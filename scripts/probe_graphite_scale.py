"""Quantify model vs SINTEF cell scale mismatch + preflight the SPM half-cell build."""
import numpy as np
import pybamm

SET = "Ecker2015_graphite_halfcell"
ps = pybamm.ParameterValues(SET)

area = ps["Electrode height [m]"] * ps["Electrode width [m]"]
thick = ps["Positive electrode thickness [m]"]
eps_am = ps["Positive electrode active material volume fraction"]
poro = ps["Positive electrode porosity"]
cmax = ps["Maximum concentration in positive electrode [mol.m-3]"]
rad = ps["Positive particle radius [m]"]
Q = ps["Nominal cell capacity [A.h]"]
F = pybamm.constants.F.value

Q_calc = area * thick * eps_am * cmax * F / 3600.0
print(f"model electrode area  : {area*1e4:.2f} cm2  (height {ps['Electrode height [m]']}, width {ps['Electrode width [m]']})")
print(f"model thickness       : {thick*1e6:.1f} um | porosity {poro:.3f} | eps_am {eps_am:.4f}")
print(f"model c_max           : {cmax:.0f} mol/m3 | radius {rad*1e6:.2f} um")
print(f"model Q (declared)    : {Q*1000:.3f} mAh")
print(f"model Q (computed)    : {Q_calc*1000:.3f} mAh")
print(f"model per-area Q      : {Q_calc/ (area*1e4) *1000:.3f} mAh/cm2")

SINTEF_AREA = np.pi * (1.4 / 2) ** 2
SINTEF_Q_MEAS = 1.942e-3
SINTEF_AREA_CAP = 1.4335
print()
print(f"SINTEF area (14 mm)   : {SINTEF_AREA:.3f} cm2")
print(f"SINTEF Q measured     : {SINTEF_Q_MEAS*1000:.3f} mAh | nominal areal {SINTEF_AREA_CAP} mAh/cm2")
print(f"area ratio model/cell : {area*1e4/SINTEF_AREA:.1f}x")
print(f"per-area Q ratio      : {(Q_calc/(area*1e4))/(SINTEF_Q_MEAS/SINTEF_AREA):.2f}x")

print()
print("=== SPM 半电池预验（工作电极=positive 槽位）===")
opts = {"working electrode": "positive"}
model = pybamm.lithium_ion.SPM(opts)
p2 = pybamm.ParameterValues(SET)
x0 = 0.98
p2["Initial concentration in positive electrode [mol.m-3]"] = x0 * cmax
p2["Current function [A]"] = -43.28e-6 * 0 + 43.28e-6 * 1000  # 43.28 mA = 1000x measured
sim = pybamm.Simulation(model, parameter_values=p2)
sol = sim.solve(t_eval=np.linspace(0, 3600, 20))
V = sol["Terminal voltage [V]"].entries
print(f"  solved OK | V start {V[0]:.4f} V end {V[-1]:.4f} V "
      f"(43.28 mA for 1 h)")
x = sol["X-averaged positive particle concentration [mol.m-3]"].entries / cmax
print(f"  x (stoich) start {x[0]:.4f} -> end {x[-1]:.4f}")
