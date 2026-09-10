#!/usr/bin/env python3
"""
Phase B2 probe: runtime cost + the first sensitivity signal.

Runs the pOCV replay at two extreme prescribed D values (one near the
reference-set level, one at the GITT median) so the full sweep can be
sized before it is launched.
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
V2_SUFFIX = "_v2"
CELL = "4ccc47"

from battery_sim.registry import get_dataset                       # noqa: E402
from parameters.sintef_graphite_capacity import register_capacity_variants  # noqa: E402
from parameters.sintef_graphite_ds_sweep import (                  # noqa: E402
    KEY_RADIUS, build_constant_d_variant, register_constant_d_sweep,
    fourier_number, tau_d_s,
)
from parameters.sintef_graphite_geometry import register as register_geometry  # noqa: E402
from parameters.sintef_graphite_ocp import (                       # noqa: E402
    load_ocp_tables, register_variants,
)
from scripts.graphite_phase_b0_compare import OCPConsistentAdapter  # noqa: E402
from scripts.graphite_phase_b05_compare import _metrics             # noqa: E402

register_geometry(CELL)
register_variants(CELL, V2_DIR, set_id_suffix=V2_SUFFIX)
cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=V2_SUFFIX)
sweep = register_constant_d_sweep(
    CELL, values=[1e-14, 3.8e-16], ocp_dir=V2_DIR, set_id_suffix=V2_SUFFIX,
    sweep_root=ROOT / "outputs" / "analysis" / "graphite_phaseB2" / "_probe",
)
print("capacity sets:", cap)
print("sweep sets:", {k: v for k, v in sweep.items()})

import pybamm                                                        # noqa: E402

_b, pv, _i = build_constant_d_variant("lithiation", 1e-14, CELL,
                                      ocp_dir=V2_DIR,
                                      set_id_suffix=V2_SUFFIX)
R = float(pv[KEY_RADIUS])
Q_NOM = float(pv["Nominal cell capacity [A.h]"])
print(f"\nR = {R*1e6:.3f} um | Q_nom = {Q_NOM*1e3:.4f} mAh")
print("reference-set D (Ecker median) = 1.22e-14 m2/s")
for d in (1e-13, 1e-14, 1e-15, 3.8e-16, 1e-16):
    print(f"  D={d:8.2e}  tau_d={tau_d_s(d, R)/3600.0:9.2f} h"
          f"   Fo(41.3h pOCV)={fourier_number(d, R, 148521.0):8.3f}"
          f"   Fo(2C 0.5h)={fourier_number(d, R, 1800.0):8.4f}")

adapter = get_dataset("sintef_graphite")
tables = load_ocp_tables(V2_DIR)

print("\n--- pOCV-lith window initial state (v2 proxy) ---")
proxy = OCPConsistentAdapter(adapter, "lithiation", tables)
df = proxy.load_processed_discharge(CELL, "pOCV-lith")
pv_meta = df.attrs["provenance"]
print("rest_ocv_V:", pv_meta["rest_ocv_V"], "| x0:", pv_meta["initial_stoichiometry_from_ocp"])
print("duration_s:", pv_meta["duration_s"], "| median I:", pv_meta["median_current_A"])
print("c_rate:", pv_meta["c_rate"], "| c_rate_measured:", pv_meta["c_rate_measured_from_data"])

from battery_sim.simulation.baseline import run_baseline_cell       # noqa: E402

for rate in ("pOCV-lith", "pOCV-deli"):
    branch = "lithiation" if rate.endswith("lith") else "delithiation"
    for d in (1e-14, 3.8e-16):
        px = OCPConsistentAdapter(adapter, branch, tables)
        sid = sweep[(branch, d)]
        t0 = time.perf_counter()
        res = run_baseline_cell(px, model_name="SPM", cell=CELL, rate=rate,
                                parameter_set=sid, plot=False, quiet=True)
        dt = time.perf_counter() - t0
        csv = Path(res["output_dir"]) / f"{rate.replace('-', '')}_time_aligned.csv"
        m = _metrics(csv)
        print(f"{rate:10s} D={d:8.2e} RMSE={m['rmse_mV']:8.3f} mV "
              f"MAE={m['mae_mV']:8.3f} n={m['n_points']:5d} "
              f"Vsim={m['v_sim_start_V']:.4f}->{m['v_sim_end_V']:.4f} "
              f"span={m['v_sim_span_mV']:8.2f} mV [{dt:.1f} s]")
