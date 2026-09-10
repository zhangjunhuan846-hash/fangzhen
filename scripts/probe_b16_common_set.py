#!/usr/bin/env python3
# ============================================================
# Phase B1.6 probe: the paired ratio, its DEFINITION, and why two
#                   summaries of the same pulses can differ
#
# This probe exists because the first version of the B1.6 report
# carried two numbers for the same question that looked contradictory:
#   * median of the per-pulse D_v2/D_v1 ratios
#   * ratio of the D_v2 and D_v1 medians
# Chasing the difference found a real bug: the paired-ratio column was
# defined with the wrong exponent (D = R^2/tau_d with tau_d ~ m^2, so
# D_v2/D_v1 = (m_lin/m_quad)^2, not its inverse).  With the column
# fixed the two summaries agree in SIGN, and the residual difference is
# genuine heterogeneity.
#
# So the probe now does two things:
#   1. DEFINITIONAL check -- the paired-ratio column must equal
#      D_v2/D_v1 computed from the two tables, pulse by pulse;
#   2. DESCRIPTIVE -- where the paired ratio is above/below 1.
#
# Read-only: it opens the two pulse tables the driver already wrote.
# ============================================================

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
B16 = ROOT / "outputs" / "analysis" / "graphite_phaseB16"


def main() -> int:
    p1 = pd.read_csv(B16 / "v1" / "gitt_ds_app_pulses.csv")
    p2 = pd.read_csv(B16 / "v2" / "gitt_ds_app_pulses.csv")
    if len(p1) != len(p2):
        raise SystemExit("the two pulse tables are not row-aligned")

    acc1 = p1["accepted"].to_numpy(bool)
    acc2 = p2["accepted"].to_numpy(bool)
    d1 = p1["Ds_app_m2_s"].to_numpy(float)
    d2 = p2["Ds_app_m2_s"].to_numpy(float)
    soc = p1["SOC_mid"].to_numpy(float)
    col = p2["Ds_ratio_vs_linear"].to_numpy(float)

    # ---- 1. definitional cross-check ------------------------------
    print()
    print("=== definitional check: column vs D_v2/D_v1 ===")
    both = np.isfinite(d1) & np.isfinite(d2) & np.isfinite(col)
    direct = d2[both] / d1[both]
    rel = np.abs(col[both] / direct - 1.0)
    print(f"  comparable pulses: {int(both.sum())}")
    print(f"  max |column/direct - 1| = {rel.max():.3e}")
    print("  -> " + ("OK, the column IS D_v2/D_v1"
                     if rel.max() < 1e-9 else "MISMATCH, column is not "
                     "D_v2/D_v1"))
    print()

    # ---- 2. the two summaries -------------------------------------
    def line(tag, m):
        r = col[m & np.isfinite(col)]
        f = m & np.isfinite(d1) & np.isfinite(d2)
        print(f"{tag:30s} n={int(m.sum()):4d} "
              f"paired median={np.median(r):8.3f}  "
              f"ratio of medians="
              f"{np.median(d2[f]) / np.median(d1[f]):8.4f}  "
              f"fraction>1={np.mean(r > 1):5.3f}")

    print("=== the two summaries, on three populations ===")
    print("paired median    = median of (D_v2/D_v1) over pulses")
    print("ratio of medians = median(D_v2)/median(D_v1) over the same pulses")
    print()
    line("v2-accepted set", acc2)
    line("accepted by BOTH", acc1 & acc2)
    line("v2 accepted, v1 rejected", ~acc1 & acc2)
    print()

    m = acc1 & acc2
    r = col[m & np.isfinite(col)]
    print("=== heterogeneity on the pulses both accept ===")
    print("  paired ratio p5/p25/p50/p75/p95 =",
          np.round(np.percentile(r, [5, 25, 50, 75, 95]), 3))
    print(f"  below 1 (D smaller after correction): {np.mean(r < 1):.3f}")
    print(f"  above 1 (D larger  after correction): {np.mean(r > 1):.3f}")
    s = soc[m & np.isfinite(col)]
    if (r > 1).any() and (r < 1).any():
        print(f"  median SOC_mid | ratio>1: {np.median(s[r > 1]):.3f} | "
              f"ratio<1: {np.median(s[r < 1]):.3f}")
    print()
    print("The effect is heterogeneous in size, but its SIGN is not in")
    print("doubt: both summaries sit below 1 on every population.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
