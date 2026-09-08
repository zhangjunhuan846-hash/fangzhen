# ============================================================
# Battery Dataset Simulation Platform v0.1
# Sensitivity runner (Step 10)
#
# Wraps the already-validated local OAT screening logic of:
#   scripts/sensitivity/sensitivity_screen.py
#
# v0.1 scope (exactly, nothing more):
#   * 9 first-stage parameters: Dsn Dsp j0n j0p De kappa_e Rn Rp brug_e
#   * factors 0.8 / 1.2
#   * model-output metrics preserved:
#         voltage_rms_shift_mV        (V(Q) shift vs baseline)
#         cutoff_capacity_shift_pct   (Q_sim shift vs baseline)
#         rmse_mV / capacity_error_pct (absolute model-vs-experiment)
#   * NO rmse-change-as-sensitivity, NO Sobol, NO thermodynamic screen.
#
# The old entry point scripts/sensitivity/sensitivity_screen.py is
# left untouched and still runnable.  This module implements the
# same screen on top of the platform's validated components
# (adapter / factory / protocol / evaluation).
#
# Outputs (outputs/platform/<dataset>/sensitivity/<MODEL>/cell<cell>/):
#   oat_raw_metrics.csv
#   oat_model_response.csv
#   oat_parameter_ranking.csv
#   oat_rate_sensitivity_matrix.csv
#   run_metadata.json
# ============================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import pybamm

from battery_sim.config import load_sensitivity_config
from battery_sim.evaluation.metrics import (
    compare_q_aligned,
    extract_discharge,
)
from battery_sim.logging_utils import timestamp_utc
from battery_sim.models.pybamm_factory import (
    build_model,
    load_parameter_values,
)
from battery_sim.paths import ensure_dir, platform_output_dir
from battery_sim.protocols.chen2020 import (
    RATE_CURRENT_A,
    RATE_CYCLE_INDEX,
    build_experiment,
)


# ------------------------------------------------------------------
# Parameter spec loading (single source: configs/sensitivity.yaml)
# ------------------------------------------------------------------
def load_parameter_specs() -> Dict[str, dict]:
    cfg = load_sensitivity_config()
    return {
        str(name): {
            "label": str(entry.get("label", name)),
            "group": str(entry.get("group", "")),
            "keys": [str(k) for k in entry.get("keys", [])],
        }
        for name, entry in cfg["parameters"].items()
    }


def load_factors() -> tuple:
    cfg = load_sensitivity_config()
    return float(cfg["factors"]["low"]), float(cfg["factors"]["high"])


# ------------------------------------------------------------------
# Parameter perturbation (verbatim reference semantics)
# ------------------------------------------------------------------
def scale_value(value, factor):
    """Multiply a scalar or a PyBaMM parameter function by factor."""
    if callable(value):
        original = value

        def scaled_function(*args, **kwargs):
            return factor * original(*args, **kwargs)

        return scaled_function
    return value * factor


def perturb_parameters(params, spec: dict, factor: float) -> None:
    for key in spec["keys"]:
        original = params[key]
        params.update({key: scale_value(original, factor)})


# ------------------------------------------------------------------
# One full command-level experiment (baseline or perturbed)
# ------------------------------------------------------------------
def _solve_case(
    adapter,
    cfg,
    model_name: str,
    cell: str,
    parameter_name: Optional[str],
    factor: float,
    param_specs: Dict[str, dict],
    rates: List[str],
):
    """Solve the full protocol once; return (metrics_df, curves_dict)."""
    V0 = float(adapter.get_initial_state(cell))
    tamb_C = float(adapter.get_ambient_temperature(cell))

    params = load_parameter_values(cfg.parameter_set)
    params.update(
        {
            "Ambient temperature [K]": tamb_C + 273.15,
            "Initial temperature [K]": tamb_C + 273.15,
        }
    )

    if parameter_name is not None:
        perturb_parameters(params, param_specs[parameter_name], factor)

    model = build_model(model_name)
    experiment = build_experiment()
    solver = pybamm.IDAKLUSolver(rtol=1e-6, atol=1e-6)

    sim = pybamm.Simulation(
        model,
        parameter_values=params,
        experiment=experiment,
        solver=solver,
    )

    tic = time.perf_counter()
    sol = sim.solve(initial_soc=f"{V0:.5f} V", calc_esoh=False)
    runtime_s = time.perf_counter() - tic

    rows = []
    curves: Dict[str, dict] = {}

    for rate in rates:
        exp = adapter.load_discharge(cell, rate)
        q_exp = exp["capacity_Ah"].to_numpy(dtype=float)
        V_exp = exp["voltage_V"].to_numpy(dtype=float)

        cycle_index = RATE_CYCLE_INDEX[rate]
        rate_current = RATE_CURRENT_A[rate]

        _, q_sim, V_sim = extract_discharge(
            sol,
            cycle_index,
            rate_current,
        )

        _, _, _, error = compare_q_aligned(q_exp, V_exp, q_sim, V_sim)

        Q_exp = float(q_exp[-1])
        Q_sim = float(q_sim[-1])

        rows.append(
            {
                "parameter": parameter_name if parameter_name else "BASELINE",
                "factor": factor,
                "rate": rate,
                "rmse_mV": float(np.sqrt(np.mean(error ** 2))) * 1000.0,
                "mae_mV": float(np.mean(np.abs(error))) * 1000.0,
                "bias_mV": float(np.mean(error)) * 1000.0,
                "Q_exp_Ah": Q_exp,
                "Q_sim_Ah": Q_sim,
                "capacity_error_pct": (
                    100.0 * (Q_sim - Q_exp) / Q_exp
                ),
                "runtime_s": runtime_s,
            }
        )

        curves[rate] = {
            "q_sim": np.asarray(q_sim, dtype=float),
            "V_sim": np.asarray(V_sim, dtype=float),
        }

    return pd.DataFrame(rows), curves, V0, tamb_C, runtime_s


def voltage_shift_vs_baseline(baseline_curve, perturbed_curve) -> float:
    """RMS V(Q) shift (mV) between baseline and perturbed sim curves."""
    qb = baseline_curve["q_sim"]
    vb = baseline_curve["V_sim"]
    qp = perturbed_curve["q_sim"]
    vp = perturbed_curve["V_sim"]

    q_end = min(float(qb[-1]), float(qp[-1]))
    if q_end <= 0:
        return float("nan")

    q_grid = np.linspace(0, q_end, 400)

    vb_i = np.interp(q_grid, qb, vb)
    vp_i = np.interp(q_grid, qp, vp)

    delta = vp_i - vb_i
    return float(np.sqrt(np.mean(delta ** 2)) * 1000.0)


# ------------------------------------------------------------------
# Public runner
# ------------------------------------------------------------------
def run_sensitivity(
    adapter,
    cfg,
    model_name: str,
    cell: str,
    parameter: str = "all",
    quiet: bool = False,
) -> Path:
    """
    Local OAT sensitivity screen for one (model, cell).

    ``parameter`` is one of the 9 ids or ``all``.
    Returns the output directory (files written).
    """
    param_specs = load_parameter_specs()
    low, high = load_factors()

    if parameter == "all":
        parameter_names = list(param_specs.keys())
    else:
        if parameter not in param_specs:
            raise ValueError(
                f"Unknown sensitivity parameter: '{parameter}'. "
                f"Valid: all, {', '.join(param_specs.keys())}"
            )
        parameter_names = [parameter]

    rates = list(adapter.list_rates())

    out_dir = ensure_dir(
        platform_output_dir(
            adapter.config.dataset_id,
            "sensitivity",
            model_name,
            cell,
        )
    )

    if not quiet:
        print(f"Sensitivity: {model_name.upper()} cell{cell} "
              f"| factors {low}/{high} | {len(parameter_names)} param(s)")

    # ----------------------------------------------------------
    # Baseline (factor = 1.0, no perturbation)
    # ----------------------------------------------------------
    baseline_df, baseline_curves, V0, tamb_C, _ = _solve_case(
        adapter,
        cfg,
        model_name,
        cell,
        parameter_name=None,
        factor=1.0,
        param_specs=param_specs,
        rates=rates,
    )

    all_rows = [baseline_df]
    response_rows = []

    baseline_qsim = {
        row["rate"]: row["Q_sim_Ah"]
        for _, row in baseline_df.iterrows()
    }

    # ----------------------------------------------------------
    # OAT perturbations
    # ----------------------------------------------------------
    total_cases = len(parameter_names) * 2
    case_i = 0

    for name in parameter_names:
        spec = param_specs[name]

        for factor in (low, high):
            case_i += 1

            if not quiet:
                print(
                    f"[{case_i}/{total_cases}] {name} "
                    f"({spec['label']}) x {factor:.2f}",
                    flush=True,
                )

            result_df, curves, *_ = _solve_case(
                adapter,
                cfg,
                model_name,
                cell,
                parameter_name=name,
                factor=factor,
                param_specs=param_specs,
                rates=rates,
            )

            all_rows.append(result_df)

            for rate in rates:
                shift_mV = voltage_shift_vs_baseline(
                    baseline_curves[rate],
                    curves[rate],
                )

                row = result_df[result_df["rate"] == rate].iloc[0]

                q_shift_pct = (
                    100.0
                    * (row["Q_sim_Ah"] - baseline_qsim[rate])
                    / baseline_qsim[rate]
                )

                response_rows.append(
                    {
                        "parameter": name,
                        "label": spec["label"],
                        "group": spec["group"],
                        "factor": factor,
                        "rate": rate,
                        "voltage_rms_shift_mV": shift_mV,
                        "cutoff_capacity_shift_pct": q_shift_pct,
                        "rmse_mV": row["rmse_mV"],
                        "capacity_error_pct": row["capacity_error_pct"],
                    }
                )

    # ----------------------------------------------------------
    # Assemble + save
    # ----------------------------------------------------------
    raw_df = pd.concat(all_rows, ignore_index=True)
    raw_df.to_csv(out_dir / "oat_raw_metrics.csv", index=False)

    response_df = pd.DataFrame(response_rows)
    response_df.to_csv(out_dir / "oat_model_response.csv", index=False)

    ranking = (
        response_df.groupby(["parameter", "label", "group"])
        .agg(
            mean_voltage_shift_mV=("voltage_rms_shift_mV", "mean"),
            max_voltage_shift_mV=("voltage_rms_shift_mV", "max"),
            mean_abs_capacity_shift_pct=(
                "cutoff_capacity_shift_pct",
                lambda x: np.mean(np.abs(x)),
            ),
            max_abs_capacity_shift_pct=(
                "cutoff_capacity_shift_pct",
                lambda x: np.max(np.abs(x)),
            ),
        )
        .reset_index()
        .sort_values("mean_voltage_shift_mV", ascending=False)
    )
    ranking.to_csv(out_dir / "oat_parameter_ranking.csv", index=False)

    rate_matrix = (
        response_df.groupby(["parameter", "rate"])["voltage_rms_shift_mV"]
        .max()
        .unstack("rate")
        .reindex(columns=rates)
    )
    rate_matrix["mean"] = rate_matrix.mean(axis=1)
    rate_matrix = rate_matrix.sort_values("mean", ascending=False)
    rate_matrix.to_csv(out_dir / "oat_rate_sensitivity_matrix.csv")

    metadata = {
        "dataset": adapter.config.dataset_id,
        "model": model_name.upper(),
        "cell": cell,
        "mode": "sensitivity",
        "parameter_set": cfg.parameter_set,
        "parameters": parameter_names,
        "factors": {"low": low, "high": high},
        "rates": rates,
        "initial_voltage_V": V0,
        "ambient_temperature_C": tamb_C,
        "pybamm_version": pybamm.__version__,
        "timestamp": timestamp_utc(),
        "note": (
            "Local OAT wrapper of "
            "scripts/sensitivity/sensitivity_screen.py; metrics "
            "voltage_rms_shift_mV / cutoff_capacity_shift_pct / rmse_mV"
        ),
    }

    with open(
        out_dir / "run_metadata.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    if not quiet:
        print("\nPARAMETER RANKING (mean voltage shift [mV])")
        print(
            ranking[["parameter", "label", "group",
                     "mean_voltage_shift_mV"]].to_string(
                index=False,
                float_format=lambda x: f"{x:.3f}",
            )
        )

    return out_dir


if __name__ == "__main__":  # pragma: no cover - CLI is run_pipeline.py
    raise SystemExit("Use: python run_pipeline.py --mode sensitivity ...")
