#!/usr/bin/env python3
"""Is one GITT pulse actually linear in sqrt(t)?  Dump the waveform."""
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
path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)

keep = []
for batch in pf.iter_batches(batch_size=1 << 18,
                             columns=[C_T, C_I, C_V, C_C, C_S]):
    d = batch.to_pandas()
    sel = (d[C_C] == 1) & (d[C_S] == 4)
    if sel.any():
        keep.append(d.loc[sel])
a = __import__("pandas").concat(keep, ignore_index=True)
a = a.sort_values(C_T).reset_index(drop=True)
t = a[C_T].to_numpy(float); i = a[C_I].to_numpy(float)
v = a[C_V].to_numpy(float)
dt = np.diff(t)
brk = np.flatnonzero(dt > 30.0) + 1
bounds = np.concatenate(([0], brk, [len(t)]))
print(f"cycle 1 step 4: {len(bounds)-1} bursts")

for pi in (1, 4, 20, 60, 100):
    if pi >= len(bounds) - 1:
        continue
    s, e = int(bounds[pi]), int(bounds[pi + 1])
    tt = t[s:e] - t[s]; vv = v[s:e]; ii = i[s:e]
    print(f"\n=== burst {pi+1}: n={e-s} tau={tt[-1]:.1f} s "
          f"I={ii.mean()*1e6:.4f} uA V0={vv[0]:.5f} Vend={vv[-1]:.5f} "
          f"dV={1e3*(vv[-1]-vv[0]):+.2f} mV ===")
    print(f"{'t[s]':>8} {'sqrt(t)':>9} {'V':>10} {'V-V0[mV]':>10}")
    for target in (0, 1, 2, 5, 10, 30, 60, 120, 300, 600, 900, 1200, 1500,
                   int(tt[-1])):
        k = int(np.searchsorted(tt, target))
        k = min(k, len(tt) - 1)
        print(f"{tt[k]:>8.1f} {np.sqrt(tt[k]):>9.2f} {vv[k]:>10.5f} "
              f"{1e3*(vv[k]-vv[0]):>10.3f}")
    sel = tt >= 60.0
    x = np.sqrt(tt[sel]); y = vv[sel]
    m, b = np.polyfit(x, y, 1)
    r = y - (b + m * x)
    r2 = 1 - r.var() / y.var()
    print(f"  fit t>=60 s: m={m:.6e} V/sqrt(s)  intercept={b:.5f}  R2={r2:.5f}")
    print(f"  m*sqrt(tau) = {m*np.sqrt(tt[-1])*1e3:.3f} mV "
          f"vs measured dV = {1e3*(vv[-1]-vv[0]):.3f} mV  "
          f"(IR+transient part = "
          f"{1e3*(vv[-1]-vv[0]) - m*np.sqrt(tt[-1])*1e3:.3f} mV)")
    print(f"  V(1s)-V(0) = {1e3*(vv[1]-vv[0]):.3f} mV  <- the ohmic jump")
