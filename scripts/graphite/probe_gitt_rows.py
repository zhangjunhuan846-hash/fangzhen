"""G6.1a step 0b -- read the ACTUAL rows of a few GITT steps.

The step-structure scan reported zero current for the long steps while
the voltage moved by two volts, which cannot both be true.  The
suspicion is that pandas' groupby SUM SKIPS NaN, so an all-NaN current
column reports as mean 0 and (through a Python max() with NaN) as
max |I| = 0.  That would make a NaN-filled rest look like a genuine
zero-current hold.

Prints, for the requested (cycle, step) groups: NaN fraction of every
column, plus the first and last few rows verbatim.

Usage:
    python scripts/graphite/probe_gitt_rows.py
"""

from __future__ import annotations

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

# (cycle, step) groups worth inspecting: the long "zero-current" ones and
# the constant-current ones, plus a genuine rest.
WANT = [(1, 2), (1, 4), (1, 7), (1, 8), (1, 10)]


def main() -> int:
    matches = sorted(DATA.glob("sintef__*gitt__RT.bdf.parquet"))
    if not matches:
        print("no gitt parquet found")
        return 2
    path = matches[0]
    print(f"file: {path.name}\n")

    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    want = set(WANT)
    # keep a bounded head and tail sample per group
    head: dict[tuple[int, int], list] = {}
    tail: dict[tuple[int, int], list] = {}
    stats: dict[tuple[int, int], dict] = {}
    seen_rows = 0

    for batch in pf.iter_batches(batch_size=1 << 18, columns=COLS):
        df = batch.to_pandas()
        cyc = df["Cycle Count / 1"].to_numpy(np.int64)
        stp = df["Step Index / 1"].to_numpy(np.int64)
        for c, s in want:
            m = (cyc == c) & (stp == s)
            n = int(m.sum())
            if not n:
                continue
            sub = df.loc[m]
            seen_rows += n
            d = stats.setdefault((c, s), {"n": 0, "nan_I": 0, "nan_V": 0,
                                          "nan_t": 0, "I_min": np.inf,
                                          "I_max": -np.inf, "I_uniq": set()})
            d["n"] += n
            d["nan_I"] += int(sub["Current / A"].isna().sum())
            d["nan_V"] += int(sub["Voltage / V"].isna().sum())
            d["nan_t"] += int(sub["Test Time / s"].isna().sum())
            ii = sub["Current / A"].to_numpy(float)
            fin = ii[np.isfinite(ii)]
            if fin.size:
                d["I_min"] = min(d["I_min"], float(fin.min()))
                d["I_max"] = max(d["I_max"], float(fin.max()))
                if len(d["I_uniq"]) < 6:
                    for v in np.unique(fin)[:6]:
                        d["I_uniq"].add(round(float(v), 12))
            if (c, s) not in head:
                head[(c, s)] = sub.head(4).to_dict("records")
            tail[(c, s)] = sub.tail(4).to_dict("records")

    print(f"sampled {seen_rows:,} rows for {len(stats)} groups\n")
    for key in WANT:
        d = stats.get(key)
        if d is None:
            print(f"--- cycle {key[0]} step {key[1]}: NOT PRESENT\n")
            continue
        print(f"--- cycle {key[0]} step {key[1]}   n={d['n']:,}")
        print(f"    NaN: current {d['nan_I']} / voltage {d['nan_V']} / "
              f"time {d['nan_t']}")
        print(f"    finite I range [{d['I_min']:.6e}, {d['I_max']:.6e}]")
        print(f"    distinct I seen (capped): {sorted(d['I_uniq'])}")
        print("    first rows:")
        for r in head[key]:
            print("      ", {k: (round(v, 6) if isinstance(v, float) else v)
                             for k, v in r.items()})
        print("    last rows:")
        for r in tail.get(key, []):
            print("      ", {k: (round(v, 6) if isinstance(v, float) else v)
                             for k, v in r.items()})
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
