"""G6.1a step 0 -- what is actually inside the SINTEF graphite GITT file?

The gate needs ONE clean (rest -> pulse -> relaxation) window, so the
file has to be surveyed before anything is selected.  The file holds
~9e7 rows, so this streams; nothing is read whole.

Reports, per (cycle, step): row count, held current, and the step's
wall-clock duration.  Duration is the column that decides whether a
step can serve as the 1800 s pulse / 9000 s relaxation pair.

Usage:
    python scripts/graphite/probe_gitt_structure.py [--cycles 3]
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

from battery_sim.datasets.sintef_graphite import (  # noqa: E402
    COL_CURRENT,
    COL_CYCLE,
    COL_STEP,
    COL_TIME,
    COL_VOLTAGE,
)

DATA = ROOT / "data"
BATCH = 1 << 18


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*gitt__RT.bdf.parquet",
                    help="raw-file glob (default: the main gitt programme)")
    ap.add_argument("--cycles", type=int, default=0,
                    help="print only the first N cycles (0 = all)")
    args = ap.parse_args()

    matches = sorted(DATA.glob("sintef__" + args.glob))
    if not matches:
        print(f"no file matched 'sintef__*{args.glob}' in {DATA}")
        return 2
    path = matches[0]
    print(f"file : {path.name}")
    print(f"size : {path.stat().st_size / 1e6:.1f} MB")

    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    print(f"rows : {pf.metadata.num_rows:,}")
    print(f"cols : {pf.schema_arrow.names}")
    print()

    # ---- stream once, aggregate per (cycle, step) -------------------
    # Vectorised groupby per batch.  An earlier draft looped over every
    # (cycle, step) key and built a boolean mask per key per batch --
    # O(keys x rows), which on a 9e7-row file does not finish.
    acc: dict[tuple[int, int], dict] = {}
    n_batches = 0
    for batch in pf.iter_batches(
        batch_size=BATCH,
        columns=[COL_CYCLE, COL_STEP, COL_TIME, COL_CURRENT, COL_VOLTAGE],
    ):
        df = batch.to_pandas()
        df = df.assign(_abs=df[COL_CURRENT].abs())
        gb = df.groupby([COL_CYCLE, COL_STEP], sort=False)
        agg = gb.agg(n=(COL_TIME, "size"),
                     sum_I=(COL_CURRENT, "sum"),
                     absmax_I=("_abs", "max"),
                     tmin=(COL_TIME, "min"),
                     tmax=(COL_TIME, "max"))
        # V at the group's own tmin / tmax, within this batch
        imin = gb[COL_TIME].idxmin()
        imax = gb[COL_TIME].idxmax()
        agg["V_tmin"] = df.loc[imin.values, COL_VOLTAGE].to_numpy()
        agg["V_tmax"] = df.loc[imax.values, COL_VOLTAGE].to_numpy()

        for (c, s), r in agg.iterrows():
            key = (int(c), int(s))
            d = acc.get(key)
            if d is None:
                acc[key] = d = {
                    "n": 0, "sum_I": 0.0, "absmax_I": 0.0,
                    "tmin": np.inf, "tmax": -np.inf,
                    "V0": np.nan, "V1": np.nan,
                }
            d["n"] += int(r["n"])
            d["sum_I"] += float(r["sum_I"])
            d["absmax_I"] = max(d["absmax_I"], float(r["absmax_I"]))
            if float(r["tmin"]) < d["tmin"]:
                d["tmin"] = float(r["tmin"])
                d["V0"] = float(r["V_tmin"])
            if float(r["tmax"]) > d["tmax"]:
                d["tmax"] = float(r["tmax"])
                d["V1"] = float(r["V_tmax"])
        n_batches += 1
        if n_batches % 40 == 0:
            print(f"   ... {n_batches} batches, {len(acc)} (cycle,step) seen",
                  flush=True)

    print(f"\nscanned {n_batches} batches, {len(acc)} (cycle,step) groups\n")

    rows = []
    for (c, s), d in sorted(acc.items()):
        rows.append({
            "cycle": c,
            "step": s,
            "n_rows": d["n"],
            "dur_s": d["tmax"] - d["tmin"] if np.isfinite(d["tmax"]) else np.nan,
            "mean_I_A": d["sum_I"] / d["n"] if d["n"] else np.nan,
            "absmax_I_A": d["absmax_I"],
            "V_start": d["V0"],
            "V_end": d["V1"],
        })
    out = pd.DataFrame(rows)

    cycles = sorted(out["cycle"].unique())
    print(f"cycles present : {cycles[:12]}{' ...' if len(cycles) > 12 else ''}")
    print(f"total groups   : {len(out)}\n")

    show = out
    if args.cycles:
        show = out[out["cycle"].isin(cycles[: args.cycles])]

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 400)
    print(show.to_string(index=False, float_format=lambda v: f"{v:12.5g}"))

    # One file per programme, derived from the glob.  A fixed filename let a
    # follow-up scan of a DIFFERENT programme overwrite the first one's
    # result -- the same mistake the G5.4 gate made with a single
    # report.json.  Deriving the name keeps every scan's output on disk.
    tag = path.name.split("__")[-2] or "unknown"
    out_path = ROOT / "outputs" / "graphite" / f"step_structure_{tag}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
