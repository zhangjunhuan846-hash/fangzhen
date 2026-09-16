"""G5.0 -- single-parameter synthetic recovery of D_s.

Answers exactly one question:

    given a synthetic voltage response generated at a KNOWN D_s, can this
    pipeline find that D_s back?

Four things are checked, and the third matters as much as the others:

  1. do the different initial guesses converge to the SAME basin?
  2. is the recovered D_s close to the truth?
  3. does an EXPLICIT one-dimensional cost scan J(log10 D_s) have its
     minimum near the truth?  (An optimiser stopping somewhere is not
     evidence that the somewhere is a minimum -- it might just have run
     out of iterations.  The scan is what makes the claim checkable.)
  4. is every candidate evaluation attributable -- requested, applied,
     source, and the platform metadata that produced it?

Scope is deliberately frozen: one parameter, one synthetic dataset, no real
Chen2020 fitting, no second parameter, no agent.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from identification.forward import Z_NAME, Observation, build_problem


def _cost_of(evaluation) -> float:
    """PyBOP returns an Evaluation; the scalar is in ``.values``."""
    vals = np.asarray(evaluation.values if hasattr(evaluation, "values")
                      else evaluation, dtype=float)
    return float(np.ravel(vals)[0])


def cost_scan(
    observation: Observation,
    output_root: Path,
    audit_dir: Path,
    z_min: float = -15.7,
    z_max: float = -13.3,
    n: int = 13,
    z_bounds: Sequence[float] = (-16.0, -13.0),
    refine_n: int = 15,
    refine_cells: float = 1.5,
    z_truth: Optional[float] = None,
) -> Dict[str, Any]:
    """Explicit J(log10 D_s) on a grid -- does NOT trust the optimiser.

    Two stages, because one is not enough to support the claim it is used
    for.  A coarse grid can only localise a minimum to within ONE CELL, so
    comparing its argmin against a tolerance finer than the spacing tests
    the grid resolution, not the physics -- which is exactly what happened
    on this gate's first run (spacing 0.4 dex, tolerance 0.15 dex, cost at
    the truth nine orders of magnitude below every grid point).

    So the coarse pass is followed by a refinement around its argmin.  Both
    passes are reported, along with the achieved resolution, so the final
    claim is stated at the precision actually measured.
    """
    problem, sim = build_problem(
        observation, output_root=output_root, audit_dir=audit_dir,
        z_bounds=tuple(z_bounds),
    )

    def evaluate(zs):
        return [float(_cost_of(problem.evaluate({Z_NAME: float(z)})))
                for z in zs]

    zs_coarse = np.linspace(float(z_min), float(z_max), int(n))
    cost_coarse = evaluate(zs_coarse)

    finite = np.isfinite(cost_coarse)
    if not finite.any():
        z_argmin_coarse = float(zs_coarse[len(zs_coarse) // 2])
    else:
        idx = int(np.nanargmin(np.where(finite, cost_coarse, np.inf)))
        z_argmin_coarse = float(zs_coarse[idx])

    spacing = (float(z_max) - float(z_min)) / max(1, int(n) - 1)
    half = refine_cells * spacing
    zs_fine = np.linspace(z_argmin_coarse - half, z_argmin_coarse + half,
                          int(refine_n))
    cost_fine = evaluate(zs_fine)

    zs_all = np.concatenate([zs_coarse, zs_fine])
    cost_all = list(cost_coarse) + list(cost_fine)

    # MEASURE the cost at the truth rather than interpolating it.  The
    # minimum here is a few 1e-4 dex wide, so a linear interpolation
    # between neighbouring grid points overestimates its value by orders of
    # magnitude -- which would make the truth look worse than the grid and
    # fail the very check it is supposed to satisfy.
    cost_at_truth = None
    if z_truth is not None:
        cost_at_truth = float(
            _cost_of(problem.evaluate({Z_NAME: float(z_truth)}))
        )

    order = np.argsort(zs_all)
    zs_all, cost_all = zs_all[order], [cost_all[i] for i in order]

    finite_all = np.isfinite(cost_all)
    idx_all = int(np.nanargmin(np.where(finite_all, cost_all, np.inf)))
    z_argmin = float(zs_all[idx_all])

    sim.write_audit(Path(audit_dir) / "cost_scan_evaluations.json")
    return {
        "z": [float(x) for x in zs_all],
        "ds": [float(10.0 ** x) for x in zs_all],
        "cost": cost_all,
        "coarse": {
            "z": [float(x) for x in zs_coarse],
            "cost": cost_coarse,
            "spacing_dex": spacing,
            "n_points": int(n),
        },
        "refined": {
            "z": [float(x) for x in zs_fine],
            "cost": cost_fine,
            "span_dex": float(2 * half),
            "resolution_dex": float(2 * half / max(1, int(refine_n) - 1)),
            "n_points": int(refine_n),
        },
        "z_argmin": z_argmin,
        "ds_argmin": float(10.0 ** z_argmin),
        "cost_min": float(min(c for c in cost_all if np.isfinite(c))),
        "achieved_resolution_dex": float(
            2 * half / max(1, int(refine_n) - 1)
        ),
        "n_points": int(len(zs_all)),
        "n_evaluations": len(sim.records),
        "n_unreachable": int(sum(1 for c in cost_all if not np.isfinite(c))),
        # measured, not interpolated
        "z_truth": (None if z_truth is None else float(z_truth)),
        "cost_at_truth_measured": cost_at_truth,
    }


@dataclass
class StartResult:
    z_init: float
    z_fit: float
    ds_fit: float
    cost_final: float
    cost_initial: Optional[float]
    n_evaluations: int
    n_iterations: int
    message: str
    method: str
    audit_path: str
    ds_truth: float = 2.0e-15
    rel_error: float = field(init=False, default=float("nan"))

    def __post_init__(self):
        if self.ds_truth:
            self.rel_error = abs(self.ds_fit - self.ds_truth) / self.ds_truth


def recover_from(
    observation: Observation,
    output_root: Path,
    audit_dir: Path,
    z_init: float,
    z_bounds: Sequence[float] = (-16.0, -13.0),
    method: str = "Nelder-Mead",
    maxiter: int = 400,
    replay_case=None,
) -> StartResult:
    """One multi-start leg: PyBOP ``SciPyMinimize`` from ``z_init``.

    ``replay_case`` lets the inverse model differ from the truth model, which
    is what a model-mismatch test needs (SPMe generates, SPM inverts).
    """
    import pybop

    problem, sim = build_problem(
        observation, output_root=output_root, audit_dir=audit_dir,
        z_bounds=tuple(z_bounds), z_initial=float(z_init),
        replay_case=replay_case,
    )

    options = pybop.SciPyMinimizeOptions(method=method, maxiter=int(maxiter))
    optimiser = pybop.SciPyMinimize(problem, options=options)
    result = optimiser.run()

    x = np.atleast_1d(np.asarray(result.x, dtype=float))
    z_fit = float(x[0])
    sim.write_audit(Path(audit_dir) / "optimiser_evaluations.json")

    cost_final = float(
        result.best_cost if getattr(result, "best_cost", None) is not None
        else _cost_of(problem.evaluate({Z_NAME: z_fit}))
    )
    cost_initial = getattr(result, "initial_cost", None)

    return StartResult(
        z_init=float(z_init),
        z_fit=z_fit,
        ds_fit=float(10.0 ** z_fit),
        cost_final=cost_final,
        cost_initial=(float(cost_initial) if cost_initial is not None else None),
        n_evaluations=int(getattr(result, "n_evaluations", 0) or 0),
        n_iterations=int(getattr(result, "n_iterations", 0) or 0),
        message=str(getattr(result, "message", "")),
        method=str(method),
        audit_path=str(Path(audit_dir) / "optimiser_evaluations.json"),
        ds_truth=observation.ds_true,
    )


def check_acceptance(
    scan: Dict[str, Any],
    starts: List[StartResult],
    ds_truth: float,
    basin_tol_dex: float = 0.05,
    rel_tol: float = 0.05,
    scan_tol_dex: float = 0.15,
) -> Dict[str, Any]:
    """The four G5.0 acceptance items, each with its evidence."""
    z_truth = math.log10(ds_truth)
    z_fits = np.array([s.z_fit for s in starts], dtype=float)

    # 1. same basin
    spread = float(z_fits.max() - z_fits.min()) if len(z_fits) else float("nan")
    same_basin = bool(len(z_fits) >= 2 and spread <= basin_tol_dex)

    # 2. close to truth
    errs = [abs(s.ds_fit - ds_truth) / ds_truth for s in starts]
    worst_rel = max(errs) if errs else float("nan")
    close_to_truth = bool(worst_rel <= rel_tol)

    # 3. explicit scan minimum near truth.
    #    A grid cannot localise a minimum better than its own step, so the
    #    tolerance is the ACHIEVED resolution (whichever is coarser), not a
    #    number chosen in advance.
    #
    #    The second condition -- "the truth must be at least as good as the
    #    best grid point" -- uses the MEASURED cost at the truth.  An
    #    earlier version interpolated it linearly between grid points and
    #    got it wrong by four orders of magnitude, because this minimum is
    #    only ~1e-3 dex wide; that is a property of the interpolator, not
    #    of the cost surface, and it must not be allowed to fail the gate.
    resolution = float(scan.get("achieved_resolution_dex", scan_tol_dex))
    tol = max(float(scan_tol_dex), resolution)
    dz = abs(scan["z_argmin"] - z_truth)
    cost_at_truth = scan.get("cost_at_truth_measured")
    if cost_at_truth is None:
        cost_at_truth = float(np.interp(z_truth, scan["z"], scan["cost"]))
        measured = False
    else:
        measured = True
    truth_at_least_as_good = bool(
        np.isfinite(cost_at_truth)
        and cost_at_truth <= scan["cost_min"] * (1 + 1e-9)
    )
    scan_ok = bool(dz <= tol and truth_at_least_as_good)

    # 4. provenance present on every recorded evaluation
    audit_files = [Path(s.audit_path) for s in starts]
    n_records = 0
    missing = 0
    for f in audit_files:
        if not f.is_file():
            missing += 1
            continue
        for rec in json.loads(f.read_text(encoding="utf-8")):
            n_records += 1
            if not rec.get("requested") or not rec.get("applied") \
                    or not rec.get("json_path"):
                missing += 1
    provenance_ok = bool(n_records > 0 and missing == 0)

    return {
        "z_truth": z_truth,
        "n_starts": len(starts),
        "1_same_basin": {
            "ok": same_basin,
            "z_fits": [float(z) for z in z_fits],
            "spread_dex": spread,
            "tol_dex": basin_tol_dex,
        },
        "2_close_to_truth": {
            "ok": close_to_truth,
            "ds_truth": ds_truth,
            "ds_fits": [s.ds_fit for s in starts],
            "rel_errors": errs,
            "worst_rel_error": worst_rel,
            "tol": rel_tol,
        },
        "3_cost_minimum_near_truth": {
            "ok": scan_ok,
            "z_argmin": scan["z_argmin"],
            "ds_argmin": float(10.0 ** scan["z_argmin"]),
            "distance_dex": dz,
            # the tolerance actually applied, and whether the grid or the
            # nominal value set it
            "tol_dex": tol,
            "nominal_tol_dex": float(scan_tol_dex),
            "achieved_resolution_dex": resolution,
            "tol_source": ("grid_resolution" if resolution > float(scan_tol_dex)
                           else "nominal"),
            "cost_min_on_grid": scan["cost_min"],
            "cost_at_truth": cost_at_truth,
            "cost_at_truth_measured": measured,
            "truth_at_least_as_good_as_grid": truth_at_least_as_good,
            "cost_ratio_truth_over_grid": (
                cost_at_truth / scan["cost_min"] if scan["cost_min"] else None
            ),
            "n_unreachable": scan.get("n_unreachable", 0),
        },
        "4_provenance_complete": {
            "ok": provenance_ok,
            "n_records": n_records,
            "n_missing": missing,
        },
        "all_passed": bool(
            same_basin and close_to_truth and scan_ok and provenance_ok
        ),
    }
