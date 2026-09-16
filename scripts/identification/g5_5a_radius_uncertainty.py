#!/usr/bin/env python
"""G5.5a -- model-scale uncertainty propagation: how much R_p error buys how much D_s error.

    python scripts/identification/g5_5a_radius_uncertainty.py [--quick]

Methodological close-out for the Chen2020 branch.  It deliberately does NOT
try to explain Chen2020's 5.22 um in terms of the user's measured PSD, and it
does NOT invent number/area/volume weighted variants of a distribution nobody
measured.  Both would manufacture information.

What it does is the narrow, defensible thing: perturb the pinned R_p by a
KNOWN relative amount and measure the resulting bias in the identified D_s.

    R_p = R_p,0 * (1 + delta),   delta = -20%, -10%, -5%, 0, +5%, +10%, +20%

and then the local slope

    beta = d log(D_s*) / d log(R_p).

THE REFERENCE LINE, NOT THE ANSWER.  If the observable constrained nothing but
the diffusion timescale tau_d = R_p^2 / D_s, then holding tau_d fixed forces
D_s to scale as R_p^2 and beta = 2 exactly.  The simulation will not land
exactly on 2, because G5.3 already showed R_p also enters through the specific
surface area and the flux boundary condition.  So 2 is drawn as a REFERENCE
and the measured departure from it is itself the finding.

Two arms, because the Chen2020 branch's whole point was that they differ:
control (SPM generates, SPM inverts) isolates the geometry of the mapping;
mismatch (SPMe generates, SPM inverts) is the config the real problem lives in.
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

from identification.forward import ReplayCase  # noqa: E402
from identification.multiprotocol import (  # noqa: E402
    MultiObservation,
    build_joint_problem,
)
from identification.synthetic import generate  # noqa: E402

DATASET, CELL, RATE = "chen2020", "02", "C10"
DS_TRUE, RP_TRUE = 2.0e-15, 5.22e-06
ZD_TRUE = math.log10(DS_TRUE)
DELTAS = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)
ARMS = (("control", "SPM"), ("mismatch", "SPMe"))
Z_BOUNDS = (-16.0, -13.0)
Z_INITS = (1.0e-15, 1.0e-14)
BETA_REFERENCE = 2.0


def _case(model):
    return ReplayCase(dataset_id=DATASET, cell=CELL, rate=RATE,
                      model_name=model).resolve()


def fit_ds(obs, runs, audit, arm_model, rp_pinned, maxiter, starts):
    """Identify D_s with R_p PINNED (injected as a constant, not dropped)."""
    import pybop

    multi = MultiObservation([obs], name="P1")
    best = None
    for z0 in starts:
        problem, sim = build_joint_problem(
            multi, output_root=runs, audit_dir=audit,
            replay_case=_case(arm_model), z_bounds=Z_BOUNDS,
            z_init=float(z0), r_init=math.log10(rp_pinned),
            fixed_radius=float(rp_pinned),
        )
        opt = pybop.SciPyMinimize(
            problem, options=pybop.SciPyMinimizeOptions(
                method="Nelder-Mead", maxiter=int(maxiter)))
        res = opt.run()
        J = float(res.best_cost)
        x = np.atleast_1d(np.asarray(res.x, dtype=float))
        if best is None or J < best["J"]:
            best = {"J": J, "z_D": float(x[0]),
                    "n_evals": int(getattr(res, "n_evaluations", 0) or 0)}
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="outputs/fitting/g5.5a")
    args = ap.parse_args()

    out = ROOT / args.out
    runs, audit = out / "runs", out / "audit"
    out.mkdir(parents=True, exist_ok=True)
    deltas = (-0.10, 0.0, 0.10) if args.quick else DELTAS
    arms = ARMS[:1] if args.quick else ARMS
    maxiter = 25 if args.quick else 60

    tic = time.perf_counter()
    log = print
    log("=" * 84)
    log("G5.5a  R_p uncertainty -> D_s uncertainty  (Chen2020 methodological close-out)")
    log("=" * 84)
    log(f"  protocol    : {RATE} (0.1C), single protocol")
    log(f"  R_p truth   : {RP_TRUE*1e6:.4f} um      D_s truth: {DS_TRUE:.4e}")
    log(f"  reference   : if only tau_d = R_p^2/D_s were constrained, "
        f"beta = {BETA_REFERENCE:g} exactly")
    log(f"  measured    : beta = d log(D_s*) / d log(R_p)")

    report = {
        "gate": "G5.5a",
        "question": "how much D_s bias does a given R_p error cause?",
        "boundary": ("perturbs a PINNED R_p by a known amount. It does NOT "
                     "interpret the user's PSD and does NOT fabricate "
                     "weighting variants of an unmeasured distribution"),
        "beta_reference": BETA_REFERENCE,
        "truth": {"ds": DS_TRUE, "rp": RP_TRUE},
        "deltas": list(deltas),
        "results": {},
    }
    starts = tuple(float(np.log10(z)) for z in Z_INITS)

    for arm, truth_model in arms:
        obs = generate(DATASET, CELL, RATE, DS_TRUE, runs / arm,
                       model_name=truth_model)
        rows = []
        log(f"\n{'-' * 84}")
        log(f"arm {arm}: {truth_model} truth -> SPM inverse")
        log(f"{'-' * 84}")
        log(f"  {'delta':>7s} {'R_p/R_p,0':>10s} {'D_s*/D_s,0':>12s}"
            f" {'bias %':>10s}  {'beta=2 pred %':>13s}  {'cost':>12s}")
        for delta in deltas:
            rp = RP_TRUE * (1.0 + delta)
            b = fit_ds(obs, runs / arm, audit / f"{arm}_{delta:+.2f}",
                       "SPM", rp, maxiter, starts)
            ratio = 10.0 ** (b["z_D"] - ZD_TRUE)
            predicted = (1.0 + delta) ** BETA_REFERENCE
            row = {
                "delta": float(delta),
                "rp_um": rp * 1e6,
                "rp_ratio": float(1.0 + delta),
                "ds_star": float(10.0 ** b["z_D"]),
                "ds_ratio": float(ratio),
                "bias_pct": float((ratio - 1.0) * 100.0),
                "beta2_prediction_pct": float((predicted - 1.0) * 100.0),
                "cost": b["J"],
                "n_evals": b["n_evals"],
            }
            rows.append(row)
            log(f"  {delta*100:+6.0f}% {1.0+delta:10.4f} {ratio:12.6f}"
                f" {(ratio-1)*100:+9.2f}%  {(predicted-1)*100:+12.2f}%"
                f"  {b['J']:12.4e}")

        # local slope through the origin: log(D_s*/D_s,0) = beta * log(R_p/R_p,0)
        pairs = [(math.log(r["rp_ratio"]), math.log(r["ds_ratio"]))
                 for r in rows
                 if r["rp_ratio"] != 1.0 and r["ds_ratio"] > 0]
        xs = np.array([p_[0] for p_ in pairs])
        ys = np.array([p_[1] for p_ in pairs])
        beta = float(np.sum(xs * ys) / np.sum(xs * xs)) if xs.size else None
        # leave-one-out spread, so a single point cannot carry the number
        betas = []
        for k in range(len(xs)):
            m = np.ones(len(xs), dtype=bool)
            m[k] = False
            if m.sum():
                betas.append(float(np.sum(xs[m] * ys[m]) / np.sum(xs[m] * xs[m])))
        report["results"][arm] = {
            "truth_model": truth_model, "rows": rows,
            "beta": beta,
            "beta_leave_one_out_min": (min(betas) if betas else None),
            "beta_leave_one_out_max": (max(betas) if betas else None),
            "beta_departure_from_2": (None if beta is None
                                      else float(beta - BETA_REFERENCE)),
        }
        log(f"\n  beta = {beta:.4f}   (reference {BETA_REFERENCE:g},"
            f" departure {beta - BETA_REFERENCE:+.4f})")
        log(f"  leave-one-out beta range: [{min(betas):.4f}, {max(betas):.4f}]")
        log(f"  -> {'tau_d controls' if abs(beta-2) < 0.15 else 'measurable departure from tau_d-only'}")

    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_5a_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    log(f"\nreport -> {out / 'g5_5a_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
