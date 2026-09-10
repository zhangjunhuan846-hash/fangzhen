# ============================================================
# Phase B0 tests: OCP extraction from a canonical p-OCV record
#
# Hermetic: synthetic canonical records; one real-data check that
# skips when the SINTEF parquet is absent.
# ============================================================

import json

import numpy as np
import pandas as pd
import pytest

from extraction.ocp_extractor import (
    BRANCH_DELITHIATION,
    BRANCH_LITHIATION,
    OCP_CSV_FIELDS,
    extract_ocp_branches,
    write_ocp_csvs,
)
from battery_sim.paths import ROOT
from battery_sim.registry import get_dataset, get_dataset_config

SINTEF = "sintef_graphite"


def _canonical_record(n=60, q_ref_mAh=1.94, cycle=1):
    """One p-OCV cycle in canonical signs (+ = discharge = lithiation)."""
    frames = []
    t = 0.0

    def block(step, current_A, v0, v1, rows, dt=60.0):
        nonlocal t
        ts = t + np.arange(rows) * dt
        t = float(ts[-1]) + dt
        return pd.DataFrame({
            "time_s": ts,
            "current_A": np.full(rows, current_A),
            "voltage_V": np.linspace(v0, v1, rows),
            "cycle": cycle,
            "step": step,
        })

    frames.append(block(1, 0.0, 2.73, 2.97, 5))          # initial rest
    frames.append(block(2, +4.33e-5, 3.0, 0.01, n))      # lithiation (+)
    frames.append(block(3, 0.0, 0.023, 0.082, 5))        # rest
    frames.append(block(4, -4.33e-5, 0.0967, 1.0, n))    # delithiation (-)
    frames.append(block(5, 0.0, 1.0, 0.65, 5))           # rest
    return pd.concat(frames, ignore_index=True)


def test_extract_branches_soc_and_columns():
    res = extract_ocp_branches(_canonical_record(), cycle=1)
    lith, deli = res["lithiation"], res["delithiation"]

    for br in (lith, deli):
        assert list(br.columns) == OCP_CSV_FIELDS
        assert set(br["branch"]) == {br["branch"].iloc[0]}

    # SOC anchored at the fresh / fully-lithiated states
    assert abs(float(lith["SOC"].iloc[0])) < 1e-9
    assert abs(float(lith["SOC"].iloc[-1]) - 1.0) < 1e-9
    assert abs(float(deli["SOC"].iloc[0]) - 1.0) < 1e-9
    assert float(deli["SOC"].iloc[-1]) < 0.2

    # directions
    assert lith["Voltage"].iloc[-1] < lith["Voltage"].iloc[0]
    assert deli["Voltage"].iloc[-1] > deli["Voltage"].iloc[0]
    assert set(lith["branch"]) == {BRANCH_LITHIATION}
    assert set(deli["branch"]) == {BRANCH_DELITHIATION}


def test_extract_records_required_provenance():
    res = extract_ocp_branches(_canonical_record(), cycle=1)
    prov = res["provenance"]

    assert prov["equilibrium_warning"]
    assert "pseudo-OCP" in prov["equilibrium_warning"]
    assert prov["soc_reference_charge_Ah"] > 0
    assert prov["branch_steps"] == {"lithiation": 2, "delithiation": 4}
    # hand-over gap is recorded separately from the (same-SOC) hysteresis
    assert prov["handover_voltage_gap_mV"] == pytest.approx(
        (0.0967 - 0.01) * 1000.0, rel=1e-2
    )
    assert "NOT hysteresis" in prov["handover_gap_note"]
    assert "common" in prov["hysteresis_proxy_definition"]
    assert prov["rest_ocv_after_lithiation_V"] == pytest.approx(0.082)
    assert prov["polarization_estimate_at_handover_mV"] is not None
    # polarisation is RECORDED only, never applied
    assert "never applied" in prov["polarization_estimate_note"]


def test_extract_respects_soc_reference_charge():
    """Q_ref is the lithiation-branch charge; deli SOC = 1 - |Q|/Q_ref."""
    rec = _canonical_record()
    res = extract_ocp_branches(rec, cycle=1)
    q_ref = res["provenance"]["soc_reference_charge_Ah"]

    # expectation computed from the synthetic record itself
    lith = rec[(rec["cycle"] == 1) & (rec["step"] == 2)]
    dt = float(lith["time_s"].iloc[-1] - lith["time_s"].iloc[0])
    expected = abs(float(lith["current_A"].iloc[0])) * dt / 3600.0
    assert q_ref == pytest.approx(expected, rel=1e-3)

    deli = res["delithiation"]
    q_deli = abs(float(deli["current_A"].iloc[0])) * float(
        deli["time_s"].iloc[-1]
    ) / 3600.0
    assert float(deli["SOC"].iloc[-1]) == pytest.approx(
        1.0 - q_deli / q_ref, abs=1e-2
    )


def test_extract_missing_branch_raises():
    rec = _canonical_record()
    rec = rec[rec["step"] != 4]  # drop delithiation
    with pytest.raises(ValueError, match="lithiation and one delithiation"):
        extract_ocp_branches(rec, cycle=1)


def test_extract_flags_wrong_direction_branches():
    """Flipping the record's signs must be caught by the direction flags.

    (The classification is purely by measured sign, so the two steps
    simply swap roles - the safety net is the per-branch direction
    check, which must fire.)
    """
    rec = _canonical_record()
    rec.loc[rec["step"].isin([2, 4]), "current_A"] *= -1.0
    res = extract_ocp_branches(rec, cycle=1)
    flags = " | ".join(res["provenance"]["flags"])
    assert "lithiation branch does not lower the voltage" in flags
    assert "delithiation branch does not raise the voltage" in flags


def test_extract_rejects_nonpositive_reference_charge():
    """A record whose 'lithiation' step is far too short must raise."""
    rec = _canonical_record()
    rec.loc[rec["step"] == 2, "time_s"] = rec.loc[
        rec["step"] == 2, "time_s"
    ].iloc[0]
    with pytest.raises(ValueError):
        extract_ocp_branches(rec, cycle=1)


def test_extract_unknown_cycle_raises():
    with pytest.raises(ValueError, match="cycle 3 not present"):
        extract_ocp_branches(_canonical_record(), cycle=3)


def test_write_ocp_csvs_and_provenance(tmp_path):
    res = extract_ocp_branches(_canonical_record(), cycle=1)
    paths = write_ocp_csvs(
        res, tmp_path,
        source_file="demo.parquet",
        source_sha256="a" * 64,
        temperature_source="declared_room_temperature_not_measured",
    )
    for key in ("lithiation", "delithiation", "provenance"):
        assert paths[key].is_file()
    assert paths["lithiation"].name == "graphite_ocp_lithiation.csv"
    assert paths["delithiation"].name == "graphite_ocp_delithiation.csv"

    prov = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    # the four required provenance fields
    assert prov["source_file"] == "demo.parquet"
    assert prov["source_sha256"] == "a" * 64
    assert prov["temperature_source"] == (
        "declared_room_temperature_not_measured"
    )
    assert prov["equilibrium_warning"]

    df = pd.read_csv(paths["lithiation"])
    assert list(df.columns) == OCP_CSV_FIELDS


# --------------------------------------------------------------
# real data (skipped when the parquet is absent)
# --------------------------------------------------------------
def test_real_pocv_extraction():
    cfg = get_dataset_config(SINTEF)
    if not any((ROOT / cfg.raw_dir).glob("*4ccc47*p-ocv*.parquet")):
        pytest.skip("SINTEF p-OCV parquet not present")
    adapter = get_dataset(SINTEF)
    raw = adapter.load_raw("4ccc47")
    res = extract_ocp_branches(raw, cycle=1)
    prov = res["provenance"]

    # audited: cycle 1 lithiation 3.0 -> 0.01 V, delithiation 0.01 -> 1.0 V
    lith, deli = res["lithiation"], res["delithiation"]
    assert lith["Voltage"].iloc[0] > 2.5
    assert abs(float(lith["Voltage"].iloc[-1]) - 0.01) < 0.05
    assert abs(float(deli["Voltage"].iloc[-1]) - 1.0) < 0.05
    # Q_ref ~1.9-2.0 mAh from the C/50 lithiation branch
    assert 1.7e-3 < prov["soc_reference_charge_Ah"] < 2.1e-3
    # same-SOC hysteresis at C/50; the mean is inflated by the steep
    # dilute-stage end, so the fixed-SOC values are the reported ones
    assert 0.0 < prov["hysteresis_proxy_mV"] < 400.0
    assert prov["hysteresis_max_abs_mV"] >= prov["hysteresis_proxy_mV"] - 1e-9
    assert set(prov["hysteresis_at_soc_mV"]) >= {"SOC_0.20", "SOC_0.50"}
    assert abs(prov["hysteresis_at_soc_mV"]["SOC_0.50"]) < 120.0
    # the hand-over gap additionally contains the cutoff overshoot
    assert prov["handover_voltage_gap_mV"] > 50.0
    assert prov["rest_ocv_after_lithiation_V"] == pytest.approx(0.0824, abs=0.01)
    # canonical sign: lithiation is the positive-current branch
    assert float(lith["current_A"].median()) > 0
    assert float(deli["current_A"].median()) < 0
