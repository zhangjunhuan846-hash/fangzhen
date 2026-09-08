"""Step 12 audit part 2: capacity check + file continuity (read-only)."""
import os

import pandas as pd

CELL_DIR = "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw/CS2_33"
files = sorted(f for f in os.listdir(CELL_DIR) if f.endswith(".xlsx"))

print("file                          rows  cycles  Q_dis_max(Ah)  V_min   last_date")
for f in [files[0], files[1], files[-1]]:
    df = pd.ExcelFile(os.path.join(CELL_DIR, f)).parse(
        next(s for s in pd.ExcelFile(os.path.join(CELL_DIR, f)).sheet_names if "Channel" in s)
    )
    dis = df[df["Discharge_Capacity(Ah)"] > 0]
    print(
        f"{f:29s} {len(df):5d}  {df['Cycle_Index'].max():3d}"
        f"  {dis['Discharge_Capacity(Ah)'].max():.4f}"
        f"  {df['Voltage(V)'].min():.3f}  {df['Date_Time'].max()}"
    )

# Full discharge profile of file[0] cycle 2 step 7
df = pd.ExcelFile(os.path.join(CELL_DIR, files[0])).parse("Channel_1-006")
seg = df[(df["Cycle_Index"] == 2) & (df["Step_Index"] == 7)]
print(f"\ncycle2/step7 discharge: {len(seg)} pts, "
      f"I={seg['Current(A)'].mean():.4f} A, "
      f"Q_end={seg['Discharge_Capacity(Ah)'].max():.4f} Ah, "
      f"V: {seg['Voltage(V)'].iloc[0]:.4f} -> {seg['Voltage(V)'].iloc[-1]:.4f}")
print(f"step7 duration: {(seg['Test_Time(s)'].iloc[-1]-seg['Test_Time(s)'].iloc[0]):.0f} s")
print(f"t sampling (first 5 dt): {list(seg['Test_Time(s)'].diff().dropna().head(5).round(1))}")
