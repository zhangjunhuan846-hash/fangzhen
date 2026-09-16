# ============================================================
# Battery Dataset Simulation Platform
# OCP lookup / inversion -- pybamm-free shared helper
#
# The inverse-OCP initialisation (measured rest OCV -> initial Li
# fraction x0) was implemented inline in two dataset adapters before
# this module existed (sintef_graphite, birmingham_ncm920305).  New
# adapters should use this one instead of adding a third copy; the two
# existing copies are left untouched because they are covered by tests
# and migrating them is a separate, riskier change.
#
# Pure data: reads a vendored CSV, does piecewise-linear inversion.  No
# pybamm import, because dataset adapters are pure data I/O.
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

#: How far outside the table's own voltage span an extrapolation is
#: tolerated before the caller is told the rest OCV is unusable.
OCP_EXTRAPOLATION_TOL_V = 0.05


def load_ocp_curve(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Read a two-column (stoichiometry, voltage) table, sorted by V.

    Sorting by VOLTAGE is what makes the inversion monotone; the source
    file is written in stoichiometry order and is not monotone in V.
    """
    ocp = pd.read_csv(Path(path), header=None,
                      names=["stoichiometry", "voltage_V"])
    sto = ocp["stoichiometry"].to_numpy(float)
    vv = ocp["voltage_V"].to_numpy(float)
    order = np.argsort(vv, kind="stable")
    return sto[order], vv[order]


def inverse_ocp(
    sto: np.ndarray,
    voltage_V_ascending: np.ndarray,
    voltage_V: float,
    *,
    extrapolation_tol_V: float = OCP_EXTRAPOLATION_TOL_V,
) -> float:
    """Stoichiometry x with OCP(x) = ``voltage_V``.

    Piecewise-linear inversion using the SAME linear extrapolation at
    both ends that a linear interpolant performs -- never ``np.interp``
    clipping, which would silently pin x0 to a table edge and make a
    mis-specified initial state look like a clean one.
    """
    sto = np.asarray(sto, dtype=float)
    vv = np.asarray(voltage_V_ascending, dtype=float)
    if sto.size < 2 or vv.size != sto.size:
        raise ValueError("OCP table needs >= 2 rows of (sto, V)")
    vmin, vmax = float(vv[0]), float(vv[-1])
    if (voltage_V < vmin - extrapolation_tol_V
            or voltage_V > vmax + extrapolation_tol_V):
        raise ValueError(
            f"rest OCV {voltage_V:.4f} V more than "
            f"{extrapolation_tol_V} V outside the OCP table "
            f"[{vmin:.4f}, {vmax:.4f}] V"
        )
    if voltage_V < vmin:
        s = (sto[1] - sto[0]) / (vv[1] - vv[0])
        return float(sto[0] + s * (voltage_V - vv[0]))
    if voltage_V > vmax:
        s = (sto[-1] - sto[-2]) / (vv[-1] - vv[-2])
        return float(sto[-1] + s * (voltage_V - vv[-1]))
    return float(np.interp(voltage_V, vv, sto))


__all__ = [
    "OCP_EXTRAPOLATION_TOL_V",
    "inverse_ocp",
    "load_ocp_curve",
]
