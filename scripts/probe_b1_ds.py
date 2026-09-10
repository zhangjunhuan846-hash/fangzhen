#!/usr/bin/env python3
"""Phase B1.1 sanity check: apparent D_s(SOC) from the GITT segments."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset                 # noqa: E402
from extraction.gitt_extractor import extract_gitt_segments   # noqa: E402
from extraction.gitt_diffusivity import compute_ds_app        # noqa: E402
from parameters.sintef_graphite_geometry import (             # noqa: E402
    derive_geometry, read_structure,
)
from parameters.sintef_graphite_ocp import load_ocp_tables     # noqa: E402

V2 = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
GITT_CELL = "063b77"

import pybamm  # noqa: E402
R = float(pybamm.ParameterValues("Ecker2015_graphite_halfcell")
          ["Positive particle radius [m]"])
geom = derive_geometry(read_structure(GITT_CELL))
q_th = float(geom["nominal_cell_capacity_Ah"])
print(f"GITT cell {GITT_CELL}: eps_am={geom['active_material_volume_fraction']:.6f} "
      f"area={geom['electrode_area_cm2']:.4f} cm2 thickness="
      f"{geom['electrode_thickness_m']*1e6:.1f} um")
print(f"Q_th = {q_th*1e3:.4f} mAh | R = {R*1e6:.3f} um (reference set, not measured)")

ad = get_dataset("sintef_graphite")
seg = extract_gitt_segments(ad, GITT_CELL, verbose=False)["segments"]
tables = load_ocp_tables(V2)
res = compute_ds_app(seg, tables, particle_radius_m=R, q_th_Ah=q_th,
                     active_mass_source="metadata.csv cell 063b77")
pul = res["pulses"]
ok = pul.Ds_app_m2_s.notna() & (pul.Ds_app_m2_s > 0)
print(f"\npulses: {len(pul)} | defined: {ok.sum()}")
print("Ds_app [cm2/s] percentiles:",
      {k: float(np.round(np.nanpercentile(pul.Ds_app_m2_s[ok], v) * 1e4, 12))
       for k, v in (("p05", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95))})
print("\nper branch (median Ds_app [cm2/s], sqrt_t r2):")
print(pul[ok].groupby("branch").agg(
    n=("Ds_app_m2_s", "size"),
    Ds_med_cm2s=("Ds_app_cm2_s", "median"),
    r2_med=("sqrt_t_r2", "median"),
    u_prime_med=("u_prime_V_per_soc", "median"),
).to_string())
print("\nflags (top):")
fl = pul[ok]["flags"].replace("", np.nan).dropna()
print(fl.value_counts().head(8).to_string() if len(fl) else "  none")
ratio = pul["relax_over_pulse_sqrt_ratio"].dropna()
print(f"\nrelax/pulse sqrt ratio: median {ratio.median():.3f} "
      f"p25 {ratio.quantile(.25):.3f} p75 {ratio.quantile(.75):.3f} (n={len(ratio)})")
print("\nSOC-resolved table (median per 0.02 SOC):")
print(res["table"].head(30).to_string(index=False))
