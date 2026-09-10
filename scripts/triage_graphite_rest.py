"""Check quasi-equilibrium at the end of each rest (criterion: dV/dt < 1 mV/h)."""
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

DATA = Path("data")
f = DATA / "sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__p-ocv__RT.bdf.parquet"
df = pq.read_table(f).to_pandas()
df.columns = ["t", "unix", "I", "V", "cyc", "step", "Ah"]

print("每个静置段末尾 1 h 的 dV/dt（判据 < 1 mV/h）")
for (c, s), g in df.groupby(["cyc", "step"]):
    if abs(g.I.mean()) > 1e-9:
        continue
    g = g.sort_values("t")
    t_end = g.t.iloc[-1]
    tail = g[g.t >= t_end - 3600]
    if len(tail) < 10:
        continue
    dv = tail.V.iloc[-1] - tail.V.iloc[0]
    dt_h = (tail.t.iloc[-1] - tail.t.iloc[0]) / 3600
    rate = dv / dt_h * 1000  # mV/h
    print(f"  cyc{c} rest: V_end={tail.V.iloc[-1]:.4f} V | "
          f"dV={dv*1000:+.2f} mV over {dt_h:.2f} h -> {rate:+.2f} mV/h "
          f"{'PASS' if abs(rate) < 1.0 else 'FAIL'}")

print()
print("GITT 静置段末端 1 h 的 dV/dt（取前 3 个静置段）")
gf = DATA / "sintef__sintef-graphite-R2032-intelligent-063b77__20250514__gitt__RT.bdf.parquet"
pf = pq.ParquetFile(gf)
seen = 0
for i in range(pf.metadata.num_row_groups):
    t = pf.read_row_group(i, columns=["Test Time / s", "Current / A", "Voltage / V"]).to_pandas()
    t.columns = ["t", "I", "V"]
    rest = t[t.I.abs() < 1e-9]
    if len(rest) < 10:
        continue
    dv = rest.V.iloc[-1] - rest.V.iloc[0]
    dt_h = (rest.t.iloc[-1] - rest.t.iloc[0]) / 3600
    if dt_h < 0.5:
        continue
    rate = dv / dt_h * 1000
    print(f"  group{i}: V_end={rest.V.iloc[-1]:.4f} V | dV={dv*1000:+.2f} mV "
          f"over {dt_h:.2f} h -> {rate:+.2f} mV/h "
          f"{'PASS' if abs(rate) < 1.0 else 'FAIL'}")
    seen += 1
    if seen >= 3:
        break
