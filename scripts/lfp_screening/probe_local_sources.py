"""H1-A local evidence probe: SINTEF LFP||Li parquet + PyBaMM_Reference tree."""
import os
import sys

import pandas as pd

ROOT = r"/mnt/c/Users/24330/WorkBuddy/仿真模拟"

SINTEF = (
    ROOT
    + "/data/raw/LIB/LFP_LiMetal/SINTEF_R2032/raw/"
    + "sintef__sintef-lfp-R2032-gelon-d07eb6__20250602__p-ocv__RT.bdf.parquet"
)

print("=" * 78)
print("SINTEF R2032 LFP||Li  parquet probe")
print("=" * 78)
df = pd.read_parquet(SINTEF)
print("shape:", df.shape)
print("columns:", list(df.columns))
print("dtypes:\n", df.dtypes)
print("\nfirst 3 rows:\n", df.head(3).to_string())
print("\ntail 2 rows:\n", df.tail(2).to_string())
for c in df.columns:
    if df[c].dtype.kind in "fc":
        print(f"  {c:<28} min={df[c].min():.6g}  max={df[c].max():.6g}")
    elif df[c].dtype.kind == "O":
        print(f"  {c:<28} nunique={df[c].nunique()}  sample={list(df[c].dropna().unique())[:6]}")

# time column guess
tcol = next((c for c in df.columns if "time" in c.lower()), None)
if tcol is not None:
    t = pd.to_numeric(df[tcol], errors="coerce")
    print(f"\n[{tcol}] span = {t.min():.3f} .. {t.max():.3f}  n={t.notna().sum()}")

print("\n" + "=" * 78)
print("PyBaMM_Reference / pybamm-data tree")
print("=" * 78)
base = ROOT + "/data/raw/LIB/PyBaMM_Reference"
for dirpath, dirnames, filenames in os.walk(base):
    depth = dirpath.replace(base, "").count(os.sep)
    if depth <= 2:
        rel = os.path.relpath(dirpath, base)
        n = len(filenames)
        print(f"{rel}/  ({n} files)")
        for f in sorted(filenames)[:8]:
            print("   -", f)
        if n > 8:
            print(f"    ... (+{n-8} more)")
