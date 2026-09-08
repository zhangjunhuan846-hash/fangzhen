# One-off provenance audit (D): step history preceding the
# auto-selected BOL discharge (cycle1/step7) in the first
# chronological file of CS2_33.
#
# Goal: prove step7 is a FULL discharge preceded by a complete
# charge -> CV -> rest protocol, not a partial segment caused by
# file splitting.
import numpy as np
import pandas as pd

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from battery_sim.registry import get_dataset

adapter = get_dataset("calce_cs2")

cell = "33"
files = adapter.cell_files(cell)
first = files[0]
print("first chronological file:", first.name)
print("file order:", [f.name for f in files[:3]], "...")
print()

df = adapter._load = __import__(
    "battery_sim.datasets.calce_cs2", fromlist=["load_calce_file"]
).load_calce_file(first)

nominal = 1.1
rows = []
for (cyc, step), seg in df.groupby(["cycle_index", "step_index"]):
    I = seg["current_A"].to_numpy(dtype=float)   # canonical: discharge +
    V = seg["voltage_V"].to_numpy(dtype=float)
    t = seg["time_s"].to_numpy(dtype=float)
    med = float(np.median(I))

    if med > 0.05 * nominal:       # strong positive -> discharge
        mode = "discharge"
    elif med < -0.05 * nominal:    # strong negative -> charge
        mode = "charge"
    elif len(seg) >= 10 and float(np.mean(np.diff(V))) < -1e-6 and med < 0:
        mode = "charge?"
    elif np.abs(I).max() < 0.05 * nominal:
        # long zero-current step = rest; negative tiny current
        # decaying = CV tail of the charge
        dur = t[-1] - t[0]
        if med < -0.005 and dur < 7200:
            mode = "CV(charge tail)"
        else:
            mode = "rest"
    else:
        mode = "other"

    rows.append(
        {
            "cycle": int(cyc),
            "step": int(step),
            "n_points": len(seg),
            "I_start_A": I[0],
            "I_end_A": I[-1],
            "I_median_A": med,
            "V_start_V": V[0],
            "V_end_V": V[-1],
            "duration_s": t[-1] - t[0],
            "inferred_mode": mode,
        }
    )

table = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(table.to_string(index=False))
print()

# The rule-based selection for cell33:
info = adapter.discharge_info(cell, "0p5C")
prov = info["provenance"]
print("rule-based selection:", prov)
print()

# Integrate capacity of the selected discharge and of the preceding
# charge for coulombic sanity
sel = df[
    (df["cycle_index"] == prov["cycle_index"])
    & (df["step_index"] == prov["step_index"])
].sort_values("time_s")
Q_dis = np.trapezoid(sel["current_A"], sel["time_s"]) / 3600.0
print(f"selected discharge integrated capacity: {Q_dis:.4f} Ah")

# find the immediately preceding charge (negative current) segment
before = table[(table["cycle"] <= prov["cycle_index"])]
hist = before[before["step"] < prov["step_index"]]
print()
print("steps preceding the selected discharge:")
print(hist.to_string(index=False))
