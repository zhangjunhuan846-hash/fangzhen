"""Check the semantics of the 'Cumulative Capacity / Ah' column in SINTEF p-OCV."""
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

F = Path("data/sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__p-ocv__RT.bdf.parquet")
df = pq.read_table(F).to_pandas()
df.columns = ["t", "unix", "I", "V", "cyc", "step", "Ah"]

print("cycle step | I_med[uA] | V0     V1     | dt[h] | d(Ah)   | I*dt/3.6[mAh] | Ah_col_first last")
for (c, s), g in df.groupby(["cyc", "step"]):
    g = g.sort_values("t")
    dt = (g.t.iloc[-1] - g.t.iloc[0]) / 3600
    q_int = np.trapezoid(g.I.to_numpy(float), g.t.to_numpy(float)) / 3.6
    print(f"  {c}   {s}  | {g.I.median()*1e6:8.2f} | {g.V.iloc[0]:.4f} {g.V.iloc[-1]:.4f} | "
          f"{dt:6.2f} | {g.Ah.iloc[-1]-g.Ah.iloc[0]:8.4f} | {q_int:10.4f}     | "
          f"{g.Ah.iloc[0]:.4f} {g.Ah.iloc[-1]:.4f}")

seg = df[(df.cyc == 1) & (df.step == 4)].sort_values("t")
print()
print("cyc1 step4 (delithiation) 前 3 / 后 3 行：")
print(seg.head(3).to_string(index=False))
print(seg.tail(3).to_string(index=False))
print("采样间隔中位数 [s]:", float(np.median(np.diff(seg.t.to_numpy(float)))))
