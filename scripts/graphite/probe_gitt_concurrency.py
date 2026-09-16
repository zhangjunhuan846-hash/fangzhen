"""G6.1a step 0d -- do two steps own the SAME instant?

Every 262144-row batch of the gitt parquet contains more than one step
index, and the per-group time ranges overlap (step 2 spans 14400 ->
2214137 s while step 4 spans 23400 -> 1137322 s).  Two step channels
cannot both be active at one instant in a single-cell cycler log, so the
occupancy has to be measured rather than argued about.

Builds a (step x time-bucket) occupancy table for one cycle.  If a time
bucket holds rows for two different steps, the file is interleaved and
grouping by (cycle, step) -- which is what the platform adapter does --
reads rows out of physical order.

Also prints the file's own wall-clock span per step, from the Unix Time
column, as an independent check on Test Time.

Usage:
    python scripts/graphite/probe_gitt_concurrency.py [--cycle 1] [--buckets 40]
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
    ap.add_argument("--cycle", type=int, default=1)
    ap.add_argument("--buckets", type=int, default=40)
    ap.add_argument("--glob", default="*gitt__RT.bdf.parquet")
    args = ap.parse_args()

    matches = sorted(DATA.glob("sintef__" + args.glob))
    path = matches[0]
    print(f"file : {path.name}")
    print(f"cycle: {args.cycle}\n")

    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)

    # pass 1: time range of the chosen cycle + per-step unix range
    t_lo, t_hi = np.inf, -np.inf
    step_unix: dict[int, list] = {}
    for batch in pf.iter_batches(batch_size=BATCH, columns=COLS):
        df = batch.to_pandas()
        m = df["Cycle Count / 1"].to_numpy(np.int64) == args.cycle
        if not m.any():
            continue
        sub = df.loc[m]
        tt = sub["Test Time / s"].to_numpy(float)
        t_lo = min(t_lo, float(tt.min()))
        t_hi = max(t_hi, float(tt.max()))
        stp = sub["Step Index / 1"].to_numpy(np.int64)
        un = sub["Unix Time / s"].to_numpy(float)
        for s in np.unique(stp):
            sm = stp == s
            lo = float(un[sm].min())
            hi = float(un[sm].max())
            d = step_unix.setdefault(int(s), [lo, hi, 0])
            d[0] = min(d[0], lo)
            d[1] = max(d[1], hi)
            d[2] += int(sm.sum())

    print(f"cycle {args.cycle} Test Time range: {t_lo:.1f} .. {t_hi:.1f} s "
          f"({(t_hi - t_lo) / 86400:.2f} days)")
    print(f"wall clock span: {min(d[0] for d in step_unix.values()):.0f} .. "
          f"{max(d[1] for d in step_unix.values()):.0f} (unix)")
    print()
    print("per-step: n_rows, Test-Time span (from the pass-1 range), "
          "unix span in days")
    for s in sorted(step_unix):
        lo, hi, n = step_unix[s]
        print(f"  step {s:>3}  n={n:>10,}  unix span {(hi - lo) / 86400:8.3f} d")
    print()

    # pass 2: occupancy (step x time bucket)
    nb = args.buckets
    width = (t_hi - t_lo) / nb
    occ: dict[int, np.ndarray] = {}
    vol: dict[int, list] = {}
    for batch in pf.iter_batches(batch_size=BATCH, columns=COLS):
        df = batch.to_pandas()
        m = df["Cycle Count / 1"].to_numpy(np.int64) == args.cycle
        if not m.any():
            continue
        sub = df.loc[m]
        tt = sub["Test Time / s"].to_numpy(float)
        stp = sub["Step Index / 1"].to_numpy(np.int64)
        vv = sub["Voltage / V"].to_numpy(float)
        b = np.clip(((tt - t_lo) / width).astype(int), 0, nb - 1)
        for s in np.unique(stp):
            sm = stp == s
            arr = occ.setdefault(int(s), np.zeros(nb, dtype=np.int64))
            np.add.at(arr, b[sm], 1)
            vol.setdefault(int(s), []).append(float(np.median(vv[sm])))

    steps = sorted(occ)
    print(f"(step x time-bucket) occupancy, {nb} buckets of "
          f"{width / 86400:.2f} days")
    hdr = "bucket  t_start_d  " + "".join(f"{s:>9}" for s in steps)
    print(hdr)
    for k in range(nb):
        row = f"{k:>6}  {(t_lo + k * width) / 86400:>9.2f}  "
        row += "".join(f"{occ[s][k]:>9}" if occ[s][k] else f"{'.':>9}"
                       for s in steps)
        print(row)
    print()
    concurrency = 0
    for s in steps:
        for k in range(nb):
            if occ[s][k]:
                others = sum(1 for s2 in steps
                             if s2 != s and occ[s2][k])
                if others:
                    concurrency += 1
                    break
    print(f"steps sharing at least one time bucket with another step: "
          f"{concurrency} of {len(steps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
