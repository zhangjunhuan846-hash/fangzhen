#!/usr/bin/env python3

from pathlib import Path
import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

BASE = (
    ROOT
    / "outputs"
    / "baseline"
    / "Chen2020_LGM50"
)

MODELS = ["SPM", "SPME", "DFN"]
CELLS = ["02", "03", "04"]
RATES = ["C10", "C2", "1C", "1p5C"]

records = []


for model in MODELS:
    for cell in CELLS:
        for rate in RATES:

            folder = (
                BASE
                / model
                / f"cell{cell}"
                / rate
            )

            metric_file = folder / "metrics.json"
            comparison_file = folder / "comparison.csv"

            if not metric_file.exists() or not comparison_file.exists():
                continue

            with open(metric_file, encoding="utf-8") as f:
                m = json.load(f)

            df = pd.read_csv(comparison_file)

            err = df["residual_V"].to_numpy(dtype=float)

            bias = float(np.mean(err))
            std_error = float(np.std(err))
            initial_error = float(err[0])
            final_error = float(err[-1])

            # normalized discharged-time coordinate
            x = (
                df["time_s"].to_numpy(dtype=float)
                / df["time_s"].iloc[-1]
            )

            bins = [
                (0.0, 0.2),
                (0.2, 0.4),
                (0.4, 0.6),
                (0.6, 0.8),
                (0.8, 1.000001),
            ]

            bin_rmse = {}

            for lo, hi in bins:

                mask = (
                    (x >= lo)
                    & (x < hi)
                )

                if mask.sum() > 0:
                    rmse = np.sqrt(
                        np.mean(err[mask] ** 2)
                    ) * 1000
                else:
                    rmse = np.nan

                key = f"rmse_{int(lo*100)}_{int(min(hi,1)*100)}_mV"
                bin_rmse[key] = rmse

            row = {
                "model": model,
                "cell": cell,
                "rate": rate,
                "rmse_mV": m["rmse_mV"],
                "mae_mV": m["mae_mV"],
                "bias_mV": bias * 1000,
                "residual_std_mV": std_error * 1000,
                "initial_error_mV": initial_error * 1000,
                "final_error_mV": final_error * 1000,
                "coverage_fraction": m["coverage_fraction"],
                "runtime_s": m["runtime_s"],
            }

            row.update(bin_rmse)

            records.append(row)


df = pd.DataFrame(records)

out = BASE / "diagnostics"
out.mkdir(parents=True, exist_ok=True)

df.to_csv(
    out / "all_diagnostics.csv",
    index=False,
)


# ==========================================
# Mean ± SD across the three cells
# ==========================================

summary = (
    df.groupby(["model", "rate"])
    .agg(
        rmse_mean_mV=("rmse_mV", "mean"),
        rmse_sd_mV=("rmse_mV", "std"),
        mae_mean_mV=("mae_mV", "mean"),
        bias_mean_mV=("bias_mV", "mean"),
        initial_error_mean_mV=("initial_error_mV", "mean"),
        final_error_mean_mV=("final_error_mV", "mean"),
        runtime_mean_s=("runtime_s", "mean"),
    )
    .reset_index()
)

summary.to_csv(
    out / "model_rate_summary.csv",
    index=False,
)

print("\n=== Model × C-rate summary ===\n")
print(
    summary.to_string(
        index=False,
        float_format=lambda x: f"{x:.2f}",
    )
)

print("\n[SAVED]")
print(out / "all_diagnostics.csv")
print(out / "model_rate_summary.csv")
