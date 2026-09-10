"""GITT pulse structure + ISU-UConn data presence check."""
from pathlib import Path
from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

DATA = Path("data")

print("=== SINTEF GITT 起始段脉冲结构（前 6 个 row group）===")
pf = pq.ParquetFile(DATA / "sintef__sintef-graphite-R2032-intelligent-063b77__20250514__gitt__RT.bdf.parquet")
cols = ["Test Time / s", "Current / A", "Voltage / V"]
t = pa.concat_tables(
    [pf.read_row_group(i, columns=cols) for i in range(6)]
)
df = t.to_pandas()
df.columns = ["t", "I", "V"]
print("  rows read:", len(df), "| duration:", round(df.t.max() - df.t.min(), 1), "s =",
      round((df.t.max() - df.t.min()) / 3600, 2), "h")
cur = df.I.round(7)
levels = sorted(set(cur.unique().tolist()), key=abs)
print("  电流档位（A，取整到 1e-7）:", levels[:8])
seg = (cur != cur.shift()).cumsum()
grp = df.assign(Ibin=cur).groupby(["Ibin"], sort=False).agg(
    n=("t", "size"), dt=("t", lambda x: x.max() - x.min())
)
tmp = df.assign(Ibin=cur, seg=seg)
runs = tmp.groupby("seg").agg(I=("Ibin", "first"), n=("t", "size"),
                              dt=("t", lambda x: x.max() - x.min()),
                              V0=("V", "first"), V1=("V", "last"))
print("  前 14 段（每段 = 一个恒流/静置段）:")
print(runs.head(14).to_string())

print()
print("=== ISU-UConn 数据文件是否存在 ===")
hits = [p for p in DATA.rglob("*") if "uconn" in p.name.lower() or "isu" in p.name.lower()]
print("  命中:", [str(p) for p in hits] or "只有 README，没有数据文件")
for d in ("raw", "processed"):
    print(f"  {d}/ 下前 8 项:", [p.name for p in sorted((DATA / d).glob('*'))][:8])

print()
print("=== DLR 文件规模 ===")
p = DATA / "DLR__LiGrHydra0b__20221114__GITT__25degC__Basytec.txt"
n = 0
with p.open("r", encoding="utf-8", errors="replace") as fh:
    for _ in fh:
        n += 1
print("  行数:", n, "| 大小 MB:", round(p.stat().st_size / 1e6, 1))
