#!/usr/bin/env python3
"""
Phase B1 probe #2: what does the GITT programme actually look like?

The first probe showed steps whose MEDIAN current is 0 but whose voltage
sweeps 2.9 -> 0.88 V, and "pulse" steps that last 309 h -- so the
median-current classifier is not enough to see the waveform.

This probe streams the file once and, per (cycle, step), keeps the first
rows plus a strided sample, so the true pattern (pulse / rest / mixed)
is visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COL_TIME = "Test Time / s"
COL_CURRENT = "Current / A"
COL_VOLTAGE = "Voltage / V"
COL_CYCLE = "Cycle Count / 1"
COL_STEP = "Step Index / 1"
COLS = [COL_TIME, COL_CURRENT, COL_VOLTAGE, COL_CYCLE, COL_STEP]

# --- reference diffusivity, evaluated symbolically -----------------
import pybamm  # noqa: E402

pv = pybamm.ParameterValues("Ecker2015_graphite_halfcell")
D_fn = pv["Positive particle diffusivity [m2.s-1]"]
R = float(pv["Positive particle radius [m]"])
print("reference Ecker2015 graphite diffusivity:")
for sto in (0.02, 0.2, 0.5, 0.8, 0.98):
    try:
        val = float(D_fn(pybamm.Scalar(sto)))
    except Exception as exc:  # noqa: BLE001
        val = float("nan")
        print(f"   sto={sto}: {type(exc).__name__}: {exc}")
        continue
    print(f"   sto={sto:.2f}  D={val:.4e} m2/s  tau_d={R**2/val:.4e} s "
          f"({R**2/val/3600:.1f} h)")

# --- stream and dump the waveform ---------------------------------
path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)

TARGET = {(1, 1), (1, 2), (1, 3), (1, 4), (1, 7), (1, 8), (1, 10)}
STRIDE = 4000        # keep every 4000th row per (cycle, step)
HEAD = 12
store: dict = {}
counters: dict = {}

for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    for key, g in d.groupby([COL_CYCLE, COL_STEP], sort=False):
        k = (int(key[0]), int(key[1]))
        if k not in TARGET:
            continue
        n0 = counters.get(k, 0)
        idx = np.arange(n0, n0 + len(g))
        counters[k] = n0 + len(g)
        sel = (idx % STRIDE == 0)
        take = g.iloc[sel]
        if k not in store:
            store[k] = {"t": [], "I": [], "V": [], "n": 0, "head": g.iloc[:HEAD]}
        store[k]["t"].append(take[COL_TIME].to_numpy(float))
        store[k]["I"].append(take[COL_CURRENT].to_numpy(float))
        store[k]["V"].append(take[COL_VOLTAGE].to_numpy(float))
        store[k]["n"] = counters[k]

for k in sorted(store):
    s = store[k]
    t = np.concatenate(s["t"])
    I = np.concatenate(s["I"])
    V = np.concatenate(s["V"])
    t = t - t[0]
    print(f"\n{'=' * 78}")
    print(f"(cycle, step) = {k}   rows = {s['n']:,}   "
          f"duration = {t[-1] / 3600:.2f} h   sampled every {STRIDE} rows")
    print("  first rows:")
    h = s["head"]
    for _, r in h.iterrows():
        print(f"     t={r[COL_TIME]:12.3f}  I={r[COL_CURRENT] * 1e6:+9.3f} uA  "
              f"V={r[COL_VOLTAGE]:8.5f}")
    print("  strided trajectory (t[h], I[uA], V):")
    for i in range(0, min(len(t), 40)):
        print(f"     t={t[i] / 3600:9.3f}  I={I[i] * 1e6:+9.3f}  V={V[i]:8.5f}")
    nz = np.abs(I) > 1e-9
    print(f"  non-zero-current share of sampled rows: "
          f"{nz.mean() * 100:.1f} %")
    if nz.any():
        lv = np.unique(np.round(I[nz] * 1e6, 2))
        print(f"  current levels [uA]: {lv[:8]}")
