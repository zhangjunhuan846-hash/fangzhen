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


ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = (
    ROOT
    / "data/raw/LIB/NMC_Graphite/"
    / "Chen2020_LGM50/raw"
)

OUT_ROOT = (
    ROOT
    / "outputs/protocol_reproduction/"
    / "Chen2020_LGM50"
)


RATE_INFO = {
    "C10": {
        "cycle_index": 1,
        "cycle_c": 2,
        "step": 7,
        "current_A": 0.5,
    },
    "C2": {
        "cycle_index": 2,
        "cycle_c": 3,
        "step": 12,
        "current_A": 2.5,
    },
    "1C": {
        "cycle_index": 3,
        "cycle_c": 4,
        "step": 17,
        "current_A": 5.0,
    },
    "1p5C": {
        "cycle_index": 4,
        "cycle_c": 5,
        "step": 22,
        "current_A": 7.5,
    },
}


def create_model(name):
    name = name.upper()

    if name == "SPME":
        return pybamm.lithium_ion.SPMe()

    if name == "DFN":
        return pybamm.lithium_ion.DFN()

    raise ValueError(name)


def load_raw(cell):

    path = RAW_DIR / f"LGM50_cell{cell}.csv"

    df = pd.read_csv(
        path,
        skiprows=13,
        low_memory=False,
    )

    return path, df


def initial_voltage(df):

    rest = df[
        (df["Cycle C"] == 1)
        & (df["Step"] == 1)
        & (df["Md"] == "R")
    ]

    # final five minutes of initial rest
    tail = rest[
        rest["Step Time [s]"]
        >= rest["Step Time [s]"].max() - 300
    ]

    return float(
        tail["Voltage [V]"].median()
    )


def ambient_temperature(df):

    # use four pre-discharge 2-h rest periods
    steps = [6, 11, 16, 21]

    x = df[
        (df["Step"].isin(steps))
        & (df["Md"] == "R")
    ]["Temperature Chamber [degC]"]

    return float(x.median())


def tagged_step(text, tag):

    return pybamm.step.string(
        text,
        period="10 seconds",
        tags=[tag],
    )


def build_experiment():

    #
    # Cycle 0:
    # Initial conditioning + first full CC-CV charge
    #
    conditioning = (

        "Rest for 30 minutes",

        "Discharge at 0.5 A until 2.5 V",

        "Rest for 2 hours",

        "Charge at 1.5 A until 4.2 V",

        "Hold at 4.2 V until 0.05 A",

        "Rest for 2 hours",
    )

    #
    # Cycle 1: C/10 validation + recharge
    #
    c10 = (

        tagged_step(
            "Discharge at 0.5 A until 2.5 V",
            "C10_discharge",
        ),

        "Rest for 2 hours",

        "Charge at 1.5 A until 4.2 V",

        "Hold at 4.2 V until 0.05 A",

        "Rest for 2 hours",
    )

    #
    # Cycle 2: C/2
    #
    c2 = (

        tagged_step(
            "Discharge at 2.5 A until 2.5 V",
            "C2_discharge",
        ),

        "Rest for 2 hours",

        "Charge at 1.5 A until 4.2 V",

        "Hold at 4.2 V until 0.05 A",

        "Rest for 2 hours",
    )

    #
    # Cycle 3: 1C
    #
    c1 = (

        tagged_step(
            "Discharge at 5 A until 2.5 V",
            "1C_discharge",
        ),

        "Rest for 2 hours",

        "Charge at 1.5 A until 4.2 V",

        "Hold at 4.2 V until 0.05 A",

        "Rest for 2 hours",
    )

    #
    # Cycle 4: 1.5C
    #
    c15 = (

        tagged_step(
            "Discharge at 7.5 A until 2.5 V",
            "1p5C_discharge",
        ),

        "Rest for 2 hours",
    )

    return pybamm.Experiment(
        [
            conditioning,
            c10,
            c2,
            c1,
            c15,
        ],
        period="10 seconds",
    )


def cumulative_capacity(t, current):

    t = np.asarray(t, dtype=float)
    current = np.asarray(current, dtype=float)

    if len(t) < 2:
        return np.zeros_like(t)

    dq = (
        0.5
        * (current[1:] + current[:-1])
        * np.diff(t)
        / 3600
    )

    return np.concatenate(
        [
            [0.0],
            np.cumsum(dq),
        ]
    )


def get_voltage(solution):

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


def get_current(solution):

    return np.asarray(
        solution["Current [A]"].entries,
        dtype=float,
    )


def experimental_discharge(
    df,
    rate,
):

    info = RATE_INFO[rate]

    seg = df[
        (df["Cycle C"] == info["cycle_c"])
        & (df["Step"] == info["step"])
        & (df["Md"] == "D")
    ].copy()

    seg = seg.sort_values(
        "Test Time [s]"
    )

    q = pd.to_numeric(
        seg["Capacity [Ah]"],
        errors="coerce",
    ).to_numpy(float)

    q = q - q[0]

    V = pd.to_numeric(
        seg["Voltage [V]"],
        errors="coerce",
    ).to_numpy(float)

    t = pd.to_numeric(
        seg["Step Time [s]"],
        errors="coerce",
    ).to_numpy(float)

    t = t - t[0]

    return t, q, V


def simulated_discharge(
    solution,
    rate,
):

    info = RATE_INFO[rate]

    cycle = solution.cycles[
        info["cycle_index"]
    ]

    t = np.asarray(
        cycle.t,
        dtype=float,
    )

    I = get_current(cycle)

    V = get_voltage(cycle)

    #
    # Positive current = discharge
    #
    threshold = (
        0.5
        * info["current_A"]
    )

    mask = I > threshold

    if not np.any(mask):
        raise RuntimeError(
            f"No discharge points for {rate}"
        )

    t = t[mask]
    I = I[mask]
    V = V[mask]

    #
    # Make time local to this discharge
    #
    t = t - t[0]

    q = cumulative_capacity(
        t,
        I,
    )

    return t, q, V


def compare_q_aligned(
    q_exp,
    V_exp,
    q_sim,
    V_sim,
):

    #
    # Compare only common capacity domain
    #
    q_end = min(
        float(q_exp[-1]),
        float(q_sim[-1]),
    )

    mask = (
        q_exp <= q_end
    )

    qe = q_exp[mask]
    Ve = V_exp[mask]

    #
    # ensure q_sim strictly increasing
    #
    unique = np.concatenate(
        [
            [True],
            np.diff(q_sim) > 1e-12,
        ]
    )

    qs = q_sim[unique]
    Vs = V_sim[unique]

    Vsi = np.interp(
        qe,
        qs,
        Vs,
    )

    err = Vsi - Ve

    return qe, Ve, Vsi, err


def run(cell, model_name):

    raw_path, raw = load_raw(cell)

    V0 = initial_voltage(raw)
    Tamb_C = ambient_temperature(raw)

    print(
        f"Initial voltage : {V0:.5f} V"
    )

    print(
        f"Ambient temp    : {Tamb_C:.2f} °C"
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

    solution = sim.solve(
        initial_soc=f"{V0:.5f} V",
        calc_esoh=False,
    )

    runtime = (
        time.perf_counter()
        - tic
    )

    print(
        f"Cycles solved   : {len(solution.cycles)}"
    )

    print(
        f"Runtime         : {runtime:.2f} s"
    )

    out_dir = (
        OUT_ROOT
        / model_name.upper()
        / f"cell{cell}"
    )

    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = []

    for rate in RATE_INFO:

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
            solution,
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

        rmse = (
            np.sqrt(
                np.mean(error ** 2)
            )
            * 1000
        )

        mae = (
            np.mean(
                np.abs(error)
            )
            * 1000
        )

        bias = (
            np.mean(error)
            * 1000
        )

        q_exp_end = float(
            q_exp[-1]
        )

        q_sim_end = float(
            q_sim[-1]
        )

        q_error_pct = (
            100
            * (q_sim_end - q_exp_end)
            / q_exp_end
        )

        t_exp_end = float(
            t_exp[-1]
        )

        t_sim_end = float(
            t_sim[-1]
        )

        t_error_pct = (
            100
            * (t_sim_end - t_exp_end)
            / t_exp_end
        )

        row = {
            "cell": cell,
            "model": model_name.upper(),
            "rate": rate,

            "rmse_Qaligned_mV":
                float(rmse),

            "mae_Qaligned_mV":
                float(mae),

            "bias_Qaligned_mV":
                float(bias),

            "Q_exp_Ah":
                q_exp_end,

            "Q_sim_Ah":
                q_sim_end,

            "cutoff_capacity_error_pct":
                float(q_error_pct),

            "t_exp_s":
                t_exp_end,

            "t_sim_s":
                t_sim_end,

            "cutoff_time_error_pct":
                float(t_error_pct),

            "initial_voltage_error_mV":
                float(
                    error[0] * 1000
                ),

            "common_end_voltage_error_mV":
                float(
                    error[-1] * 1000
                ),
        }

        rows.append(row)

        print(
            f"\n{rate:5s} | "
            f"RMSE(Q)={rmse:7.2f} mV | "
            f"Qexp={q_exp_end:.3f} Ah | "
            f"Qsim={q_sim_end:.3f} Ah | "
            f"dQ={q_error_pct:+6.2f}% | "
            f"dt={t_error_pct:+6.2f}%"
        )

        #
        # Save comparison table
        #
        compare = pd.DataFrame({
            "capacity_Ah":
                q_common,

            "voltage_exp_V":
                V_exp_common,

            "voltage_sim_V":
                V_sim_common,

            "residual_V":
                error,
        })

        compare.to_csv(
            out_dir
            / f"{rate}_capacity_aligned.csv",
            index=False,
        )

        #
        # V-Q plot
        #
        fig, ax = plt.subplots(
            figsize=(7.2, 5.2)
        )

        ax.plot(
            q_exp,
            V_exp,
            label="Experiment",
            linewidth=1.8,
        )

        ax.plot(
            q_sim,
            V_sim,
            label="Command-level DFN",
            linewidth=1.6,
        )

        ax.set_xlabel(
            "Discharged capacity [Ah]"
        )

        ax.set_ylabel(
            "Terminal voltage [V]"
        )

        ax.set_title(
            f"cell{cell} | {rate} | "
            f"RMSE(Q)={rmse:.1f} mV"
        )

        ax.legend()

        fig.tight_layout()

        fig.savefig(
            out_dir
            / f"{rate}_VQ.png",
            dpi=250,
        )

        plt.close(fig)

    metrics = pd.DataFrame(rows)

    metrics.to_csv(
        out_dir
        / "protocol_metrics.csv",
        index=False,
    )

    with open(
        out_dir
        / "run_metadata.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "cell": cell,
                "model": model_name.upper(),
                "initial_voltage_V": V0,
                "ambient_temperature_C": Tamb_C,
                "runtime_s": runtime,
                "pybamm_version":
                    pybamm.__version__,
            },
            f,
            indent=2,
        )

    print("\n" + "=" * 90)

    print(
        metrics.to_string(
            index=False,
            float_format=lambda x:
                f"{x:.3f}",
        )
    )

    print("\n[SAVED]")
    print(out_dir)


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
        default="DFN",
        choices=[
            "DFN",
            "SPMe",
        ],
    )

    args = parser.parse_args()

    print("=" * 90)
    print(
        "Chen2020 command-level protocol reproduction"
    )
    print("=" * 90)

    print(
        "PyBaMM:",
        pybamm.__version__,
    )

    run(
        args.cell,
        args.model,
    )


if __name__ == "__main__":
    main()
