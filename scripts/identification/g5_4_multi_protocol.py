#!/usr/bin/env python
"""G5.4 -- multi-protocol identifiability and model-consistency gate.

    python scripts/identification/g5_4_multi_protocol.py [--quick]

ONE question: can additional protocols or independent measurements actually
break the D_s-R_p practical correlation?  Neither "yes" nor "no" is assumed.

Three groups, each run for BOTH arms (control SPM->SPM, mismatch SPMe->SPM):

    A  single protocol          P1 = 0.1C
    B  multi protocol           P2 = 0.1C+0.5C ;  P4 = +1C+1.5C
    C  multi protocol + an independent R_p constraint

Protocol sets are nested 1 -> 2 -> 4, which reads as a dose-response: how much
does each added protocol buy?

Group C is the part that connects the simulation to real measurements.  The
user's measured PSD is D10/D50/D90 = 10.72/17.58/27.82 um.  Those are
DIAMETERS, and PyBaMM's ``Positive particle radius`` is a single effective
diffusion length, not a geometric mean radius -- the Chen2020 value is 5.22 um
while D50/2 would be 8.79 um.  So C is run TWICE, with R_p pinned at each
interpretation, precisely to show that how the measurement is interpreted
changes the answer:

    C_low   R_p pinned at D10/2 = 5.36 um   (sits within 2.6% of the model's
                                             own effective radius)
    C_mid   R_p pinned at D50/2 = 8.79 um   (the naive geometric-mean reading)

If C_low recovers D_s and C_mid does not, then an independent measurement does
break the correlation -- but only when it is interpreted as the length scale
the model actually uses.

Objective: equal weight per protocol (see identification/multiprotocol.py).
Metrics: optimum vs truth, condition number, corr(D_s,R_p), and the residual of
EACH protocol at the shared optimum -- the last is the model-consistency
diagnostic.
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
    local_geometry,
    per_protocol_residuals,
)
from identification.synthetic import generate  # noqa: E402

DATASET, CELL = "chen2020", "02"
DS_TRUE, RP_TRUE = 2.0e-15, 5.22e-06
ZD_TRUE, ZR_TRUE = math.log10(DS_TRUE), math.log10(RP_TRUE)

#: measured PSD, um -- DIAMETERS
D10, D50, D90 = 10.72, 17.58, 27.82
RP_LOW = (D10 / 2) * 1e-6          # 5.36 um
RP_MID = (D50 / 2) * 1e-6          # 8.79 um

SETS = (("P1", ("C10",)), ("P2", ("C10", "C2")), ("P4", ("C10", "C2", "1C", "1p5C")))
ARMS = (("control", "SPM"), ("mismatch", "SPMe"))
Z_BOUNDS = (-16.0, -13.0)
R_BOUNDS = (math.log10(1e-6), math.log10(2e-5))
Z_INITS = (1.0e-15, 1.0e-14)


def _case(rate, model):
    return ReplayCase(dataset_id=DATASET, cell=CELL, rate=rate,
                      model_name=model).resolve()


def joint_fit(multi, runs, audit, arm_model, starts, maxiter, fixed_radius=None):
    import pybop

    best = None
    for z0 in starts:
        problem, sim = build_joint_problem(
            multi, output_root=runs, audit_dir=audit,
            replay_case=_case(multi.protocols[0].case.rate, arm_model),
            z_bounds=Z_BOUNDS, r_bounds=R_BOUNDS,
            z_init=float(z0),
            r_init=ZR_TRUE,
            fixed_radius=fixed_radius,
        )
        opt = pybop.SciPyMinimize(
            problem, options=pybop.SciPyMinimizeOptions(
                method="Nelder-Mead", maxiter=int(maxiter)))
        res = opt.run()
        J = float(res.best_cost)
        if best is None or J < best["J"]:
            x = np.atleast_1d(np.asarray(res.x, dtype=float))
            best = {
                "J": J, "x": [float(v) for v in x],
                "z_D": float(x[0]),
                "z_R": (float(x[1]) if fixed_radius is None
                        else float(math.log10(fixed_radius))),
                "n_evals": int(getattr(res, "n_evaluations", 0) or 0),
                "message": str(getattr(res, "message", "")),
            }
        sim.write_audit(Path(audit) / "joint_evaluations.json")
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="outputs/fitting/g5.4")
    ap.add_argument("--group-c-only", action="store_true",
                    help="re-run only group C (the R_p constraint)")
    args = ap.parse_args()

    out = ROOT / args.out
    runs, audit = out / "runs", out / "audit"
    out.mkdir(parents=True, exist_ok=True)
    sets = SETS[:2] if args.quick else SETS
    arms = ARMS[:1] if args.quick else ARMS
    maxiter_2d = 60 if args.quick else 150
    maxiter_1d = 25 if args.quick else 40

    tic = time.perf_counter()
    log = print
    log("=" * 84)
    log("G5.4  multi-protocol identifiability and model consistency")
    log("=" * 84)
    log(f"  objective   : equal weight per protocol, J = (1/K) sum_k (1/N_k) SSR_k")
    log(f"  question    : can more protocols, or an independent R_p measurement,")
    log(f"                actually break the D_s-R_p practical correlation?")
    log(f"  truth       : D_s={DS_TRUE:.3e}  R_p={RP_TRUE*1e6:.2f} um")
    log(f"  measured PSD: D10={D10} D50={D50} D90={D90} um (DIAMETERS)")
    log(f"                -> D10/2={RP_LOW*1e6:.2f} um   D50/2={RP_MID*1e6:.2f} um")
    log(f"     model R_p / (D10/2) = {RP_TRUE/RP_LOW:.3f}"
        f"   model R_p / (D50/2) = {RP_TRUE/RP_MID:.3f}")

    report = {
        "gate": "G5.4",
        "question": ("can additional protocols or independent measurements "
                     "actually break the D_s-R_p practical correlation?"),
        "objective": ("J = (1/K) sum_k (1/N_k) SSR_k -- equal weight per "
                      "protocol, NOT a pooled SSE"),
        "truth": {"ds": DS_TRUE, "rp": RP_TRUE},
        "measured_psd_um": {"D10": D10, "D50": D50, "D90": D90,
                            "note": "diameters; PyBaMM radius is an effective "
                                    "diffusion length, not a geometric mean"},
        "config": {"protocol_sets": {n: list(r) for n, r in sets},
                   "starts": [float(np.log10(z)) for z in Z_INITS],
                   "maxiter_2d": maxiter_2d, "maxiter_1d": maxiter_1d},
        "results": {}, "group_C": {},
    }

    # observations per arm (generated once, reused by every protocol set)
    obs_cache: dict[str, dict[str, object]] = {}
    for arm, model in arms:
        obs_cache[arm] = {}
        for _, rates in sets:
            for r in rates:
                if r not in obs_cache[arm]:
                    obs_cache[arm][r] = generate(
                        DATASET, CELL, r, DS_TRUE, runs / arm, model_name=model)

    starts = tuple(float(np.log10(z)) for z in Z_INITS)

    log(f"\n{'=' * 84}")
    log("A + B   protocol sets, both arms"
        + ("   [SKIPPED by --group-c-only]" if args.group_c_only else ""))
    log(f"{'=' * 84}")
    for arm, model in (() if args.group_c_only else arms):
        inv = "SPM"
        for name, rates in sets:
            multi = MultiObservation(
                [obs_cache[arm][r] for r in rates], name=f"{arm}:{name}")
            b = joint_fit(multi, runs / arm, audit / f"{arm}_{name}", inv,
                          starts, maxiter_2d)
            inputs = {"log10_Ds": b["z_D"], "log10_Rp": b["z_R"]}
            ppr = per_protocol_residuals(
                multi, inputs, runs / arm, audit / f"{arm}_{name}_ppr",
                replay_case=_case(rates[0], inv))
            geo = local_geometry(
                build_joint_problem(
                    multi, output_root=runs / arm,
                    audit_dir=audit / f"{arm}_{name}_geo",
                    replay_case=_case(rates[0], inv),
                    z_bounds=Z_BOUNDS, r_bounds=R_BOUNDS,
                    z_init=b["z_D"], r_init=b["z_R"])[0],
                b["z_D"], b["z_R"], h=0.05)
            entry = {
                "arm": arm, "truth_model": model, "inverse_model": inv,
                "protocols": list(rates), "K": len(rates),
                "ds": float(10 ** b["z_D"]), "rp": float(10 ** b["z_R"]),
                "bias_D": float(10 ** (b["z_D"] - ZD_TRUE) - 1),
                "bias_R": float(10 ** (b["z_R"] - ZR_TRUE) - 1),
                "cost": b["J"], "n_evals": b["n_evals"],
                "condition_number": geo.get("condition_number"),
                "corr_Ds_Rp": geo.get("corr_Ds_Rp"),
                "corr_reliable": geo.get("corr_reliable"),
                "rise_D_at_0p05": geo.get("rise_D_at_0p05"),
                "rise_R_at_0p05": geo.get("rise_R_at_0p05"),
                "sharpness_D": geo.get("sharpness_D"),
                "sharpness_R": geo.get("sharpness_R"),
                "eigenvalues": geo.get("eigenvalues"),
                "per_protocol": ppr,
                "message": b["message"],
            }
            report["results"][f"{arm}:{name}"] = entry
            log(f"\n  [{arm}] {name} ({'+'.join(rates)})")
            log(f"     D_s={entry['ds']:.5e} ({entry['bias_D']*100:+9.2f} %)"
                f"   R_p={entry['rp']*1e6:7.3f} um ({entry['bias_R']*100:+8.2f} %)")
            corr_txt = ("%.4f" % entry["corr_Ds_Rp"]
                        if entry["corr_Ds_Rp"] is not None
                        else "n/a (non-quadratic)")
            sd = entry["sharpness_D"]
            sr = entry["sharpness_R"]
            log(f"     sharpness J(.05)/J(.20):  z_D "
                f"{'n/a' if sd is None else format(sd, '.4f')}"
                f"   z_R {'n/a' if sr is None else format(sr, '.4f')}")
            log(f"     cond(H)={entry['condition_number']:.3g}"
                f"   corr(D_s,R_p)={corr_txt}   evals={b['n_evals']}")
            for p in ppr:
                rms = p["rms_mV"]
                bias = p["bias_mV"]
                rms_txt = "unreachable" if rms is None else f"{rms:9.4f} mV"
                bias_txt = "--" if bias is None else f"{bias:+8.3f} mV"
                log(f"        {p['rate']:6s}  n={p['n_points']:5d}"
                    f"  RMS={rms_txt:>14s}  bias={bias_txt:>12s}")

    # ---------------- group C ----------------
    log(f"\n{'=' * 84}")
    log("C   multi-protocol (P4) + an INDEPENDENT R_p constraint")
    log(f"{'=' * 84}")
    p4 = max(sets, key=lambda s: len(s[1]))[1]   # widest set actually run
    for arm, model in arms:
        multi = MultiObservation([obs_cache[arm][r] for r in p4],
                                 name=f"{arm}:P4")
        for label, rp in (("C_low", RP_LOW), ("C_mid", RP_MID)):
            b = joint_fit(multi, runs / arm, audit / f"{arm}_{label}", "SPM",
                          starts, maxiter_1d, fixed_radius=rp)
            free = report["results"].get(f"{arm}:P4")
            entry = {
                "arm": arm, "rp_pinned_um": rp * 1e6,
                "rp_pinned_over_truth": rp / RP_TRUE,
                "free_rp_reference": (
                    {"ds": free["ds"], "bias_D": free["bias_D"],
                     "cost": free["cost"]} if free else None),
                "ds": float(10 ** b["z_D"]),
                "bias_D": float(10 ** (b["z_D"] - ZD_TRUE) - 1),
                "cost": b["J"], "n_evals": b["n_evals"],
                "message": b["message"],
            }
            report["group_C"][f"{arm}:{label}"] = entry
            log(f"\n  [{arm}] {label}: R_p PINNED at {rp*1e6:.3f} um"
                f"  ({rp/RP_TRUE:.3f}x the model's own value)")
            log(f"     D_s={entry['ds']:.5e}  ({entry['bias_D']*100:+9.2f} %)"
                f"   cost={entry['cost']:.6e}  evals={entry['n_evals']}")
            if entry["free_rp_reference"]:
                f0 = entry["free_rp_reference"]
                log(f"     (free R_p, same P4: D_s={f0['ds']:.5e}"
                    f"  {f0['bias_D']*100:+.1f} %  cost={f0['cost']:.6e})")

    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_4_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    log(f"\nreport -> {out / 'g5_4_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
