"""G6.1a step 0e -- is there a PULSE anywhere in these files?

The occupancy map showed ~3 concurrent step channels per instant, so the
(cycle, step) grouping is not a physical segmentation.  But two short
groups exist that the earlier scan flagged as carrying non-zero current
inside an otherwise quiet step -- gitthold cycle 1 step 7 and 13, 2161
rows over 6 h each.  If this dataset contains a GITT pulse train at all,
it is there.

Dumps a decimated run of those groups so the current waveform can be
read directly instead of inferred from aggregates.

Usage:
    python scripts/graphite/probe_gitt_shortsteps.py --glob "*gitthold__RT.bdf.parquet" --cycle 1 --steps 7,13 --every 25
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
BATCH = 1 << 18
COLS = ["Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
        "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*gitthold__RT.bdf.parquet")
    ap.add_argument("--cycle", type=int, default=1)
    ap.add_argument("--steps", default="7,13")
    ap.add_argument("--every", type=int, default=25)
    args = ap.parse_args()

    want = {int(s) for s in args.steps.split(",") if s.strip()}
    matches = sorted(DATA.glob("sintef__" + args.glob))
    path = matches[0]
    print(f"file  : {path.name}")
    print(f"cycle : {args.cycle}   steps: {sorted(want)}")
    print(f"print every {args.every}th row of each\n")

    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    chunks: list[pd.DataFrame] = []
    for batch in pf.iter_batches(batch_size=BATCH, columns=COLS):
        df = batch.to_pandas()
        m = ((df["Cycle Count / 1"].to_numpy(np.int64) == args.cycle)
             & np.isin(df["Step Index / 1"].to_numpy(np.int64),
                       list(want)))
        if m.any():
            chunks.append(df.loc[m])
    if not chunks:
        print("no rows matched")
        return 1
    sub = pd.concat(chunks, ignore_index=True)
    sub = sub.sort_values(["Step Index / 1", "Test Time / s"], kind="stable")

    for s in sorted(want):
        g = sub[sub["Step Index / 1"] == s]
        if g.empty:
            print(f"--- step {s}: absent")
            continue
        print(f"--- step {s}: n={len(g)}  "
              f"t {g['Test Time / s'].min():.2f} .. "
              f"{g['Test Time / s'].max():.2f} s")
        ii = g["Current / A"].to_numpy(float)
        print(f"    |I| max {np.abs(ii).max():.4e}  mean {ii.mean():+.4e}  "
              f"n_nonzero {(ii != 0).sum()}")
        dec = g.iloc[:: args.every]
        cols = ["Test Time / s", "Current / A", "Voltage / V",
                "Cumulative Capacity / Ah"]
        print(dec[cols].to_string(index=False,
                                  float_format=lambda v: f"{v:14.7f}"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
