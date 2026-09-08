"""Step 12 audit: inspect CALCE CS2 xlsx file structure (read-only)."""
import os
import sys

import pandas as pd

CELL_DIR = sys.argv[1] if len(sys.argv) > 1 else (
    "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw/CS2_33"
)

files = sorted(f for f in os.listdir(CELL_DIR) if f.endswith(".xlsx"))
f = files[0]
path = os.path.join(CELL_DIR, f)
print(f"file: {f}  ({len(files)} xlsx in cell dir)")
print(f"size: {os.path.getsize(path)/1e6:.2f} MB")

xl = pd.ExcelFile(path)
print("sheets:", xl.sheet_names)

for sheet in xl.sheet_names:
    head = xl.parse(sheet, nrows=3)
    print(f"\n--- sheet '{sheet}': cols={list(head.columns)}")

# Main record sheet deep dive
rec_name = next(s for s in xl.sheet_names if "Channel" in s)
df = xl.parse(rec_name)
print(f"\n=== '{rec_name}' full: {len(df)} rows ===")
print("dtypes:\n", df.dtypes)
print("\nCycle_Index range:", df["Cycle_Index"].min(), "-", df["Cycle_Index"].max())
print("Step_Index range:", df["Step_Index"].min(), "-", df["Step_Index"].max())
print("Current range: %.4f .. %.4f A" % (df["Current(A)"].min(), df["Current(A)"].max()))
print("Voltage range: %.4f .. %.4f V" % (df["Voltage(V)"].min(), df["Voltage(V)"].max()))
if "Test_Time(s)" in df.columns:
    print("Test_Time max: %.0f s (%.1f h)" % (df["Test_Time(s)"].max(), df["Test_Time(s)"].max() / 3600))
print("\nStep table (first 30 steps):")
step_tbl = (
    df.groupby(["Cycle_Index", "Step_Index"])["Current(A)"]
    .agg(["mean", "min", "max", "count"])
    .reset_index()
)
step_tbl["V_end"] = df.groupby(["Cycle_Index", "Step_Index"])["Voltage(V)"].last().values
print(step_tbl.head(30).to_string(index=False))
