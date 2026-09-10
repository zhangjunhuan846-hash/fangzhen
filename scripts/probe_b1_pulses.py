#!/usr/bin/env python3
"""
Phase B1 probe #6: the GITT pulse train lives in the gaps.

Established so far:
  * the file is time-sorted and multi-rate: within one time window the
    rows of several (cycle, step) channels are interleaved;
  * steps 2/3 and 8/9 log at 0.01 s / 10 s with I == 0 (rest channels);
  * steps 4 and 10 log at 1 s with I == -44.155 / +44.155 uA;
  * a naive trapezoid over a step spans the REST gaps too and inflates
    the charge to 9.8 mAh (4.5x the cell capacity), which is why the
    pulse/rest split must come from the LOGGING GAPS.
  187 027 rows at 1 s = 51.9 h = 103 x 1800 s -> consistent with a
  1800 s pulse train.  This probe verifies that directly by
  run-length-encoding the gaps.
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
PULSE_STEPS = {4, 10}

path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)

frames = []
for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    sel = d[C_S].isin(PULSE_STEPS)
    if sel.any():
        frames.append(d.loc[sel])
pulses_all = __import__("pandas").concat(frames, ignore_index=True)
print(f"kept {len(pulses_all):,} rows tagged step 4/10 "
      f"(of {pf.metadata.num_rows:,})")

print()
print(f"{'cyc':>4}{'step':>6}{'rows':>10}{'span[h]':>9}{'logged[h]':>10}"
      f"{'n_bursts':>10}{'burst_med[s]':>13}{'gap_med[s]':>11}"
      f"{'Q_excl_gaps[mAh]':>18}")
summary = []
for (cyc, step), g in pulses_all.groupby([C_C, C_S], sort=True):
    t = g[C_T].to_numpy(float)
    i = g[C_I].to_numpy(float)
    dt = np.diff(t)
    is_pulse = dt <= 2.0                       # 1 s logging = pulse
    # burst boundaries
    edges = np.flatnonzero(np.diff(is_pulse.astype(int)) != 0) + 1
    starts = np.concatenate(([0], edges))
    stops = np.concatenate((edges, [len(dt)]))
    lens = stops - starts
    plens = lens[is_pulse[starts]] if len(starts) else np.array([])
    glens = lens[~is_pulse[starts]] if len(starts) else np.array([])
    # charge EXCLUDING the rest gaps (sample-and-hold on the logged rows)
    q = float(np.sum(i[:-1][is_pulse] * dt[is_pulse]) / 3600.0)
    summary.append((int(cyc), int(step), len(t), (t[-1] - t[0]) / 3600,
                    dt[is_pulse].sum() / 3600, len(plens),
                    np.median(plens) if len(plens) else np.nan,
                    np.median(glens) if len(glens) else np.nan, q * 1e3))
    print(f"{int(cyc):>4}{int(step):>6}{len(t):>10,}{(t[-1] - t[0]) / 3600:>9.1f}"
          f"{dt[is_pulse].sum() / 3600:>10.2f}{len(plens):>10}"
          f"{(np.median(plens) if len(plens) else float('nan')):>13.1f}"
          f"{(np.median(glens) if len(glens) else float('nan')):>11.1f}"
          f"{q * 1e3:>18.4f}")

print()
print("burst-length distribution (cycle 1):")
for (cyc, step), g in pulses_all.groupby([C_C, C_S], sort=True):
    if int(cyc) != 1:
        continue
    t = g[C_T].to_numpy(float)
    dt = np.diff(t)
    is_pulse = dt <= 2.0
    edges = np.flatnonzero(np.diff(is_pulse.astype(int)) != 0) + 1
    starts = np.concatenate(([0], edges))
    stops = np.concatenate((edges, [len(dt)]))
    lens = stops - starts
    plens = lens[is_pulse[starts]]
    # pulse duration in seconds = sum of the dt inside each burst
    durs = np.array([dt[s:e].sum() for s, e in zip(starts, stops)
                     if is_pulse[s]])
    print(f"  step {int(step)}: {len(durs)} bursts, "
          f"duration s -> median {np.median(durs):.1f}, "
          f"min {durs.min():.1f}, max {durs.max():.1f}")
    u, c = np.unique(np.round(durs / 60.0), return_counts=True)
    print(f"     duration [min] histogram (top 6): "
          + ", ".join(f"{v:g}x{n}" for n, v in
                      sorted(zip(c, u), reverse=True)[:6]))

print()
print("first pulse of cycle 1 step 4 (raw rows):")
g = pulses_all[(pulses_all[C_C] == 1) & (pulses_all[C_S] == 4)]
t = g[C_T].to_numpy(float)
i = g[C_I].to_numpy(float)
v = g[C_V].to_numpy(float)
dt = np.diff(t)
first_gap = np.argmax(dt > 2.0)
n = min(first_gap + 1, len(t))
print(f"  first burst: {n} rows, {(t[n - 1] - t[0]) / 60:.2f} min, "
      f"I = {i[:n].mean() * 1e6:.4f} uA const (std {i[:n].std() * 1e6:.4f})")
print(f"  V {v[0]:.5f} -> {v[n - 1]:.5f}   (dV = {(v[n - 1] - v[0]) * 1e3:.2f} mV)")
print(f"  after it: gap = {dt[first_gap]:.1f} s")
print("  V at a few points in the pulse (t[min], V):")
for k in np.linspace(0, n - 1, 8).astype(int):
    print(f"     {(t[k] - t[0]) / 60:8.3f}  {v[k]:.5f}")
