"""H2 identity check: our Birmingham raw rate files vs the author's saved
model-vs-experiment CSVs (external/Jackowska-2025-JPS/2mAh_cm2/results/*_discharge.csv).

The repo CSVs contain columns Time/Current/Discharge capacity/Voltage/Absolute error.
The author's script (figure_5.py) built these by replaying the experimental current
and computing  error[i] = |V_exp[i] - V_sim[i]|  over the *same* experimental rows.
If our downloaded raw file is the same underlying dataset, then row-by-row
    |V_ours[i] - V_sim[i]|  should reproduce the stored Absolute error,
and row counts after drop_duplicates should match.

Inspection-only; does not touch battery_sim.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RAW = "/mnt/c/Users/24330/WorkBuddy/仿真模拟/data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw"
RES = "/mnt/c/Users/24330/WorkBuddy/仿真模拟/external/Jackowska-2025-JPS/2mAh_cm2/results"

PAIRS = [
    ("RateCapability_Cover10_2mAhcm_2_NCM920305.csv", "C_10_discharge.csv"),
    ("RateCapability_Cover5_2mAhcm_2_NCM920305.csv", "C_5_discharge.csv"),
    ("RateCapability_Cover2_2mAhcm_2_NCM920305.csv", "C_2_discharge.csv"),
    ("RateCapability_1C_2mAhcm_2_NCM920305.csv", "1C_discharge.csv"),
    ("RateCapability_2C_2mAhcm_2_NCM920305.csv", "2C_discharge.csv"),
]


def main() -> int:
    print(f"{'rate':>8} {'ours_n':>7} {'repo_n':>7} {'matched_n':>10}"
          f" {'med|Δerr|':>10} {'p95|Δerr|':>10} {'max|Δerr|':>10}")
    for raw_name, res_name in PAIRS:
        df_ours = pd.read_csv(os.path.join(RAW, raw_name)).drop_duplicates(
            subset=["Time [s]"], keep="first").reset_index(drop=True)
        df_repo = pd.read_csv(os.path.join(RES, res_name))
        v_ours = df_ours["Voltage [V]"].to_numpy(float)
        v_sim = df_repo["Voltage [V]"].to_numpy(float)
        err = df_repo["Absolute error [V]"].to_numpy(float)
        n = min(len(v_ours), len(v_sim))
        delta = np.abs(np.abs(v_ours[:n] - v_sim[:n]) - err[:n])
        print(f"{raw_name.split('RateCapability_')[1][:6]:>8} {len(df_ours):>7}"
              f" {len(df_repo):>7} {n:>10} {np.median(delta)*1e3:>10.4f}"
              f" {np.percentile(delta,95)*1e3:>10.4f} {delta.max()*1e3:>10.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
