# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B0.6: high-fidelity OCP extraction (v2)
#
# WHAT CHANGES vs v1
#   Only the SAMPLING of the extracted table.  Everything else is
#   deliberately identical:
#     * the input record is the FULL-RESOLUTION trace
#       (extraction.hires_trace -- no global stride), instead of the
#       adapter's decimated `load_raw` output;
#     * SOC definition, Q_ref anchor, branch classification, the
#       hysteresis / hand-over / polarisation bookkeeping and the
#       proxy-OCP warning all come from the SAME v1 code path
#       (`extraction.ocp_extractor.extract_ocp_branches`), so the
#       only difference between v1 and v2 is which samples of the
#       measured curve the table keeps.
#   The v1 outputs are never touched: v2 is written to its own
#   `graphite_ocp_v2/` directory.
#
# WHY THE SAMPLING MATTERS
#   A global stride removes samples uniformly in TIME, so it removes
#   the most samples exactly where the curve is steepest.  The v1
#   lithiation table carried ONE sample above 1.43 V.  v2 replaces
#   that with a BRANCH-AWARE selection:
#
#     1. FIDELITY   vertical-distance Ramer-Douglas-Peucker in the
#                   (SOC, V) plane: keep the minimal sample set whose
#                   piecewise-linear reconstruction (exactly what
#                   PyBaMM's OCP Interpolant does) stays within
#                   EPS_V of the full-resolution curve.  Both branch
#                   endpoints are always kept.
#     2. STEEPNESS  any segment with |dV/dSOC| above STEEP_DV_DSOC
#                   must contain at least MIN_PTS_IN_STEEP raw
#                   samples.  This is what "add sampling where
#                   dV/dSOC is large" means operationally, and it
#                   also protects downstream users of the table that
#                   take a DERIVATIVE of it (e.g. GITT D_s via
#                   dOCP/dSOC), where a 2-point linear stretch would
#                   be meaningless.
#     3. PLATEAU    no segment may span more than MAX_GAP_SOC in SOC,
#                   so a flat region cannot collapse to two points.
#
#   The achieved fidelity is MEASURED afterwards, not assumed: the
#   table's interpolant is compared with every full-resolution
#   sample inside the common SOC range.
#
# This module imports numpy/pandas only -- never pybamm.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from extraction.ocp_extractor import (
    OCP_CSV_FIELDS,
    extract_ocp_branches,
    write_ocp_csvs,
)

# ---- sampling defaults (all overridable, all recorded) ----------
# Fidelity target for the piecewise-linear reconstruction.  Chosen
# from the sweep in scripts/probe_b06_sampling.py: 0.2 mV is one to
# two orders of magnitude below the ~C/50 polarisation carried by this
# pseudo-OCP (14.3 mV) and below the replay residual scale, so the
# table is never the limiting factor -- while the total point count
# (1571) is still about HALF of v1's (3275), because the budget is
# moved from the flat plateau to the steep regions.
EPS_V_MV = 0.2
# ladder used if the fidelity target alone yields more than POINT_CAP
EPS_LADDER_FACTOR = 2.0
# hard cap on points per branch (table size / Interpolant cost)
POINT_CAP = 4000
# |dV/dSOC| above this (V per unit SOC) counts as a steep region.
# Lithiation: ~13.6 V/unit median and 1.96e4 V/unit at the dilute
# stage, plateau ~0.5-1 V/unit -> a threshold of 5 separates them.
STEEP_DV_DSOC_V = 5.0
# In a steep region keep at least this many raw samples (never binds
# the dilute stage: the measurement itself carries only 5 samples
# above 1.43 V, and v2 keeps all 5 -- v1 kept 1).
MIN_PTS_IN_STEEP = 12
# no kept segment may span more than this in SOC (plateau safety net)
MAX_GAP_SOC = 0.005

# SOC bands used by the reporting
SOC_BANDS: List[Tuple[str, float, float]] = [
    ("0.000-0.01", 0.0, 0.01),
    ("0.010-0.10", 0.01, 0.10),
    ("0.100-0.50", 0.10, 0.50),
    ("0.500-1.00", 0.50, 1.00),
]


# ------------------------------------------------------------------
# 1. branch-aware resampling
# ------------------------------------------------------------------
def _vertical_rdp(x: np.ndarray, y: np.ndarray, eps: float) -> np.ndarray:
    """
    Ramer-Douglas-Peucker with the error measured VERTICALLY (in y),
    which is the error the model actually sees: the OCP is a function
    of SOC, interpolated linearly in y.

    For a near-vertical stretch a vertical criterion is the strict
    one: a chord across it cannot follow the drop, so the samples are
    kept.  Endpoints are always kept.
    """
    n = len(x)
    if n <= 2:
        return np.arange(n, dtype=int)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack: List[Tuple[int, int]] = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        dx = x[j] - x[i]
        seg = slice(i + 1, j)
        if dx != 0.0:
            y_line = y[i] + (y[j] - y[i]) * (x[seg] - x[i]) / dx
        else:
            y_line = np.full(j - i - 1, 0.5 * (y[i] + y[j]))
        err = np.abs(y[seg] - y_line)
        k = int(np.argmax(err))
        if err[k] > eps:
            idx = i + 1 + k
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return np.nonzero(keep)[0]


def _insert_evenly(idx: np.ndarray, n_wanted: int) -> np.ndarray:
    """Pick ``n_wanted`` positions out of ``idx`` (endpoints included)."""
    if len(idx) <= n_wanted:
        return idx
    return idx[np.unique(np.linspace(0, len(idx) - 1, n_wanted,
                                    dtype=int))]


def _fill_max_gap(soc: np.ndarray, keep: np.ndarray,
                  max_gap: float) -> np.ndarray:
    """Insert raw samples so no kept segment spans more than ``max_gap``."""
    out = [int(keep[0])]
    for j in keep[1:]:
        cur = out[-1]
        while soc[j] - soc[cur] > max_gap:
            nxt = int(np.searchsorted(soc, soc[cur] + max_gap, side="right"))
            nxt = min(max(nxt - 1, cur + 1), j)
            if nxt <= cur:
                break
            out.append(nxt)
            cur = nxt
        out.append(int(j))
    return np.array(sorted(set(out)), dtype=int)


def resample_branch(
    soc: np.ndarray,
    voltage: np.ndarray,
    *,
    eps_mV: float = EPS_V_MV,
    max_gap_soc: float = MAX_GAP_SOC,
    steep_v_per_soc: float = STEEP_DV_DSOC_V,
    min_pts_in_steep: int = MIN_PTS_IN_STEEP,
    point_cap: int = POINT_CAP,
) -> Tuple[np.ndarray, Dict[str, object]]:
    """
    Branch-aware sample selection.

    Returns (indices, diagnostics).  ``indices`` indexes the input
    arrays (which must be sorted by ascending SOC) and always
    contains the first and last sample.

    ``point_cap`` bounds the FIDELITY stage only (it drives the eps
    ladder); the steepness floor and the gap cap are explicit
    requirements and may add points above it.  On the SINTEF p-OCV
    data the floor adds ~40 % on top of the RDP set, so the cap is
    never a practical constraint (final sizes: 933 / 638 points).
    """
    soc = np.asarray(soc, dtype=float)
    voltage = np.asarray(voltage, dtype=float)
    if len(soc) < 3:
        raise ValueError("resample_branch needs at least 3 samples")
    if np.any(np.diff(soc) <= 0):
        raise ValueError("SOC must be strictly increasing")

    # ---- 1. fidelity (with a point cap via the eps ladder) -------
    eps = eps_mV / 1000.0
    ladder = []
    for _ in range(24):
        keep = _vertical_rdp(soc, voltage, eps)
        ladder.append({"eps_mV": eps * 1000.0, "n_kept": int(len(keep))})
        if len(keep) <= point_cap:
            break
        eps *= EPS_LADDER_FACTOR

    # ---- 2. steepness floor -------------------------------------
    keep_list = list(keep)
    for a, b in zip(keep_list[:-1], keep_list[1:]):
        if b - a <= 1:
            continue
        d_soc = soc[b] - soc[a]
        if d_soc <= 0:
            continue
        dv_dsoc = abs(voltage[b] - voltage[a]) / d_soc
        if dv_dsoc > steep_v_per_soc:
            wanted = _insert_evenly(np.arange(a, b + 1), min_pts_in_steep)
            keep_list.extend(int(k) for k in wanted)
    keep = np.array(sorted(set(keep_list)), dtype=int)

    # ---- 3. plateau gap cap -------------------------------------
    keep = _fill_max_gap(soc, keep, max_gap_soc)

    # ---- measure the achieved fidelity --------------------------
    v_interp = np.interp(soc, soc[keep], voltage[keep])
    err_mV = np.abs(v_interp - voltage) * 1000.0

    def _band_err(lo: float, hi: float) -> Dict[str, float]:
        sel = (soc >= lo) & (soc <= hi)
        if not sel.any():
            return {"n": 0, "max_mV": float("nan"), "mean_mV": float("nan")}
        return {
            "n": int(sel.sum()),
            "max_mV": float(err_mV[sel].max()),
            "mean_mV": float(err_mV[sel].mean()),
        }

    d_soc = np.diff(soc[keep])
    d_v = np.diff(voltage[keep])
    dv_dsoc = np.abs(d_v) / np.where(d_soc > 0, d_soc, np.nan)

    diagnostics = {
        "method": (
            "vertical-distance RDP in the (SOC, V) plane + steepness "
            "floor + no-gap-greater-than-max_gap_soc"
        ),
        "parameters": {
            "eps_mV_requested": float(eps_mV),
            "point_cap": int(point_cap),
            "steep_dv_dsoc_v_per_soc": float(steep_v_per_soc),
            "min_pts_in_steep": int(min_pts_in_steep),
            "max_gap_soc": float(max_gap_soc),
        },
        "eps_ladder": ladder,
        "eps_mV_used": float(ladder[-1]["eps_mV"]),
        "n_in": int(len(soc)),
        "n_out": int(len(keep)),
        "endpoints_kept": bool(keep[0] == 0 and keep[-1] == len(soc) - 1),
        "soc_span": [float(soc[keep][0]), float(soc[keep][-1])],
        "min_soc_step": float(d_soc.min()) if len(d_soc) else float("nan"),
        "median_soc_step": float(np.median(d_soc)) if len(d_soc) else float("nan"),
        "max_dv_dsoc_v_per_soc": float(np.nanmax(dv_dsoc)),
        "median_dv_dsoc_v_per_soc": float(np.nanmedian(dv_dsoc)),
        "achieved_vertical_error_mV": {
            "max": float(err_mV.max()),
            "mean": float(err_mV.mean()),
            "p95": float(np.percentile(err_mV, 95)),
            "by_soc_band": {name: _band_err(lo, hi)
                            for name, lo, hi in SOC_BANDS},
        },
    }
    return keep, diagnostics


def resample_frame(frame: pd.DataFrame, **kwargs) -> Tuple[pd.DataFrame,
                                                          Dict[str, object]]:
    """Resample one extracted branch table produced by the v1 extractor."""
    srt = frame.sort_values("SOC", kind="stable").reset_index(drop=True)
    keep, diag = resample_branch(
        srt["SOC"].to_numpy(float), srt["Voltage"].to_numpy(float), **kwargs
    )
    out = srt.iloc[keep].reset_index(drop=True)
    return out[OCP_CSV_FIELDS], diag


# ------------------------------------------------------------------
# 2. extraction (v1 core + new sampling)
# ------------------------------------------------------------------
def extract_ocp_v2(
    adapter,
    cell: str,
    rate: str,
    *,
    cycle: int = 1,
    **sampling,
) -> Dict[str, object]:
    """
    Full-resolution trace -> v1 extraction core -> branch-aware sampling.

    Returns the same shape as ``extract_ocp_branches`` plus a
    ``sampling`` block and the trace provenance.
    """
    from extraction.hires_trace import load_hires_trace

    trace = load_hires_trace(adapter, cell, rate)
    full = extract_ocp_branches(trace, cycle=cycle)

    lith, lith_diag = resample_frame(full["lithiation"], **sampling)
    deli, deli_diag = resample_frame(full["delithiation"], **sampling)

    provenance = dict(full["provenance"])
    provenance["extraction"] = (
        "extraction/ocp_extractor_v2.py::extract_ocp_v2 (v1 core + "
        "branch-aware sampling)"
    )
    provenance["input_trace"] = trace.attrs["provenance"]
    provenance["n_points_full_resolution"] = {
        "lithiation": int(len(full["lithiation"])),
        "delithiation": int(len(full["delithiation"])),
    }
    provenance["n_points"] = {
        "lithiation": int(len(lith)),
        "delithiation": int(len(deli)),
    }
    provenance["resampling"] = {
        "lithiation": lith_diag,
        "delithiation": deli_diag,
    }
    provenance["scope"] = (
        f"{rate} cycle {cycle}, both branches, full-resolution input, "
        f"canonical sign"
    )
    provenance["wording"] = (
        provenance.get("wording", "") +
        "; sampling re-derived from the full-resolution trace -- the OCP "
        "definition is unchanged from v1"
    ).strip("; ")
    return {"lithiation": lith, "delithiation": deli,
            "provenance": provenance, "trace": trace,
            "full_resolution": full}


def write_ocp_v2(
    result: Dict[str, object],
    phase_dir: Path | str,
    *,
    extra_provenance: Optional[dict] = None,
) -> Dict[str, Path]:
    """
    Write the v2 tables into ``<phase_dir>/graphite_ocp_v2/`` with the
    SAME file names as v1, so ``parameters.sintef_graphite_ocp
    .load_ocp_tables(dir)`` can read them unchanged.
    """
    trace_prov = dict(result["provenance"])["input_trace"]  # type: ignore
    out = Path(phase_dir) / "graphite_ocp_v2"
    paths = write_ocp_csvs(
        result,
        out,
        source_file=str(trace_prov.get("source_file", "")),
        source_sha256=str(trace_prov.get("source_sha256", "")),
        temperature_source=(
            "declared_room_temperature_not_measured"
            if trace_prov.get("ambient_temperature_C") == 25.0
            else "declared_dataset_temperature"
        ),
        extra_provenance={
            "phase": "B0.6 high-fidelity OCP extraction",
            "no_decimation": True,
            "supersedes": (
                "v1 (outputs/analysis/graphite_phaseB0) - kept untouched"
            ),
            **(extra_provenance or {}),
        },
    )
    return paths


# ------------------------------------------------------------------
# 3. table comparison metrics (v1 vs v2)
# ------------------------------------------------------------------
def table_stats(frame: pd.DataFrame) -> Dict[str, object]:
    """Density and slope statistics of one OCP table."""
    srt = frame.sort_values("SOC", kind="stable").reset_index(drop=True)
    soc = srt["SOC"].to_numpy(float)
    v = srt["Voltage"].to_numpy(float)
    d_soc = np.diff(soc)
    d_v = np.diff(v)
    dv_dsoc = np.abs(d_v) / np.where(d_soc > 0, d_soc, np.nan)

    bands: Dict[str, dict] = {}
    for name, lo, hi in SOC_BANDS:
        sel = (soc >= lo) & (soc <= hi)
        n = int(sel.sum())
        width = hi - lo
        inner = np.zeros_like(sel)
        inner[1:] = sel[1:] & sel[:-1]
        bands[name] = {
            "n_points": n,
            "points_per_0p01_soc": float(n / (width / 0.01)) if width else float("nan"),
            "min_soc_step": float(d_soc[inner[1:]].min())
            if inner[1:].any() else float("nan"),
            "max_dv_dsoc_v_per_soc": float(np.nanmax(dv_dsoc[inner[1:]]))
            if inner[1:].any() else float("nan"),
        }

    return {
        "n_points": int(len(srt)),
        "soc_range": [float(soc[0]), float(soc[-1])],
        "voltage_range_V": [float(v.min()), float(v.max())],
        "min_soc_step": float(d_soc.min()),
        "median_soc_step": float(np.median(d_soc)),
        "max_dv_dsoc_v_per_soc": float(np.nanmax(dv_dsoc)),
        "median_dv_dsoc_v_per_soc": float(np.nanmedian(dv_dsoc)),
        "bands": bands,
    }


def interpolant_deviation(
    a: pd.DataFrame,
    b: pd.DataFrame,
    *,
    band: Optional[Tuple[float, float]] = None,
    n_grid: int = 4000,
    at_soc: Optional[Sequence[float]] = None,
) -> Dict[str, object]:
    """
    |V_a(SOC) - V_b(SOC)| on a dense grid over the COMMON SOC range
    (linear interpolation on both, i.e. exactly how PyBaMM reads them).
    """
    sa = a.sort_values("SOC", kind="stable")
    sb = b.sort_values("SOC", kind="stable")
    lo = max(float(sa["SOC"].min()), float(sb["SOC"].min()))
    hi = min(float(sa["SOC"].max()), float(sb["SOC"].max()))
    if band is not None:
        lo = max(lo, band[0])
        hi = min(hi, band[1])
    if hi <= lo:
        raise ValueError("no overlapping SOC range")

    grid = (np.asarray(at_soc, float) if at_soc is not None
            else np.linspace(lo, hi, n_grid))
    grid = np.clip(grid, lo, hi)
    va = np.interp(grid, sa["SOC"].to_numpy(float),
                   sa["Voltage"].to_numpy(float))
    vb = np.interp(grid, sb["SOC"].to_numpy(float),
                   sb["Voltage"].to_numpy(float))
    d_mV = np.abs(va - vb) * 1000.0
    return {
        "soc_range": [float(lo), float(hi)],
        "n_grid": int(len(grid)),
        "max_abs_mV": float(d_mV.max()),
        "mean_abs_mV": float(d_mV.mean()),
        "p95_abs_mV": float(np.percentile(d_mV, 95)),
        "signed_max_abs_mV": float(np.max(np.abs(va - vb)) * 1000.0),
        "soc_at_max": float(grid[int(np.argmax(d_mV))]),
    }


def _band_deviation(a: pd.DataFrame, b: pd.DataFrame,
                     band: Tuple[float, float]) -> Dict[str, object]:
    """
    Band deviation, tolerant of a band that lies outside the common SOC
    range (e.g. SOC 0-0.01 for the delithiation branch, which starts at
    ~0.08).  A non-overlapping band is NOT an error: it is recorded.
    """
    lo_band, hi_band = band
    lo = max(lo_band, float(a["SOC"].min()), float(b["SOC"].min()))
    hi = min(hi_band, float(a["SOC"].max()), float(b["SOC"].max()))
    if hi <= lo:
        return {
            "soc_range": None,
            "n_grid": 0,
            "max_abs_mV": float("nan"),
            "mean_abs_mV": float("nan"),
            "p95_abs_mV": float("nan"),
            "signed_max_abs_mV": float("nan"),
            "soc_at_max": float("nan"),
            "note": "band lies outside the common SOC range of the two tables",
        }
    return interpolant_deviation(a, b, band=band)


def compare_tables(
    v1_lith: pd.DataFrame, v1_deli: pd.DataFrame,
    v2_lith: pd.DataFrame, v2_deli: pd.DataFrame,
    v2_provenance: dict,
    *,
    reference_lith: Optional[pd.DataFrame] = None,
    reference_deli: Optional[pd.DataFrame] = None,
) -> Dict[str, object]:
    """
    Full v1-vs-v2 diagnostic payload (the Phase B0.6 deliverable).

    ``reference_*`` are the FULL-RESOLUTION extracted branches.  When
    given, each table's own deviation from the measured curve is
    reported too -- that is the decisive fidelity number, because a
    table can be large and still wrong (v1) or small and accurate
    (v2's plateau).
    """
    out: Dict[str, object] = {
        "definition_unchanged": {
            "soc_definition": v2_provenance.get("soc_definition"),
            "soc_reference_charge_Ah": v2_provenance.get(
                "soc_reference_charge_Ah"
            ),
            "n_points_full_resolution": v2_provenance.get(
                "n_points_full_resolution"
            ),
        },
        "sampling": v2_provenance.get("resampling"),
        "branches": {},
    }
    refs = {"lithiation": reference_lith, "delithiation": reference_deli}
    for name, a, b in (("lithiation", v1_lith, v2_lith),
                       ("delithiation", v1_deli, v2_deli)):
        block: Dict[str, object] = {
            "v1": table_stats(a),
            "v2": table_stats(b),
            "deviation_v1_minus_v2_mV": {
                "full_overlap": interpolant_deviation(a, b),
                "by_soc_band": {
                    band_name: _band_deviation(a, b, (lo, hi))
                    for band_name, lo, hi in SOC_BANDS
                },
                "at_v1_knots": interpolant_deviation(
                    a, b, at_soc=a.sort_values("SOC")["SOC"].to_numpy(float)
                ),
                "soc_0_to_0p1_dense": interpolant_deviation(
                    a, b, band=(0.0, 0.1), n_grid=4000
                ),
            },
        }
        ref = refs.get(name)
        if ref is not None:
            block["fidelity_vs_measured_mV"] = {
                "v1": {
                    "full_overlap": interpolant_deviation(a, ref),
                    "by_soc_band": {
                        band_name: _band_deviation(a, ref, (lo, hi))
                        for band_name, lo, hi in SOC_BANDS
                    },
                },
                "v2": {
                    "full_overlap": interpolant_deviation(b, ref),
                    "by_soc_band": {
                        band_name: _band_deviation(b, ref, (lo, hi))
                        for band_name, lo, hi in SOC_BANDS
                    },
                },
            }
        na = block["v1"]["n_points"]  # type: ignore[index]
        nb = block["v2"]["n_points"]  # type: ignore[index]
        block["point_density_ratio_v2_over_v1"] = (
            float(nb / na) if na else float("nan")
        )
        out["branches"][name] = block

    lith = out["branches"]["lithiation"]  # type: ignore[index]
    fidelity = lith.get("fidelity_vs_measured_mV", {})
    out["headline"] = {
        "lithiation_n_points_v1": lith["v1"]["n_points"],
        "lithiation_n_points_v2": lith["v2"]["n_points"],
        "lithiation_n_points_above_1p43V_v1": int(
            (v1_lith["Voltage"] > 1.4325).sum()
        ),
        "lithiation_n_points_above_1p43V_v2": int(
            (v2_lith["Voltage"] > 1.4325).sum()
        ),
        "lithiation_max_deviation_v1_minus_v2_mV": (
            lith["deviation_v1_minus_v2_mV"]["full_overlap"]["max_abs_mV"]
        ),
        "lithiation_max_deviation_v1_minus_v2_soc_0_to_0p1_mV": (
            lith["deviation_v1_minus_v2_mV"]["soc_0_to_0p1_dense"]
            ["max_abs_mV"]
        ),
    }
    if fidelity:
        out["headline"]["lithiation_fidelity_v1_vs_measured_mV"] = (
            fidelity["v1"]["full_overlap"]["max_abs_mV"]
        )
        out["headline"]["lithiation_fidelity_v2_vs_measured_mV"] = (
            fidelity["v2"]["full_overlap"]["max_abs_mV"]
        )
    return out


def write_comparison(report: dict, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return out
