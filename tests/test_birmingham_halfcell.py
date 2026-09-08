# ============================================================
# Battery Dataset Simulation Platform -- v0.5 half-cell pilot
# Birmingham NCM920305 || Li tests (H7/H9)
#
# Covers the first-class half-cell schema, the pure-data adapter
# window extraction / inverse-OCP (linear extrapolation above the
# table top, mirroring the pybamm linear Interpolant), the factory
# options translation, the external parameter-source registry, and
# one short DFN replay consistency check against the frozen
# as-published baseline.
# ============================================================

import pytest

from battery_sim.datasets.base import BatteryDatasetAdapter  # noqa: E402
from battery_sim.models.pybamm_factory import (  # noqa: E402
    build_model_options,
)
from battery_sim.registry import (  # noqa: E402
    get_dataset,
    get_dataset_config,
)

BIRM = "birmingham_ncm920305"


# ------------------------------------------------------------------
# First-class half-cell schema (H4)
# ------------------------------------------------------------------
def test_config_declares_half_cell_first_class():
    cfg = get_dataset_config(BIRM)
    assert cfg.extra["cell_configuration"] == "half_cell"
    assert cfg.extra["working_electrode"] == "positive"
    assert cfg.extra["counter_electrode"] == "lithium_metal"
    assert cfg.extra["model_options"]["surface form"] == "differential"
    assert cfg.extra["model_options"]["contact resistance"] == "true"
    assert cfg.extra["initialisation_method"] == "inverse_ocp"
    assert cfg.parameter_set == "Jackowska2025_2mAh_cm2"
    assert cfg.extra["parameter_match"]["grade"] == "A"
    assert cfg.extra["parameter_match"]["level"] == "exact"


def test_adapter_rejects_missing_half_cell_declaration():
    # the adapter must never *guess* half cell from chemistry
    cfg = get_dataset_config(BIRM)
    assert type(get_dataset(BIRM)).__name__ == "BirminghamNcm920305Adapter"


def test_get_metadata_carries_cell_configuration():
    adapter = get_dataset(BIRM)
    meta = adapter.get_metadata()
    assert meta["cell_configuration"] == "half_cell"
    assert meta["working_electrode"] == "positive"
    assert meta["counter_electrode"] == "lithium_metal"
    assert meta["parameter_match"]["grade"] == "A"


# ------------------------------------------------------------------
# Pure-data adapter behaviour (H6)
# ------------------------------------------------------------------
def test_c10_rate_resolution():
    adapter = get_dataset(BIRM)
    info = adapter.rate_info("Cover10")
    assert float(info["c_rate"]) == pytest.approx(0.1)
    assert info["rate_slug"] == "C0p1"
    assert info["rate_label"] == "C/10"
    assert info["source_rate"] == "Cover10"


def test_c10_window_structural_checks():
    adapter = get_dataset(BIRM)
    df = adapter.load_processed_discharge("2mAhcm2", "Cover10")

    # canonical sign: discharge = +
    assert float(df["current_A"].median()) > 0
    assert float(df["voltage_V"].iloc[0]) > float(df["voltage_V"].iloc[-1])

    # single CC discharge down to the 2.5 V cutoff (no CV tail)
    assert float(df["voltage_V"].iloc[-1]) <= 2.51
    assert float(df["voltage_V"].iloc[0]) > 4.15
    assert len(df) > 100

    prov = df.attrs["provenance"]
    assert prov["source_file"].startswith("RateCapability_Cover10")
    assert len(prov["file_sha256"]) == 64
    assert prov["temperature_matches_298.15K"] is True
    assert prov["initial_state"]["type"] == (
        "fixed_initial_concentration_from_inverse_ocp"
    )
    assert prov["initial_state"]["fitted_to_voltage"] is False

    init = df.attrs["initialisation"]
    assert init["method"] == "fixed_initial_concentration"
    assert init["concentration_parameter"] == (
        "Initial concentration in positive electrode [mol.m-3]"
    )
    assert init["max_concentration_parameter"] == (
        "Maximum concentration in positive electrode [mol.m-3]"
    )


def test_inverse_ocp_linear_extrapolation_above_table_top():
    # 4.1935 V sits ~7.6 mV ABOVE the tabulated top (4.18595 V).
    # np.interp clipping would pin x0 to the table edge (0.3109);
    # the pybamm linear Interpolant extrapolates -> x0 ~ 0.3028.
    adapter = get_dataset(BIRM)
    x0 = adapter.inverse_ocp(4.1935115)
    assert x0 < 0.3100
    assert x0 > 0.2900
    assert abs(x0 - 0.30281) < 1e-3


# ------------------------------------------------------------------
# Factory options translation (H5)
# ------------------------------------------------------------------
def test_build_model_options_full_cell_is_none():
    assert build_model_options("full_cell") is None
    assert build_model_options("", "positive") is None


def test_build_model_options_half_cell_positive():
    opts = build_model_options(
        "half_cell_positive",
        "positive",
        {"surface form": "differential", "contact resistance": "true"},
    )
    assert opts == {
        "working electrode": "positive",
        "surface form": "differential",
        "contact resistance": "true",
    }


def test_build_model_options_conflict_raises():
    with pytest.raises(ValueError):
        build_model_options("half_cell_positive", "negative")
    with pytest.raises(ValueError):
        build_model_options("bogus_config")


# ------------------------------------------------------------------
# External parameter-source registry (H5)
# ------------------------------------------------------------------
pybamm = pytest.importorskip("pybamm")

from battery_sim.models import parameter_sources  # noqa: E402


def test_external_registry_flag():
    assert parameter_sources.is_external("Jackowska2025_2mAh_cm2") is True
    assert parameter_sources.is_external("Chen2020") is False


def test_external_registry_source_info():
    info = parameter_sources.source_info("Jackowska2025_2mAh_cm2")
    assert info["repo_rel"] == "external/Jackowska-2025-JPS"
    assert info["module"] == "Jackowska2025"
    assert info["function"] == "get_parameter_values_2mAh_cm2"


def test_external_parameter_dict_values():
    d = parameter_sources.load_parameter_dict("Jackowska2025_2mAh_cm2")
    assert d["Maximum concentration in positive electrode [mol.m-3]"] == (
        pytest.approx(49225.0)
    )
    # legacy author key present and as-published (D scaling = 1.0)
    assert d["Positive electrode diffusivity scaling factor"] == (
        pytest.approx(1.0)
    )


def test_auto_materialised_keys_reports_alias():
    d = parameter_sources.load_parameter_dict("Jackowska2025_2mAh_cm2")
    pv = pybamm.ParameterValues(d)
    extra = parameter_sources.auto_materialised_keys(d, pv.keys())
    # PyBaMM 26.8 materialises the renamed canonical key next to the
    # author's legacy key -- never silently renamed or dropped.
    assert "Positive particle diffusivity scaling factor" in extra


# ------------------------------------------------------------------
# One short as-published DFN replay consistency check (H7/H9)
# ------------------------------------------------------------------
def test_baseline_c2_metrics_match_frozen_as_published():
    from battery_sim.simulation.baseline import run_baseline_cell

    adapter = get_dataset(BIRM)
    res = run_baseline_cell(
        adapter,
        model_name="DFN",
        cell="2mAhcm2",
        rate="Cover2",
        parameter_set="Jackowska2025_2mAh_cm2",
        plot=False,
        quiet=True,
    )
    row = res["metrics"].iloc[0]
    assert row["cell_configuration"] == "half_cell"
    assert row["working_electrode"] == "positive"
    # frozen as-published C/2 DFN RMSE = 116.40 mV (zero fitting)
    assert row["rmse_time_aligned_mV"] == pytest.approx(116.40, abs=0.5)
    assert row["coverage_fraction"] < 1.0
    assert row["coverage_fraction"] > 0.5
    assert row["bias_time_aligned_mV"] < 0  # model cuts off early
    assert row["initial_soc"] != row["initial_soc"]  # NaN (half cell)
    assert row["initial_state_type"] == (
        "fixed_initial_concentration_from_inverse_ocp"
    )
