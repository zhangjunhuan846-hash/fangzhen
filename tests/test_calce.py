# ============================================================
# Battery Dataset Simulation Platform v0.2
# CALCE CS2 regression tests (Step 17)
#
# Golden locks (docs/calce_cs2_vertical_slice_provenance.md):
#   CS2_33: I = 0.5502 A, Q = 1.1602 Ah,
#           V 4.1187 -> 2.6997 V   (cycle1/step7, rules not locators)
#   CS2_35: I = 1.0997 A, Q = 1.1385 Ah
#   baseline RMSE(t): CS2_33 200.37 mV +-1, CS2_35 269.93 mV +-1
# ============================================================

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from battery_sim.datasets import calce_cs2 as calce_mod
from battery_sim.datasets.calce_cs2 import (
    CalceCs2Adapter,
    load_calce_file,
    _file_sort_key,
)
from battery_sim.rates import resolve_rate
from battery_sim.registry import get_dataset, list_datasets


# ------------------------------------------------------------------
# Fixtures (heavy xlsx parsing - cache per module)
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def adapter():
    return get_dataset("calce_cs2")


@pytest.fixture(scope="module")
def first_file_df(adapter):
    first = adapter.cell_files("33")[0]
    return load_calce_file(first)


@pytest.fixture(scope="module")
def seg33(adapter):
    df, prov = adapter._find_first_full_discharge("33", "0p5C")
    return df, prov


@pytest.fixture(scope="module")
def seg35(adapter):
    df, prov = adapter._find_first_full_discharge("35", "1C")
    return df, prov


# ------------------------------------------------------------------
# 1. Registry
# ------------------------------------------------------------------
def test_calce_registry():
    df = list_datasets()
    ids = set(df["ID"])
    assert "calce_cs2" in ids
    assert "chen2020" in ids

    cfg_adapter = get_dataset("calce_cs2")
    assert isinstance(cfg_adapter, CalceCs2Adapter)
    assert cfg_adapter.list_cells() == ["33", "35"]
    assert cfg_adapter.config.parameter_set == "Ramadass2004"
    assert cfg_adapter.config.chemistry == "LCO_Graphite"


# ------------------------------------------------------------------
# 2. File sorting (T3: filename order != chronological)
# ------------------------------------------------------------------
def test_calce_file_sorting(adapter):
    files = adapter.cell_files("33")
    names = [f.name for f in files]
    # the alphabetically-last file (9_7_10 = Sep 7) is chronologically FIRST
    assert names[0] == "CS2_33_8_17_10.xlsx"
    assert "CS2_33_9_7_10.xlsx" not in names[:1]

    keys = [_file_sort_key(f) for f in files]
    assert keys == sorted(keys)


# ------------------------------------------------------------------
# 3. Sign conversion (T1: CALCE charge=+ / discharge=- -> flip)
# ------------------------------------------------------------------
def test_calce_sign_conversion(first_file_df):
    # charge step (2): raw CALCE current is positive -> canonical negative
    charge = first_file_df[
        first_file_df["step_index"] == 2
    ]
    assert charge["current_A"].median() < 0

    # discharge step (7): raw CALCE current is negative -> canonical positive
    discharge = first_file_df[
        first_file_df["step_index"] == 7
    ]
    assert discharge["current_A"].median() > 0


# ------------------------------------------------------------------
# 4. Rule-based discharge detection (no hard-coded locator)
# ------------------------------------------------------------------
def test_calce_discharge_detection(adapter, seg33):
    df, prov = seg33

    # located inside the FIRST chronological file, via rules
    assert prov["source_file"] == "CS2_33_8_17_10.xlsx"
    assert prov["cycle_index"] == 1
    assert prov["step_index"] == 7

    # golden values
    assert prov["median_current_A"] == pytest.approx(0.5502, abs=1e-3)
    assert prov["voltage_start_V"] == pytest.approx(4.1187, abs=1e-3)
    assert prov["voltage_end_V"] == pytest.approx(2.6997, abs=1e-3)
    assert prov["n_points"] == 760

    # canonical trace is well-formed
    assert list(df.columns) >= ["time_s", "current_A", "voltage_V"]
    assert (np.diff(df["time_s"].to_numpy()) > 0).all()
    assert (df["current_A"] > 0.5).all()


# ------------------------------------------------------------------
# 5. Capacity integration (T2: Arbin cumulative column NOT used)
# ------------------------------------------------------------------
def test_calce_capacity_integration(seg33, seg35):
    df33, prov33 = seg33
    df35, prov35 = seg35

    assert float(df33["capacity_Ah"].iloc[-1]) == pytest.approx(
        1.1602, abs=1e-3
    )
    assert float(df35["capacity_Ah"].iloc[-1]) == pytest.approx(
        1.1385, abs=1e-3
    )
    assert prov35["median_current_A"] == pytest.approx(1.0997, abs=1e-3)

    # capacity starts at exactly zero (integrated, not cumulative col)
    assert df33["capacity_Ah"].iloc[0] == 0.0


# ------------------------------------------------------------------
# 6. Rate normalization (c_rate is the key; aliases resolve identically)
# ------------------------------------------------------------------
def test_calce_rate_normalization(adapter):
    # all four spellings must resolve to the same canonical quintuple
    variants = ["0p5C", "C2", "0.5", "C0p5"]
    infos = [adapter.rate_info(v) for v in variants]
    for info in infos:
        assert info["c_rate"] == 0.5
        assert info["rate_slug"] == "C0p5"
        assert info["rate_label"] == "C/2"

    # source provenance: every alias reports the CALCE source label
    for info in infos:
        assert info["source_rate"] == "0p5C"

    # 1C identical across datasets (numeric key)
    assert adapter.rate_info("1C")["c_rate"] == 1.0
    assert adapter.rate_info("1C")["rate_slug"] == "C1"

    # cross-dataset: Chen2020 legacy "C2" and CALCE "0p5C" are the
    # SAME C-rate
    chen = get_dataset("chen2020")
    assert chen.rate_info("C2")["c_rate"] == adapter.rate_info("0p5C")["c_rate"]

    # the two datasets land on the identical segment
    a = adapter.load_discharge("33", "C2")
    b = adapter.load_discharge("33", "0p5C")
    pd.testing.assert_frame_equal(a, b)


# ------------------------------------------------------------------
# 7. Temperature assumption (config-owned, no Python default)
# ------------------------------------------------------------------
def test_calce_temperature_assumption(adapter):
    assert adapter.get_ambient_temperature("33") == 25.0
    assert adapter._temperature_source == "assumed"
    assert adapter._temperature_confidence == "low"


def test_calce_temperature_missing_config_raises():
    """No Python-side default: a dataset config without the
    ambient_temperature block must raise, never assume 25 C."""
    from battery_sim.schemas import DatasetConfig

    cfg = DatasetConfig.from_dict(
        "calce_broken",
        {
            "name": "broken",
            "chemistry": "LCO_Graphite",
            "raw_dir": "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw",
            "adapter": "calce_cs2",
            "protocol": "calce_cs2",
            "parameter_set": "Ramadass2004",
            "cells": ["33"],
            "rates": ["0p5C"],
            "supported_models": ["SPMe"],
            "nominal_capacity_Ah": 1.1,
        },
    )
    with pytest.raises(ValueError, match="ambient temperature"):
        CalceCs2Adapter(cfg)


def test_calce_temperature_from_config_only():
    """Robustness path: changing the YAML block changes the
    assumption without touching Python (23 C robustness check)."""
    from battery_sim.schemas import DatasetConfig

    cfg = DatasetConfig.from_dict(
        "calce_robust",
        {
            "name": "robust",
            "chemistry": "LCO_Graphite",
            "raw_dir": "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw",
            "adapter": "calce_cs2",
            "protocol": "calce_cs2",
            "parameter_set": "Ramadass2004",
            "cells": ["33"],
            "rates": ["0p5C"],
            "supported_models": ["SPMe"],
            "nominal_capacity_Ah": 1.1,
            "ambient_temperature": {
                "value_C": 23.0,
                "source": "assumed",
                "confidence": "low",
            },
        },
    )
    ad = CalceCs2Adapter(cfg)
    assert ad.get_ambient_temperature("33") == 23.0


# ------------------------------------------------------------------
# 8. parameter_match metadata (B-grade surrogate, never "validation")
# ------------------------------------------------------------------
def test_calce_parameter_match(adapter):
    meta = adapter.get_metadata()
    pm = meta["parameter_match"]

    assert pm["level"] == "compatible_surrogate"
    assert pm["grade"] == "B"
    assert pm["parameter_set"] == "Ramadass2004"
    assert pm["fitted_to_dataset"] is False
    assert "NOT physics-model validation" in pm["notes"]
    # Ecker2015 must be documented as the C-grade mismatched comparator
    assert "Ecker2015" in pm["notes"]

    # chen2020 stays exact / A-grade
    chen = get_dataset("chen2020")
    cpm = chen.get_metadata()["parameter_match"]
    assert cpm["level"] == "exact"
    assert cpm["grade"] == "A"


# ------------------------------------------------------------------
# 9. Baseline CLI regression (canonical + source alias + golden RMSE)
# ------------------------------------------------------------------
def test_calce_baseline_cli(adapter, tmp_path, capsys):
    from run_pipeline import main

    # canonical legacy label --rate C2
    rc = main([
        "--dataset", "calce_cs2",
        "--mode", "baseline",
        "--model", "SPMe",
        "--cell", "33",
        "--rate", "C2",
        "--no-plot",
    ])
    assert rc == 0

    out33 = Path(adapter.__class__.__module__)  # noqa: F841 (clarity)
    metrics33 = pd.read_csv(
        "outputs/platform/calce_cs2/baseline/SPME/cell33/metrics.csv"
    )
    row = metrics33.iloc[0]

    # canonical schema columns
    assert row["rate"] == "C2"          # legacy compat column
    assert row["c_rate"] == 0.5
    assert row["rate_slug"] == "C0p5"
    assert row["source_rate"] == "0p5C"
    assert row["capacity_metric_type"] == "forced_current_window"
    assert row["capacity_is_predictive"] is False or str(
        row["capacity_is_predictive"]
    ) in ("False", "false")

    # golden RMSE (unfitted surrogate baseline)
    assert row["rmse_time_aligned_mV"] == pytest.approx(200.37, abs=1.0)

    # per-rate artifacts named by canonical slug
    out_dir = Path(
        "outputs/platform/calce_cs2/baseline/SPME/cell33"
    )
    assert (out_dir / "C0p5_time_aligned.csv").exists()

    # source alias must give the identical scientific row
    rc = main([
        "--dataset", "calce_cs2",
        "--mode", "baseline",
        "--model", "SPMe",
        "--cell", "33",
        "--rate", "0p5C",
        "--no-plot",
    ])
    assert rc == 0
    metrics33b = pd.read_csv(
        out_dir / "metrics.csv"
    ).drop(columns=["runtime_s"])
    metrics33a = metrics33.drop(columns=["runtime_s"])
    pd.testing.assert_frame_equal(metrics33a, metrics33b)


def test_calce_baseline_cli_cell35(adapter):
    from run_pipeline import main

    rc = main([
        "--dataset", "calce_cs2",
        "--mode", "baseline",
        "--model", "SPMe",
        "--cell", "35",
        "--rate", "1C",
        "--no-plot",
    ])
    assert rc == 0

    metrics35 = pd.read_csv(
        "outputs/platform/calce_cs2/baseline/SPME/cell35/metrics.csv"
    )
    row = metrics35.iloc[0]
    assert row["c_rate"] == 1.0
    assert row["rate_slug"] == "C1"
    assert row["rmse_time_aligned_mV"] == pytest.approx(269.93, abs=1.0)
