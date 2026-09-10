#!/usr/bin/env python3
"""
Phase B0.7 probe: how much does the initial-Li-fraction floor cost?

Chain of events for the p-OCV LITHIATION window (graphite||Li):
  * measured pre-branch rest OCV        = 3.0161 V
  * frozen v2 lithiation OCP table top  = 3.0003 V   (SOC = 0)
  -> the rest OCV lies 15.8 mV ABOVE the table, so the physical initial
     state is the TABLE EDGE (x0 -> 0+), which the adapter duly flags as
     `ocp_table_edge_fallback`
  -> the analysis proxy then does np.clip(x0, 1e-3, 1-1e-3), which moves
     the state INTO the dilute stage.  That stage is near vertical
     (3.0003 V -> 1.7865 V within SOC 6.2e-5), so x0 = 1e-3 puts the model
     at V(0) = 1.077 V while the experiment starts at 3.016 V.

This probe scans the floor and reports, for each value: V(0), whether the
solve survives, the replay RMSE/MAE, coverage, and the residual in the
band the platform labels `V_exp > 1.43 V` (which is where the 1.9 V
initial-state error shows up).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
SUFFIX = "_v2"
CELL = "4ccc47"
RATE = "pOCV-lith"

import scripts.graphite_phase_b0_compare as b0                       # noqa: E402
from battery_sim.registry import get_dataset                          # noqa: E402
from parameters.sintef_graphite_capacity import register_capacity_variants  # noqa: E402
from parameters.sintef_graphite_geometry import register as register_geometry  # noqa: E402
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)
from scripts.graphite_phase_b05_compare import _metrics               # noqa: E402

register_geometry(CELL)
register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)

adapter = get_dataset("sintef_graphite")
tables = load_ocp_tables(V2_DIR)
lith = tables["lithiation"].sort_values("SOC")
print("v2 lithiation table (first 4 rows, and the top of the table):")
print(lith.head(4)[["SOC", "Voltage"]].to_string(index=False))
print(f"  table SOC range = [{lith.SOC.min():.6g}, {lith.SOC.max():.6g}]")
print(f"  table V   range = [{lith.Voltage.min():.4f}, {lith.Voltage.max():.4f}]")
print(f"  first-segment dV/dSOC = "
      f"{(lith.Voltage.iloc[1] - lith.Voltage.iloc[0]) / (lith.SOC.iloc[1] - lith.SOC.iloc[0]):.0f} V per unit SOC")
print()

base = b0.OCPConsistentAdapter(adapter, "lithiation", tables)
df = base.load_processed_discharge(CELL, RATE)
v0 = float(df.attrs["provenance"]["rest_ocv_V"])
print(f"measured pre-branch rest OCV = {v0:.4f} V  ->  "
      f"{1e3 * (v0 - float(lith.Voltage.max())):+.1f} mV vs the table top")
print(f"adapter x0 (reference-table edge fallback) = "
      f"{df.attrs['initialisation']['stoichiometry_from_ocp']}")
print()

from battery_sim.simulation.baseline import run_baseline_cell          # noqa: E402
from scripts.graphite_phase_b05_compare import _region_mae             # noqa: E402

print(f"{'floor':>9} {'x0':>11} {'V(0) [V]':>9} {'RMSE':>8} {'MAE':>7} "
      f"{'cov':>5} {'n':>5} {'RMSE>1.43V band':>16} {'t [s]':>6}")
for floor in (1e-3, 3e-4, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8):
    b0.X0_MARGIN = floor
    px = b0.OCPConsistentAdapter(adapter, "lithiation", tables)
    t0 = time.perf_counter()
    try:
        res = run_baseline_cell(px, model_name="SPM", cell=CELL, rate=RATE,
                                parameter_set=cap["lithiation"], plot=False,
                                quiet=True)
    except Exception as exc:
        print(f"{floor:>9.0e} {'--':>11} {'--':>9} {'--':>8} {'--':>7} "
              f"{'--':>5} {'--':>5} {'--':>16} SOLVE FAILED "
              f"{type(exc).__name__}")
        continue
    dt = time.perf_counter() - t0
    csv = Path(res["output_dir"]) / f"{RATE.replace('-', '')}_time_aligned.csv"
    m = _metrics(csv)
    reg = _region_mae(csv)
    x0 = float(px.mapping_log[-1]["x0"])
    band = reg["V_exp>1.43_outside_ref_table"]
    print(f"{floor:>9.0e} {x0:>11.3e} {m['v_sim_start_V']:>9.4f} "
          f"{m['rmse_mV']:>8.3f} {m['mae_mV']:>7.3f} "
          f"{m['n_points'] / 2000.0:>5.3f} "
          f"{m['n_points']:>5d} "
          f"{band['mae_mV']:>10.1f} (n={band['n_points']:>2d}) "
          f"{dt:>6.1f}")
b0.X0_MARGIN = 1e-3
print()
print("(cov = n_points / 2000, i.e. how much of the window the run survived)")
