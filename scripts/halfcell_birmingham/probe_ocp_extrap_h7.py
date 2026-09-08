# ============================================================
# H7 init probe - resolve the author initial stoichiometry the
# model must start from so that the simulated rest OCV equals the
# measured 4.1935 V (their saved sim starts at exactly 4.1935 V).
#
# Questions:
#  1. does the pybamm Interpolant (as built in Jackowska2025.py)
#     linearly EXTRAPOLATE above the ocp_discharge.csv top voltage?
#  2. what x0 does the author pipeline's inverse-OCP imply?
#  3. does pure-numpy linear extrapolation reproduce pybamm values?
# ============================================================
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pybamm  # noqa: E402

from battery_sim.models import parameter_sources  # noqa: E402

import pandas as pd

# ---- load author OCP data exactly like Jackowska2025.py --------
tab = pd.read_csv(
    ROOT / "external/Jackowska-2025-JPS/2mAh_cm2/results/ocp_discharge.csv"
)
sto = tab["Stoichiometry"].to_numpy(float)
vv = tab["Voltage [V]"].to_numpy(float)
# sort ascending in sto (as process_1D_data / Interpolant expects)
order = np.argsort(sto, kind="stable")
sto = sto[order]
vv = vv[order]
print(f"OCP table: n={len(sto)}  sto=[{sto[0]:.4f},{sto[-1]:.4f}]  "
      f"V=[{vv[0]:.4f},{vv[-1]:.4f}]")

# pybamm Interpolant exactly as the author builds it
ocp_pb = pybamm.Interpolant(
    sto, vv, pybamm.InputParameter("sto"),
    name="ocp", interpolator="linear",
)
x_in = pybamm.InputParameter("sto")

for x in (0.3028, 0.3109, 0.3110, 0.35):
    # numpy linear extrapolation (piecewise-linear, extend ends)
    xp_asc = sto
    fp_asc = vv
    if x < xp_asc[0]:
        s = (fp_asc[1] - fp_asc[0]) / (xp_asc[1] - xp_asc[0])
        v_np = fp_asc[0] + s * (x - xp_asc[0])
    elif x > xp_asc[-1]:
        s = (fp_asc[-1] - fp_asc[-2]) / (xp_asc[-1] - xp_asc[-2])
        v_np = fp_asc[-1] + s * (x - xp_asc[-1])
    else:
        v_np = float(np.interp(x, xp_asc, fp_asc))
    try:
        v_pb = float(ocp_pb.evaluate(inputs={"sto": x}))
        tag = "OK"
    except Exception as exc:  # noqa: BLE001
        v_pb = np.nan
        tag = f"{type(exc).__name__}: {str(exc)[:80]}"
    print(f"sto={x:.4f}: numpy_extrap={v_np:.5f}  pybamm={v_pb:.5f}  [{tag}]")

# ---- root-find x0 for V0=4.1935 on the numpy linear-extrap curve --
v0_target = 4.1935115
# linear extrapolation model
def v_of_x(x):
    if x < sto[0]:
        s = (vv[1] - vv[0]) / (sto[1] - sto[0])
        return vv[0] + s * (x - sto[0])
    return float(np.interp(x, sto, vv))

# bisection on x in [0.25, 0.31]
lo, hi = 0.25, sto[0]
for _ in range(200):
    mid = 0.5 * (lo + hi)
    if v_of_x(mid) > v0_target:
        lo = mid
    else:
        hi = mid
x0 = 0.5 * (lo + hi)
print(f"\nV0={v0_target:.5f} V -> x0_extrap={x0:.5f}")
c_max = 49225.0
print(f"x0*c_max = {x0*c_max:.1f} mol/m3   (published default 5e3)")
print(f"OCP(x0) check = {v_of_x(x0):.5f}")
