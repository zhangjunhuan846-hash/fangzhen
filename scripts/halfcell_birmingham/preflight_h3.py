"""H3 preflight smoke — half-cell on PyBaMM 26.8 WITHOUT touching battery_sim/.

Tests (platform-external, per H0 taskbook H3):
  1. pybamm / numpy versions in the active env
  2. direct import of the author's Jackowska2025 module (repo path on sys.path;
     NO pip install, NO entry-point registration)
  3. pybamm.ParameterValues(get_parameter_values_2mAh_cm2()) constructs
  4. (informational) entry-point name lookup without install -> expected failure
  5. DFN build + param.process_model with the AUTHOR options
     {"working electrode":"positive","surface form":"differential","contact resistance":"true"}
  6. SPMe build + process_model (author options first, minimal fallback)
  7. short CC discharge solve (C/10, 30 min) as an integration smoke

Initial concentration is mapped from the experimental pre-discharge rest OCV
(V0 = 4.1935 V for C/10) using the author's OCP file (inverse interpolation),
mirroring figure_5.py. This is needed because the published default
(5e3 mol/m3) starts at sto~0.10 which contradicts the 4.19 V rest OCV.

Exit code: 0 = PASS gate (author options DFN works); 1 = FAIL/STOP.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = str(Path(__file__).resolve().parents[2])  # repo root
REPO = os.path.join(ROOT, "external", "Jackowska-2025-JPS")

import pybamm  # noqa: E402

print(f"pybamm {pybamm.__version__}")
print(f"numpy {np.__version__}")

FAILED = []


def check(name: str, fn, informational: bool = False):
    t0 = time.time()
    try:
        out = fn()
        print(f"[PASS] {name}  ({time.time()-t0:.1f}s)")
        return out
    except Exception as exc:  # noqa: BLE001
        if not informational:
            FAILED.append(name)
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    # --- 2/3: import author module + parameter dict -------------------------
    sys.path.insert(0, REPO)
    mod = check("import Jackowska2025 (needs pybamm.parameters.process_1D_data)", lambda: __import__("Jackowska2025"))

    def build_pv():
        pv = pybamm.ParameterValues(mod.get_parameter_values_2mAh_cm2())
        return pv

    pv = check("ParameterValues(get_parameter_values_2mAh_cm2())", build_pv)
    if pv is None:
        print("STOP: parameter set could not be constructed on PyBaMM 26.8.")
        return 1
    print("   nominal cap [Ah] =", pv["Nominal cell capacity [A.h]"])
    print("   electrode area [m2] =", float(pv["Electrode width [m]"] * pv["Electrode height [m]"]))
    print("   R_contact [Ohm] =", pv["Contact resistance [Ohm]"])
    print("   c_max [mol/m3] =", pv["Maximum concentration in positive electrode [mol.m-3]"])

    # --- 4: informational entry-point lookup --------------------------------
    def lookup():
        return pybamm.ParameterValues("Jackowska2025_2mAh_cm2")

    ep = check("entry-point name lookup (expected to FAIL w/o install) [informational]", lookup, informational=True)

    # --- initial concentration from experimental rest OCV -------------------
    ocp = pd.read_csv(os.path.join(REPO, "2mAh_cm2", "results", "ocp_discharge.csv"))
    sto = ocp["Stoichiometry"].to_numpy(float)
    vv = ocp["Voltage [V]"].to_numpy(float)
    order = np.argsort(vv)
    v0 = 4.1935  # C/10 file first-row rest OCV
    soc_init = float(np.interp(v0, vv[order], sto[order]))
    c_max = float(pv["Maximum concentration in positive electrode [mol.m-3]"])
    print(f"   inverse-OCP: V0={v0} V -> soc_init={soc_init:.4f} "
          f"c_s_init={soc_init*c_max:.1f} mol/m3")
    pv["Initial concentration in positive electrode [mol.m-3]"] = soc_init * c_max

    author_options = {
        "working electrode": "positive",
        "surface form": "differential",
        "contact resistance": "true",
    }
    minimal_options = {"working electrode": "positive"}

    # --- 5: DFN build + process --------------------------------------------
    def build_dfn():
        model = pybamm.lithium_ion.DFN(author_options)
        pv.process_model(model)
        return model

    dfn = check("DFN build + process_model (author options)", build_dfn)

    # --- 6: SPMe build + process -------------------------------------------
    def build_spme_auth():
        model = pybamm.lithium_ion.SPMe(author_options)
        pv.process_model(model)
        return model

    spme_auth = check("SPMe build + process_model (author options)", build_spme_auth)

    if spme_auth is None:
        def build_spme_min():
            model = pybamm.lithium_ion.SPMe(minimal_options)
            pv.process_model(model)
            return model

        spme_min = check("SPMe build + process_model (minimal options) [fallback]", build_spme_min)

    # --- 7: short CC integration smoke -------------------------------------
    def solve_dfm():
        sim = pybamm.Simulation(
            pybamm.lithium_ion.DFN(author_options),
            parameter_values=pv,
            experiment=pybamm.Experiment(["Discharge at C/10 for 30 minutes"]),
            solver=pybamm.IDAKLUSolver(),
        )
        sol = sim.solve()
        v = sol["Voltage [V]"].entries
        return f"V_range=[{v.min():.4f},{v.max():.4f}] V, t_end={sol.t[-1]:.1f} s, steps={len(v)}"

    sol_dfn = check("DFN short solve: CC C/10 30 min (author options)", solve_dfm)
    if sol_dfn:
        print("   " + sol_dfn)

    # --- verdict ------------------------------------------------------------
    print("-" * 60)
    if FAILED:
        print(f"H3 gate FAILED on: {FAILED}")
        return 1
    print("H3 gate PASS: Jackowska2025_2mAh_cm2 + half-cell DFN/SPMe work on PyBaMM 26.8 "
          "(direct import, no install).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
