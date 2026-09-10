# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B2: constant-diffusivity SWEEP sets (sensitivity device)
#
# WHAT THIS MODULE IS
#   A sweep of PRESCRIBED constant diffusivities D = 1e-17 ... 1e-13
#   m2/s laid over the frozen graphite parameter set
#
#       Ecker2015 reference
#     + SINTEF measured geometry            (Phase A.5)
#     + SINTEF measured OCP, v2 tables       (Phase B0.6, frozen)
#     + SINTEF capacity-matched eps_am       (Phase B0.5)
#     + D held CONSTANT at a grid value      (this module)
#
# WHAT THIS MODULE IS NOT
#   It does NOT read, interpolate, modify or re-derive the GITT
#   apparent D_s(SOC) table of Phase B1, and it does NOT fit anything.
#   The grid values are chosen a priori on a log grid and are used to
#   MEASURE how sensitive the model's voltage is to the diffusivity at
#   different rates.  Nothing here is a diffusivity estimate, and no
#   value produced here is proposed as one.
#
# WHY A CONSTANT D AND NOT THE MEASURED D(SOC) CURVE
#   A sensitivity scan must vary ONE thing.  Holding D(SOC) at a
#   constant removes the shape of the extracted curve as a confounder,
#   so the resulting voltage spread can be attributed to the magnitude
#   of D alone.  The measured (SOC-dependent) curve is compared against
#   this scan in the Phase B2 report, not mixed into it.
#
# THE DIAGNOSTIC THE SWEEP IS BUILT AROUND
#   The diffusivity only matters when the protocol is short compared
#   with the particle diffusion time
#
#       tau_d = R^2 / D                     [s]
#       Fo    = t_protocol / tau_d = D t / R^2     (Fourier number)
#
#   Fo >> 1 : the particle stays equilibrated, the surface sees the
#             average stoichiometry, V(t) is insensitive to D;
#   Fo << 1 : the surface is diffusion-starved, V(t) is controlled by D.
#
#   Fo is recorded for every (D, protocol) pair so the empirical
#   voltage sensitivity can be read against a dimensionless group.
#
# This module imports pybamm lazily.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from parameters.sintef_graphite_capacity import (
    CAPACITY_MATCHED_IDS,
    build_capacity_matched_pair,
)
from parameters.sintef_graphite_geometry import DEFAULT_CELL
from parameters.sintef_graphite_ocp import DEFAULT_OCP_DIR

ROOT = Path(__file__).resolve().parents[1]

KEY_DIFFUSIVITY = "Positive particle diffusivity [m2.s-1]"
KEY_RADIUS = "Positive particle radius [m]"

# a priori log grid, 4 decades, 3 points per decade
DEFAULT_SWEEP_M2_S: Tuple[float, ...] = (
    1e-17, 3e-17, 1e-16, 3e-16, 1e-15, 3e-15, 1e-14, 3e-14, 1e-13,
)

#
# The id MUST carry the branch.  The lithiation and delithiation sets
# differ in their OCP table, and the OCP is only valid on its own
# branch: a branch-less id means the second branch registered silently
# overwrites the first, and the lithium window then runs on the
# delithiation OCP (which extrapolates to ~4.5 V outside its table and
# trips the Maximum-voltage event at t=0).  That failure was observed;
# ``register_constant_d_sweep`` now also refuses duplicate ids.
SET_ID_TEMPLATE = "sintef_graphite_Dsweep_{branch}_{tag}"
BRANCH_TOKEN = {"lithiation": "lith", "delithiation": "deli"}
SWEEP_GRADE = "prescribed_constant_D_sensitivity_grid_not_an_estimate"


def branch_token(branch: str) -> str:
    """Short, stable branch token used in set ids."""
    key = str(branch)
    if key not in BRANCH_TOKEN:
        raise ValueError(
            f"unknown branch '{branch}' (expected one of "
            f"{sorted(BRANCH_TOKEN)})"
        )
    return BRANCH_TOKEN[key]


# printed magnitude notation for set ids: 1e-13 -> "1e-13"
def d_tag(d_m2_s: float) -> str:
    """Stable id token for a grid value, e.g. 1e-13 -> '1e-13'."""
    d = float(d_m2_s)
    if d <= 0:
        raise ValueError("diffusivity must be positive")
    exp = int(np.floor(np.log10(d)))
    mant = d / 10.0 ** exp
    mant_txt = f"{mant:.0f}" if abs(mant - round(mant)) < 1e-9 \
        else f"{mant:g}"
    return f"{mant_txt}e{exp}"


def constant_d_set_id(branch: str, d_m2_s: float) -> str:
    """Branch-qualified id: lithiation and delithiation never collide."""
    return SET_ID_TEMPLATE.format(branch=branch_token(branch),
                                  tag=d_tag(d_m2_s))


def tau_d_s(d_m2_s: float, radius_m: float) -> float:
    """Particle diffusion time constant R^2/D [s]."""
    return float(radius_m) ** 2 / float(d_m2_s)


def fourier_number(
    d_m2_s: float, radius_m: float, duration_s: float,
) -> float:
    """Dimensionless D t / R^2 for a protocol of ``duration_s``."""
    return float(d_m2_s) * float(duration_s) / float(radius_m) ** 2


def sweep_provenance(
    d_m2_s: float,
    radius_m: float,
    *,
    radius_source: str = "",
    protocols: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Audit record for one grid value: where the number came from (a
    prescribed grid, nothing else) plus the dimensionless groups that
    decide whether the diffusivity can matter at all.
    """
    tau = tau_d_s(d_m2_s, radius_m)
    rec: Dict[str, object] = {
        "prescribed_D_m2_s": float(d_m2_s),
        "prescribed_D_cm2_s": float(d_m2_s) * 1e4,
        "origin": (
            "PRESCRIBED grid value from a priori log grid "
            "1e-17..1e-13 m2/s; NOT extracted, NOT fitted, NOT an "
            "estimate of this material's diffusivity"
        ),
        "particle_radius_m": float(radius_m),
        "particle_radius_source": radius_source,
        "tau_d_s": tau,
        "tau_d_h": tau / 3600.0,
        "fo_note": (
            "Fo = D t / R^2 = t_protocol / tau_d; recorded per protocol "
            "so the voltage sensitivity can be read against a "
            "dimensionless group rather than against a rate label"
        ),
    }
    if protocols:
        rec["protocols"] = {
            name: {
                "duration_s": float(dur),
                "Fo": fourier_number(d_m2_s, radius_m, float(dur)),
                "equilibrated": bool(
                    fourier_number(d_m2_s, radius_m, float(dur)) > 1.0
                ),
            }
            for name, dur in protocols.items()
        }
    return rec


def build_constant_d_variant(
    branch: str = "lithiation",
    d_m2_s: float = 1e-15,
    cell: str = DEFAULT_CELL,
    *,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
):
    """
    ``(reference, pv, info)`` for one grid value.

    ``pv`` is the frozen capacity-matched set with exactly one key
    replaced: a CONSTANT diffusivity.  ``reference`` is the same set
    with its native diffusivity, so
    ``changed_keys_against(reference, pv) == [KEY_DIFFUSIVITY]`` -- every
    other entry is carried over object-identically (the tests assert
    this key by key).
    """
    import pybamm

    d = float(d_m2_s)
    if not np.isfinite(d) or d <= 0:
        raise ValueError(f"diffusivity must be finite and positive (got {d})")

    base, pv = build_capacity_matched_pair(
        branch, cell, ocp_dir, metadata_csv,
        set_id_suffix=set_id_suffix,
    )
    if KEY_DIFFUSIVITY not in pv:
        raise KeyError(
            f"parameter set has no '{KEY_DIFFUSIVITY}' key; refusing to "
            f"add a parameter the model does not expect"
        )
    # the reference this lattice is measured against is the SAME set with
    # its native (SOC-dependent) diffusivity, so ``changed_keys_against``
    # against it returns exactly [KEY_DIFFUSIVITY]
    reference = pybamm.ParameterValues(dict(pv))
    pv[KEY_DIFFUSIVITY] = pybamm.Scalar(d)
    radius = float(pv[KEY_RADIUS])
    return reference, pv, {
        "d_m2_s": d,
        "radius_m": radius,
        "set_id": constant_d_set_id(branch, d) + set_id_suffix,
        "base_set_id": CAPACITY_MATCHED_IDS[branch] + set_id_suffix,
        "branch": branch,
    }


def register_constant_d_sweep(
    cell: str = DEFAULT_CELL,
    *,
    values: Optional[Iterable[float]] = None,
    branches: Tuple[str, ...] = ("lithiation", "delithiation"),
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
    sweep_root: Optional[str] = None,
) -> Dict[Tuple[str, float], str]:
    """
    Register the whole (branch, D) lattice in THIS process and return
    {(branch, D): set_id}.  Registration uses the same read-through view
    over ``pybamm.parameter_sets`` as Phases A.5 / B0 / B1 -- no repo
    file is touched and nothing is written to disk.
    """
    import pybamm

    from parameters.sintef_graphite_geometry import _ParameterSetsWithExtra

    vals: List[float] = list(values or DEFAULT_SWEEP_M2_S)
    extra: Dict[str, dict] = {}
    out: Dict[Tuple[str, float], str] = {}
    for branch in branches:
        for d in vals:
            _base, pv, info = build_constant_d_variant(
                branch, d, cell,
                ocp_dir=ocp_dir, metadata_csv=metadata_csv,
                set_id_suffix=set_id_suffix,
            )
            sid = str(info["set_id"])
            if sid in extra or sid in out.values():
                raise ValueError(
                    f"duplicate sweep set id '{sid}' for "
                    f"(branch={branch}, D={d:g}); ids must be unique across "
                    f"the whole (branch, D) lattice"
                )
            extra[sid] = dict(pv)
            out[(branch, float(d))] = sid

    current = pybamm.parameter_sets
    if isinstance(current, _ParameterSetsWithExtra):
        current._extra.update(extra)
    else:
        pybamm.parameter_sets = _ParameterSetsWithExtra(current, extra)

    if sweep_root:
        write_sweep_manifest(
            sweep_root, cell=cell, values=vals, branches=branches,
            ocp_dir=ocp_dir, metadata_csv=metadata_csv,
            set_id_suffix=set_id_suffix,
        )
    return out


def write_sweep_manifest(
    out_dir: Path | str,
    *,
    cell: str = DEFAULT_CELL,
    values: Optional[Iterable[float]] = None,
    branches: Tuple[str, ...] = ("lithiation", "delithiation"),
    protocols: Optional[Dict[str, float]] = None,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
) -> Path:
    """
    The traceability deliverable: every grid value with its set id, its
    origin, its tau_d and its Fourier number per protocol.
    """
    vals = list(values or DEFAULT_SWEEP_M2_S)
    # the radius actually used by the model, read from the frozen set
    _base, pv, _info = build_constant_d_variant(
        branches[0], vals[0], cell,
        ocp_dir=ocp_dir, metadata_csv=metadata_csv,
        set_id_suffix=set_id_suffix,
    )
    radius = float(pv[KEY_RADIUS])
    payload = {
        "cell": cell,
        "branches": list(branches),
        "grade": SWEEP_GRADE,
        "what_this_is": (
            "constant-D sensitivity lattice: the frozen graphite set with "
            "the diffusivity key replaced by a prescribed constant"
        ),
        "what_this_is_not": (
            "not a diffusivity estimate, not fitted, and it does not read "
            "or modify the Phase B1 GITT apparent D_s(SOC) table"
        ),
        "diffusivity_key": KEY_DIFFUSIVITY,
        "radius_key": KEY_RADIUS,
        "particle_radius_m": radius,
        "grid_m2_s": [float(v) for v in vals],
        "grid_note": "a priori log grid, 4 decades, 3 values per decade",
        "entries": [
            {
                "branch": b,
                "set_id": constant_d_set_id(b, v) + set_id_suffix,
                "base_set_id": CAPACITY_MATCHED_IDS[b] + set_id_suffix,
                **sweep_provenance(v, radius, protocols=protocols),
            }
            for b in branches
            for v in vals
        ],
        "wording": (
            "the spread of V(t) across this lattice measures the model's "
            "SENSITIVITY to solid diffusivity at a given protocol; it is "
            "not a measurement of D"
        ),
    }
    d = Path(out_dir)
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    path = d / "ds_sweep_manifest.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path
