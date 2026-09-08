"""H1-B local probe: dump SINTEF metadata rows + p-ocv parquet schema/content.

Pure pandas/pyarrow — NO pybamm import. Run inside WSL pybamm env.
"""
import sys

import pandas as pd

ROOT = "/mnt/c/Users/24330/WorkBuddy/仿真模拟"
META = ROOT + "/data/raw/LIB/LFP_LiMetal/SINTEF_R2032/meta/metadata.csv"
RAW = (
    ROOT + "/data/raw/LIB/LFP_LiMetal/SINTEF_R2032/raw/"
    + "sintef__sintef-lfp-R2032-gelon-d07eb6__20250602__p-ocv__RT.bdf.parquet"
)

print("=" * 80)
print("metadata.csv")
print("=" * 80)
mdf = pd.read_csv(META)
print("shape:", mdf.shape)
print("columns:", list(mdf.columns))
# find rows that refer to our parquet token d07eb6
mask = mdf.apply(lambda r: r.astype(str).str.contains("d07eb6|p-ocv|LFP", case=False, na=False).any(), axis=1)
print("rows mentioning d07eb6/p-ocv/LFP:", int(mask.sum()))
sel = mdf[mask]
for i, r in sel.iterrows():
    print("-" * 80)
    print("row index:", i)
    for c in mdf.columns:
        v = r[c]
        if pd.notna(v) and str(v).strip() != "":
            print(f"  {c:<46} {str(v)[:400]}")

print()
print("=" * 80)
print("p-ocv parquet")
print("=" * 80)
df = pd.read_parquet(RAW)
print("shape:", df.shape)
print("columns:", list(df.columns))
print("dtypes:\n", df.dtypes)
print()
print("first 5 rows:")
print(df.head(5).to_string())
print()
print("last 3 rows:")
print(df.tail(3).to_string())
for c in df.columns:
    s = df[c]
    if pd.api.types.is_numeric_dtype(s):
        print(f"  {c:<32} min={s.min():.9g}  max={s.max():.9g}  nunique={s.nunique()}")
    else:
        print(f"  {c:<32} nunique={s.nunique()}  sample={list(s.dropna().unique())[:8]}")
