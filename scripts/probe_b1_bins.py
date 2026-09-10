#!/usr/bin/env python3
"""
Phase B1 probe #3: time-binned current/voltage profile per step.

Probe #2 showed stretches with I == 0 while V fell by volts, and a
309 h "pulse" step that would pass 6x the cell capacity if the current
were continuous.  Both are impossible, so the waveform must be
intermittent: bin every step in TIME and look at the mean current and
the charged fraction per bin.
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
NBINS = 200
WANT = [(1, 2), (1, 3), (1, 4), (1, 7), (1, 8), (1, 9), (1, 10), (1, 13)]

path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)

# per (cycle, step): bin sums
acc: dict = {}
for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    for key, g in d.groupby([C_C, C_S], sort=False):
        k = (int(key[0]), int(key[1]))
        if k not in WANT:
            continue
        t = g[C_T].to_numpy(float)
        i = g[C_I].to_numpy(float)
        v = g[C_V].to_numpy(float)
        a = acc.get(k)
        if a is None:
            acc[k] = a = {"t0": t.min(), "t1": t.max(), "n": 0,
                          "itot": 0.0, "ntot": 0, "vmin": np.inf,
                          "vmax": -np.inf}
        a["t0"] = min(a["t0"], float(t.min()))
        a["t1"] = max(a["t1"], float(t.max()))
        a["n"] += len(t)
        a["itot"] += float(i.sum())
        a["ntot"] += int((np.abs(i) > 1e-9).sum())
        a["vmin"] = min(a["vmin"], float(v.min()))
        a["vmax"] = max(a["vmax"], float(v.max()))

# second pass: time bins
bins: dict = {}
for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    for key, g in d.groupby([C_C, C_S], sort=False):
        k = (int(key[0]), int(key[1]))
        if k not in WANT:
            continue
        a = acc[k]
        span = a["t1"] - a["t0"]
        t = g[C_T].to_numpy(float)
        b = np.clip(((t - a["t0"]) / span * NBINS).astype(int), 0, NBINS - 1)
        i = g[C_I].to_numpy(float)
        v = g[C_V].to_numpy(float)
        rec = bins.setdefault(k, {"si": np.zeros(NBINS), "sn": np.zeros(NBINS),
                                  "sv": np.zeros(NBINS),
                                  "nz": np.zeros(NBINS)})
        np.add.at(rec["si"], b, i)
        np.add.at(rec["sn"], b, 1.0)
        np.add.at(rec["sv"], b, v)
        np.add.at(rec["nz"], b, (np.abs(i) > 1e-9).astype(float))

print(f"{'cyc':>4}{'step':>6}{'rows':>12}{'hours':>10}{'Vmin':>9}{'Vmax':>9}"
      f"{'sumI[uA*s]':>13}{'nonzero%':>10}")
for k in sorted(acc):
    a = acc[k]
    print(f"{k[0]:>4}{k[1]:>6}{a['n']:>12,}{(a['t1'] - a['t0']) / 3600:>10.2f}"
          f"{a['vmin']:>9.4f}{a['vmax']:>9.4f}{a['itot'] * 1e6:>13.3f}"
          f"{100 * a['ntot'] / a['n']:>10.2f}")

for k in sorted(bins):
    rec = bins[k]
    a = acc[k]
    ok = rec["sn"] > 0
    print(f"\n{'=' * 78}")
    print(f"(cycle, step) = {k}  -- {NBINS} equal-TIME bins over "
          f"{(a['t1'] - a['t0']) / 3600:.2f} h")
    print(f"  {'bin':>4} {'t[h]':>9} {'<I>[uA]':>10} {'nonzero%':>9} "
          f"{'<V>':>9}")
    step = max(1, NBINS // 25)
    for j in range(0, NBINS, step):
        if not ok[j]:
            continue
        tm = (j + 0.5) / NBINS * (a["t1"] - a["t0"]) / 3600
        print(f"  {j:>4} {tm:>9.3f} {rec['si'][j] / rec['sn'][j] * 1e6:>10.3f} "
              f"{100 * rec['nz'][j] / rec['sn'][j]:>9.2f} "
              f"{rec['sv'][j] / rec['sn'][j]:>9.5f}")
