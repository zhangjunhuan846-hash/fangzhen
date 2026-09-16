"""G6.1a step 1 -- select a clean pulse-rest window from the DLR GITT.

Plan C wanted a SINTEF graphite GITT pulse as the positive control for
the function-valued D_s(x) activation gate.  The SINTEF `gitt` file
turned out not to contain a pulse train at all (see
docs/g6.1a_gitt_protocol_audit.md), so the control has to come from the
one real GITT dataset on disk: the DLR Hydra.0b Li||graphite GITT at
25 degC, Basytec export.

The file is a phase log: every row carries a `Command`
(Pause / Charge / Discharge), so a pulse-rest triplet is
    Pause -> Discharge -> Pause
and nothing has to be inferred from step numbering.

This ranks those triplets and prints the chosen one, so the window is
selected by a stated criterion rather than by eye.

Ranking criterion -- for a diffusivity activation gate the window must
show a LARGE, well-resolved diffusion transient, so the score is the
pulse overvoltage |dV_pulse| combined with the relaxation amplitude
|dV_relax|.  Windows that touch the voltage cut-offs are excluded,
because there the model is being asked to reproduce clipping rather
than transport.

Usage:
    python scripts/graphite/select_dlr_gitt_window.py [--top 12] [--pulse 240]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DATA = ROOT / "data"
FILE = "DLR__LiGrHydra0b__20221114__GITT__25degC__Basytec.txt"

COLS = ["Time_h", "DataSet", "t_Set_h", "Line", "Command", "U_V", "I_A",
        "Ah_per_kg", "Ah_Charge", "Ah_Discharge", "Ah_Step", "Ah_Step_kg",
        "Ah_Set", "Ah_Set_kg", "T1_C", "Cyc_Count", "State"]

LOW_CUT = 0.015      # V -- below this the pulse is clipped at the cut-off
HIGH_CUT = 1.00      # V -- above this likewise


def load() -> pd.DataFrame:
    # The Basytec export is LATIN-1, not UTF-8: the header carries a
    # degree sign (0xb0) in "T1[°C]" and the decoder stops there.
    df = pd.read_csv(DATA / FILE, comment="~", sep=r"\s+", names=COLS,
                     header=None, engine="python", encoding="latin-1")
    df = df[COLS]
    df["t_s"] = df["Time_h"].astype(float) * 3600.0
    df["Command"] = df["Command"].astype(str)
    return df


def segments(df: pd.DataFrame) -> pd.DataFrame:
    """One row per contiguous run of the same Command."""
    ch = df["Command"].to_numpy()
    brk = np.r_[0, np.flatnonzero(ch[1:] != ch[:-1]) + 1, len(ch)]
    rows = []
    for i in range(len(brk) - 1):
        g = df.iloc[brk[i]:brk[i + 1]]
        rows.append({
            "command": str(g["Command"].iloc[0]),
            "i0": int(brk[i]),
            "i1": int(brk[i + 1]) - 1,
            "t0": float(g["t_s"].iloc[0]),
            "t1": float(g["t_s"].iloc[-1]),
            "dur_s": float(g["t_s"].iloc[-1] - g["t_s"].iloc[0]),
            "n": int(len(g)),
            "mean_I": float(g["I_A"].astype(float).mean()),
            "V0": float(g["U_V"].iloc[0]),
            "V1": float(g["U_V"].iloc[-1]),
            "Vmin": float(g["U_V"].astype(float).min()),
            "Vmax": float(g["U_V"].astype(float).max()),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--pulse", type=int, default=240,
                    help="index of the ranked triplet to print in full")
    args = ap.parse_args()

    df = load()
    seg = segments(df)
    print(f"file      : {FILE}")
    print(f"rows      : {len(df):,}")
    print(f"segments  : {len(seg)}")
    print(f"commands  : {seg['command'].value_counts().to_dict()}\n")

    # ---- pulse-rest triplets: Pause -> Discharge -> Pause -----------
    trip = []
    for k in range(1, len(seg) - 1):
        a, b, c = seg.iloc[k - 1], seg.iloc[k], seg.iloc[k + 1]
        if (a["command"] == "Pause" and b["command"] == "Discharge"
                and c["command"] == "Pause"):
            if b["Vmin"] < LOW_CUT or b["Vmax"] > HIGH_CUT:
                continue
            dv_pulse = b["V1"] - b["V0"]
            dv_relax = c["V1"] - b["V1"]
            trip.append({
                "k": k,
                "t_pulse_start": b["t0"],
                "pulse_s": b["dur_s"],
                "I_A": b["mean_I"],
                "V_start": b["V0"],
                "dV_pulse_mV": dv_pulse * 1000.0,
                "dV_relax_mV": dv_relax * 1000.0,
                "rest_s": c["dur_s"],
                "n_pulse": b["n"],
                "n_rest": c["n"],
                "score_mV": abs(dv_pulse) * 1000.0 + abs(dv_relax) * 1000.0,
            })
    tt = pd.DataFrame(trip)
    print(f"usable pulse-rest triplets (cut-offs excluded): {len(tt)}\n")
    if tt.empty:
        return 1

    cols = ["k", "t_pulse_start", "pulse_s", "I_A", "V_start",
            "dV_pulse_mV", "dV_relax_mV", "rest_s", "score_mV"]
    print(f"top {args.top} by |dV_pulse| + |dV_relax|:")
    print(tt.nlargest(args.top, "score_mV")[cols]
          .to_string(index=False, float_format=lambda v: f"{v:12.4f}"))
    print()
    print("and the same table sorted by pulse index, every 20th:")
    print(tt.iloc[::20][cols]
          .to_string(index=False, float_format=lambda v: f"{v:12.4f}"))
    print()

    if args.pulse < len(tt):
        row = tt.iloc[args.pulse]
        k = int(row["k"])
        a, b, c = seg.iloc[k - 1], seg.iloc[k], seg.iloc[k + 1]
        lo, hi = int(a["i0"]), int(c["i1"])
        print(f"=== triplet #{args.pulse}: rest {a['dur_s']:.0f} s -> "
              f"pulse {b['dur_s']:.0f} s @ {b['mean_I']:.4e} A -> "
              f"rest {c['dur_s']:.0f} s ===")
        w = df.iloc[lo:hi + 1]
        print(f"rows in window: {len(w)}, "
              f"t {w['t_s'].iloc[0]:.0f} .. {w['t_s'].iloc[-1]:.0f} s")
        print(w[["t_s", "Command", "U_V", "I_A", "T1_C"]]
              .iloc[:: max(1, len(w) // 40)]
              .to_string(index=False, float_format=lambda v: f"{v:12.5f}"))

    out = ROOT / "outputs" / "graphite"
    out.mkdir(parents=True, exist_ok=True)
    tt.to_csv(out / "dlr_gitt_pulse_windows.csv", index=False)
    print(f"\nwrote {out / 'dlr_gitt_pulse_windows.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
