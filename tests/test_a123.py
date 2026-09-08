# ============================================================
# Battery Dataset Simulation Platform v0.4
# CALCE A123 (LFP/graphite) chemistry-generalization tests (Step 35)
#
# Golden strategy identical to v0.3: lock STRUCTURAL invariants
# (source file, n_points, duration, current peaks, voltage
# start/end, integrated charge, selected segment) measured in
# the Step 28 audit, then lock the unfitted surrogate-baseline
# RMSE as a software regression reference.  No scientific
# RMSE acceptance line exists.
# ============================================================

import numpy as np
import pandas as pd
import pytest

from battery_sim.paths import ROOT
from battery_sim.registry import get_dataset, list_dataset_configs

GOLDEN_WINDOWS = {
    # (cell, protocol): structural golden from docs/v04_step28_a123_audit.md
    ("007", "DST"): {
        "source_step": 8, "n_points": 7368,
        "duration_s": pytest.approx(7387.4, abs=1.0),
        "voltage_start_V": pytest.approx(3.554, abs=0.02),
        "voltage_end_V": pytest.approx(1.999, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(1.93, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.036, abs=0.01),
        "temperature_median_C": pytest.approx(27.3, abs=0.5),
    },
    ("007", "FUDS"): {
        "source_step": 24, "n_points": 7372,
        "duration_s": pytest.approx(7400.1, abs=1.0),
        "voltage_start_V": pytest.approx(3.555, abs=0.02),
        "voltage_end_V": pytest.approx(1.938, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.06, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.036, abs=0.01),
        "temperature_median_C": pytest.approx(27.2, abs=0.5),
    },
    ("007", "US06"): {
        "source_step": 16, "n_points": 6957,
        "duration_s": pytest.approx(6980.4, abs=1.0),
        "voltage_start_V": pytest.approx(3.555, abs=0.02),
        "voltage_end_V": pytest.approx(2.000, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(0.83, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.033, abs=0.01),
        "temperature_median_C": pytest.approx(27.1, abs=0.5),
    },
    ("008", "DST"): {
        "source_step": 8, "n_points": 7441,
        "duration_s": pytest.approx(7460.7, abs=1.0),
        "voltage_start_V": pytest.approx(3.554, abs=0.02),
        "voltage_end_V": pytest.approx(2.000, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(1.92, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.044, abs=0.01),
        "temperature_median_C": pytest.approx(27.0, abs=0.5),
    },
    ("008", "FUDS"): {
        "source_step": 24, "n_points": 7579,
        "duration_s": pytest.approx(7605.7, abs=1.0),
        "voltage_start_V": pytest.approx(3.555, abs=0.02),
        "voltage_end_V": pytest.approx(1.999, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.06, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.057, abs=0.01),
        "temperature_median_C": pytest.approx(27.0, abs=0.5),
    },
    ("008", "US06"): {
        "source_step": 16, "n_points": 7161,
        "duration_s": pytest.approx(7184.0, abs=1.0),
        "voltage_start_V": pytest.approx(3.555, abs=0.02),
        "voltage_end_V": pytest.approx(1.999, abs=0.02),
        "current_peak_discharge_A": pytest.approx(3.85, abs=0.05),
        "current_peak_charge_A": pytest.approx(0.83, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.058, abs=0.01),
        "temperature_median_C": pytest.approx(26.9, abs=0.5),
    },
}


@pytest.fixture(scope="module")
def adapter():
    return get_dataset("calce_a123")


def test_a123_registry():
    ids = [c.dataset_id for c in list_dataset_configs()]
    assert "calce_a123" in ids

    cfg = next(
        c for c in list_dataset_configs() if c.dataset_id == "calce_a123"
    )
    assert cfg.adapter == "calce_a123"
    assert cfg.parameter_set == "Prada2013"
    assert cfg.chemistry == "LFP_Graphite"
    assert cfg.nominal_capacity_Ah == pytest.approx(1.1)
    assert cfg.cells == ["007", "008"]

    meta = get_dataset("calce_a123").get_metadata()
    pm = meta["parameter_match"]
    # Step 30: B-grade surrogate, never exact, never fitted
    assert pm["grade"] == "B"
    assert pm["level"] == "compatible_surrogate"
    assert pm["parameter_set"] == "Prada2013"
    assert pm["fitted_to_dataset"] is False
    # v0.4 final temperature semantics: isothermal environment is
    # the pre-profile rest-end measured cell temperature; the
    # in-profile measured cell trace is a validation target only
    assert (
        meta["temperature_source"]
        == "assumed_from_preprofile_rest_cell_temperature"
    )


def test_a123_file_reading(adapter):
    df = adapter.load_raw("007")
    for col in ("time_s", "current_A", "voltage_V", "temperature_cell_C"):
        assert col in df.columns

    wdf = adapter.load_processed_discharge("007", "DST")
    # Step 19/31 canonical schema
    assert set(wdf.columns) == {
        "time_s", "current_A", "voltage_V", "capacity_Ah",
        "temperature_cell_C", "temperature_ambient_C",
    }


def test_a123_sign_conversion(adapter):
    """Arbin raw charge=+/discharge=- -> canonical discharge=+."""
    for (cell, proto), golden in GOLDEN_WINDOWS.items():
        df = adapter.load_processed_discharge(cell, proto)
        I = df["current_A"].to_numpy()
        assert I.max() > 0, (cell, proto)   # discharge present (+)
        assert I.min() < 0, (cell, proto)   # regen present (-)
        assert I.max() == golden["current_peak_discharge_A"]
        assert -I.min() == golden["current_peak_charge_A"]
        # net discharge dominates (run to 2.0 V cutoff)
        assert df["capacity_Ah"].iloc[-1] > 0.9


def test_a123_time_monotonic(adapter):
    for cell in ("007", "008"):
        for proto in ("DST", "FUDS", "US06"):
            df = adapter.load_processed_discharge(cell, proto)
            t = df["time_s"].to_numpy()
            assert np.all(np.diff(t) > 0), (cell, proto)
            assert np.isfinite(t).all()
            assert np.isfinite(df["current_A"]).all()
            assert np.isfinite(df["voltage_V"]).all()
            assert float(t[0]) == 0.0


def test_a123_protocol_list(adapter):
    assert adapter.list_protocols() == ["DST", "FUDS", "US06"]
    assert set(adapter.list_rates()) == {"DST", "FUDS", "US06"}
    for p in ("DST", "FUDS", "US06"):
        assert adapter.expand_protocol(p) == [p]
        info = adapter.rate_info(p)
        # dynamic windows have no single C-rate by construction
        assert np.isnan(info["c_rate"])
        assert info["protocol_id"] == p


def _check_window(adapter, cell, proto):
    golden = GOLDEN_WINDOWS[(cell, proto)]
    df = adapter.load_processed_discharge(cell, proto)
    prov = df.attrs["provenance"]

    assert prov["source_file"] == (
        f"A1-{cell}-DST-US06-FUDS-25-20120827.xlsx"
    )
    assert prov["profile_kind"] == "dynamic"
    assert prov["source_step"] == golden["source_step"]
    # Step 34: initial-state semantics (v0.3 freeze spec).  The
    # value is config-owned (highest audited SOC that does not sit
    # at the Prada2013 upper-cutoff event boundary).
    ist = prov["initial_state"]
    assert ist["type"] == "surrogate_ocv_mapped_soc"
    assert ist["value"] == pytest.approx(0.995)
    assert ist["history_replayed"] is False
    assert ist["is_exact_electrochemical_state"] is False
    assert df.attrs["initial_soc"] == pytest.approx(0.995)

    assert len(df) == golden["n_points"]
    assert df["time_s"].iloc[-1] == golden["duration_s"]
    assert df["voltage_V"].iloc[0] == golden["voltage_start_V"]
    assert df["voltage_V"].iloc[-1] == golden["voltage_end_V"]
    assert df["current_A"].max() == golden["current_peak_discharge_A"]
    assert -df["current_A"].min() == golden["current_peak_charge_A"]
    assert df["capacity_Ah"].iloc[-1] == golden["integrated_charge_Ah"]
    assert float(np.nanmedian(df["temperature_cell_C"])) == (
        golden["temperature_median_C"]
    )


def test_a123_dst(adapter):
    _check_window(adapter, "007", "DST")
    _check_window(adapter, "008", "DST")


def test_a123_fuds(adapter):
    _check_window(adapter, "007", "FUDS")
    _check_window(adapter, "008", "FUDS")


def test_a123_us06(adapter):
    _check_window(adapter, "007", "US06")
    _check_window(adapter, "008", "US06")


def test_a123_parameter_match():
    """Prada2013 must build with all three model classes (Step 30)."""
    pybamm = pytest.importorskip("pybamm")
    pv = pybamm.ParameterValues("Prada2013")
    assert pv["Lower voltage cut-off [V]"] == pytest.approx(2.0)
    assert pv["Upper voltage cut-off [V]"] == pytest.approx(3.6)
    for model in (
        pybamm.lithium_ion.SPM(),
        pybamm.lithium_ion.SPMe(),
        pybamm.lithium_ion.DFN(),
    ):
        pybamm.Simulation(model, parameter_values=pv)  # must not raise


@pytest.mark.skipif(
    not pytest.importorskip("pybamm", reason="pybamm not available"),
    reason="pybamm not available",
)
def test_a123_cli():
    """In-process CLI run: A123 enters the SAME baseline runner."""
    import run_pipeline

    rc = run_pipeline.main(
        [
            "--dataset", "calce_a123",
            "--mode", "baseline",
            "--model", "SPMe",
            "--cell", "007",
            "--protocol", "DST",
            "--no-plot",
        ]
    )
    assert rc == 0

    metrics = pd.read_csv(
        ROOT / "outputs" / "platform" / "calce_a123" / "baseline"
        / "SPME" / "cell007" / "metrics.csv"
    )
    row = metrics[metrics["protocol_id"] == "DST"].iloc[0]
    assert row["rate_slug"] == "DST"
    assert row["profile_kind"] == "dynamic"
    assert row["parameter_set"] == "Prada2013"

    # Step 24 metric family present (same evaluator)
    for col in (
        "rmse_time_aligned_mV", "residual_std_mV", "current_rms_A",
        "current_peak_discharge_A", "current_peak_charge_A",
    ):
        assert col in metrics.columns, col

    # Step 25/34 capacity + initial-state semantics
    assert (metrics["capacity_metric_type"] == "forced_current_window").all()
    assert (metrics["capacity_is_predictive"] == False).all()  # noqa: E712
    assert row["initial_state_type"] == "surrogate_ocv_mapped_soc"
    assert float(row["initial_state_value"]) == pytest.approx(0.995)
    assert row["initial_state_history_replayed"] in (False, "False")
    # v0.4 final temperature semantics reach the metrics row
    assert row["ambient_temperature_source"] == (
        "assumed_from_preprofile_rest_cell_temperature"
    )
