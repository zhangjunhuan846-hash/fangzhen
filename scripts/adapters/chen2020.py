#!/usr/bin/env python3

from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd


NOMINAL_CAPACITY_AH = 5.0

RATE_MAP = {
    2: ("C10", 0.1),
    3: ("C2", 0.5),
    4: ("1C", 1.0),
    5: ("1p5C", 1.5),
}


def load_raw(path: Path) -> pd.DataFrame:
    # Chen2020 Maccor CSV: real header is line 14
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
        "Energy [Wh]",
        "Current [A]",
        "Voltage [V]",
        "Md",
        "Temperature Cell [degC]",
        "Temperature Chamber [degC]",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            f"{path.name}: missing columns: {missing}"
        )

    return df


def extract_validation_discharges(
    path: Path,
):
    df = load_raw(path)

    outputs = []

    for cycle_c, (rate_name, nominal_c_rate) in RATE_MAP.items():

        seg = df[
            (df["Cycle C"] == cycle_c)
            & (df["Md"] == "D")
        ].copy()

        if seg.empty:
            print(
                f"[WARNING] {path.name}: "
                f"Cycle C={cycle_c} discharge missing"
            )
            continue

        seg = seg.sort_values("Test Time [s]")

        t0 = float(seg["Test Time [s]"].iloc[0])

        out = pd.DataFrame({
            "dataset": "Chen2020_LGM50",
            "cell_id": path.stem,
            "cycle_c": cycle_c,
            "step": seg["Step"].values,
            "mode": seg["Md"].values,

            # Relative time for PyBaMM
            "time_s":
                seg["Test Time [s]"].astype(float).values - t0,

            "step_time_s":
                pd.to_numeric(
                    seg["Step Time [s]"],
                    errors="coerce",
                ).values,

            # Chen2020 Maccor current is magnitude.
            # PyBaMM convention: positive current = discharge.
            "current_A":
                pd.to_numeric(
                    seg["Current [A]"],
                    errors="coerce",
                ).values,

            "voltage_V":
                pd.to_numeric(
                    seg["Voltage [V]"],
                    errors="coerce",
                ).values,

            "capacity_Ah":
                pd.to_numeric(
                    seg["Capacity [Ah]"],
                    errors="coerce",
                ).values,

            "energy_Wh":
                pd.to_numeric(
                    seg["Energy [Wh]"],
                    errors="coerce",
                ).values,

            # Observation for later thermal validation
            "temperature_cell_C":
                pd.to_numeric(
                    seg["Temperature Cell [degC]"],
                    errors="coerce",
                ).values,

            # Physical ambient-temperature input
            "temperature_ambient_C":
                pd.to_numeric(
                    seg["Temperature Chamber [degC]"],
                    errors="coerce",
                ).values,
        })

        out = out.dropna(
            subset=[
                "time_s",
                "current_A",
                "voltage_V",
            ]
        ).reset_index(drop=True)

        measured_current = float(
            out["current_A"].median()
        )

        measured_c_rate = (
            measured_current / NOMINAL_CAPACITY_AH
        )

        metadata = {
            "dataset": "Chen2020_LGM50",
            "cell_id": path.stem,
            "cycle_c": cycle_c,
            "rate_name": rate_name,
            "nominal_c_rate": nominal_c_rate,
            "measured_c_rate": measured_c_rate,
            "median_current_A": measured_current,
            "n_points": int(len(out)),
            "duration_s": float(out["time_s"].iloc[-1]),
            "voltage_start_V": float(out["voltage_V"].iloc[0]),
            "voltage_end_V": float(out["voltage_V"].iloc[-1]),
            "capacity_end_Ah": float(out["capacity_Ah"].iloc[-1]),
            "ambient_temperature_C": float(
                out["temperature_ambient_C"].median()
            ),
            "cell_temperature_start_C": float(
                out["temperature_cell_C"].iloc[0]
            ),
            "cell_temperature_end_C": float(
                out["temperature_cell_C"].iloc[-1]
            ),
        }

        outputs.append(
            (rate_name, out, metadata)
        )

    return outputs


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "input",
        type=Path,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = extract_validation_discharges(
        args.input
    )

    metadata_all = []

    for rate_name, df, metadata in outputs:

        csv_path = (
            args.output_dir
            / f"{args.input.stem}_{rate_name}.csv"
        )

        json_path = (
            args.output_dir
            / f"{args.input.stem}_{rate_name}.json"
        )

        df.to_csv(
            csv_path,
            index=False,
        )

        with open(
            json_path,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                metadata,
                f,
                indent=2,
                ensure_ascii=False,
            )

        metadata_all.append(metadata)

        print(
            f"[OK] {args.input.stem:12s} "
            f"{rate_name:5s} | "
            f"I={metadata['median_current_A']:.3f} A | "
            f"C-rate={metadata['measured_c_rate']:.3f} | "
            f"Q={metadata['capacity_end_Ah']:.3f} Ah | "
            f"T={metadata['ambient_temperature_C']:.2f} °C"
        )

    summary = pd.DataFrame(metadata_all)

    summary.to_csv(
        args.output_dir
        / f"{args.input.stem}_protocol_summary.csv",
        index=False,
    )


if __name__ == "__main__":
    main()
