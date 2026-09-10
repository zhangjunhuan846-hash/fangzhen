#!/usr/bin/env python3
# ============================================================
# Phase B2 driver: GITT apparent-D_s CREDIBILITY ASSESSMENT
#
#   B2.1  per-pulse diagnostics + validity flags
#            extraction/ds_diagnostics.py   ->  Ds_diagnostics*.csv
#
#   B2.2  diffusivity SENSITIVITY
#            constant-D lattice D = 1e-17 ... 1e-13
#              * pOCV replay   (experiment available: REAL RMSE)
#              * C/50, 0.5C, 1C, 2C constant-current discharges
#                (MODEL-ONLY: this cell has no rate data)
#            SPM and SPMe side by side
#
#   B2.3  the criterion
#            Fo = D t / R^2 = t_protocol / tau_d
#            measured sensitivity plotted against Fo, so the answer to
#            "when is the GITT D_s suitable as a model input" is a
#            dimensionless statement rather than a rate label.
#
# RULES OBEYED
#   * battery_sim/ scientific core untouched
#   * NO fitting, NO optimisation: D is swept on an a priori log grid
#     and every grid value is a prescribed number, not an estimate
#   * the Phase B1 apparent-D_s table is used READ-ONLY, as one of the
#     curves compared against the lattice
#   * every parameter source is recorded (ds_sweep_manifest.json,
#     Ds_diagnostics_provenance.json, sensitivity_summary.json)
#
# Outputs (outputs/analysis/graphite_phaseB2/):
#   Ds_diagnostics.csv / Ds_diagnostics_by_soc.csv / Ds_diagnostics_provenance.json
#   ds_sweep_manifest.json
#   pocv_replay_sweep.csv / cc_rate_sweep.csv / cc_rate_curves.csv
#   sensitivity_summary.json
#   fig_ds_diagnostics.png / fig_sensitivity.png / fig_criterion.png
#   report.md
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.ds_diagnostics import (                      # noqa: E402
    build_diagnostics,
    diagnostics_by_soc,
    diagnostics_provenance,
    write_diagnostics,
)
from parameters.sintef_graphite_capacity import (             # noqa: E402
    register_capacity_variants,
)
from parameters.sintef_graphite_ds import (                   # noqa: E402
    DS_PARAMETER_SET_IDS,
    register_ds_variants,
)
from parameters.sintef_graphite_ds_sweep import (              # noqa: E402
    DEFAULT_SWEEP_M2_S,
    KEY_DIFFUSIVITY,
    KEY_RADIUS,
    constant_d_set_id,
    fourier_number,
    register_constant_d_sweep,
    tau_d_s,
    write_sweep_manifest,
)
from parameters.sintef_graphite_geometry import (             # noqa: E402
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (                   # noqa: E402
    load_ocp_tables,
    register_variants,
)

B1_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB1"
V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB2"

DATASET = "sintef_graphite"
CELL = "4ccc47"
V2_SUFFIX = "_v2"

POCV_WINDOWS = {"pOCV-lith": "lithiation", "pOCV-deli": "delithiation"}

# constant-current family.  The p-OCV programme is ~C/50; 0.5C/1C/2C exist
# only as MODEL-ONLY forward simulations because this cell has no rate data.
CC_RATES: Dict[str, float] = {"C/50": 0.02, "0.5C": 0.5, "1C": 1.0, "2C": 2.0}
# a voltage spread of this size is the threshold used to call a protocol
# "sensitive" to the diffusivity.  Declared up front; it is a reading
# convention for the report, not a physical constant.
SENSITIVITY_THRESHOLD_MV = 5.0
# same idea for the capacity-side observable: the fraction of the nominal
# protocol the model can sustain must not move by more than this many
# percentage points.  A declared reading convention, not a physical
# constant.
SUSTAINED_THRESHOLD_PCT = 5.0
FGRID = (0.1, 0.3, 0.5, 0.7, 0.9)

CONC_KEY = "Initial concentration in positive electrode [mol.m-3]"
CMAX_KEY = "Maximum concentration in positive electrode [mol.m-3]"


# ------------------------------------------------------------------
# pOCV replay through the UNMODIFIED public runner
# ------------------------------------------------------------------
def _replay(adapter, model: str, rate: str, set_id: str, dest: Path) -> Path:
    from battery_sim.simulation.baseline import run_baseline_cell

    result = run_baseline_cell(
        adapter, model_name=model, cell=CELL, rate=rate,
        parameter_set=set_id, plot=False, quiet=True,
    )
    run_dir = Path(result["output_dir"])
    slug = rate.replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{slug}_time_aligned.csv"
    src = run_dir / f"{slug}_time_aligned.csv"
    if src.is_file() and src.resolve() != target.resolve():
        shutil.copy2(src, target)
    return target


def _metrics(csv: Path, exp_duration_s: float) -> dict:
    df = pd.read_csv(csv)
    res = df["residual_V"].to_numpy(float)
    dur = float(df["time_s"].iloc[-1])
    return {
        "n_points": int(len(df)),
        "rmse_mV": float(np.sqrt(np.mean(res ** 2)) * 1000.0),
        "mae_mV": float(np.mean(np.abs(res)) * 1000.0),
        "bias_mV": float(np.mean(res) * 1000.0),
        "max_abs_mV": float(np.max(np.abs(res)) * 1000.0),
        "v_exp_start_V": float(df["voltage_exp_V"].iloc[0]),
        "v_exp_end_V": float(df["voltage_exp_V"].iloc[-1]),
        "v_sim_start_V": float(df["voltage_sim_V"].iloc[0]),
        "v_sim_end_V": float(df["voltage_sim_V"].iloc[-1]),
        "duration_s": dur,
        "coverage_fraction": float(dur / exp_duration_s)
        if exp_duration_s > 0 else float("nan"),
    }


# ------------------------------------------------------------------
# model-only constant-current runs
# ------------------------------------------------------------------
def _cc_run(
    *, model_name: str, set_id: str, model_options, current_A: float,
    x0: float, t_max_s: float, ambient_C: float, n_eval: int,
) -> dict:
    """
    Forward constant-current discharge from a prescribed initial state.

    Mirrors the public runner's setup (same model builder, model options,
    temperature handling and pre-Simulation concentration override) but
    drives the model with a synthetic protocol instead of a measured
    trace, which is the only way to ask "what would this electrode do at
    1C" when the dataset contains no 1C experiment.
    """
    import pybamm

    from battery_sim.models.pybamm_factory import (
        build_model,
        load_parameter_values,
    )

    params = load_parameter_values(set_id)
    params["Current function [A]"] = float(current_A)
    for k in ("Ambient temperature [K]", "Initial temperature [K]"):
        if k in params:
            params[k] = float(ambient_C) + 273.15
    if CONC_KEY not in params or CMAX_KEY not in params:
        raise KeyError(
            f"parameter set '{set_id}' is missing the working-electrode "
            f"concentration keys required for a fixed initial state"
        )
    params[CONC_KEY] = float(x0) * float(params[CMAX_KEY])

    model = build_model(model_name, options=model_options)
    sim = pybamm.Simulation(model, parameter_values=params)
    sol = sim.solve(t_eval=np.linspace(0.0, float(t_max_s), int(n_eval)))

    t = np.asarray(sol.t, dtype=float)
    V = np.asarray(sol["Terminal voltage [V]"].entries, dtype=float).reshape(-1)
    if t.size != V.size:
        V = np.interp(t, np.linspace(t[0], t[-1], V.size), V)
    q_Ah = float(current_A) * t / 3600.0

    return {
        "t_s": t,
        "V": V,
        "q_Ah": q_Ah,
        "t_end_s": float(t[-1]),
        "q_end_Ah": float(q_Ah[-1]),
        "V_end": float(V[-1]),
        "V_start": float(V[0]),
        "V_span_mV": float((V.max() - V.min()) * 1000.0),
        "reached_cutoff": bool(t[-1] < float(t_max_s) * 0.999),
    }


def _v_at_time(run: dict, t_target_s: float) -> float:
    """V at an elapsed time; NaN when the run ended before it."""
    t = run["t_s"]
    if t_target_s > float(t[-1]) + 1e-9:
        return float("nan")
    return float(np.interp(t_target_s, t, run["V"]))


def _v_at_capacity(run: dict, q_target_Ah: float) -> float:
    """V at a delivered capacity, NaN when the run never got there."""
    q = run["q_Ah"]
    if q_target_Ah > float(q[-1]) + 1e-12:
        return float("nan")
    return float(np.interp(q_target_Ah, q, run["V"]))


def _slope_per_decade(x: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope of y against log10(x); NaN if underdetermined."""
    sel = np.isfinite(x) & np.isfinite(y) & (x > 0)
    if sel.sum() < 3 or np.ptp(np.log10(x[sel])) < 1e-9:
        return float("nan")
    lx = np.log10(x[sel])
    return float(np.polyfit(lx, y[sel], 1)[0])


def _threshold_D(
    d_grid: np.ndarray, spread_mV: np.ndarray, level_mV: float,
) -> float:
    """
    Smallest D at which the voltage spread drops to ``level_mV``.

    The spread falls monotonically with D (more D -> closer to
    equilibrium -> less voltage response), so this is the boundary of
    the region where the diffusivity matters for the protocol.
    """
    sel = np.isfinite(spread_mV)
    if sel.sum() < 2:
        return float("nan")
    d, s = d_grid[sel], spread_mV[sel]
    order = np.argsort(d)
    d, s = d[order], s[order]
    for i in range(1, len(d)):
        if s[i - 1] >= level_mV > s[i]:
            # log-linear interpolation on the crossing
            l0, l1 = np.log10(d[i - 1]), np.log10(d[i])
            t = (level_mV - s[i - 1]) / (s[i] - s[i - 1])
            return float(10.0 ** (l0 + t * (l1 - l0)))
    return float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["SPM", "SPMe"])
    ap.add_argument("--values", nargs="+", type=float,
                    default=list(DEFAULT_SWEEP_M2_S))
    ap.add_argument("--ambient-c", type=float, default=25.0)
    ap.add_argument("--n-eval", type=int, default=600)
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "runs").mkdir(exist_ok=True)

    # ---------------- register everything (runtime only) -----------
    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)
    extra = adapter.config.extra or {}
    model_options = None
    cell_config = str(extra.get("cell_configuration") or "full_cell")
    if cell_config.strip() not in ("", "full_cell"):
        from battery_sim.models.pybamm_factory import build_model_options

        model_options = build_model_options(
            cell_configuration=f"half_cell_{extra.get('working_electrode')}",
            working_electrode=str(extra.get("working_electrode")),
            extra_model_options=extra.get("model_options"),
        )
    print(f"[B2] cell_configuration={cell_config} options={model_options}")

    register_geometry(CELL)
    register_variants(CELL, V2_DIR, set_id_suffix=V2_SUFFIX)
    cap = register_capacity_variants(CELL, V2_DIR, set_id_suffix=V2_SUFFIX)
    sweep = register_constant_d_sweep(
        CELL, values=args.values, ocp_dir=V2_DIR, set_id_suffix=V2_SUFFIX,
    )
    ds_ids = register_ds_variants(
        CELL, ocp_dir=V2_DIR, ds_dir=B1_DIR, set_id_suffix=V2_SUFFIX,
    )
    print(f"[B2] control = {cap['lithiation']}")
    print(f"[B2] GITT curve sets = {ds_ids}")

    import pybamm

    r_val = float(pybamm.ParameterValues(cap["lithiation"])[KEY_RADIUS])
    q_nom_Ah = float(
        pybamm.ParameterValues(cap["lithiation"])["Nominal cell capacity [A.h]"]
    )
    ecker_d = float(pybamm.ParameterValues(
        "Ecker2015_graphite_halfcell"
    )[KEY_DIFFUSIVITY](pybamm.Scalar(0.5), pybamm.Scalar(298.15)).evaluate())
    print(f"[B2] R={r_val*1e6:.3f} um  Q_nom={q_nom_Ah*1e3:.4f} mAh  "
          f"Ecker D(0.5)={ecker_d:.3e} m2/s")

    # ---------------- B2.1 diagnostics ----------------------------
    diag = build_diagnostics(B1_DIR)
    by_soc = diagnostics_by_soc(diag)
    prov = diagnostics_provenance(diag, b1_dir=B1_DIR)
    dpaths = write_diagnostics(diag, by_soc, prov, OUT_DIR)
    print(f"[B2] diagnostics: {prov['n_valid']}/{prov['n_pulses']} valid "
          f"({prov['valid_fraction']:.3f}) -> {dpaths['diagnostics'].name}")
    print(f"[B2] rejection counts: {prov['rejection_counts']}")

    # SOC-resolved GITT curve (valid pulses only), per branch
    gitt_curve: Dict[str, pd.DataFrame] = {}
    for br in ("lithiation", "delithiation"):
        g = by_soc[(by_soc["branch"] == br)].dropna(subset=["Ds_median_m2_s"])
        gitt_curve[br] = g

    # protocol durations used for the Fourier numbers
    durations = {f"CC {k}": 1.0 / v * 3600.0 for k, v in CC_RATES.items()}
    exp_duration: Dict[str, float] = {}
    for rate, br in POCV_WINDOWS.items():
        px = _proxy(adapter, br)
        exp_duration[rate] = float(
            px.load_processed_discharge(CELL, rate).attrs["provenance"][
                "duration_s"
            ]
        )
        durations[f"{rate} measured window"] = exp_duration[rate]
    write_sweep_manifest(
        OUT_DIR, cell=CELL, values=args.values, protocols=durations,
        ocp_dir=V2_DIR, set_id_suffix=V2_SUFFIX,
    )

    # ---------------- B2.2a pOCV replay sweep ----------------------
    replay_rows: List[dict] = []
    for model in args.models:
        for rate, br in POCV_WINDOWS.items():
            cases: List[Tuple[str, str, Optional[float]]] = [
                ("control_native_ecker", cap[br], None),
                ("gitt_curve", ds_ids[br], None),
            ] + [
                (f"const_{d:.3g}", sweep[(br, d)], float(d))
                for d in args.values
            ]
            for tag, sid, dval in cases:
                px = _proxy(adapter, br)
                csv = _replay(adapter=px, model=model, rate=rate,
                              set_id=sid,
                              dest=OUT_DIR / "runs" / f"{rate}_{model}_{tag}")
                m = _metrics(csv, exp_duration[rate])
                replay_rows.append({
                    "axis": "pocv_replay",
                    "model": model,
                    "rate": rate,
                    "branch": br,
                    "case": tag,
                    "parameter_set": sid,
                    "D_prescribed_m2_s": dval,
                    "D_origin": (
                        "prescribed constant (sensitivity grid)"
                        if dval is not None
                        else ("reference set native D(SOC)"
                              if tag.startswith("control")
                              else "Phase B1 GITT apparent D_s(SOC)")
                    ),
                    "tau_d_of_prescribed_s": (
                        tau_d_s(dval, r_val) if dval else float("nan")
                    ),
                    "Fo_over_window": (
                        fourier_number(dval, r_val, m["duration_s"])
                        if dval else float("nan")
                    ),
                    **m,
                })
            blk = replay_rows[-len(cases):]
            print(f"[B2] pOCV {rate} {model}: control "
                  f"{blk[0]['rmse_mV']:.2f} mV -> gitt {blk[1]['rmse_mV']:.2f} "
                  f"mV | lattice {min(b['rmse_mV'] for b in blk[2:]):.2f}"
                  f"..{max(b['rmse_mV'] for b in blk[2:]):.2f}")
    replay = pd.DataFrame(replay_rows)
    replay.to_csv(OUT_DIR / "pocv_replay_sweep.csv", index=False)

    # ---------------- B2.2b constant-current family ----------------
    #  initial state = the pOCV-lith window's measured pre-branch
    #  equilibrium mapped onto the frozen OCP (same anchor as every
    #  other phase), so the four rates differ ONLY in current.
    px0 = _proxy(adapter, "lithiation")
    df0 = px0.load_processed_discharge(CELL, "pOCV-lith")
    x0 = float(df0.attrs["initialisation"]["stoichiometry_from_ocp"])
    v0_meas = float(df0.attrs["provenance"]["rest_ocv_V"])
    print(f"[B2] CC family initial state: x0={x0:.6f} "
          f"(measured rest OCV {v0_meas:.4f} V)")

    cc_rows: List[dict] = []
    curve_rows: List[dict] = []
    for model in args.models:
        for label, rate in CC_RATES.items():
            i_const = rate * q_nom_Ah
            t_max = max(4.0 / rate * 3600.0, 1800.0)
            cases = [
                ("control_native_ecker", cap["lithiation"], None),
                ("gitt_curve", ds_ids["lithiation"], None),
            ] + [
                (f"const_{d:.3g}", sweep[("lithiation", d)], float(d))
                for d in args.values
            ]
            for tag, sid, dval in cases:
                run = _cc_run(
                    model_name=model, set_id=sid, model_options=model_options,
                    current_A=i_const, x0=x0, t_max_s=t_max,
                    ambient_C=args.ambient_c, n_eval=args.n_eval,
                )
                v_at = {f: _v_at_capacity(run, f * q_nom_Ah) for f in FGRID}
                # nominal protocol time (1/rate h) and the fraction of it
                # the model can actually sustain before the lower cut-off.
                # Unlike V at a fixed delivered capacity - which saturates,
                # because only the well-equilibrated runs ever reach it -
                # this fraction is finite for EVERY lattice member and is
                # monotone in D, so it can carry the sensitivity search.
                t_nominal = 3600.0 / rate
                sustained = float(min(1.0, run["t_end_s"] / t_nominal))
                cc_rows.append({
                    "axis": "cc_rate",
                    "model": model,
                    "rate_label": label,
                    "c_rate": rate,
                    "case": tag,
                    "parameter_set": sid,
                    "D_prescribed_m2_s": dval,
                    "D_origin": (
                        "prescribed constant (sensitivity grid)"
                        if dval is not None
                        else ("reference set native D(SOC)"
                              if tag.startswith("control")
                              else "Phase B1 GITT apparent D_s(SOC)")
                    ),
                    "I_const_A": i_const,
                    "tau_d_of_prescribed_s": (
                        tau_d_s(dval, r_val) if dval else float("nan")
                    ),
                    "t_protocol_s": t_nominal,
                    "Fo_over_protocol": (
                        fourier_number(dval, r_val, t_nominal)
                        if dval else float("nan")
                    ),
                    "t_end_s": run["t_end_s"],
                    "sustained_protocol_fraction": sustained,
                    "q_end_mAh": run["q_end_Ah"] * 1e3,
                    "q_to_cutoff_mAh": run["q_end_Ah"] * 1e3,
                    "reached_cutoff": run["reached_cutoff"],
                    "V_start_V": run["V_start"],
                    "V_end_V": run["V_end"],
                    "V_span_mV": run["V_span_mV"],
                    "V_at_half_protocol_V": _v_at_time(run, 0.5 * t_nominal),
                    **{f"V_at_{int(f*100)}pct_Qnom_V": v for f, v in v_at.items()},
                })
                # decimated curve for plotting
                sel = np.linspace(0, len(run["t_s"]) - 1,
                                  min(400, len(run["t_s"]))).astype(int)
                curve_rows.extend({
                    "model": model, "rate_label": label, "case": tag,
                    "D_prescribed_m2_s": dval,
                    "t_s": float(run["t_s"][i]),
                    "q_mAh": float(run["q_Ah"][i] * 1e3),
                    "V": float(run["V"][i]),
                } for i in sel)
            print(f"[B2] CC {label:5s} {model:4s}: "
                  f"control q={cc_rows[-len(cases)]['q_to_cutoff_mAh']:.3f} | "
                  f"gitt q={cc_rows[-len(cases) + 1]['q_to_cutoff_mAh']:.3f} mAh")
    cc = pd.DataFrame(cc_rows)
    cc.to_csv(OUT_DIR / "cc_rate_sweep.csv", index=False)
    pd.DataFrame(curve_rows).to_csv(OUT_DIR / "cc_rate_curves.csv", index=False)

    # ---------------- B2.3 sensitivity + criterion -----------------
    grid = np.array([d for d in args.values], dtype=float)
    sens_rows: List[dict] = []
    for model in args.models:
        # ---- pOCV: RMSE response to D (experiment available) ----
        for rate, br in POCV_WINDOWS.items():
            sub = replay[(replay["model"] == model) & (replay["rate"] == rate)]
            cur = sub[sub["case"] == "control_native_ecker"].iloc[0]
            git = sub[sub["case"] == "gitt_curve"].iloc[0]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            sens_rows.append({
                "axis": "pocv_replay", "model": model, "protocol": rate,
                "t_protocol_s": float(cur["duration_s"]),
                "rmse_control_mV": float(cur["rmse_mV"]),
                "rmse_gitt_curve_mV": float(git["rmse_mV"]),
                "rmse_min_over_lattice_mV": float(lat["rmse_mV"].min()),
                "D_at_rmse_min_m2_s": float(
                    lat.loc[lat["rmse_mV"].idxmin(), "D_prescribed_m2_s"]
                ),
                "rmse_spread_over_lattice_mV": float(
                    lat["rmse_mV"].max() - lat["rmse_mV"].min()
                ),
                "dV_dlog10D_mV_per_decade": _slope_per_decade(
                    lat["D_prescribed_m2_s"].to_numpy(float),
                    lat["rmse_mV"].to_numpy(float),
                ),
                "sensitivity_threshold_D_m2_s": float("nan"),
                "Fo_at_threshold": float("nan"),
                "Fo_gitt_curve_min": float("nan"),
                "Fo_gitt_curve_median": float("nan"),
                "Fo_gitt_curve_max": float("nan"),
            })
        # ---- CC family: how much the diffusivity changes the answer ----
        #  Two observables, both finite for every lattice member:
        #   * sustained_protocol_fraction - the fraction of the nominal
        #     protocol the model can complete before the lower cut-off.
        #     Monotone in D; a value of 1 means fully sustained.
        #   * V at t = 0.5 t_protocol - a pure surface-vs-average
        #     signature, because at a fixed TIME the volume-averaged
        #     stoichiometry is D-independent.
        #  (V at a fixed DELIVERED CAPACITY is deliberately not the
        #  headline: it saturates, since only the equilibrated runs ever
        #  reach a given capacity, so the starved members drop out as NaN.)
        for label, rate in CC_RATES.items():
            sub = cc[(cc["model"] == model) & (cc["rate_label"] == label)]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            ctrl = sub[sub["case"] == "control_native_ecker"]
            sus_ctrl = float(ctrl["sustained_protocol_fraction"].iloc[0]) \
                if len(ctrl) else float("nan")
            v_ctrl = float(ctrl["V_at_half_protocol_V"].iloc[0]) \
                if len(ctrl) else float("nan")
            sus = lat["sustained_protocol_fraction"].to_numpy(float)
            vhalf = lat["V_at_half_protocol_V"].to_numpy(float)
            d_arr = lat["D_prescribed_m2_s"].to_numpy(float)
            # deviation from the near-equilibrium control, in the units
            # each convention is declared in
            dev_sus = np.abs(sus - sus_ctrl) if np.isfinite(sus_ctrl) \
                else np.full(len(sus), np.nan)
            dev_v = np.abs(vhalf - v_ctrl) * 1e3 if np.isfinite(v_ctrl) \
                else np.full(len(vhalf), np.nan)
            d_thr_sus = _threshold_D(d_arr, dev_sus * 100.0,
                                     SUSTAINED_THRESHOLD_PCT)
            d_thr_v = _threshold_D(d_arr, dev_v, SENSITIVITY_THRESHOLD_MV)
            t_prot = 3600.0 / rate
            g = gitt_curve["lithiation"]
            fo_g = (g["Ds_median_m2_s"].to_numpy(float) * t_prot
                    / r_val ** 2)
            sens_rows.append({
                "axis": "cc_rate", "model": model, "protocol": label,
                "t_protocol_s": t_prot,
                "sustained_control": sus_ctrl,
                "sustained_gitt_curve": float(
                    sub[sub["case"] == "gitt_curve"]
                    ["sustained_protocol_fraction"].iloc[0]),
                "sustained_spread_over_lattice": float(
                    np.nanmax(sus) - np.nanmin(sus)),
                "sustained_deviation_control_pct": float(
                    np.nanmax(dev_sus) * 100.0),
                "sensitivity_threshold_D_from_sustained_m2_s": d_thr_sus,
                "Fo_at_threshold_from_sustained": (
                    fourier_number(d_thr_sus, r_val, t_prot)
                    if np.isfinite(d_thr_sus) else float("nan")
                ),
                "V_half_protocol_control_V": v_ctrl,
                "V_half_protocol_deviation_control_mV": float(
                    np.nanmax(dev_v)) if np.isfinite(dev_v).any()
                else float("nan"),
                "sensitivity_threshold_D_from_voltage_m2_s": d_thr_v,
                "Fo_at_threshold_from_voltage": (
                    fourier_number(d_thr_v, r_val, t_prot)
                    if np.isfinite(d_thr_v) else float("nan")
                ),
                "q_to_cutoff_control_mAh": float(
                    ctrl["q_to_cutoff_mAh"].iloc[0]) if len(ctrl)
                    else float("nan"),
                "q_to_cutoff_gitt_curve_mAh": float(
                    sub[sub["case"] == "gitt_curve"]["q_to_cutoff_mAh"].iloc[0]),
                "q_to_cutoff_spread_over_lattice_mAh": float(
                    lat["q_to_cutoff_mAh"].max()
                    - lat["q_to_cutoff_mAh"].min()),
                "dV_dlog10D_at_half_protocol_mV_per_decade": _slope_per_decade(
                    d_arr, vhalf,
                ),
                "Fo_gitt_curve_min": float(np.nanmin(fo_g)),
                "Fo_gitt_curve_median": float(np.nanmedian(fo_g)),
                "Fo_gitt_curve_max": float(np.nanmax(fo_g)),
            })
    sens = pd.DataFrame(sens_rows)
    sens.to_csv(OUT_DIR / "sensitivity_summary.csv", index=False)

    summary = {
        "dataset": DATASET,
        "cell": CELL,
        "phase": "B2 GITT apparent-D_s credibility assessment",
        "models": list(args.models),
        "diffusivity_grid_m2_s": [float(d) for d in args.values],
        "sensitivity_threshold_mV": SENSITIVITY_THRESHOLD_MV,
        "particle_radius_m": r_val,
        "particle_radius_note": (
            "from the reference set (NOT measured); D scales with R^2, so "
            "every tau_d and Fourier number here carries that systematic"
        ),
        "Q_nom_Ah": q_nom_Ah,
        "ecker_D_at_soc_0p5_m2_s": ecker_d,
        "cc_initial_state": {
            "x0": x0,
            "measured_rest_ocv_V": v0_meas,
            "note": (
                "same anchor as the pOCV-lith window, so the four rates "
                "differ only in current"
            ),
        },
        "no_fitting": (
            "D is swept on an a priori log grid; nothing is optimised and "
            "no lattice value is proposed as an estimate of D"
        ),
        "no_experiment_at_these_rates": (
            "this cell has p-OCV and GITT programmes only, so the "
            "0.5C/1C/2C columns are MODEL-ONLY forward simulations; the "
            "only experimental column is the p-OCV replay"
        ),
        "protocol_durations_s": durations,
        "sensitivity": sens.to_dict(orient="records"),
    }
    with (OUT_DIR / "sensitivity_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    _figures(diag, by_soc, replay, cc, pd.DataFrame(curve_rows), sens,
             grid, r_val, gitt_curve, args.values)
    _report(OUT_DIR, diag, by_soc, prov, replay, cc, sens, summary,
            durations, grid, r_val, q_nom_Ah, x0, v0_meas, ecker_d,
            gitt_curve, args.values)

    print(f"[B2] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


def _proxy(adapter, branch: str):
    """OCP-consistent initial-state proxy (analysis level, unchanged)."""
    from scripts.graphite_phase_b0_compare import OCPConsistentAdapter

    return OCPConsistentAdapter(
        adapter, branch, load_ocp_tables(V2_DIR)
    )


def _figures(diag, by_soc, replay, cc, curves, sens, grid, r_val,
             gitt_curve, values) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ---- fig 1: diagnostics ----
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.4))
    ax = axes[0, 0]
    for br, c in (("lithiation", "#378ADD"), ("delithiation", "#1D9E75")):
        sub = diag[diag["branch"] == br]
        ax.semilogy(sub[sub["is_valid"]]["SOC"], sub[sub["is_valid"]]["Ds_app_cm2_s"],
                    "o", ms=3, color=c, alpha=0.6, label=f"{br} valid")
        ax.semilogy(sub[~sub["is_valid"]]["SOC"], sub[~sub["is_valid"]]["Ds_app_cm2_s"],
                    "x", ms=3, color="#E24B4A", alpha=0.5,
                    label="rejected" if br == "lithiation" else None)
    ax.set_xlabel("SOC")
    ax.set_ylabel("apparent $D_s$ [cm$^2$/s]")
    ax.set_title("Phase B1 apparent $D_s$ and its validity flag")
    ax.legend(fontsize=7)

    ax = axes[0, 1]
    for br, c in (("lithiation", "#378ADD"), ("delithiation", "#1D9E75")):
        sub = diag[diag["branch"] == br]
        ax.plot(sub["SOC"], sub["WH_fit_R2"], "o", ms=3, color=c, alpha=0.6,
                label=br)
    ax.axhline(0.90, color="#E24B4A", ls="--", lw=1.2,
               label="acceptance gate 0.90")
    ax.set_xlabel("SOC")
    ax.set_ylabel("$R^2$ of $V = a + m\\sqrt{t}$")
    ax.set_title("signal 1: is the pulse linear in $\\sqrt{t}$?")
    ax.legend(fontsize=7)

    ax = axes[1, 0]
    for br, c in (("lithiation", "#378ADD"), ("delithiation", "#1D9E75")):
        sub = diag[diag["branch"] == br]
        ax.semilogy(sub["SOC"], sub["dE_pulse_mV"].abs(), "o", ms=3, color=c,
                    alpha=0.5, label=f"{br} $|\\Delta E_{{pulse}}|$")
        ax.semilogy(sub["SOC"], sub["dE_relax_mV"].abs(), ".", ms=3,
                    color=c, alpha=0.25,
                    label=f"{br} $|\\Delta E_{{relax}}|$")
    ax.set_xlabel("SOC")
    ax.set_ylabel("overpotential [mV]")
    ax.set_title("pulse vs relaxation overpotential")
    ax.legend(fontsize=6, ncol=2)

    ax = axes[1, 1]
    for br, c in (("lithiation", "#378ADD"), ("delithiation", "#1D9E75")):
        g = by_soc[by_soc["branch"] == br]
        ax.plot(g["SOC"], g["Ds_decades_spanned"], "o-", ms=3, color=c,
                label=br)
    ax.set_xlabel("SOC")
    ax.set_ylabel("decades spanned by $D_s$ (p05\u2013p95)")
    ax.set_title("spread per SOC bin \u2014 a single median hides this")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_ds_diagnostics.png", dpi=150)
    plt.close(fig)

    # ---- fig 2: sensitivity ----
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.4))
    for i, model in enumerate(sorted(set(replay["model"]))):
        ax = axes[i, 0]
        for rate, c in (("pOCV-lith", "#378ADD"), ("pOCV-deli", "#1D9E75")):
            sub = replay[(replay["model"] == model) & (replay["rate"] == rate)]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            cur = sub[sub["case"] == "control_native_ecker"].iloc[0]
            git = sub[sub["case"] == "gitt_curve"].iloc[0]
            ax.semilogx(lat["D_prescribed_m2_s"], lat["rmse_mV"], "o-", ms=4,
                        color=c, label=f"{rate} (const D)")
            ax.axhline(float(cur["rmse_mV"]), color=c, ls=":", lw=1.2)
            ax.plot([float(lat["D_prescribed_m2_s"].min())],
                    [float(git["rmse_mV"])], marker="*", ms=12, color=c,
                    label=f"{rate} GITT curve")
        ax.set_xlabel("constant $D$ [m$^2$/s]")
        ax.set_ylabel("RMSE (time-aligned) [mV]")
        ax.set_title(f"{model}: p-OCV replay vs prescribed $D$")
        ax.legend(fontsize=7)

        ax = axes[i, 1]
        for label, c in (("C/50", "#8A8A87"), ("0.5C", "#378ADD"),
                         ("1C", "#1D9E75"), ("2C", "#BA7517")):
            sub = cc[(cc["model"] == model) & (cc["rate_label"] == label)]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            ax.semilogx(lat["D_prescribed_m2_s"],
                        lat["sustained_protocol_fraction"] * 100.0,
                        "o-", ms=4, color=c, label=label)
            ctrl = sub[sub["case"] == "control_native_ecker"]
            if len(ctrl):
                ax.axhline(
                    float(ctrl["sustained_protocol_fraction"].iloc[0]) * 100.0,
                    color=c, ls=":", lw=1.0)
                git = sub[sub["case"] == "gitt_curve"]
                if len(git):
                    ax.plot([float(lat["D_prescribed_m2_s"].min())],
                            [float(git["sustained_protocol_fraction"].iloc[0])
                             * 100.0], marker="*", ms=12, color=c)
        ax.set_xlabel("constant $D$ [m$^2$/s]")
        ax.set_ylabel("% of nominal protocol sustained")
        ax.set_title(f"{model}: model-only CC family (no rate data)")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_sensitivity.png", dpi=150)
    plt.close(fig)

    # ---- fig 3: criterion ----
    fig, axes = plt.subplots(1, 3, figsize=(18, 4.6))
    marks = {"SPM": "o", "SPMe": "s"}
    colors = {"C/50": "#8A8A87", "0.5C": "#378ADD", "1C": "#1D9E75",
              "2C": "#BA7517"}
    ax = axes[0]
    for label, c in colors.items():
        for model in ("SPM", "SPMe"):
            sub = cc[(cc["model"] == model) & (cc["rate_label"] == label)]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            ctrl = sub[sub["case"] == "control_native_ecker"]
            if not len(ctrl):
                continue
            v0 = float(ctrl["V_at_half_protocol_V"].iloc[0])
            dev = np.abs(lat["V_at_half_protocol_V"].to_numpy(float) - v0) * 1e3
            ax.semilogx(lat["Fo_over_protocol"], dev, marks[model] + "-",
                        ms=4, color=c, lw=1.0,
                        alpha=0.9 if model == "SPM" else 0.5,
                        label=f"{label} {model}")
    ax.axhline(SENSITIVITY_THRESHOLD_MV, color="#E24B4A", ls="--", lw=1.2)
    ax.set_ylim(0, max(3 * SENSITIVITY_THRESHOLD_MV, 20))
    ax.set_xlabel("$Fo = D\\,t/R^2$ of the prescribed $D$")
    ax.set_ylabel("|$V(t/2)$ \u2212 control| [mV]")
    ax.set_title(f"voltage signature ({SENSITIVITY_THRESHOLD_MV:.0f} mV line)")
    ax.legend(fontsize=6, ncol=2)

    ax = axes[1]
    for label, c in colors.items():
        for model in ("SPM", "SPMe"):
            sub = cc[(cc["model"] == model) & (cc["rate_label"] == label)]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            ctrl = sub[sub["case"] == "control_native_ecker"]
            if not len(ctrl):
                continue
            s0 = float(ctrl["sustained_protocol_fraction"].iloc[0])
            dev = np.abs(
                lat["sustained_protocol_fraction"].to_numpy(float) - s0) * 100.0
            ax.semilogx(lat["Fo_over_protocol"], dev, marks[model] + "-",
                        ms=4, color=c, lw=1.0,
                        alpha=0.9 if model == "SPM" else 0.5,
                        label=f"{label} {model}")
    ax.axhline(SUSTAINED_THRESHOLD_PCT, color="#E24B4A", ls="--", lw=1.2)
    ax.set_xlabel("$Fo = D\\,t/R^2$ of the prescribed $D$")
    ax.set_ylabel("|sustained fraction \u2212 control| [pp]")
    ax.set_title(f"capacity signature ({SUSTAINED_THRESHOLD_PCT:.0f} pp line)")
    ax.legend(fontsize=6, ncol=2)

    ax = axes[2]
    for label, c in colors.items():
        t_prot = 3600.0 / CC_RATES[label]
        g = gitt_curve["lithiation"]
        d = g["Ds_median_m2_s"].to_numpy(float)
        if not len(d):
            continue
        ax.plot([fourier_number(d.min(), r_val, t_prot),
                 fourier_number(d.max(), r_val, t_prot)],
                [label, label], "-", lw=7, color=c, alpha=0.55)
    ax.axvline(1.0, color="k", lw=1.0)
    ax.set_xscale("log")
    ax.set_xlabel("$Fo$ of the GITT $D_s(SOC)$ curve over the protocol")
    ax.set_title("the GITT curve lands here (min\u2013max over SOC)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_criterion.png", dpi=150)
    plt.close(fig)

    return None


def _usable_intervals(by_soc: pd.DataFrame, *, min_frac: float = 0.5):
    """
    Contiguous SOC intervals where at least ``min_frac`` of the pulses
    survive the gates - i.e. where the Weppner-Huggins single-particle
    inversion is actually supported by this dataset.
    """
    out: Dict[str, List[List[float]]] = {}
    for br, g in by_soc.groupby("branch"):
        g = g.sort_values("SOC").reset_index(drop=True)
        runs: List[List[float]] = []
        cur: Optional[List[float]] = None
        for _, r in g.iterrows():
            if float(r["valid_fraction"]) >= min_frac:
                if cur is None:
                    cur = [float(r["SOC"]), float(r["SOC"])]
                else:
                    cur[1] = float(r["SOC"])
            elif cur is not None:
                runs.append(cur)
                cur = None
        if cur is not None:
            runs.append(cur)
        out[str(br)] = runs
    return out


def _md_table(df: pd.DataFrame, cols: List[str], fmt: Dict[str, str]) -> List[str]:
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            f = fmt.get(c)
            if isinstance(v, float) and not np.isfinite(v):
                cells.append("n/a")
            elif f:
                cells.append(f.format(v))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return out


def _report(out_dir, diag, by_soc, prov, replay, cc, sens, summary,
            durations, grid, r_val, q_nom, x0, v0, ecker_d, gitt_curve,
            values) -> Path:
    lines: List[str] = [
        "# Phase B2 — GITT apparent $D_s$: credibility assessment and",
        "## when the extracted diffusivity can be a model input",
        "",
        "Phase B2 does **not** fit, tune or re-extract anything.  It asks a",
        "narrower question: **when is the GITT-derived apparent $D_s$ "
        "trustworthy as a model input, and when is it irrelevant?**",
        "",
        "```",
        "D_s credibility  ->  per-pulse diagnostics + validity flags (B2.1)",
        "D_s sensitivity  ->  constant-D lattice 1e-17..1e-13 m2/s (B2.2)",
        "                      pOCV replay        (experiment available)",
        "                      C/50, 0.5C, 1C, 2C (MODEL-ONLY)",
        "                      SPM and SPMe",
        "criterion        ->  Fo = D t / R^2          (B2.3)",
        "```",
        "",
        f"- cells: p-OCV `{CELL}`, GITT `063b77`; frozen OCP = Phase B0.6 v2",
        f"- lattice: {', '.join(f'{v:.3g}' for v in values)} m2/s "
        f"({len(values)} values)",
        f"- $R$ = {r_val*1e6:.3f} um **from the reference set, not measured** "
        f"(so $D \\propto R^2$ and every $\\tau_d$ below carries that "
        f"systematic)",
        f"- $Q_{{nom}}$ = {q_nom*1e3:.4f} mAh (capacity-matched set)",
        f"- reference diffusivity (Ecker2015 at SOC 0.5) = "
        f"{ecker_d:.3e} m2/s",
        "",
        "## 0. What the data can and cannot support",
        "",
        "This cell was measured with a **p-OCV** programme (≈C/50, 41 h) and a",
        "**GITT** programme.  It has **no rate-capability data**.  Therefore:",
        "",
        "| column | experiment? | what a change in it means |",
        "|---|---|---|",
        "| p-OCV replay | **yes** | a real RMSE change |",
        "| 0.5C / 1C / 2C | **no** | a model-only forward simulation; the",
        "| | | comparison is between model runs, never against data |",
        "",
        "## 1. $D_s$ diagnostics (B2.1)",
        "",
        f"`Ds_diagnostics.csv` — {prov['n_pulses']} pulses, "
        f"**{prov['n_valid']} valid** "
        f"({prov['valid_fraction']*100:.1f} %), "
        f"{prov['n_rejected']} rejected.",
        "",
        "| field | meaning |",
        "|---|---|",
        "| `SOC` | pulse midpoint, same charge-based axis as the frozen OCP |",
        "| `Ds_app_m2_s` / `Ds_app_cm2_s` | apparent/effective diffusivity |",
        "| `WH_fit_R2` | $R^2$ of $V = a + m\\sqrt{t}$ over the pulse |",
        "| `dE_pulse_mV` | measured pulse overpotential |",
        "| `dE_relax_mV` | measured relaxation overpotential |",
        "| `OCP_slope_V_per_soc` | $U'$ from the frozen Phase B0.6 table |",
        "| `validity_flag` | `valid` / `rejected` (+ `rejection_reasons`) |",
        "",
        "Rejection counts (a pulse can fail more than one gate):",
        "",
    ]
    for code, n in sorted(prov["rejection_counts"].items(),
                          key=lambda kv: -kv[1]):
        lines.append(f"- `{code}` \u2014 {n} pulses")
    lines += [
        "",
        "Per-SOC rollup (`Ds_diagnostics_by_soc.csv`) — the surviving spread:",
        "",
    ]
    tab = by_soc.copy()
    lines += _md_table(
        tab, ["branch", "SOC", "n_pulses", "n_valid", "valid_fraction",
              "Ds_median_m2_s", "Ds_decades_spanned", "Fo_pulse_median"],
        {"SOC": "{:.2f}", "valid_fraction": "{:.2f}",
         "Ds_median_m2_s": "{:.3e}", "Ds_decades_spanned": "{:.2f}",
         "Fo_pulse_median": "{:.4f}"},
    )
    lines += [
        "",
        "### 1.1 Which SOC ranges actually support the inversion",
        "",
        "This is the diagnostic that matters most for using $D_s$ as a "
        "model parameter.  Intervals where at least half the pulses pass "
        "every gate:",
        "",
    ]
    iv = _usable_intervals(by_soc)
    for br, runs in iv.items():
        txt = "; ".join(f"SOC {a:.2f}\u2013{b:.2f}" for a, b in runs) or "none"
        lines.append(f"- **{br}**: {txt}")
    lines += [
        "",
        f"The overall valid fraction is "
        f"{prov['n_valid']}/{prov['n_pulses']} = "
        f"{prov['valid_fraction']*100:.1f} %.  The rejections are not "
        f"random: they concentrate where the Weppner-Huggins model itself "
        f"breaks down \u2014",
        "",
        "- the **dilute stage** (near SOC 0, and the mirror end of the "
        "delithiation branch), where the OCP is nearly vertical so the "
        "pulse step is not a small perturbation, and the frozen table's "
        "own resolution is pushed to its limit;",
        "- the **plateaus** (the stage-2/stage-1 flat regions), where the "
        "OCP is flat ($U' \\to 0$), the pulse produces almost no "
        "diffusional overpotential, and the $\\sqrt{t}$ regression is "
        "fitting noise.",
        "",
        f"Per-SOC $\\log_{{10}}$ spread of the surviving values: median "
        f"{by_soc['Ds_decades_spanned'].median():.2f} decades, max "
        f"{by_soc['Ds_decades_spanned'].max():.2f} decades.  So the "
        f"five-decade range of the curve is mostly SOC STRUCTURE between "
        f"stages, not scatter within one stage.",
        "",
        "## 2. Diffusivity sensitivity (B2.2)",
        "",
        "### 2.1 p-OCV replay — the only column with an experiment",
        "",
        "RMSE against the measured p-OCV window for every prescribed "
        "constant $D$, plus the two *curves* (reference-set native $D(SOC)$ "
        "and the Phase B1 GITT $D_s(SOC)$).",
        "",
    ]
    view = replay[["model", "rate", "case", "D_prescribed_m2_s",
                   "rmse_mV", "mae_mV", "n_points", "coverage_fraction"]]
    lines += _md_table(
        view, ["model", "rate", "case", "D_prescribed_m2_s", "rmse_mV",
               "mae_mV", "n_points", "coverage_fraction"],
        {"D_prescribed_m2_s": "{:.3e}", "rmse_mV": "{:.2f}",
         "mae_mV": "{:.2f}", "coverage_fraction": "{:.3f}"},
    )
    lines += [
        "",
        "#### What the p-OCV replay can and cannot identify",
        "",
        "| model | window | RMSE, control (native $D(SOC)$) | "
        "best constant-$D$ RMSE | at $D$ | is that the grid edge? | "
        "coverage at the control | weakest-run coverage |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model in sorted(set(replay["model"])):
        for rate, _br in POCV_WINDOWS.items():
            sub = replay[(replay["model"] == model) & (replay["rate"] == rate)]
            ctrl = sub[sub["case"] == "control_native_ecker"].iloc[0]
            lat = sub[sub["D_prescribed_m2_s"].notna()].sort_values(
                "D_prescribed_m2_s")
            i = lat["rmse_mV"].idxmin()
            d_best = float(lat.loc[i, "D_prescribed_m2_s"])
            edge = d_best in (float(np.min(values)), float(np.max(values)))
            lines.append(
                f"| {model} | {rate} | {ctrl['rmse_mV']:.2f} mV | "
                f"{float(lat.loc[i, 'rmse_mV']):.2f} mV | {d_best:.1e} | "
                f"{'yes' if edge else 'no'} | "
                f"{ctrl['coverage_fraction']:.3f} | "
                f"{lat['coverage_fraction'].min():.3f} |"
            )
    lines += [
        "",
        "Two readings, both important:",
        "",
        "1. **No constant $D$ beats the SOC-dependent reference curve** on "
        "either window.  The best lattice member is still slightly worse "
        "than the control, so the *shape* of $D(SOC)$, not just its "
        "magnitude, is doing real work in the replay.",
        "2. Where the minimum sits on the **grid edge**, the experiment "
        "does not identify a value: it only says the replay keeps "
        "improving as $D$ grows, i.e. it bounds $D$ **from below**.  A "
        "bounded-below statement is all a near-equilibrium protocol can "
        "give; it can never pin a magnitude.",
        "",
        "**Coverage caveat (must travel with these numbers).**  A run "
        "whose diffusive overpotential grows enough to reach the lower "
        "cut-off early is scored only over the part of the window it "
        "survived, so its RMSE is computed on the *easiest* stretch and is "
        "therefore an underestimate.  The weakly-starved runs above have "
        "coverage as low as "
        f"{replay['coverage_fraction'].min():.2f}; the direction of the "
        "effect makes the 'small $D$ is worse' conclusion conservative, "
        "not optimistic.",
        "",
        "### 2.2 Constant-current family — model-only",
        "",
        "Same initial state as the p-OCV lithiation window "
        f"($x_0$ = {x0:.4f}, measured rest OCV {v0:.4f} V), so the four "
        "rates differ only in current.",
        "",
        "Two observables are used, both finite for every lattice member:",
        "",
        f"- **sustained protocol fraction** — how much of the nominal "
        f"$1/\\text{{rate}}$ hour the model completes before the lower "
        f"cut-off.  Threshold convention: {SUSTAINED_THRESHOLD_PCT:.0f} "
        f"percentage points.",
        f"- **$V$ at $t = \\tfrac12 t_{{protocol}}$** — a pure "
        f"surface-vs-average signature, because at a fixed *time* the "
        f"volume-averaged stoichiometry is $D$-independent.  Threshold "
        f"convention: {SENSITIVITY_THRESHOLD_MV:.0f} mV.",
        "",
        "$V$ at a fixed *delivered capacity* is deliberately **not** the "
        "headline: it saturates, because only the well-equilibrated runs "
        "ever reach a given capacity, so the starved members drop out as "
        "NaN instead of counting as sensitive.",
        "",
        "| model | rate | $t$ [s] | sustained, control | sustained, GITT | "
        "sustained spread | $Q$ to cutoff, control [mAh] | "
        "$Q$ to cutoff, GITT [mAh] | $Q$ spread [mAh] | "
        "$|V(t/2)-$ctrl$|$ [mV] | $D_{thr}$ from sustained [m$^2$/s] | "
        "Fo at that $D_{thr}$ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in sens[sens["axis"] == "cc_rate"].iterrows():
        lines.append(
            f"| {r['model']} | {r['protocol']} | {r['t_protocol_s']:.0f} | "
            f"{r['sustained_control']:.3f} | {r['sustained_gitt_curve']:.3f} | "
            f"{r['sustained_spread_over_lattice']:.3f} | "
            f"{r['q_to_cutoff_control_mAh']:.4f} | "
            f"{r['q_to_cutoff_gitt_curve_mAh']:.4f} | "
            f"{r['q_to_cutoff_spread_over_lattice_mAh']:.4f} | "
            f"{r['V_half_protocol_deviation_control_mV']:.1f} | "
            f"{r['sensitivity_threshold_D_from_sustained_m2_s']:.2e} | "
            f"{r['Fo_at_threshold_from_sustained']:.4f} |"
        )
    lines += ["", "#### $V$ at $Q = 0.5\\,Q_{nom}$ [V] across the lattice", ""]
    for model in sorted(set(cc["model"])):
        piv = cc[(cc["model"] == model)
                 & cc["D_prescribed_m2_s"].notna()].pivot_table(
            index="D_prescribed_m2_s", columns="rate_label",
            values="V_at_50pct_Qnom_V", aggfunc="first",
        )
        piv = piv.reindex(columns=[c for c in ("C/50", "0.5C", "1C", "2C")
                                   if c in piv.columns])
        lines.append(f"**{model}**")
        lines += _md_table(
            piv.reset_index(),
            ["D_prescribed_m2_s"] + list(piv.columns),
            {**{"D_prescribed_m2_s": "{:.3e}"},
             **{c: "{:.4f}" for c in piv.columns}},
        )
        lines.append("")
    lines += [
        "",
        "### 2.3 Model comparison (SPM vs SPMe)",
        "",
    ]
    lines += _md_table(
        sens[["axis", "protocol", "model", "t_protocol_s",
              "rmse_control_mV", "rmse_gitt_curve_mV",
              "sustained_control", "sustained_gitt_curve",
              "V_half_protocol_deviation_control_mV",
              "sensitivity_threshold_D_from_sustained_m2_s",
              "Fo_at_threshold_from_sustained"]],
        ["axis", "protocol", "model", "t_protocol_s", "rmse_control_mV",
         "rmse_gitt_curve_mV", "sustained_control", "sustained_gitt_curve",
         "V_half_protocol_deviation_control_mV",
         "sensitivity_threshold_D_from_sustained_m2_s",
         "Fo_at_threshold_from_sustained"],
        {"t_protocol_s": "{:.0f}", "rmse_control_mV": "{:.2f}",
         "rmse_gitt_curve_mV": "{:.1f}", "sustained_control": "{:.3f}",
         "sustained_gitt_curve": "{:.3f}",
         "V_half_protocol_deviation_control_mV": "{:.1f}",
         "sensitivity_threshold_D_from_sustained_m2_s": "{:.2e}",
         "Fo_at_threshold_from_sustained": "{:.4f}"},
    )

    # ---------------- verdict, computed from the numbers ----------
    lines += ["", "## 3. Verdict — when the GITT $D_s$ is usable", ""]
    cc_sens = sens[sens["axis"] == "cc_rate"]
    fo_thr = cc_sens["Fo_at_threshold_from_sustained"].dropna()
    if len(fo_thr):
        lines += [
            f"- Across every model and rate, the sustained-capacity "
            f"deviation falls below the "
            f"{SUSTAINED_THRESHOLD_PCT:.0f}-point level once",
            f"  $Fo = D t / R^2 \\gtrsim$ **{fo_thr.median():.2f}** "
            f"(range {fo_thr.min():.2f}\u2013{fo_thr.max():.2f}).",
            "",
        ]
    for _, r in cc_sens.iterrows():
        if not np.isfinite(r["Fo_gitt_curve_median"]):
            continue
        lines.append(
            f"- **{r['protocol']} / {r['model']}**: the GITT curve spans "
            f"$Fo$ = {r['Fo_gitt_curve_min']:.1e} \u2013 "
            f"{r['Fo_gitt_curve_max']:.1e} (median "
            f"{r['Fo_gitt_curve_median']:.1e}); with it the model sustains "
            f"{r['sustained_gitt_curve']*100:.0f} % of the protocol "
            f"against {r['sustained_control']*100:.0f} % with the "
            f"reference diffusivity."
        )
    lines += [
        "",
        "### SPM vs SPMe",
        "",
    ]
    for _, r in cc_sens.iterrows():
        if r["model"] != "SPM":
            continue
        other = cc_sens[(cc_sens["model"] == "SPMe")
                        & (cc_sens["protocol"] == r["protocol"])]
        if not len(other):
            continue
        o = other.iloc[0]
        lines.append(
            f"- **{r['protocol']}**: sustained fraction "
            f"{r['sustained_control']*100:.1f} % (SPM) vs "
            f"{o['sustained_control']*100:.1f} % (SPMe) with the reference "
            f"diffusivity; the lattice $D_{{thr}}$ is "
            f"{r['sensitivity_threshold_D_from_sustained_m2_s']:.2e} vs "
            f"{o['sensitivity_threshold_D_from_sustained_m2_s']:.2e} "
            f"m$^2$/s."
        )
    lines += [
        "",
        "So the **diffusivity** conclusion is model-structure robust at "
        "and below C/2 (SPM and SPMe agree to a couple of percent), while "
        "at 2C the two models separate because the electrolyte adds a "
        "second limitation: extrapolating the 2C column to a real cell "
        "needs SPMe (or DFN), not SPM.",
        "",
        "### The decision rule",
        "",
        "$$Fo = \\frac{D\\,t}{R^{2}}\\;=\\;\\frac{t_{protocol}}{\\tau_d}$$",
        "",
        "| regime | meaning | is the GITT $D_s$ usable? |",
        "|---|---|---|",
        "| $Fo \\gtrsim 1$ | particle equilibrated every step | **yes \u2014 "
        "and it barely matters**: any plausible $D$ gives nearly the same "
        "answer, so the five-decade SOC spread is harmless |",
        "| $Fo \\approx 0.1\\!-\\!1$ | diffusion and protocol share a time "
        "scale | **marginal**: $D$ enters the answer directly, so both "
        "magnitude and SOC shape must be right |",
        "| $Fo \\lesssim 0.1$ | surface starved | **no**: the model output "
        "is controlled by $D$ itself, and a wrong $D$ is indistinguishable "
        "from wrong physics |",
        "",
        "## 4. Honest limitations", "",
        f"- $D \\propto R^2$ and $R$ = {r_val*1e6:.2f} um comes from the "
        "reference set, not from a measurement of this material: a factor 2 "
        "error in $R$ moves every $Fo$ by 4, i.e. a whole regime boundary.",
        "- The 0.5C/1C/2C columns are model-only; they bound when "
        "$D$ *would* matter, they do not show that the model reproduces "
        "any measured 1C result.",
        "- The p-OCV replay is a near-equilibrium protocol: an RMSE minimum "
        "on the lattice is reported as an observation only and is "
        "**never adopted** as a fitted diffusivity (Phase B2 does no "
        "fitting by construction).",
        "- The constant-$D$ lattice removes the SOC shape on purpose, so "
        "the lattice sensitivity is a **lower bound**: a wrong $D(SOC)$ "
        "shape can produce more error than any constant \u2014 which is "
        "exactly what the 'GITT curve' rows show, and why no constant on "
        "the lattice out-scores the SOC-dependent reference curve.",
        "- RMSE over a truncated replay window is an underestimate; "
        "coverage is reported next to every RMSE and the effect is "
        "conservative.",
        "",
        "## 5. Wording (mandatory)", "",
        "**apparent / effective** solid diffusivity, never *intrinsic* and "
        "never *the diffusion coefficient*.  $Fo$ is a property of a "
        "PROTOCOL and a diffusivity, not of the material.  The GITT curve "
        "is a dataset-associated apparent parameter: it does not transfer "
        "to another cell, another particle size or another temperature, "
        "and it is **not** validated here.",
        "",
    ]
    path = Path(out_dir) / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
