# -*- coding: utf-8 -*-
"""v0.4 Step 28: CALCE A123 dynamic data audit (read-only)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("/mnt/c/Users/24330/WorkBuddy/仿真模拟/data/raw/LIB/LFP_Graphite/CALCE_A123/raw/DST-US06-FUDS-25")
OUT = Path("/mnt/c/Users/24330/WorkBuddy/仿真模拟/outputs/audit")
OUT.mkdir(parents=True, exist_ok=True)

report = {}
for path in sorted(RAW.glob("*.xlsx")):
    xl = pd.ExcelFile(path)
    r = {"file": path.name, "sheets": xl.sheet_names, "sheet_summaries": {}}
    data_sheet = None
    for s in xl.sheet_names:
        head = xl.parse(s, nrows=3)
        r["sheet_summaries"][s] = {"cols": [str(c) for c in head.columns]}
        cols_l = {str(c).lower() for c in head.columns}
        if "current" in " ".join(cols_l) or "test_time" in " ".join(cols_l):
            if data_sheet is None or s != "Info":
                if data_sheet is None:
                    data_sheet = s
    r["data_sheet"] = data_sheet
    df = xl.parse(data_sheet)
    r["n_rows"] = int(len(df))
    r["columns"] = [str(c) for c in df.columns]
    t = pd.to_numeric(df["Test_Time(s)"], errors="coerce")
    i = pd.to_numeric(df["Current(A)"], errors="coerce")
    v = pd.to_numeric(df["Voltage(V)"], errors="coerce")
    r["time"] = {
        "min": float(t.min()), "max": float(t.max()), "nan": int(t.isna().sum()),
        "n_dupe": int(t.duplicated().sum()),
        "monotonic": bool(t.is_monotonic_increasing),
        "n_nonincreasing": int((t.diff().dropna() <= 0).sum()),
        "median_dt": float(t.diff().median()),
        "max_dt": float(t.diff().max()), "min_dt": float(t.diff().min()),
    }
    resets = df.index[t.diff() < 0].tolist()
    r["n_time_resets"] = len(resets)
    r["time_reset_positions"] = resets[:20]
    r["current"] = {
        "min": float(i.min()), "max": float(i.max()), "nan": int(i.isna().sum()),
        "n_zero": int((i == 0).sum()),
        "p01": float(i.quantile(0.01)), "p99": float(i.quantile(0.99)),
    }
    r["voltage"] = {
        "min": float(v.min()), "max": float(v.max()), "nan": int(v.isna().sum()),
        "first": float(v.dropna().iloc[0]), "last": float(v.dropna().iloc[-1]),
    }
    # cycle structure
    cyc = df.groupby("Cycle_Index")
    rows = []
    for c, d in cyc:
        dd = d.sort_values("Test_Time(s)")
        tc = pd.to_numeric(dd["Test_Time(s)"], errors="coerce")
        ic = pd.to_numeric(dd["Current(A)"], errors="coerce")
        rows.append({
            "cycle": int(c), "n": int(len(d)),
            "dur_s": float(tc.max() - tc.min()),
            "I_min": float(ic.min()), "I_max": float(ic.max()),
            "I_rms": float(np.sqrt((ic ** 2).mean())),
            "V_min": float(pd.to_numeric(dd["Voltage(V)"], errors="coerce").min()),
            "V_max": float(pd.to_numeric(dd["Voltage(V)"], errors="coerce").max()),
            "Q_int_Ah": float(np.trapezoid(ic.fillna(0), tc.fillna(0)) / 3600.0),
            "steps": sorted(int(x) for x in dd["Step_Index"].unique())[:12],
        })
    r["cycles"] = rows
    # temperature column?
    r["has_temperature_col"] = [str(c) for c in df.columns if "temp" in str(c).lower()]
    report[path.name] = r

txt = json.dumps(report, indent=1, default=str)
(OUT / "v04_step28_a123_audit.json").write_text(txt, encoding="utf-8")

# compact print
for name, r in report.items():
    print("=" * 70)
    print(name, "| sheets:", r["sheets"], "| data:", r["data_sheet"], "| rows:", r["n_rows"])
    print(" cols:", r["columns"])
    print(" time:", {k: r["time"][k] for k in ["min", "max", "nan", "n_dupe", "monotonic", "n_nonincreasing", "median_dt", "max_dt", "min_dt"]})
    print(" time_resets:", r["n_time_resets"], r["time_reset_positions"][:10])
    print(" current:", r["current"])
    print(" voltage:", r["voltage"])
    print(" temp cols:", r["has_temperature_col"])
    print(" cycles:")
    for row in r["cycles"]:
        print("  cyc %3d n=%6d dur=%8.1fs I[%+.2f,%+.2f] rms=%.2f V[%.3f,%.3f] Q=%+.3f Ah steps=%s" % (
            row["cycle"], row["n"], row["dur_s"], row["I_min"], row["I_max"],
            row["I_rms"], row["V_min"], row["V_max"], row["Q_int_Ah"], row["steps"]))
