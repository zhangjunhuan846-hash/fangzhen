#!/usr/bin/env python
"""G5.0 -- single-parameter synthetic recovery of D_s (gate script).

    python scripts/identification/g5_0_synthetic_recovery.py [--quick]

Frozen scope: ONE parameter (D_s), ONE synthetic observation, no real-data
fitting, no second parameter, no agent.

Why synthetic first: if the pipeline cannot recover a parameter it was
itself handed, a fit against real data carries no evidential weight -- a
pretty RMSE would not distinguish "found the physics" from "the optimiser
compensated for an error somewhere else".  The answer is known here, so the
result is checkable.

All artefacts go under outputs/fitting/ (gitignored) -- identification runs
must not be able to dirty the tracked outputs tree.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from identification.recovery import (  # noqa: E402
    check_acceptance,
    cost_scan,
    recover_from,
)
from identification.synthetic import (  # noqa: E402
    generate,
    verify_truth_is_reproducible,
)

DS_TRUE = 2.0e-15
Z_INITS = (1.0e-15, 4.0e-15, 1.0e-14)
Z_BOUNDS = (-16.0, -13.0)
DATASET, CELL, RATE, MODEL = "chen2020", "02", "C2", "SPM"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="fewer scan points / iterations, for a wiring check")
    ap.add_argument("--out", default="outputs/fitting/g5.0")
    ap.add_argument("--method", default="Nelder-Mead")
    args = ap.parse_args()

    out = ROOT / args.out
    runs = out / "runs"
    audit = out / "audit"
    out.mkdir(parents=True, exist_ok=True)

    tic = time.perf_counter()
    report = {
        "gate": "G5.0",
        "question": ("given a synthetic voltage response generated at a "
                     "known D_s, can the pipeline recover it?"),
        "scope": "one parameter (D_s), synthetic data only",
        "config": {
            "dataset": DATASET, "cell": CELL, "rate": RATE, "model": MODEL,
            "ds_true": DS_TRUE, "z_var": "log10(D_s)",
            "z_inits": [float(np.log10(z)) for z in Z_INITS],
            "z_bounds": list(Z_BOUNDS),
            "optimiser": f"pybop.SciPyMinimize(method={args.method})",
            "quick": args.quick,
        },
    }

    log = print
    log("=" * 74)
    log("G5.0  single-parameter synthetic recovery of D_s")
    log("=" * 74)

    # ---- 1. synthetic observation ---------------------------------
    log("\n[1/5] generating synthetic observation at D_s_true = "
        f"{DS_TRUE:.3e}")
    obs = generate(DATASET, CELL, RATE, DS_TRUE, runs, MODEL)
    report["observation"] = {
        "n_points": int(len(obs.time_s)),
        "t_end_s": float(obs.time_s[-1]),
        "voltage_min_V": float(obs.voltage_V.min()),
        "voltage_max_V": float(obs.voltage_V.max()),
    }
    log(f"      n_points={len(obs.time_s)}  t_end={obs.time_s[-1]:.1f} s  "
        f"V=[{obs.voltage_V.min():.4f}, {obs.voltage_V.max():.4f}]")

    # ---- 2. the truth must replay exactly -------------------------
    log("\n[2/5] verifying the truth replays bit-for-bit")
    repro = verify_truth_is_reproducible(obs, runs)
    report["truth_reproducible"] = bool(repro)
    log(f"      reproducible = {repro}")
    if not repro:
        log("      ABORT: the forward model does not reproduce its own "
            "observation; any fit would be measuring that mismatch.")
        (out / "g5_0_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 2

    # ---- 3. explicit cost scan ------------------------------------
    n_scan = 7 if args.quick else 13
    log(f"\n[3/5] explicit cost scan J(log10 D_s) -- coarse + refinement "
        "(does NOT trust the optimiser)")
    scan = cost_scan(
        obs, runs, audit / "scan", n=n_scan, z_bounds=Z_BOUNDS,
        z_truth=float(np.log10(DS_TRUE)),
    )
    report["cost_scan"] = scan

    zt = float(np.log10(DS_TRUE))
    log(f"      coarse pass ({scan['coarse']['n_points']} pts, "
        f"spacing {scan['coarse']['spacing_dex']:.3f} dex):")
    for z, c in zip(scan["coarse"]["z"], scan["coarse"]["cost"]):
        txt = ("unreachable (overlap too small)" if not np.isfinite(c)
               else f"{c:.6e}")
        log(f"         z={z:+.4f}  D_s={10**z:.3e}  J={txt}")
    log(f"      refined pass ({scan['refined']['n_points']} pts, "
        f"span {scan['refined']['span_dex']:.3f} dex, "
        f"resolution {scan['refined']['resolution_dex']:.4f} dex):")
    for z, c in zip(scan["refined"]["z"], scan["refined"]["cost"]):
        if not np.isfinite(c):
            continue
        near = "  <-- near truth" if abs(z - zt) < 0.1 else ""
        log(f"         z={z:+.4f}  D_s={10**z:.3e}  J={c:.6e}{near}")
    log(f"      argmin  z={scan['z_argmin']:+.4f} "
        f"(D_s={10**scan['z_argmin']:.3e})   truth z={zt:+.4f} "
        f"(D_s={DS_TRUE:.3e})")
    log(f"      achieved resolution {scan['achieved_resolution_dex']:.5f} dex"
        f"   unreachable points {scan['n_unreachable']}")

    # ---- 4. multi-start -------------------------------------------
    maxiter = 60 if args.quick else 400
    starts = []
    log(f"\n[4/5] multi-start recovery, {len(Z_INITS)} initial guesses, "
        f"maxiter={maxiter}")
    for z0 in (np.log10(z) for z in Z_INITS):
        log(f"      from D_s={10**z0:.3e} ...")
        sr = recover_from(
            obs, runs, audit / f"init_{z0:+.4f}", z_init=float(z0),
            z_bounds=Z_BOUNDS, method=args.method, maxiter=maxiter,
        )
        starts.append(sr)
        log(f"         -> D_s={sr.ds_fit:.6e}  z={sr.z_fit:+.5f}  "
            f"J={sr.cost_final:.6e}  evals={sr.n_evaluations}  "
            f"rel_err={sr.rel_error*100:.3f}%  [{sr.message}]")
    report["starts"] = [vars(s) for s in starts]

    # ---- 5. acceptance --------------------------------------------
    log("\n[5/5] acceptance")
    acc = check_acceptance(scan, starts, DS_TRUE)
    report["acceptance"] = acc
    for key in ("1_same_basin", "2_close_to_truth",
                "3_cost_minimum_near_truth", "4_provenance_complete"):
        log(f"      {'PASS' if acc[key]['ok'] else 'FAIL'}  {key}")
    b = acc["1_same_basin"]
    log(f"            basin spread {b['spread_dex']:.5f} dex "
        f"(tol {b['tol_dex']})")
    c = acc["2_close_to_truth"]
    log(f"            worst relative error {c['worst_rel_error']*100:.4f}% "
        f"(tol {c['tol']*100:.1f}%)")
    d = acc["3_cost_minimum_near_truth"]
    log(f"            argmin distance {d['distance_dex']:.4f} dex "
        f"(tol {d['tol_dex']:.4f} = {d['tol_source']})")
    log(f"            cost at truth {d['cost_at_truth']:.3e} vs grid min "
        f"{d['cost_min_on_grid']:.3e}  "
        f"(truth at least as good: {d['truth_at_least_as_good_as_grid']})")
    e = acc["4_provenance_complete"]
    log(f"            {e['n_records']} evaluations audited, "
        f"{e['n_missing']} missing provenance")
    log(f"\n      ALL PASSED = {acc['all_passed']}")

    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_0_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nreport -> {out / 'g5_0_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0 if acc["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
