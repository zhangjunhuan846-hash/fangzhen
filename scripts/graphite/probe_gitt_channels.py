"""G6.1a step 0f -- what does each concurrent channel actually read?

The occupancy map proved three step channels log the same instants at
very different rates (8.14 Hz / 0.076 Hz / 0.163 Hz).  To decide what
the file MEANS, compare the channels at the same instant: if the
high-rate channel (step 2) and the applied-current channel (step 4)
report the same voltage at the same time, they are one signal logged
twice; if not, they are different quantities.

Prints, per narrow time window in the requested cycle, the median
voltage and median current of every step present in that window.

Usage:
    python scripts/graphite/probe_gitt_channels.py --cycle 1 --windows 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

DATA = ROOT / "data"
BATCH = 1 << 18
COLS = ["Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
        "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*gitt__RT.bdf.parquet")
    ap.add_argument("--cycle", type=int, default=1)
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--width", type=float, default=600.0,
                    help="window width in seconds")
    args = ap.parse_args()

    matches = sorted(DATA.glob("sintef__" + args.glob))
    path = matches[0]
    print(f"file : {path.name}\n")

    import pyarrow.parquet as pq

    # centre the windows inside each half of the cycle
    centres = [60000 + i * 60000 for i in range(args.windows // 2)] + \
              [1200000 + i * 60000 for i in range(args.windows // 2)]

    # per (window, step): collect V and I
    store: dict[tuple[int, int], list] = {}
    for batch in pf_iter(path):
        df = batch.to_pandas()
        m = df["Cycle Count / 1"].to_numpy(np.int64) == args.cycle
        if not m.any():
            continue
        sub = df.loc[m]
        tt = sub["Test Time / s"].to_numpy(float)
        stp = sub["Step Index / 1"].to_numpy(np.int64)
        vv = sub["Voltage / V"].to_numpy(float)
        ii = sub["Current / A"].to_numpy(float)
        for wi, c in enumerate(centres):
            sel = (tt >= c) & (tt < c + args.width)
            if not sel.any():
                continue
            for s in np.unique(stp[sel]):
                sm = sel & (stp == s)
                store.setdefault((wi, int(s)), []).append(
                    (float(np.median(vv[sm])), float(np.median(ii[sm])),
                     int(sm.sum())))

    print(f"cycle {args.cycle}, windows of {args.width:.0f} s\n")
    for wi, c in enumerate(centres):
        steps = sorted(s for (w, s) in store if w == wi)
        if not steps:
            print(f"--- window at t={c:.0f} s : nothing")
            continue
        print(f"--- window at t={c:.0f} s ({c / 86400:.2f} d)")
        for s in steps:
            vals = store[(wi, s)]
            v = float(np.median([x[0] for x in vals]))
            i = float(np.median([x[1] for x in vals]))
            n = int(sum(x[2] for x in vals))
            print(f"      step {s:>3}  n={n:>7}  median V={v:10.5f}  "
                  f"median I={i:+.5e}")
        print()
    return 0


def pf_iter(path):
    import pyarrow.parquet as pq

    return pq.ParquetFile(path).iter_batches(batch_size=BATCH, columns=COLS)


if __name__ == "__main__":
    raise SystemExit(main())
