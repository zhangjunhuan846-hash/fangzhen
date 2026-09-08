# ============================================================
# Battery Dataset Simulation Platform v0.1
# Command-level reproduction runner
#
# Reuses the validated logic of:
#   scripts/runners/command_reproduction.py
#
# Pipeline for one (cell, model):
#   adapter initial voltage V0 (from tail of initial rest)
#   ambient temperature (chamber median over steps 6/11/16/21)
#   pybamm.ParameterValues("Chen2020") + T amb/init  <- factory
#   model from factory
#   command-level pybamm.Experiment from protocol module
#   IDAKLUSolver(rtol=1e-6, atol=1e-6)
#   sim.solve(initial_soc=f"{V0:.5f} V", calc_esoh=False)
#   per rate: extract sim discharge, compare V(Q) vs Vexp(Q)
#
# Outputs (per run):
#   metrics.csv            one row per validation rate
#   run_metadata.json      dataset/model/cell/version/runtime
#   voltage_comparison.png per-rate V-Q plot (optional)
# ============================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

import pybamm

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.evaluation.metrics import (
    compare_q_aligned,
    extract_discharge,
    metrics_for_discharge,
)
from battery_sim.evaluation.plotting import save_voltage_comparison
from battery_sim.models.pybamm_factory import (
    build_model,
    load_parameter_values,
)
from battery_sim.paths import ensure_dir
from battery_sim.protocols.chen2020 import (
    RATE_CYCLE_INDEX,
    RATE_CURRENT_A,
    build_experiment,
)


def _solver() -> pybamm.IDAKLUSolver:
    """Validated solver configuration (reference default)."""
    return pybamm.IDAKLUSolver(
        rtol=1e-6,
        atol=1e-6,
    )


def run_reproduction_cell(
    adapter: BatteryDatasetAdapter,
    model_name: str,
    cell: str,
    parameter_set: str,
    rates: Optional[List[str]] = None,
    output_dir: Optional[Path] = None,
    plot: bool = True,
    quiet: bool = False,
) -> dict:
    """
    Run command-level reproduction for one cell with one model.

    Returns a result dict:
        {
          "metrics": pd.DataFrame (one row per rate),
          "output_dir": Path,
          "initial_voltage_V": float,
          "ambient_temperature_C": float,
          "runtime_s": float,
          "rate_info": {rate: (q_exp, V_exp, q_sim, V_sim, q_common, V_exp_c, V_sim_c)}
        }
    """
    if rates is None:
        rates = list(adapter.list_rates())

    # ----------------------------------------------------------
    # Initial / environmental state from the experimental record
    # ----------------------------------------------------------
    V0 = float(adapter.get_initial_state(cell))
    tamb_C = float(adapter.get_ambient_temperature(cell))

    # ----------------------------------------------------------
    # Parameter set + model + experiment + solver
    # ----------------------------------------------------------
    params = load_parameter_values(parameter_set)

    params.update(
        {
            "Ambient temperature [K]": tamb_C + 273.15,
            "Initial temperature [K]": tamb_C + 273.15,
        }
    )

    model = build_model(model_name)

    experiment = build_experiment()

    solver = _solver()

    sim = pybamm.Simulation(
        model,
        parameter_values=params,
        experiment=experiment,
        solver=solver,
    )

    # ----------------------------------------------------------
    # Solve full protocol
    # ----------------------------------------------------------
    tic = time.perf_counter()

    solution = sim.solve(
        initial_soc=f"{V0:.5f} V",
        calc_esoh=False,
    )

    runtime_s = time.perf_counter() - tic

    # ----------------------------------------------------------
    # Per-rate comparison (V(Q) capacity aligned)
    # ----------------------------------------------------------
    out_dir = ensure_dir(output_dir) if output_dir is not None else None

    rows = []
    rate_curves = {}

    for rate in rates:

        # A: canonical rate quintuple (slug names files; `rate`
        # column keeps the legacy label for regression compat)
        info = adapter.rate_info(rate)

        cycle_index = RATE_CYCLE_INDEX[rate]
        rate_current = RATE_CURRENT_A[rate]

        # Experimental discharge from the adapter
        exp = adapter.load_discharge(cell, rate)

        t_exp = exp["time_s"].to_numpy(dtype=float)
        q_exp = exp["capacity_Ah"].to_numpy(dtype=float)
        V_exp = exp["voltage_V"].to_numpy(dtype=float)

        # Simulated discharge from the command-level solution
        t_sim, q_sim, V_sim = extract_discharge(
            solution,
            cycle_index,
            rate_current,
        )

        row = metrics_for_discharge(
            q_exp,
            V_exp,
            q_sim,
            V_sim,
            t_exp=t_exp,
            t_sim=t_sim,
        )

        row = {
            "cell": cell,
            "model": model_name.upper(),
            # legacy compat label (cross-dataset groupby must use
            # c_rate, not this string)
            "rate": rate,
            "c_rate": float(info["c_rate"]),
            "rate_label": str(info["rate_label"]),
            "rate_slug": str(info["rate_slug"]),
            "source_rate": str(info["source_rate"]),
            **row,
        }

        rows.append(row)

        rate_curves[rate] = {
            "q_exp": q_exp,
            "V_exp": V_exp,
            "q_sim": q_sim,
            "V_sim": V_sim,
        }

        if not quiet:
            print(
                f"{rate:5s} | "
                f"RMSE(Q)={row['rmse_Qaligned_mV']:7.2f} mV | "
                f"Qexp={row['Q_exp_Ah']:.3f} Ah | "
                f"Qsim={row['Q_sim_Ah']:.3f} Ah | "
                f"dQ={row['cutoff_capacity_error_pct']:+6.2f}% | "
                f"dt={row.get('cutoff_time_error_pct', float('nan')):+6.2f}%"
            )


        # ------------------------------------------------------
        # Per-rate comparison table + V-Q plot
        # (files named by the canonical rate_slug)
        # ------------------------------------------------------
        if out_dir is not None:
            rate_slug = str(info["rate_slug"])

            q_common, V_exp_c, V_sim_c, error = compare_q_aligned(
                q_exp,
                V_exp,
                q_sim,
                V_sim,
            )

            pd.DataFrame(
                {
                    "capacity_Ah": q_common,
                    "voltage_exp_V": V_exp_c,
                    "voltage_sim_V": V_sim_c,
                    "residual_V": error,
                }
            ).to_csv(
                out_dir / f"{rate_slug}_capacity_aligned.csv",
                index=False,
            )

            if plot:
                save_voltage_comparison(
                    q_exp,
                    V_exp,
                    q_sim,
                    V_sim,
                    out_dir / f"{rate_slug}_VQ.png",
                    cell=f"cell{cell}",
                    rate=rate,
                    model=model_name.upper(),
                    rmse_mV=row["rmse_Qaligned_mV"],
                )

    metrics = pd.DataFrame(rows)

    # ----------------------------------------------------------
    # Standard outputs: metrics.csv + run_metadata.json
    # ----------------------------------------------------------
    if out_dir is not None:
        metrics.to_csv(
            out_dir / "metrics.csv",
            index=False,
        )

        with open(
            out_dir / "run_metadata.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "dataset": adapter.config.dataset_id,
                    "model": model_name.upper(),
                    "cell": cell,
                    "mode": "reproduction",
                    "parameter_set": parameter_set,
                    # v0.2: chemistry-parameter compatibility block
                    # (dataset-agnostic merge from the adapter).
                    "parameter_match": (
                        adapter.get_metadata().get("parameter_match")
                    ),
                    "initial_voltage_V": V0,
                    "ambient_temperature_C": tamb_C,
                    "pybamm_version": pybamm.__version__,
                    "timestamp": _timestamp(),
                    "runtime_s": runtime_s,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    return {
        "metrics": metrics,
        "output_dir": out_dir,
        "initial_voltage_V": V0,
        "ambient_temperature_C": tamb_C,
        "runtime_s": runtime_s,
        "rate_curves": rate_curves,
    }


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
