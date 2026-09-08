# ============================================================
# Battery Dataset Simulation Platform v0.1
# YAML configuration loader
#
# Requirement (task spec §5): prefer ``import yaml``; check first,
# never silently install. If PyYAML is missing, raise a clear error.
# ============================================================

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from battery_sim.paths import CONFIGS_DIR

try:
    import yaml  # type: ignore

    _HAS_YAML = True
except Exception:  # pragma: no cover - environment check
    yaml = None  # type: ignore
    _HAS_YAML = False


class ConfigError(RuntimeError):
    """Raised when a platform config file is missing or invalid."""


def _check_yaml() -> None:
    if not _HAS_YAML:
        raise ConfigError(
            "PyYAML is required to load configs/*.yaml but is not installed.\n"
            "Install it explicitly in the pybamm environment, e.g.:\n"
            "  source ~/miniforge3/etc/profile.d/conda.sh && "
            "conda activate pybamm && pip install pyyaml"
        )


@lru_cache(maxsize=None)
def load_yaml(filename: str) -> Dict[str, Any]:
    """
    Load ``configs/<filename>`` as a dict.

    Cached so repeated registry lookups do not re-read the file.
    """
    _check_yaml()

    path = CONFIGS_DIR / filename

    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}\n"
            f"Expected in project configs/ directory."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ConfigError(f"Config file is empty: {path}")

    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file must contain a top-level mapping: {path}"
        )

    return data


def load_datasets_config() -> Dict[str, Any]:
    """Top-level datasets.yaml content."""
    return load_yaml("datasets.yaml")


def load_models_config() -> Dict[str, Any]:
    """Top-level models.yaml content."""
    return load_yaml("models.yaml")


def load_sensitivity_config() -> Dict[str, Any]:
    """Top-level sensitivity.yaml content."""
    return load_yaml("sensitivity.yaml")
