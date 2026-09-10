# ============================================================
# Phase A.5 tests: geometry override module
#
# Hermetic: synthetic metadata csv in tmp_path; the vendored OCP
# table and the reference parameter set are the only real inputs.
# ============================================================

import numpy as np
import pandas as pd
import pytest

from parameters.sintef_graphite_geometry import (
    GEOMETRY_PARAMETER_SET_ID,
    GRAPHITE_TRUE_DENSITY_KG_M3,
    KEPT_PARAMETERS,
    OVERRIDDEN_PARAMETERS,
    REFERENCE_SET,
    build_parameter_values,
    derive_geometry,
    geometry_override,
    read_structure,
    register,
)
from battery_sim.paths import ROOT

META_COLUMNS = [
    "BDF names", "Active Material type", "Start Date YYYYMMDD",
    "Public Labels", "Cycling Programme name",
    "Mass of Active Material / mg", "Electrode Coating Mass / g",
    "Weight percentage of Active Material / %",
    "Theoretical Capacity /  mAh g-1", "Electrode Diameter / cm",
    "Dry Thickness / um", "Nominal Areal Capacity / mAh cm-2",
    "Electrode Loading / g cm-2", "Known Issues",
]


def _metadata_csv(tmp_path, cell="4ccc47"):
    row = [
        f"sintef__sintef-graphite-R2032-intelligent-{cell}__20250514__p-ocv__RT.bdf.parquet",
        "Graphite", 20250514, "Gr-AQ-1", "p-OCV",
        5.816164537524997, 0.006392499999999995, 90.98419274124022,
        372, 14, 64, 1.404943641532012, 0.0037767302191720753, "",
    ]
    path = tmp_path / "metadata.csv"
    pd.DataFrame([row], columns=META_COLUMNS).to_csv(path, index=False)
    return path


# --------------------------------------------------------------
# measured structure (unit trap)
# --------------------------------------------------------------
def test_read_structure_treats_diameter_as_mm(tmp_path):
    s = read_structure("4ccc47", _metadata_csv(tmp_path))
    # 14 mm disc -> 1.5394 cm2 (NOT 153.9 cm2: the catalog column
    # is labelled 'cm' but holds millimetres)
    assert s["electrode_diameter_mm"] == 14.0
    assert abs(s["electrode_area_cm2"] - 1.5394) < 1e-3
    assert "MILLIMETRES" in s["unit_note"]


def test_read_structure_rejects_unknown_cell(tmp_path):
    with pytest.raises(ValueError, match="expected 1"):
        read_structure("deadbeef", _metadata_csv(tmp_path))


# --------------------------------------------------------------
# derived geometry
# --------------------------------------------------------------
def test_derive_geometry_preserves_aspect_ratio_and_area(tmp_path):
    s = read_structure("4ccc47", _metadata_csv(tmp_path))
    g = derive_geometry(s)

    area_m2 = g["electrode_area_m2"]
    assert abs(area_m2 - 1.5394e-4) < 1e-7
    assert abs(g["electrode_height_m"] * g["electrode_width_m"] - area_m2) < 1e-12
    # aspect ratio 0.101/0.085 preserved -> scale-only change
    assert abs(g["electrode_height_m"] / g["electrode_width_m"] - 0.101 / 0.085) < 1e-9
    assert abs(g["electrode_thickness_m"] - 64e-6) < 1e-12


def test_derive_geometry_eps_am_routes_and_capacity(tmp_path):
    s = read_structure("4ccc47", _metadata_csv(tmp_path))
    g = derive_geometry(s)

    eps = g["active_material_volume_fraction"]
    assert 0.2 < eps < 0.3
    # independent routes must agree to within 15 %
    assert abs(
        g["cross_checks"]["eps_am_relative_difference_loading_vs_mass_pct"]
    ) < 15.0
    # derived cell capacity lands near the catalog nominal (2.16 mAh)
    assert 1.9e-3 < g["nominal_cell_capacity_Ah"] < 2.5e-3
    # scale ratios: reference is much bigger
    assert g["scale_ratios_vs_reference"]["area_ratio_reference_over_measured"] > 50


def test_derive_geometry_capacity_scales_with_eps_and_cmax(tmp_path):
    """Capacity formula is explicit: area x thickness x eps x c_max x F/3600."""
    s = read_structure("4ccc47", _metadata_csv(tmp_path))
    g = derive_geometry(s, c_max_mol_m3=31920.0)
    expected = (
        g["electrode_area_m2"] * g["electrode_thickness_m"]
        * g["active_material_volume_fraction"] * 31920.0 * 96485.33212 / 3600.0
    )
    assert abs(g["nominal_cell_capacity_Ah"] - expected) < 1e-12


# --------------------------------------------------------------
# override payload
# --------------------------------------------------------------
def test_geometry_override_payload_is_auditable(tmp_path):
    p = geometry_override("4ccc47", _metadata_csv(tmp_path))
    assert p["parameter_set_id"] == GEOMETRY_PARAMETER_SET_ID
    assert p["reference_parameter_set"] == REFERENCE_SET
    # exactly the geometry keys are overridden
    assert set(p["override"]) == set(OVERRIDDEN_PARAMETERS)
    # OCP / diffusivity / kinetics are declared kept
    assert "Positive electrode OCP [V]" in p["kept_unchanged"]
    assert "Positive particle diffusivity [m2.s-1]" in p["kept_unchanged"]
    assert "Positive electrode exchange-current density [A.m-2]" in KEPT_PARAMETERS
    # every override carries a derivation string in parameter-key space
    for key in p["override"]:
        assert key in p["derivations_by_parameter"]
        assert p["derivations_by_parameter"][key]
    # and the catalog inconsistency is reported, not hidden
    assert "catalog_internal_inconsistency" in p["cross_checks"]
    assert "NOT validation" in p["wording"]


# --------------------------------------------------------------
# parameter-set construction (pybamm-side)
# --------------------------------------------------------------
def test_build_parameter_values_changes_only_geometry(tmp_path):
    pv = build_parameter_values("4ccc47", _metadata_csv(tmp_path))
    import pybamm

    ref = pybamm.ParameterValues(REFERENCE_SET)

    # geometry replaced
    assert abs(pv["Positive electrode thickness [m]"] - 64e-6) < 1e-12
    assert abs(
        pv["Electrode height [m]"] * pv["Electrode width [m]"] - 1.5394e-4
    ) < 1e-7
    assert pv["Positive electrode active material volume fraction"] != pytest.approx(
        ref["Positive electrode active material volume fraction"]
    )

    # OCP / diffusivity / kinetics / c_max carried over as the SAME objects
    for key in KEPT_PARAMETERS[:4]:
        assert pv[key] is ref[key] or pv[key] == ref[key]
    assert (
        pv["Maximum concentration in positive electrode [mol.m-3]"]
        == ref["Maximum concentration in positive electrode [mol.m-3]"]
    )
    # porosity and particle radius untouched (not measured in the catalog)
    assert pv["Positive electrode porosity"] == ref["Positive electrode porosity"]
    assert pv["Positive particle radius [m]"] == ref["Positive particle radius [m]"]


def test_register_makes_the_set_resolvable_by_name(tmp_path):
    set_id = register("4ccc47", _metadata_csv(tmp_path))
    assert set_id == GEOMETRY_PARAMETER_SET_ID

    import pybamm

    # resolvable through the normal ParameterValues(name) path
    assert set_id in pybamm.parameter_sets
    pv = pybamm.ParameterValues(set_id)
    assert abs(pv["Positive electrode thickness [m]"] - 64e-6) < 1e-12
    # the reference set is still resolvable too (view, not replacement)
    assert REFERENCE_SET in pybamm.parameter_sets
    ref = pybamm.ParameterValues(REFERENCE_SET)
    assert ref["Positive electrode thickness [m]"] == pytest.approx(7.4e-5)
    assert ref["Positive electrode OCP [V]"] is not None


def test_register_is_idempotent(tmp_path):
    meta = _metadata_csv(tmp_path)
    assert register("4ccc47", meta) == register("4ccc47", meta)
    import pybamm

    pv = pybamm.ParameterValues(GEOMETRY_PARAMETER_SET_ID)
    assert abs(pv["Positive electrode thickness [m]"] - 64e-6) < 1e-12


# --------------------------------------------------------------
# real catalog metadata (skipped when absent)
# --------------------------------------------------------------
def test_real_metadata_row_derives_expected_geometry():
    if not (ROOT / "data" / "metadata.csv").is_file():
        pytest.skip("SINTEF catalog metadata.csv not present")
    g = derive_geometry(read_structure("4ccc47"))
    assert abs(g["electrode_area_m2"] - 1.5391e-4) < 1e-6
    assert abs(g["electrode_thickness_m"] - 64e-6) < 1e-12
    assert 0.25 < g["active_material_volume_fraction"] < 0.27
    assert 2.1e-3 < g["nominal_cell_capacity_Ah"] < 2.3e-3
