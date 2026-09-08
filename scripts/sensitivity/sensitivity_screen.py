#!/usr/bin/env python3

from pathlib import Path
import argparse
import time
import sys

import numpy as np
import pandas as pd
import pybamm


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# Reuse the already validated command-level protocol code
from scripts.runners.command_reproduction import (
    load_raw,
    initial_voltage,
    ambient_temperature,
    create_model,
    build_experiment,
    experimental_discharge,
    simulated_discharge,
    compare_q_aligned,
)


OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "sensitivity"
    / "Chen2020_LGM50"
)


# ============================================================
# First-stage screening parameters
# ============================================================

PARAMETERS = {

    "Dsn": {
        "label": "Negative particle diffusivity",
        "keys": [
            "Negative particle diffusivity [m2.s-1]",
        ],
        "group": "solid_transport",
    },

    "Dsp": {
        "label": "Positive particle diffusivity",
        "keys": [
            "Positive particle diffusivity [m2.s-1]",
        ],
        "group": "solid_transport",
    },

    "j0n": {
        "label": "Negative exchange-current density",
        "keys": [
            "Negative electrode exchange-current density [A.m-2]",
        ],
        "group": "kinetics",
    },

    "j0p": {
        "label": "Positive exchange-current density",
        "keys": [
            "Positive electrode exchange-current density [A.m-2]",
        ],
        "group": "kinetics",
    },

    "De": {
        "label": "Electrolyte diffusivity",
        "keys": [
            "Electrolyte diffusivity [m2.s-1]",
        ],
        "group": "electrolyte_transport",
    },

    "kappa_e": {
        "label": "Electrolyte conductivity",
        "keys": [
            "Electrolyte conductivity [S.m-1]",
        ],
        "group": "electrolyte_transport",
    },

    "Rn": {
        "label": "Negative particle radius",
        "keys": [
            "Negative particle radius [m]",
        ],
        "group": "microstructure",
    },

    "Rp": {
        "label": "Positive particle radius",
        "keys": [
            "Positive particle radius [m]",
        ],
        "group": "microstructure",
    },

    "brug_e": {
        "label": "Electrolyte Bruggeman coefficients",
        "keys": [
            "Negative electrode Bruggeman coefficient (electrolyte)",
            "Separator Bruggeman coefficient (electrolyte)",
            "Positive electrode Bruggeman coefficient (electrolyte)",
        ],
        "group": "electrolyte_transport",
    },
}


RATES = [
    "C10",
    "C2",
    "1C",
    "1p5C",
]


# ============================================================
# Parameter scaling
# ============================================================

def scale_value(value, factor):
    """
    Safely multiply either a scalar or a PyBaMM parameter function.
    """

    if callable(value):

        original = value

        def scaled_function(*args, **kwargs):
            return factor * original(
                *args,
                **kwargs,
            )

        return scaled_function

    else:
        return value * factor


def perturb_parameters(
    params,
    parameter_name,
    factor,
):

    spec = PARAMETERS[
        parameter_name
    ]

    for key in spec["keys"]:

        original = params[key]

        params.update({
            key: scale_value(
                original,
                factor,
            )
        })


# ============================================================
# Run one full command-level experiment
# ============================================================

def run_parameter_case(
    cell,
    model_name,
    parameter_name=None,
    factor=1.0,
):

    _, raw = load_raw(cell)

    V0 = initial_voltage(raw)

    Tamb_C = ambient_temperature(
        raw
    )

    params = pybamm.ParameterValues(
        "Chen2020"
    )

    params.update({
        "Ambient temperature [K]":
            Tamb_C + 273.15,

        "Initial temperature [K]":
            Tamb_C + 273.15,
    })

    if parameter_name is not None:

        perturb_parameters(
            params,
            parameter_name,
            factor,
        )

    model = create_model(
        model_name
    )

    experiment = build_experiment()

    solver = pybamm.IDAKLUSolver(
        rtol=1e-6,
        atol=1e-6,
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=params,
        experiment=experiment,
        solver=solver,
    )

    tic = time.perf_counter()

    sol = sim.solve(
        initial_soc=f"{V0:.5f} V",
        calc_esoh=False,
    )

    runtime_s = (
        time.perf_counter()
        - tic
    )

    metrics = []
    curves = {}

    for rate in RATES:

        (
            t_exp,
            q_exp,
            V_exp,
        ) = experimental_discharge(
            raw,
            rate,
        )

        (
            t_sim,
            q_sim,
            V_sim,
        ) = simulated_discharge(
            sol,
            rate,
        )

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

        rmse_mV = (
            np.sqrt(
                np.mean(error ** 2)
            )
            * 1000
        )

        mae_mV = (
            np.mean(
                np.abs(error)
            )
            * 1000
        )

        bias_mV = (
            np.mean(error)
            * 1000
        )

        Q_exp = float(
            q_exp[-1]
        )

        Q_sim = float(
            q_sim[-1]
        )

        Q_error_pct = (
            100
            * (Q_sim - Q_exp)
            / Q_exp
        )

        metrics.append({
            "parameter":
                (
                    parameter_name
                    if parameter_name
                    else "BASELINE"
                ),

            "factor":
                factor,

            "rate":
                rate,

            "rmse_mV":
                float(rmse_mV),

            "mae_mV":
                float(mae_mV),

            "bias_mV":
                float(bias_mV),

            "Q_exp_Ah":
                Q_exp,

            "Q_sim_Ah":
                Q_sim,

            "capacity_error_pct":
                float(Q_error_pct),

            "runtime_s":
                runtime_s,
        })

        curves[rate] = {
            "q_sim":
                np.asarray(
                    q_sim,
                    dtype=float,
                ),

            "V_sim":
                np.asarray(
                    V_sim,
                    dtype=float,
                ),
        }

    return (
        pd.DataFrame(metrics),
        curves,
    )


# ============================================================
# True model-output sensitivity
# ============================================================

def voltage_shift_vs_baseline(
    baseline_curve,
    perturbed_curve,
):

    qb = baseline_curve[
        "q_sim"
    ]

    vb = baseline_curve[
        "V_sim"
    ]

    qp = perturbed_curve[
        "q_sim"
    ]

    vp = perturbed_curve[
        "V_sim"
    ]

    q_end = min(
        float(qb[-1]),
        float(qp[-1]),
    )

    if q_end <= 0:
        return np.nan

    q_grid = np.linspace(
        0,
        q_end,
        400,
    )

    vb_i = np.interp(
        q_grid,
        qb,
        vb,
    )

    vp_i = np.interp(
        q_grid,
        qp,
        vp,
    )

    delta = (
        vp_i - vb_i
    )

    return float(
        np.sqrt(
            np.mean(delta ** 2)
        )
        * 1000
    )


# ============================================================
# Main screening
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--cell",
        default="02",
        choices=[
            "02",
            "03",
            "04",
        ],
    )

    parser.add_argument(
        "--model",
        default="SPMe",
        choices=[
            "SPMe",
            "DFN",
        ],
    )

    parser.add_argument(
        "--low",
        type=float,
        default=0.8,
    )

    parser.add_argument(
        "--high",
        type=float,
        default=1.2,
    )

    parser.add_argument(
        "--parameter",
        default="all",
        help=(
            "all, Dsn, Dsp, j0n, j0p, "
            "De, kappa_e, Rn, Rp, brug_e"
        ),
    )

    args = parser.parse_args()

    if args.parameter == "all":

        parameter_names = list(
            PARAMETERS.keys()
        )

    else:

        if (
            args.parameter
            not in PARAMETERS
        ):
            raise ValueError(
                f"Unknown parameter: "
                f"{args.parameter}"
            )

        parameter_names = [
            args.parameter
        ]

    output_dir = (
        OUTPUT_ROOT
        / args.model.upper()
        / f"cell{args.cell}"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 100)
    print(
        "Chen2020 local OAT sensitivity screening"
    )
    print("=" * 100)

    print(
        "PyBaMM:",
        pybamm.__version__,
    )

    print(
        "Model:",
        args.model
    )

    print(
        "Cell:",
        args.cell
    )

    print(
        "Factors:",
        args.low,
        args.high,
    )

    print(
        "Parameters:",
        ", ".join(
            parameter_names
        )
    )

    # ========================================================
    # Baseline
    # ========================================================

    print("\n[BASELINE]")

    (
        baseline_df,
        baseline_curves,
    ) = run_parameter_case(
        args.cell,
        args.model,
        parameter_name=None,
        factor=1.0,
    )

    all_rows = [
        baseline_df
    ]

    response_rows = []

    baseline_qsim = {
        row["rate"]:
            row["Q_sim_Ah"]
        for _, row
        in baseline_df.iterrows()
    }

    # ========================================================
    # Perturbations
    # ========================================================

    total_cases = (
        len(parameter_names)
        * 2
    )

    case_i = 0

    for name in parameter_names:

        spec = PARAMETERS[name]

        for factor in [
            args.low,
            args.high,
        ]:

            case_i += 1

            print(
                f"\n[{case_i}/{total_cases}] "
                f"{name} "
                f"({spec['label']}) "
                f"x {factor:.2f}"
            )

            try:

                (
                    result_df,
                    curves,
                ) = run_parameter_case(
                    args.cell,
                    args.model,
                    parameter_name=name,
                    factor=factor,
                )

            except Exception as exc:

                print(
                    "[FAILED]",
                    type(exc).__name__,
                    str(exc),
                )

                continue

            all_rows.append(
                result_df
            )

            for rate in RATES:

                shift_mV = (
                    voltage_shift_vs_baseline(
                        baseline_curves[
                            rate
                        ],
                        curves[
                            rate
                        ],
                    )
                )

                row = result_df[
                    result_df["rate"]
                    == rate
                ].iloc[0]

                q_shift_pct = (
                    100
                    * (
                        row["Q_sim_Ah"]
                        - baseline_qsim[
                            rate
                        ]
                    )
                    / baseline_qsim[
                        rate
                    ]
                )

                response_rows.append({
                    "parameter":
                        name,

                    "label":
                        spec["label"],

                    "group":
                        spec["group"],

                    "factor":
                        factor,

                    "rate":
                        rate,

                    "voltage_rms_shift_mV":
                        shift_mV,

                    "cutoff_capacity_shift_pct":
                        q_shift_pct,

                    "rmse_mV":
                        row["rmse_mV"],

                    "capacity_error_pct":
                        row[
                            "capacity_error_pct"
                        ],
                })

            print(
                result_df[
                    [
                        "rate",
                        "rmse_mV",
                        "capacity_error_pct",
                    ]
                ].to_string(
                    index=False,
                    float_format=lambda x:
                        f"{x:.2f}",
                )
            )

    # ========================================================
    # Save raw results
    # ========================================================

    raw_df = pd.concat(
        all_rows,
        ignore_index=True,
    )

    raw_df.to_csv(
        output_dir
        / "oat_raw_metrics.csv",
        index=False,
    )

    response_df = pd.DataFrame(
        response_rows
    )

    response_df.to_csv(
        output_dir
        / "oat_model_response.csv",
        index=False,
    )

    # ========================================================
    # Ranking
    # ========================================================

    ranking = (
        response_df
        .groupby(
            [
                "parameter",
                "label",
                "group",
            ]
        )
        .agg(
            mean_voltage_shift_mV=(
                "voltage_rms_shift_mV",
                "mean",
            ),

            max_voltage_shift_mV=(
                "voltage_rms_shift_mV",
                "max",
            ),

            mean_abs_capacity_shift_pct=(
                "cutoff_capacity_shift_pct",
                lambda x:
                    np.mean(
                        np.abs(x)
                    ),
            ),

            max_abs_capacity_shift_pct=(
                "cutoff_capacity_shift_pct",
                lambda x:
                    np.max(
                        np.abs(x)
                    ),
            ),
        )
        .reset_index()
        .sort_values(
            "mean_voltage_shift_mV",
            ascending=False,
        )
    )

    ranking.to_csv(
        output_dir
        / "oat_parameter_ranking.csv",
        index=False,
    )

    # ========================================================
    # Rate × parameter matrix
    # ========================================================

    rate_matrix = (
        response_df
        .groupby(
            [
                "parameter",
                "rate",
            ]
        )[
            "voltage_rms_shift_mV"
        ]
        .max()
        .unstack("rate")
        .reindex(
            columns=RATES
        )
    )

    rate_matrix[
        "mean"
    ] = rate_matrix.mean(
        axis=1
    )

    rate_matrix = (
        rate_matrix
        .sort_values(
            "mean",
            ascending=False,
        )
    )

    rate_matrix.to_csv(
        output_dir
        / "oat_rate_sensitivity_matrix.csv"
    )

    print("\n" + "=" * 100)
    print(
        "PARAMETER RANKING"
    )
    print("=" * 100)

    print(
        ranking.to_string(
            index=False,
            float_format=lambda x:
                f"{x:.3f}",
        )
    )

    print("\n" + "=" * 100)
    print(
        "RATE × PARAMETER "
        "VOLTAGE RESPONSE [mV]"
    )
    print("=" * 100)

    print(
        rate_matrix.to_string(
            float_format=lambda x:
                f"{x:.2f}",
        )
    )

    print("\n[SAVED]")
    print(output_dir)


if __name__ == "__main__":
    main()
