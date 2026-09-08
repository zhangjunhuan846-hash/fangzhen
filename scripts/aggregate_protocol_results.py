#!/usr/bin/env python3

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

BASE = (
    ROOT
    / "outputs"
    / "protocol_reproduction"
    / "Chen2020_LGM50"
)

rows = []

for model in ["SPME", "DFN"]:
    for cell in ["02", "03", "04"]:

        p = (
            BASE
            / model
            / f"cell{cell}"
            / "protocol_metrics.csv"
        )

        if not p.exists():
            print("[MISSING]", p)
            continue

        df = pd.read_csv(p)
        rows.append(df)

if not rows:
    raise RuntimeError("No protocol metrics found.")

all_df = pd.concat(
    rows,
    ignore_index=True,
)

out = BASE / "summary"
out.mkdir(
    parents=True,
    exist_ok=True,
)

all_df.to_csv(
    out / "all_protocol_metrics.csv",
    index=False,
)

summary = (
    all_df
    .groupby(["model", "rate"])
    .agg(
        n=("cell", "count"),

        rmse_mean_mV=(
            "rmse_Qaligned_mV",
            "mean",
        ),

        rmse_sd_mV=(
            "rmse_Qaligned_mV",
            "std",
        ),

        mae_mean_mV=(
            "mae_Qaligned_mV",
            "mean",
        ),

        bias_mean_mV=(
            "bias_Qaligned_mV",
            "mean",
        ),

        capacity_error_mean_pct=(
            "cutoff_capacity_error_pct",
            "mean",
        ),

        capacity_error_sd_pct=(
            "cutoff_capacity_error_pct",
            "std",
        ),

        initial_error_mean_mV=(
            "initial_voltage_error_mV",
            "mean",
        ),
    )
    .reset_index()
)

rate_order = {
    "C10": 0,
    "C2": 1,
    "1C": 2,
    "1p5C": 3,
}

summary["_order"] = (
    summary["rate"]
    .map(rate_order)
)

summary = (
    summary
    .sort_values(
        ["model", "_order"]
    )
    .drop(columns="_order")
)

summary.to_csv(
    out / "model_rate_summary.csv",
    index=False,
)

print("\n=== Command-level protocol benchmark ===\n")

print(
    summary.to_string(
        index=False,
        float_format=lambda x: f"{x:.2f}",
    )
)

print("\nSaved:")
print(out / "all_protocol_metrics.csv")
print(out / "model_rate_summary.csv")
