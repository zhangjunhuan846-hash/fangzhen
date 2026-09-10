# ============================================================
# Phase B0.5 tests: capacity-CONSISTENT parameter override
#
# Hermetic: synthetic OCP tables + synthetic catalog metadata.
# One optional test cross-checks the analytic capacity formula
# against a real short SPM solve.
# ============================================================

import json

import numpy as np
import pandas as pd
import pytest

from parameters.sintef_graphite_capacity import (
    BASE_OCP_IDS,
    CAPACITY_MATCHED_IDS,
    KEY_C_MAX,
    KEY_EPS_AM,
    KEY_HEIGHT,
    KEY_NOMINAL_Q,
    KEY_OCP,
    KEY_THICKNESS,
    KEY_WIDTH,
    build_capacity_matched_pair,
    build_capacity_matched_variant,
    capacity_payload,
    changed_keys_against,
    electrode_capacity_Ah,
    read_q_target,
    register_capacity_variants,
    write_capacity_summary,
)
from parameters.sintef_graphite_geometry import (
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (
    MEASURED_LOWER_CUTOFF_V,
    MEASURED_UPPER_CUTOFF_V,
)

META_COLUMNS = [
    "BDF names", "Active Material type", "Start Date YYYYMMDD",
    "Public Labels", "Cycling Programme name",
    "Mass of Active Material / mg", "Electrode Coating Mass / g",
    "Weight percentage of Active Material / %",
    "Theoretical Capacity /  mAh g-1", "Electrode Diameter / cm",
    "Dry Thickness / um", "Nominal Areal Capacity / mAh cm-2",
    "Electrode Loading / g cm-2", "Known Issues",
]

Q_REF_AH = 1.9424659492079026e-3     # the audited Phase B0 value


# ------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------
@pytest.fixture()
def ocp_dir(tmp_path):
    """Synthetic Phase B0 extraction outputs (same file names/schema)."""
    d = tmp_path / "ocp"
    d.mkdir()

    soc = np.linspace(0.0, 1.0, 200)
    v_lith = 3.0 - 2.99 * soc ** 0.35
    pd.DataFrame({"SOC": soc, "Voltage": v_lith, "branch": "lithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, 4.33e-5),
                  "capacity_Ah": soc * Q_REF_AH}).to_csv(
        d / "graphite_ocp_lithiation.csv", index=False)

    soc_d = np.linspace(0.9, 0.1, 200)
    v_deli = 0.10 + 0.9 * (1.0 - soc_d) ** 0.5
    pd.DataFrame({"SOC": soc_d, "Voltage": v_deli, "branch": "delithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, -4.33e-5),
                  "capacity_Ah": (soc_d - 1.0) * Q_REF_AH}).to_csv(
        d / "graphite_ocp_delithiation.csv", index=False)

    provenance = {
        "source_file": "sintef__....parquet",
        "source_sha256": "0" * 64,
        "temperature_source": "declared_room_temperature_not_measured",
        "soc_definition": (
            "Q_ref = charge of the cycle's lithiation branch (canonical "
            "current > 0); lithiation SOC = Q/Q_ref"
        ),
        "soc_reference_charge_Ah": Q_REF_AH,
        "soc_reference_charge_mAh": Q_REF_AH * 1e3,
        "equilibrium_warning": "pseudo-OCP: contains the C/50 polarisation",
        "voltage_range_V": {"lithiation": [0.01, 3.0],
                            "delithiation": [0.0967, 1.0]},
    }
    with (d / "ocp_extraction_provenance.json").open(
        "w", encoding="utf-8"
    ) as fh:
        json.dump(provenance, fh)
    return d


@pytest.fixture()
def metadata_csv(tmp_path):
    row = [
        "sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__p-ocv__RT.bdf.parquet",
        "Graphite", 20250514, "Gr-AQ-1", "p-OCV",
        5.816164537524997, 0.006392499999999995, 90.98419274124022,
        372, 14, 64, 1.404943641532012, 0.0037767302191720753, "",
    ]
    path = tmp_path / "metadata.csv"
    pd.DataFrame([row], columns=META_COLUMNS).to_csv(path, index=False)
    return path


# ------------------------------------------------------------------
# 1. the capacity formula
# ------------------------------------------------------------------
def test_electrode_capacity_formula_matches_geometry_module():
    """Q = eps_am * L * A * c_max * F / 3600, on the published set."""
    import pybamm

    ref = pybamm.ParameterValues(REFERENCE_SET)
    q = electrode_capacity_Ah(ref)
    area = float(ref[KEY_HEIGHT]) * float(ref[KEY_WIDTH])
    expected = (
        float(ref[KEY_THICKNESS])
        * float(ref[KEY_EPS_AM])
        * area
        * float(ref[KEY_C_MAX])
        * 96485.33212
        / 3600.0
    )
    assert q == pytest.approx(expected, rel=1e-12)
    # the published set's OWN declared capacity is 30 % lower: recorded
    # as a finding, never silently reconciled
    assert q == pytest.approx(0.2024, abs=1e-3)
    assert float(ref[KEY_NOMINAL_Q]) == pytest.approx(0.15625)
    assert q / float(ref[KEY_NOMINAL_Q]) == pytest.approx(1.295, abs=0.005)


def test_capacity_is_independent_of_declared_nominal():
    """The nominal key is bookkeeping: it must not enter the formula."""
    import pybamm

    pv = pybamm.ParameterValues(REFERENCE_SET)
    before = electrode_capacity_Ah(pv)
    pv[KEY_NOMINAL_Q] = 0.5
    assert electrode_capacity_Ah(pv) == pytest.approx(before, rel=1e-15)


def test_geometry_set_matches_its_declared_capacity():
    """Phase A.5 deliberately made declared == physical (ratio 1)."""
    import pybamm

    register_geometry()
    pv = pybamm.ParameterValues(GEOMETRY_PARAMETER_SET_ID)
    assert electrode_capacity_Ah(pv) == pytest.approx(
        float(pv[KEY_NOMINAL_Q]), rel=1e-9
    )
    assert electrode_capacity_Ah(pv) == pytest.approx(2.2017e-3, rel=1e-3)


# ------------------------------------------------------------------
# 2. Q_target provenance
# ------------------------------------------------------------------
def test_read_q_target_from_provenance(ocp_dir):
    t = read_q_target(ocp_dir)
    assert t["q_target_Ah"] == pytest.approx(Q_REF_AH, rel=1e-12)
    assert "measured charge" in t["source"]
    assert t["provenance_file"].endswith("ocp_extraction_provenance.json")
    assert "lithiation branch" in t["soc_definition"]


def test_read_q_target_override_and_validation(tmp_path):
    assert read_q_target(tmp_path, override_Ah=2.0e-3)["q_target_Ah"] == 2.0e-3
    with pytest.raises(ValueError):
        read_q_target(tmp_path, override_Ah=0.0)
    with pytest.raises(ValueError):
        read_q_target(tmp_path, override_Ah=float("nan"))
    with pytest.raises(FileNotFoundError):
        read_q_target(tmp_path)


# ------------------------------------------------------------------
# 3. the payload
# ------------------------------------------------------------------
def test_payload_scales_eps_am_by_the_capacity_ratio(ocp_dir, metadata_csv):
    p = capacity_payload("delithiation", "4ccc47", ocp_dir, metadata_csv)
    q_before = p["q_before_Ah"]
    q_target = p["q_target_Ah"]

    assert q_before == pytest.approx(2.2017e-3, rel=1e-3)
    assert q_target == pytest.approx(Q_REF_AH, rel=1e-12)
    assert p["scaling_factor"] == pytest.approx(q_target / q_before, rel=1e-12)
    assert p["scaling_factor"] == pytest.approx(0.8823, abs=2e-4)

    # Q_after equals the target by construction
    assert p["q_after_Ah"] == pytest.approx(q_target, rel=1e-12)
    assert p["q_after_relative_error"] < 1e-12

    # eps_am scaled 1:1 by that factor, nothing else
    assert p["changed_parameter"] == KEY_EPS_AM
    detail = {d["parameter"]: d for d in p["changed_parameters_detail"]}
    assert detail[KEY_EPS_AM]["after"] == pytest.approx(
        detail[KEY_EPS_AM]["before"] * p["scaling_factor"], rel=1e-12
    )
    assert detail[KEY_EPS_AM]["after"] == pytest.approx(0.23047, abs=5e-5)
    assert detail[KEY_EPS_AM]["relative_change_pct"] == pytest.approx(
        -11.77, abs=0.05
    )
    # the second entry is explicitly bookkeeping, not physics
    assert "bookkeeping" in detail[KEY_NOMINAL_Q]["role"]
    assert detail[KEY_NOMINAL_Q]["after"] == pytest.approx(q_target, rel=1e-12)


def test_payload_declares_frozen_parameters(ocp_dir, metadata_csv):
    p = capacity_payload("lithiation", "4ccc47", ocp_dir, metadata_csv)
    frozen = set(p["kept_unchanged"])
    assert KEY_OCP in frozen
    assert "Positive particle diffusivity [m2.s-1]" in frozen
    assert "Positive electrode exchange-current density [A.m-2]" in frozen
    assert "Lower voltage cut-off [V]" in frozen
    assert "Upper voltage cut-off [V]" in frozen
    assert KEY_EPS_AM not in frozen
    assert p["is_fitted_to_voltage"] is False
    assert "NOT validation" in p["wording"]
    assert "measured" in p["q_target_source"]["source"]


def test_payload_volume_balance_stays_feasible(ocp_dir, metadata_csv):
    p = capacity_payload("delithiation", "4ccc47", ocp_dir, metadata_csv)
    b = p["electrode_volume_balance"]
    assert b["feasible"] is True
    assert b["sum_after"] < b["sum_before"] < 1.0
    assert b["sum_after"] == pytest.approx(
        b["eps_am_after"] + b["porosity"], rel=1e-12
    )


def test_payload_reports_loading_equivalent(ocp_dir, metadata_csv):
    p = capacity_payload("delithiation", "4ccc47", ocp_dir, metadata_csv)
    ref = p["measured_structure_cross_reference"]
    assert ref["active_material_loading_g_cm2_after"] == pytest.approx(
        ref["active_material_loading_g_cm2_before"] * p["scaling_factor"],
        rel=1e-12,
    )
    # 3.7767 mg/cm2 coating x 90.984 % AM
    assert ref["active_material_loading_g_cm2_before"] == pytest.approx(
        3.436e-3, abs=2e-5
    )


def test_payload_rejects_unreachable_target(ocp_dir, metadata_csv):
    with pytest.raises(ValueError, match="outside"):
        capacity_payload("delithiation", "4ccc47", ocp_dir, metadata_csv,
                         q_target_Ah=1.0)
    with pytest.raises(ValueError, match="unknown variant"):
        capacity_payload("mean", "4ccc47", ocp_dir, metadata_csv)


def test_write_capacity_summary(ocp_dir, metadata_csv, tmp_path):
    path = write_capacity_summary(tmp_path / "out", "4ccc47", ocp_dir,
                                  metadata_csv)
    assert path.name == "capacity_override.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert {v["variant"] for v in payload["variants"]} == {
        "lithiation", "delithiation"
    }


# ------------------------------------------------------------------
# 4. the built parameter sets
# ------------------------------------------------------------------
@pytest.mark.parametrize("variant", ["lithiation", "delithiation"])
def test_build_changes_only_eps_am_and_nominal(ocp_dir, metadata_csv, variant):
    base, pv = build_capacity_matched_pair(variant, "4ccc47", ocp_dir,
                                           metadata_csv)
    changed = changed_keys_against(base, pv)
    assert changed == sorted([KEY_EPS_AM, KEY_NOMINAL_Q])

    # OCP / diffusivity / kinetics / window carried over by IDENTITY
    for key in (KEY_OCP, "Positive particle diffusivity [m2.s-1]",
                "Positive electrode exchange-current density [A.m-2]",
                KEY_C_MAX, "Positive electrode porosity",
                "Positive particle radius [m]"):
        assert pv[key] is base[key], key

    # voltage window untouched (still the measured programme window)
    assert pv["Lower voltage cut-off [V]"] == MEASURED_LOWER_CUTOFF_V
    assert pv["Upper voltage cut-off [V]"] == MEASURED_UPPER_CUTOFF_V

    # geometry untouched
    assert pv[KEY_THICKNESS] == base[KEY_THICKNESS]
    assert pv[KEY_HEIGHT] == base[KEY_HEIGHT]
    assert pv[KEY_WIDTH] == base[KEY_WIDTH]


def test_built_set_has_the_target_capacity(ocp_dir, metadata_csv):
    pv = build_capacity_matched_variant("delithiation", "4ccc47", ocp_dir,
                                        metadata_csv)
    assert electrode_capacity_Ah(pv) == pytest.approx(Q_REF_AH, rel=1e-12)
    assert float(pv[KEY_NOMINAL_Q]) == pytest.approx(Q_REF_AH, rel=1e-12)


def test_register_and_resolve_by_name(ocp_dir, metadata_csv):
    import pybamm

    ids = register_capacity_variants("4ccc47", ocp_dir, metadata_csv)
    assert ids == CAPACITY_MATCHED_IDS
    for variant, set_id in ids.items():
        assert set_id in pybamm.parameter_sets
        resolved = pybamm.ParameterValues(set_id)
        assert electrode_capacity_Ah(resolved) == pytest.approx(
            Q_REF_AH, rel=1e-12
        )
        # and the base OCP set is untouched (never overwritten)
        base = pybamm.ParameterValues(BASE_OCP_IDS[variant])
        assert electrode_capacity_Ah(base) == pytest.approx(
            2.2017e-3, rel=1e-3
        )


def test_register_is_idempotent(ocp_dir, metadata_csv):
    import pybamm

    register_capacity_variants("4ccc47", ocp_dir, metadata_csv)
    register_capacity_variants("4ccc47", ocp_dir, metadata_csv)
    assert CAPACITY_MATCHED_IDS["delithiation"] in pybamm.parameter_sets
