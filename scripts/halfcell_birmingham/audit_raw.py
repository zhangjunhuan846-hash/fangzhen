"""H1 audit helper (raw inspection pass).

Reads the raw Birmingham NCM920305 CSV files and prints:
  - first N raw lines (repr) to reveal metadata header / delimiter / units
  - total line count
  - encoding / NUL checks

This is an *inspection-only* helper for docs/halfcell_birmingham_audit.md.
It does NOT write adapters and does NOT import battery_sim.
"""
from __future__ import annotations

import glob
import os
import sys

BASE = "/mnt/c/Users/24330/WorkBuddy/仿真模拟/data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw"


def main() -> int:
    files = sorted(glob.glob(os.path.join(BASE, "*.csv")))
    print(f"# files: {len(files)}\n")
    for p in files:
        name = os.path.basename(p)
        with open(p, "rb") as f:
            raw = f.read()
        nul = raw.count(b"\x00")
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        print("=" * 72)
        print(f"FILE: {name}  ({len(raw)} bytes, {len(lines)} lines, NUL={nul})")
        # delimiter guess on first non-empty line beyond any header
        for i in range(min(6, len(lines))):
            print(f"  [{i}] {lines[i][:200]!r}")
        if len(lines) > 6:
            print(f"  ...")
            for i in range(max(6, len(lines) - 2), len(lines)):
                print(f"  [{i}] {lines[i][:200]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
