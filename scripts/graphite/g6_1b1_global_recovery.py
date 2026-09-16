"""G6.1b-1 -- Global log-multiplier recovery for a function-valued D_s(x).

WHERE THIS SITS
    G6 models the diffusivity as a log-space low-order correction

        log10 D_s(x) = log10 D_ref(x) + sum_j a_j phi_j(x)

    and the lowest order basis is a single constant: phi_0(x) = 1.  G6.1a
    already swept that axis by hand (x{0.316, 1, 3.162}, i.e. 0.5 dex
    steps) and showed the response exists and is monotone.  This gate
    FORMALISES that axis: the multiplier becomes a continuous variable a0,
    and the question stops being "does the trajectory move?" and becomes
    "does the INVERSE problem have its minimum where the truth is?".

THE CLAIM UNDER TEST
    A function-valued parameter that is numerically active is not thereby
    recoverable.  Activity is a statement about dV/da != 0; recovery is a
    statement about the SHAPE of J(a) = ||V(a) - V(a_0)||^2 around its
    minimum.  A one-sided or saturating J passes the first and fails the
    second.

WHAT THIS GATE CAN AND CANNOT SHOW  (this boundary must travel with the numbers)
    This is an INVERSE CRIME: the synthetic observation V(a_0) is produced
    by the same model, the same parameterisation and the same solver that
    the fit uses, with no noise and no model-form difference.  Therefore
    J(a_0) is EXACTLY ZERO BY CONSTRUCTION and the recovery criterion
    cannot fail unless the override never reached the model at all.
    Same red line as G5.0:

        synthetic recovery success  !=  experimental identifiability

    So R1 is a WIRING check.  The informative content of this gate is
    elsewhere: the width of the 1 mV band around the minimum (I1), its
    asymmetry, and the curvature.  "Recovery passed, therefore D_s is
    identifiable on DLR GITT" would be exactly the mistake this paragraph
    exists to prevent.

WHY A SCAN AND NOT AN OPTIMISER
    At one parameter a bounded scan is exact, and it yields the whole cost
    curve -- which IS the identifiability statement.  A gradient method
    reports a point estimate and hides a flat bottom.  A bounded Brent fit
    is run anyway, after the scan, as an independent check that a real
    optimiser lands on the same value; the two must agree to one fine step.

PRE-REGISTERED CRITERIA (fixed before the run):
    F1 forward activity   peak model-to-model RMSE over the scan >= 1.0 mV
    F2 forward ordering   dV_pulse strictly monotone across the scan
    R1 recovery           max |a_hat - a_0| <= 0.02 dex  (4.7 % in D_s)
    R2 interior           argmin strictly inside the scan, |a_hat| <= 0.95
    I1 identifiability    width of the {RMSE <= 1 mV} band <= 0.30 dex
    C1 optimiser agreement  scipy Brent within one fine step of the scan
    C2 scan coverage      no point of the scanned range unreachable
    C3 clean outside the pulse   override leaks < 0.01 mV into the rest
    N1 negative control   zero-excitation window: cost surface EXACTLY flat

    The Hessian condition number the design asked for is reported but is
    VACUOUS at d = 1: a 1x1 matrix has condition number 1 by definition
    and carries no information.  It becomes a real criterion at G6.1b-2
    (3-region, 3x3).  In its place the measured curvature J''(a_hat) and
    the band width are reported; the minimum is a MEASURED grid point,
    never an interpolated one (the G5.0 lesson).

WHAT THIS IS NOT
    Not a validation of Ecker2015, and not a determination of the true
    D_s(x) of the DLR cell.  Different cell, different laboratory,
    different electrode and OCP; the parameter set was not calibrated for
    it, which is why the dataset is declared `benchmark` in
    configs/datasets.yaml (see governance/dataset_roles.py).

Usage:
    python scripts/graphite/g6_1b1_global_recovery.py [--out outputs/fitting/g6.1b1]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import battery_sim.paths as paths  # noqa: E402

from battery_sim.models.pybamm_factory import (  # noqa: E402
    load_parameter_values,
    resolve_model_options,
)
from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.baseline import (  # noqa: E402
    _filter_and_downsample,
    _run_one_replay,
)
from battery_sim.simulation.protocol_replay import transient_metrics  # noqa: E402
from governance.scale_alignment import (  # noqa: E402
    PIPELINE_STAGES,
    alignment_overrides,
    audit,
)
from identification.replay_scan import (  # noqa: E402
    MultiplierScan as WindowReplay,
    build_multiplier_override as build_ds_override,
)

#: The function-valued parameter under test.
DS_KEY = "Positive particle diffusivity [m2.s-1]"

#: Synthetic truths, in dex of the multiplier on the recorded D_s(x,T).
#: They must land on the coarse grid or the "observation" would itself be
#: an interpolated object.
TRUTHS_DEX = (-0.5, 0.0, 0.5)

#: The scanned range.  +/-1 dex spans 0.1x .. 10x of the recorded function:
#: wide enough that the truth is never near the edge, and it is the axis
#: G6.1c will reuse for each basis coefficient.
SCAN_MIN_DEX, SCAN_MAX_DEX = -1.0, 1.0
COARSE_STEP_DEX = 0.05
FINE_STEP_DEX = 0.005
FINE_HALFSPAN_DEX = 0.05
HESSIAN_H_DEX = 0.02
NEGATIVE_STEP_DEX = 0.10

#: A run that stopped early is not "a small transient", it is a run that
#: did not happen.  Below this coverage the point is dropped and reported
#: as unreachable -- the identification layer's rule (better to fail than
#: to fit a fragment).
MIN_COVERAGE = 0.98

# ---- pre-registered thresholds ------------------------------------
RMSE_IDENTIFIABLE_MV = 1.0
BAND_MAX_DEX = 0.30
PEAK_MIN_MV = 1.0
RECOVERY_TOL_DEX = 0.02
BOUNDARY_MARGIN_DEX = 0.95
#: The override may not disturb the resting state.  Set at 1 % of the
#: identifiability level above (so 0.01 mV), which is at the solver's own
#: tolerance: anything larger would mean the cost surface is not a clean
#: function of D_s.
LEAK_MAX_MV = 0.01 * RMSE_IDENTIFIABLE_MV

WINDOWS: List[Dict[str, Any]] = [
    {
        "name": "GITT_plateau",
        "v_target_V": 0.1165,
        "role": "positive",
        "note": "graphite plateau; G6.1a measured the 0.5 dex spread at "
                "8.2450 mV of dV_pulse",
    },
    {
        "name": "GITT_steep",
        "v_target_V": 0.93,
        "role": "positive",
        "note": "steep OCP; G6.1a measured the 0.5 dex spread at "
                "29.3874 mV of dV_pulse",
    },
]

NEGATIVE_WINDOW: Dict[str, Any] = {
    "name": "zero_current_plateau",
    "v_target_V": 0.1165,
    "role": "negative",
    "zero_current": True,
    "note": "same window, same scale, same override path -- the excitation "
            "removed.  A pOCV window would change scale, duration and state "
            "at once and could not separate 'no excitation' from 'everything "
            "different' (that was G6.1a's failed negative control).",
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ``build_multiplier_override`` and ``WindowReplay`` live in
# identification/replay_scan.py: G6.1c scans 239 windows with exactly the
# same object, and two copies of the cost definition would drift silently.
# The names are imported above, so the body of this script is unchanged.


def _band(grid: np.ndarray, J: np.ndarray, a_hat: float,
          level_mV2: float) -> Dict[str, Any]:
    """The {J <= level} band around ``a_hat``.

    The estimator lives in ``identification/recovery_stats.py`` because
    G6.1c measures the same thing 239 times; two copies would drift
    invisibly.  This name is kept so the call sites and the report keys do
    not change.
    """
    from identification.recovery_stats import band_width

    return band_width(grid, J, a_hat, level_mV2)


def _fit_brent(win: WindowReplay, a_truth: float) -> Dict[str, Any]:
    """Independent optimiser check: bounded Brent on the same cost curve."""
    from scipy.optimize import minimize_scalar

    calls = {"n": 0}

    def f(a: float) -> float:
        calls["n"] += 1
        j = win.cost(a, a_truth)
        return 1e9 if not np.isfinite(j) else j

    res = minimize_scalar(
        f, bounds=(SCAN_MIN_DEX, SCAN_MAX_DEX), method="bounded",
        options={"xatol": 1e-4},
    )
    return {
        "a_hat_dex": float(res.x),
        "cost_mV2": float(res.fun),
        "n_evaluations": int(calls["n"]),
        "converged": bool(res.success),
    }


def analyse_window(win: WindowReplay, grid: np.ndarray,
                   *, verbose: bool = True) -> Dict[str, Any]:
    """Scan, recover, and measure the cost-curve shape for one window."""
    recs = [win.evaluate(float(a)) for a in grid]
    reach = np.array([win.reachable(r) for r in recs], dtype=bool)
    unreachable = [float(g) for g, ok in zip(grid, reach) if not ok]
    used = grid[reach]
    if used.size < 5:
        raise RuntimeError(
            f"{win.protocol_id}: only {used.size} of {grid.size} scan points "
            f"are reachable; there is no cost curve to analyse"
        )

    dv = np.array([r["dv_pulse_mV"] for r in recs], dtype=float)[reach]
    finite_dv = dv[np.isfinite(dv)]
    entry: Dict[str, Any] = {
        "protocol_id": win.protocol_id,
        "n_reference_points": win.n_ref,
        "scan_requested_dex": [SCAN_MIN_DEX, SCAN_MAX_DEX],
        "scan_used_dex": [float(used.min()), float(used.max())],
        "scan_narrowed": bool(used.size != grid.size),
        "coarse_step_dex": COARSE_STEP_DEX,
        "n_grid_points": int(grid.size),
        "n_unreachable": int((~reach).sum()),
        "unreachable_dex": unreachable,
        "ordered_by_a": bool(
            finite_dv.size == used.size and finite_dv.size > 2
            and (np.all(np.diff(finite_dv) > 0)
                 or np.all(np.diff(finite_dv) < 0))
        ),
        "dv_pulse_mV_vs_a": {f"{r['a_dex']:+.3f}": r["dv_pulse_mV"]
                             for r, ok in zip(recs, reach) if ok},
        "truths": {},
        "pre_pulse_leak_mV": win.pre_pulse_leak_mV(SCAN_MAX_DEX),
        "n_simulations": win.n_sim,
        "runtime_s": win.runtime_s,
    }

    for a_truth in TRUTHS_DEX:
        a_truth = round(float(a_truth), 6)
        if not (used.min() <= a_truth <= used.max()):
            raise RuntimeError(
                f"{win.protocol_id}: truth {a_truth} lies outside the "
                f"reachable scan range [{used.min()}, {used.max()}]"
            )
        J = np.array([win.cost(float(a), a_truth) for a in used])
        a_hat_coarse = float(used[int(np.argmin(J))])

        fine = np.round(
            a_hat_coarse + np.arange(-FINE_HALFSPAN_DEX,
                                     FINE_HALFSPAN_DEX + 1e-9, FINE_STEP_DEX),
            6,
        )
        fine = fine[(fine >= used.min()) & (fine <= used.max())]
        J_fine = np.array([win.cost(float(a), a_truth) for a in fine])
        a_hat = float(fine[int(np.argmin(J_fine))])

        # union of MEASURED points, so the band is read off real runs
        union = np.unique(np.concatenate([used, fine]))
        J_union = np.array([win.cost(float(a), a_truth) for a in union])
        band = _band(union, J_union, a_hat, RMSE_IDENTIFIABLE_MV ** 2)

        j0 = win.cost(a_hat, a_truth)
        jp = win.cost(a_hat + HESSIAN_H_DEX, a_truth)
        jm = win.cost(a_hat - HESSIAN_H_DEX, a_truth)
        curvature = (
            float((jp - 2.0 * j0 + jm) / (HESSIAN_H_DEX ** 2))
            if np.isfinite(jp) and np.isfinite(jm) else float("nan")
        )
        asym = (
            float((jp - jm) / (jp + jm))
            if np.isfinite(jp) and np.isfinite(jm) and (jp + jm) > 0
            else float("nan")
        )
        at_max = win.compare(float(used.max()), a_truth)
        at_min = win.compare(float(used.min()), a_truth)

        entry["truths"][f"{a_truth:+.3f}"] = {
            "a_truth_dex": a_truth,
            "a_hat_grid_dex": a_hat_coarse,
            "a_hat_refined_dex": a_hat,
            "recovery_error_dex": float(a_hat - a_truth),
            "recovery_error_pct_in_D": float(
                (10.0 ** (a_hat - a_truth) - 1.0) * 100.0
            ),
            "cost_at_truth_mV2": float(win.cost(a_truth, a_truth)),
            "cost_at_a_hat_mV2": float(j0),
            "J_max_mV2": float(np.nanmax(J[np.isfinite(J)])),
            "peak_model_to_model_rmse_mV": float(
                np.nanmax([at_min["rmse_mV"], at_max["rmse_mV"]])
            ),
            "rmse_at_scan_min_mV": at_min["rmse_mV"],
            "rmse_at_scan_max_mV": at_max["rmse_mV"],
            "cost_at_a_hat_pm_h_mV2": {
                f"minus_{HESSIAN_H_DEX}": float(jm),
                f"plus_{HESSIAN_H_DEX}": float(jp),
            },
            "curvature_Jpp_mV2_per_dex2": curvature,
            "curvature_asymmetry": asym,
            "band_at_1mV": band,
            "brent": None,       # filled after the scan, deliberately
        }

    # independent optimiser check runs AFTER the scan, so the scan's
    # numbers are already fixed and cannot be tuned to match it
    for a_truth in TRUTHS_DEX:
        a_truth = round(float(a_truth), 6)
        key = f"{a_truth:+.3f}"
        brent = _fit_brent(win, a_truth)
        brent["agreement_dex"] = float(
            brent["a_hat_dex"] - entry["truths"][key]["a_hat_refined_dex"]
        )
        entry["truths"][key]["brent"] = brent

    if verbose:
        log(f"    reachable          : {used.size} / {grid.size} points "
            f"[{used.min():+.2f}, {used.max():+.2f}] dex")
        log(f"    ordered by a       : {entry['ordered_by_a']}")
        log(f"    pre-pulse leak     : {entry['pre_pulse_leak_mV']:.3e} mV "
            f"(must be < {LEAK_MAX_MV} mV: the override cannot move rest)")
        for key, t in entry["truths"].items():
            log(f"    a0={key}  a_hat {t['a_hat_refined_dex']:+.4f} dex "
                f"(grid {t['a_hat_grid_dex']:+.4f}, brent "
                f"{t['brent']['a_hat_dex']:+.4f})")
            log(f"            err {t['recovery_error_dex']:+.6f} dex "
                f"({t['recovery_error_pct_in_D']:+.3f} % in D)  "
                f"peakRMSE {t['peak_model_to_model_rmse_mV']:.3f} mV")
            log(f"            band@1mV {t['band_at_1mV']['width_dex']:.4f} dex "
                f"(L {t['band_at_1mV']['left_dex']:.4f} / "
                f"R {t['band_at_1mV']['right_dex']:.4f}, "
                f"res {t['band_at_1mV']['resolution_dex']}, "
                f"trunc {t['band_at_1mV']['truncated']})")
            log(f"            J'' {t['curvature_Jpp_mV2_per_dex2']:.6e} "
                f"mV^2/dex^2   asymmetry {t['curvature_asymmetry']:+.4f}"
                f"   cost@truth {t['cost_at_truth_mV2']:.3e} mV^2")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/fitting/g6.1b1")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    paths.PLATFORM_OUTPUT_ROOT = out / "platform_runs"

    tic = time.perf_counter()
    report: Dict[str, Any] = {
        "gate": "G6.1b-1",
        "claim": (
            "a function-valued D_s(x) that is numerically active is not "
            "thereby recoverable; the inverse problem needs a cost-curve "
            "minimum of finite width, not just a non-zero derivative"
        ),
        "representation": "log10 D_s(x) = log10 D_ref(x) + a0,  phi_0(x) = 1",
        "ds_key": DS_KEY,
        "truths_dex": list(TRUTHS_DEX),
        "criteria": {
            "F1_forward_activity_min_peak_rmse_mV": PEAK_MIN_MV,
            "F2_forward_ordering": "dV_pulse strictly monotone across the scan",
            "R1_recovery_tol_dex": RECOVERY_TOL_DEX,
            "R2_interior_margin_dex": BOUNDARY_MARGIN_DEX,
            "I1_band_max_dex": BAND_MAX_DEX,
            "I1_band_level_mV": RMSE_IDENTIFIABLE_MV,
            "C1_optimiser_agreement_dex": FINE_STEP_DEX,
            "C2_scan_coverage": "every requested scan point reachable",
            "C3_clean_outside_pulse_max_mV": LEAK_MAX_MV,
            "N1_negative_flat": "cost surface exactly flat without excitation",
        },
        "scan": {
            "min_dex": SCAN_MIN_DEX, "max_dex": SCAN_MAX_DEX,
            "coarse_step_dex": COARSE_STEP_DEX,
            "fine_step_dex": FINE_STEP_DEX,
            "fine_halfspan_dex": FINE_HALFSPAN_DEX,
            "hessian_h_dex": HESSIAN_H_DEX,
            "min_coverage": MIN_COVERAGE,
        },
        "pipeline_stages": list(PIPELINE_STAGES),
        "scale_alignment": {},
        "windows": {},
        "negative_control": {},
        "inverse_crime_note": (
            "the synthetic observation is the a0 point of the same scan, "
            "produced by the same model, parameterisation and solver as the "
            "fit, with no noise -- so J(a0) = 0 BY CONSTRUCTION and recovery "
            "success is a wiring check, not identifiability (G5.0 red line)"
        ),
    }

    log("=" * 92)
    log("G6.1b-1  global log-multiplier recovery for a function-valued D_s(x)")
    log("=" * 92)
    log(f"  pipeline: {' -> '.join(PIPELINE_STAGES)}")

    adapter = get_dataset("dlr_gitt")
    ps = adapter.config.parameter_set
    model_options = resolve_model_options(adapter)
    cell = "Hydra.0b_A"

    # ---- stages 1-2: geometry audit + capacity alignment -----------
    log("")
    log("-" * 92)
    log("stage 1-2  geometry audit + capacity alignment "
        "(governance/scale_alignment.py)")
    log("-" * 92)
    al_rec = audit(adapter, "GITT-discharge", cell)
    log(f"  model capacity    : {al_rec['model_capacity_Ah'] * 1e3:.3f} mAh "
        f"({al_rec['parameter_set']})")
    log(f"  measured charge   : {al_rec['measured_charge_Ah'] * 1e3:.4f} mAh "
        f"over '{al_rec['charge_reference']}'")
    log(f"  verdict           : {al_rec['verdict'].upper()}  "
        f"(x{al_rec['capacity_ratio_model_over_measured']:.1f}, "
        f"{al_rec['log10_model_over_measured']:+.3f} dex, tolerance "
        f"+/-{al_rec['tolerance_dex']} dex)")
    log(f"  C-rate as read    : C/{1.0 / al_rec['c_rate_on_cell']:.1f}")
    log(f"  C-rate on model   : C/{1.0 / al_rec['c_rate_on_model_unscaled']:.0f}"
        f"   <- only this one decides whether diffusion is excited")
    report["scale_alignment"] = al_rec

    # ---- positive windows ------------------------------------------
    replay_objects: Dict[str, WindowReplay] = {}
    grids: Dict[str, np.ndarray] = {}
    for spec in WINDOWS:
        log("")
        log("-" * 92)
        log(f"[positive] {spec['name']}   ({spec['note']})")
        log("-" * 92)

        pid = adapter.find_triplet("discharge", spec["v_target_V"])
        df = adapter.load_processed_protocol(cell, pid)
        protocol = adapter.load_protocol(pid)
        align = alignment_overrides(adapter, pid, cell)
        log(f"  window      : {pid}")
        log(f"  {protocol.describe()}")
        log(f"  alignment   : area x{align['footprint_scale_area']:.6f} "
            f"(linear x{align['footprint_scale_linear']:.6f})")

        win = WindowReplay(adapter, cell, pid, df, protocol, ps,
                           model_options, align)
        # determinism: the same a twice.  Without it, "J(a0) = 0" could be
        # read as a property of the physics rather than of the code.
        first = win.evaluate(SCAN_MAX_DEX)
        dup = win.evaluate(SCAN_MAX_DEX, force=True)
        det = float(np.nanmax(np.abs(first["V_ref"] - dup["V_ref"]))) * 1e3

        grid = np.round(
            np.arange(SCAN_MIN_DEX, SCAN_MAX_DEX + 1e-9, COARSE_STEP_DEX), 6
        )
        entry = analyse_window(win, grid)
        entry["determinism_max_abs_dV_mV"] = det
        entry["v_target_V"] = spec["v_target_V"]
        entry["note"] = spec["note"]
        entry["n_simulations"] = win.n_sim
        entry["runtime_s"] = win.runtime_s
        log(f"  determinism : max |dV| between two identical runs = "
            f"{det:.3e} mV")
        report["windows"][spec["name"]] = entry
        replay_objects[spec["name"]] = win
        grids[spec["name"]] = grid

    # ---- negative control ------------------------------------------
    log("")
    log("=" * 92)
    log(f"[negative] {NEGATIVE_WINDOW['name']}   ({NEGATIVE_WINDOW['note']})")
    log("=" * 92)
    pid = adapter.find_triplet("discharge", NEGATIVE_WINDOW["v_target_V"])
    df = adapter.load_processed_protocol(cell, pid)
    protocol = adapter.load_protocol(pid)
    align = alignment_overrides(adapter, pid, cell)
    negg = WindowReplay(adapter, cell, pid, df, protocol, ps, model_options,
                        align, zero_current=True)
    neg_grid = np.round(
        np.arange(SCAN_MIN_DEX, SCAN_MAX_DEX + 1e-9, NEGATIVE_STEP_DEX), 6
    )
    neg_recs = [negg.evaluate(float(a)) for a in neg_grid]
    ref = neg_recs[0]["V_ref"]
    max_dev = 0.0
    for r in neg_recs[1:]:
        m = np.isfinite(ref) & np.isfinite(r["V_ref"])
        if m.any():
            max_dev = max(max_dev,
                          float(np.max(np.abs(ref[m] - r["V_ref"][m]))) * 1e3)
    cost_max = float(max(negg.cost(float(a), float(b))
                         for a in neg_grid for b in neg_grid))

    a_init = 0.0
    neg_entry: Dict[str, Any] = {
        "protocol_id": pid,
        "zero_current": True,
        "n_grid_points": int(neg_grid.size),
        "max_abs_dV_across_a_mV": max_dev,
        "flat": bool(max_dev == 0.0),
        "cost_matrix_max_mV2": cost_max,
        "a_init_dex": a_init,
        "per_truth": {},
        "n_simulations": negg.n_sim,
        "runtime_s": negg.runtime_s,
        "estimator_note": (
            "with a flat cost surface every point is a minimum, so np.argmin "
            "returns an index artefact.  The honest statement is that a "
            "deterministic optimiser returns its INITIAL GUESS; the implied "
            "error is |a_init - a0| and is labelled derived, not measured."
        ),
    }
    for a_truth in TRUTHS_DEX:
        a_truth = round(float(a_truth), 4)
        neg_entry["per_truth"][f"{a_truth:+.2f}"] = {
            "a_truth_dex": a_truth,
            "estimator_returns_initial_guess_dex": a_init,
            "implied_error_dex": float(abs(a_init - a_truth)),
            "implied_error_pct_in_D": float(
                abs(10.0 ** (a_init - a_truth) - 1.0) * 100.0
            ),
            "derived_not_measured": True,
        }
    log(f"  max |dV| across all a : {max_dev:.6e} mV  "
        f"(exactly flat: {neg_entry['flat']})")
    log(f"  cost matrix max       : {cost_max:.6e} mV^2")
    log(f"  reachability          : "
        f"{sum(negg.reachable(r) for r in neg_recs)}/{len(neg_recs)}")
    log("  -> the excitation is gone, so the parameter is not merely")
    log("     inactive: the cost surface is EXACTLY flat and the estimator")
    log("     has no information at all.  Its output is its initial guess;")
    log("     for a0 = +/-0.5 dex the implied error is 0.5 dex (3.16x in")
    log("     D_s), reported as derived, not measured.")
    report["negative_control"] = neg_entry

    # ---- pre-registered verdict ------------------------------------
    pos = report["windows"]
    peak_max = max(t["peak_model_to_model_rmse_mV"]
                   for w in pos.values() for t in w["truths"].values())
    err_max = max(abs(t["recovery_error_dex"])
                  for w in pos.values() for t in w["truths"].values())
    interior_ok = all(abs(t["a_hat_refined_dex"]) <= BOUNDARY_MARGIN_DEX
                      for w in pos.values() for t in w["truths"].values())
    band_max = max(t["band_at_1mV"]["width_dex"]
                   for w in pos.values() for t in w["truths"].values())
    brent_ok = all(
        abs(t["brent"]["agreement_dex"]) <= FINE_STEP_DEX and t["brent"]["converged"]
        for w in pos.values() for t in w["truths"].values()
    )
    unreachable_total = sum(w["n_unreachable"] for w in pos.values())
    leaks = [abs(w["pre_pulse_leak_mV"]) for w in pos.values()
             if np.isfinite(w["pre_pulse_leak_mV"])]
    leak_max = max(leaks) if leaks else float("nan")

    crit = {
        "F1_forward_activity": bool(peak_max >= PEAK_MIN_MV),
        "F2_forward_ordering": bool(all(w["ordered_by_a"] for w in pos.values())),
        "R1_recovery": bool(err_max <= RECOVERY_TOL_DEX),
        "R2_interior": bool(interior_ok),
        "I1_identifiability_band": bool(band_max <= BAND_MAX_DEX),
        "C1_optimiser_agreement": bool(brent_ok),
        "C2_scan_coverage": bool(unreachable_total == 0),
        "C3_clean_outside_pulse": bool(
            np.isfinite(leak_max) and leak_max < LEAK_MAX_MV
        ),
        "N1_negative_control_flat": bool(neg_entry["flat"]),
    }
    passed = all(crit.values())

    report["verdict"] = {
        "criteria": crit,
        "max_recovery_error_dex": float(err_max),
        "max_peak_model_to_model_rmse_mV": float(peak_max),
        "max_band_width_dex": float(band_max),
        "max_pre_pulse_leak_mV": float(leak_max),
        "n_unreachable_points": int(unreachable_total),
        "hessian_condition_number": 1.0,
        "hessian_condition_number_note": (
            "VACUOUS at d = 1: a 1x1 matrix has condition number 1 by "
            "definition and carries no information.  It becomes a real "
            "criterion at G6.1b-2 (3-region, 3x3).  In its place the "
            "measured curvature J''(a_hat) and the 1 mV band width are "
            "reported per truth; the minimum is a measured grid point, "
            "never an interpolated one."
        ),
        "passed": bool(passed),
        "n_simulations_total": int(
            sum(w["n_simulations"] for w in pos.values()) + negg.n_sim
        ),
        "runtime_s": time.perf_counter() - tic,
    }

    log("")
    log("=" * 92)
    for k, v in crit.items():
        log(f"  {'PASS' if v else 'FAIL'}  {k}")
    log(f"  peak model-to-model RMSE : {peak_max:.4f} mV "
        f"(need >= {PEAK_MIN_MV})")
    log(f"  max recovery error       : {err_max:+.6f} dex "
        f"(tolerance {RECOVERY_TOL_DEX})")
    log(f"  max band at 1 mV         : {band_max:.4f} dex "
        f"(limit {BAND_MAX_DEX})")
    log(f"  unreachable points       : {unreachable_total}")
    log(f"  pre-pulse leak           : {leak_max:.3e} mV "
        f"(limit {LEAK_MAX_MV})")
    log(f"  GATE PASSED              : {passed}")
    log(f"  simulations              : {report['verdict']['n_simulations_total']}")
    log(f"  runtime                  : {report['verdict']['runtime_s']:.1f} s")
    log("=" * 92)
    log("")
    log("NOTE  R1 (recovery) cannot fail unless the override never reached")
    log("      the model: the synthetic observation IS the truth point of")
    log("      the same scan, so J(a0) = 0 by construction.  This is an")
    log("      inverse crime, and synthetic recovery success is NOT")
    log("      experimental identifiability (same red line as G5.0).  The")
    log("      informative content here is the SHAPE of the cost curve:")
    log("      band width, asymmetry, curvature.")

    rows = []
    for wname, w in pos.items():
        for tkey, t in w["truths"].items():
            rows.append({
                "window": wname,
                "a_truth_dex": t["a_truth_dex"],
                "a_hat_grid_dex": t["a_hat_grid_dex"],
                "a_hat_refined_dex": t["a_hat_refined_dex"],
                "a_hat_brent_dex": t["brent"]["a_hat_dex"],
                "recovery_error_dex": t["recovery_error_dex"],
                "recovery_error_pct_in_D": t["recovery_error_pct_in_D"],
                "band_width_dex": t["band_at_1mV"]["width_dex"],
                "band_left_dex": t["band_at_1mV"]["left_dex"],
                "band_right_dex": t["band_at_1mV"]["right_dex"],
                "band_truncated": t["band_at_1mV"]["truncated"],
                "band_resolution_dex": t["band_at_1mV"]["resolution_dex"],
                "curvature_Jpp_mV2_per_dex2": t["curvature_Jpp_mV2_per_dex2"],
                "curvature_asymmetry": t["curvature_asymmetry"],
                "peak_model_to_model_rmse_mV": t["peak_model_to_model_rmse_mV"],
                "cost_at_truth_mV2": t["cost_at_truth_mV2"],
                "cost_at_a_hat_mV2": t["cost_at_a_hat_mV2"],
            })
    pd.DataFrame(rows).to_csv(out / "g6_1b1_recovery.csv", index=False)

    # cost curves are read back from the SAME replay objects, so this file
    # costs no extra simulations and cannot disagree with the scan
    curve_rows = []
    for wname, win in replay_objects.items():
        for a_truth in TRUTHS_DEX:
            a_truth = round(float(a_truth), 6)
            for a in grids[wname]:
                J = win.cost(float(a), a_truth)
                curve_rows.append({
                    "window": wname,
                    "a_truth_dex": a_truth,
                    "a_dex": float(a),
                    "cost_mV2": J,
                    "rmse_mV": float(math.sqrt(J)) if np.isfinite(J) else float("nan"),
                    "reachable": bool(win.reachable(win.evaluate(float(a)))),
                })
    pd.DataFrame(curve_rows).to_csv(out / "g6_1b1_cost_curves.csv", index=False)

    (out / "g6_1b1_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nwrote {out / 'g6_1b1_report.json'}")
    log(f"wrote {out / 'g6_1b1_recovery.csv'}")
    log(f"wrote {out / 'g6_1b1_cost_curves.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
