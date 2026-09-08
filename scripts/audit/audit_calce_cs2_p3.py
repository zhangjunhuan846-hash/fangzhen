"""Step 12 audit part 3: Info sheet content + chronology check (read-only)."""
import os
import re

import pandas as pd

CELL_DIR = "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw/CS2_33"
files = os.listdir(CELL_DIR)

# chronological order via filename date M_D_YY
def sort_key(name):
    m = re.search(r"CS2_33_(\d+)_(\d+)_(\d+)", name)
    if not m:
        return (0, 0.0, 0.0)
    mo, d, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (2000 + yr if yr < 50 else 1900 + yr, mo, d)

chrono = sorted(files, key=sort_key)
print("chronological first 5:", chrono[:5])
print("chronological last 3:", chrono[-3:])

# Info sheet content of first file
f = chrono[0]
xl = pd.ExcelFile(os.path.join(CELL_DIR, f))
info = xl.parse("Info", header=None)
print(f"\n=== Info sheet of {f} ===")
for _, row in info.iterrows():
    vals = [str(v) for v in row.tolist() if str(v) != "nan"]
    if vals:
        print(" | ".join(vals[:8]))

# first rows of channel sheet (what is the initial state?)
df = xl.parse(next(s for s in xl.sheet_names if "Channel" in s))
print("\nfirst 3 data rows:")
print(df.head(3)[["Test_Time(s)", "Step_Index", "Cycle_Index", "Current(A)", "Voltage(V)"]].to_string(index=False))
