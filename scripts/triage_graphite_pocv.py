"""SINTEF p-OCV branch structure (lithiation / delithiation)."""
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

DATA = Path("data")
f = DATA / "sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__p-ocv__RT.bdf.parquet"
df = pq.read_table(f).to_pandas()
df.columns = ["t", "unix", "I", "V", "cyc", "step", "Ah"]

Q = 2.2  # mAh, rough cell capacity from metadata (1.43 mAh/cm2 x 1.54 cm2)

print("总行数:", len(df), "| 时长 d:", round(df.t.max() / 86400, 2))
print()
for (c, s), g in df.groupby(["cyc", "step"]):
    ich = g.I.mean()
    dt = g.t.max() - g.t.min()
    q = abs(ich) * dt / 3.6  # mAh
    print(f"  cyc{c} step{s}: I={ich*1e6:8.2f} uA | "
          f"V {g.V.min():.4f}..{g.V.max():.4f} | "
          f"dt={dt/3600:6.2f} h | |Q|={q:6.3f} mAh ({q/3.6*1000:.0f} uAh) | "
          f"{'lithiation' if ich < 0 else 'delithiation' if ich > 0 else 'rest'}")
