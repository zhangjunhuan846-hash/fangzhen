# ============================================================
# Battery Dataset Simulation Platform v0.1
# Dataset registry
#
# Public API:
#   get_dataset(dataset_id) -> BatteryDatasetAdapter instance
#   list_datasets()         -> pandas DataFrame of dataset summary
#
# Extending to a new dataset requires:
#   1. a new adapter class in platform/datasets/<name>.py
#   2. a new entry in configs/datasets.yaml
# No change to the core simulation runners is required.
#
# Adapter resolution convention:
#   dataset entry:    adapter: "chen2020"
#   module:           platform/datasets/chen2020.py
#   class:            Chen2020Adapter
#   i.e. PascalCase(adapter_id) + "Adapter"
# ============================================================

from __future__ import annotations

import importlib
from typing import Dict, List, Optional

import pandas as pd

from battery_sim.config import (
    ConfigError,
    load_datasets_config,
)
from battery_sim.schemas import DatasetConfig


class RegistryError(RuntimeError):
    """Raised for unknown dataset ids or broken adapters."""


def _to_class_name(adapter_id: str) -> str:
    """'chen2020' -> 'Chen2020';  'calce' -> 'Calce'; then + 'Adapter'."""
    parts = adapter_id.split("_")
    return "".join(p.capitalize() for p in parts) + "Adapter"


def _load_configs() -> Dict[str, DatasetConfig]:
    raw = load_datasets_config()

    configs: Dict[str, DatasetConfig] = {}

    for dataset_id, entry in raw.items():

        if not isinstance(entry, dict):
            raise ConfigError(
                f"datasets.yaml entry '{dataset_id}' is not a mapping"
            )

        configs[dataset_id] = DatasetConfig.from_dict(
            dataset_id,
            entry,
        )

    return configs


def list_dataset_configs() -> List[DatasetConfig]:
    """All dataset configs in declaration order."""
    return list(_load_configs().values())


def get_dataset_config(dataset_id: str) -> DatasetConfig:
    configs = _load_configs()

    if dataset_id not in configs:
        known = ", ".join(sorted(configs.keys()))
        raise RegistryError(
            f"Unknown dataset id: '{dataset_id}'. "
            f"Registered datasets: {known or '(none)'}"
        )

    return configs[dataset_id]


def get_dataset(dataset_id: str):
    """
    Build (and return) the adapter instance for a dataset id.

    Adapter construction is deliberately lazy so that simply
    listing datasets never imports pybamm.
    """
    config = get_dataset_config(dataset_id)

    module_name = f"battery_sim.datasets.{config.adapter}"

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RegistryError(
            f"Dataset '{dataset_id}': cannot import adapter module "
            f"'{module_name}': {exc}"
        ) from exc

    class_name = _to_class_name(config.adapter)

    adapter_cls = getattr(module, class_name, None)

    if adapter_cls is None:
        raise RegistryError(
            f"Dataset '{dataset_id}': adapter module '{module_name}' "
            f"has no class '{class_name}'"
        )

    return adapter_cls(config)


def list_datasets() -> pd.DataFrame:
    """
    Tabular overview of registered datasets.

    Output columns:
        ID          Chemistry       Cells       Parameter set
    """
    rows = []

    for cfg in list_dataset_configs():

        cells = ",".join(cfg.cells)

        rows.append(
            {
                "ID": cfg.dataset_id,
                "Chemistry": cfg.chemistry,
                "Cells": cells,
                "Parameter set": cfg.parameter_set,
            }
        )

    return pd.DataFrame(rows)
