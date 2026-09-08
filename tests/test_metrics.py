# ============================================================
# Battery Dataset Simulation Platform v0.1
# Metrics unit tests (Step 11)
#
# Covers the pure-math metric functions plus the naming
# convention requirements:
#   * command-level reproduction -> rmse_Qaligned_mV (validated
#     reference name) + rmse_capacity_aligned_mV alias
#   * replay / baseline           -> rmse_time_aligned_mV
# ============================================================

import numpy as np
import pytest

from battery_sim.evaluation.metrics import (
    bias,
    compare_q_aligned,
    cutoff_capacity_error,
    extract_discharge,
    get_current,
    get_voltage,
    initial_voltage_error_mV,
    mae,
    metrics_for_discharge,
    rmse,
)


# ------------------------------------------------------------------
# Scalar metrics
# ------------------------------------------------------------------
def test_rmse_known_vector():
    r = np.array([1.0, -1.0])
    assert rmse(r) == pytest.approx(1.0)


def test_mae_known_vector():
    r = np.array([2.0, -4.0])
    assert mae(r) == pytest.approx(3.0)


def test_bias_known_vector():
    r = np.array([2.0, -4.0])
    assert bias(r) == pytest.approx(-1.0)


def test_cutoff_capacity_error_sign():
    # +2% when simulation discharges more capacity than experiment
    assert cutoff_capacity_error(5.1, 5.0) == pytest.approx(2.0)
    assert cutoff_capacity_error(4.9, 5.0) == pytest.approx(-2.0)


def test_initial_voltage_error_mV():
    assert initial_voltage_error_mV(3.2, 3.1) == pytest.approx(100.0)


# ------------------------------------------------------------------
# Capacity-aligned comparison
# ------------------------------------------------------------------
def test_compare_q_aligned_basic():
    q_exp = np.array([0.0, 0.5, 1.0])
    V_exp = np.array([4.0, 3.8, 3.5])
    q_sim = np.array([0.0, 0.5, 1.0])
    V_sim = np.array([4.0, 3.7, 3.5])

    q, Ve, Vs, err = compare_q_aligned(q_exp, V_exp, q_sim, V_sim)

    assert len(q) == 3
    np.testing.assert_allclose(err, [0.0, -0.1, 0.0], atol=1e-12)


def test_compare_q_aligned_truncates_to_shortest():
    # simulated discharge ends earlier -> comparison is restricted to
    # experimental points with q <= q_sim[-1]
    q_exp = np.array([0.0, 0.5, 1.0, 1.5])
    V_exp = np.array([4.0, 3.8, 3.5, 3.0])
    q_sim = np.array([0.0, 0.4, 1.2])
    V_sim = np.array([4.0, 3.9, 3.4])

    q, _, Vs, _ = compare_q_aligned(q_exp, V_exp, q_sim, V_sim)

    # all retained points lie on the experimental grid within q_sim range
    assert len(q) == 3
    assert q[-1] == pytest.approx(1.0)
    # interpolation of V_sim at q=1.0 lies between 3.9 (0.4) and 3.4 (1.2)
    assert Vs[-1] == pytest.approx(
        np.interp(1.0, q_sim, V_sim), abs=1e-12
    )


# ------------------------------------------------------------------
# metric row schema (validated reference + standard alias)
# ------------------------------------------------------------------
def test_metrics_for_discharge_has_reference_and_alias_columns():
    q = np.linspace(0.0, 1.0, 50)
    V = 4.0 - 0.5 * q

    row = metrics_for_discharge(q, V, q, V - 0.01)

    # validated reference names are preserved
    assert "rmse_Qaligned_mV" in row
    assert "mae_Qaligned_mV" in row
    assert "bias_Qaligned_mV" in row

    # standardised aliases equal the reference columns
    assert row["rmse_capacity_aligned_mV"] == row["rmse_Qaligned_mV"]
    assert row["mae_capacity_aligned_mV"] == row["mae_Qaligned_mV"]
    assert row["bias_capacity_aligned_mV"] == row["bias_Qaligned_mV"]

    assert row["rmse_Qaligned_mV"] == pytest.approx(10.0, abs=1e-6)
    assert row["Q_exp_Ah"] == pytest.approx(1.0)
    assert row["Q_sim_Ah"] == pytest.approx(1.0)


def test_metrics_for_discharge_time_columns_optional():
    q = np.linspace(0.0, 1.0, 20)
    V = 4.0 - 0.5 * q

    with_time = metrics_for_discharge(
        q, V, q, V, t_exp=np.ones(20) * 10.0, t_sim=np.ones(20) * 11.0
    )

    assert with_time["t_exp_s"] == pytest.approx(10.0)
    assert with_time["t_sim_s"] == pytest.approx(11.0)
    assert with_time["cutoff_time_error_pct"] == pytest.approx(10.0)

    without_time = metrics_for_discharge(q, V, q, V)

    assert "cutoff_time_error_pct" not in without_time


# ------------------------------------------------------------------
# solution helpers need a pybamm solution; only exercised in WSL
# ------------------------------------------------------------------
def test_extract_discharge_requires_cycle():
    # Force a path through the helper layer: no real pybamm object
    # here, so we only verify the failure mode is clear.
    class FakeCycle:
        t = np.linspace(0, 100, 10)

        def __getitem__(self, key):
            if key == "Current [A]":
                class _C:
                    entries = np.zeros(10)
                return _C()
            raise KeyError(key)

    fake = FakeCycle()

    # get_voltage should raise KeyError for a fake object without voltage
    with pytest.raises(KeyError):
        get_voltage(fake)


def test_get_current_helper_on_fake_cycle():
    class FakeCycle:
        t = np.linspace(0, 100, 10)

        def __getitem__(self, key):
            assert key == "Current [A]"

            class _C:
                entries = np.arange(10.0)

            return _C()

    assert get_current(FakeCycle())[-1] == pytest.approx(9.0)
