#!/usr/bin/env python3
"""
Phase B0.6 probe: what does branch-aware sampling actually produce, and
is the fidelity target met?

Prints, per branch: input/output point counts, the eps ladder, the
MEASURED vertical error of the output table against every
full-resolution sample, the |dV/dSOC| distribution and the point
density per SOC band.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset  # noqa: E402
from extraction.ocp_extractor_v2 import (  # noqa: E402
    SOC_BANDS,
    extract_ocp_v2,
    table_stats,
)

adapter = get_dataset("sintef_graphite")
t0 = time.perf_counter()
res = extract_ocp_v2(adapter, "4ccc47", "pOCV-deli", cycle=1)
print("runtime: %.2f s" % (time.perf_counter() - t0))

# ------------------------------------------------------------------
# design sweep: how does the fidelity/size trade-off move?
# ------------------------------------------------------------------
print("\n" + "=" * 78)
print("sampling-parameter sweep (n_out per branch | measured max error mV)")
print("=" * 78)
print("%-46s %-22s %-22s" % ("config", "lithiation", "delithiation"))
SWEEP = [
    ("eps 0.5 mV, gap 0.020, steep>=5", dict(eps_mV=0.5, max_gap_soc=0.020,
                                             min_pts_in_steep=5)),
    ("eps 0.3 mV, gap 0.010, steep>=8", dict(eps_mV=0.3, max_gap_soc=0.010,
                                             min_pts_in_steep=8)),
    ("eps 0.2 mV, gap 0.005, steep>=12", dict(eps_mV=0.2, max_gap_soc=0.005,
                                              min_pts_in_steep=12)),
    ("eps 0.1 mV, gap 0.002, steep>=25", dict(eps_mV=0.1, max_gap_soc=0.002,
                                              min_pts_in_steep=25)),
]
for label, kw in SWEEP:
    r = extract_ocp_v2(adapter, "4ccc47", "pOCV-deli", cycle=1, **kw)
    cells = []
    for branch in ("lithiation", "delithiation"):
        d = r["provenance"]["resampling"][branch]
        cells.append("%5d pts | %.3f mV" % (d["n_out"],
                                            d["achieved_vertical_error_mV"]["max"]))
    above = [int((r[b]["Voltage"] > 1.4325).sum())
             for b in ("lithiation", "delithiation")]
    print("%-46s %-22s %-22s  >1.43V: %d" % (label, cells[0], cells[1],
                                             above[0]))

res = extract_ocp_v2(adapter, "4ccc47", "pOCV-deli", cycle=1)
prov = res["provenance"]
print("Q_ref (v2)          = %r" % prov["soc_reference_charge_Ah"])
print("full-resolution pts = %s" % (prov["n_points_full_resolution"],))
print("trace rows          = %d" % prov["input_trace"]["n_rows"])
print("trace sampling      = %.1f s median" % prov["input_trace"]["sampling_median_s"])
print("trace decimation    = %s" % prov["input_trace"]["decimation"])
print("verify vs adapter   = %s" % (prov["input_trace"]["verification_vs_adapter"],))

for branch in ("lithiation", "delithiation"):
    d = prov["resampling"][branch]
    print("\n=== %s ===" % branch)
    print("  n_in=%d  n_out=%d  eps_used=%.3f mV  endpoints=%s"
          % (d["n_in"], d["n_out"], d["eps_mV_used"], d["endpoints_kept"]))
    print("  eps ladder: %s" % (d["eps_ladder"],))
    err = d["achieved_vertical_error_mV"]
    print("  MEASURED vertical error: max=%.4f mV  mean=%.4f  p95=%.4f"
          % (err["max"], err["mean"], err["p95"]))
    for name, _lo, _hi in SOC_BANDS:
        b = err["by_soc_band"][name]
        print("     %-12s n=%6d  max=%.4f mV  mean=%.4f mV"
              % (name, b["n"], b["max_mV"], b["mean_mV"]))
    print("  |dV/dSOC| max=%.4g V/unit  median=%.4g V/unit"
          % (d["max_dv_dsoc_v_per_soc"], d["median_dv_dsoc_v_per_soc"]))
    print("  soc step: min=%.3e  median=%.3e" % (d["min_soc_step"], d["median_soc_step"]))

    st = table_stats(res[branch])
    print("  table: n=%d  SOC %s  V %s"
          % (st["n_points"], st["soc_range"], st["voltage_range_V"]))
    for name, _lo, _hi in SOC_BANDS:
        b = st["bands"][name]
        print("     %-12s n=%5d  per-0.01-SOC=%8.1f  min_step=%.2e  maxdVdSOC=%.3g"
              % (name, b["n_points"], b["points_per_0p01_soc"],
                 b["min_soc_step"], b["max_dv_dsoc_v_per_soc"]))
    above = float((res[branch]["Voltage"] > 1.4325).sum())
    print("  points above 1.4325 V: %.0f" % above)
