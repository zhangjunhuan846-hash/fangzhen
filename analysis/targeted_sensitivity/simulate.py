# ============================================================
# Phase A2 — simulation step (perturbed SPMe replay)
#
# Mirrors battery_sim/simulation/baseline.py:_run_one_replay EXACTLY
# (same model build, same parameter pipeline, same current
# Interpolant, same solve call), then applies the validated
# one-at-a-time parameter perturbation of
# battery_sim/simulation/sensitivity.py (read-only reuse).
#
# The platform is FROZEN: nothing in battery_sim/ is modified.
# Each solve is cached to .npz so table/plot steps never re-run
# PyBaMM.
#
#   S_p(t) = [V(t, p(1+delta)) - V(t, p(1-delta))] / (2*delta)
# with delta = 0.20, evaluated on the stored time-aligned grid.
# ============================================================

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pybamm  # noqa: E402

from battery_sim.models.pybamm_factory import (  # noqa: E402
    build_model,
    load_parameter_values,
)
from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.sensitivity import (  # noqa: E402
    load_parameter_specs,
    perturb_parameters,
)

from common import (  # noqa: E402
    DELTA,
    FACTORS,
    PARAMETERS,
    selected_runs,
)

OUT = ROOT / "outputs" / "analysis" / "targeted_sensitivity"
CACHE = OUT / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Exact mirror of baseline._run_one_replay plumbing
# ------------------------------------------------------------------
def _filter_and_downsample(t_exp, I_exp, V_exp):
    """Strictly increasing time + cap at 2000 points (reference)."""
    t_exp = np.asarray(t_exp, dtype=float)
    I_exp = np.asarray(I_exp, dtype=float)
    V_exp = np.asarray(V_exp, dtype=float)
    valid = np.concatenate(([True], np.diff(t_exp) > 0))
    t_exp = t_exp[valid]
    I_exp = I_exp[valid]
    V_exp = V_exp[valid]
    if len(t_exp) > 2000:
        idx = np.linspace(0, len(t_exp) - 1, 2000, dtype=int)
        idx = np.unique(idx)
        t_exp = t_exp[idx]
        I_exp = I_exp[idx]
        V_exp = V_exp[idx]
    return t_exp, I_exp, V_exp


def _solve_window(
    df: pd.DataFrame,
    model_name: str,
    parameter_set: str,
    spec: dict | None = None,
    factor: float = 1.0,
):
    """One open-loop replay with optional parameter perturbation.

    Returns raw solver output (t_exp grid, t_sim, V_sim_full) --
    alignment to the stored time-aligned grid happens in
    ``align_to_grid``.  The code below mirrors baseline.py
    verbatim up to the parameter perturbation and the fact that
    metric/scalar computation is skipped.
    """
    t_exp = df["time_s"].to_numpy(dtype=float)
    I_exp = df["current_A"].to_numpy(dtype=float)
    V_exp = df["voltage_V"].to_numpy(dtype=float)
    t_exp, I_exp, V_exp = _filter_and_downsample(t_exp, I_exp, V_exp)

    model = build_model(model_name)
    params = load_parameter_values(parameter_set)

    # validated OAT perturbation (read-only reuse of the screen)
    if spec is not None:
        for key in spec["keys"]:
            if key not in params:
                raise KeyError(
                    f"parameter key '{key}' not in set '{parameter_set}'"
                )
        perturb_parameters(params, spec, factor)

    initial_soc = float(df.attrs.get("initial_soc", 1.0))

    ambient_C = float(
        df["temperature_ambient_C"].dropna().median()
        if "temperature_ambient_C" in df.columns
        else df.get("cell_temperature_C", pd.Series([25.0])).dropna().median()
    )
    ambient_K = ambient_C + 273.15
    if "Ambient temperature [K]" in params:
        params["Ambient temperature [K]"] = ambient_K
    if "Initial temperature [K]" in params:
        params["Initial temperature [K]"] = ambient_K

    current_function = pybamm.Interpolant(t_exp, I_exp, pybamm.t)
    params["Current function [A]"] = current_function

    simulation = pybamm.Simulation(model, parameter_values=params)
    tic = time.perf_counter()
    solution = simulation.solve(t_eval=t_exp, initial_soc=initial_soc)
    runtime_s = time.perf_counter() - tic

    t_sim = np.asarray(solution.t, dtype=float)
    try:
        V_full = np.asarray(
            solution["Terminal voltage [V]"].entries, dtype=float
        )
    except KeyError:
        V_full = np.asarray(solution["Voltage [V]"].entries, dtype=float)

    return {
        "t_exp": t_exp,
        "t_sim": t_sim,
        "V_full": V_full,
        "runtime_s": runtime_s,
    }


def align_to_grid(t_grid, t_sim, V_full):
    """V interpolated onto t_grid; NaN beyond the solver end."""
    t_grid = np.asarray(t_grid, dtype=float)
    vg = np.full(t_grid.shape, np.nan, dtype=float)
    ok = t_grid <= float(t_sim[-1]) + 1e-9
    if np.any(ok):
        vg[ok] = np.interp(t_grid[ok], t_sim, V_full)
    return vg


# ------------------------------------------------------------------
# Case-level cache
# ------------------------------------------------------------------
def case_path(run, param, factor):
    slug = run["rate_slug"].replace("/", "_")
    pname = param if param is not None else "BASE"
    fname = f"{run['dataset']}__{run['cell']}__{slug}__{pname}__{factor}.npz"
    return CACHE / fname


def solve_case(run, spec, param, factor, force=False):
    """Solve one (run, param, factor), write npz cache, return dict."""
    path = case_path(run, param, factor)
    if path.exists() and not force:
        d = np.load(path, allow_pickle=True)
        return {
            "t_grid": d["t_grid"], "v_grid": d["v_grid"],
            "t_sim": d["t_sim"], "v_full": d["v_full"],
            "end_sim_s": float(d["end_sim_s"]),
            "runtime_s": float(d["runtime_s"]),
        }

    ad = get_dataset(run["dataset"])
    df = ad.load_processed_discharge(run["cell"], run["window"])
    model_name = "SPMe"
    parameter_set = ad.config.parameter_set

    tic = time.perf_counter()
    sol = _solve_window(df, model_name, parameter_set, spec, factor)
    solve_s = time.perf_counter() - tic

    ta = pd.read_csv(run["time_aligned"])
    t_grid = ta["time_s"].to_numpy(dtype=float)
    v_grid = align_to_grid(t_grid, sol["t_sim"], sol["V_full"])

    np.savez(
        path,
        t_grid=t_grid,
        v_grid=v_grid,
        t_sim=sol["t_sim"],
        v_full=sol["V_full"],
        end_sim_s=float(sol["t_sim"][-1]),
        runtime_s=solve_s,
    )
    return {
        "t_grid": t_grid, "v_grid": v_grid,
        "t_sim": sol["t_sim"], "v_full": sol["V_full"],
        "end_sim_s": float(sol["t_sim"][-1]),
        "runtime_s": solve_s,
    }


# ------------------------------------------------------------------
# Baseline mirror validation (one extra solve per run)
# ------------------------------------------------------------------
def validate_baseline_mirror(run) -> dict:
    """Re-solve the unperturbed window and compare against the
    stored *_time_aligned.csv V_sim (must be ~machine-equal)."""
    path = case_path(run, None, 1.0)
    res = solve_case(run, None, None, 1.0, force=False)
    ta = pd.read_csv(run["time_aligned"])
    v_stored = ta["voltage_sim_V"].to_numpy(dtype=float)
    ok = np.isfinite(res["v_grid"])
    max_diff_mV = (
        float(np.max(np.abs(res["v_grid"][ok] - v_stored[ok]))) * 1000.0
        if ok.sum()
        else float("nan")
    )
    return {"max_abs_diff_mV": max_diff_mV, "n_ok": int(ok.sum())}


# ------------------------------------------------------------------
# Parameter availability probe (no solve)
# ------------------------------------------------------------------
def probe_parameters():
    rows = []
    for run in selected_runs():
        ad = get_dataset(run["dataset"])
        params = load_parameter_values(ad.config.parameter_set)
        specs = load_parameter_specs()
        for pid in PARAMETERS:
            missing = [k for k in specs[pid]["keys"] if k not in params]
            rows.append({
                "dataset": run["dataset"],
                "parameter_set": ad.config.parameter_set,
                "parameter": pid,
                "missing_keys": ";".join(missing),
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="only check parameter-key availability")
    ap.add_argument("--force", action="store_true",
                    help="re-solve even if cached")
    ap.add_argument("--param", default=None,
                    help="restrict to one parameter id")
    ap.add_argument("--run", default=None,
                    help="restrict to one run id (substring match)")
    args = ap.parse_args()

    if args.probe:
        print(probe_parameters().to_string(index=False))
        return 0

    specs = load_parameter_specs()
    params = PARAMETERS if args.param is None else [args.param]
    runs = selected_runs()
    if args.run:
        runs = [r for r in runs if args.run in r["run_id"]]
        print(f"run filter '{args.run}' -> {[r['run_id'] for r in runs]}")

    print(f"runs: {len(runs)} | params: {params} | delta={DELTA} "
          f"factors={FACTORS}")
    validation = {}
    total = 0
    t_all = time.perf_counter()
    for run in runs:
        rid = run["run_id"]
        # 1) baseline mirror check (cheap, cached)
        val = validate_baseline_mirror(run)
        validation[rid] = val
        print(f"[{rid}] baseline-mirror max|dV|={val['max_abs_diff_mV']:.3e} mV"
              f" (n={val['n_ok']})")
        # 2) perturbed cases
        for pid in params:
            spec = specs[pid]
            for factor in FACTORS:
                solve_case(run, spec, pid, factor, force=args.force)
                total += 1
    wall = time.perf_counter() - t_all

    (OUT / "simulation_validation.json").write_text(
        json.dumps({
            "baseline_mirror_max_abs_diff_mV": validation,
            "delta": DELTA,
            "n_solved_cases": total,
            "wall_time_s": wall,
            "note": (
                "baseline mirror diff ~0 proves the perturbed replay "
                "shares the exact solver/parameter pipeline of the "
                "frozen baseline outputs"
            ),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"solved {total} perturbed cases in {wall:.1f} s -> {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
