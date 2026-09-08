#!/usr/bin/env python3
# ============================================================
# Battery Dataset Simulation Platform v0.1
#
# Single entry point for the platform.
#
# Usage:
#   python run_pipeline.py --list-datasets
#   python run_pipeline.py --dataset chen2020 --mode reproduction \
#       --model SPMe --cell 02
#   python run_pipeline.py --dataset chen2020 --mode benchmark \
#       --models SPMe DFN --cells all
#   python run_pipeline.py --dataset chen2020 --mode sensitivity \
#       --model SPMe --cell 02 --parameter Dsn
#   python run_pipeline.py --dataset chen2020 --mode baseline \
#       --model SPMe --cell 02
#
# v0.1 formally supports only the Chen2020 LG M50 dataset.
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project root importable regardless of CWD.
ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.logging_utils import banner, kv  # noqa: E402
from battery_sim.registry import get_dataset, get_dataset_config, list_datasets  # noqa: E402


MODES = [
    "reproduction",
    "benchmark",
    "baseline",
    "sensitivity",
]

# benchmark:  --model (singular) is ignored in favour of --models


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description=(
            "Battery Dataset Simulation Platform v0.1 "
            "(Chen2020 LG M50)."
        ),
    )

    parser.add_argument(
        "--dataset",
        default="chen2020",
        help="Dataset id (see configs/datasets.yaml).",
    )

    parser.add_argument(
        "--mode",
        choices=MODES,
        default="reproduction",
        help="Pipeline mode.",
    )

    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model id (SPM, SPMe, DFN). Used by reproduction, "
            "baseline and sensitivity."
        ),
    )

    parser.add_argument(
        "--models",
        default=None,
        nargs="+",
        help=(
            "Model ids for benchmark mode, e.g. "
            "--models SPMe DFN (default: all supported)."
        ),
    )

    parser.add_argument(
        "--cell",
        default=None,
        help=(
            "Cell id, e.g. 02. Use 'all' to run every cell "
            "(benchmark / baseline)."
        ),
    )

    parser.add_argument(
        "--cells",
        default=None,
        nargs="+",
        help="Cells for benchmark mode, e.g. --cells 02 03 04 or all.",
    )

    parser.add_argument(
        "--rate",
        default=None,
        help="Rate id (C10, C2, 1C, 1p5C) or 'all'.",
    )

    parser.add_argument(
        "--protocol",
        default=None,
        help=(
            "v0.3: protocol id for dynamic datasets (DST, FUDS, "
            "US06) or a full window id (DST50, FUDS_80SOC, ...). "
            "Alias of --rate; expanded to every window of the "
            "protocol by the dataset adapter."
        ),
    )

    parser.add_argument(
        "--parameter",
        default=None,
        help=(
            "Sensitivity parameter (Dsn, Dsp, j0n, j0p, De, "
            "kappa_e, Rn, Rp, brug_e) or 'all'."
        ),
    )

    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Disable PNG plotting (CSV outputs still written).",
    )

    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="List registered datasets and exit.",
    )

    return parser


def cmd_list_datasets() -> int:
    banner("Battery Dataset Simulation Platform", 70)
    df = list_datasets()
    print(df.to_string(index=False))
    return 0


def _resolve_cells(cfg, cells_arg):
    """Normalise --cell/--cells to a concrete list of cell ids."""
    if cells_arg in (None, "all"):
        return cfg.cells
    if isinstance(cells_arg, list):
        if "all" in cells_arg:
            return cfg.cells
        return list(cells_arg)
    if str(cells_arg) == "all":
        return cfg.cells
    return [str(cells_arg)]


def _resolve_models(cfg, model_arg, models_arg, default="SPMe"):
    """Normalise model selection for a mode."""
    if models_arg:
        models = [str(m) for m in models_arg]
    elif model_arg:
        models = [str(model_arg)]
    else:
        models = [default]

    # validate against dataset-supported models (case-insensitive)
    supported = {m.upper(): m for m in cfg.supported_models}

    out = []
    for m in models:
        if m.upper() not in supported:
            raise ValueError(
                f"Model '{m}' is not in supported_models of dataset "
                f"'{cfg.dataset_id}': {cfg.supported_models}"
            )
        out.append(m)

    return out


def main(argv=None) -> int:

    parser = build_parser()

    args = parser.parse_args(argv)

    if args.list_datasets:
        return cmd_list_datasets()

    dataset_id = args.dataset

    # ----------------------------------------------------------
    # Load dataset config + adapter
    # ----------------------------------------------------------
    cfg = get_dataset_config(dataset_id)

    banner("Battery Dataset Simulation Platform")
    kv("Dataset", cfg.name)
    kv("Chemistry", cfg.chemistry)
    kv("Mode", args.mode)
    kv("Parameter set", cfg.parameter_set)

    adapter = get_dataset(dataset_id)

    # ----------------------------------------------------------
    # Dispatch
    # ----------------------------------------------------------
    if args.mode == "reproduction":
        return cmd_reproduction(adapter, cfg, args)

    if args.mode == "benchmark":
        return cmd_benchmark(adapter, cfg, args)

    if args.mode == "baseline":
        return cmd_baseline(adapter, cfg, args)

    if args.mode == "sensitivity":
        return cmd_sensitivity(adapter, cfg, args)

    parser.error(f"Unknown mode: {args.mode}")
    return 2


# ------------------------------------------------------------------
# Mode commands (implemented in battery_sim.simulation.*)
# ------------------------------------------------------------------

def cmd_reproduction(adapter, cfg, args) -> int:
    from battery_sim.simulation.reproduction import run_reproduction_cell
    from battery_sim.paths import platform_output_dir

    model = _resolve_models(cfg, args.model, None)[0]
    cell = _resolve_cells(cfg, args.cell)[0]

    out_dir = platform_output_dir(
        cfg.dataset_id,
        "reproduction",
        model,
        cell,
    )

    kv("Cell", cell)
    kv("Model", model)
    print()

    print(f"Protocol loaded        [OK]")
    print(f"Model built            [OK]")

    result = run_reproduction_cell(
        adapter,
        model_name=model,
        cell=cell,
        parameter_set=cfg.parameter_set,
        output_dir=out_dir,
        plot=not args.no_plot,
        quiet=False,
    )

    print(f"Simulation solved      [OK]")
    print()

    metrics = result["metrics"]

    # Summary table
    cols = [
        "rate",
        "rmse_Qaligned_mV",
        "cutoff_capacity_error_pct",
    ]

    print(
        metrics[cols].to_string(
            index=False,
            float_format=lambda x: f"{x:.2f}",
        )
    )

    print()
    print("Results saved:")
    print(result["output_dir"])

    return 0


def cmd_benchmark(adapter, cfg, args) -> int:
    from battery_sim.simulation.benchmark import run_benchmark

    models = _resolve_models(cfg, args.model, args.models, default=None)
    cells = _resolve_cells(cfg, args.cells if args.cells else args.cell)

    print(f"Cells : {cells}")
    print(f"Models: {models}")
    print()

    summary = run_benchmark(
        adapter,
        cfg=cfg,
        models=models,
        cells=cells,
        plot=not args.no_plot,
    )

    print()
    print("[BENCHMARK DONE]")
    print(summary)

    return 0


def cmd_baseline(adapter, cfg, args) -> int:
    from battery_sim.simulation.baseline import run_baseline_cell

    model = _resolve_models(cfg, args.model, None)[0]
    cells = _resolve_cells(cfg, args.cell)

    # v0.3: --protocol is an alias of --rate for the replay
    # runner.  Dynamic adapters may expand a bare protocol id
    # ("DST") into its window list (["DST50", "DST80"]) via
    # expand_protocol(); CC adapters are unaffected.
    rate = args.protocol or args.rate

    if rate == "all":
        rate = None

    if (
        rate is not None
        and not isinstance(rate, list)
        and hasattr(adapter, "expand_protocol")
    ):
        rate = adapter.expand_protocol(rate)

    for cell in cells:
        kv("Cell", cell)
        kv("Model", model)
        if rate is not None:
            wins = (
                [str(rate)]
                if isinstance(rate, str)
                else [str(r) for r in rate]
            )
            kv("Windows", ", ".join(wins))
        print()

        result = run_baseline_cell(
            adapter,
            model_name=model,
            cell=cell,
            rate=rate,
            parameter_set=cfg.parameter_set,
            plot=not args.no_plot,
        )

        print(f"[DONE] cell{cell}")
        print(result["output_dir"])

    return 0


def cmd_sensitivity(adapter, cfg, args) -> int:
    from battery_sim.simulation.sensitivity import run_sensitivity

    model = _resolve_models(cfg, args.model, None)[0]
    cell = _resolve_cells(cfg, args.cell)[0]

    parameter = args.parameter or "all"

    kv("Cell", cell)
    kv("Model", model)
    kv("Parameter", parameter)
    print()

    output_dir = run_sensitivity(
        adapter,
        cfg=cfg,
        model_name=model,
        cell=cell,
        parameter=parameter,
    )

    print()
    print("[SENSITIVITY DONE]")
    print(output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
