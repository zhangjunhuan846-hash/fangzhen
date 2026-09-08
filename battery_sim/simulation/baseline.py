# ============================================================
# Battery Dataset Simulation Platform v0.1
# Baseline runner (Step 9)
#
# Reuses the already-validated open-loop replay logic of:
#   scripts/run_baseline.py
#
# Pipeline (per measured single-rate discharge):
#   measured discharge I(t)  (processed CSV)
#        -> PyBaMM (SPM/SPMe/DFN, Chen2020 + chamber temperature)
#        -> Vsim(t)
#        -> time-aligned comparison with Vexp(t)
#
# Metric family (time aligned - deliberately distinct from the
# command-level reproduction V(Q) family):
#   rmse_time_aligned_mV
#   mae_time_aligned_mV
#   bias_time_aligned_mV
#   max_abs_error_mV
#   ...
#
# Reproduction mode keeps its own rmse_capacity_aligned_mV (alias
# of the validated rmse_Qaligned_mV).  The two conventions are
# never mixed in one output file.
#
# Outputs (outputs/platform/<dataset>/baseline/<MODEL>/cell<cell>/):
#   metrics.csv            one row per rate (time-aligned metrics)
#   run_metadata.json
#   {rate}_time_aligned.csv   per-rate time-domain comparison table
#   {rate}_Vt.png             per-rate V(t) comparison plot
# ============================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

import pybamm

from battery_sim.evaluation.plotting import save_time_voltage_plot
from battery_sim.models import parameter_sources
from battery_sim.models.pybamm_factory import (
    build_model,
    build_model_options,
    get_solver_config,
    load_parameter_values,
)
from battery_sim.paths import (
    ensure_dir,
    platform_output_dir,
)
from battery_sim.logging_utils import timestamp_utc


# ------------------------------------------------------------------
# Helpers (verbatim reuse of scripts/run_baseline.py semantics)
# ------------------------------------------------------------------
def integrate_capacity(t, current) -> float:
    """Trapezoidal capacity [Ah] from (t[s], I[A])."""
    try:
        return float(np.trapezoid(current, t) / 3600.0)
    except AttributeError:
        return float(np.trapz(current, t) / 3600.0)


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


# ------------------------------------------------------------------
# One (cell, rate): open-loop replay of the measured current trace
# ------------------------------------------------------------------
def _run_one_replay(
    df: pd.DataFrame,
    model_name: str,
    parameter_set: str,
    model_options: Optional[dict] = None,
) -> dict:
    """Time-aligned replay for one processed discharge CSV.

    Returns a dict with comparison arrays + scalar metrics using the
    ``*_time_aligned_mV`` metric family (see module docstring).

    v0.5 half-cell pilot (additive, default path unchanged):
      ``model_options`` (optional pybamm options, e.g. for a
      positive-working-electrode half cell) are passed to the model
      constructor.  An adapter-declared ``df.attrs['initialisation']``
      block can switch the initial state from the platform
      ``initial_soc`` convention to a fixed initial concentration
      (inverse-OCP method).  Datasets without that block keep the
      exact v0.1-v0.4 behaviour.
    """
    t_exp = df["time_s"].to_numpy(dtype=float)
    I_exp = df["current_A"].to_numpy(dtype=float)
    V_exp = df["voltage_V"].to_numpy(dtype=float)

    t_exp, I_exp, V_exp = _filter_and_downsample(t_exp, I_exp, V_exp)

    model = build_model(model_name, options=model_options)

    params = load_parameter_values(parameter_set)

    # v0.3 (interface extension, additive): a dynamic-protocol
    # window can carry its own starting state of charge (e.g. the
    # CALCE 20R windows start at 50 % / 80 % SOC).  Datasets that
    # do not provide one keep the validated initial_soc=1.0.
    #
    # v0.5 (additive): a half-cell dataset may declare an
    # "initialisation" block with method
    #   fixed_initial_concentration  -> x0 from inverse-OCP(rest V0)
    # The initial_soc convention (a battery SOC) does not apply to
    # Li-metal half cells; the reported metric is left NaN and the
    # initial_state_* columns carry the exact semantics.
    init_block = df.attrs.get("initialisation") or {}
    init_method = str(init_block.get("method", "initial_soc"))

    if init_method == "initial_soc":
        initial_soc = float(df.attrs.get("initial_soc", 1.0))
    else:
        initial_soc = float("nan")

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

    # Real experimental current trace as the model input
    current_function = pybamm.Interpolant(t_exp, I_exp, pybamm.t)
    params["Current function [A]"] = current_function

    mapping_rows: list = []

    # v0.5 H5/H6: for a fixed-initial-concentration replay the
    # working-electrode initial concentration is overridden BEFORE
    # the Simulation is built so the processed model sees the
    # mapped value (x0*c_max from the measured rest OCV).  The
    # full-cell initial_soc path is untouched.
    if init_method == "fixed_initial_concentration":
        conc_key = str(init_block.get("concentration_parameter") or "")
        max_key = str(init_block.get("max_concentration_parameter") or "")
        if conc_key not in params or max_key not in params:
            raise ValueError(
                f"fixed_initial_concentration: parameter keys not found "
                f"in parameter set '{parameter_set}' "
                f"({conc_key!r} / {max_key!r})"
            )
        source_value = float(params[conc_key])
        x0 = float(init_block["stoichiometry_from_ocp"])
        v0 = float(init_block["ocp_voltage_V"])
        c_max = float(params[max_key])
        mapped_value = float(x0 * c_max)
        params[conc_key] = mapped_value

        mapping_rows.append(
            {
                "parameter_set": parameter_set,
                "source_key": conc_key,
                "mapped_key": conc_key,
                "source_value": source_value,
                "mapped_value": mapped_value,
                "mapping_reason": (
                    f"inverse-OCP(rest OCV {v0:.4f} V) -> x0 = {x0:.4f} "
                    f"-> x0*c_max = {mapped_value:.1f} mol/m3; "
                    + str(init_block.get("mapping_reason", ""))
                ),
            }
        )

    simulation = pybamm.Simulation(model, parameter_values=params)

    tic = time.perf_counter()

    if init_method == "initial_soc":
        solution = simulation.solve(t_eval=t_exp, initial_soc=initial_soc)
    elif init_method == "fixed_initial_concentration":
        solution = simulation.solve(t_eval=t_exp)
    else:
        raise ValueError(
            f"unknown initialisation method '{init_method}' "
            f"(supported: initial_soc, fixed_initial_concentration)"
        )

    runtime_s = time.perf_counter() - tic

    t_sim = np.asarray(solution.t, dtype=float)

    try:
        V_sim_full = np.asarray(
            solution["Terminal voltage [V]"].entries,
            dtype=float,
        )
    except KeyError:
        V_sim_full = np.asarray(
            solution["Voltage [V]"].entries,
            dtype=float,
        )

    # PyBaMM can terminate at the lower-voltage event before t_exp ends
    common_end = min(float(t_exp[-1]), float(t_sim[-1]))
    mask = t_exp <= common_end

    t_common = t_exp[mask]
    V_exp_common = V_exp[mask]

    V_sim_common = np.interp(t_common, t_sim, V_sim_full)

    residual = V_sim_common - V_exp_common

    rmse_v = float(np.sqrt(np.mean(residual ** 2)))
    mae_v = float(np.mean(np.abs(residual)))
    bias_v = float(np.mean(residual))
    max_abs_error_v = float(np.max(np.abs(residual)))
    coverage = float(common_end / t_exp[-1])

    Q_exp_integrated = integrate_capacity(t_exp, I_exp)
    Q_exp_reported = float(df["capacity_Ah"].dropna().iloc[-1])

    try:
        Q_sim = float(solution["Discharge capacity [A.h]"].entries[-1])
    except Exception:
        Q_sim = np.nan

    capacity_error_pct = (
        100.0 * (Q_sim - Q_exp_reported) / Q_exp_reported
        if np.isfinite(Q_sim)
        else np.nan
    )

    median_current = float(np.median(I_exp))
    nominal_capacity = float(params["Nominal cell capacity [A.h]"])
    c_rate_measured = median_current / nominal_capacity

    # --------------------------------------------------------------
    # v0.3 Step 24 (additive metrics; existing values untouched)
    #   residual_std_mV          dispersion of the V(t) residual
    #   current_rms_A / current_peak_*_A   protocol
    #   characterization (NOT model scoring).  Canonical current
    #   sign: discharge = +.
    # --------------------------------------------------------------
    residual_std_mV = float(np.std(residual)) * 1000.0
    current_rms_A = float(np.sqrt(np.mean(I_exp ** 2)))
    current_peak_discharge_A = float(np.max(I_exp))
    current_peak_charge_A = float(-np.min(I_exp))

    # v0.3 Step 19: protocol metadata travels with the window via
    # df.attrs (set by the adapter); datasets without attrs get
    # empty protocol fields (CC datasets: profile_kind = "").
    prov = dict(df.attrs.get("provenance", {}) or {})
    ist = dict(prov.get("initial_state", {}) or {})

    # v0.5 H5 audit: report keys PyBaMM 26.8 auto-materialised next
    # to the author's legacy keys when an external set is loaded
    # (they are never silently renamed or dropped).
    if init_method != "initial_soc" and parameter_sources.is_external(
        parameter_set
    ):
        try:
            src_dict = parameter_sources.load_parameter_dict(parameter_set)
            for k in parameter_sources.auto_materialised_keys(
                src_dict, params.keys()
            ):
                val = params[k]
                mapping_rows.append(
                    {
                        "parameter_set": parameter_set,
                        "source_key": "(absent from author dict)",
                        "mapped_key": str(k),
                        "source_value": None,
                        "mapped_value": (
                            float(val)
                            if isinstance(val, (int, float))
                            else str(val)[:120]
                        ),
                        "mapping_reason": (
                            "auto-materialised by PyBaMM 26.8 "
                            "(deprecated-key alias); value copied from "
                            "the author's legacy key, model inputs "
                            "unchanged"
                        ),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - audit is best-effort
            mapping_rows.append(
                {
                    "parameter_set": parameter_set,
                    "source_key": "",
                    "mapped_key": "",
                    "source_value": None,
                    "mapped_value": None,
                    "mapping_reason": (
                        "alias audit unavailable: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    return {
        # time-aligned scalar metrics (mV family)
        "rmse_time_aligned_mV": rmse_v * 1000.0,
        "mae_time_aligned_mV": mae_v * 1000.0,
        "bias_time_aligned_mV": bias_v * 1000.0,
        "max_abs_error_mV": max_abs_error_v * 1000.0,
        "coverage_fraction": coverage,
        # v0.3 Step 24: dynamic-replay additions
        "residual_std_mV": residual_std_mV,
        "current_rms_A": current_rms_A,
        "current_peak_discharge_A": current_peak_discharge_A,
        "current_peak_charge_A": current_peak_charge_A,
        # v0.3 Step 19/22: protocol metadata (empty for CC datasets)
        "protocol_id": prov.get("protocol_id", ""),
        "profile_kind": prov.get("profile_kind", ""),
        "source_file": prov.get("source_file", ""),
        "source_cycle": prov.get("source_cycle", ""),
        "source_step": prov.get("source_step", ""),
        "source_soc_percent": prov.get("source_soc_percent", ""),
        "initial_soc": initial_soc,
        "initial_soc_source": prov.get("initial_soc_source", ""),
        "identification": prov.get("identification", ""),
        # v0.3 freeze item: explicit initial-state semantics for
        # dynamic windows replayed from a nominal SOC without the
        # preceding charge/rest history (empty for CC datasets).
        "initial_state_type": ist.get("type", ""),
        "initial_state_value": ist.get("value", ""),
        "initial_state_source": ist.get("source", ""),
        "initial_state_history_replayed": ist.get("history_replayed", ""),
        "initial_state_is_exact_electrochemical_state": (
            ist.get("is_exact_electrochemical_state", "")
        ),
        "initial_state_purpose": ist.get("purpose", ""),
        "initial_state_fitted_to_voltage": ist.get(
            "fitted_to_voltage", ""
        ),
        # v0.4 final temperature semantics (empty for CC datasets
        # that carry no provenance temperature block)
        "ambient_temperature_source": prov.get(
            "ambient_temperature_source", ""
        ),
        "measured_cell_temperature_role": prov.get(
            "measured_cell_temperature_role", ""
        ),
        "initial_temperature_C": prov.get("initial_temperature_C", ""),
        # capacity
        # C: explicit semantics -- this is a FORCED-WINDOW charge,
        # not a cutoff-capacity prediction (Q_sim integrates the
        # measured current over the experimental window).
        "Q_exp_reported_Ah": Q_exp_reported,
        "Q_exp_integrated_Ah": Q_exp_integrated,
        "Q_sim_Ah": Q_sim,
        "experimental_window_charge_Ah": Q_exp_integrated,
        "simulated_forced_window_charge_Ah": Q_sim,
        "capacity_metric_type": "forced_current_window",
        "capacity_is_predictive": False,
        "capacity_error_pct": capacity_error_pct,
        # operating point
        "ambient_temperature_C": ambient_C,
        "median_current_A": median_current,
        "c_rate_measured": c_rate_measured,
        # timing / coverage
        "experimental_duration_s": float(t_exp[-1]),
        "simulation_duration_s": float(t_sim[-1]),
        "n_comparison_points": int(len(t_common)),
        "runtime_s": runtime_s,
        # arrays for the comparison table / plot
        "_t_common": t_common,
        "_V_exp_common": V_exp_common,
        "_V_sim_common": V_sim_common,
        "_residual": residual,
        "_init_method": init_method,
        "_mapping_rows": mapping_rows or None,
    }


# ------------------------------------------------------------------
# Public runner
# ------------------------------------------------------------------
def run_baseline_cell(
    adapter,
    model_name: str,
    cell: str,
    rate: Optional[str] = None,
    parameter_set: Optional[str] = None,
    plot: bool = True,
    quiet: bool = False,
) -> dict:
    """
    Run the time-aligned baseline replay for one (cell [, rate]).

    ``rate=None`` runs every rate of the dataset.
    Returns {"metrics": DataFrame, "output_dir": Path, "runtime_s": ...}.
    """
    if parameter_set is None:
        parameter_set = adapter.config.parameter_set

    # v0.5 half-cell pilot (H5/H7, additive): translate the
    # datasets.yaml half-cell first-class block into pybamm model
    # options.  full_cell keeps model_options=None -> the exact
    # v0.1-v0.4 model construction.
    extra = adapter.config.extra or {}
    cell_configuration = str(extra.get("cell_configuration") or "full_cell")
    if cell_configuration.strip() in ("", "full_cell"):
        cell_configuration = "full_cell"
        working_electrode = ""
        model_options = None
    else:
        working_electrode = str(extra.get("working_electrode") or "").strip()
        if working_electrode not in ("positive", "negative"):
            raise ValueError(
                f"dataset '{adapter.config.dataset_id}': "
                f"cell_configuration='{cell_configuration}' requires "
                f"working_electrode in {{positive, negative}} "
                f"(configs/datasets.yaml)"
            )
        model_options = build_model_options(
            cell_configuration=f"half_cell_{working_electrode}",
            working_electrode=working_electrode,
            extra_model_options=extra.get("model_options"),
        )

    solver_cfg = get_solver_config()

    # v0.3 (interface extension, additive): ``rate`` may be a
    # single window id, a list of window ids (e.g. the CLI expands
    # --protocol DST -> [DST50, DST80]), or None = every window.
    if rate is None:
        rates: List[str] = list(adapter.list_rates())
    elif isinstance(rate, (list, tuple)):
        rates = [str(r) for r in rate]
    else:
        rates = [str(rate)]

    out_dir = ensure_dir(
        platform_output_dir(
            adapter.config.dataset_id,
            "baseline",
            model_name,
            cell,
        )
    )

    rows = []
    tic_all = time.perf_counter()

    for r in rates:
        # A: canonical rate normalization -- c_rate is the machine
        # key; rate_slug names files; `rate` keeps the legacy label
        # so existing regressions stay untouched.
        info = adapter.rate_info(r)
        rate_slug = str(info["rate_slug"])

        df = adapter.load_processed_discharge(cell, r)

        if not quiet:
            print(
                f"[BASELINE] cell{cell} {rate_slug} "
                f"({info['rate_label']}, source: {info['source_rate']}) "
                f"{model_name.upper()}",
                flush=True,
            )

        res = _run_one_replay(
            df,
            model_name=model_name,
            parameter_set=parameter_set,
            model_options=model_options,
        )

        row = {
            "cell": cell,
            "model": model_name.upper(),
            # legacy compat column (do NOT groupby across datasets
            # on this -- use c_rate)
            "rate": str(info["legacy_rate"]),
            "c_rate": float(info["c_rate"]),
            "rate_label": str(info["rate_label"]),
            "rate_slug": rate_slug,
            "source_rate": str(info["source_rate"]),
            "parameter_set": parameter_set,
            # C: baseline Q_sim comes from forcing the measured
            # current over the measured time window -- it is NOT a
            # capacity prediction.
            "capacity_metric_type": "forced_current_window",
            "capacity_is_predictive": False,
        }
        for k, v in res.items():
            if not k.startswith("_"):
                row[k] = v

        # v0.5 half-cell pilot: report the cell configuration on the
        # metrics row ONLY when it is not the default full cell, so
        # the four frozen datasets keep byte-identical outputs.
        if model_options is not None:
            row["cell_configuration"] = cell_configuration
            row["working_electrode"] = working_electrode
        rows.append(row)

        # per-rate time-aligned comparison table + plot
        # (named by the canonical rate_slug)
        pd.DataFrame(
            {
                "time_s": res["_t_common"],
                "voltage_exp_V": res["_V_exp_common"],
                "voltage_sim_V": res["_V_sim_common"],
                "residual_V": res["_residual"],
            }
        ).to_csv(out_dir / f"{rate_slug}_time_aligned.csv", index=False)

        if plot:
            save_time_voltage_plot(
                res["_t_common"],
                res["_V_exp_common"],
                res["_t_common"],
                res["_V_sim_common"],
                out_dir / f"{rate_slug}_Vt.png",
                model=model_name.upper(),
                rmse_mV=row["rmse_time_aligned_mV"],
            )

        # v0.5 H5/H7 audit file: parameter mapping + full provenance
        # for every externally-parameterised replay.  Written only
        # when a mapping exists, so frozen full-cell output dirs are
        # unchanged.
        mapping_rows = res.get("_mapping_rows")
        if mapping_rows:
            prov = dict(df.attrs.get("provenance", {}) or {})
            ocp_file = getattr(adapter, "_ocp_file", None)
            ocp_sha = ""
            if ocp_file is not None and Path(ocp_file).is_file():
                try:
                    ocp_sha = parameter_sources.sha256_file(
                        Path(ocp_file)
                    )
                except Exception:  # noqa: BLE001 - best-effort audit
                    ocp_sha = ""
            mapping_doc = {
                "dataset": adapter.config.dataset_id,
                "cell": cell,
                "model": model_name.upper(),
                "rate_slug": rate_slug,
                "rate_label": str(info["rate_label"]),
                "c_rate": float(info["c_rate"]),
                "source_rate": str(info["source_rate"]),
                "parameter_set": parameter_set,
                "external_repo_commit": (
                    parameter_sources.repo_commit(parameter_set)
                    if parameter_sources.is_external(parameter_set)
                    else ""
                ),
                "pybamm_version": pybamm.__version__,
                "solver": {
                    "class": str(solver_cfg.get("class", "IDAKLUSolver")),
                    "rtol": float(solver_cfg.get("rtol", 1.0e-6)),
                    "atol": float(solver_cfg.get("atol", 1.0e-6)),
                },
                "source_file": prov.get("source_file", ""),
                "dataset_file_sha256": prov.get("file_sha256", ""),
                "ocp_file": str(ocp_file) if ocp_file is not None else "",
                "ocp_file_sha256": ocp_sha,
                "mapping": mapping_rows,
            }
            with open(
                out_dir / f"{rate_slug}_parameter_mapping.json",
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(mapping_doc, f, indent=2, ensure_ascii=False)

        if not quiet:
            print(
                f"  RMSE(t)={row['rmse_time_aligned_mV']:7.2f} mV | "
                f"MAE(t)={row['mae_time_aligned_mV']:7.2f} mV | "
                f"Qexp={row['Q_exp_reported_Ah']:.3f} Ah | "
                f"Qsim={row['Q_sim_Ah']:.3f} Ah"
            )

    metrics = pd.DataFrame(rows)

    runtime_s = time.perf_counter() - tic_all

    metrics.to_csv(out_dir / "metrics.csv", index=False)

    with open(
        out_dir / "run_metadata.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            {
                "dataset": adapter.config.dataset_id,
                "model": model_name.upper(),
                "cell": cell,
                "mode": "baseline",
                # canonical rate keys (c_rate is the machine key)
                "rates": [
                    str(adapter.rate_info(r)["rate_slug"]) for r in rates
                ],
                "rate_labels": [
                    str(adapter.rate_info(r)["rate_label"]) for r in rates
                ],
                "c_rates": [
                    float(adapter.rate_info(r)["c_rate"]) for r in rates
                ],
                "source_rates": [
                    str(adapter.rate_info(r)["source_rate"]) for r in rates
                ],
                "parameter_set": parameter_set,
                # C: capacity semantics of the open-loop replay
                "capacity_metric_type": "forced_current_window",
                "capacity_is_predictive": False,
                "capacity_metric_note": (
                    "Q_sim integrates the experimentally measured "
                    "current over the experimental time window, so "
                    "Q_sim ~= Q_exp by construction.  Do NOT read "
                    "baseline Q_sim-Q_exp as a capacity prediction; "
                    "predictive capacity requires a constant-current "
                    "run where the model itself reaches the cutoff."
                ),
                # v0.2: chemistry-parameter compatibility block
                # (dataset-agnostic merge from the adapter).
                "parameter_match": (
                    adapter.get_metadata().get("parameter_match")
                ),
                # v0.5 half-cell pilot (H5/H7): first-class cell
                # configuration + external-repo provenance, added
                # only for half-cell datasets (frozen full-cell
                # metadata unchanged).
                **(
                    {
                        "cell_configuration": cell_configuration,
                        "working_electrode": working_electrode,
                        "model_options": model_options,
                        "parameter_source": dict(
                            extra.get("parameter_source", {})
                        ),
                        "parameter_repo_commit": (
                            parameter_sources.repo_commit(parameter_set)
                            if parameter_sources.is_external(parameter_set)
                            else ""
                        ),
                    }
                    if model_options is not None
                    else {}
                ),
                "metric_family": (
                    "time-aligned V(t) replay "
                    "(rmse_time_aligned_mV / mae_time_aligned_mV / "
                    "bias_time_aligned_mV)"
                ),
                "reused_reference": "scripts/run_baseline.py",
                "pybamm_version": pybamm.__version__,
                "timestamp": timestamp_utc(),
                "runtime_s": runtime_s,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    return {
        "metrics": metrics,
        "output_dir": out_dir,
        "runtime_s": runtime_s,
    }


if __name__ == "__main__":  # pragma: no cover - CLI is run_pipeline.py
    raise SystemExit("Use: python run_pipeline.py --mode baseline ...")
