#!/usr/bin/env python3

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

BASE = (
    ROOT
    / "outputs"
    / "sensitivity"
    / "Chen2020_LGM50"
    / "SPME"
)

CELLS = ["02", "03", "04"]

frames = []

for cell in CELLS:

    p = (
        BASE
        / f"cell{cell}"
        / "oat_model_response.csv"
    )

    if not p.exists():
        print("[MISSING]", p)
        continue

    df = pd.read_csv(p)
    df["cell"] = cell

    frames.append(df)

if not frames:
    raise RuntimeError("No sensitivity results found")

df = pd.concat(
    frames,
    ignore_index=True,
)

out = BASE / "summary"
out.mkdir(
    parents=True,
    exist_ok=True,
)

df.to_csv(
    out / "all_cells_oat_response.csv",
    index=False,
)

# ------------------------------------------------------------
# Parameter × rate:
# average magnitude over ±20% perturbation and cells
# ------------------------------------------------------------

rate_summary = (
    df.groupby(
        [
            "parameter",
            "label",
            "group",
            "rate",
        ]
    )
    .agg(
        mean_voltage_shift_mV=(
            "voltage_rms_shift_mV",
            "mean",
        ),
        sd_voltage_shift_mV=(
            "voltage_rms_shift_mV",
            "std",
        ),
        max_voltage_shift_mV=(
            "voltage_rms_shift_mV",
            "max",
        ),
        mean_abs_capacity_shift_pct=(
            "cutoff_capacity_shift_pct",
            lambda x: np.mean(np.abs(x)),
        ),
    )
    .reset_index()
)

rate_summary.to_csv(
    out / "parameter_rate_summary.csv",
    index=False,
)

# ------------------------------------------------------------
# Overall ranking
# ------------------------------------------------------------

ranking = (
    rate_summary.groupby(
        [
            "parameter",
            "label",
            "group",
        ]
    )
    .agg(
        mean_voltage_shift_mV=(
            "mean_voltage_shift_mV",
            "mean",
        ),
        max_voltage_shift_mV=(
            "max_voltage_shift_mV",
            "max",
        ),
        mean_abs_capacity_shift_pct=(
            "mean_abs_capacity_shift_pct",
            "mean",
        ),
    )
    .reset_index()
    .sort_values(
        "mean_voltage_shift_mV",
        ascending=False,
    )
)

ranking.to_csv(
    out / "cross_cell_parameter_ranking.csv",
    index=False,
)

# ------------------------------------------------------------
# Matrix
# ------------------------------------------------------------

matrix = (
    rate_summary
    .pivot(
        index="parameter",
        columns="rate",
        values="mean_voltage_shift_mV",
    )
)

order = [
    x for x in
    ["C10", "C2", "1C", "1p5C"]
    if x in matrix.columns
]

matrix = matrix[order]

matrix["mean"] = matrix.mean(axis=1)

matrix = matrix.sort_values(
    "mean",
    ascending=False,
)

matrix.to_csv(
    out / "cross_cell_rate_matrix.csv"
)

print("\n=== Cross-cell sensitivity ranking ===\n")

print(
    ranking.to_string(
        index=False,
        float_format=lambda x: f"{x:.2f}",
    )
)

print("\n=== Parameter × C-rate sensitivity [mV] ===\n")

print(
    matrix.to_string(
        float_format=lambda x: f"{x:.2f}",
    )
)

print("\nSaved:")
print(out)
