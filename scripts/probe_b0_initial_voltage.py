"""Debug: initial model voltage vs the variant's voltage window."""
import sys
from pathlib import Path

import numpy as np
import pybamm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset  # noqa: E402
from parameters.sintef_graphite_geometry import REFERENCE_SET  # noqa: E402
from parameters.sintef_graphite_ocp import (  # noqa: E402
    OCP_LITH_ID,
    load_ocp_tables,
    register_variants,
)

register_variants()
tables = load_ocp_tables()
a = get_dataset("sintef_graphite")

for rate in ("pOCV-lith", "pOCV-deli"):
    df = a.load_processed_discharge("4ccc47", rate)
    prov = df.attrs["provenance"]
    print(f"\n=== {rate}: rest OCV {prov['rest_ocv_V']:.4f} V | adapter x0 "
          f"{prov['initial_stoichiometry_from_ocp']:.4f} "
          f"({prov['initial_state_source']})")

tbl = tables["lithiation"].sort_values("SOC")
print("\nlith table: SOC", float(tbl.SOC.min()), "->", float(tbl.SOC.max()),
      "| V", float(tbl.Voltage.max()), "->", float(tbl.Voltage.min()))
print(tbl.head(4).to_string(index=False))

df = a.load_processed_discharge("4ccc47", "pOCV-lith")
x0_adapter = float(df.attrs["initialisation"]["stoichiometry_from_ocp"])

for set_id, x0 in ((REFERENCE_SET, x0_adapter), (OCP_LITH_ID, 0.005)):
    pv = pybamm.ParameterValues(set_id)
    cmax = pv["Maximum concentration in positive electrode [mol.m-3]"]
    pv["Initial concentration in positive electrode [mol.m-3]"] = x0 * cmax
    pv["Current function [A]"] = 43.28e-6
    model = pybamm.lithium_ion.SPM({"working electrode": "positive"})
    sim = pybamm.Simulation(model, parameter_values=pv)
    lo = pv["Lower voltage cut-off [V]"]
    hi = pv["Upper voltage cut-off [V]"]
    try:
        sol = sim.solve(t_eval=np.linspace(0, 60, 3))
        V = np.asarray(sol["Terminal voltage [V]"].entries, dtype=float)
        print(f"{set_id} (x0={x0:.5f}, window {lo}/{hi}): "
              f"V0 = {V[0]:.4f} V")
    except Exception as exc:  # noqa: BLE001
        print(f"{set_id} (x0={x0:.5f}, window {lo}/{hi}): FAILED "
              f"{type(exc).__name__}: {str(exc)[:110]}")
