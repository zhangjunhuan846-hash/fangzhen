# ============================================================
# Battery Dataset Simulation Platform v0.1
# Benchmark runner (Step 8)
#
# Batch cells x models x rates through the already-regression-
# validated command-level reproduction runner and aggregate the
# per-cell protocol metrics into model-rate summaries.
#
# IMPORTANT: benchmark calls run_reproduction_cell() and does NOT
# re-implement any simulation / comparison logic. Per-cell detail
# (curves, plots) belongs to ``reproduction`` mode; benchmark only
# aggregates the metrics returned by the reproduction runner.
#
# Outputs (outputs/platform/<dataset>/benchmark/):
#   all_metrics.csv            one row per (model, cell, rate)
#   model_rate_summary.csv     model x rate aggregates
#   run_metadata.json
#
# Summary column names and aggregation match the validated
# reference aggregator scripts/aggregate_protocol_results.py
# (pandas .std() default ddof=1).
# ============================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

import pybamm

from battery_sim.paths import (
    PLATFORM_OUTPUT_ROOT,
    ensure_dir,
)
from battery_sim.simulation.reproduction import (
    run_reproduction_cell,
)
from battery_sim.logging_utils import timestamp_utc

# Canonical validation-rate ordering for summaries
RATE_ORDER = ["C10", "C2", "1C", "1p5C"]

SUMMARY_COLUMNS = [
    "model",
    "rate",
    "n",
    "rmse_mean_mV",
    "rmse_sd_mV",
    "mae_mean_mV",
    "bias_mean_mV",
    "capacity_error_mean_pct",
    "capacity_error_sd_pct",
    "initial_error_mean_mV",
]


def _rank_rate(rate: str) -> int:
    try:
        return RATE_ORDER.index(rate)
    except ValueError:
        return len(RATE_ORDER)


def _aggregate(all_metrics: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per-cell protocol metrics into the model_rate_summary
    schema (identical aggregation to scripts/aggregate_protocol_results.py).
    """
    group_cols = ["model", "rate"]

    agg = (
        all_metrics.groupby(group_cols, sort=False)
        .agg(
            n=("cell", "count"),
            rmse_mean_mV=("rmse_Qaligned_mV", "mean"),
            rmse_sd_mV=("rmse_Qaligned_mV", "std"),
            mae_mean_mV=("mae_Qaligned_mV", "mean"),
            bias_mean_mV=("bias_Qaligned_mV", "mean"),
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

    # Preserve model order of the request, canonical rate order.
    model_order = {
        m.upper(): i for i, m in enumerate(all_metrics["model"].unique())
    }
    agg["_model_order"] = agg["model"].map(model_order)
    agg["_rate_order"] = agg["rate"].map(_rank_rate)
    agg = agg.sort_values(["_model_order", "_rate_order"])
    agg = agg.drop(columns=["_model_order", "_rate_order"])

    return agg[SUMMARY_COLUMNS].reset_index(drop=True)


def run_benchmark(
    adapter,
    cfg,
    models: Optional[List[str]] = None,
    cells: Optional[List[str]] = None,
    plot: bool = True,
    quiet: bool = True,
) -> pd.DataFrame:
    """
    Run command-level reproduction for every (model, cell) pair and
    return the aggregated model_rate_summary DataFrame (also saved).

    ``plot`` is accepted for CLI parity but benchmark aggregation
    itself never re-plots per-cell curves.
    """
    if not models:
        models = list(cfg.supported_models)
    if not cells:
        cells = list(cfg.cells)

    out_root = PLATFORM_OUTPUT_ROOT / cfg.dataset_id / "benchmark"
    ensure_dir(out_root)

    tic = time.perf_counter()

    frames: List[pd.DataFrame] = []
    rate_meta = None

    for model in models:
        for cell in cells:
            if not quiet:
                print(
                    f"[BENCH] {model.upper()}  cell{cell}",
                    flush=True,
                )

            res = run_reproduction_cell(
                adapter,
                model_name=model,
                cell=str(cell),
                parameter_set=cfg.parameter_set,
                rates=None,
                output_dir=None,
                plot=False,
                quiet=True,
            )

            rate_meta = {
                "initial_voltage_V": res["initial_voltage_V"],
                "ambient_temperature_C": res["ambient_temperature_C"],
            }

            frames.append(res["metrics"])

    all_metrics = pd.concat(frames, ignore_index=True)

    summary = _aggregate(all_metrics)

    runtime_s = time.perf_counter() - tic

    # ----------------------------------------------------------
    # Save standard outputs
    # ----------------------------------------------------------
    all_metrics.to_csv(
        out_root / "all_metrics.csv",
        index=False,
    )

    summary.to_csv(
        out_root / "model_rate_summary.csv",
        index=False,
    )

    metadata = {
        "dataset": cfg.dataset_id,
        "mode": "benchmark",
        "models": [m.upper() for m in models],
        "cells": [str(c) for c in cells],
        "rates": list(cfg.rates),
        "n_cells": len(cells),
        "n_models": len(models),
        "parameter_set": cfg.parameter_set,
        "pybamm_version": pybamm.__version__,
        "timestamp": timestamp_utc(),
        "runtime_s": runtime_s,
        "aggregation": {
            "note": (
                "Per-cell metrics come from run_reproduction_cell(); "
                "summary columns match "
                "scripts/aggregate_protocol_results.py"
            ),
            "rmse_source_column": "rmse_Qaligned_mV",
        },
        **(rate_meta or {}),
    }

    with open(
        out_root / "run_metadata.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return summary


if __name__ == "__main__":  # pragma: no cover - CLI is run_pipeline.py
    raise SystemExit(
        "Use: python run_pipeline.py --mode benchmark ..."
    )
