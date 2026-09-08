# ============================================================
# Half-cell pilot H7 - Gate A/B for the C/10 first replay
#
# Gate A (platform equivalence): replay the SAME inputs with an
# INDEPENDENT pybamm solve (no platform runner code) and compare
# against the platform-produced C0p1_time_aligned.csv.  The two
# should agree to solver round-off (~1e-9 V).
#
# Gate B (scientific reproduction, attribution only): re-run the
# independent solve with the AUTHORS' C/10 fitted diffusivity
# scaling (1.157, output.txt) and compare to the authors' saved
# simulation (results/C_10_discharge.csv).  This separates
# "as-published D=1.0 error" (published set out-of-the-box) from
# "author pipeline reproduction" and is NOT a fit of our own.
# ============================================================
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pybamm  # noqa: E402

from battery_sim.models import parameter_sources  # noqa: E402
from battery_sim.registry import get_dataset  # noqa: E402

AUTHOR_C10 = (
    ROOT / "external/Jackowska-2025-JPS/2mAh_cm2/results/C_10_discharge.csv"
)
PLATFORM_TA = (
    ROOT / "outputs/platform/birmingham_ncm920305/baseline/DFN/"
    "cell2mAhcm2/C0p1_time_aligned.csv"
)


def independent_replay(scale: float):
    """Standalone as-published(±D-scale) DFN half-cell replay."""
    adapter = get_dataset("birmingham_ncm920305")
    df = adapter.load_processed_discharge("2mAhcm2", "Cover10")
    t = df["time_s"].to_numpy(float)
    I = df["current_A"].to_numpy(float)
    init = df.attrs["initialisation"]

    pv = pybamm.ParameterValues(
        parameter_sources.load_parameter_dict("Jackowska2025_2mAh_cm2")
    )
    pv["Ambient temperature [K]"] = 298.15
    pv["Initial temperature [K]"] = 298.15
    pv["Current function [A]"] = pybamm.Interpolant(t, I, pybamm.t)
    conc_key = str(init["concentration_parameter"])
    max_key = str(init["max_concentration_parameter"])
    x0 = float(init["stoichiometry_from_ocp"])
    pv[conc_key] = x0 * float(pv[max_key])
    pv["Positive electrode diffusivity scaling factor"] = scale

    model = pybamm.lithium_ion.DFN(
        {
            "working electrode": "positive",
            "surface form": "differential",
            "contact resistance": "true",
        }
    )
    sim = pybamm.Simulation(model, parameter_values=pv)
    sol = sim.solve(t_eval=t)
    # the solve may terminate at the 2.5 V event before t[-1]
    t_s = np.asarray(sol.t, dtype=float)
    V_s = np.asarray(
        sol["Terminal voltage [V]"].entries, dtype=float
    )
    return t, I, df["voltage_V"].to_numpy(float), t_s, V_s, sol


t, I, Vexp, t_s10, V_s10, _ = independent_replay(1.0)

# ---- Gate A: platform vs independent, same inputs --------------
pl = pd.read_csv(PLATFORM_TA)
tp = pl["time_s"].to_numpy(float)
vp = pl["voltage_sim_V"].to_numpy(float)
ve = pl["voltage_exp_V"].to_numpy(float)
d = np.interp(tp, t_s10, V_s10) - vp  # same grid as the platform
print(f"[Gate A] platform vs independent replay on {len(tp)} pts:")
print(f"  max|dV| = {np.max(np.abs(d))*1000:.6f} mV")
print(f"  mean|dV| = {np.mean(np.abs(d))*1000:.3e} mV")

# sanity: platform exp column must equal the adapter window
print(f"  platform exp == adapter exp max|d| = "
      f"{np.max(np.abs(ve - np.interp(tp, t, Vexp)))*1000:.2e} mV")

# ---- Gate B: authors' fitted C/10 scaling (1.157) ---------------
FITTED_C10 = 1.157  # output.txt L237 -> [Cover10, Cover5, Cover2, 1C, 2C]
_, _, _, t_sf, V_sf, sol_fit = independent_replay(FITTED_C10)

# common t range up to the experimental cutoff row
end = t[-1]
common_end = min(end, float(sol_fit.t[-1]))
cm_s = t_sf <= common_end  # on the solver grid
cm_e = t <= common_end  # on the experimental grid
Vexp_c = np.interp(t_sf[cm_s], t, Vexp)
print(f"\n[Gate B] fitted D={FITTED_C10}: sim duration "
      f"{float(sol_fit.t[-1]):.1f} s of {end:.1f} s")
rmse_fit = float(
    np.sqrt(np.mean((V_sf[cm_s] - Vexp_c) ** 2))
) * 1000
bias_fit = float(np.mean(V_sf[cm_s] - Vexp_c)) * 1000
print(f"  vs experiment: RMSE={rmse_fit:.2f} mV  bias={bias_fit:.2f} mV")

# vs authors' saved simulation over the shared window
au = pd.read_csv(AUTHOR_C10)
tau = au["Time [s]"].to_numpy(float)
vau = au["Voltage [V]"].to_numpy(float)
m = (tau >= t[0]) & (tau <= common_end)
vsim_at_au = np.interp(tau[m], t_sf, V_sf)
print(f"  vs author saved sim ({m.sum()} pts): "
      f"max|dV|={np.max(np.abs(vsim_at_au - vau[m]))*1000:.3f} mV, "
      f"mean|dV|={np.mean(np.abs(vsim_at_au - vau[m]))*1000:.3f} mV")

# as-published attribution numbers (solver-grid RMSE over the
# truncated common window, mirroring the platform metric)
Vexp_ap = np.interp(t_s10, t, Vexp)
rmse_ap = float(np.sqrt(np.mean((V_s10 - Vexp_ap) ** 2))) * 1000
bias_ap = float(np.mean(V_s10 - Vexp_ap)) * 1000
print(f"\n[attribution] as-published D=1.0 vs exp: "
      f"RMSE={rmse_ap:.2f} mV bias={bias_ap:.2f} mV "
      f"(platform 102.26 / -41.24 mV on the same truncated grid)")
