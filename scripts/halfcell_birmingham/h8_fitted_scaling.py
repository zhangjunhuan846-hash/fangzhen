# ============================================================
# Half-cell pilot H8-B - author per-rate fitted D-scaling replay
#
# Runs the SAME measured-current half-cell DFN replay at each rate
# with the as-published set (D scale = 1.0) and with the AUTHORS'
# per-rate fitted diffusivity scaling (output.txt L237:
#   Cover10..2C -> [1.157, 2.093, 3.891, 8.580, 12.262]).
#
# This is an ATTRIBUTION study (does the fitted scaling close the
# as-published gap? can the public set + fitted scale reproduce the
# authors' saved results?), NOT a fit and NOT a platform baseline.
# Outputs go to outputs/analysis/halfcell_h8/ so the frozen
# as-published platform baseline in outputs/platform/... is never
# touched.
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

OUT = ROOT / "outputs" / "analysis" / "halfcell_h8"
OUT.mkdir(parents=True, exist_ok=True)

AUTHOR_FITTED = {"Cover10": 1.157, "Cover5": 2.093,
                 "Cover2": 3.891, "1C": 8.580, "2C": 12.262}


def replay(rate: str, scale: float):
    """Measured-current DFN half-cell replay -> (t_s, V_s, Q_s)."""
    adapter = get_dataset("birmingham_ncm920305")
    df = adapter.load_processed_discharge("2mAhcm2", rate)
    t = df["time_s"].to_numpy(float)
    I = df["current_A"].to_numpy(float)
    Vexp = df["voltage_V"].to_numpy(float)
    init = df.attrs["initialisation"]

    pv = pybamm.ParameterValues(
        parameter_sources.load_parameter_dict("Jackowska2025_2mAh_cm2")
    )
    pv["Ambient temperature [K]"] = 298.15
    pv["Initial temperature [K]"] = 298.15
    pv["Current function [A]"] = pybamm.Interpolant(t, I, pybamm.t)
    pv[str(init["concentration_parameter"])] = (
        float(init["stoichiometry_from_ocp"])
        * float(pv[str(init["max_concentration_parameter"])])
    )
    pv["Positive electrode diffusivity scaling factor"] = scale

    model = pybamm.lithium_ion.DFN(
        {
            "working electrode": "positive",
            "surface form": "differential",
            "contact resistance": "true",
        }
    )
    sol = pybamm.Simulation(model, parameter_values=pv).solve(t_eval=t)
    t_s = np.asarray(sol.t, dtype=float)
    V_s = np.asarray(sol["Terminal voltage [V]"].entries, dtype=float)
    try:
        Q_s = float(sol["Discharge capacity [A.h]"].entries[-1])
    except Exception:  # noqa: BLE001
        Q_s = float("nan")
    return t, I, Vexp, t_s, V_s, Q_s


rows = []
adapter_h8 = get_dataset("birmingham_ncm920305")
for rate in ("Cover10", "Cover5", "Cover2", "1C", "2C"):
    df_exp = adapter_h8.load_processed_discharge("2mAhcm2", rate)
    Q_exp = float(df_exp["capacity_Ah"].iloc[-1])
    t, I, Vexp, t_s0, V_s0, Q_s0 = replay(rate, 1.0)
    t, I, Vexp, t_sf, V_sf, Q_sf = replay(rate, AUTHOR_FITTED[rate])

    end = t[-1]
    # metrics on the truncated common window (platform convention)
    for tag, t_s, V_s, Q_s in (("as_published_D1", t_s0, V_s0, Q_s0),
                               ("author_fitted_D", t_sf, V_sf, Q_sf)):
        common_end = min(end, float(t_s[-1]))
        m = t_s <= common_end
        Vexp_c = np.interp(t_s[m], t, Vexp)
        res = V_s[m] - Vexp_c
        rows.append(
            {
                "rate_slug": str(
                    get_dataset("birmingham_ncm920305").rate_info(rate)[
                        "rate_slug"
                    ]
                ),
                "source_rate": rate,
                "replay": tag,
                "D_scale": (1.0 if tag.endswith("D1") else AUTHOR_FITTED[rate]),
                "rmse_mV": float(np.sqrt(np.mean(res ** 2))) * 1000.0,
                "bias_mV": float(np.mean(res)) * 1000.0,
                "coverage_fraction": float(common_end / end),
                "Q_sim_Ah": Q_s,
                "Q_exp_Ah": Q_exp,
                "n_pts": int(m.sum()),
            }
        )
        info = get_dataset("birmingham_ncm920305").rate_info(rate)
        print(
            f"{info['rate_slug']:5s} {rate:8s} {tag:16s} "
            f"D={rows[-1]['D_scale']:<7.3f} "
            f"RMSE={rows[-1]['rmse_mV']:7.2f} mV  "
            f"bias={rows[-1]['bias_mV']:7.2f} mV  "
            f"cov={rows[-1]['coverage_fraction']:.3f}  "
            f"Q_sim={rows[-1]['Q_sim_Ah']:.4f} Ah"
        )

df_out = pd.DataFrame(rows)
df_out.to_csv(OUT / "h8_rate_table.csv", index=False)
print(f"\nwrote {OUT / 'h8_rate_table.csv'}")
