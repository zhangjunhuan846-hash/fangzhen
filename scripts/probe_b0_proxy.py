"""Debug: reproduce the driver's proxy path for the failing case."""
import sys
from pathlib import Path

import numpy as np
import pybamm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from battery_sim.registry import get_dataset  # noqa: E402
from parameters.sintef_graphite_ocp import (  # noqa: E402
    load_ocp_tables,
    register_variants,
    OCP_LITH_ID,
)
from graphite_phase_b0_compare import OCPConsistentAdapter  # noqa: E402

register_variants()
tables = load_ocp_tables()
adapter = get_dataset("sintef_graphite")

proxy = OCPConsistentAdapter(adapter, "lithiation", tables)
df = proxy.load_processed_discharge("4ccc47", "pOCV-lith")
x0 = float(df.attrs["initialisation"]["stoichiometry_from_ocp"])
print("proxy x0:", x0, "| mapping:", proxy.mapping_log)

pv = pybamm.ParameterValues(OCP_LITH_ID)
cmax = pv["Maximum concentration in positive electrode [mol.m-3]"]
pv["Initial concentration in positive electrode [mol.m-3]"] = x0 * cmax
pv["Current function [A]"] = 43.28e-6
t_exp = df["time_s"].to_numpy(float)[:5]
pv["Current function [A]"] = pybamm.Interpolant(
    t_exp, df["current_A"].to_numpy(float)[:5], pybamm.t
)
model = pybamm.lithium_ion.SPM({"working electrode": "positive"})
sim = pybamm.Simulation(model, parameter_values=pv)
print("initial concentration set to:", pv[
    "Initial concentration in positive electrode [mol.m-3]"
], "of cmax", cmax)
try:
    sol = sim.solve(t_eval=np.linspace(0, float(t_exp[-1]), 5))
    V = np.asarray(sol["Terminal voltage [V]"].entries, dtype=float)
    print("V0 =", V[0])
except Exception as exc:  # noqa: BLE001
    print("FAILED:", type(exc).__name__, str(exc)[:160])

# what does the OCP interpolant return at sto = 0 and at small sto?
ocp = pybamm.ParameterValues(OCP_LITH_ID)["Positive electrode OCP [V]"]
for sto in (0.0, 1e-4, 5e-4, 1e-3, 5e-3):
    expr = ocp(pybamm.Scalar(sto))
    print(f"  OCP(sto={sto:g}) = {float(expr.evaluate()):.4f} V")
