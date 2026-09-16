"""Post-analysis for G5.5a: beta computed about delta = 0, not through the origin.

The driver's through-origin fit folds a constant offset into the exponent.
That is harmless on the control arm, where the offset is zero, but the
mismatch arm already carries a -25% bias at delta = 0, and there the
leave-one-out range of the through-origin estimate blows up. Normalising each
D_s* by its own delta = 0 value removes the offset and leaves the R_p
sensitivity, which is what beta is meant to describe.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

REPORT = Path("outputs/fitting/g5.5a/g5_5a_report.json")
OUT = Path("outputs/fitting/g5.5a/g5_5a_beta.json")


def beta_about_zero(rows):
    base = next((x["ds_ratio"] for x in rows if x["delta"] == 0.0), None)
    if base is None or base <= 0:
        return None
    num = den = 0.0
    for x in rows:
        if x["delta"] == 0.0 or x["ds_ratio"] <= 0:
            continue
        lx = math.log(x["rp_ratio"])
        ly = math.log(x["ds_ratio"] / base)
        num += lx * ly
        den += lx * lx
    return num / den if den else None


def loo(rows, fn):
    vals = []
    for k in range(len(rows)):
        sub = [x for i, x in enumerate(rows) if i != k]
        v = fn(sub)
        if v is not None and math.isfinite(v):
            vals.append(v)
    return (min(vals), max(vals)) if vals else (None, None)


def main() -> int:
    r = json.loads(REPORT.read_text(encoding="utf-8"))
    out = {
        "gate": "G5.5a",
        "beta_definition": "d log(D_s*) / d log(R_p), about delta = 0",
        "beta_reference": 2.0,
        "reference_note": ("beta = 2 exactly if the observable constrained "
                           "nothing but tau_d = R_p^2/D_s"),
        "arms": {},
    }
    print("=" * 78)
    print("G5.5a  beta = d log(D_s*) / d log(R_p)")
    print("=" * 78)
    print(f"  {'arm':10s} {'through origin':>15s} {'LOO':>20s}"
          f" {'about zero':>12s} {'LOO':>20s}")
    for arm, d in r["results"].items():
        rows = d["rows"]
        bn = beta_about_zero(rows)
        lo, hi = loo(rows, beta_about_zero)
        out["arms"][arm] = {
            "beta_through_origin": d["beta"],
            "beta_through_origin_loo": [d["beta_leave_one_out_min"],
                                        d["beta_leave_one_out_max"]],
            "beta_about_zero": bn,
            "beta_about_zero_loo": [lo, hi],
            "departure_from_2": (None if bn is None else bn - 2.0),
            "rows": rows,
        }
        print(f"  {arm:10s} {d['beta']:15.4f}"
              f" {'[%.3f, %.3f]' % (d['beta_leave_one_out_min'], d['beta_leave_one_out_max']):>20s}"
              f" {bn:12.4f} {'[%.4f, %.4f]' % (lo, hi):>20s}")

    print()
    print("=" * 78)
    print("  measured bias vs the beta = 2 prediction (control arm)")
    print("=" * 78)
    print(f"  {'delta':>7s} {'measured %':>12s} {'beta=2 pred %':>14s} {'excess %':>10s}")
    for x in r["results"]["control"]["rows"]:
        if x["delta"] == 0.0:
            continue
        print(f"  {x['delta']*100:+6.0f}% {x['bias_pct']:+11.2f}%"
              f" {x['beta2_prediction_pct']:+13.2f}%"
              f" {x['bias_pct'] - x['beta2_prediction_pct']:+9.2f}%")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"\nwritten -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
