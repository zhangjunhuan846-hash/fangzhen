"""H1 audit helper (slice pass): pOCV/EIS details + rest segments of rate files."""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = str(Path(__file__).resolve().parents[2] / "data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw")
ACT = 1e-6


def rate_detail(name: str) -> None:
    df = pd.read_csv(os.path.join(BASE, name))
    t = df["Time [s]"].to_numpy(float)
    v = df["Voltage [V]"].to_numpy(float)
    i = df["Current [mA]"].to_numpy(float)
    act = np.abs(i) > ACT
    idx = np.where(act)[0]
    a0, a1 = idx[0], idx[-1]
    print(f"[{name}] rest_before_s={t[a0]-t[0]:.3f}  rest_after_s={t[-1]-t[a1]:.3f}"
          f"  n_rest_rows={len(df)-len(idx)}")
    # plateau subset: |I| within 1% of median |I| during active
    ia = np.abs(i[act])
    med = np.median(ia)
    plat = act & (np.abs(i) > 0.99 * med)
    p0, p1 = np.where(plat)[0][0], np.where(plat)[0][-1]
    print(f"   plateau I_med={med:.5f} mA  plateau_rows={plat.sum()}/{len(df)}"
          f"  plateau_V_start={v[p0]:.4f}  plateau_V_end={v[p1]:.4f}"
          f"  plateau_t_dur_s={t[p1]-t[p0]:.3f}"
          f"  plateau_cutoff_hit={v[p1]:.4f} (min V={v[act].min():.4f})")
    print(f"   last-active rows: t={t[a1-2]:.3f},{t[a1-1]:.3f},{t[a1]:.3f}"
          f" V={v[a1-2]:.4f},{v[a1-1]:.4f},{v[a1]:.4f}"
          f" I={i[a1-2]:.4f},{i[a1-1]:.4f},{i[a1]:.4f}")
    # dt histogram
    dtt = np.diff(t)
    print(f"   dt_s: min={dtt.min():.4f} p1={np.percentile(dtt,1):.4f}"
          f" med={np.median(dtt):.4f} p99={np.percentile(dtt,99):.4f} max={dtt.max():.4f}")


def pocv_detail(name: str) -> None:
    df = pd.read_csv(os.path.join(BASE, name))
    print(f"[{name}] rows={len(df)} cols={list(df.columns)}")
    print(f"   step boundaries:")
    for s, g in df.groupby("Step"):
        tt = g["Time [s]"].to_numpy(float)
        vv = g["Voltage [V]"].to_numpy(float)
        ii = g["Current [mA]"].to_numpy(float)
        cc = g["Capacity [mAh]"].to_numpy(float)
        print(f"   step {s:>2.0f}: t {tt[0]:>12.3f}..{tt[-1]:>12.3f} dur={tt[-1]-tt[0]:>10.2f}"
              f" I=[{ii.min():+.4f},{ii.max():+.4f}] mean|I|={np.abs(ii).mean():.5f}"
              f" V=[{vv.min():.4f},{vv.max():.4f}] cap=[{cc[0]:.4f},{cc[-1]:.4f}] n={len(g)}")


def main() -> int:
    for n in ["RateCapability_Cover10_2mAhcm_2_NCM920305.csv",
              "RateCapability_Cover5_2mAhcm_2_NCM920305.csv",
              "RateCapability_Cover2_2mAhcm_2_NCM920305.csv",
              "RateCapability_1C_2mAhcm_2_NCM920305.csv",
              "RateCapability_2C_2mAhcm_2_NCM920305.csv"]:
        rate_detail(n)
        print()
    pocv_detail("pOCV_2mAhcm_2_NCM920305.csv")
    eis = pd.read_csv(os.path.join(BASE, "SOC50_25deg_EIS_2mAhcm_2_NCM920305.csv"))
    print(f"\n[EIS] rows={len(eis)} cols={list(eis.columns)}")
    print(eis.head(3).to_string(index=False))
    print("...")
    print(eis.tail(3).to_string(index=False))
    # EIS duplicate frequencies?
    f = eis["Frequency [Hz]"].to_numpy(float)
    print(f"   freq sweep: n={len(f)} min={f.min():.4f} Hz max={f.max():.2f} Hz"
          f" distinct={len(np.unique(f))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
