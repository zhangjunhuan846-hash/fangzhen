#!/usr/bin/env python3
"""
Phase B1 probe #5: verbatim consecutive rows.

The row-group census showed steps 2/3/4 appearing inside the SAME time
window, which is impossible for a single cell's current channel unless
the file interleaves several logging streams.  Only a verbatim dump
settles it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)
names = [f.name for f in pf.schema_arrow]
print("columns:", names)

for rg, start, count in ((0, 0, 45), (4, 60, 45), (200, 0, 45)):
    d = pf.read_row_group(rg).to_pandas()
    sub = d.iloc[start:start + count]
    print(f"\n{'=' * 96}")
    print(f"row group {rg}, rows {start}..{start + count - 1}")
    print(f"{'#':>5} {'TestTime[s]':>13} {'UnixTime':>12} {'I[uA]':>10} "
          f"{'V':>9} {'cyc':>4} {'step':>5} {'CumCap[Ah]':>12}")
    t0 = float(d["Test Time / s"].iloc[0])
    for n, (_, r) in enumerate(sub.iterrows()):
        print(f"{start + n:>5} {r['Test Time / s']:>13.3f} "
              f"{r['Unix Time / s']:>12.0f} "
              f"{r['Current / A'] * 1e6:>10.3f} {r['Voltage / V']:>9.5f} "
              f"{int(r['Cycle Count / 1']):>4} {int(r['Step Index / 1']):>5} "
              f"{r['Cumulative Capacity / Ah']:>12.6f}")

# distribution of dt within one step, separately
d = pf.read_row_group(4, columns=["Test Time / s", "Current / A",
                                  "Cycle Count / 1", "Step Index / 1"]
                      ).to_pandas()
print(f"\n{'=' * 96}")
print("dt statistics per (cycle, step) inside one row group (rg 4)")
for key, g in d.groupby(["Cycle Count / 1", "Step Index / 1"]):
    t = g["Test Time / s"].to_numpy(float)
    i = g["Current / A"].to_numpy(float)
    dt = np.diff(t)
    if not len(dt):
        continue
    vals, cnts = np.unique(np.round(dt, 3), return_counts=True)
    top = sorted(zip(cnts, vals), reverse=True)[:4]
    print(f"  step {int(key[1])}: n={len(t)} dt top: "
          + ", ".join(f"{v:g}s x{c}" for c, v in top)
          + f" | I range [{i.min() * 1e6:.3f}, {i.max() * 1e6:.3f}] uA"
          + f" | share I!=0 {100 * np.mean(np.abs(i) > 1e-9):.1f}%")
