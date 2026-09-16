"""Print the FULL traceback for a function-valued override, so the failing
line is named instead of guessed at."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pybamm  # noqa: E402

from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.baseline import run_baseline_cell  # noqa: E402

KEY = "Positive particle diffusivity [m2.s-1]"
adapter = get_dataset("sintef_graphite")
ref = pybamm.ParameterValues("Ecker2015_graphite_halfcell")[KEY]


def scaled(*args):
    return 1.2 * ref(*args)


scaled.__name__ = "graphite_diffusivity_scaled_1.2"

try:
    run_baseline_cell(
        adapter, "SPM", "4ccc47", rate="pOCV-deli",
        parameter_set="Ecker2015_graphite_halfcell",
        plot=False, quiet=True,
        parameter_overrides={KEY: scaled},
    )
    print("OK -- no exception")
except Exception:  # noqa: BLE001
    traceback.print_exc()
