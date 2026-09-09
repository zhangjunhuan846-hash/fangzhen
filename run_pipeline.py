#!/usr/bin/env python3
# ============================================================
# Battery Dataset Simulation Platform v0.1
#
# Single entry point for the platform.
#
# Usage:
#   python run_pipeline.py --config configs/example.yaml
#   python run_pipeline.py --list-datasets
#   python run_pipeline.py baseline  --dataset chen2020 --model SPMe --cell 02
#   python run_pipeline.py benchmark --dataset chen2020 --models SPMe DFN --cells all
#   python run_pipeline.py sensitivity --dataset chen2020 --model SPMe --cell 02 \
#       --parameter Dsn
#   python run_pipeline.py reproduction --dataset chen2020 --model SPMe --cell 02
#
# The task may also be given as --mode <task> (historical form, still supported).
# A YAML config (--config) is merged first; explicit CLI flags win.
#
# v0.1 formally supports only the Chen2020 LG M50 dataset.
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

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

    # Positional task: "python run_pipeline.py baseline ...".
    # Optional and additive: --mode remains fully supported.
    parser.add_argument(
        "task",
        nargs="?",
        choices=MODES,
        default=None,
        metavar="{" + ",".join(MODES) + "}",
        help="Task to run (same values as --mode).",
    )

    parser.add_argument(
        "--dataset",
        default=None,
        help="Dataset id (see configs/datasets.yaml). Default: chen2020.",
    )

    parser.add_argument(
        "--config",
        default=None,
        help=(
            "YAML run config (see configs/example.yaml). Merged first; "
            "explicit CLI flags win over config values."
        ),
    )

    parser.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="Pipeline mode (equivalent to the positional task).",
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


# ------------------------------------------------------------------
# YAML run-config support (--config, v0.4.1, additive)
#
# Precedence: explicit CLI flags > --config YAML > built-in defaults.
# The config mirrors the CLI; nothing here bypasses the runners or
# the dataset registry - it only fills the same argparse fields.
# ------------------------------------------------------------------

_CONFIG_TASK_KEY = "task"


def load_run_config(path) -> dict:
    """Load and sanity-check a one-shot run config (configs/example.yaml)."""
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Run config not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Run config must be a YAML mapping: {cfg_path}")

    task = data.get(_CONFIG_TASK_KEY)
    if task is not None and task not in MODES:
        raise ValueError(
            f"Run config task '{task}' is not one of {MODES}"
        )

    return data


def _config_model_names(run_cfg) -> list:
    """Extract model name(s) from the config `model:` block."""
    model_block = run_cfg.get("model")
    if model_block is None:
        return []
    if isinstance(model_block, str):
        return [model_block]
    if isinstance(model_block, dict):
        names = model_block.get("models") or model_block.get("name")
        if names is None:
            return []
        if isinstance(names, str):
            return [names]
        return [str(m) for m in names]
    raise ValueError("config 'model' must be a name or a block with name/models")


def _user_set(parser, args, dest) -> bool:
    """True if the user explicitly passed `dest` on the command line."""
    default = parser.get_default(dest)
    return getattr(args, dest) != default


def apply_run_config(parser, args, run_cfg) -> None:
    """Fill unset CLI fields from the YAML config (CLI flags win)."""
    # task: only if neither positional task nor --mode was given.
    if not _user_set(parser, args, "task") and not _user_set(parser, args, "mode"):
        cfg_task = run_cfg.get(_CONFIG_TASK_KEY)
        if cfg_task is not None:
            args.task = cfg_task

    if not _user_set(parser, args, "dataset"):
        args.dataset = run_cfg.get("dataset")

    if not _user_set(parser, args, "model"):
        names = _config_model_names(run_cfg)
        if names:
            args.model = names[0]

    if not _user_set(parser, args, "models"):
        names = _config_model_names(run_cfg)
        if len(names) > 1:
            args.models = names

    for arg_dest, cfg_key in (("cell", "cell"), ("cells", "cells")):
        if not _user_set(parser, args, arg_dest) and run_cfg.get(cfg_key) is not None:
            setattr(args, arg_dest, str(run_cfg[cfg_key]))

    if not _user_set(parser, args, "rate"):
        cond = run_cfg.get("condition") or {}
        rate = cond.get("rate")
        if rate is not None:
            args.rate = str(rate)

    if not _user_set(parser, args, "protocol"):
        cond = run_cfg.get("condition") or {}
        protocol = cond.get("protocol")
        if protocol is not None:
            args.protocol = str(protocol)

    if not _user_set(parser, args, "parameter") and run_cfg.get("parameter"):
        args.parameter = str(run_cfg["parameter"])

    if not _user_set(parser, args, "no_plot"):
        out = run_cfg.get("output") or {}
        if out.get("save_curve") is False:
            args.no_plot = True


def describe_run_config(run_cfg) -> None:
    """Echo config-level condition/output intent (no silent overrides)."""
    cond = run_cfg.get("condition") or {}
    temperature = cond.get("temperature")
    if temperature is not None:
        kv("Requested T", f"{temperature} K (dataset-native T is used; "
                          "zero-fit: no silent override)")

    out = run_cfg.get("output") or {}
    if out.get("save_metrics") is False:
        print("Note: save_metrics=false is advisory only; "
              "metrics.csv is always written by the runners.")


def load_chemistry_description(chemistry_id):
    """Resolve a chemistry id against configs/chemistry.yaml (read-only)."""
    chem_path = ROOT / "configs" / "chemistry.yaml"
    if not chem_path.is_file():
        return None
    with chem_path.open("r", encoding="utf-8") as fh:
        registry = yaml.safe_load(fh) or {}
    entry = registry.get(chemistry_id)
    if not isinstance(entry, dict):
        return None
    return {
        "detail": (
            f"{entry.get('positive_electrode', '?')} || "
            f"{entry.get('negative_electrode', '?')} "
            f"({entry.get('electrolyte', '?')}), "
            f"{entry.get('cell_form', '?')}"
        ),
        "default_parameter_set": entry.get("default_parameter_set"),
        "grade": entry.get("parameter_set_grade"),
    }


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

    # ----------------------------------------------------------
    # YAML run config (merged first; explicit CLI flags win)
    # ----------------------------------------------------------
    run_cfg = {}
    if args.config:
        run_cfg = load_run_config(args.config)
        apply_run_config(parser, args, run_cfg)

    # Resolve the task: positional `task` and `--mode` are equivalent.
    if args.task and args.mode and args.task != args.mode:
        parser.error(
            f"conflicting task '{args.task}' and --mode '{args.mode}'; "
            "use one or the other"
        )
    mode = args.task or args.mode or "reproduction"

    dataset_id = args.dataset or "chen2020"

    # ----------------------------------------------------------
    # Load dataset config + adapter
    # ----------------------------------------------------------
    cfg = get_dataset_config(dataset_id)

    banner("Battery Dataset Simulation Platform")
    kv("Dataset", cfg.name)
    kv("Chemistry", cfg.chemistry)
    kv("Mode", mode)
    kv("Parameter set", cfg.parameter_set)

    chem = load_chemistry_description(cfg.chemistry)
    if chem is not None:
        kv("Chemistry detail", chem["detail"])
        grade = chem.get("grade")
        if grade and grade != "A-exact":
            kv("Parameter grade", f"{grade} (surrogate baseline, "
                                  f"NOT a validation run)")
        if chem.get("default_parameter_set") not in (None, cfg.parameter_set):
            print(f"Note: chemistry default parameter set is "
                  f"'{chem['default_parameter_set']}', dataset uses "
                  f"'{cfg.parameter_set}' (see configs/datasets.yaml).")

    if run_cfg:
        kv("Run config", str(args.config))
        describe_run_config(run_cfg)

    adapter = get_dataset(dataset_id)

    # ----------------------------------------------------------
    # Dispatch
    # ----------------------------------------------------------
    if mode == "reproduction":
        return cmd_reproduction(adapter, cfg, args)

    if mode == "benchmark":
        return cmd_benchmark(adapter, cfg, args)

    if mode == "baseline":
        return cmd_baseline(adapter, cfg, args)

    if mode == "sensitivity":
        return cmd_sensitivity(adapter, cfg, args)

    parser.error(f"Unknown mode: {mode}")
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
