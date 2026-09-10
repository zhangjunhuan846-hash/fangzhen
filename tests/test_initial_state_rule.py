# ============================================================
# Phase B0.7 tests: the initial-state / window-start rule
#
# Hermetic: a stub adapter supplies a canonical frame and synthetic OCP
# tables supply the variant curves.  No dataset directory is required.
# ============================================================

import numpy as np
import pandas as pd
import pytest

import scripts.graphite_phase_b0_compare as b0
from scripts.graphite_phase_b0_compare import (
    WINDOW_START_TOL_V,
    X0_MARGIN,
    OCPConsistentAdapter,
)


# ------------------------------------------------------------------
# the constants the rule rests on
# ------------------------------------------------------------------
def test_floor_and_tolerance_are_declared_and_documented():
    assert X0_MARGIN == 1e-3, (
        "the 1e-3 floor is load-bearing: PyBaMM's initial-state "
        "initialisation makes the initial overpotential diverge as c_s -> 0"
    )
    assert WINDOW_START_TOL_V == 1e-3
    src = open(b0.__file__, encoding="utf-8").read()
    assert "initial-state initialisation" in src
    assert "WINDOW_START_TOL_V" in src


# ------------------------------------------------------------------
# fixtures: a stub adapter and synthetic OCP tables
# ------------------------------------------------------------------
class _StubAdapter:
    """Supplies the canonical frame the proxy decorates."""

    def __init__(self, frame: pd.DataFrame, rest_ocv: float = 3.0161):
        self._frame = frame
        self._rest_ocv = float(rest_ocv)
        self.config = None

    def load_processed_discharge(self, cell, rate):
        df = self._frame.copy()
        df.attrs["provenance"] = {"rest_ocv_V": self._rest_ocv}
        df.attrs["initialisation"] = {"method": "fixed_initial_concentration"}
        return df


def _descending_frame(n=400, v_start=3.0, v_end=0.02, t_end=1000.0):
    """A window that FALLS (the lithiation case)."""
    t = np.linspace(0.0, t_end, n)
    # near-vertical dilute stage, then a flatter plateau
    frac = t / t_end
    V = v_start - (v_start - v_end) * np.sqrt(frac)
    return pd.DataFrame({
        "time_s": t, "current_A": np.full(n, 4.328e-5),
        "voltage_V": V, "capacity_Ah": frac * 1.94e-3,
        "temperature_ambient_C": np.full(n, 25.0),
    })


def _ascending_frame(n=400, v_start=0.083, v_end=1.0, t_end=1000.0):
    """A window that RISES (the delithiation case)."""
    t = np.linspace(0.0, t_end, n)
    frac = t / t_end
    V = v_start + (v_end - v_start) * np.sqrt(frac)
    return pd.DataFrame({
        "time_s": t, "current_A": np.full(n, 4.328e-5),
        "voltage_V": V, "capacity_Ah": frac * 1.94e-3,
        "temperature_ambient_C": np.full(n, 25.0),
    })


@pytest.fixture()
def ocp_tables():
    """
    Synthetic tables that reproduce the two SHAPES the rule has to cope
    with (the real magnitudes are in the Phase B0.7 report):

      * lithiation   - a near-vertical dilute stage: 3.0003 V at SOC 0
                       collapsing to 1.0759 V by SOC 1e-3, then plateaus
      * delithiation - rises with SOC from 0.30 V at its SOC edge

    The delithiation bottom is deliberately above the frame's start so
    that the ascending branch exercises a non-trivial prefix.
    """
    soc_l = [0.0, 6.2e-5, 1.24e-4, 1.86e-4, 1e-3, 5e-3, 1e-2, 5e-2,
             0.1, 0.2, 0.5, 0.9, 1.0]
    vol_l = [3.0003, 1.7865, 1.6208, 1.5304, 1.0759, 0.7500, 0.5815,
             0.2678, 0.1415, 0.0986, 0.0631, 0.0409, 0.0106]
    lith = pd.DataFrame({"SOC": soc_l, "Voltage": vol_l,
                         "branch": "lithiation"})
    soc_d = np.linspace(0.0812, 1.0, 200)
    deli = pd.DataFrame({
        "SOC": soc_d,
        "Voltage": 0.30 + 0.70 * (soc_d - 0.0812) / 0.9188,
        "branch": "delithiation",
    })
    return {"lithiation": lith, "delithiation": deli}


# ------------------------------------------------------------------
# the rule itself
# ------------------------------------------------------------------
def test_prefix_is_trimmed_when_the_window_falls(ocp_tables):
    px = OCPConsistentAdapter(_StubAdapter(_descending_frame()),
                              "lithiation", ocp_tables)
    df = px.load_processed_discharge("cell", "rate")
    rec = df.attrs["provenance"]["window_start_rule"]
    assert rec["applied"] is True
    assert rec["traversal_direction"] == "descending"
    assert rec["n_points_removed"] > 0
    v_start = rec["model_start_voltage_V"]
    # everything kept is at or below the model's start voltage
    assert float(df["voltage_V"].max()) <= v_start + WINDOW_START_TOL_V + 1e-9
    # the kept frame is re-zeroed and keeps canonical semantics
    assert float(df["time_s"].iloc[0]) == 0.0
    assert float(df["capacity_Ah"].iloc[0]) == 0.0
    assert rec["n_points_kept"] == len(df)


def test_prefix_is_trimmed_when_the_window_rises(ocp_tables):
    px = OCPConsistentAdapter(
        _StubAdapter(_ascending_frame(), rest_ocv=0.0824),
        "delithiation", ocp_tables,
    )
    df = px.load_processed_discharge("cell", "rate")
    rec = df.attrs["provenance"]["window_start_rule"]
    assert rec["traversal_direction"] == "ascending"
    assert rec["applied"] is True
    assert float(df["voltage_V"].min()) >= (
        rec["model_start_voltage_V"] - WINDOW_START_TOL_V - 1e-9
    )


def test_rule_removes_a_prefix_only_never_an_interior_point(ocp_tables):
    frame = _descending_frame()
    px = OCPConsistentAdapter(_StubAdapter(frame), "lithiation", ocp_tables)
    df = px.load_processed_discharge("cell", "rate")
    k = df.attrs["provenance"]["window_start_rule"]["n_points_removed"]
    expected = frame["voltage_V"].to_numpy(float)[k:]
    assert np.allclose(df["voltage_V"].to_numpy(float), expected)


def test_rule_off_still_records_what_would_be_removed(ocp_tables):
    px = OCPConsistentAdapter(_StubAdapter(_descending_frame()),
                              "lithiation", ocp_tables,
                              trim_unrepresentable_prefix=False)
    df = px.load_processed_discharge("cell", "rate")
    rec = df.attrs["provenance"]["window_start_rule"]
    assert rec["enabled"] is False
    assert rec["applied"] is False
    assert rec["n_points_removed"] > 0          # still evaluated
    assert len(df) == len(_descending_frame())  # frame untouched
    assert "DISABLED" in rec["note"]


def test_rule_is_a_noop_when_the_window_is_representable(ocp_tables):
    """A window entirely inside the model's admissible range keeps all
    its points."""
    frame = _descending_frame(v_start=0.9, v_end=0.02)
    px = OCPConsistentAdapter(_StubAdapter(frame, rest_ocv=3.0161),
                              "lithiation", ocp_tables)
    df = px.load_processed_discharge("cell", "rate")
    rec = df.attrs["provenance"]["window_start_rule"]
    assert rec["n_points_removed"] == 0
    assert rec["applied"] is False
    assert len(df) == len(frame)


def test_record_carries_the_audit_fields(ocp_tables):
    px = OCPConsistentAdapter(_StubAdapter(_descending_frame()),
                              "lithiation", ocp_tables)
    df = px.load_processed_discharge("cell", "rate")
    rec = df.attrs["provenance"]["window_start_rule"]
    for key in ("rule", "applied", "variant", "x0",
                "model_start_voltage_V", "traversal_direction",
                "tolerance_V", "n_points_removed", "n_points_kept",
                "duration_removed_s", "duration_total_s",
                "fraction_removed", "voltage_range_removed_V", "reason",
                "not_a_fit"):
        assert key in rec, key
    assert 0.0 < rec["fraction_removed"] < 1.0
    vr = rec["voltage_range_removed_V"]
    assert len(vr) == 2 and vr[0] <= vr[1]


def test_rule_does_not_look_at_the_residual(ocp_tables):
    """The rule is parameter-based: the same frame with a different
    (irrelevant) extra column yields the same trim."""
    a = _descending_frame()
    b = a.copy()
    b["residual_V"] = np.random.default_rng(0).normal(0, 1, len(b))
    ka = OCPConsistentAdapter(_StubAdapter(a), "lithiation",
                              ocp_tables).load_processed_discharge(
        "c", "r").attrs["provenance"]["window_start_rule"]["n_points_removed"]
    kb = OCPConsistentAdapter(_StubAdapter(b), "lithiation",
                              ocp_tables).load_processed_discharge(
        "c", "r").attrs["provenance"]["window_start_rule"]["n_points_removed"]
    assert ka == kb


# ------------------------------------------------------------------
# the proxy's OCP helpers stay consistent with the original mapping
# ------------------------------------------------------------------
def test_ocp_at_matches_the_curve_helper(ocp_tables):
    px = OCPConsistentAdapter(_StubAdapter(_descending_frame()),
                              "lithiation", ocp_tables)
    s, v = px._curve()
    for soc in (0.0, 0.1, 0.5, 1.0):
        assert px.ocp_at(soc) == pytest.approx(
            float(np.interp(soc, s, v)), abs=1e-12
        )


def test_x0_mapping_is_unchanged_by_the_refactor(ocp_tables):
    """_x0_for must behave exactly as before the _curve() refactor:
    a rest OCV above the table top pins to the table edge, then the
    floor lifts it to X0_MARGIN."""
    px = OCPConsistentAdapter(_StubAdapter(_descending_frame()),
                              "lithiation", ocp_tables)
    x0 = px._x0_for(3.0161)
    assert x0 == pytest.approx(X0_MARGIN)
    log = px.mapping_log[-1]
    assert log["clamped_to_table_edge"] is True
    assert log["x0_before_margin"] == pytest.approx(0.0, abs=1e-9)
