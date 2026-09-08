# ============================================================
# H7 diagnostic - compare the authors' internal figure_5 chain
# (parameters_after_4.pickle) with the PUBLIC Jackowska2025_2mAh_cm2
# set.  Attribution ONLY for the H10 report: the public set is the
# frozen as-published baseline; nothing is fitted or replaced.
# ============================================================
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from battery_sim.models import parameter_sources  # noqa: E402

pub = parameter_sources.load_parameter_dict("Jackowska2025_2mAh_cm2")

# the internal pickles reference the author module under its earlier
# name 'Jackowska2024' -> alias the freshly imported module.
import importlib.util  # noqa: E402
import sys as _sys  # noqa: E402

_info = parameter_sources.EXTERNAL_PARAMETER_SETS["Jackowska2025_2mAh_cm2"]
_d = ROOT / _info["repo_rel"]
_spec = importlib.util.spec_from_file_location(
    "Jackowska2024", _d / "Jackowska2025.py"
)
_m = importlib.util.module_from_spec(_spec)
_sys.modules["Jackowska2024"] = _m
_spec.loader.exec_module(_m)

pk_path = (
    ROOT / "external/Jackowska-2025-JPS/2mAh_cm2/results/"
    "parameters_after_4.pickle"
)
class _TolerantUnpickler(pickle.Unpickler):
    """Pickles from the author chain reference functions that were
    renamed before release (Jackowska2024 -> Jackowska2025).  For a
    scalar-diff diagnostic, missing attributes degrade to None."""

    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (AttributeError, ModuleNotFoundError):
            return None


with open(pk_path, "rb") as f:
    chain = _TolerantUnpickler(f).load()
print(f"pickle type: {type(chain).__name__}")
chain_keys = set(chain.keys())
print(f"n keys={len(chain_keys)}")

interesting = [
    "Maximum concentration in positive electrode [mol.m-3]",
    "Initial concentration in positive electrode [mol.m-3]",
    "Positive electrode thickness [m]",
    "Positive electrode active material volume fraction",
    "Positive electrode diffusivity scaling factor",
    "Positive particle diffusivity scaling factor",
    "Positive electrode OCP [V]",
    "Contact resistance [Ohm.m2]",
    "Positive electrode exchange-current density [A.m-2]",
    "Current function [A]",
    "Nominal cell capacity [A.h]",
    "Electrode area [m2]",
    "Positive electrode porosity",
    "Positive electrode Bruggeman coefficient (electrolyte)",
]


def fmt(v):
    if callable(v):
        return "<callable>"
    try:
        import numbers

        if isinstance(v, numbers.Number):
            return f"{float(v):.6g}"
    except Exception:  # noqa: BLE001
        pass
    s = str(v)
    return s[:80]


print(f"\n{'parameter':<58} {'public':>22} {'after_4':>22}")
for k in interesting:
    pv = pub.get(k, "<absent>")
    cv = chain[k] if k in chain_keys else "<absent>"
    print(f"{k:<58} {fmt(pv):>22} {fmt(cv):>22}")
