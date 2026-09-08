# ============================================================
# Battery Dataset Simulation Platform v0.1
# Plotting helpers
#
# matplotlib is imported with the Agg backend so the platform
# runs headless (inside WSL / CI) without a display.
# ============================================================

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def save_voltage_comparison(
    q_exp,
    V_exp,
    q_sim,
    V_sim,
    path: Path,
    *,
    cell: str = "",
    rate: str = "",
    model: str = "",
    rmse_mV: float = 0.0,
    title: str = "",
) -> Path:
    """V vs discharged-capacity comparison plot for one discharge."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 5.2))

    ax.plot(
        q_exp,
        V_exp,
        label="Experiment",
        linewidth=1.8,
    )

    ax.plot(
        q_sim,
        V_sim,
        label=f"Command-level {model}",
        linewidth=1.6,
    )

    ax.set_xlabel("Discharged capacity [Ah]")
    ax.set_ylabel("Terminal voltage [V]")

    if not title:
        bits = [b for b in (cell, rate) if b]
        title = " | ".join(bits)
        if rmse_mV:
            title += f" | RMSE(Q)={rmse_mV:.1f} mV"

    ax.set_title(title)
    ax.legend()
    fig.tight_layout()

    fig.savefig(path, dpi=250)
    plt.close(fig)

    return path


def save_time_voltage_plot(
    t_exp,
    V_exp,
    t_sim,
    V_sim,
    path: Path,
    *,
    model: str = "",
    rmse_mV: float = 0.0,
) -> Path:
    """V vs time comparison plot (time-aligned replay/baseline)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 5.2))

    ax.plot(
        np.asarray(t_exp) / 3600.0,
        V_exp,
        label="Experiment",
        linewidth=1.8,
    )

    ax.plot(
        np.asarray(t_sim) / 3600.0,
        V_sim,
        label=f"PyBaMM {model}",
        linewidth=1.6,
    )

    ax.set_xlabel("Time [h]")
    ax.set_ylabel("Terminal voltage [V]")

    if rmse_mV:
        ax.set_title(f"RMSE(t)={rmse_mV:.1f} mV")

    ax.legend()
    fig.tight_layout()

    fig.savefig(path, dpi=250)
    plt.close(fig)

    return path
