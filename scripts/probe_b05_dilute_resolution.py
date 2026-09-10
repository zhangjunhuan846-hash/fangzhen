#!/usr/bin/env python3
"""
Phase B0.5 diagnostic: is the near-vertical dilute stage of the
lithiation branch lost to DECIMATION, or is it absent from the raw data?

The extracted lithiation OCP table jumps 3.0003 V -> 1.2349 V between
its first two samples (SOC 0 -> 0.00056).  If the raw file resolves that
drop, the table's resolution there is a decimation choice that can be
fixed; if not, it is a property of the measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset  # noqa: E402

COLUMNS = ["Test Time / s", "Current / A", "Voltage / V", "Cycle Count / 1",
           "Step Index / 1", "Cumulative Capacity / Ah"]

adapter = get_dataset("sintef_graphite")
path = adapter._raw_path("4ccc47", "pOCV-lith")
pf = pq.ParquetFile(path)
print(f"file            : {path.name}")
print(f"row groups      : {pf.metadata.num_row_groups}")
print(f"total rows      : {pf.metadata.num_rows}")

# step 2 of cycle 1 = lithiation
rows = []
for i in range(pf.metadata.num_row_groups):
    df = pf.read_row_group(i, columns=COLUMNS).to_pandas()
    sel = df[(df["Cycle Count / 1"] == 1) & (df["Step Index / 1"] == 2)]
    if len(sel):
        rows.append(sel)
step = __import__("pandas").concat(rows, ignore_index=True)
t = step["Test Time / s"].to_numpy(float)
V = step["Voltage / V"].to_numpy(float)
I = step["Current / A"].to_numpy(float)
print(f"lithiation rows : {len(step)}  ({t[-1] / 3600:.2f} h)")
dt = np.diff(t)
print(f"raw sampling    : median dt = {np.median(dt):.3f} s "
      f"(min {dt.min():.3f}, max {dt.max():.3f})")

print("\nraw first 300 s of the lithiation branch (t relative to step start):")
t_rel = t - t[0]
for target in (0, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300):
    i = int(np.searchsorted(t_rel, target))
    if i < len(t):
        print(f"   t={t_rel[i]:8.1f} s  V={V[i]:8.4f} V  I={I[i] * 1e6:+8.3f} uA")

# how many raw rows survive the adapter's decimation?
raw = adapter.load_raw("4ccc47")
print(f"\nadapter.load_raw: rows={len(raw)} "
      f"stride={raw.attrs.get('decimation_stride')} "
      f"pre-decimation={raw.attrs.get('rows_before_decimation')}")

sel = raw[raw["step"] == 2].sort_values("time_s")
sel = sel.assign(t_rel=sel["time_s"] - sel["time_s"].iloc[0])
early = sel[sel["t_rel"] <= 300.0]
print(f"decimated rows with t_rel<=300 s: {len(early)} of "
      f"{int((t_rel <= 300).sum())} raw rows in the same span")
if len(early):
    print(early[["t_rel", "voltage_V", "current_A"]].head(12).to_string(index=False))
