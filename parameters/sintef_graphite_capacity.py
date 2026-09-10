# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B0.5: CAPACITY-CONSISTENT parameter override
#
# WHY THIS EXISTS
#   Phase B0 replaced the published graphite OCP with the measured
#   p-OCV branch table.  That table's abscissa is a CHARGE-BASED SOC:
#
#       Q_ref      = charge of cycle 1's lithiation branch
#                    (fresh state -> lower cutoff) = 1.9425 mAh
#       SOC_lith   = Q / Q_ref
#       SOC_deli   = 1 - |Q| / Q_ref
#
#   The table is only interpretable as an "OCP(x)" if the model's own
#   stoichiometry x means the same thing.  It does not: the model's Li
#   inventory is
#
#       Q_model = eps_am * L * A * c_max * F / 3600        [A.h]
#
#   (validated in scripts/probe_b05_capacity.py against a MEASURED
#    d(x_avg)/dt from a constant-current solve: 2.2017 mAh, 0.00 %
#    difference; the SURFACE stoichiometry moves ~21 % faster over 1 h
#    because diffusion has not equilibrated the particle -- which is
#    why the capacity must be read from the volume average, never from
#    the surface).  With Q_model = 2.2017 mAh against Q_ref = 1.9425 mAh
#    the model's x lags the table's SOC by a factor 1.13, so a branch
#    that should end at x = 0.08 stops at x = 0.19 and the model cannot
#    reach the measured 1.0 V.  That is the residual Phase B0 left in
#    the 0.60-1.43 V region.
#
# WHAT THIS PHASE DOES
#   Scale the electrode's active-material volume fraction so that the
#   model's Li inventory equals the MEASURED reference charge:
#
#       eps_am' = eps_am * (Q_target / Q_before)
#
#   with Q_target = Q_ref taken from the Phase B0 extraction
#   provenance (a measured charge, NOT a fitted value).  Nothing is
#   fitted to any voltage.
#
# WHAT IT DOES NOT TOUCH
#   OCP, particle diffusivity, exchange-current density, maximum
#   concentration, porosity, particle radius and the voltage window
#   are carried over by OBJECT IDENTITY (asserted in tests).
#
# `Nominal cell capacity [A.h]` is also updated, but only as a
# BOOKKEEPING follow-on: the probe shows the particle equation depends
# on eps_am alone, and a test asserts that changing only the nominal
# value leaves the simulated voltage bit-identical.  Leaving it at the
# pre-match value would make the parameter set self-contradictory
# (declared capacity != physical capacity).
#
# TERMINOLOGY (mandatory)
#   capacity-consistent  !=  fitted
#   Q_ref is a measured charge at the declared room temperature
#   this is still a zero-fit replay, still NOT validation
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from parameters.sintef_graphite_geometry import (
    DEFAULT_CELL,
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    read_structure,
)
from parameters.sintef_graphite_ocp import (
    DEFAULT_OCP_DIR,
    OCP_DELI_ID,
    OCP_LITH_ID,
    build_ocp_variant,
)

ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------
# parameter keys
# ------------------------------------------------------------------
KEY_EPS_AM = "Positive electrode active material volume fraction"
KEY_THICKNESS = "Positive electrode thickness [m]"
KEY_HEIGHT = "Electrode height [m]"
KEY_WIDTH = "Electrode width [m]"
KEY_C_MAX = "Maximum concentration in positive electrode [mol.m-3]"
KEY_NOMINAL_Q = "Nominal cell capacity [A.h]"
KEY_OCP = "Positive electrode OCP [V]"

# parameters this phase is FORBIDDEN to touch (identity-checked)
FROZEN_PARAMETERS: List[str] = [
    KEY_OCP,
    "Positive particle diffusivity [m2.s-1]",
    "Positive electrode exchange-current density [A.m-2]",
    KEY_C_MAX,
    "Positive electrode porosity",
    "Positive particle radius [m]",
    "Lower voltage cut-off [V]",
    "Upper voltage cut-off [V]",
]

# Parameters this phase changes, with the ROLE of each change.
CHANGED_PARAMETERS: Dict[str, str] = {
    KEY_EPS_AM: "physics - sets the model's Li inventory (Q_model)",
    KEY_NOMINAL_Q: (
        "bookkeeping - declared capacity only; does not enter the "
        "particle equation (asserted in tests)"
    ),
}

CAPACITY_MATCHED_IDS: Dict[str, str] = {
    "lithiation": "sintef_graphite_ocp_lith_capmatch_v1",
    "delithiation": "sintef_graphite_ocp_deli_capmatch_v1",
}

BASE_OCP_IDS: Dict[str, str] = {
    "lithiation": OCP_LITH_ID,
    "delithiation": OCP_DELI_ID,
}

FARADAY_C_MOL = 96485.33212  # C/mol (CODATA, as PyBaMM uses)
PROVENANCE_NAME = "ocp_extraction_provenance.json"


# ------------------------------------------------------------------
# 1. the capacity the model actually has
# ------------------------------------------------------------------
def electrode_capacity_Ah(parameter_values) -> float:
    """
    Li inventory of the working electrode as the model defines it:

        Q = eps_am * L * A * c_max * F / 3600      [A.h]

    ``parameter_values`` is anything mapping-like (a pybamm
    ParameterValues or a plain dict).  Validated against a measured
    d(x_avg)/dt from a constant-current SPM solve (0.00 % difference)
    -- see scripts/probe_b05_capacity.py.
    """
    area_m2 = float(parameter_values[KEY_HEIGHT]) * float(
        parameter_values[KEY_WIDTH]
    )
    return (
        float(parameter_values[KEY_THICKNESS])
        * float(parameter_values[KEY_EPS_AM])
        * area_m2
        * float(parameter_values[KEY_C_MAX])
        * FARADAY_C_MOL
        / 3600.0
    )


# ------------------------------------------------------------------
# 2. where Q_target comes from (measured, not fitted)
# ------------------------------------------------------------------
def read_q_target(
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    override_Ah: Optional[float] = None,
) -> Dict[str, object]:
    """
    The capacity target = Q_ref of the Phase B0 OCP extraction
    (lithiation-branch charge, a MEASURED quantity).

    ``override_Ah`` exists for unit tests; anything else is read from
    the extraction provenance file so the number is never retyped.
    """
    if override_Ah is not None:
        q = float(override_Ah)
        if not np.isfinite(q) or q <= 0:
            raise ValueError(f"q_target_Ah must be positive (got {q!r})")
        return {
            "q_target_Ah": q,
            "source": "explicit override (test / caller supplied)",
            "provenance_file": None,
            "soc_definition": None,
            "temperature_source": None,
        }

    d = Path(ocp_dir)
    if not d.is_absolute():
        d = ROOT / d
    path = d / PROVENANCE_NAME
    if not path.is_file():
        raise FileNotFoundError(
            f"OCP extraction provenance not found: {path} "
            f"(Phase B0 must run before Phase B0.5)"
        )
    with path.open(encoding="utf-8") as fh:
        prov = json.load(fh)
    for key in ("soc_reference_charge_Ah", "soc_definition",
                "equilibrium_warning"):
        if key not in prov:
            raise ValueError(f"{path.name}: missing key '{key}'")
    q = float(prov["soc_reference_charge_Ah"])
    if not np.isfinite(q) or q <= 0:
        raise ValueError(f"{path.name}: soc_reference_charge_Ah invalid ({q})")
    return {
        "q_target_Ah": q,
        "source": "Phase B0 extraction provenance (measured charge)",
        "provenance_file": str(path.relative_to(ROOT))
        if path.is_relative_to(ROOT)
        else str(path),
        "soc_definition": prov["soc_definition"],
        "temperature_source": prov.get("temperature_source"),
        "equilibrium_warning": prov["equilibrium_warning"],
    }


def _ensure_base_registered(
    cell: str,
    ocp_dir: Path | str,
    metadata_csv: Optional[Path | str],
) -> None:
    """
    The base sets of Phase B0 must be resolvable by name before a
    capacity-matched set can be derived from them.  Registering is
    idempotent (read-through view over pybamm.parameter_sets), so this
    is safe to call on every entry point.
    """
    import pybamm

    from parameters.sintef_graphite_ocp import register_variants

    if BASE_OCP_IDS["delithiation"] not in pybamm.parameter_sets:
        register_variants(cell, ocp_dir, metadata_csv)


# ------------------------------------------------------------------
# 3. the override payload (the auditable deliverable)
# ------------------------------------------------------------------
def capacity_payload(
    variant: str = "delithiation",
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
) -> Dict[str, object]:
    """
    Full audit payload for one capacity-matched variant.

    ``variant`` in {"lithiation", "delithiation"} (the OCP branch the
    set is built on; the mean variant is not used -- Phase B0 showed
    averaging the branches is invalid).
    """
    import pybamm

    if variant not in CAPACITY_MATCHED_IDS:
        raise ValueError(
            f"unknown variant '{variant}' "
            f"(expected one of {sorted(CAPACITY_MATCHED_IDS)})"
        )

    base_id = BASE_OCP_IDS[variant]
    _ensure_base_registered(cell, ocp_dir, metadata_csv)
    base = pybamm.ParameterValues(base_id)

    q_before = electrode_capacity_Ah(base)
    target = read_q_target(ocp_dir, q_target_Ah)
    q_target = float(target["q_target_Ah"])
    factor = q_target / q_before

    eps_before = float(base[KEY_EPS_AM])
    eps_after = eps_before * factor
    if not 0.0 < eps_after < 1.0:
        raise ValueError(
            f"capacity matching would push eps_am to {eps_after:.6f}, "
            f"outside (0, 1); the target is not physically reachable by "
            f"scaling eps_am alone"
        )

    q_after = q_before * factor  # by construction; verified below

    # physical feasibility of the electrode volume balance
    porosity = float(base["Positive electrode porosity"])

    # measured-structure cross reference (reported, never used to
    # silently correct anything)
    try:
        structure = read_structure(cell, metadata_csv)
        loading_am_g_cm2_before = (
            float(structure["electrode_loading_g_cm2"])
            * float(structure["active_material_wt_pct"])
            / 100.0
        )
    except FileNotFoundError:
        structure = None
        loading_am_g_cm2_before = float("nan")

    return {
        "parameter_set_id": CAPACITY_MATCHED_IDS[variant],
        "base_parameter_set": base_id,
        "reference_parameter_set": REFERENCE_SET,
        "geometry_parameter_set": GEOMETRY_PARAMETER_SET_ID,
        "variant": variant,
        "purpose": (
            "Phase B0.5 capacity consistency: make the model's Li "
            "inventory equal the MEASURED reference charge of the "
            "p-OCV extraction, so the model's stoichiometry x and the "
            "OCP table's charge-based SOC mean the same thing"
        ),
        "capacity_model": (
            "Q_model = eps_am * L * A * c_max * F / 3600, validated "
            "against a measured d(x_volume-averaged)/dt from a "
            "constant-current solve (0.00 % difference); the surface "
            "stoichiometry is NOT used because diffusion has not "
            "equilibrated the particle"
        ),
        "q_before_Ah": float(q_before),
        "q_before_mAh": float(q_before * 1e3),
        "q_before_declared_Ah": float(base[KEY_NOMINAL_Q]),
        "q_target_Ah": float(q_target),
        "q_target_mAh": float(q_target * 1e3),
        "q_target_source": target,
        "scaling_factor": float(factor),
        "scaling_factor_definition": "Q_target / Q_before  (applied to eps_am)",
        "q_after_Ah": float(q_after),
        "q_after_mAh": float(q_after * 1e3),
        "q_after_relative_error": float(abs(q_after - q_target) / q_target),
        "changed_parameter": KEY_EPS_AM,
        "changed_parameters_detail": [
            {
                "parameter": KEY_EPS_AM,
                "role": CHANGED_PARAMETERS[KEY_EPS_AM],
                "before": eps_before,
                "after": eps_after,
                "relative_change_pct": 100.0 * (eps_after / eps_before - 1.0),
            },
            {
                "parameter": KEY_NOMINAL_Q,
                "role": CHANGED_PARAMETERS[KEY_NOMINAL_Q],
                "before": float(base[KEY_NOMINAL_Q]),
                "after": float(q_target),
                "relative_change_pct": 100.0
                * (q_target / float(base[KEY_NOMINAL_Q]) - 1.0),
            },
        ],
        "apply": {
            KEY_EPS_AM: float(eps_after),
            KEY_NOMINAL_Q: float(q_target),
        },
        "kept_unchanged": FROZEN_PARAMETERS,
        "electrode_volume_balance": {
            "eps_am_after": float(eps_after),
            "porosity": porosity,
            "sum_after": float(eps_after + porosity),
            "sum_before": float(eps_before + porosity),
            "feasible": bool(eps_after + porosity < 1.0),
            "note": (
                "the reference set declares no inactive-material volume "
                "fraction, so eps_am + porosity must simply stay < 1"
            ),
        },
        "measured_structure_cross_reference": {
            "active_material_loading_g_cm2_before": loading_am_g_cm2_before,
            "active_material_loading_g_cm2_after": (
                loading_am_g_cm2_before * factor
                if np.isfinite(loading_am_g_cm2_before)
                else float("nan")
            ),
            "note": (
                "coating loading x active-material weight fraction, scaled "
                "by the same factor; reported for the electrode-fabrication "
                "record only - the model parameter is eps_am"
            ),
        },
        "is_fitted_to_voltage": False,
        "wording": (
            "capacity-CONSISTENT, not fitted: Q_target is a measured "
            "charge from the p-OCV extraction, OCP / diffusivity / "
            "kinetics / voltage window are unchanged by object identity, "
            "and this remains a zero-fit reference replay - NOT validation"
        ),
    }


# ------------------------------------------------------------------
# 4. build / register / persist
# ------------------------------------------------------------------
def build_capacity_matched_pair(
    variant: str = "delithiation",
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
):
    """
    ``(base, matched)`` pair of ``pybamm.ParameterValues``.

    ``base`` is the Phase B0 set (measured OCP + measured geometry) and
    ``matched`` is the same set with the capacity override applied.
    Returning the pair lets an audit compare the two by OBJECT IDENTITY
    for the parameters this phase must not touch.
    """
    import pybamm

    base = build_ocp_variant(variant, cell, ocp_dir, metadata_csv)
    pv = pybamm.ParameterValues(dict(base))
    payload = capacity_payload(
        variant, cell, ocp_dir, metadata_csv, q_target_Ah
    )
    for key, value in payload["apply"].items():
        if key not in pv:
            raise KeyError(
                f"parameter set '{BASE_OCP_IDS[variant]}' has no key "
                f"'{key}'; refusing to add a parameter the model does not "
                f"expect"
            )
        pv[key] = value
    return base, pv


def build_capacity_matched_variant(
    variant: str = "delithiation",
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
):
    """
    ``pybamm.ParameterValues`` = B0 OCP variant + capacity-matched
    eps_am.  OCP / diffusivity / kinetics objects are carried over
    unchanged (identity-checked in tests).
    """
    return build_capacity_matched_pair(
        variant, cell, ocp_dir, metadata_csv, q_target_Ah
    )[1]


def variant_summary(
    variant: str = "delithiation",
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
) -> Dict[str, object]:
    """Auditable summary (no pybamm solve; pybamm is used for lookups)."""
    return capacity_payload(
        variant, cell, ocp_dir, metadata_csv, q_target_Ah
    )


def register_capacity_variants(
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
    variants: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Register the capacity-matched sets for name-based lookup in THIS
    process (read-through view over pybamm.parameter_sets; nothing is
    written to disk and no repository file is modified).
    """
    import pybamm

    from parameters.sintef_graphite_geometry import _ParameterSetsWithExtra

    variants = variants or ["lithiation", "delithiation"]
    extra: Dict[str, dict] = {}
    for variant in variants:
        pv = build_capacity_matched_variant(
            variant, cell, ocp_dir, metadata_csv, q_target_Ah
        )
        extra[CAPACITY_MATCHED_IDS[variant]] = dict(pv)

    current = pybamm.parameter_sets
    if isinstance(current, _ParameterSetsWithExtra):
        current._extra.update(extra)
    else:
        pybamm.parameter_sets = _ParameterSetsWithExtra(current, extra)
    return {v: CAPACITY_MATCHED_IDS[v] for v in variants}


def changed_keys_against(base_parameter_values, new_parameter_values) -> List[str]:
    """Keys whose VALUE differs between two parameter sets."""
    out = []
    for key in new_parameter_values.keys():
        if key not in base_parameter_values:
            out.append(str(key))
            continue
        a, b = base_parameter_values[key], new_parameter_values[key]
        if a is b:
            continue
        try:
            same = bool(np.all(np.asarray(a, dtype=object)
                               == np.asarray(b, dtype=object)))
        except Exception:  # noqa: BLE001 - callables / expressions
            same = False
        if not same:
            out.append(str(key))
    return sorted(out)


def write_capacity_summary(
    out_dir: Path | str,
    cell: str = DEFAULT_CELL,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    metadata_csv: Optional[Path | str] = None,
    q_target_Ah: Optional[float] = None,
) -> Path:
    d = Path(out_dir)
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "cell": cell,
        "variants": [
            capacity_payload(v, cell, ocp_dir, metadata_csv, q_target_Ah)
            for v in ("lithiation", "delithiation")
        ],
    }
    path = d / "capacity_override.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path
