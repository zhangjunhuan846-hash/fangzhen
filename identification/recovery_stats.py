"""Recovery statistics shared by the G6 identifiability gates.

WHY THIS IS A MODULE AND NOT A FUNCTION INSIDE EACH SCRIPT
    G6.1b-1 measures the width of the cost-curve valley at a fixed
    tolerance, and G6.1c measures the same quantity for 239 protocol
    windows.  Two copies of that estimator would drift, and the drift
    would be invisible -- both would keep returning plausible numbers.
    The project has already paid for this lesson once (two copies of the
    half-cell option translation, two copies of the capability table).

WHAT THE BAND WIDTH IS
    ``band_width`` returns the width, in dex of the scanned parameter, of
    the set {J <= level} around the argmin, where J is the mean squared
    MODEL-TO-MODEL voltage difference.  It answers a question that a
    residual or a fitted value cannot:

        how far can this parameter move before the trajectory notices?

    Two rules are baked in because both were learned the hard way:
      * the crossing is interpolated between two MEASURED points, and the
        gap between them is returned as the resolution actually achieved.
        A reading sharper than its own grid is not a reading.
      * the minimum itself is never interpolated.  ``a_hat`` must be a
        point that was evaluated (G5.0: interpolating near a sharp
        minimum inflated the cost by four orders of magnitude).
      * a band that reaches the edge of the scanned range is reported as
        TRUNCATED.  In G6.1b-1 two of six bands were still rising at the
        edge, so the printed widths there are lower bounds, not
        measurements -- and reporting them without the flag would convert
        a one-sided result into an apparently two-sided one.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import numpy as np

#: Step and extent of the map's probe grid, in dex of the multiplier.
#: Tied to the comparison being made: bands are judged against a 0.30 dex
#: limit, so the grid has to resolve well below that.
PROBE_STEP_DEX = 0.05
PROBE_MAX_DEX = 1.0


def probe_grid(step: float = PROBE_STEP_DEX,
               a_max: float = PROBE_MAX_DEX) -> np.ndarray:
    """The symmetric uniform grid ``-a_max ... 0 ... +a_max`` in dex.

    Uniform rather than graded: the map compares band widths across 239
    windows against a fixed limit, so the RESOLUTION has to be the same
    everywhere.  A graded grid would make narrow bands look better
    measured than wide ones for reasons that have nothing to do with the
    physics -- and the resolution is reported per window precisely so that
    this cannot happen unnoticed.
    """
    n = int(round(float(a_max) / float(step)))
    return np.round(np.linspace(-n * float(step), n * float(step), 2 * n + 1), 6)


def band_width(
    grid: np.ndarray,
    cost: np.ndarray,
    a_hat: float,
    level: float,
) -> Dict[str, Any]:
    """Width of the {cost <= level} component containing ``a_hat``.

    ``grid`` and ``cost`` are measured arrays (cost in mV^2 when the cost
    is a mean squared voltage difference).  Non-finite costs are dropped:
    an unreachable run is not a small cost.
    """
    grid = np.asarray(grid, dtype=float)
    cost = np.asarray(cost, dtype=float)
    order = np.argsort(grid)
    g, j = grid[order], cost[order]
    finite = np.isfinite(j)
    g, j = g[finite], j[finite]
    if g.size == 0:
        return {"width_dex": float("nan"), "left_dex": float("nan"),
                "right_dex": float("nan"), "truncated_left": True,
                "truncated_right": True, "truncated": True,
                "resolution_dex": float("nan"), "n_points": 0}

    i_hat = int(np.argmin(np.abs(g - float(a_hat))))
    if not (j[i_hat] <= level):
        return {"width_dex": 0.0, "left_dex": 0.0, "right_dex": 0.0,
                "truncated_left": False, "truncated_right": False,
                "truncated": False, "resolution_dex": float("nan"),
                "n_points": int(g.size)}

    def _cross(i_in: int, i_out: int):
        g0, g1 = float(g[i_in]), float(g[i_out])
        j0, j1 = float(j[i_in]), float(j[i_out])
        if not np.isfinite(j1) or j1 == j0:
            return g1, abs(g1 - g0)
        frac = min(max((level - j0) / (j1 - j0), 0.0), 1.0)
        return g0 + frac * (g1 - g0), abs(g1 - g0)

    # A neighbouring point whose cost is NOT FINITE is a run that did not
    # happen, so where the band ends is unknown there.  The edge is then
    # reported at the last MEASURED in-band point and the side is flagged
    # truncated, which keeps one meaning for the flag: whenever it is set,
    # ``width_dex`` is a LOWER bound on the band, never an estimate of it.
    left, left_res, trunc_l = float(g[0]), float("nan"), True
    for i in range(i_hat, 0, -1):
        if not (j[i - 1] <= level):
            if np.isfinite(j[i - 1]):
                left, left_res = _cross(i, i - 1)
                trunc_l = False
            else:
                left, left_res = float(g[i]), abs(float(g[i - 1] - g[i]))
            break
    right, right_res, trunc_r = float(g[-1]), float("nan"), True
    for i in range(i_hat, g.size - 1):
        if not (j[i + 1] <= level):
            if np.isfinite(j[i + 1]):
                right, right_res = _cross(i, i + 1)
                trunc_r = False
            else:
                right, right_res = float(g[i]), abs(float(g[i + 1] - g[i]))
            break

    res = np.array([left_res, right_res], dtype=float)
    return {
        "left_dex": abs(float(a_hat) - left),
        "right_dex": abs(right - float(a_hat)),
        "width_dex": abs(right - left),
        "truncated_left": bool(trunc_l),
        "truncated_right": bool(trunc_r),
        "truncated": bool(trunc_l or trunc_r),
        "resolution_dex": float(np.nanmax(res)) if np.isfinite(res).any()
        else float("nan"),
        "n_points": int(g.size),
    }


def curvature_stats(
    evaluate: Callable[[float], float],
    a_hat: float,
    h: float,
) -> Dict[str, float]:
    """Measured curvature and one-sidedness at ``a_hat``.

    ``J''`` is a central second difference on MEASURED points, and the
    asymmetry is

        (J(a+h) - J(a-h)) / (J(a+h) + J(a-h))

    which is negative when raising the parameter is CHEAPER than lowering
    it.  In G6.1b-1 that sign came out negative for all six (window,
    truth) pairs, and it is the numeric form of the finding: these
    protocols bound the parameter from one side only.
    """
    j0 = float(evaluate(a_hat))
    jp = float(evaluate(a_hat + h))
    jm = float(evaluate(a_hat - h))
    out = {
        "J_at_a_hat_mV2": j0,
        "J_plus_h_mV2": jp,
        "J_minus_h_mV2": jm,
        "a_hat_dex": float(a_hat),
        "h_dex": float(h),
        "curvature_Jpp_mV2_per_dex2": float("nan"),
        "curvature_asymmetry": float("nan"),
    }
    if np.isfinite(j0) and np.isfinite(jp) and np.isfinite(jm):
        out["curvature_Jpp_mV2_per_dex2"] = float(
            (jp - 2.0 * j0 + jm) / (h ** 2)
        )
        if (jp + jm) > 0:
            out["curvature_asymmetry"] = float((jp - jm) / (jp + jm))
    return out


__all__ = [
    "PROBE_MAX_DEX",
    "PROBE_STEP_DEX",
    "band_width",
    "curvature_stats",
    "probe_grid",
]
