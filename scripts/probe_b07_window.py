#!/usr/bin/env python3
"""
Phase B0.7 probe 5: window-start rule ON vs OFF.

Rule (declared, parameter-based, pre-registered): the model's terminal
voltage at the declared initial state is OCP(x0); measured samples on the
FAR side of that value - relative to the direction the window traverses -
are outside the model's admissible state space and are removed as a
prefix, with the removal recorded.

Expected: the p-OCV LITHIATION window loses ~18 points / 160 s (0.1 %),
and the single-point 1939 mV initial-state residual disappears, which is
what dominated its 44.74 mV RMSE.  The delithiation window loses only the
~60 s rest tail (its own ~14 mV version of the same defect).
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

import scripts.graphite_phase_b0_compare as b0                       # noqa: E402
from battery_sim.registry import get_dataset                          # noqa: E402
from parameters.sintef_graphite_capacity import register_capacity_variants  # noqa: E402
from parameters.sintef_graphite_geometry import register as register_geometry  # noqa: E402
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)
from scripts.graphite_phase_b05_compare import _metrics, _region_mae  # noqa: E402
from battery_sim.simulation.baseline import run_baseline_cell         # noqa: E402

register_geometry(CELL)
register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
adapter = get_dataset("sintef_graphite")
tables = load_ocp_tables(V2_DIR)

WINDOWS = (("lithiation", "pOCV-lith"), ("delithiation", "pOCV-deli"))


def run(model, branch, rate, trim):
    px = b0.OCPConsistentAdapter(adapter, branch, tables,
                                 trim_unrepresentable_prefix=trim)
    res = run_baseline_cell(px, model_name=model, cell=CELL, rate=rate,
                            parameter_set=cap[branch], plot=False,
                            quiet=True)
    csv = Path(res["output_dir"]) / f"{rate.replace('-', '')}_time_aligned.csv"
    return _metrics(csv), _region_mae(csv), px.window_trim_log[-1]


print(f"{'model':5} {'window':10} {'rule':4} {'n':>5} {'RMSE':>8} {'MAE':>7} "
      f"{'max|res|':>9} {'removed pts':>11} {'removed s':>10} "
      f"{'V(0) sim':>9}")
for model in ("SPM", "SPMe"):
    for branch, rate in WINDOWS:
        rows = {}
        for trim in (False, True):
            m, reg, trimrec = run(model, branch, rate, trim)
            rows[trim] = (m, reg, trimrec)
            print(f"{model:5} {rate:10} {'ON' if trim else 'off':4} "
                  f"{m['n_points']:>5} {m['rmse_mV']:>8.3f} "
                  f"{m['mae_mV']:>7.3f} {m['max_abs_mV']:>9.1f} "
                  f"{trimrec['n_points_removed']:>11} "
                  f"{trimrec['duration_removed_s']:>10.1f} "
                  f"{m['v_sim_start_V']:>9.4f}")
        a, b = rows[False][0], rows[True][0]
        print(f"{'':5} {'':10} {'delta':4} {'':5} "
              f"{b['rmse_mV'] - a['rmse_mV']:>+8.3f} "
              f"{b['mae_mV'] - a['mae_mV']:>+7.3f} "
              f"{b['max_abs_mV'] - a['max_abs_mV']:>+9.1f}")
        for label, _lo, _hi in b0.REGIONS:
            o = rows[False][1][label]
            n = rows[True][1][label]
            print(f"{'':5} {'':10} {'':4} region {label:16s} "
                  f"MAE {o['mae_mV']:>9.3f} (n={o['n_points']:>3}) -> "
                  f"{n['mae_mV']:>9.3f} (n={n['n_points']:>3})")
        print()
