"""H1 audit helper (structural pass).

Segment / boundary / sampling statistics for each Birmingham CSV.

Inspection-only; does NOT write adapters, does NOT import battery_sim.
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = str(Path(__file__).resolve().parents[2] / "data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw")


def _fmt(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}g}"


def summarize(df: pd.DataFrame, name: str) -> None:
    t = df["Time [s]"].to_numpy(float)
    v = df["Voltage [V]"].to_numpy(float)
    i = df["Current [mA]"].to_numpy(float)
    cap = (
        df["Capacity [mAh]"].to_numpy(float)
        if "Capacity [mAh]" in df.columns
        else np.full_like(t, np.nan)
    )
    has_step = "Step" in df.columns
    step = df["Step"].to_numpy(float) if has_step else None

    print("=" * 78)
    print(f"FILE: {name}   rows={len(df)}  t_span_s={_fmt(t[-1]-t[0])}")
    if has_step:
        # per-step table
        print(f"  columns: {list(df.columns)}")
        print(f"  {'step':>4} {'t_start_s':>14} {'dur_s':>12} {'I_lo':>9} {'I_hi':>9}"
              f" {'mean|I|':>9} {'V_lo':>8} {'V_hi':>8} {'cap0':>8} {'cap1':>8} {'n':>6}")
        for s, g in df.groupby("Step"):
            tt = g["Time [s]"].to_numpy(float)
            vv = g["Voltage [V]"].to_numpy(float)
            ii = g["Current [mA]"].to_numpy(float)
            cc = g["Capacity [mAh]"].to_numpy(float)
            print(f"  {s:>4.0f} {tt[0]:>14.3f} {tt[-1]-tt[0]:>12.3f} {ii.min():>9.3f}"
                  f" {ii.max():>9.3f} {np.abs(ii).mean():>9.3f} {vv.min():>8.4f}"
                  f" {vv.max():>8.4f} {cc[0]:>8.4f} {cc[-1]:>8.4f} {len(g):>6}")
    # segment detection: active current = |I| > 1e-6 mA
    act = np.abs(i) > 1e-6
    if act.any():
        edges = np.where(np.diff(act.astype(int)) != 0)[0] + 1
        bounds = np.concatenate([[0], edges, [len(df)]])
        print("  active-current segments (|I|>1e-6 mA):")
        print(f"    {'seg':>3} {'t_start':>12} {'dur_s':>11} {'I_mean':>9} {'I_lo':>9}"
              f" {'I_hi':>9} {'V_lo':>8} {'V_hi':>8} {'dQ_col_mAh':>11} {'dt_med_ms':>10} {'dt_min_ms':>9}")
        segno = 0
        for a, b in zip(bounds[:-1], bounds[1:]):
            if not act[a]:
                continue
            segno += 1
            ii = i[a:b]
            tt = t[a:b]
            vv = v[a:b]
            cc = cap[a:b]
            dtt = np.diff(tt)
            # coulomb integral of current (mA*s)/3600 = mAh
            dq_int = np.trapezoid(ii, tt) / 3600.0 if len(tt) > 1 else 0.0
            print(f"    {segno:>3} {tt[0]:>12.3f} {tt[-1]-tt[0]:>11.3f} {ii.mean():>9.3f}"
                  f" {ii.min():>9.3f} {ii.max():>9.3f} {vv.min():>8.4f} {vv.max():>8.4f}"
                  f" {cc[-1]-cc[0]:>11.4f} {np.median(dtt)*1e3:>10.3f} {dtt.min()*1e3:>9.3f}")
    else:
        print("  NO active-current segment found (all |I|<=1e-6 mA)")

    # global voltage/current sanity
    print(f"  global: V in [{v.min():.4f}, {v.max():.4f}]  I in [{i.min():.4f},"
          f" {i.max():.4f}]  T unique: {np.unique(df['Temperature [K]'])}")
    # sign-vs-slope check within active discharge segments (I<0 while V falling => discharge negative)
    mask = act & np.concatenate([[False], np.diff(v) < -1e-5])
    if mask.sum() > 0:
        print(f"  sign check: rows with V falling (dV<-1e-5) while active: {mask.sum()};"
              f" mean I there = {i[mask].mean():.4f} mA"
              f"  -> {'discharge NEGATIVE' if i[mask].mean() < 0 else 'discharge POSITIVE?'}")


def main() -> int:
    files = sorted(glob.glob(os.path.join(BASE, "*.csv")))
    for p in files:
        name = os.path.basename(p)
        df = pd.read_csv(p)
        summarize(df, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
