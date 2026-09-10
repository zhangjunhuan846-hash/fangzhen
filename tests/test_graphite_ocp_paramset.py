# ============================================================
# Phase B0 tests: derived parameter sets with the experiment-derived OCP
#
# Hermetic: synthetic OCP tables + synthetic catalog metadata.
# ============================================================

import numpy as np
import pandas as pd
import pytest

from parameters.sintef_graphite_geometry import REFERENCE_SET
from parameters.sintef_graphite_ocp import (
    KEY_LOWER_V,
    KEY_OCP,
    KEY_UPPER_V,
    MEASURED_LOWER_CUTOFF_V,
    MEASURED_UPPER_CUTOFF_V,
    KEPT_UNCHANGED_PHASE_B0,
    OCP_DELI_ID,
    OCP_LITH_ID,
    OCP_MEAN_ID,
    build_ocp_variant,
    load_ocp_tables,
    register_variants,
    variant_summary,
    write_variant_summaries,
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


@pytest.fixture()
def ocp_dir(tmp_path):
    """Synthetic extraction outputs (same schema as the real ones)."""
    d = tmp_path / "ocp"
    d.mkdir()

    soc = np.linspace(0.0, 1.0, 200)
    v_lith = 3.0 - 2.99 * soc ** 0.35          # 3.0 V -> 0.01 V
    pd.DataFrame({"SOC": soc, "Voltage": v_lith, "branch": "lithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, 4.33e-5),
                  "capacity_Ah": soc * 1.94e-3}).to_csv(
        d / "graphite_ocp_lithiation.csv", index=False)

    soc_d = np.linspace(0.9, 0.1, 200)
    v_deli = 0.10 + 0.9 * (1.0 - soc_d) ** 0.5  # 0.10 V @0.9 -> 0.95 V @0.1
    pd.DataFrame({"SOC": soc_d, "Voltage": v_deli, "branch": "delithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, -4.33e-5),
                  "capacity_Ah": (soc_d - 1.0) * 1.94e-3}).to_csv(
        d / "graphite_ocp_delithiation.csv", index=False)
    return d


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


def test_load_ocp_tables_sorted(ocp_dir):
    tables = load_ocp_tables(ocp_dir)
    assert set(tables) == {"lithiation", "delithiation"}
    for df in tables.values():
        assert df["SOC"].is_monotonic_increasing


def test_load_ocp_tables_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="OCP table not found"):
        load_ocp_tables(tmp_path)


def test_variant_summary_describes_ocp_and_keeps(ocp_dir, tmp_path):
    s = variant_summary("lithiation", "4ccc47", ocp_dir,
                        _metadata_csv(tmp_path))
    assert s["parameter_set_id"] == OCP_LITH_ID
    assert s["reference_parameter_set"] == REFERENCE_SET
    assert s["ocp_soc_range"] == pytest.approx([0.0, 1.0])
    assert s["ocp_voltage_range_V"][1] == pytest.approx(3.0, abs=0.05)
    # diffusivity must stay untouched in Phase B0 (GITT is a later phase)
    assert "Positive particle diffusivity [m2.s-1]" in s["kept_unchanged"]
    assert set(s["kept_unchanged"]) == set(KEPT_UNCHANGED_PHASE_B0)
    assert "PSEUDO-OCP" in s["wording"]
    assert "extrapolat" in s["ocp_extrapolation"]
    assert s["voltage_window_override"][KEY_UPPER_V] > 3.0


def test_variant_summary_delithiation_flags_narrow_range(ocp_dir, tmp_path):
    s = variant_summary("delithiation", "4ccc47", ocp_dir,
                        _metadata_csv(tmp_path))
    assert s["parameter_set_id"] == OCP_DELI_ID
    assert s["ocp_soc_range"][0] == pytest.approx(0.1, abs=0.05)
    assert s["ocp_soc_range"][1] == pytest.approx(0.9, abs=0.05)


def test_build_ocp_variant_replaces_only_ocp_and_geometry(ocp_dir, tmp_path):
    import pybamm

    ref = pybamm.ParameterValues(REFERENCE_SET)
    pv = build_ocp_variant("lithiation", "4ccc47", ocp_dir,
                           _metadata_csv(tmp_path))

    # OCP replaced (different callable object)
    assert pv[KEY_OCP] is not ref[KEY_OCP]
    # diffusivity / kinetics / c_max / porosity carried over as the same objects
    for key in KEPT_UNCHANGED_PHASE_B0:
        assert pv[key] is ref[key] or pv[key] == ref[key]
    # the measured voltage window replaces Ecker's own bounds, otherwise
    # the upper-voltage event fires at t=0 for a 3 V fresh state
    assert pv[KEY_LOWER_V] == pytest.approx(MEASURED_LOWER_CUTOFF_V)
    assert pv[KEY_UPPER_V] == pytest.approx(MEASURED_UPPER_CUTOFF_V)
    # geometry from Phase A.5 applied
    assert abs(pv["Positive electrode thickness [m]"] - 64e-6) < 1e-12
    assert abs(
        pv["Electrode height [m]"] * pv["Electrode width [m]"] - 1.5394e-4
    ) < 1e-7


def test_build_ocp_variant_mean_uses_overlap(ocp_dir, tmp_path):
    pv = build_ocp_variant("mean", "4ccc47", ocp_dir, _metadata_csv(tmp_path))
    assert pv[KEY_OCP] is not None
    s = variant_summary("mean", "4ccc47", ocp_dir, _metadata_csv(tmp_path))
    assert s["parameter_set_id"] == OCP_MEAN_ID
    # overlap of [0,1] and [0.1,0.9]
    assert s["ocp_soc_range"] == pytest.approx([0.1, 0.9], abs=0.02)
    assert "0.5 *" in s["ocp_source"]


def test_register_variants_resolvable_by_name(ocp_dir, tmp_path):
    ids = register_variants("4ccc47", ocp_dir, _metadata_csv(tmp_path))
    assert set(ids) == {"lithiation", "delithiation", "mean"}

    import pybamm

    for variant, set_id in ids.items():
        assert set_id in pybamm.parameter_sets, variant
        pv = pybamm.ParameterValues(set_id)
        assert abs(pv["Positive electrode thickness [m]"] - 64e-6) < 1e-12
    # the published reference set is still resolvable
    assert pybamm.ParameterValues(REFERENCE_SET)[KEY_OCP] is not None


def test_write_variant_summaries(ocp_dir, tmp_path):
    import json

    path = write_variant_summaries(ocp_dir, "4ccc47",
                                   _metadata_csv(tmp_path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["variants"]) == 3
    assert payload["reference_baseline"]["parameter_set_id"] == REFERENCE_SET


def test_unknown_variant_raises(ocp_dir, tmp_path):
    with pytest.raises(ValueError, match="unknown OCP variant"):
        build_ocp_variant("sideways", "4ccc47", ocp_dir,
                          _metadata_csv(tmp_path))
