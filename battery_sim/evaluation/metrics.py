# ============================================================
# Battery Dataset Simulation Platform v0.1
# Evaluation metrics
#
# Metric names distinguish the two alignment conventions
# (task spec §11):
#
#   rmse_Qaligned_mV     command-level reproduction:
#                        V_sim(Q) vs V_exp(Q), capacity aligned
#   rmse_time_aligned_mV replay / baseline:
#                        V_sim(t) vs V_exp(t), time aligned
#
# All voltage errors are reported in millivolts (multiply by 1000).
# The residual sign convention is preserved from the reference:
#   residual = V_sim - V_exp
# ============================================================

from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------
# Basic scalar metrics on a residual vector (units: V -> mV)
# ------------------------------------------------------------------
def rmse(residual) -> float:
    """Root mean square error in V."""
    r = np.asarray(residual, dtype=float)
    return float(np.sqrt(np.mean(r ** 2)))


def mae(residual) -> float:
    """Mean absolute error in V."""
    r = np.asarray(residual, dtype=float)
    return float(np.mean(np.abs(r)))


def bias(residual) -> float:
    """Mean signed error in V (V_sim - V_exp)."""
    r = np.asarray(residual, dtype=float)
    return float(np.mean(r))


# ------------------------------------------------------------------
# Capacity metrics
# ------------------------------------------------------------------
def cutoff_capacity_error(q_sim_end: float, q_exp_end: float) -> float:
    """Percent capacity error at cutoff: 100*(Qsim-Qexp)/Qexp."""
    return 100.0 * (q_sim_end - q_exp_end) / q_exp_end


def initial_voltage_error_mV(v_sim_start: float, v_exp_start: float) -> float:
    """First-point voltage error in mV: (Vsim0 - Vexp0)*1000."""
    return (v_sim_start - v_exp_start) * 1000.0


# ------------------------------------------------------------------
# Capacity-aligned comparison (used by command-level reproduction)
# ------------------------------------------------------------------
def compare_q_aligned(q_exp, V_exp, q_sim, V_sim):
    """
    Compare simulated vs experimental discharge on the common
    discharged-capacity domain.

    Returns (q_common, V_exp_common, V_sim_common, error).

    This replicates the reference compare_q_aligned() in
    scripts/runners/command_reproduction.py.
    """
    q_exp = np.asarray(q_exp, dtype=float)
    V_exp = np.asarray(V_exp, dtype=float)
    q_sim = np.asarray(q_sim, dtype=float)
    V_sim = np.asarray(V_sim, dtype=float)

    q_end = min(float(q_exp[-1]), float(q_sim[-1]))

    mask = q_exp <= q_end
    qe = q_exp[mask]
    Ve = V_exp[mask]

    # ensure q_sim strictly increasing
    unique = np.concatenate(
        [
            [True],
            np.diff(q_sim) > 1e-12,
        ]
    )

    qs = q_sim[unique]
    Vs = V_sim[unique]

    Vsi = np.interp(qe, qs, Vs)

    error = Vsi - Ve

    return qe, Ve, Vsi, error


# ------------------------------------------------------------------
# Solution helpers
# ------------------------------------------------------------------
def cumulative_capacity(t, current) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    t = np.asarray(t, dtype=float)
    current = np.asarray(current, dtype=float)

    if len(t) < 2:
        return np.zeros_like(t)

    dq = 0.5 * (current[1:] + current[:-1]) * np.diff(t) / 3600.0

    return np.concatenate(
        [
            [0.0],
            np.cumsum(dq),
        ]
    )


def get_voltage(solution) -> np.ndarray:
    """Voltage array from a pybamm solution/cycle (volts)."""
    for key in [
        "Voltage [V]",
        "Terminal voltage [V]",
    ]:
        try:
            return np.asarray(
                solution[key].entries,
                dtype=float,
            )
        except KeyError:
            pass

    raise KeyError("Voltage variable unavailable")


def get_current(solution) -> np.ndarray:
    """Current array from a pybamm solution/cycle (A)."""
    return np.asarray(
        solution["Current [A]"].entries,
        dtype=float,
    )


def extract_discharge(solution, cycle_index: int, rate_current_A: float):
    """
    Extract the discharge branch of one validation cycle from a
    command-level solution.

    Positive current = discharge. Points with I > 0.5 * I_nominal
    belong to the discharge; time is made local to its start and
    cumulative discharged capacity is computed.

    Returns (t, q, V) numpy arrays.
    """
    cycle = solution.cycles[cycle_index]

    t = np.asarray(cycle.t, dtype=float)
    I = get_current(cycle)
    V = get_voltage(cycle)

    threshold = 0.5 * rate_current_A
    mask = I > threshold

    if not np.any(mask):
        raise RuntimeError(
            f"No discharge points for cycle index {cycle_index}"
        )

    t = t[mask]
    I = I[mask]
    V = V[mask]

    t = t - t[0]
    q = cumulative_capacity(t, I)

    return t, q, V


def metrics_for_discharge(
    q_exp,
    V_exp,
    q_sim,
    V_sim,
    t_exp=None,
    t_sim=None,
) -> dict:
    """
    Full metric row for one capacity-aligned discharge comparison.

    Column names match the validated reference output schema of
    scripts/runners/command_reproduction.py (protocol_metrics.csv).
    """
    q_exp = np.asarray(q_exp, dtype=float)
    V_exp = np.asarray(V_exp, dtype=float)
    q_sim = np.asarray(q_sim, dtype=float)
    V_sim = np.asarray(V_sim, dtype=float)

    (
        q_common,
        V_exp_common,
        V_sim_common,
        error,
    ) = compare_q_aligned(
        q_exp,
        V_exp,
        q_sim,
        V_sim,
    )

    q_exp_end = float(q_exp[-1])
    q_sim_end = float(q_sim[-1])

    row = {
        "rmse_Qaligned_mV": rmse(error) * 1000.0,
        "mae_Qaligned_mV": mae(error) * 1000.0,
        "bias_Qaligned_mV": bias(error) * 1000.0,
        "Q_exp_Ah": q_exp_end,
        "Q_sim_Ah": q_sim_end,
        "cutoff_capacity_error_pct": cutoff_capacity_error(
            q_sim_end,
            q_exp_end,
        ),
        "initial_voltage_error_mV": initial_voltage_error_mV(
            float(V_sim_common[0]),
            float(V_exp_common[0]),
        ),
        "common_end_voltage_error_mV": float(error[-1]) * 1000.0,
        "n_points": int(len(q_common)),
    }

    if t_exp is not None and t_sim is not None:
        t_exp_end = float(np.asarray(t_exp)[-1])
        t_sim_end = float(np.asarray(t_sim)[-1])
        row["t_exp_s"] = t_exp_end
        row["t_sim_s"] = t_sim_end
        row["cutoff_time_error_pct"] = (
            100.0 * (t_sim_end - t_exp_end) / t_exp_end
        )

    # --------------------------------------------------------------
    # Standardised aliases (spec §9 / Step 9)
    #
    # The validated reference output used rmse_Qaligned_mV; those
    # columns are kept verbatim for regression compatibility.  The
    # *_capacity_aligned_* names are the platform-standard aliases
    # of the same values and are simply duplicates of the old names.
    # --------------------------------------------------------------
    row["rmse_capacity_aligned_mV"] = row["rmse_Qaligned_mV"]
    row["mae_capacity_aligned_mV"] = row["mae_Qaligned_mV"]
    row["bias_capacity_aligned_mV"] = row["bias_Qaligned_mV"]

    return row
