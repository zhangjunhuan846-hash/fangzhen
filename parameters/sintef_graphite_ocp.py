# ============================================================
# Phase B0 (graphite line): derived parameter sets with the
# EXPERIMENT-DERIVED graphite OCP
#
# Base            : Ecker2015_graphite_halfcell (published reference)
# Geometry        : SINTEF measurement (parameters.sintef_graphite_geometry,
#                   Phase A.5) - area / thickness / eps_am / capacity ONLY
# OCP             : replaced by the extracted SINTEF p-OCV branch table
# Diffusivity     : UNCHANGED (no GITT in this phase)
# Kinetics        : UNCHANGED
#
# Variants (each is a runtime parameter-set id):
#   sintef_graphite_ocp_lith_v1   OCP = lithiation branch table
#   sintef_graphite_ocp_deli_v1   OCP = delithiation branch table
#   sintef_graphite_ocp_mean_v1   OCP = 0.5 * (lith + deli) on the
#                                 overlapping SOC grid (hysteresis split)
#
# The ORIGINAL parameter sets are never modified: each variant is a
# fresh dict derived from the reference set and registered through a
# read-through view over pybamm.parameter_sets (see
# sintef_graphite_geometry.register).
#
# EXTRAPOLATION: pybamm's linear Interpolant extrapolates linearly
# outside the tabulated range.  The lithiation table covers SOC
# 0..1; the delithiation table covers ~0.08..1, so below its lower
# edge the OCP is extrapolated - recorded in `extrapolation` of the
# variant summary, and the delithiation variant is only used for the
# delithiation window (where SOC stays inside the table).
#
# This module imports pybamm lazily (inside functions) so it stays
# importable for provenance/bookkeeping without a solver environment.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from parameters.sintef_graphite_geometry import (
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    geometry_override,
    read_structure,
    derive_geometry,
)

ROOT = Path(__file__).resolve().parents[1]

KEY_OCP = "Positive electrode OCP [V]"
KEY_LOWER_V = "Lower voltage cut-off [V]"
KEY_UPPER_V = "Upper voltage cut-off [V]"

# Voltage window of the SINTEF p-OCV programme: 0.01 V to 1.0 V, with the
# fresh cell sitting at ~3.0 V.  The published reference set carries
# Ecker's OWN window (0 - 1.5 V); those bounds must be replaced by the
# measured ones or the model trips the "Maximum voltage" event at t=0
# (audited: SolverError 'Events [Maximum voltage [V]] are non-positive at
# initial conditions').  Cut-offs are experimental-protocol settings, so
# taking them from the dataset is consistent with keeping the physics
# from the reference set.
MEASURED_LOWER_CUTOFF_V = 0.005
MEASURED_UPPER_CUTOFF_V = 3.2

OCP_LITH_ID = "sintef_graphite_ocp_lith_v1"
OCP_DELI_ID = "sintef_graphite_ocp_deli_v1"
OCP_MEAN_ID = "sintef_graphite_ocp_mean_v1"

# parameters deliberately NOT touched in this phase
KEPT_UNCHANGED_PHASE_B0 = [
    "Positive particle diffusivity [m2.s-1]",          # needs GITT (Phase B1)
    "Positive electrode exchange-current density [A.m-2]",
    "Maximum concentration in positive electrode [mol.m-3]",
    "Positive electrode porosity",
    "Positive particle radius [m]",
]

DEFAULT_OCP_DIR = "outputs/analysis/graphite_phaseB0"


def load_ocp_tables(
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
) -> Dict[str, pd.DataFrame]:
    """Load the two extracted branch tables (Phase B0 outputs)."""
    d = Path(ocp_dir)
    if not d.is_absolute():
        d = ROOT / d
    out: Dict[str, pd.DataFrame] = {}
    for key, name in (("lithiation", "graphite_ocp_lithiation.csv"),
                      ("delithiation", "graphite_ocp_delithiation.csv")):
        path = d / name
        if not path.is_file():
            raise FileNotFoundError(
                f"OCP table not found: {path} "
                f"(run extraction.ocp_extractor first)"
            )
        df = pd.read_csv(path)
        for col in ("SOC", "Voltage", "branch"):
            if col not in df.columns:
                raise ValueError(f"{path.name}: missing column '{col}'")
        df = df.sort_values("SOC", kind="stable").reset_index(drop=True)
        out[key] = df
    return out


def _ocp_function(soc: np.ndarray, voltage: np.ndarray):
    """
    Build a pybamm OCP callable for a (SOC, V) table.

    Mirrors the reference parameter sets' own pattern:
    ``def ocp(sto): return pybamm.Interpolant(x, y, sto)``
    so the value is a proper pybamm expression, not a numpy array.
    """
    import pybamm

    soc = np.asarray(soc, dtype=float)
    voltage = np.asarray(voltage, dtype=float)
    order = np.argsort(soc, kind="stable")
    soc, voltage = soc[order], voltage[order]
    # strictly increasing x is required by the interpolant
    keep = np.concatenate(([True], np.diff(soc) > 0))
    soc, voltage = soc[keep], voltage[keep]
    if len(soc) < 5:
        raise ValueError("OCP table needs at least 5 distinct SOC points")

    def ocp(sto):
        return pybamm.Interpolant(soc, voltage, sto)

    return ocp, soc, voltage


def build_ocp_variant(
    variant: str = "lithiation",
    cell: str = "4ccc47",
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
):
    """
    pybamm.ParameterValues = reference set + A.5 geometry + chosen OCP.

    ``variant`` in {"lithiation", "delithiation", "mean"}.
    """
    import pybamm

    tables = load_ocp_tables(ocp_dir)
    if variant == "mean":
        lith, deli = tables["lithiation"], tables["delithiation"]
        lo = max(float(lith["SOC"].min()), float(deli["SOC"].min()))
        hi = min(float(lith["SOC"].max()), float(deli["SOC"].max()))
        grid = np.linspace(lo, hi, 400)
        v_lith = np.interp(grid, lith["SOC"], lith["Voltage"])
        v_deli = np.interp(grid, deli["SOC"], deli["Voltage"])
        soc, voltage = grid, 0.5 * (v_lith + v_deli)
    elif variant in ("lithiation", "delithiation"):
        tbl = tables[variant]
        soc = tbl["SOC"].to_numpy(float)
        voltage = tbl["Voltage"].to_numpy(float)
    else:
        raise ValueError(
            f"unknown OCP variant '{variant}' "
            f"(expected lithiation|delithiation|mean)"
        )

    ocp, soc_used, v_used = _ocp_function(soc, voltage)

    ref = pybamm.ParameterValues(REFERENCE_SET)
    pv = pybamm.ParameterValues(dict(ref))

    # ---- geometry (Phase A.5, unchanged) ----
    geom = geometry_override(cell, metadata_csv)
    for key, value in geom["override"].items():
        pv[key] = value

    # ---- OCP (this phase) ----
    pv[KEY_OCP] = ocp

    # ---- voltage window of the measured programme ----
    pv[KEY_LOWER_V] = MEASURED_LOWER_CUTOFF_V
    pv[KEY_UPPER_V] = MEASURED_UPPER_CUTOFF_V

    pv.attrs = getattr(pv, "attrs", {}) if hasattr(pv, "attrs") else {}
    return pv


def variant_summary(
    variant: str = "lithiation",
    cell: str = "4ccc47",
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
) -> dict:
    """
    Auditable description of one variant (no pybamm needed).

    ``set_id_suffix`` lets a SECOND table set (e.g. the Phase B0.6
    high-fidelity extraction written to another directory) coexist in
    the same process with its own ids.  Empty by default, so every
    existing id and output is unchanged.
    """
    tables = load_ocp_tables(ocp_dir)
    if variant == "mean":
        soc_lo = max(float(tables["lithiation"]["SOC"].min()),
                     float(tables["delithiation"]["SOC"].min()))
        soc_hi = min(float(tables["lithiation"]["SOC"].max()),
                     float(tables["delithiation"]["SOC"].max()))
        n = "400 (interpolated grid)"
        vrange = [
            float(min(tables["lithiation"]["Voltage"].min(),
                      tables["delithiation"]["Voltage"].min())),
            float(max(tables["lithiation"]["Voltage"].max(),
                      tables["delithiation"]["Voltage"].max())),
        ]
        source = "0.5 * (lithiation + delithiation) on the overlap grid"
    else:
        tbl = tables[variant]
        soc_lo = float(tbl["SOC"].min())
        soc_hi = float(tbl["SOC"].max())
        n = int(len(tbl))
        vrange = [float(tbl["Voltage"].min()), float(tbl["Voltage"].max())]
        source = f"measured {variant} branch of the SINTEF p-OCV"

    geom_override = geometry_override(cell, metadata_csv)
    geom = derive_geometry(read_structure(cell, metadata_csv))
    return {
        "variant": variant,
        "parameter_set_id": {
            "lithiation": OCP_LITH_ID,
            "delithiation": OCP_DELI_ID,
            "mean": OCP_MEAN_ID,
        }[variant] + set_id_suffix,
        "reference_parameter_set": REFERENCE_SET,
        "geometry_parameter_set_id": GEOMETRY_PARAMETER_SET_ID,
        "ocp_source": source,
        "ocp_table_points": n,
        "ocp_soc_range": [soc_lo, soc_hi],
        "ocp_voltage_range_V": vrange,
        "ocp_extrapolation": (
            "pybamm linear Interpolant extrapolates linearly outside "
            f"[{soc_lo:.3f}, {soc_hi:.3f}]"
        ),
        "kept_unchanged": KEPT_UNCHANGED_PHASE_B0,
        "voltage_window_override": {
            KEY_LOWER_V: MEASURED_LOWER_CUTOFF_V,
            KEY_UPPER_V: MEASURED_UPPER_CUTOFF_V,
            "reason": (
                "the reference set carries Ecker's own 0-1.5 V window; the "
                "measured programme spans 0.01-1.0 V with the fresh cell at "
                "~3.0 V, so the published bounds must be replaced or the "
                "upper-voltage event fires at t=0"
            ),
        },
        "geometry_override": geom_override["override"],
        "geometry_scale_ratios": geom["scale_ratios_vs_reference"],
        "wording": (
            "reference diffusivity/kinetics + measured geometry + "
            "experiment-derived PSEUDO-OCP; nothing fitted to any voltage; "
            "NOT validation"
        ),
    }


def register_variants(
    cell: str = "4ccc47",
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    variants: Optional[List[str]] = None,
    set_id_suffix: str = "",
) -> Dict[str, str]:
    """
    Register the derived variants for name-based lookup in THIS
    process (read-through view over pybamm.parameter_sets).

    ``set_id_suffix`` (default empty) suffixes every id so that a
    second table set can be registered side by side without
    overwriting the first.
    """
    import pybamm

    from parameters.sintef_graphite_geometry import _ParameterSetsWithExtra

    variants = variants or ["lithiation", "delithiation", "mean"]
    extra: Dict[str, dict] = {}
    for variant in variants:
        pv = build_ocp_variant(variant, cell, ocp_dir, metadata_csv)
        extra[variant_summary(variant, cell, ocp_dir, metadata_csv,
                              set_id_suffix)["parameter_set_id"]] = dict(pv)

    current = pybamm.parameter_sets
    if isinstance(current, _ParameterSetsWithExtra):
        current._extra.update(extra)
    else:
        pybamm.parameter_sets = _ParameterSetsWithExtra(current, extra)
    return {v: variant_summary(v, cell, ocp_dir, metadata_csv,
                               set_id_suffix)["parameter_set_id"]
            for v in variants}


def write_variant_summaries(
    out_dir: Path | str = DEFAULT_OCP_DIR,
    cell: str = "4ccc47",
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
) -> Path:
    d = Path(out_dir)
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "cell": cell,
        "variants": [
            variant_summary(v, cell, out_dir, metadata_csv,
                            set_id_suffix)
            for v in ("lithiation", "delithiation", "mean")
        ],
        "reference_baseline": {
            "parameter_set_id": REFERENCE_SET,
            "note": "published reference OCP + reference geometry (Phase A)",
        },
    }
    path = d / "ocp_parameter_variants.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path
