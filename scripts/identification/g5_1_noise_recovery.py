#!/usr/bin/env python
"""G5.1 -- noise-added synthetic recovery of D_s.

    python scripts/identification/g5_1_noise_recovery.py [--quick]

G5.0 showed the pipeline can recover a parameter from data it generated
itself, noiselessly.  That is an INVERSE CRIME: the same model, structure and
parameter definition produce and invert the data, so it can only demonstrate
that the implementation is not broken.

This gate adds measurement noise and starts asking the scientific question
instead:

    is D_s still identifiable when the data are not exactly reproducible?

What is reported per noise level:

  * bias      -- is the recovered value systematically off, and in which
                 direction?  A systematic bias is the signature of a
                 parameter the observable constrains only indirectly.
  * spread    -- seed-to-seed variance: how much does the answer depend on
                 WHICH noise realisation was drawn?
  * basin     -- multi-start spread within a single realisation: does the
                 optimiser land in the same place from different starts?
  * fit RMS   -- the residual of the fit.  This must come out at about the
                 injected noise level.  Well below it means the optimiser is
                 fitting the noise; well above it means the model cannot
                 reach the data at all.

Noise is added to the OBSERVATION only; the forward model is untouched, so
any deviation is attributable to the noise and to how strongly the
observable constrains the parameter.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from identification.recovery import recover_from  # noqa: E402
from identification.synthetic import (  # noqa: E402
    add_noise,
    generate,
    verify_truth_is_reproducible,
)

DS_TRUE = 2.0e-15
DATASET, CELL, RATE, MODEL = "chen2020", "02", "C2", "SPM"
SIGMA_MV = (0.0, 0.5, 1.0, 2.0, 5.0)
Z_INITS = (1.0e-15, 4.0e-15, 1.0e-14)
Z_BOUNDS = (-16.0, -13.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="outputs/fitting/g5.1")
    ap.add_argument("--method", default="Nelder-Mead")
    args = ap.parse_args()

    out = ROOT / args.out
    runs, audit = out / "runs", out / "audit"
    out.mkdir(parents=True, exist_ok=True)

    seeds = (0,) if args.quick else (0, 1, 2)
    sigmas = (0.0, 2.0) if args.quick else SIGMA_MV
    maxiter = 80 if args.quick else 400

    tic = time.perf_counter()
    log = print
    log("=" * 78)
    log("G5.1  noise-added synthetic recovery of D_s")
    log("=" * 78)

    base = generate(DATASET, CELL, RATE, DS_TRUE, runs, MODEL)
    repro = verify_truth_is_reproducible(base, runs)
    log(f"\nbase observation: {len(base.time_s)} pts, "
        f"t_end={base.time_s[-1]:.1f} s, D_s_true={DS_TRUE:.3e}")
    log(f"truth replays bit-for-bit: {repro}")
    if not repro:
        log("ABORT: forward model does not reproduce its own observation")
        return 2

    z_truth = math.log10(DS_TRUE)
    n_points = len(base.time_s)
    report = {
        "gate": "G5.1",
        "question": ("is D_s still identifiable when the observation carries "
                     "measurement noise?"),
        "boundary": ("noise is added to the observation only; the forward "
                     "model, its structure and the parameter definition are "
                     "unchanged, so this is still a synthetic test -- it "
                     "measures NOISE sensitivity, not model mismatch"),
        "config": {
            "dataset": DATASET, "cell": CELL, "rate": RATE, "model": MODEL,
            "ds_true": DS_TRUE, "z_truth": z_truth,
            "sigma_mV": list(sigmas), "seeds": list(seeds),
            "z_inits": [float(np.log10(z)) for z in Z_INITS],
            "n_points": int(n_points),
            "optimiser": f"pybop.SciPyMinimize(method={args.method})",
        },
        "levels": {},
    }

    for sigma in sigmas:
        log(f"\n{'-' * 78}")
        log(f"noise sigma = {sigma:g} mV")
        log(f"{'-' * 78}")
        per_seed = []
        for seed in seeds:
            obs = (base if sigma == 0.0 else add_noise(base, sigma, seed))
            fits, spreads, rms = [], [], []
            for z0 in (np.log10(z) for z in Z_INITS):
                sr = recover_from(
                    obs, runs, audit / f"sigma{sigma:g}_seed{seed}_z{z0:+.4f}",
                    z_init=float(z0), z_bounds=Z_BOUNDS,
                    method=args.method, maxiter=maxiter,
                )
                fits.append(sr.z_fit)
                # residual of the fit, in mV -- compare against the noise
                if np.isfinite(sr.cost_final) and n_points:
                    rms.append(math.sqrt(sr.cost_final / n_points) * 1000.0)
            fits = np.array(fits, dtype=float)
            entry = {
                "sigma_mV": float(sigma),
                "seed": int(seed),
                "z_fits": [float(z) for z in fits],
                "ds_fits": [float(10.0 ** z) for z in fits],
                "basin_spread_dex": float(fits.max() - fits.min()),
                "z_mean": float(fits.mean()),
                "bias_dex": float(fits.mean() - z_truth),
                "bias_pct": float(
                    (10.0 ** (fits.mean() - z_truth) - 1.0) * 100.0
                ),
                "fit_rms_mV": (float(np.mean(rms)) if rms else None),
            }
            per_seed.append(entry)
            log(f"  seed {seed}: D_s = "
                f"{entry['ds_fits'][0]:.6e} / {entry['ds_fits'][1]:.6e} / "
                f"{entry['ds_fits'][2]:.6e}")
            log(f"           basin spread {entry['basin_spread_dex']:.5f} dex"
                f"   bias {entry['bias_dex']:+.5f} dex "
                f"({entry['bias_pct']:+.4f}%)"
                f"   fit RMS {entry['fit_rms_mV']:.3f} mV"
                if entry["fit_rms_mV"] is not None else "")

        biases = np.array([e["bias_dex"] for e in per_seed])
        spreads = np.array([e["basin_spread_dex"] for e in per_seed])
        rmsvals = np.array([e["fit_rms_mV"] for e in per_seed
                            if e["fit_rms_mV"] is not None])
        report["levels"][f"{sigma:g}"] = {
            "sigma_mV": float(sigma),
            "per_seed": per_seed,
            "bias_dex_mean": float(biases.mean()),
            "bias_dex_std_across_seeds": float(biases.std(ddof=0)),
            "bias_pct_mean": float(np.mean([e["bias_pct"] for e in per_seed])),
            "worst_basin_spread_dex": float(spreads.max()),
            "fit_rms_mV_mean": (float(rmsvals.mean()) if rmsvals.size
                                else None),
            "n_recoveries": len(per_seed) * len(Z_INITS),
        }
        lv = report["levels"][f"{sigma:g}"]
        log(f"  summary: bias {lv['bias_dex_mean']:+.5f} dex "
            f"+/- {lv['bias_dex_std_across_seeds']:.5f} "
            f"(across {len(seeds)} seed(s))")
        log(f"           worst basin spread {lv['worst_basin_spread_dex']:.5f}"
            f" dex, fit RMS {lv['fit_rms_mV_mean']:.3f} mV"
            if lv["fit_rms_mV_mean"] is not None else "")

    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_1_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nreport -> {out / 'g5_1_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
