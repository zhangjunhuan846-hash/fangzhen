#!/usr/bin/env python3
"""Sanity check of the B1.0 GITT segmentation on the real file."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset      # noqa: E402
from extraction.gitt_extractor import extract_gitt_segments  # noqa: E402

ad = get_dataset("sintef_graphite")
res = extract_gitt_segments(ad, "063b77")
seg = res["segments"]
prov = res["provenance"]
print()
print("pulse protocol:", prov["pulse_protocol"])
print("Q_ref per cycle [mAh]:", prov["soc_reference_charge_mAh"])
print("SOC range:", float(seg.SOC_start.min()), float(seg.SOC_end.max()))
print()
cols = ["cycle","pulse_id","branch","SOC_start","SOC_end","I_A",
        "pulse_time_s","relax_time_s","delta_V_pulse_V","delta_V_relax_V",
        "capacity_increment_mAh","sqrt_t_r2","n_fit_samples","relax_step"]
with pd.option_context("display.width", 200, "display.max_columns", 50):
    print(seg[cols].head(6).to_string(index=False))
    print("...")
    print(seg[cols].iloc[100:106].to_string(index=False))
print()
g = seg[(seg.branch=="lithiation") & (seg.cycle==1)]
print("cycle 1 lithiation pulses:", len(g))
print("pulse_time_s unique:", sorted(g.pulse_time_s.round(1).unique())[:6])
print("I_A unique:", sorted(g.I_A.round(9).unique())[:4])
print("relax matched: %d/%d" % ((g.relax_step>=0).sum(), len(g)))
print("sqrt_t r2: median %.4f  min %.4f" % (g.sqrt_t_r2.median(), g.sqrt_t_r2.min()))
print("delta_V_pulse [mV]: median %.2f  min %.2f  max %.2f" % (
    g.delta_V_pulse_V.median()*1e3, g.delta_V_pulse_V.min()*1e3, g.delta_V_pulse_V.max()*1e3))
print("delta_V_relax [mV]: median %.2f  min %.2f  max %.2f" % (
    g.delta_V_relax_V.median()*1e3, g.delta_V_relax_V.min()*1e3, g.delta_V_relax_V.max()*1e3))
print("SOC in [0,1]:", bool(seg.SOC_start.between(-0.01,1.01).all() and seg.SOC_end.between(-0.01,1.01).all()))
