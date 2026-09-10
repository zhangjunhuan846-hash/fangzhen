#!/usr/bin/env python3
"""
Phase B1 probe: SINTEF GITT file structure + the reference diffusivity.

1. reference (Ecker2015_graphite_halfcell) diffusivity values, to know the
   order of magnitude we are comparing against;
2. GITT parquet: row count, sampling, and the (cycle, step) programme
   table (count / duration / median current / first+last voltage) so the
   pulse + relaxation pattern is known before the extractor is written.
"""
from __future__ import annotations

import sys
import time
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

print("=" * 78)
print("1. reference diffusivity (Ecker2015_graphite_halfcell)")
print("=" * 78)
import pybamm  # noqa: E402

pv = pybamm.ParameterValues("Ecker2015_graphite_halfcell")
D = pv["Positive particle diffusivity [m2.s-1]"]
R = float(pv["Positive particle radius [m]"])
c_max = float(pv["Maximum concentration in positive electrode [mol.m-3]"])
eps = float(pv["Positive electrode active material volume fraction"])
L = float(pv["Positive electrode thickness [m]"])
A = float(pv["Electrode height [m]"]) * float(pv["Electrode width [m]"])
print(f"  particle radius      = {R * 1e6:.3f} um")
print(f"  eps_am               = {eps:.6f}")
print(f"  c_max                = {c_max:.1f} mol/m3")
print(f"  thickness / area     = {L * 1e6:.1f} um / {A * 1e4:.4f} cm2")
print(f"  Q_th = F eps c_max L A = "
      f"{96485.33212 * eps * c_max * L * A:.4f} A.s "
      f"({96485.33212 * eps * c_max * L * A / 3600 * 1e3:.4f} mAh)")
print("  D(sto) [m2/s]:")
for sto in (0.05, 0.2, 0.5, 0.8, 0.95):
    try:
        val = float(D(sto))
    except Exception as exc:  # noqa: BLE001
        val = float("nan")
        print(f"     sto={sto}: {type(exc).__name__}")
    tau = R ** 2 / val if val and np.isfinite(val) and val > 0 else float("nan")
    print(f"     sto={sto:.2f}  D={val:.4e}  tau_d={tau:.4e} s "
          f"({tau / 3600:.2f} h)")

print()
print("=" * 78)
print("2. SINTEF GITT parquet")
print("=" * 78)
path = (ROOT / "data" / "sintef__sintef-graphite-R2032-intelligent-063b77"
        "__20250514__gitt__RT.bdf.parquet")
pf = pq.ParquetFile(path)
print(f"  file          : {path.name}")
print(f"  size          : {path.stat().st_size / 1e6:.1f} MB")
print(f"  row groups    : {pf.metadata.num_row_groups}")
print(f"  total rows    : {pf.metadata.num_rows:,}")
print(f"  schema        :")
for f in pf.schema_arrow:
    print(f"     {f.name}  ({f.type})")

# sampling from a middle row group
mid = pf.metadata.num_row_groups // 2
df = pf.read_row_group(mid, columns=COLS).to_pandas()
t = df[COL_TIME].to_numpy(float)
dt = np.diff(t)
dt = dt[dt > 0]
print(f"  sampling      : median {np.median(dt):.4f} s "
      f"(min {dt.min():.4f}, max {dt.max():.4f})")

print("\n  streaming pass over every row group (per-cardinality scan)...")
t0 = time.perf_counter()
acc: dict = {}
peak = 0.0
for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
    d = batch.to_pandas()
    cur = d[COL_CURRENT].to_numpy(float)
    if len(cur):
        peak = max(peak, float(np.max(np.abs(cur))))
    d = d.assign(_a=d[COL_CURRENT].abs())
    gb = d.groupby([COL_CYCLE, COL_STEP], sort=False)
    agg = gb.agg(n=(COL_CURRENT, "count"),
                 s=(COL_CURRENT, "sum"),
                 t0=(COL_TIME, "min"),
                 t1=(COL_TIME, "max"))
    vf = gb[COL_VOLTAGE].first()
    vl = gb[COL_VOLTAGE].last()
    am = gb["_a"].max()
    for key, row in agg.iterrows():
        k = (int(key[0]), int(key[1]))
        a = acc.get(k)
        if a is None:
            acc[k] = a = {"n": 0, "sum": 0.0, "t0": np.inf, "t1": -np.inf,
                          "amax": 0.0, "vf": None, "vl": None}
        a["n"] += int(row["n"])
        a["sum"] += float(row["s"])
        a["t0"] = min(a["t0"], float(row["t0"]))
        a["t1"] = max(a["t1"], float(row["t1"]))
        a["amax"] = max(a["amax"], float(am.loc[key]))
        if a["vf"] is None:
            a["vf"] = float(vf.loc[key])
        a["vl"] = float(vl.loc[key])
print(f"  streaming pass done in {time.perf_counter() - t0:.1f} s")
print(f"  peak |I| = {peak * 1e6:.3f} uA")

rows = []
for (c, s), a in sorted(acc.items()):
    med = a["sum"] / a["n"] if a["n"] else float("nan")
    kind = "pulse" if abs(med) >= 0.5 * peak else "rest"
    rows.append((c, s, a["n"], (a["t1"] - a["t0"]) / 3600.0,
                 med * 1e6, a["vf"], a["vl"], kind))
print(f"\n  {len(rows)} (cycle, step) groups; cycles: "
      f"{sorted({r[0] for r in rows})}")
print(f"  {'cyc':>4} {'step':>5} {'rows':>10} {'hours':>7} "
      f"{'I_med[uA]':>10} {'V_first':>8} {'V_last':>8}  kind")
for r in rows[:60]:
    print(f"  {r[0]:>4} {r[1]:>5} {r[2]:>10} {r[3]:>7.3f} "
          f"{r[4]:>10.3f} {r[5]:>8.4f} {r[6]:>8.4f}  {r[7]}")
if len(rows) > 60:
    print(f"  ... {len(rows) - 60} more")
