#!/usr/bin/env python3

from pathlib import Path
import argparse
import json
import time

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pybamm


ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = (
    ROOT
    / "data"
    / "processed"
    / "LIB"
    / "NMC_Graphite"
    / "Chen2020_LGM50"
)

OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "baseline"
    / "Chen2020_LGM50"
)


def create_model(name):

    name = name.upper()

    if name == "SPM":
        return pybamm.lithium_ion.SPM()

    if name == "SPME":
        return pybamm.lithium_ion.SPMe()

    if name == "DFN":
        return pybamm.lithium_ion.DFN()

    raise ValueError(
        f"Unsupported model: {name}"
    )


def integrate_capacity(t, current):

    try:
        return float(
            np.trapezoid(current, t) / 3600
        )
    except AttributeError:
        return float(
            np.trapz(current, t) / 3600
        )


def run_one(
    csv_path: Path,
    model_name: str,
):

    df = pd.read_csv(csv_path)

    t_exp = df["time_s"].to_numpy(
        dtype=float
    )

    I_exp = df["current_A"].to_numpy(
        dtype=float
    )

    V_exp = df["voltage_V"].to_numpy(
        dtype=float
    )

    # Ensure strictly increasing time
    valid = np.concatenate(
        (
            [True],
            np.diff(t_exp) > 0,
        )
    )

    t_exp = t_exp[valid]
    I_exp = I_exp[valid]
    V_exp = V_exp[valid]

    # Current data do not need thousands of points
    if len(t_exp) > 2000:

        idx = np.linspace(
            0,
            len(t_exp) - 1,
            2000,
            dtype=int,
        )

        idx = np.unique(idx)

        t_exp = t_exp[idx]
        I_exp = I_exp[idx]
        V_exp = V_exp[idx]

    model = create_model(
        model_name
    )

    params = pybamm.ParameterValues(
        "Chen2020"
    )

    ambient_C = float(
        df["temperature_ambient_C"]
        .dropna()
        .median()
    )

    ambient_K = (
        ambient_C + 273.15
    )

    # Use chamber temperature as physical ambient condition
    if "Ambient temperature [K]" in params:
        params[
            "Ambient temperature [K]"
        ] = ambient_K

    if "Initial temperature [K]" in params:
        params[
            "Initial temperature [K]"
        ] = ambient_K

    # Real experimental current trace
    current_function = pybamm.Interpolant(
        t_exp,
        I_exp,
        pybamm.t,
    )

    params[
        "Current function [A]"
    ] = current_function

    simulation = pybamm.Simulation(
        model,
        parameter_values=params,
    )

    tic = time.perf_counter()

    solution = simulation.solve(
        t_eval=t_exp,
        initial_soc=1.0,
    )

    runtime_s = (
        time.perf_counter() - tic
    )

    t_sim = np.asarray(
        solution.t,
        dtype=float,
    )

    try:
        V_sim = np.asarray(
            solution[
                "Terminal voltage [V]"
            ].entries,
            dtype=float,
        )
    except KeyError:
        V_sim = np.asarray(
            solution[
                "Voltage [V]"
            ].entries,
            dtype=float,
        )

    # PyBaMM can terminate at lower-voltage event
    common_end = min(
        float(t_exp[-1]),
        float(t_sim[-1]),
    )

    mask = (
        t_exp <= common_end
    )

    t_common = t_exp[mask]
    V_exp_common = V_exp[mask]

    V_sim_common = np.interp(
        t_common,
        t_sim,
        V_sim,
    )

    residual = (
        V_sim_common - V_exp_common
    )

    rmse = float(
        np.sqrt(
            np.mean(residual ** 2)
        )
    )

    mae = float(
        np.mean(
            np.abs(residual)
        )
    )

    max_abs_error = float(
        np.max(
            np.abs(residual)
        )
    )

    coverage = float(
        common_end / t_exp[-1]
    )

    Q_exp_integrated = (
        integrate_capacity(
            t_exp,
            I_exp,
        )
    )

    Q_exp_reported = float(
        df["capacity_Ah"]
        .dropna()
        .iloc[-1]
    )

    try:
        Q_sim = float(
            solution[
                "Discharge capacity [A.h]"
            ].entries[-1]
        )
    except Exception:
        Q_sim = np.nan

    capacity_error_pct = (
        100
        * (Q_sim - Q_exp_reported)
        / Q_exp_reported
        if np.isfinite(Q_sim)
        else np.nan
    )

    median_current = float(
        np.median(I_exp)
    )

    nominal_capacity = float(
        params[
            "Nominal cell capacity [A.h]"
        ]
    )

    c_rate = (
        median_current
        / nominal_capacity
    )

    metrics = {
        "file": csv_path.name,
        "model": model_name.upper(),
        "parameter_set": "Chen2020",

        "ambient_temperature_C":
            ambient_C,

        "median_current_A":
            median_current,

        "c_rate":
            c_rate,

        "rmse_V":
            rmse,

        "rmse_mV":
            rmse * 1000,

        "mae_V":
            mae,

        "mae_mV":
            mae * 1000,

        "max_abs_error_V":
            max_abs_error,

        "coverage_fraction":
            coverage,

        "capacity_exp_reported_Ah":
            Q_exp_reported,

        "capacity_exp_integrated_Ah":
            Q_exp_integrated,

        "capacity_sim_Ah":
            Q_sim,

        "capacity_error_pct":
            capacity_error_pct,

        "runtime_s":
            runtime_s,

        "experimental_duration_s":
            float(t_exp[-1]),

        "simulation_duration_s":
            float(t_sim[-1]),

        "n_comparison_points":
            int(len(t_common)),
    }

    comparison = pd.DataFrame({
        "time_s":
            t_common,

        "voltage_exp_V":
            V_exp_common,

        "voltage_sim_V":
            V_sim_common,

        "residual_V":
            residual,
    })

    return comparison, metrics


def save_results(
    comparison,
    metrics,
    output_dir: Path,
):

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    comparison.to_csv(
        output_dir
        / "comparison.csv",
        index=False,
    )

    with open(
        output_dir
        / "metrics.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            metrics,
            f,
            indent=2,
            ensure_ascii=False,
        )

    fig, ax = plt.subplots(
        figsize=(7.2, 5.2)
    )

    ax.plot(
        comparison["time_s"] / 3600,
        comparison["voltage_exp_V"],
        label="Experiment",
        linewidth=1.8,
    )

    ax.plot(
        comparison["time_s"] / 3600,
        comparison["voltage_sim_V"],
        label=f'PyBaMM {metrics["model"]}',
        linewidth=1.6,
    )

    ax.set_xlabel(
        "Time [h]"
    )

    ax.set_ylabel(
        "Terminal voltage [V]"
    )

    ax.set_title(
        f'{metrics["file"]}\n'
        f'{metrics["model"]}, '
        f'{metrics["c_rate"]:.2f}C, '
        f'RMSE={metrics["rmse_mV"]:.1f} mV'
    )

    ax.legend()

    fig.tight_layout()

    fig.savefig(
        output_dir
        / "voltage_comparison.png",
        dpi=250,
    )

    plt.close(fig)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        choices=[
            "SPM",
            "SPMe",
            "DFN",
        ],
        default="SPMe",
    )

    parser.add_argument(
        "--cell",
        default="02",
        help="02, 03, 04 or all",
    )

    parser.add_argument(
        "--rate",
        default="all",
        choices=[
            "C10",
            "C2",
            "1C",
            "1p5C",
            "all",
        ],
    )

    args = parser.parse_args()

    if args.cell == "all":
        cells = [
            "02",
            "03",
            "04",
        ]
    else:
        cells = [
            args.cell
        ]

    rates = (
        [
            "C10",
            "C2",
            "1C",
            "1p5C",
        ]
        if args.rate == "all"
        else [args.rate]
    )

    all_metrics = []

    print("=" * 72)
    print("Chen2020 → PyBaMM baseline")
    print("=" * 72)
    print(
        "PyBaMM version:",
        pybamm.__version__,
    )
    print(
        "Model:",
        args.model,
    )
    print("=" * 72)

    for cell in cells:

        for rate in rates:

            csv_path = (
                DATA_DIR
                / f"LGM50_cell{cell}_{rate}.csv"
            )

            if not csv_path.exists():

                print(
                    "[MISSING]",
                    csv_path,
                )

                continue

            print(
                f"\n[RUN] Cell {cell} "
                f"| {rate} "
                f"| {args.model}"
            )

            try:

                comparison, metrics = (
                    run_one(
                        csv_path,
                        args.model,
                    )
                )

            except Exception as exc:

                print(
                    "[FAILED]",
                    type(exc).__name__,
                    str(exc),
                )

                continue

            output_dir = (
                OUTPUT_ROOT
                / args.model.upper()
                / f"cell{cell}"
                / rate
            )

            save_results(
                comparison,
                metrics,
                output_dir,
            )

            all_metrics.append(
                metrics
            )

            print(
                f"  RMSE    : "
                f"{metrics['rmse_mV']:.2f} mV"
            )

            print(
                f"  MAE     : "
                f"{metrics['mae_mV']:.2f} mV"
            )

            print(
                f"  Coverage: "
                f"{metrics['coverage_fraction']*100:.1f}%"
            )

            print(
                f"  Qexp    : "
                f"{metrics['capacity_exp_reported_Ah']:.3f} Ah"
            )

            print(
                f"  Qsim    : "
                f"{metrics['capacity_sim_Ah']:.3f} Ah"
            )

            print(
                f"  Runtime : "
                f"{metrics['runtime_s']:.2f} s"
            )

    if all_metrics:

        summary = pd.DataFrame(
            all_metrics
        )

        summary_dir = (
            OUTPUT_ROOT
            / args.model.upper()
        )

        summary_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        summary_path = (
            summary_dir
            / "baseline_summary.csv"
        )

        summary.to_csv(
            summary_path,
            index=False,
        )

        print("\n" + "=" * 72)
        print(
            "[SUMMARY]",
            summary_path,
        )

        cols = [
            "file",
            "model",
            "c_rate",
            "rmse_mV",
            "mae_mV",
            "coverage_fraction",
            "capacity_error_pct",
            "runtime_s",
        ]

        print(
            summary[cols]
            .to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()
