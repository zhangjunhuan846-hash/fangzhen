#!/usr/bin/env python3
"""
Phase B1 probe #4: is the GITT file time-sorted, and what does each
(cycle, step) really contain?

Probe #3 left an impossibility: step 2 spans 611 h with I == 0 while V
falls 2.5 -> 0.03 V, and step 4 shows I != 0 on 100 % of its rows but
would then pass ~6x the cell capacity.  The only way both can be true
is that the rows are NOT in one temporal order, so this probe prints
the per-row-group time span and composition, plus the true charge
Σ I·dt per step.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

C_T, C_I, C_V, C_C, C_S = ("Test Time / s", "Current / A", "Voltage / V",
                           "Cycle Count / 1", "Step Index / 1")
COLS = [C_T, C_I, C_V, C_C, C_S]

path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)

print("=" * 100)
print("per row group: time span and (cycle, step) composition")
print("=" * 100)
print(f"{'rg':>4} {'rows':>9} {'t_min[h]':>10} {'t_max[h]':>10} "
      f"{'monotone':>8}  steps present (count)")
mono_all = True
prev_tmax = -np.inf
for rg in range(min(pf.metadata.num_row_groups, 26)):
    d = pf.read_row_group(rg, columns=COLS).to_pandas()
    t = d[C_T].to_numpy(float)
    mono = bool(np.all(np.diff(t) >= 0))
    comp = (d.groupby([C_C, C_S]).size().to_dict())
    comp_s = " ".join(f"{int(k[0])}/{int(k[1])}:{v}" for k, v in
                      sorted(comp.items()))
    print(f"{rg:>4} {len(d):>9,} {t.min() / 3600:>10.2f} "
          f"{t.max() / 3600:>10.2f} {str(mono):>8}  {comp_s[:70]}")
    if t.max() < prev_tmax:
        mono_all = False
    prev_tmax = max(prev_tmax, t.max())
print(f"\nrow groups are globally time-ordered (by t_max): {mono_all}")

print()
print("=" * 100)
print("true charge Σ I·dt and duty per (cycle, step)")
print("=" * 100)
print(f"{'cyc':>4}{'step':>6}{'rows':>11}{'span[h]':>9}{'sampled[h]':>11}"
      f"{'Q[mAh]':>10}{'I_set[uA]':>10}{'duty%':>7}")
acc: dict = {}
for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    for key, g in d.groupby([C_C, C_S], sort=False):
        k = (int(key[0]), int(key[1]))
        t = g[C_T].to_numpy(float)
        i = g[C_I].to_numpy(float)
        a = acc.get(k)
        if a is None:
            acc[k] = a = {"n": 0, "t0": np.inf, "t1": -np.inf,
                          "q": 0.0, "sampled": 0.0, "iset": 0.0, "ni": 0,
                          "gaps": 0.0}
        dt = np.diff(t)
        if len(dt):
            a["sampled"] += float(dt.sum())
            a["gaps"] += float(dt[dt > 1.0].sum())
        a["n"] += len(t)
        a["t0"] = min(a["t0"], float(t[0]))
        a["t1"] = max(a["t1"], float(t[-1]))
        q = 0.0
        if len(t) > 1:
            q = float(np.trapezoid(i, t) / 3600.0)      # Ah
        a["q"] += q
        nz = np.abs(i) > 1e-9
        if nz.any():
            a["iset"] += float(np.median(i[nz]))
            a["ni"] += 1

for k in sorted(acc):
    a = acc[k]
    iset = a["iset"] / a["ni"] if a["ni"] else 0.0
    span = (a["t1"] - a["t0"])
    duty = 100.0 * a["sampled"] / span if span else float("nan")
    print(f"{k[0]:>4}{k[1]:>6}{a['n']:>11,}{span / 3600:>9.2f}"
          f"{a['sampled'] / 3600:>11.2f}{a['q'] * 1e3:>10.4f}"
          f"{iset * 1e6:>10.3f}{duty:>7.1f}")
print("\nQ = Σ I·dt over the step; 'duty%' = (Σ dt)/(t_max - t_min) x 100")
