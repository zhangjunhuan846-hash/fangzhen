# ============================================================
# Battery Dataset Simulation Platform -- v0.5 half-cell pilot
# External parameter-set source registry (H5)
#
# The Birmingham NCM920305 pilot uses the AUTHORS' OWN PyBaMM
# parameter set (Jackowska2025_2mAh_cm2), which ships in the
# companion repository
#   external/Jackowska-2025-JPS
# and is registered there only through the package entry point
# ``pybamm_parameter_sets`` (the repo is NOT pip-installable into
# this environment: it pins PyBaMM==25.8.0, see
# docs/halfcell_birmingham_params_audit.md).
#
# This module therefore loads the parameter dict by DIRECT dynamic
# import of the author module (file-spec) -- NO pip install, NO
# entry-point registration.  It also exposes the auditable mapping
# between the author parameter keys and what PyBaMM 26.8 actually
# keeps, so no key is ever silently renamed or re-purposed.
#
# The four frozen v0.1-v0.4 datasets never touch this path:
#   load_parameter_values("Chen2020") keeps its exact old behaviour.
# ============================================================

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from battery_sim.paths import ROOT

# ------------------------------------------------------------------
# Registry of externally-loaded parameter sets.
#
#   repo_rel      repo directory relative to the project root
#   module        python module file name (no .py)
#   function      callable inside that module returning the dict
#   electrode_subdir  sub-folder of the repo holding the electrode
#                     data used by the module at import time
# ------------------------------------------------------------------
EXTERNAL_PARAMETER_SETS: Dict[str, Dict[str, str]] = {
    "Jackowska2025_2mAh_cm2": {
        "repo_rel": "external/Jackowska-2025-JPS",
        "module": "Jackowska2025",
        "function": "get_parameter_values_2mAh_cm2",
        "electrode_subdir": "2mAh_cm2",
    },
}


def is_external(parameter_set: str) -> bool:
    """True if ``parameter_set`` is loaded from an external repo dict."""
    return parameter_set in EXTERNAL_PARAMETER_SETS


def source_info(parameter_set: str) -> Optional[dict]:
    """Registry entry for an external set, or None."""
    return dict(EXTERNAL_PARAMETER_SETS.get(parameter_set, {}))


def repo_dir(parameter_set: str) -> Optional[Path]:
    """Absolute repo directory for an external set (or None)."""
    info = EXTERNAL_PARAMETER_SETS.get(parameter_set)
    if info is None:
        return None
    d = ROOT / info["repo_rel"]
    return d if d.is_dir() else None


def repo_commit(parameter_set: str) -> str:
    """
    HEAD commit of the external parameter repo (short sha), or ""
    if the directory / .git is unavailable.
    """
    d = repo_dir(parameter_set)
    if d is None or not (d / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:  # noqa: BLE001 - non-fatal provenance field
        pass
    return ""


def _import_module(parameter_set: str):
    """Dynamic file-spec import of the author module (lazy, cached)."""
    info = EXTERNAL_PARAMETER_SETS[parameter_set]
    d = repo_dir(parameter_set)
    if d is None:
        raise FileNotFoundError(
            f"external parameter repo for '{parameter_set}' not found: "
            f"{ROOT / info['repo_rel']}"
        )
    module_path = d / f"{info['module']}.py"
    if not module_path.is_file():
        raise FileNotFoundError(
            f"module '{info['module']}' not found in {d} "
            f"(expected {module_path})"
        )
    spec = importlib.util.spec_from_file_location(
        f"external_{info['module']}", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build import spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    # the author module reads its data files relative to its own
    # __file__ at import time -> register it in sys.modules first
    sys.modules[f"external_{info['module']}"] = module
    spec.loader.exec_module(module)
    return module


def load_parameter_dict(parameter_set: str) -> dict:
    """
    The raw parameter dict for an external set (author semantics
    preserved verbatim; no renaming, no silent default override).
    """
    info = EXTERNAL_PARAMETER_SETS[parameter_set]
    module = _import_module(parameter_set)
    fn = getattr(module, info["function"])
    if fn is None:
        raise AttributeError(
            f"external set '{parameter_set}': no function "
            f"'{info['function']}' in {info['module']}"
        )
    raw = fn()
    if not isinstance(raw, dict):
        raise TypeError(
            f"external set '{parameter_set}': {info['function']}() "
            f"returned {type(raw).__name__}, expected dict"
        )
    return dict(raw)


def sha256_file(path: Path) -> str:
    """SHA-256 of a file (hex), for provenance manifests."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def auto_materialised_keys(source_dict: dict, pv_keys) -> List[str]:
    """
    Keys present in a constructed ParameterValues object that are NOT
    in the raw source dict.  PyBaMM 26.8 auto-materialises new
    canonical keys for renamed legacy parameters (e.g. it adds
    ``Positive particle diffusivity scaling factor`` next to the
    author's ``Positive electrode diffusivity scaling factor``).
    They are reported (never silently dropped or renamed).
    """
    src = set(source_dict.keys())
    return sorted(k for k in pv_keys if k not in src)
