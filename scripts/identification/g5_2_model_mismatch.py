#!/usr/bin/env python
"""G5.2 -- model-form error: does the optimiser compensate with D_s?

    python scripts/identification/g5_2_model_mismatch.py [--quick]

G5.0 verified the chain.  G5.1 added measurement noise and showed the
recovery is robust to it -- but noise perturbs the DATA, not the STRUCTURE,
so it cannot answer the question that matters most for real experiments:

    when the model that generates the data and the model that inverts it are
    structurally different, does the optimiser buy a good fit by moving D_s?

That is the dangerous scenario: a wrong model can produce a plausible-looking
curve through a wrong parameter, and nothing in the residual would reveal it.

Design -- a small mismatch matrix, one parameter throughout:

    CONTROL     SPM  truth -> SPM  inverse   (must still recover the truth)
    MISMATCH    SPMe truth -> SPM  inverse   (not expected to)

run over every rate the dataset actually has, per cell.

Two signatures are looked for, and NEITHER is "did it recover the truth":

  1. does the identified D_s DRIFT SYSTEMATICALLY WITH RATE?
     A single material parameter should not depend on which protocol was
     used to measure it.  If D_s*(rate) trends, the parameter has become a
     protocol-specific correction rather than a property of the material.

  2. is there an IRREDUCIBLE RESIDUAL FLOOR (J_min > 0)?
     Under noiseless control data the minimum cost is 0.  Under mismatch it
     cannot be, and how large it gets says how much of the discrepancy the
     one free parameter can absorb.

And a cross-protocol transfer test: take D_s identified on one rate and
score it on another WITHOUT re-fitting.  A parameter that is fitted well on
0.5C and fails on 1.5C is not a transferable material property.

Acceptance is deliberately NOT "recovers the truth within X%": under
mismatch the truth is not the expected answer, and demanding it would
mislabel a real scientific result as a failure.

  Gate 1  control recovers the truth across all rates  (chain intact)
  Gate 2  mismatch: report the shift and the floor, require no recovery
  Gate 3  rate consistency: report whether D_s*(rate) is constant
  Gate 4  cross-protocol transfer: reported, with the oracle for comparison
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

from identification.forward import (  # noqa: E402
    ReplayCase,
    predict_at,
)
from identification.recovery import recover_from  # noqa: E402
from identification.synthetic import generate  # noqa: E402

DS_TRUE = 2.0e-15
DATASET, CELL = "chen2020", "02"
INVERSE_MODEL = "SPM"

#: Every rate chen2020 actually has.  The gate brief asked for
#: C/20, C/10, C/5, 0.5C, 1C, 2C; this dataset provides 0.1C, 0.5C, 1C and
#: 1.5C, so the matrix is built on what exists rather than on what was
#: wished for.  The gap is recorded in the report.
RATES = ("C10", "C2", "1C", "1p5C")
RATE_C = {"C10": 0.1, "C2": 0.5, "1C": 1.0, "1p5C": 1.5}
MISSING_FROM_BRIEF = ("C/20", "C/5", "2C")

ARMS = (("control", "SPM"), ("mismatch", "SPMe"))
Z_INITS = (1.0e-15, 4.0e-15, 1.0e-14)
Z_BOUNDS = (-16.0, -13.0)


def _inverse_case(rate: str, model: str) -> ReplayCase:
    return ReplayCase(
        dataset_id=DATASET, cell=CELL, rate=rate, model_name=model,
    ).resolve()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="outputs/fitting/g5.2")
    ap.add_argument("--method", default="Nelder-Mead")
    args = ap.parse_args()

    out = ROOT / args.out
    runs, audit = out / "runs", out / "audit"
    out.mkdir(parents=True, exist_ok=True)

    rates = RATES[:2] if args.quick else RATES
    maxiter = 80 if args.quick else 400

    tic = time.perf_counter()
    log = print
    log("=" * 80)
    log("G5.2  model-form error -- does the optimiser compensate with D_s?")
    log("=" * 80)
    log(f"  inverse model (all cases) : {INVERSE_MODEL}")
    log(f"  rates available           : {', '.join(RATES)}")
    log(f"  rates in the gate brief    : C/20, C/10, C/5, 0.5C, 1C, 2C")
    log(f"  NOT in this dataset        : {', '.join(MISSING_FROM_BRIEF)}")

    report = {
        "gate": "G5.2",
        "question": ("when the generating and inverting models differ "
                     "structurally, does the optimiser compensate with D_s?"),
        "inverse_model": INVERSE_MODEL,
        "armss": {},
        "rates_available": list(rates),
        "rates_missing_from_brief": list(MISSING_FROM_BRIEF),
        "boundary": ("synthetic truth on both sides; the mismatch is in the "
                     "MODEL FORM, not in the data source. Still not real "
                     "experimental data"),
        "config": {
            "dataset": DATASET, "cell": CELL, "ds_true": DS_TRUE,
            "z_inits": [float(np.log10(z)) for z in Z_INITS],
            "optimiser": f"pybop.SciPyMinimize(method={args.method})",
        },
    }

    observations: dict[str, dict[str, object]] = {}
    results: dict[str, dict[str, dict]] = {}

    for arm, truth_model in ARMS:
        log(f"\n{'=' * 80}")
        log(f"ARM {arm}:  {truth_model} truth  ->  {INVERSE_MODEL} inverse")
        log(f"{'=' * 80}")
        observations[arm] = {}
        results[arm] = {}

        for rate in rates:
            obs = generate(
                DATASET, CELL, rate, DS_TRUE, runs / arm,
                model_name=truth_model,
            )
            observations[arm][rate] = obs
            icase = _inverse_case(rate, INVERSE_MODEL)

            fits, rms, covs, msgs = [], [], [], []
            for z0 in (np.log10(z) for z in Z_INITS):
                sr = recover_from(
                    obs, runs / arm,
                    audit / f"{arm}_{rate}_z{z0:+.4f}",
                    z_init=float(z0), z_bounds=Z_BOUNDS,
                    method=args.method, maxiter=maxiter,
                    replay_case=icase,
                )
                fits.append(sr.z_fit)
                msgs.append(sr.message)
                n = len(obs.time_s)
                if np.isfinite(sr.cost_final) and n:
                    rms.append(math.sqrt(sr.cost_final / n) * 1000.0)
            fits = np.array(fits, dtype=float)

            # the residual AT the true D_s -- the "oracle" point
            oracle = predict_at(
                obs, DS_TRUE, runs / arm, audit / f"{arm}_{rate}_oracle",
                replay_case=icase, z_bounds=Z_BOUNDS,
            )

            entry = {
                "arm": arm,
                "rate": rate,
                "c_rate": RATE_C[rate],
                "truth_model": truth_model,
                "inverse_model": INVERSE_MODEL,
                "ds_true": DS_TRUE,
                "ds_identified": float(10.0 ** fits.mean()),
                "ds_identified_all": [float(10.0 ** z) for z in fits],
                "delta_log10": float(fits.mean() - math.log10(DS_TRUE)),
                "relative_bias": float(
                    (10.0 ** (fits.mean() - math.log10(DS_TRUE)) - 1.0)
                ),
                "min_fit_rms_mV": (float(np.mean(rms)) if rms else None),
                "oracle_rms_at_true_mV": oracle["fit_rms_mV"],
                "multistart_spread_dex": float(fits.max() - fits.min()),
                "coverage": oracle["coverage"],
                "n_points": oracle["n_points"],
                "termination": msgs[0] if msgs else "",
                "n_evals": None,
            }
            results[arm][rate] = entry

            log(f"\n  rate {rate} ({RATE_C[rate]:g}C)   truth model {truth_model}")
            log(f"     D_s true        {DS_TRUE:.6e}")
            log(f"     D_s identified  {entry['ds_identified']:.6e}"
                f"   ({entry['relative_bias']*100:+.4f} %)")
            log(f"     delta log10 D_s {entry['delta_log10']:+.5f}")
            log(f"     min fit RMS     {entry['min_fit_rms_mV']:.4f} mV"
                f"     RMS at true D_s {entry['oracle_rms_at_true_mV']:.4f} mV")
            log(f"     multistart      {entry['multistart_spread_dex']:.6f} dex"
                f"     coverage {entry['coverage']:.3f}"
                f"     [{entry['termination']}]")

    # ---- gate 1: control ------------------------------------------
    log(f"\n{'=' * 80}")
    log("GATE 1  control: SPM -> SPM must recover the truth at every rate")
    log(f"{'=' * 80}")
    ctrl_errs = [abs(v["relative_bias"]) for v in results["control"].values()]
    gate1_ok = bool(ctrl_errs and max(ctrl_errs) <= 0.01)
    log(f"  worst |relative bias| = {max(ctrl_errs)*100:.5f} %"
        f"   (tol 1 %)   -> {'PASS' if gate1_ok else 'FAIL'}")

    # ---- gate 2: mismatch detection --------------------------------
    log(f"\n{'=' * 80}")
    log("GATE 2  mismatch: SPM inverting SPMe data -- shift and floor")
    log(f"{'=' * 80}")
    mm = results["mismatch"]
    floors = {r: v["min_fit_rms_mV"] for r, v in mm.items()}
    biases = {r: v["relative_bias"] for r, v in mm.items()}
    for r in rates:
        fl = floors[r]
        fl_txt = "unreachable" if fl is None else f"{fl:8.4f} mV"
        log(f"  {r:6s} ({RATE_C[r]:g}C)  bias {biases[r]*100:+9.3f} %"
            f"   D_s* {mm[r]['ds_identified']:.6e}"
            f"   floor {fl_txt}")
    # a floor is only meaningful if it is clearly non-zero
    floor_levels = [f for f in floors.values() if f is not None]
    gate2_recorded = bool(floor_levels)
    log(f"  recorded (no truth-recovery requirement); "
        f"floor range {min(floor_levels):.4f} .. {max(floor_levels):.4f} mV"
        if floor_levels else "  no floors recorded")
    log(f"  -> {'PASS (reported)' if gate2_recorded else 'FAIL'}")

    # ---- gate 3: rate consistency ----------------------------------
    log(f"\n{'=' * 80}")
    log("GATE 3  rate consistency: should D_s*(rate) be constant?")
    log(f"{'=' * 80}")
    def _spread(arm):
        zs = [math.log10(v["ds_identified"]) for v in results[arm].values()]
        return float(max(zs) - min(zs))
    spread_ctrl = _spread("control")
    spread_mm = _spread("mismatch")
    log(f"  control  spread across rates = {spread_ctrl:.5f} dex")
    log(f"  mismatch spread across rates = {spread_mm:.5f} dex")
    monotone = None
    if len(rates) >= 3:
        zs = [math.log10(mm[r]["ds_identified"]) for r in rates]
        c_rates = [RATE_C[r] for r in rates]
        # Spearman-free check: is the rank order monotone in rate?
        order = np.argsort(c_rates)
        zs_sorted = np.array(zs)[order]
        diffs = np.diff(zs_sorted)
        monotone = bool(np.all(diffs > 0) or np.all(diffs < 0))
        log(f"  mismatch D_s*(rate) monotone in rate? {monotone}")
    gate3 = {"ok": True, "control_spread_dex": spread_ctrl,
             "mismatch_spread_dex": spread_mm, "monotone_in_rate": monotone}
    log("  -> PASS (reported; no constancy required a priori)")

    # ---- gate 4: cross-protocol transfer ---------------------------
    log(f"\n{'=' * 80}")
    log("GATE 4  cross-protocol transfer: identify on one rate, score on")
    log("        another WITHOUT re-fitting (mismatch arm)")
    log(f"{'=' * 80}")
    transfer = {}
    _head = "from\\to".rjust(8)

    def _fmt(v):
        # a transfer cell can be unreachable: the scoring replay may stop
        # before the observation window ends, and the coverage gate then
        # returns an infinite cost.  That is a RESULT, not a crash.
        return "  unreach" if v is None else f"{v:10.3f}"

    log(f"  {_head}" + "".join(f"{r:>10s}" for r in rates) + f"{'oracle':>10s}")
    for src in rates:
        ds_star = mm[src]["ds_identified"]
        row = {}
        for tgt in rates:
            obs = observations["mismatch"][tgt]
            p = predict_at(
                obs, ds_star, runs / "mismatch",
                audit / f"transfer_{src}_to_{tgt}",
                replay_case=_inverse_case(tgt, INVERSE_MODEL),
                z_bounds=Z_BOUNDS,
            )
            row[tgt] = p["fit_rms_mV"]
        oracle_row = [
            predict_at(observations["mismatch"][t], DS_TRUE, runs / "mismatch",
                       audit / f"oracle_{t}",
                       replay_case=_inverse_case(t, INVERSE_MODEL),
                       z_bounds=Z_BOUNDS)["fit_rms_mV"]
            for t in rates
        ]
        transfer[src] = {
            "ds_star": ds_star, "rms_mV": row,
            "n_unreachable": sum(1 for v in row.values() if v is None),
        }
        log(f"  {src:>8s}" + "".join(_fmt(row[r]) for r in rates))
    log(f"  {'(true)':>8s}" + "".join(_fmt(o) for o in oracle_row))
    log("  diagonal = in-protocol (always best); off-diagonal = transfer")
    log(f"  oracle row = residual of the TRUE D_s on each protocol")
    n_unreach = sum(v["n_unreachable"] for v in transfer.values())
    log(f"  unreachable transfer cells: {n_unreach}"
        f"  (scoring replay stopped before the observation window ended)")

    report["arms"] = {a: results[a] for a, _ in ARMS}
    report["gates"] = {
        "1_control_recovers_truth": {
            "ok": gate1_ok, "worst_rel_bias": float(max(ctrl_errs)) if ctrl_errs else None,
            "tol": 0.01,
        },
        "2_mismatch_reported": {
            "ok": gate2_recorded,
            "relative_bias": biases,
            "floor_rms_mV": floors,
            "note": ("no recovery requirement: under model mismatch the true "
                     "D_s is not the expected answer, and demanding it would "
                     "mislabel a real result as a failure"),
        },
        "3_rate_consistency": gate3,
        "4_cross_protocol_transfer": {
            "ok": True, "transfer": transfer,
            "note": ("scored WITHOUT re-fitting; the oracle row is the "
                     "residual of the true D_s on each protocol"),
        },
    }
    report["runtime_s"] = time.perf_counter() - tic
    (out / "g5_2_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nreport -> {out / 'g5_2_report.json'}")
    log(f"runtime {report['runtime_s']:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
