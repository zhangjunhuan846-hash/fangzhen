# ============================================================
# Phase A.5 (graphite line): geometry-aware zero-fit parameter set
#
# GOAL: test whether the "voltage frozen" artefact of Phase A is a
# pure SCALE artefact, by replacing ONLY the electrode geometry of
# the PyBaMM built-in reference set with the geometry MEASURED in
# the SINTEF catalog metadata.  No parameter is fitted to any
# voltage; OCP, diffusivity and kinetics are carried over
# bit-for-bit from the reference set.
#
#   reference : Ecker2015_graphite_halfcell
#               area 85.85 cm2, thickness 74 um, eps_am 0.372403,
#               declared nominal capacity 0.15625 Ah
#   derived   : SINTEF graphite R2032 coin cell 4ccc47
#               area 1.5391 cm2 (14 mm disc), thickness 64 um,
#               coating loading 3.7767e-3 g/cm2, AM 90.984 %
#
# OVERRIDDEN (geometry only)
#   Electrode height [m]
#   Electrode width [m]
#   Positive electrode thickness [m]
#   Positive electrode active material volume fraction
#   Nominal cell capacity [A.h]
#
# KEPT UNCHANGED (verified by identity in tests)
#   Positive electrode OCP [V]                        (Ecker2015 graphite)
#   Positive particle diffusivity [m2.s-1]
#   Positive electrode exchange-current density [A.m-2]
#   Maximum concentration in positive electrode [mol.m-3]  (31920)
#   Positive electrode porosity                      (0.329, NOT measured)
#   Positive particle radius [m]                     (13.7 um, NOT measured)
#
# INJECTION (no repo / core modification): PyBaMM resolves a named
# set through ``pybamm.parameter_sets``, which is a plain
# dict-of-dicts, so a derived set is registered AT RUNTIME by this
# module.  Nothing in battery_sim/ or configs/ is edited.
#
# eps_am: two independent derivations are computed and BOTH are
# reported; the mass-based one is used as primary because it uses
# only measured quantities (plus the standard graphite true density,
# cross-checked against the reference set's own consistency:
# 31920 mol/m3 <-> 372 mAh/g at rho ~ 2260 kg/m3).
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------
# Reference set + the exact keys this module is allowed to touch
# ------------------------------------------------------------------
REFERENCE_SET = "Ecker2015_graphite_halfcell"
GEOMETRY_PARAMETER_SET_ID = "sintef_graphite_geometry_v1"

KEY_HEIGHT = "Electrode height [m]"
KEY_WIDTH = "Electrode width [m]"
KEY_THICKNESS = "Positive electrode thickness [m]"
KEY_EPS_AM = "Positive electrode active material volume fraction"
KEY_NOMINAL_Q = "Nominal cell capacity [A.h]"

OVERRIDDEN_PARAMETERS = [
    KEY_HEIGHT,
    KEY_WIDTH,
    KEY_THICKNESS,
    KEY_EPS_AM,
    KEY_NOMINAL_Q,
]

KEPT_PARAMETERS = [
    "Positive electrode OCP [V]",
    "Positive particle diffusivity [m2.s-1]",
    "Positive electrode exchange-current density [A.m-2]",
    "Maximum concentration in positive electrode [mol.m-3]",
    "Positive electrode porosity",
    "Positive particle radius [m]",
]

# ------------------------------------------------------------------
# Physical constants / defaults
# ------------------------------------------------------------------
GRAPHITE_TRUE_DENSITY_KG_M3 = 2260.0   # standard graphite true density
FARADAY_C_MOL = 96485.33212            # C/mol (CODATA, as used by PyBaMM)
DEFAULT_METADATA_CSV = "data/metadata.csv"
DEFAULT_CELL = "4ccc47"

# metadata.csv columns (same vocabulary as the adapter)
META_BDF = "BDF names"
META_AM_TYPE = "Active Material type"
META_LABEL = "Public Labels"
META_MASS_MG = "Mass of Active Material / mg"
META_WT_PCT = "Weight percentage of Active Material / %"
META_THEO_CAP = "Theoretical Capacity /  mAh g-1"
META_DIAMETER = "Electrode Diameter / cm"   # values are MILLIMETRES
META_THICKNESS_UM = "Dry Thickness / um"
META_AREAL_CAP = "Nominal Areal Capacity / mAh cm-2"
META_LOADING = "Electrode Loading / g cm-2"


# ------------------------------------------------------------------
# 1. measured structure (catalog metadata; read-only)
# ------------------------------------------------------------------
def read_structure(
    cell: str = DEFAULT_CELL,
    metadata_csv: Optional[Path | str] = None,
) -> Dict[str, object]:
    """Measured electrode structure of one cell from the catalog CSV."""
    path = Path(metadata_csv or (ROOT / DEFAULT_METADATA_CSV))
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"metadata csv not found: {path}")

    meta = pd.read_csv(path)
    if META_BDF not in meta.columns:
        raise ValueError(f"{path.name}: missing column '{META_BDF}'")
    hit = meta[meta[META_BDF].astype(str).str.contains(str(cell), regex=False)]
    if len(hit) != 1:
        raise ValueError(
            f"{path.name}: {len(hit)} rows match cell '{cell}'; expected 1"
        )
    row = hit.iloc[0]
    d_mm = float(row[META_DIAMETER])
    out: Dict[str, object] = {
        "cell_id": str(cell),
        "metadata_csv": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "source_file": str(row[META_BDF]),
        "public_label": str(row.get(META_LABEL, "")),
        "active_material_type": str(row.get(META_AM_TYPE, "")),
        "mass_active_material_mg": float(row[META_MASS_MG]),
        "active_material_wt_pct": float(row[META_WT_PCT]),
        "theoretical_capacity_mAh_g": float(row[META_THEO_CAP]),
        "electrode_diameter_mm": d_mm,
        "dry_thickness_um": float(row[META_THICKNESS_UM]),
        "nominal_areal_capacity_mAh_cm2": float(row[META_AREAL_CAP]),
        "electrode_loading_g_cm2": float(row[META_LOADING]),
        "unit_note": (
            "the catalog column labelled 'Electrode Diameter / cm' holds "
            "MILLIMETRES (14 = standard 14 mm R2032 disc); taken as mm here"
        ),
    }
    out["electrode_area_cm2"] = float(np.pi * (d_mm / 20.0) ** 2)
    return out


# ------------------------------------------------------------------
# 2. derived geometry (pure arithmetic, every step recorded)
# ------------------------------------------------------------------
def derive_geometry(
    structure: Dict[str, object],
    reference_area_m2: float = 0.101 * 0.085,
    reference_height_m: float = 0.101,
    reference_width_m: float = 0.085,
    reference_eps_am: float = 0.372403,
    reference_thickness_m: float = 7.4e-05,
    reference_nominal_capacity_Ah: float = 0.15625,
    c_max_mol_m3: float = 31920.0,
    graphite_true_density_kg_m3: float = GRAPHITE_TRUE_DENSITY_KG_M3,
) -> Dict[str, object]:
    """
    Geometry override derived from measured structure.

    Aspect ratio of the reference electrode is preserved so that ONLY
    the scale changes (a square electrode would be a second, larger
    modelling choice).
    """
    area_cm2 = float(structure["electrode_area_cm2"])
    area_m2 = area_cm2 * 1e-4
    thickness_m = float(structure["dry_thickness_um"]) * 1e-6
    loading_g_cm2 = float(structure["electrode_loading_g_cm2"])
    wt_frac = float(structure["active_material_wt_pct"]) / 100.0
    mass_am_kg = float(structure["mass_active_material_mg"]) * 1e-6
    areal_capacity_mAh_cm2 = float(
        structure["nominal_areal_capacity_mAh_cm2"]
    )

    # aspect ratio preserved from the reference electrode
    aspect = reference_height_m / reference_width_m
    width_m = float(np.sqrt(area_m2 / aspect))
    height_m = float(aspect * width_m)

    # --- eps_am route 1 (PRIMARY): active mass / (rho * V_electrode) ---
    # uses measured active mass + measured disc area + measured thickness
    # (independent of the catalog's loading/area inconsistency)
    eps_am_mass = mass_am_kg / (
        graphite_true_density_kg_m3 * thickness_m * area_m2
    )

    # --- eps_am route 2 (cross-check): from the loading column --------
    active_loading_kg_m2 = loading_g_cm2 * wt_frac * 10.0  # g/cm2 -> kg/m2
    eps_am_loading = active_loading_kg_m2 / (
        graphite_true_density_kg_m3 * thickness_m
    )

    # --- eps_am route 3 (cross-check): areal capacity + c_max -------
    q_areal_C_m2 = areal_capacity_mAh_cm2 * 1e-3 * 3600.0  # Ah/cm2 -> C/m2
    eps_am_areal = q_areal_C_m2 / (thickness_m * c_max_mol_m3 * FARADAY_C_MOL)

    eps_am_used = float(eps_am_mass)

    # --- resulting model capacity ---------------------------------
    per_area_Ah_m2 = (
        thickness_m * eps_am_used * c_max_mol_m3 * FARADAY_C_MOL / 3600.0
    )
    nominal_capacity_Ah = per_area_Ah_m2 * area_m2

    # --- measured-vs-derived consistency ---------------------------
    mass_implied_areal_mAh_cm2 = (
        active_loading_kg_m2 * 1e-1 * float(structure["theoretical_capacity_mAh_g"])
    )  # kg/m2 -> g/cm2 is *1e-1, times mAh/g

    return {
        "electrode_area_cm2": area_cm2,
        "electrode_area_m2": area_m2,
        "electrode_width_m": width_m,
        "electrode_height_m": height_m,
        "electrode_thickness_m": thickness_m,
        "active_material_volume_fraction": eps_am_used,
        "nominal_cell_capacity_Ah": nominal_capacity_Ah,
        "derivations": {
            "electrode_area_m2": (
                f"pi * (d/2)^2 with d = {structure['electrode_diameter_mm']} mm "
                f"(catalog column labelled 'cm', values are mm)"
            ),
            "electrode_width_m": (
                f"sqrt(area / aspect) with aspect = {aspect:.6f} preserved "
                f"from {REFERENCE_SET} (height {reference_height_m} / "
                f"width {reference_width_m}); scale-only change"
            ),
            "electrode_height_m": "aspect * width",
            "electrode_thickness_m": (
                f"measured dry thickness "
                f"{structure['dry_thickness_um']} um"
            ),
            "active_material_volume_fraction": (
                "PRIMARY (active mass): eps_am = m_AM / (rho_graphite * "
                f"thickness * area) with m_AM "
                f"{structure['mass_active_material_mg']} mg, rho "
                f"{graphite_true_density_kg_m3} kg/m3, thickness "
                f"{thickness_m:.3e} m, area {area_m2:.6e} m2"
            ),
            "nominal_cell_capacity_Ah": (
                "area * thickness * eps_am * c_max * F / 3600 with c_max "
                f"{c_max_mol_m3} mol/m3 carried over unchanged"
            ),
        },
        "cross_checks": {
            "eps_am_active_mass_route": float(eps_am_mass),
            "eps_am_loading_column_route": float(eps_am_loading),
            "eps_am_areal_capacity_route": float(eps_am_areal),
            "eps_am_relative_difference_loading_vs_mass_pct": float(
                100.0 * (eps_am_loading - eps_am_mass) / eps_am_mass
            ),
            "eps_am_relative_difference_areal_vs_mass_pct": float(
                100.0 * (eps_am_areal - eps_am_mass) / eps_am_mass
            ),
            "catalog_nominal_areal_capacity_mAh_cm2": areal_capacity_mAh_cm2,
            "mass_implied_areal_capacity_mAh_cm2": float(
                mass_implied_areal_mAh_cm2
            ),
            "catalog_internal_inconsistency": (
                "the catalog is ~10 % internally inconsistent: its "
                "(coating mass / loading) implies a larger electrode area "
                "than the punched-disc diameter gives.  The disc diameter "
                f"({structure['electrode_diameter_mm']:g} mm -> "
                f"{area_cm2:.4f} cm2) is used for the AREA because it is the "
                "physical electrode; the active mass is used for eps_am; both "
                "alternatives are reported and neither is silently corrected."
            ),
        },
        "not_measured_kept_from_reference": [
            KEY_HEIGHT,  # reported for completeness; overridden via area
            "Positive electrode porosity",
            "Positive particle radius [m]",
        ],
        "reference_values": {
            "area_m2": float(reference_area_m2),
            "thickness_m": float(reference_thickness_m),
            "eps_am": float(reference_eps_am),
            "nominal_cell_capacity_Ah": float(reference_nominal_capacity_Ah),
        },
        "scale_ratios_vs_reference": {
            "area_ratio_reference_over_measured": float(
                reference_area_m2 / area_m2
            ),
            "thickness_ratio": float(reference_thickness_m / thickness_m),
            "per_area_capacity_ratio": float(
                (reference_nominal_capacity_Ah / reference_area_m2)
                / (nominal_capacity_Ah / area_m2)
            ),
        },
    }


# ------------------------------------------------------------------
# 3. parameter override payload (JSON) + pybamm dict
# ------------------------------------------------------------------
def geometry_override(
    cell: str = DEFAULT_CELL,
    metadata_csv: Optional[Path | str] = None,
) -> Dict[str, object]:
    """Full, auditable geometry override payload (the phase deliverable)."""
    structure = read_structure(cell, metadata_csv)
    geom = derive_geometry(structure)
    return {
        "parameter_set_id": GEOMETRY_PARAMETER_SET_ID,
        "reference_parameter_set": REFERENCE_SET,
        "purpose": (
            "Phase A.5 geometry-aware ZERO-FIT: remove the electrode-scale "
            "mismatch of Phase A without fitting anything to voltage"
        ),
        "measured_structure": structure,
        "override": {
            KEY_HEIGHT: geom["electrode_height_m"],
            KEY_WIDTH: geom["electrode_width_m"],
            KEY_THICKNESS: geom["electrode_thickness_m"],
            KEY_EPS_AM: geom["active_material_volume_fraction"],
            KEY_NOMINAL_Q: geom["nominal_cell_capacity_Ah"],
        },
        "kept_unchanged": KEPT_PARAMETERS,
        "derivations": geom["derivations"],
        "derivations_by_parameter": {
            KEY_HEIGHT: geom["derivations"]["electrode_height_m"],
            KEY_WIDTH: geom["derivations"]["electrode_width_m"],
            KEY_THICKNESS: geom["derivations"]["electrode_thickness_m"],
            KEY_EPS_AM: geom["derivations"]["active_material_volume_fraction"],
            KEY_NOMINAL_Q: geom["derivations"]["nominal_cell_capacity_Ah"],
        },
        "cross_checks": geom["cross_checks"],
        "reference_values": geom["reference_values"],
        "scale_ratios_vs_reference": geom["scale_ratios_vs_reference"],
        "not_measured_kept_from_reference": geom[
            "not_measured_kept_from_reference"
        ],
        "wording": (
            "geometry override from measured structure; OCP / diffusivity / "
            "kinetics unchanged; still a reference (surrogate) parameter "
            "set, still zero-fit, NOT validation"
        ),
    }


def build_parameter_values(
    cell: str = DEFAULT_CELL,
    metadata_csv: Optional[Path | str] = None,
):
    """
    Reference set with ONLY the geometry replaced (lazy pybamm import).

    Returns a ``pybamm.ParameterValues``.  OCP / diffusivity / kinetics
    objects are carried over unchanged (identity-checked in tests).
    """
    import pybamm  # local import: this module stays importable without it

    override = geometry_override(cell, metadata_csv)
    ref = pybamm.ParameterValues(REFERENCE_SET)
    pv = pybamm.ParameterValues(dict(ref))  # copy, then override geometry
    for key, value in override["override"].items():
        if key not in pv:
            raise KeyError(
                f"reference set '{REFERENCE_SET}' has no key '{key}'; "
                f"refusing to add a parameter that the model does not expect"
            )
        pv[key] = value
    return pv


class _ParameterSetsWithExtra:
    """
    Read-through view over ``pybamm.parameter_sets`` plus our runtime sets.

    ``pybamm.parameter_sets`` is a LAZY entry-point mapping (assignment
    raises ``TypeError``), and ``pybamm.ParameterValues(name)`` resolves
    names through that module attribute at call time.  Swapping the
    module attribute for this view therefore injects a derived set
    WITHOUT editing PyBaMM, battery_sim/ or any config file.

    Only the mapping protocol PyBaMM actually uses is implemented
    (``in``, ``[]``, ``get``, ``keys``, ``items``, ``values``, ``len``).
    """

    def __init__(self, base, extra: Dict[str, dict]):
        self._base = base
        self._extra = dict(extra)

    def __getitem__(self, key):
        if key in self._extra:
            return self._extra[key]
        return self._base[key]

    def __contains__(self, key) -> bool:
        return key in self._extra or key in self._base

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self):
        return list(dict.fromkeys(list(self._extra) + list(self._base.keys())))

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def values(self):
        return [self[k] for k in self.keys()]


def register(
    cell: str = DEFAULT_CELL,
    metadata_csv: Optional[Path | str] = None,
) -> str:
    """
    Make the derived set resolvable by name in THIS process and return
    the id, so it is a drop-in for any ``parameter_set`` string
    (e.g. ``run_baseline_cell(..., parameter_set=id)``).

    Implementation: build the dict, then swap ``pybamm.parameter_sets``
    for a read-through view that also serves our set.  Runtime-only:
    nothing is written to disk and no repository file is modified.
    """
    import pybamm

    override = geometry_override(cell, metadata_csv)
    base = dict(pybamm.parameter_sets[REFERENCE_SET])
    for key, value in override["override"].items():
        if key not in base:
            raise KeyError(
                f"reference set '{REFERENCE_SET}' has no key '{key}'; "
                f"refusing to add a parameter the model does not expect"
            )
        base[key] = value

    current = pybamm.parameter_sets
    if isinstance(current, _ParameterSetsWithExtra):
        current._extra[GEOMETRY_PARAMETER_SET_ID] = base
    else:
        pybamm.parameter_sets = _ParameterSetsWithExtra(
            current, {GEOMETRY_PARAMETER_SET_ID: base}
        )
    return GEOMETRY_PARAMETER_SET_ID


def write_geometry_json(
    path: Path | str = "outputs/analysis/graphite_phaseA5/geometry_override.json",
    cell: str = DEFAULT_CELL,
    metadata_csv: Optional[Path | str] = None,
) -> Path:
    """Persist the auditable override payload."""
    out = Path(path)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = geometry_override(cell, metadata_csv)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return out
