# -*- coding: utf-8 -*-
"""v0.3 Step 18: CALCE INR18650-20R dynamic protocol data audit (read-only).

Runs inside WSL pybamm env. No files are modified; outputs JSON to stdout.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path("/mnt/c/Users/24330/WorkBuddy/仿真模拟/data/raw/LIB/NMC_Graphite/CALCE_INR18650_20R")
RAW = BASE / "raw"
OUT = Path("/mnt/c/Users/24330/WorkBuddy/仿真模拟/outputs/audit")
OUT.mkdir(parents=True, exist_ok=True)


def audit_sheet(xl, sheet_name):
    df = xl.parse(sheet_name)
    info = {"rows": int(len(df)), "columns": [str(c) for c in df.columns]}
    return info, df


def audit_file(path):
    res = {"file": path.name, "size_bytes": path.stat().st_size}
    xl = pd.ExcelFile(path)
    res["sheets"] = xl.sheet_names
    # pick the sheet that looks like the data table
    chosen = None
    for s in xl.sheet_names:
        info, df = audit_sheet(xl, s)
        res.setdefault("sheet_summaries", {})[s] = info
        cols_lower = {str(c).lower() for c in df.columns}
        if any("current" in c for c in cols_lower) and any("voltage" in c for c in cols_lower):
            chosen = s
            break
    if chosen is None:
        res["data_sheet"] = None
        return res
    res["data_sheet"] = chosen
    df = xl.parse(chosen)
    res["columns"] = [str(c) for c in df.columns]
    res["dtypes"] = {str(c): str(df[c].dtype) for c in df.columns}
    res["head"] = df.head(5).astype(str).to_dict(orient="records")

    # locate time / current / voltage columns
    colmap = {}
    for c in df.columns:
        cl = str(c).lower()
        if "test_time" in cl or cl == "time/s" or "time" in cl and "date" not in cl:
            colmap.setdefault("time", c)
        if cl.startswith("current") or "/a" in cl:
            colmap.setdefault("current", c)
        if cl.startswith("voltage") or "/v" in cl:
            colmap.setdefault("voltage", c)
        if "temperature" in cl:
            colmap.setdefault("temperature", cl)
        if "step" in cl or "cycle" in cl:
            colmap.setdefault("cycle_step", c)
    res["column_map"] = {k: str(v) for k, v in colmap.items()}

    tcol = colmap.get("time")
    icol = colmap.get("current")
    vcol = colmap.get("voltage")

    if tcol is not None:
        t = pd.to_numeric(df[tcol], errors="coerce")
        res["time_s"] = {
            "min": float(t.min()), "max": float(t.max()),
            "duration_s": float(t.max() - t.min()),
            "nan": int(t.isna().sum()),
            "n_dupe": int(t.duplicated().sum()),
            "monotonic_increasing": bool(t.is_monotonic_increasing),
            "n_negative_dt": int((t.diff().dropna() <= 0).sum()),
            "median_dt_s": float(t.diff().median()),
            "dt_p1_p99": [float(t.diff().quantile(0.01)), float(t.diff().quantile(0.99))],
            "min_dt": float(t.diff().min()),
            "max_dt": float(t.diff().max()),
        }
        # time resets (file concatenation)
        dt = t.diff()
        resets = df.index[dt < 0].tolist()
        res["time_reset_indices"] = resets[:20]
        res["n_time_resets"] = len(resets)
    if icol is not None:
        i = pd.to_numeric(df[icol], errors="coerce")
        res["current_A"] = {
            "min": float(i.min()), "max": float(i.max()),
            "mean": float(i.mean()), "nan": int(i.isna().sum()),
            "n_zero": int((i == 0).sum()),
            "rms": float(np.sqrt((i ** 2).mean())),
            "p99_discharge": float(i.quantile(0.99)),
            "p01": float(i.quantile(0.01)),
        }
        # integrated charge with raw sign
        if tcol is not None:
            t = pd.to_numeric(df[tcol], errors="coerce")
            res["integrated_charge_raw_sign_Ah"] = float(np.trapezoid(i.fillna(0), t.fillna(0)) / 3600.0)
    if vcol is not None:
        v = pd.to_numeric(df[vcol], errors="coerce")
        res["voltage_V"] = {
            "min": float(v.min()), "max": float(v.max()),
            "first": float(v.dropna().iloc[0]), "last": float(v.dropna().iloc[-1]),
            "nan": int(v.isna().sum()),
        }
    # cycle/step columns distinct values
    cs = colmap.get("cycle_step")
    if cs is not None:
        res["cycle_step_col"] = str(cs)
        res["n_unique_cycle_step"] = int(df[cs].nunique())
        res["cycle_step_head"] = [int(x) for x in df[cs].head(10)]
    return res


def main():
    report = {}
    for f in sorted(RAW.glob("*.xls")):
        try:
            report[f.name] = audit_file(f)
        except Exception as e:
            report[f.name] = {"error": repr(e)}
    # OCV xlsx quick structural peek
    for f in sorted(RAW.glob("*.xlsx")):
        try:
            xl = pd.ExcelFile(f)
            info = {"sheets": xl.sheet_names}
            s0 = xl.sheet_names[0]
            df = xl.parse(s0, nrows=3)
            info["first_sheet_cols"] = [str(c) for c in df.columns]
            info["first_sheet_head"] = df.astype(str).to_dict(orient="records")
            report[f.name] = info
        except Exception as e:
            report[f.name] = {"error": repr(e)}
    txt = json.dumps(report, indent=1, ensure_ascii=False, default=str)
    (OUT / "v03_step18_20r_audit.json").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    sys.exit(main())
