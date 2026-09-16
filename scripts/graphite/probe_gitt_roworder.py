"""G6.1a step 0c -- decisive: are the rows interleaved by step?

The per-(cycle, step) scan produced three mutually impossible facts at
once:

  * cycle 1 step 2 holds I EXACTLY 0 for 2.2e6 s while V falls
    2.902 -> 0.8846 V
  * cycle 2 step 2 holds I exactly 0 while V RISES 0.56 -> 1.0 V
  * step 2's Test Time range (14400 -> 2214137 s) OVERLAPS step 4's
    (23400 -> 1137322 s)

A rest cannot move the voltage by half a volt, and two step channels
cannot both own the same instant unless the file stores them
INTERLEAVED.  Grouping by (cycle, step) -- which is what the platform
adapter does -- would then be reading rows out of their physical order.

This prints a contiguous run of rows exactly as stored, so the layout is
settled by inspection rather than inference.

Usage:
    python scripts/graphite/probe_gitt_roworder.py [--at 0.5] [--n 40]
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
COLS = ["Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
        "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah"]
BATCH = 1 << 18


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", type=float, default=0.5,
                    help="fraction of the file to start printing at")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--glob", default="*gitt__RT.bdf.parquet")
    args = ap.parse_args()

    matches = sorted(DATA.glob("sintef__" + args.glob))
    path = matches[0]
    print(f"file: {path.name}\n")

    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    total = pf.metadata.num_rows
    target_row = int(total * args.at)
    print(f"total rows {total:,}; printing {args.n} rows from row "
          f"{target_row:,} (file order)\n")

    # also: does any single batch contain MORE THAN ONE step index?
    multi = 0
    multi_example = None

    printed = 0
    row_cursor = 0
    for batch in pf.iter_batches(batch_size=BATCH, columns=COLS):
        df = batch.to_pandas()
        n = len(df)
        stp = df["Step Index / 1"].to_numpy(np.int64)
        ns = len(np.unique(stp))
        if ns > 1:
            multi += 1
            if multi_example is None:
                vals, cnt = np.unique(stp, return_counts=True)
                multi_example = (row_cursor, dict(zip(vals.tolist(),
                                                      cnt.tolist())))
        if row_cursor + n > target_row and printed < args.n:
            start = max(0, target_row - row_cursor)
            sub = df.iloc[start:start + (args.n - printed)]
            pd.set_option("display.width", 220)
            print(sub.to_string(index=False))
            printed += len(sub)
        row_cursor += n
        if printed >= args.n and multi > 3 and path.stat().st_size < 1e6:
            break
    print()
    print(f"batches containing MORE THAN ONE step index: {multi} of "
          f"{row_cursor // BATCH + 1}")
    if multi_example:
        print(f"  first such batch starts at row {multi_example[0]:,}, "
              f"step counts {multi_example[1]}")

    # ---- the decisive quantity: step index as a function of row order
    print("\nstep index at 20 evenly spaced points (file order):")
    pf2 = pq.ParquetFile(path)
    pts = [int(i * total / 20) for i in range(20)]
    cur = 0
    got = 0
    for batch in pf2.iter_batches(batch_size=BATCH, columns=COLS):
        df = batch.to_pandas()
        n = len(df)
        while got < len(pts) and cur + n > pts[got]:
            r = pts[got] - cur
            row = df.iloc[r]
            print(f"  row {pts[got]:>12,}  cycle {int(row['Cycle Count / 1'])}"
                  f"  step {int(row['Step Index / 1']):>3}"
                  f"  t={row['Test Time / s']:>12.1f}"
                  f"  I={row['Current / A']:>+12.6e}"
                  f"  V={row['Voltage / V']:>10.5f}")
            got += 1
        cur += n
        if got >= len(pts):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
