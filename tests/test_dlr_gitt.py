"""Contract tests for the DLR GITT adapter and the excitation schema.

These are the things that were actually wrong (or nearly wrong) while the
adapter was built, pinned so they cannot regress:

  * the SIGN flip -- Basytec's negative-is-discharge against the platform's
    discharge-is-positive -- verified IN DATA rather than asserted
  * the phase segmentation coming from the file's own Command column
  * the pulse-relax classification thresholds
  * the capacity reference being the SWEEP, not the pulse.  Using the
    pulse gave a 7400x scale error that looked exactly like an inert
    parameter, which is the one failure this whole gate exists to detect
  * honest failure for a dataset with no recorded-protocol capability
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.datasets.dlr_gitt import (
    DlrGittAdapter,
    SWEEP_CHARGE,
    SWEEP_DISCHARGE,
)
from battery_sim.excitation import (
    KIND_PULSE,
    KIND_REST,
    PulseRelaxProtocol,
    Segment,
)
from battery_sim.registry import get_dataset

DATASET = "dlr_gitt"
CELL = "Hydra.0b_A"


@pytest.fixture(scope="module")
def adapter():
    return get_dataset(DATASET)


@pytest.fixture(scope="module")
def log(adapter):
    return adapter.log


# ------------------------------------------------------------------
# Registration and metadata
# ------------------------------------------------------------------
def test_adapter_resolves_by_convention(adapter):
    assert isinstance(adapter, DlrGittAdapter)
    assert isinstance(adapter, BatteryDatasetAdapter)


def test_declared_role_is_not_validation(adapter):
    """The cell is a different cell; calling it validation would be wrong."""
    role = (adapter.config.extra or {}).get("dataset_role")
    assert role == "benchmark"
    assert role != "validation"


def test_cells_and_rates_come_from_config(adapter):
    assert adapter.list_cells() == [CELL]
    assert adapter.list_rates() == ["GITT-pulse"]
    info = adapter.rate_info("GITT-pulse")
    assert info["c_rate"] == pytest.approx(0.1)
    assert info["rate_slug"] == "gittPulse"


def test_measured_temperature_is_real(adapter):
    ambient = adapter.get_ambient_temperature(CELL)
    assert 20.0 < ambient < 30.0


# ------------------------------------------------------------------
# Sign convention, verified in data
# ------------------------------------------------------------------
def test_sign_convention_holds_in_data(adapter):
    """Canonical positive current must coincide with FALLING voltage.

    For graphite that is lithiation, which is the spontaneous direction of
    a graphite||Li cell -- i.e. discharge.  Asserting the flip instead of
    checking it would let a sign error pass as a physics result.
    """
    frame = adapter.log.frame
    I = frame["current_A"].to_numpy(float)
    V = frame["voltage_V"].to_numpy(float)
    lab = frame["label"].to_numpy()

    dis = lab == "Discharge"
    chg = lab == "Charge"
    assert dis.any() and chg.any()
    assert np.median(I[dis]) > 0, "Discharge must be canonical positive"
    assert np.median(I[chg]) < 0, "Charge must be canonical negative"

    # and the trend must agree with the label
    for mask, sign in ((dis, -1), (chg, +1)):
        idx = np.flatnonzero(mask)
        first, last = idx[0], idx[-1]
        dv = V[last] - V[first]
        assert np.sign(dv) == sign, (
            f"label trend mismatch: dV={dv:.5f} for sign {sign}"
        )


# ------------------------------------------------------------------
# Phase segmentation
# ------------------------------------------------------------------
def test_phase_table_matches_source_commands(log):
    counts = log.phases["label"].value_counts().to_dict()
    assert counts["Pause"] > 400
    assert counts["Discharge"] > 200
    assert counts["Charge"] > 200


def test_phases_are_contiguous_and_ordered(log):
    ph = log.phases
    # contiguity means stop[i] == start[i+1], i.e. the LAGGING stop
    # array against the LEADING start array
    assert (ph["row_stop"].to_numpy()[:-1]
            == ph["row_start"].to_numpy()[1:]).all()
    assert ph["row_start"].iloc[0] == 0
    assert ph["row_stop"].iloc[-1] == log.n_rows
    assert (ph["duration_s"] >= 0).all()
    assert (np.diff(ph["row_start"].to_numpy()) > 0).all()


def test_rests_carry_no_current(log):
    ph = log.phases
    rests = ph[ph["label"] == "Pause"]
    assert np.allclose(rests["mean_current_A"].to_numpy(float), 0.0)


# ------------------------------------------------------------------
# Protocol classification
# ------------------------------------------------------------------
def test_classified_as_pulse_relax(adapter):
    proto = adapter.log.protocol
    assert isinstance(proto, PulseRelaxProtocol)
    assert proto.source["classified_as"] == "pulse_relax"


def test_pulse_and_rest_geometries_are_the_declared_ones(adapter):
    src = adapter.log.protocol.source
    assert src["pulse_duration_median_s"] == pytest.approx(150.0, abs=5.0)
    assert src["rest_duration_median_s"] > 1000.0


def test_duty_cycle_is_small(adapter):
    """A pulse-relax protocol must actually be mostly rest."""
    assert adapter.log.protocol.duty_cycle < 0.10


def test_alternation_is_checked_not_assumed(adapter):
    trips = adapter.log.protocol.triplets()
    assert len(trips) > 400
    for a, b, c in trips[:20]:
        segs = adapter.log.protocol.segments
        assert segs[a].kind == KIND_REST
        assert segs[b].kind == KIND_PULSE
        assert segs[c].kind == KIND_REST


# ------------------------------------------------------------------
# Triplet selection
# ------------------------------------------------------------------
def test_triplets_split_into_two_sweeps(adapter):
    t = adapter.triplets()
    sweeps = set(t["sweep"])
    assert sweeps == {SWEEP_DISCHARGE, SWEEP_CHARGE}
    dis = t[t["sweep"] == SWEEP_DISCHARGE]
    assert (dis["current_A"] > 0).all()
    assert (t[t["sweep"] == SWEEP_CHARGE]["current_A"] < 0).all()


def test_find_triplet_selects_by_voltage(adapter):
    pid = adapter.find_triplet(SWEEP_DISCHARGE, 0.1165)
    k = int(pid.split("#t")[1])
    row = adapter.triplets()
    v = float(row[row["triplet"] == k]["v_pre_V"].iloc[0])
    assert abs(v - 0.1165) < 0.02


def test_triplet_window_rebases_time_and_stays_under_the_cap(adapter):
    """The replay path decimates above 2000 points, which would smear a
    pulse.  A triplet must therefore fit underneath that cap."""
    pid = adapter.default_protocol_id()
    df = adapter.load_processed_protocol(CELL, pid)
    assert list(df.columns) == ["time_s", "current_A", "voltage_V",
                                "capacity_Ah", "temperature_ambient_C"]
    assert df["time_s"].iloc[0] == pytest.approx(0.0)
    assert len(df) < 2000, (
        f"triplet window has {len(df)} rows; the platform decimates above "
        f"2000 and would smooth the pulse"
    )
    n_on = int((np.abs(df["current_A"].to_numpy(float)) > 0).sum())
    assert 100 < n_on < 300


def test_window_is_carrying_the_measured_current_not_a_segment_mean(adapter):
    """A flat current profile would remove the very transient the protocol
    exists to provide."""
    pid = adapter.default_protocol_id()
    df = adapter.load_processed_protocol(CELL, pid)
    on = df["current_A"].to_numpy(float)
    on = on[np.abs(on) > 0]
    assert on.size > 0
    assert np.ptp(on) > 0.0


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------
def test_initialisation_is_inverse_ocp_inside_the_table(adapter):
    pid = adapter.default_protocol_id()
    df = adapter.load_processed_protocol(CELL, pid)
    init = df.attrs["initialisation"]
    assert init["method"] == "fixed_initial_concentration"
    assert init["ocp_table_edge_fallback"] is False
    assert 0.0 < init["stoichiometry_from_ocp"] < 1.0
    assert init["concentration_parameter"] == (
        "Initial concentration in positive electrode [mol.m-3]"
    )


def test_provenance_records_where_the_numbers_came_from(adapter):
    pid = adapter.default_protocol_id()
    prov = adapter.load_processed_protocol(CELL, pid).attrs["provenance"]
    assert prov["source_file"].endswith(".txt")
    assert "Basytec" in prov["sign_convention"]["raw"]
    assert prov["sign_convention"]["platform_canonical"] == (
        "discharge = +, charge = -"
    )
    assert "CAPABILITY demonstration" in prov["known_difference_from_sintef_line"]
    assert prov["measured_temperature_C"]["min"] > 20.0


# ------------------------------------------------------------------
# Capacity reference -- the 7400x trap
# ------------------------------------------------------------------
def test_capacity_reference_is_the_sweep_not_the_pulse(adapter):
    """A triplet's charge is ONE PULSE, not the cell capacity.

    Using it scaled the model down by ~7400x, pushing the replay into the
    voltage cut-off and producing NaN transients that read as 'the
    parameter is inert'.  The declared reference must be the sweep.
    """
    ref = adapter.capacity_reference_protocol()
    assert ref is not None
    assert "#t" not in str(ref), (
        "the capacity reference must not be a single triplet"
    )
    assert str(ref) == "GITT-discharge"


def test_sweep_charge_is_far_larger_than_one_pulse(adapter):
    """Guards the arithmetic the reference choice depends on."""
    sweep = adapter.load_processed_protocol(CELL, "GITT-discharge")
    trip = adapter.load_processed_protocol(CELL, adapter.default_protocol_id())

    def charge_Ah(df):
        t = df["time_s"].to_numpy(float)
        I = df["current_A"].to_numpy(float)
        return abs(float(np.sum(0.5 * (I[1:] + I[:-1]) * np.diff(t))) / 3600.0)

    q_sweep = charge_Ah(sweep)
    q_trip = charge_Ah(trip)
    assert q_sweep > 100 * q_trip
    assert 5e-3 < q_sweep < 8e-3, (
        f"sweep charge {q_sweep * 1e3:.3f} mAh outside the measured range"
    )


# ------------------------------------------------------------------
# The schema's own invariants
# ------------------------------------------------------------------
def test_rest_segment_rejects_current():
    with pytest.raises(ValueError, match="rest but carries"):
        Segment(kind=KIND_REST, t_start_s=0.0, t_stop_s=1.0, current_A=1e-4)


def test_pulse_segment_rejects_zero_current():
    with pytest.raises(ValueError, match="carries.*zero current"):
        Segment(kind=KIND_PULSE, t_start_s=0.0, t_stop_s=1.0, current_A=0.0)


def test_segment_rejects_non_positive_duration():
    with pytest.raises(ValueError, match="non-positive duration"):
        Segment(kind=KIND_REST, t_start_s=5.0, t_stop_s=5.0, current_A=0.0)


def test_triplet_accepts_only_its_own_sweep(adapter):
    t = adapter.triplets()
    charge_k = int(t[t["sweep"] == SWEEP_CHARGE]["triplet"].iloc[0])
    with pytest.raises(ValueError, match="belongs to sweep"):
        adapter.load_protocol(f"GITT-{SWEEP_DISCHARGE}#t{charge_k}")


def test_unknown_protocol_id_fails_loudly(adapter):
    with pytest.raises(ValueError, match="unrecognised protocol id"):
        adapter.load_protocol("not-a-protocol")


# ------------------------------------------------------------------
# Capability detection must not be fooled by the base class
# ------------------------------------------------------------------
def test_base_hasattr_trap_is_avoided():
    """``hasattr(adapter, 'load_processed_protocol')`` is ALWAYS True,
    because the base class defines it.  The check has to compare against
    the base implementation, and a dataset without the capability must be
    reported as such rather than raising NotImplementedError halfway."""
    sintef = get_dataset("sintef_graphite")
    assert hasattr(sintef, "load_processed_protocol")  # the trap
    assert (type(sintef).load_processed_protocol
            is BatteryDatasetAdapter.load_processed_protocol)  # the truth

    from battery_sim.simulation.protocol_replay import run_protocol_replay

    with pytest.raises(TypeError, match="does not expose recorded protocols"):
        run_protocol_replay(sintef, "pOCV-deli", model_name="SPM")


def test_this_adapter_does_expose_the_capability(adapter):
    assert (type(adapter).load_processed_protocol
            is not BatteryDatasetAdapter.load_processed_protocol)
    assert adapter.list_protocols() == [
        f"GITT-{SWEEP_DISCHARGE}", f"GITT-{SWEEP_CHARGE}"
    ]
