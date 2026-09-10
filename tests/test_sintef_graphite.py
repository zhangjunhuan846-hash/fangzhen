# ============================================================
# Phase A (graphite line): SINTEF graphite R2032 adapter tests
#
# Hermetic: every test builds its own tiny synthetic parquet /
# metadata fixture in ``tmp_path`` so the suite never needs the
# real 13 GB data directory.  One test additionally exercises the
# real datasets.yaml entry and the vendored OCP table.
# ============================================================

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from battery_sim.datasets.sintef_graphite import (
    COL_CAPACITY,
    COL_CURRENT,
    COL_CYCLE,
    COL_STEP,
    COL_TIME,
    COL_UNIX,
    COL_VOLTAGE,
    SintefGraphiteAdapter,
)
from battery_sim.paths import ROOT
from battery_sim.registry import get_dataset, get_dataset_config
from battery_sim.schemas import DatasetConfig

SINTEF = "sintef_graphite"

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
OCP_FILE_REL = "external/pybamm-input-data/graphite_ocp_Ecker2015.csv"


def _write_parquet(path, cycles=1, include_delithiation=True):
    """Tiny SINTEF-shaped p-OCV file (10 s sampling, 4 steps/cycle)."""
    frames = []
    step = 0
    for cyc in range(1, cycles + 1):
        # step 1 (cycle 1 only, as in the real file): initial rest,
        # fresh cell ~2.97 V = ABOVE the reference graphite OCP table
        # top, which exercises the table-edge fallback for the
        # lithiation branch
        if cyc == 1:
            step += 1
            n = 20
            t0 = 0.0
            frames.append(pd.DataFrame({
                COL_TIME: t0 + np.arange(n) * 10.0,
                COL_UNIX: 1.7e9 + t0 + np.arange(n) * 10.0,
                COL_CURRENT: np.zeros(n),
                COL_VOLTAGE: np.linspace(2.73, 2.97, n),
                COL_CYCLE: cyc,
                COL_STEP: 1,
                COL_CAPACITY: np.zeros(n),
            }))
        # step 2: lithiation (negative current), 3.0 V -> 0.01 V
        step += 1
        n = 20
        t0 = len(frames) * 1000.0
        frames.append(pd.DataFrame({
            COL_TIME: t0 + np.arange(n) * 10.0,
            COL_UNIX: 1.7e9 + t0 + np.arange(n) * 10.0,
            COL_CURRENT: np.full(n, -4.3e-5),
            COL_VOLTAGE: np.linspace(3.0, 0.01, n),
            COL_CYCLE: cyc,
            COL_STEP: 2,
            COL_CAPACITY: np.linspace(0.0, 0.0019, n),
        }))
        # step 3: rest, 8 h at 10 s (only 40 points here) -> OCV 0.082 V
        step += 1
        n = 40
        t0 = frames[-1][COL_TIME].iloc[-1] + 10.0
        frames.append(pd.DataFrame({
            COL_TIME: t0 + np.arange(n) * 10.0,
            COL_UNIX: 1.7e9 + t0 + np.arange(n) * 10.0,
            COL_CURRENT: np.zeros(n),
            COL_VOLTAGE: np.linspace(0.023, 0.082, n),
            COL_CYCLE: cyc,
            COL_STEP: 3,
            COL_CAPACITY: np.full(n, 0.0019),
        }))
        # step 4: delithiation (positive current), 0.097 V -> 1.0 V
        step += 1
        if include_delithiation:
            n = 50
            t0 = frames[-1][COL_TIME].iloc[-1] + 10.0
            frames.append(pd.DataFrame({
                COL_TIME: t0 + np.arange(n) * 10.0,
                COL_UNIX: 1.7e9 + t0 + np.arange(n) * 10.0,
                COL_CURRENT: np.full(n, 4.33e-5),
                COL_VOLTAGE: np.linspace(0.0967, 1.0, n),
                COL_CYCLE: cyc,
                COL_STEP: 4,
                COL_CAPACITY: np.linspace(0.0, 0.00179, n),
            }))
        # step 5: rest
        step += 1
        n = 20
        t0 = frames[-1][COL_TIME].iloc[-1] + 10.0
        frames.append(pd.DataFrame({
            COL_TIME: t0 + np.arange(n) * 10.0,
            COL_UNIX: 1.7e9 + t0 + np.arange(n) * 10.0,
            COL_CURRENT: np.zeros(n),
            COL_VOLTAGE: np.linspace(1.0, 0.65, n),
            COL_CYCLE: cyc,
            COL_STEP: 5,
            COL_CAPACITY: np.full(n, 0.00179),
        }))
    df = pd.concat(frames, ignore_index=True)
    table = pa.table({c: pa.array(df[c]) for c in df.columns})
    pq.write_table(table, path)


META_COLUMNS = [
    "BDF names",
    "Active Material type",
    "Start Date YYYYMMDD",
    "Public Labels",
    "Cycling Programme name",
    "Mass of Active Material / mg",
    "Electrode Coating Mass / g",
    "Weight percentage of Active Material / %",
    "Theoretical Capacity /  mAh g-1",
    "Electrode Diameter / cm",
    "Dry Thickness / um",
    "Nominal Areal Capacity / mAh cm-2",
    "Electrode Loading / g cm-2",
    "Known Issues",
]


def _write_metadata(path, cell="4ccc47"):
    row = [
        f"sintef__sintef-graphite-R2032-intelligent-{cell}__20250514__p-ocv__RT.bdf.parquet",
        "Graphite", 20250514, "Gr-AQ-1", "p-OCV",
        5.816164537524997, 0.006392499999999995, 90.98419274124022,
        372, 14, 64, 1.404943641532012, 0.0037767302191720753, "",
    ]
    pd.DataFrame([row], columns=META_COLUMNS).to_csv(path, index=False)


def make_config(tmp_path, cell="4ccc47", **extra_overrides):
    """DatasetConfig pointed at a synthetic raw dir."""
    _write_parquet(
        tmp_path
        / f"sintef__sintef-graphite-R2032-intelligent-{cell}__20250514__p-ocv__RT.bdf.parquet"
    )
    _write_metadata(tmp_path / "metadata.csv", cell=cell)

    extra = {
        "cell_configuration": "half_cell",
        "working_electrode": "positive",
        "physical_working_electrode": "graphite_negative",
        "counter_electrode": "lithium_metal",
        "window_cycle": 1,
        "max_points": 20000,
        "initialisation_ocp_file_rel": OCP_FILE_REL,
        "metadata_csv_rel": str(tmp_path / "metadata.csv"),
        "rates_meta": {
            "pOCV-deli": {
                "programme": "p-ocv",
                "branch": "delithiation",
                "c_rate": 0.02,
                "rate_label": "C/50 (p-OCV delithiation)",
                "rate_slug": "pOCVdeli",
                "legacy_rate": "pOCVdeli",
            },
            "pOCV-lith": {
                "programme": "p-ocv",
                "branch": "lithiation",
                "c_rate": 0.02,
                "rate_label": "C/50 (p-OCV lithiation)",
                "rate_slug": "pOCVlith",
                "legacy_rate": "pOCVlith",
            },
        },
        "ambient_temperature": {
            "value_C": 25.0,
            "source": "declared_room_temperature_not_measured",
            "confidence": "low",
            "note": "declared",
        },
        "parameter_match": {"grade": "B"},
    }
    extra.update(extra_overrides)

    raw = {
        "name": "synthetic SINTEF graphite",
        "chemistry": "Graphite_LiMetal",
        "raw_dir": str(tmp_path),
        "adapter": "sintef_graphite",
        "protocol": "sintef_graphite_pocv",
        "parameter_set": "Ecker2015_graphite_halfcell",
        "cells": [cell],
        "rates": ["pOCV-deli", "pOCV-lith"],
        "supported_models": ["SPM", "SPMe", "DFN"],
        "nominal_capacity_Ah": 0.002162,
        "lower_voltage_cutoff_V": 0.01,
        "upper_voltage_cutoff_V": 1.0,
    }
    raw.update(extra)
    return DatasetConfig.from_dict(SINTEF, raw)


# ------------------------------------------------------------------
# Declarative entry (real datasets.yaml)
# ------------------------------------------------------------------
def test_dataset_entry_declares_half_cell_and_slot_convention():
    cfg = get_dataset_config(SINTEF)
    extra = cfg.extra
    assert extra["cell_configuration"] == "half_cell"
    # PyBaMM SLOT (the set stores graphite in the positive slots)
    assert extra["working_electrode"] == "positive"
    assert extra["physical_working_electrode"] == "graphite_negative"
    assert extra["counter_electrode"] == "lithium_metal"
    assert cfg.parameter_set == "Ecker2015_graphite_halfcell"
    assert extra["ambient_temperature"]["source"] == (
        "declared_room_temperature_not_measured"
    )
    assert extra["rates_meta"]["pOCV-deli"]["branch"] == "delithiation"
    assert extra["rates_meta"]["pOCV-lith"]["branch"] == "lithiation"


# ------------------------------------------------------------------
# Vendored OCP table
# ------------------------------------------------------------------
def test_vendored_ocp_table_is_usable():
    cfg = get_dataset_config(SINTEF)
    ocp = ROOT / cfg.extra["initialisation_ocp_file_rel"]
    assert ocp.is_file(), f"vendored OCP table missing: {ocp}"
    df = pd.read_csv(ocp, header=None, names=["sto", "V"])
    assert len(df) > 20
    assert df["sto"].is_monotonic_increasing
    # x=0 delithiated (high V), x=1 lithiated (low V)
    assert df["V"].iloc[0] > df["V"].iloc[-1]
    # monotone decreasing voltage in stoichiometry -> inversion is unique
    assert df["V"].is_monotonic_decreasing


def test_inverse_ocp_reproduces_measured_rest_ocv(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    x0 = adapter.inverse_ocp(0.082)
    assert 0.90 < x0 <= 1.0
    # forward check: interpolating at x0 returns the input voltage
    sto, vv = adapter._load_ocp_curve()
    order = np.argsort(sto)
    assert abs(float(np.interp(x0, sto[order], vv[order])) - 0.082) < 0.005


def test_inverse_ocp_rejects_far_out_of_range(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    with pytest.raises(ValueError, match="outside the graphite OCP"):
        adapter.inverse_ocp(3.0)


# ------------------------------------------------------------------
# Window extraction + canonical contract
# ------------------------------------------------------------------
def test_load_processed_discharge_contract(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    df = adapter.load_processed_discharge("4ccc47", "pOCV-deli")

    for col in ("time_s", "current_A", "voltage_V", "capacity_Ah",
                "temperature_ambient_C"):
        assert col in df.columns

    # relative time starts at 0 and is strictly increasing
    assert float(df["time_s"].iloc[0]) == 0.0
    assert np.all(np.diff(df["time_s"].to_numpy(float)) > 0)

    # platform canonical sign: the DELITHIATION branch is a
    # CHARGE-direction window -> negative current
    branch = df[df["current_A"] < 0]
    rest = df[df["current_A"] == 0]
    assert len(branch) > 10
    assert len(rest) > 0
    assert float(np.median(branch["current_A"])) < 0

    # capacity: zero over the rest, negative (charge) over the branch
    assert float(df["capacity_Ah"].iloc[0]) == 0.0
    assert float(df["capacity_Ah"].iloc[-1]) < 0

    # voltage rises across the branch
    assert float(branch["voltage_V"].iloc[-1]) - float(
        branch["voltage_V"].iloc[0]
    ) > 0.5


def test_lithiation_branch_is_canonical_discharge(tmp_path):
    """The lithiation window is the cell's own discharge (canonical +)."""
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    df = adapter.load_processed_discharge("4ccc47", "pOCV-lith")

    branch = df[df["current_A"] > 0]
    assert len(branch) > 10
    assert float(np.median(branch["current_A"])) > 0
    assert float(df["capacity_Ah"].iloc[-1]) > 0
    # lithiation lowers the graphite potential
    assert float(branch["voltage_V"].iloc[-1]) < float(
        branch["voltage_V"].iloc[0]
    )
    assert abs(float(branch["voltage_V"].iloc[-1]) - 0.01) < 0.05


def test_provenance_records_sign_units_and_full_hash(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    df = adapter.load_processed_discharge("4ccc47", "pOCV-deli")
    prov = df.attrs["provenance"]

    # raw cycler sign = discharge (negative) -> flipped to canonical
    assert prov["sign_convention"]["action"] == "raw sign FLIPPED to canonical"
    assert "DISCHARGE" in prov["sign_convention"]["raw"]
    assert "lithiation" in prov["sign_convention"]["verified_from_data"]
    assert prov["ambient_temperature_source"] == (
        "declared_room_temperature_not_measured"
    )
    # full-file sha256, not a sample hash
    assert len(prov["source_file_sha256"]) == 64
    assert prov["source_file"].endswith("__p-ocv__RT.bdf.parquet")
    assert prov["branch"] == "delithiation"
    # unit conversion is documented field by field
    assert set(prov["unit_conversion"]) == {
        "time_s", "current_A", "voltage_V", "capacity_Ah", "temperature"
    }
    # measured electrode structure travels with the window
    # (the catalog column is LABELLED cm but holds MILLIMETRES)
    assert prov["measured_structure"]["electrode_diameter_mm"] == 14.0
    assert abs(prov["measured_structure"]["electrode_area_cm2"] - 1.5394) < 0.001
    assert prov["measured_structure"]["nominal_cell_capacity_mAh"] > 2.0


def test_initialisation_block_matches_half_cell_slot(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    df = adapter.load_processed_discharge("4ccc47", "pOCV-deli")
    init = df.attrs["initialisation"]

    # baseline.py only supports these two methods
    assert init["method"] == "fixed_initial_concentration"
    # the parameter set stores graphite in the POSITIVE slots
    assert init["concentration_parameter"] == (
        "Initial concentration in positive electrode [mol.m-3]"
    )
    assert init["max_concentration_parameter"] == (
        "Maximum concentration in positive electrode [mol.m-3]"
    )
    assert 0.0 < float(init["stoichiometry_from_ocp"]) <= 1.0
    assert abs(float(init["ocp_voltage_V"]) - 0.082) < 0.01


def test_rate_table_resolves_aliases(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    for alias in ("pOCV-deli", "pOCVdeli", 0.02, "0.02"):
        info = adapter.rate_info(alias)
        assert info["rate_slug"] == "pOCVdeli"
        assert abs(float(info["c_rate"]) - 0.02) < 1e-9
    assert adapter.list_rate_slugs() == ["pOCVdeli", "pOCVlith"]
    with pytest.raises(ValueError, match="Unknown rate"):
        adapter.rate_info("GITT")  # Phase B, not declared in Phase A


def test_decimation_bounds_memory(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path, max_points=50))
    df = adapter.load_processed_discharge("4ccc47", "pOCV-deli")
    # 60 s rest tail + 50-point branch, capped by max_points
    assert len(df) <= 50 + 5
    assert df.attrs["provenance"]["decimation_stride"] > 1
    assert df.attrs["provenance"]["n_raw_rows_in_window"] > len(df)


# ------------------------------------------------------------------
# Fail-loud behaviour
# ------------------------------------------------------------------
def test_missing_delithiation_step_raises(tmp_path):
    cfg = make_config(tmp_path)
    _write_parquet(
        tmp_path
        / "sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__p-ocv__RT.bdf.parquet",
        include_delithiation=False,
    )
    adapter = SintefGraphiteAdapter(cfg)
    with pytest.raises(ValueError, match="no delithiation"):
        adapter.load_processed_discharge("4ccc47", "pOCV-deli")


def test_unknown_cell_raises(tmp_path):
    adapter = SintefGraphiteAdapter(make_config(tmp_path))
    with pytest.raises(ValueError, match="unknown cell"):
        adapter.load_processed_discharge("deadbeef", "pOCV-deli")


def test_adapter_rejects_negative_slot_declaration(tmp_path):
    """working_electrode must be the PyBaMM slot holding graphite."""
    cfg = make_config(tmp_path, working_electrode="negative")
    with pytest.raises(ValueError, match="must be\\s+'positive'"):
        SintefGraphiteAdapter(cfg)


def test_adapter_rejects_declared_temperature_without_source(tmp_path):
    cfg = make_config(
        tmp_path,
        ambient_temperature={"value_C": 25.0},
    )
    with pytest.raises(ValueError, match="ambient_temperature"):
        SintefGraphiteAdapter(cfg)


def test_adapter_rejects_non_delithiation_branch(tmp_path):
    cfg = make_config(
        tmp_path,
        rates_meta={
            "weird": {
                "programme": "p-ocv",
                "branch": "sideways",
                "c_rate": 0.02,
                "rate_label": "x",
                "rate_slug": "weird",
                "legacy_rate": "weird",
            }
        },
    )
    with pytest.raises(ValueError, match="lithiation.*or.*delithiation"):
        SintefGraphiteAdapter(cfg)


def test_missing_ocp_file_raises(tmp_path):
    cfg = make_config(tmp_path, initialisation_ocp_file_rel="external/nope.csv")
    with pytest.raises(FileNotFoundError, match="OCP file not found"):
        SintefGraphiteAdapter(cfg)


# ------------------------------------------------------------------
# Registry + real data (skipped when the raw files are absent)
# ------------------------------------------------------------------
def test_registry_resolves_sintef_adapter():
    cfg = get_dataset_config(SINTEF)
    if not (ROOT / cfg.raw_dir).is_dir():
        pytest.skip("SINTEF raw dir not present")
    adapter = get_dataset(SINTEF)
    assert isinstance(adapter, SintefGraphiteAdapter)
    assert adapter.get_metadata()["chemistry"] == "Graphite_LiMetal"


def test_real_pocv_file_window():
    cfg = get_dataset_config(SINTEF)
    raw_dir = ROOT / cfg.raw_dir
    if not any(raw_dir.glob("*4ccc47*p-ocv*.parquet")):
        pytest.skip("SINTEF p-OCV parquet not present")
    adapter = SintefGraphiteAdapter(cfg)
    df = adapter.load_processed_discharge("4ccc47", "pOCV-deli")
    prov = df.attrs["provenance"]

    # audited facts (docs/graphite_dataset_triage.md)
    assert prov["window_cycle"] == 1
    assert prov["rest_step"] == 3
    assert prov["branch_step"] == 4
    assert 0.07 < prov["rest_ocv_V"] < 0.10
    assert 0.90 < prov["initial_stoichiometry_from_ocp"] <= 1.0
    assert abs(prov["voltage_end_V"] - 1.0) < 0.05
    # raw per-step column vs canonical (flipped) integral
    assert 1.7e-3 < prov["branch_charge_raw_column_Ah"] < 1.9e-3
    assert -1.9e-3 < prov["branch_charge_canonical_Ah"] < -1.7e-3
