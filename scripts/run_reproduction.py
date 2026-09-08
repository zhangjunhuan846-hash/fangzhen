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

RAW_DIR = (
    ROOT
    / "data"
    / "raw"
    / "LIB"
    / "NMC_Graphite"
    / "Chen2020_LGM50"
    / "raw"
)

OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "reproduction"
    / "Chen2020_LGM50"
)

BASELINE_ROOT = (
    ROOT
    / "outputs"
    / "baseline"
    / "Chen2020_LGM50"
)


# Formal validation discharges
RATE_MAP = {
    2: ("C10", 0.1),
    3: ("C2", 0.5),
    4: ("1C", 1.0),
    5: ("1p5C", 1.5),
}


# ============================================================
# Model
# ============================================================

def create_model(name: str):

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


# ============================================================
# Raw Maccor loader
# ============================================================

def load_raw(cell: str):

    path = RAW_DIR / f"LGM50_cell{cell}.csv"

    if not path.exists():
        raise FileNotFoundError(path)

    # Real Maccor header is row 14
    df = pd.read_csv(
        path,
        skiprows=13,
        low_memory=False,
    )

    required = [
        "Cycle C",
        "Step",
        "Test Time [s]",
        "Step Time [s]",
        "Capacity [Ah]",
        "Current [A]",
        "Voltage [V]",
        "Md",
        "Temperature Cell [degC]",
        "Temperature Chamber [degC]",
    ]

    missing = [
        c for c in required
        if c not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing columns: {missing}"
        )

    numeric_cols = [
        "Cycle C",
        "Step",
        "Test Time [s]",
        "Step Time [s]",
        "Capacity [Ah]",
        "Current [A]",
        "Voltage [V]",
        "Temperature Cell [degC]",
        "Temperature Chamber [degC]",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "Test Time [s]",
            "Voltage [V]",
        ]
    ).copy()

    df = df.sort_values(
        "Test Time [s]"
    )

    # A rare Maccor sub-record can share a timestamp.
    # Keep the last entry at duplicate timestamps.
    df = df.drop_duplicates(
        subset=["Test Time [s]"],
        keep="last",
    ).reset_index(drop=True)

    t0 = float(
        df["Test Time [s]"].iloc[0]
    )

    df["time_s"] = (
        df["Test Time [s]"] - t0
    )

    # --------------------------------------------------------
    # Maccor stores current magnitude.
    #
    # PyBaMM convention:
    #   positive = discharge
    #   negative = charge
    #   zero     = rest
    # --------------------------------------------------------

    mode = (
        df["Md"]
        .astype(str)
        .str.strip()
    )

    current_mag = (
        pd.to_numeric(
            df["Current [A]"],
            errors="coerce",
        )
        .fillna(0.0)
        .abs()
    )

    signed_current = np.zeros(
        len(df),
        dtype=float,
    )

    signed_current[
        mode.eq("D").to_numpy()
    ] = current_mag[
        mode.eq("D")
    ].to_numpy()

    signed_current[
        mode.eq("C").to_numpy()
    ] = -current_mag[
        mode.eq("C")
    ].to_numpy()

    # R / O / SBr / unknown -> 0 A
    df["current_signed_A"] = (
        signed_current
    )

    return path, df


# ============================================================
# Initial state from measured initial rest voltage
# ============================================================

def get_initial_voltage(df):

    # Cycle 1, step 1 is initial rest
    rest = df[
        (df["Cycle C"] == 1)
        & (df["Step"] == 1)
        & (df["Md"] == "R")
    ].copy()

    if rest.empty:
        # fallback
        rest = df.iloc[:30].copy()

    # Use the last 5 min of the initial rest
    t_end = float(
        rest["time_s"].max()
    )

    tail = rest[
        rest["time_s"]
        >= t_end - 300
    ]

    if tail.empty:
        tail = rest

    return float(
        tail["Voltage [V]"].median()
    )


# ============================================================
# Run complete measured-current history
# ============================================================

def run_full_history(
    cell: str,
    model_name: str,
):

    raw_path, df = load_raw(cell)

    t_exp = df[
        "time_s"
    ].to_numpy(dtype=float)

    I_exp = df[
        "current_signed_A"
    ].to_numpy(dtype=float)

    V_exp = df[
        "Voltage [V]"
    ].to_numpy(dtype=float)

    initial_voltage = (
        get_initial_voltage(df)
    )

    # Chamber temperature = environment
    chamber = (
        df["Temperature Chamber [degC]"]
        .dropna()
    )

    # Remove obviously corrupted tail points if present
    chamber_plausible = chamber[
        (chamber > 15)
        & (chamber < 45)
    ]

    if len(chamber_plausible):
        ambient_C = float(
            chamber_plausible.median()
        )
    else:
        ambient_C = float(
            chamber.median()
        )

    ambient_K = (
        ambient_C + 273.15
    )

    model = create_model(
        model_name
    )

    params = pybamm.ParameterValues(
        "Chen2020"
    )

    # --------------------------------------------------------
    # Use measured current through the whole experiment.
    # --------------------------------------------------------

    params[
        "Current function [A]"
    ] = pybamm.Interpolant(
        t_exp,
        I_exp,
        pybamm.t,
    )

    if (
        "Ambient temperature [K]"
        in params
    ):
        params[
            "Ambient temperature [K]"
        ] = ambient_K

    if (
        "Initial temperature [K]"
        in params
    ):
        params[
            "Initial temperature [K]"
        ] = ambient_K

    # --------------------------------------------------------
    # IMPORTANT:
    # During reproduction we do not want the simulation
    # terminating merely because model voltage reaches the
    # experimental 2.5/4.2-V boundary slightly early.
    #
    # Widen limits so the full measured-current history can
    # propagate the internal state.
    # --------------------------------------------------------

    if (
        "Lower voltage cut-off [V]"
        in params
    ):
        params[
            "Lower voltage cut-off [V]"
        ] = 2.0

    if (
        "Upper voltage cut-off [V]"
        in params
    ):
        params[
            "Upper voltage cut-off [V]"
        ] = 4.4

    sim = pybamm.Simulation(
        model,
        parameter_values=params,
    )

    initial_state = (
        f"{initial_voltage:.5f} V"
    )

    print(
        f"  Initial measured voltage : "
        f"{initial_voltage:.5f} V"
    )

    print(
        f"  PyBaMM initial state     : "
        f"{initial_state}"
    )

    print(
        f"  Ambient temperature     : "
        f"{ambient_C:.2f} °C"
    )

    print(
        f"  Current range            : "
        f"{I_exp.min():.3f} → "
        f"{I_exp.max():.3f} A"
    )

    print(
        f"  Full duration            : "
        f"{t_exp[-1]/3600:.2f} h"
    )

    tic = time.perf_counter()

    solution = sim.solve(
        t_eval=t_exp,
        initial_soc=initial_state,
    )

    runtime_s = (
        time.perf_counter()
        - tic
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

    common_end = min(
        float(t_exp[-1]),
        float(t_sim[-1]),
    )

    coverage = (
        common_end
        / float(t_exp[-1])
    )

    mask = (
        t_exp <= common_end
    )

    comp = df.loc[mask].copy()

    comp["voltage_sim_V"] = (
        np.interp(
            comp["time_s"].to_numpy(),
            t_sim,
            V_sim,
        )
    )

    comp["voltage_exp_V"] = (
        comp["Voltage [V]"]
    )

    comp["residual_V"] = (
        comp["voltage_sim_V"]
        - comp["voltage_exp_V"]
    )

    full_metrics = {
        "cell": cell,
        "model": model_name.upper(),
        "parameter_set": "Chen2020",
        "initial_voltage_V":
            initial_voltage,
        "initial_state":
            initial_state,
        "ambient_temperature_C":
            ambient_C,
        "experimental_duration_h":
            float(t_exp[-1] / 3600),
        "simulation_duration_h":
            float(t_sim[-1] / 3600),
        "coverage_fraction":
            float(coverage),
        "runtime_s":
            float(runtime_s),
    }

    return (
        raw_path,
        comp,
        full_metrics,
    )


# ============================================================
# Metrics for individual validation discharges
# ============================================================

def evaluate_validation_discharges(
    comp,
    cell,
    model_name,
):

    rows = []

    for cycle_c, (
        rate_name,
        nominal_rate,
    ) in RATE_MAP.items():

        seg = comp[
            (comp["Cycle C"] == cycle_c)
            & (comp["Md"] == "D")
        ].copy()

        if seg.empty:
            print(
                f"  [WARNING] Missing "
                f"{rate_name}"
            )
            continue

        err = (
            seg["residual_V"]
            .to_numpy(dtype=float)
        )

        rmse = float(
            np.sqrt(
                np.mean(err ** 2)
            )
        )

        mae = float(
            np.mean(
                np.abs(err)
            )
        )

        bias = float(
            np.mean(err)
        )

        q = (
            pd.to_numeric(
                seg["Capacity [Ah]"],
                errors="coerce",
            )
            .to_numpy(dtype=float)
        )

        # True discharge-progress coordinate:
        # use measured discharged capacity, not time.
        q0 = np.nanmin(q)
        q = q - q0

        q_end = np.nanmax(q)

        if (
            np.isfinite(q_end)
            and q_end > 0
        ):
            progress = (
                q / q_end
            )
        else:
            t = (
                seg["time_s"]
                .to_numpy(dtype=float)
            )

            progress = (
                (t - t[0])
                / (t[-1] - t[0])
            )

        bin_metrics = {}

        bins = [
            (0.0, 0.2),
            (0.2, 0.4),
            (0.4, 0.6),
            (0.6, 0.8),
            (0.8, 1.000001),
        ]

        for lo, hi in bins:

            bmask = (
                (progress >= lo)
                & (progress < hi)
            )

            if np.any(bmask):
                b_rmse = float(
                    np.sqrt(
                        np.mean(
                            err[bmask] ** 2
                        )
                    )
                    * 1000
                )
            else:
                b_rmse = np.nan

            key = (
                f"rmse_"
                f"{int(lo*100)}_"
                f"{int(min(hi,1)*100)}"
                f"_mV"
            )

            bin_metrics[key] = (
                b_rmse
            )

        row = {
            "file":
                f"LGM50_cell"
                f"{cell}_{rate_name}.csv",

            "cell":
                cell,

            "model":
                model_name.upper(),

            "rate":
                rate_name,

            "nominal_c_rate":
                nominal_rate,

            "rmse_mV":
                rmse * 1000,

            "mae_mV":
                mae * 1000,

            "bias_mV":
                bias * 1000,

            "initial_error_mV":
                float(err[0] * 1000),

            "final_error_mV":
                float(err[-1] * 1000),

            "n_points":
                int(len(seg)),

            "capacity_end_Ah":
                float(
                    seg[
                        "Capacity [Ah]"
                    ].iloc[-1]
                ),
        }

        row.update(
            bin_metrics
        )

        rows.append(row)

    return pd.DataFrame(rows)


# ============================================================
# Plots
# ============================================================

def save_full_voltage_plot(
    comp,
    output_dir,
    cell,
    model_name,
):

    fig, ax = plt.subplots(
        figsize=(10, 5.5)
    )

    ax.plot(
        comp["time_s"] / 3600,
        comp["voltage_exp_V"],
        label="Experiment",
        linewidth=1.3,
    )

    ax.plot(
        comp["time_s"] / 3600,
        comp["voltage_sim_V"],
        label=f"PyBaMM {model_name.upper()}",
        linewidth=1.2,
    )

    ax.set_xlabel(
        "Test time [h]"
    )

    ax.set_ylabel(
        "Terminal voltage [V]"
    )

    ax.set_title(
        f"Chen2020 cell{cell} "
        f"full-history reproduction"
    )

    ax.legend()

    fig.tight_layout()

    fig.savefig(
        output_dir
        / "full_protocol_voltage.png",
        dpi=250,
    )

    plt.close(fig)


def save_current_plot(
    comp,
    output_dir,
    cell,
):

    fig, ax = plt.subplots(
        figsize=(10, 4.5)
    )

    ax.plot(
        comp["time_s"] / 3600,
        comp["current_signed_A"],
        linewidth=1.1,
    )

    ax.axhline(
        0,
        linewidth=0.8,
    )

    ax.set_xlabel(
        "Test time [h]"
    )

    ax.set_ylabel(
        "Current [A]\n"
        "(+ discharge, − charge)"
    )

    ax.set_title(
        f"Chen2020 cell{cell} "
        f"measured current protocol"
    )

    fig.tight_layout()

    fig.savefig(
        output_dir
        / "full_protocol_current.png",
        dpi=250,
    )

    plt.close(fig)


def save_rate_plots(
    comp,
    output_dir,
    cell,
    model_name,
):

    for cycle_c, (
        rate_name,
        _,
    ) in RATE_MAP.items():

        seg = comp[
            (comp["Cycle C"] == cycle_c)
            & (comp["Md"] == "D")
        ].copy()

        if seg.empty:
            continue

        t = (
            seg["time_s"]
            - seg["time_s"].iloc[0]
        )

        fig, ax = plt.subplots(
            figsize=(7.2, 5.2)
        )

        ax.plot(
            t / 3600,
            seg["voltage_exp_V"],
            label="Experiment",
            linewidth=1.8,
        )

        ax.plot(
            t / 3600,
            seg["voltage_sim_V"],
            label=(
                f"Full-history "
                f"{model_name.upper()}"
            ),
            linewidth=1.6,
        )

        err = (
            seg["residual_V"]
            .to_numpy(dtype=float)
        )

        rmse = (
            np.sqrt(
                np.mean(err ** 2)
            )
            * 1000
        )

        ax.set_xlabel(
            "Discharge time [h]"
        )

        ax.set_ylabel(
            "Terminal voltage [V]"
        )

        ax.set_title(
            f"cell{cell} | {rate_name} | "
            f"RMSE={rmse:.1f} mV"
        )

        ax.legend()

        fig.tight_layout()

        fig.savefig(
            output_dir
            / f"{rate_name}_comparison.png",
            dpi=250,
        )

        plt.close(fig)


# ============================================================
# Compare to discharge-only baseline
# ============================================================

def compare_with_baseline(
    reproduction_df,
    model_name,
):

    path = (
        BASELINE_ROOT
        / model_name.upper()
        / "baseline_summary.csv"
    )

    if not path.exists():
        return None

    base = pd.read_csv(path)

    keep = [
        "file",
        "rmse_mV",
        "mae_mV",
    ]

    if not all(
        c in base.columns
        for c in keep
    ):
        return None

    base = (
        base[keep]
        .rename(
            columns={
                "rmse_mV":
                    "baseline_rmse_mV",
                "mae_mV":
                    "baseline_mae_mV",
            }
        )
    )

    merged = (
        reproduction_df
        .merge(
            base,
            on="file",
            how="left",
        )
    )

    merged[
        "delta_rmse_mV"
    ] = (
        merged["rmse_mV"]
        - merged["baseline_rmse_mV"]
    )

    merged[
        "rmse_change_pct"
    ] = (
        100
        * merged["delta_rmse_mV"]
        / merged["baseline_rmse_mV"]
    )

    return merged


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        choices=[
            "SPM",
            "SPMe",
            "DFN",
        ],
        default="DFN",
    )

    parser.add_argument(
        "--cell",
        default="02",
        choices=[
            "02",
            "03",
            "04",
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

    print("=" * 80)
    print(
        "Chen2020 measured-current "
        "full-history reproduction"
    )
    print("=" * 80)

    print(
        "PyBaMM:",
        pybamm.__version__
    )

    print(
        "Model:",
        args.model
    )

    all_rates = []
    all_full_metrics = []

    for cell in cells:

        print("\n" + "-" * 80)

        print(
            f"[RUN] cell{cell} | "
            f"{args.model}"
        )

        try:

            (
                raw_path,
                comp,
                full_metrics,
            ) = run_full_history(
                cell,
                args.model,
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
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        comp.to_csv(
            output_dir
            / "full_protocol_comparison.csv",
            index=False,
        )

        with open(
            output_dir
            / "full_protocol_metrics.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                full_metrics,
                f,
                indent=2,
                ensure_ascii=False,
            )

        rates = (
            evaluate_validation_discharges(
                comp,
                cell,
                args.model,
            )
        )

        rates.to_csv(
            output_dir
            / "validation_rate_metrics.csv",
            index=False,
        )

        save_full_voltage_plot(
            comp,
            output_dir,
            cell,
            args.model,
        )

        save_current_plot(
            comp,
            output_dir,
            cell,
        )

        save_rate_plots(
            comp,
            output_dir,
            cell,
            args.model,
        )

        all_rates.append(
            rates
        )

        all_full_metrics.append(
            full_metrics
        )

        print(
            f"  Coverage : "
            f"{full_metrics['coverage_fraction']*100:.2f}%"
        )

        print(
            f"  Runtime  : "
            f"{full_metrics['runtime_s']:.2f} s"
        )

        print("\n  Validation discharges:")

        print(
            rates[
                [
                    "rate",
                    "rmse_mV",
                    "mae_mV",
                    "bias_mV",
                    "initial_error_mV",
                    "final_error_mV",
                ]
            ].to_string(
                index=False,
                float_format=lambda x:
                    f"{x:.2f}",
            )
        )

    if not all_rates:
        return

    result = pd.concat(
        all_rates,
        ignore_index=True,
    )

    model_dir = (
        OUTPUT_ROOT
        / args.model.upper()
    )

    model_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        model_dir
        / "reproduction_summary.csv",
        index=False,
    )

    full_df = pd.DataFrame(
        all_full_metrics
    )

    full_df.to_csv(
        model_dir
        / "full_history_summary.csv",
        index=False,
    )

    comparison = (
        compare_with_baseline(
            result,
            args.model,
        )
    )

    if comparison is not None:

        comparison.to_csv(
            model_dir
            / "reproduction_vs_discharge_only.csv",
            index=False,
        )

        print("\n" + "=" * 80)
        print(
            "FULL-HISTORY vs DISCHARGE-ONLY"
        )
        print("=" * 80)

        cols = [
            "cell",
            "rate",
            "baseline_rmse_mV",
            "rmse_mV",
            "delta_rmse_mV",
            "rmse_change_pct",
        ]

        print(
            comparison[
                cols
            ].to_string(
                index=False,
                float_format=lambda x:
                    f"{x:.2f}",
            )
        )

    print("\n" + "=" * 80)

    print(
        "[DONE]"
    )

    print(
        model_dir
        / "reproduction_summary.csv"
    )


if __name__ == "__main__":
    main()
