# ============================================================
# Battery Dataset Simulation Platform v0.1
# PyBaMM model factory
#
# Public API:
#   build_model(model_name, options=None)  -> pybamm.lithium_ion model
#   build_model_options(cell_configuration, working_electrode,
#                       extra_model_options) -> pybamm options dict|None
#   load_parameter_values(parameter_set) -> pybamm.ParameterValues
#
# Model mapping (identical to the reference scripts):
#   SPM  -> pybamm.lithium_ion.SPM()
#   SPMe -> pybamm.lithium_ion.SPMe()
#   DFN  -> pybamm.lithium_ion.DFN()
#
# v0.5 half-cell pilot (additive, default path unchanged):
#   * build_model(..., options=...) passes pybamm model options, e.g.
#     {"working electrode": "positive", ...}; options=None keeps the
#     exact v0.1-v0.4 behaviour (plain full cell).
#   * load_parameter_values() routes externally-hosted author sets
#     (Jackowska2025_2mAh_cm2, H5) through
#     battery_sim.models.parameter_sources -- never silently falls
#     back; unknown sets raise pybamm's own error.
# ============================================================

from __future__ import annotations

import importlib
from typing import Optional

import pybamm

from battery_sim.config import load_models_config
from battery_sim.models import parameter_sources

_SUPPORTED = ("SPM", "SPME", "DFN")

# Platform cell-configuration ids -> PyBaMM "working electrode"
# base options.  full_cell -> None (plain default model).
_CELL_CONFIG_BASE_OPTIONS = {
    "half_cell_positive": {"working electrode": "positive"},
    "half_cell_negative": {"working electrode": "negative"},
}


def _canonical(name: str) -> str:
    """'spme' / 'SPMe' / 'SPME' -> 'SPME'."""
    return name.upper()


def _spm(options=None):
    return (
        pybamm.lithium_ion.SPM()
        if options is None
        else pybamm.lithium_ion.SPM(options)
    )


def _spme(options=None):
    return (
        pybamm.lithium_ion.SPMe()
        if options is None
        else pybamm.lithium_ion.SPMe(options)
    )


def _dfn(options=None):
    return (
        pybamm.lithium_ion.DFN()
        if options is None
        else pybamm.lithium_ion.DFN(options)
    )


_BUILDERS = {
    "SPM": _spm,
    "SPME": _spme,
    "DFN": _dfn,
}


def build_model(model_name: str, options: Optional[dict] = None):
    """
    Build a pybamm lithium-ion model by name.

    Accepted names (case-insensitive): SPM, SPMe, DFN.
    ``options`` (optional) are passed to the model constructor, e.g.
    for a positive-working-electrode half cell.  ``None`` keeps the
    exact v0.1-v0.4 default (full cell).
    """
    key = _canonical(model_name)

    if key not in _BUILDERS:
        raise ValueError(
            f"Unsupported model: {model_name}. "
            f"Supported: {', '.join(_SUPPORTED)}"
        )

    return _BUILDERS[key](options)


def build_model_options(
    cell_configuration: str = "full_cell",
    working_electrode: str = "",
    extra_model_options: Optional[dict] = None,
) -> Optional[dict]:
    """
    Translate platform cell configuration into pybamm model options.

      full_cell            -> None (default model, unchanged)
      half_cell_positive   -> {"working electrode": "positive", **extra}
      half_cell_negative   -> {"working electrode": "negative", **extra}

    ``extra_model_options`` carries author-level options that the
    platform stores data-set agnostically in datasets.yaml
    (e.g. ``{"surface form": "differential",
    "contact resistance": "true"}`` for Jackowska2025).  Nothing is
    guessed here: unsupported configurations raise.
    """
    key = (cell_configuration or "full_cell").strip()

    if key in ("", "full_cell"):
        return None

    if key not in _CELL_CONFIG_BASE_OPTIONS:
        raise ValueError(
            f"Unsupported cell_configuration '{key}'. Supported: "
            f"full_cell, half_cell_positive, half_cell_negative "
            f"(set via datasets.yaml + working_electrode)."
        )

    if key == "half_cell_positive" and working_electrode.strip() not in (
        "",
        "positive",
    ):
        raise ValueError(
            f"cell_configuration='{key}' conflicts with "
            f"working_electrode='{working_electrode}'"
        )
    if key == "half_cell_negative" and working_electrode.strip() not in (
        "",
        "negative",
    ):
        raise ValueError(
            f"cell_configuration='{key}' conflicts with "
            f"working_electrode='{working_electrode}'"
        )

    opts = dict(_CELL_CONFIG_BASE_OPTIONS[key])
    for k, v in (extra_model_options or {}).items():
        opts[str(k)] = v
    return opts


def resolve_model_options(adapter) -> Optional[dict]:
    """Model options implied by a dataset's own datasets.yaml entry.

    Extracted from ``baseline.run_baseline_cell`` so that a second replay
    entry (``simulation.protocol_replay``) applies the SAME half-cell
    translation instead of growing a second copy of it.  Two copies of
    this rule is how a half cell ends up silently replayed as a full cell
    in one path and not the other -- a failure this platform has already
    had once.

    Reads the half-cell first-class block:
      ``cell_configuration``, ``working_electrode``, ``model_options``.
    A ``full_cell`` dataset (or one that declares nothing) gets ``None``,
    which is the exact v0.1-v0.4 model construction.
    """
    extra = getattr(getattr(adapter, "config", None), "extra", None) or {}
    cell_configuration = str(extra.get("cell_configuration") or "full_cell")
    if cell_configuration.strip() in ("", "full_cell"):
        return None

    working_electrode = str(extra.get("working_electrode") or "").strip()
    if working_electrode not in ("positive", "negative"):
        dataset_id = getattr(getattr(adapter, "config", None),
                             "dataset_id", "<unknown>")
        raise ValueError(
            f"dataset '{dataset_id}': "
            f"cell_configuration='{cell_configuration}' requires "
            f"working_electrode in {{positive, negative}} "
            f"(configs/datasets.yaml)"
        )
    return build_model_options(
        cell_configuration=f"half_cell_{working_electrode}",
        working_electrode=working_electrode,
        extra_model_options=extra.get("model_options"),
    )


def load_parameter_values(parameter_set: str) -> pybamm.ParameterValues:
    """
    Load a pybamm parameter set by name, e.g. 'Chen2020'.

    Externally-hosted author sets (H5, e.g. Jackowska2025_2mAh_cm2)
    are loaded as a raw dict via parameter_sources (direct module
    import, no pip install).  Never silently falls back; unknown
    sets raise pybamm's own error.
    """
    if parameter_sources.is_external(parameter_set):
        return pybamm.ParameterValues(
            parameter_sources.load_parameter_dict(parameter_set)
        )
    return pybamm.ParameterValues(parameter_set)


def _resolve_builder_from_config(model_name: str):
    """
    Optional path: resolve a builder function from models.yaml.

    Kept for future datasets that may register extra model ids;
    the core v0.1 path uses the built-in mapping above.
    """
    cfg = load_models_config()

    builders = cfg.get("builders", {})

    key = _canonical(model_name)

    if key not in builders:
        return None

    module_path, attr = builders[key].split(":")

    module = importlib.import_module(module_path)

    return getattr(module, attr)


def get_solver_config() -> dict:
    """Solver defaults from models.yaml (IDAKLU rtol/atol)."""
    cfg = load_models_config()

    solver = cfg.get("solver", {})

    return dict(solver)


def get_experiment_config() -> dict:
    """Experiment defaults from models.yaml (period, calc_esoh)."""
    cfg = load_models_config()

    exp = cfg.get("experiment", {})

    return dict(exp)
