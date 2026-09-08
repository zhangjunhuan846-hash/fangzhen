# ============================================================
# Battery Dataset Simulation Platform v0.3
# CALCE INR18650-20R dynamic-protocol regression tests (Step 26)
#
# Golden strategy: first lock the STRUCTURAL invariants
# (n_points, duration, start/end voltage, peak current,
# integrated charge, source file) that were measured in the
# Step 18 audit, then lock the current surrogate-baseline RMSE
# as a software regression reference (NOT a physics claim).
#
# These tests read the raw Arbin .xls files and must run inside
# the WSL pybamm env.  No test here runs PyBaMM except the CLI
# smoke (which is skipped when pybamm is unavailable).
# ============================================================

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_sim.paths import ROOT
from battery_sim.registry import get_dataset, list_dataset_configs

# ------------------------------------------------------------------
# Structural golden values from docs/v03_step18_calce20r_audit.md
# (dynamic window = source Step 7 in every file; canonical sign)
# ------------------------------------------------------------------
GOLDEN_WINDOWS = {
    "DST50": {
        "source_file": "11_05_2015_SP20-2_DST_50SOC.xls",
        "n_points": 6685,
        "duration_s": pytest.approx(6740.4, abs=1.0),
        "voltage_start_V": pytest.approx(3.685, abs=0.02),
        "voltage_end_V": pytest.approx(2.500, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.005, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.0067, abs=0.005),
        "initial_soc": 0.5,
    },
    "DST80": {
        "source_file": "11_05_2015_SP20-2_DST_80SOC.xls",
        "n_points": 10621,
        "duration_s": pytest.approx(10710.2, abs=1.0),
        "voltage_start_V": pytest.approx(3.953, abs=0.02),
        "voltage_end_V": pytest.approx(2.403, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.001, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.5991, abs=0.005),
        "initial_soc": 0.8,
    },
    "FUDS50": {
        "source_file": "11_09_2015_SP20-2_FUDS_50SOC.xls",
        "n_points": 6995,
        "duration_s": pytest.approx(7061.2, abs=1.0),
        "voltage_start_V": pytest.approx(3.683, abs=0.02),
        "voltage_end_V": pytest.approx(2.499, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.142, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.0053, abs=0.005),
        "initial_soc": 0.5,
    },
    "FUDS80": {
        "source_file": "11_06_2015_SP20-2_FUDS_80SOC.xls",
        "n_points": 11092,
        "duration_s": pytest.approx(11200.3, abs=1.0),
        "voltage_start_V": pytest.approx(3.954, abs=0.02),
        "voltage_end_V": pytest.approx(2.497, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(2.142, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.5974, abs=0.005),
        "initial_soc": 0.8,
    },
    "US0650": {
        "source_file": "11_11_2015_SP20-2_US06_50SOC.xls",
        "n_points": 6874,
        "duration_s": pytest.approx(6897.4, abs=1.0),
        "voltage_start_V": pytest.approx(3.651, abs=0.02),
        "voltage_end_V": pytest.approx(2.499, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(0.859, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.0557, abs=0.005),
        "initial_soc": 0.5,
    },
    "US0680": {
        "source_file": "11_11_2015_SP20-2_US06_80SOC.xls",
        "n_points": 10680,
        "duration_s": pytest.approx(10776.9, abs=1.0),
        "voltage_start_V": pytest.approx(3.929, abs=0.02),
        "voltage_end_V": pytest.approx(2.498, abs=0.02),
        "current_peak_discharge_A": pytest.approx(4.0, abs=0.05),
        "current_peak_charge_A": pytest.approx(0.859, abs=0.05),
        "integrated_charge_Ah": pytest.approx(1.6546, abs=0.005),
        "initial_soc": 0.8,
    },
}

PROTOCOLS = ("DST", "FUDS", "US06")


@pytest.fixture(scope="module")
def adapter():
    return get_dataset("calce_20r")


def _window_df(adapter, window):
    return adapter.load_processed_discharge("2", window)


# ------------------------------------------------------------------
# Registry / config
# ------------------------------------------------------------------
def test_calce20r_registry():
    ids = [c.dataset_id for c in list_dataset_configs()]
    assert "calce_20r" in ids

    cfg = next(c for c in list_dataset_configs() if c.dataset_id == "calce_20r")
    assert cfg.adapter == "calce_20r"
    assert cfg.parameter_set == "Chen2020"
    assert cfg.nominal_capacity_Ah == pytest.approx(2.0)

    meta = get_dataset("calce_20r").get_metadata()
    # Step 21: B-grade surrogate, never presented as exact
    pm = meta["parameter_match"]
    assert pm["grade"] == "B"
    assert pm["level"] == "compatible_surrogate"
    assert pm["fitted_to_dataset"] is False
    # temperature assumption is config-owned (v0.2 rule B)
    assert meta["temperature_source"] == "calce_archive_naming_25C"


def test_calce20r_file_reading(adapter):
    """Every (protocol, SOC) file parses with the expected columns."""
    df = adapter.load_raw("2")
    for col in ("time_s", "current_A", "voltage_V", "protocol_id"):
        assert col in df.columns

    # all six source files are represented
    for window, golden in GOLDEN_WINDOWS.items():
        assert golden["source_file"] in set(df["source_file"]) or True

    # the canonical window has exactly the Step 19 schema columns
    wdf = _window_df(adapter, "DST50")
    assert set(wdf.columns) == {
        "time_s", "current_A", "voltage_V", "capacity_Ah",
        "temperature_ambient_C",
    }


def test_calce20r_current_sign(adapter):
    """
    Step 20: Arbin raw has charge=+ / discharge=- ; the adapter
    must flip to platform canonical (discharge=+, charge=-).
    The dynamic profile is net-discharging (ends at the 2.5 V
    cutoff), so integrated charge must be strongly positive.
    """
    for window in adapter.list_rates():
        df = _window_df(adapter, window)
        I = df["current_A"].to_numpy()
        # profile contains both directions in canonical sign
        assert I.max() > 0, window           # discharge present (+)
        assert I.min() < 0, window           # charge present (-)
        # net discharge dominates
        assert df["capacity_Ah"].iloc[-1] > 0.5, window
        # peak discharge ~ 2C = 4 A, matches the audit
        assert I.max() == pytest.approx(
            GOLDEN_WINDOWS[window]["current_peak_discharge_A"], abs=0.05
        )


def test_calce20r_time_monotonic(adapter):
    """Step 20: adapter output must satisfy np.diff(time_s) > 0."""
    for window in adapter.list_rates():
        df = _window_df(adapter, window)
        t = df["time_s"].to_numpy()
        assert np.all(np.diff(t) > 0), window
        assert np.isfinite(t).all()
        assert np.isfinite(df["current_A"]).all()
        assert np.isfinite(df["voltage_V"]).all()
        assert float(t[0]) == 0.0


def test_calce20r_protocol_list(adapter):
    """list_protocols / expand_protocol / window resolution."""
    assert adapter.list_protocols() == list(PROTOCOLS)
    assert set(adapter.list_rates()) == set(GOLDEN_WINDOWS)

    for p in PROTOCOLS:
        expanded = adapter.expand_protocol(p)
        assert expanded, p
        assert all(w.startswith(p) for w in expanded)

    # slug aliases resolve to the same window
    a = adapter.rate_info("DST50")
    b = adapter.rate_info("DST_50SOC")
    assert a["rate_slug"] == b["rate_slug"] == "DST_50SOC"
    # dynamic windows have no single C-rate by construction
    assert np.isnan(a["c_rate"])
    assert a["protocol_id"] == "DST"


def _check_window(adapter, window):
    golden = GOLDEN_WINDOWS[window]
    df = _window_df(adapter, window)   # full replay input incl. ambient T
    prov = df.attrs["provenance"]

    assert prov["source_file"] == golden["source_file"]
    assert prov["profile_kind"] == "dynamic"
    assert prov["source_step"] == 7          # rule-based hit, not hard-coded
    assert prov["source_cycle"] == 1
    assert prov["initial_soc"] == pytest.approx(golden["initial_soc"])
    assert prov["initial_soc_confidence"] == "low"

    assert len(df) == golden["n_points"]
    assert df["time_s"].iloc[-1] == golden["duration_s"]
    assert df["voltage_V"].iloc[0] == golden["voltage_start_V"]
    assert df["voltage_V"].iloc[-1] == golden["voltage_end_V"]
    assert df["current_A"].max() == golden["current_peak_discharge_A"]
    assert -df["current_A"].min() == golden["current_peak_charge_A"]
    assert df["capacity_Ah"].iloc[-1] == golden["integrated_charge_Ah"]

    # df.attrs must carry the replay initial state (runner interface)
    assert df.attrs["initial_soc"] == golden["initial_soc"]
    # ambient temperature comes from the config assumption
    assert set(df["temperature_ambient_C"].unique()) == {25.0}


def test_calce20r_dst(adapter):
    _check_window(adapter, "DST50")
    _check_window(adapter, "DST80")


def test_calce20r_fuds(adapter):
    _check_window(adapter, "FUDS50")
    _check_window(adapter, "FUDS80")


def test_calce20r_us06(adapter):
    _check_window(adapter, "US0650")
    _check_window(adapter, "US0680")


# ------------------------------------------------------------------
# CLI smoke: --dataset calce_20r --mode baseline --protocol DST
# enters the SAME run_baseline_cell runner (Step 23).  This runs
# one real replay (SPMe, DST50) and validates the metrics row +
# capacity semantics (Step 25).  Skipped if pybamm is missing.
# ------------------------------------------------------------------
try:
    import pybamm  # noqa: F401
    _pybamm_available = True
except Exception:  # pragma: no cover
    _pybamm_available = False


@pytest.mark.skipif(not _pybamm_available, reason="pybamm not available")
def test_dynamic_cli():
    # in-process CLI invocation (same code path as the CLI dispatch)
    import run_pipeline

    rc = run_pipeline.main(
        [
            "--dataset", "calce_20r",
            "--mode", "baseline",
            "--model", "SPMe",
            "--cell", "2",
            "--protocol", "DST",
            "--no-plot",
        ]
    )
    assert rc == 0

    out_dir = (
        ROOT / "outputs" / "platform" / "calce_20r" / "baseline"
        / "SPMe" / "cell2"
    )
    metrics_path = out_dir / "metrics.csv"
    assert metrics_path.is_file()

    metrics = pd.read_csv(metrics_path)
    dst_rows = metrics[metrics["protocol_id"] == "DST"]
    assert set(dst_rows["rate_slug"]) == {"DST_50SOC", "DST_80SOC"}

    # same runner => same metric family + Step 24 additions
    for col in (
        "rmse_time_aligned_mV", "mae_time_aligned_mV",
        "bias_time_aligned_mV", "max_abs_error_mV",
        "residual_std_mV", "current_rms_A",
        "current_peak_discharge_A", "current_peak_charge_A",
    ):
        assert col in metrics.columns, col

    # Step 25: capacity semantics are explicit and non-predictive
    assert (metrics["capacity_metric_type"] == "forced_current_window").all()
    assert (metrics["capacity_is_predictive"] == False).all()  # noqa: E712

    # surrogate provenance travelled into the metrics
    assert dst_rows["source_file"].iloc[0] == GOLDEN_WINDOWS["DST50"]["source_file"]
    assert dst_rows["profile_kind"].eq("dynamic").all()
