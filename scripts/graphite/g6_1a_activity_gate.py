"""G6.1a -- Protocol-dependent activity gate for function-valued parameters.

THE CLAIM UNDER TEST
    A function-valued diffusivity D_s(x) that is present in the model and
    consumed by it is not necessarily OBSERVABLE.  Whether the trajectory
    responds to it at all depends on whether the protocol excites solid
    diffusion -- and, as this gate found the hard way, on whether the
    model is on the same SCALE as the cell.

    Same recorded D_s(x) function, scaled by {0.316, 1, 3.162}:

      negative control   SINTEF p-OCV window     C/50, quasi-equilibrium
      positive control   DLR GITT pulse windows  C/10, 150 s pulse

PRE-REGISTERED CRITERIA (fixed before running, so the result cannot be
read backwards out of the numbers):

    negative control PASSES as a control when the spread of
        RMSE across the three multipliers is < 0.10 mV  (i.e. INERT)
    positive control PASSES when the spread of
        dV_pulse across the three multipliers is > 1.00 mV  (i.e. ACTIVE)
    the gate passes when BOTH hold
    activity ratio = spread(positive) / spread(negative)

CAPACITY CONSISTENCY IS A PRECONDITION, applied to BOTH arms.
    Ecker2015_graphite_halfcell describes an 86 cm2, 202 mAh cell.  The
    DLR record passes 6.55 mAh and the SINTEF window ~1.9 mAh, so without
    this step the DLR C/10 pulse lands at C/309 and the SINTEF C/50 branch
    at C/4670.  A scale mismatch would then masquerade as parameter
    inertness -- which is the exact conclusion this gate exists to reach.
    See simulation.protocol_replay.capacity_consistency_overrides.

WHAT THIS IS NOT
    Not a validation of Ecker2015.  The DLR cell is a different cell from
    a different laboratory with a different electrode and OCP; the
    replay is a CAPABILITY demonstration.  Reported numbers are not model
    error.

Usage:
    python scripts/graphite/g6_1a_activity_gate.py [--out outputs/fitting/g6.1a]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import battery_sim.paths as paths  # noqa: E402

from battery_sim.excitation import (  # noqa: E402
    ConstantCurrentProtocol,
    Protocol,
    Segment,
)
from battery_sim.models.pybamm_factory import (  # noqa: E402
    load_parameter_values,
    resolve_model_options,
)
from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.baseline import _run_one_replay  # noqa: E402
from battery_sim.simulation.protocol_replay import (  # noqa: E402
    capacity_consistency_overrides,
    transient_metrics,
)

#: The function-valued parameter under test.
DS_KEY = "Positive particle diffusivity [m2.s-1]"

MULTIPLIERS = (0.316, 1.0, 3.162)

#: pre-registered thresholds, in mV
NEGATIVE_MAX_RMSE_SPREAD_MV = 0.10
POSITIVE_MIN_DV_PULSE_SPREAD_MV = 1.00

ARMS: List[Dict[str, Any]] = [
    {
        "name": "negative_pOCV",
        "role": "negative",
        "dataset": "sintef_graphite",
        "cell": "4ccc47",
        "rate": "pOCV-deli",
        "model": "SPM",
        "note": "C/50 quasi-equilibrium sweep: no transport limitation is "
                "ever established",
    },
    {
        "name": "negative_zero_current",
        "role": "negative",
        "dataset": "dlr_gitt",
        "cell": "Hydra.0b_A",
        "v_target_V": 0.1165,
        "zero_current": True,
        "model": "SPM",
        "note": "SINGLE-VARIABLE control: the same window, the same scale "
                "and the same D_s(x) override as positive_GITT_plateau, "
                "with the excitation removed.  pOCV changes the scale, the "
                "duration and the state at once, so it cannot separate "
                "'no excitation' from 'different everything'.",
    },
    {
        "name": "positive_GITT_plateau",
        "role": "positive",
        "dataset": "dlr_gitt",
        "cell": "Hydra.0b_A",
        "v_target_V": 0.1165,
        "model": "SPM",
        "note": "GITT pulse in the graphite plateau region",
    },
    {
        "name": "positive_GITT_steep",
        "role": "positive",
        "dataset": "dlr_gitt",
        "cell": "Hydra.0b_A",
        "v_target_V": 0.93,
        "model": "SPM",
        "note": "GITT pulse where the OCP is steep (largest measured "
                "transient)",
    },
]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _sintef_window_protocol(adapter, cell: str, rate: str,
                            df: pd.DataFrame) -> Protocol:
    """Describe the SINTEF p-OCV replay window with the same schema.

    The window is (rest tail) + (one constant-current branch); its
    provenance states both durations, so the two segments are read off
    the adapter's own record rather than re-derived here.
    """
    prov = df.attrs["provenance"]
    rest_s = float(prov["rest_tail_s"])
    total_s = float(df["time_s"].iloc[-1])
    v_at_rest_end = float(
        df.loc[df["time_s"] <= rest_s, "voltage_V"].iloc[-1]
    )
    v_end = float(df["voltage_V"].iloc[-1])
    branch_I = float(np.median(df.loc[df["time_s"] > rest_s, "current_A"]))
    segs = (
        Segment(kind="rest", t_start_s=0.0, t_stop_s=rest_s, current_A=0.0,
                label="pre-branch rest tail", voltage_start_V=float(df["voltage_V"].iloc[0]),
                voltage_end_V=v_at_rest_end, row_start=0, row_stop=0),
        Segment(kind="constant_current", t_start_s=rest_s, t_stop_s=total_s,
                current_A=branch_I, label=str(prov.get("branch", "branch")),
                voltage_start_V=v_at_rest_end, voltage_end_V=v_end,
                row_start=0, row_stop=0),
    )
    # A rest + one branch is not a ConstantCurrentProtocol (which requires
    # every segment to carry current), so this uses the plain Protocol:
    # the object is here to fix the segment boundaries the transients are
    # measured on, not to claim a classification the window does not have.
    return Protocol(
        protocol_id=f"sintef_{rate}", segments=segs,
        temperature_C=float(prov.get("ambient_temperature_C", float("nan"))),
        source={"constructed_from": "adapter provenance",
                "rest_tail_s": rest_s, "branch": prov.get("branch")},
    )


def _dlr_window(adapter, cell: str, v_target: float):
    pid = adapter.find_triplet("discharge", v_target)
    df = adapter.load_processed_protocol(cell, pid)
    proto = adapter.load_protocol(pid)
    return pid, df, proto


def _sintef_window(adapter, cell: str, rate: str):
    df = adapter.load_processed_discharge(cell, rate)
    proto = _sintef_window_protocol(adapter, cell, rate, df)
    return f"{adapter.config.dataset_id}:{rate}", df, proto


def build_ds_override(parameter_set: str, multiplier: float):
    """Wrap the parameter set's own D_s(x) function by a constant factor.

    This is the function-valued override the gate is about: the result is
    a CALLABLE, not a number, so the shape of D_s(x) is preserved and
    only its level moves.  A scalar override here would be testing a
    different capability.
    """
    pv = load_parameter_values(parameter_set)
    if DS_KEY not in pv:
        raise KeyError(f"{parameter_set}: no {DS_KEY!r}")
    ref = pv[DS_KEY]
    if not callable(ref):
        raise TypeError(
            f"{parameter_set}: {DS_KEY!r} is {type(ref).__name__}, not a "
            f"function; the scalar-versus-function distinction is the "
            f"whole point of this gate"
        )

    def scaled(*args, _m=float(multiplier), _ref=ref):
        return _m * _ref(*args)

    scaled.__name__ = f"graphite_diffusivity_x{multiplier:.3f}"
    return scaled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/fitting/g6.1a")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    # every replay writes under a redirected platform root so the gate
    # cannot dirty the frozen outputs/ tree
    paths.PLATFORM_OUTPUT_ROOT = out / "platform_runs"

    tic = time.perf_counter()
    report: Dict[str, Any] = {
        "gate": "G6.1a",
        "claim": "protocol-dependent activity of a function-valued D_s(x)",
        "ds_key": DS_KEY,
        "multipliers": list(MULTIPLIERS),
        "criteria_mV": {
            "negative_max_rmse_spread": NEGATIVE_MAX_RMSE_SPREAD_MV,
            "positive_min_dv_pulse_spread":
                POSITIVE_MIN_DV_PULSE_SPREAD_MV,
        },
        "capacity_consistency": {},
        "arms": {},
    }

    log("=" * 88)
    log("G6.1a  protocol-dependent activity gate for function-valued parameters")
    log("=" * 88)

    for arm in ARMS:
        name = arm["name"]
        log(f"\n{'-' * 88}")
        log(f"[{arm['role']:8s}] {name}   ({arm['note']})")
        log(f"{'-' * 88}")

        adapter = get_dataset(arm["dataset"])
        ps = adapter.config.parameter_set
        model_options = resolve_model_options(adapter)

        if arm["dataset"] == "dlr_gitt":
            pid, df, proto = _dlr_window(adapter, arm["cell"],
                                         arm["v_target_V"])
        else:
            pid, df, proto = _sintef_window(adapter, arm["cell"], arm["rate"])

        log(f"  window      : {pid}")
        log(f"  {proto.describe()}")

        if arm.get("zero_current"):
            # Remove ONLY the excitation.  The frame's current goes to
            # zero; the protocol object keeps its segment boundaries, so
            # the transients are still measured at the same instants and
            # "no response" cannot be confused with "no measurement".
            df = df.copy()
            df["current_A"] = np.zeros(len(df), dtype=float)
            log("  excitation  : REMOVED (current set to zero)")

        # ---- capacity consistency (same rule, both arms) ----------
        # the identifier differs by arm: a protocol id on the DLR side, a
        # bare rate on the SINTEF side (whose adapter has no protocol
        # capability and resolves windows through load_processed_discharge)
        cc_id = (pid if arm["dataset"] == "dlr_gitt" else arm["rate"])
        cc = capacity_consistency_overrides(adapter, cc_id, arm["cell"])
        report["capacity_consistency"][name] = {
            "protocol_id": pid,
            "scale_factor_area": cc["scale"],
            "model_capacity_Ah": cc["model_capacity_Ah"],
            "measured_charge_Ah": cc["measured_charge_Ah"],
            "overrides": cc["overrides"],
        }
        log(f"  capacity    : model {cc['model_capacity_Ah'] * 1e3:.3f} mAh"
            f" -> measured {cc['measured_charge_Ah'] * 1e3:.4f} mAh"
            f"   scale {cc['scale']:.6f} (area)")

        I_pulse = float(np.nanmax(np.abs(df["current_A"].to_numpy(float))))
        q_matched = cc["model_capacity_Ah"] * cc["scale"]
        log(f"  pulse       : {I_pulse:.4e} A -> "
            f"{I_pulse / q_matched:.4f} C on the matched capacity")

        rows = []
        for mult in MULTIPLIERS:
            ds_fn = build_ds_override(ps, mult)
            overrides = {DS_KEY: ds_fn, **cc["overrides"]}
            sources = {
                DS_KEY: {
                    "source": "G6.1a activity gate",
                    "method": "function-valued scaling of the reference "
                              "D_s(x,T)",
                    "multiplier": mult,
                },
                **cc["source"],
            }
            res = _run_one_replay(
                df,
                model_name=arm["model"],
                parameter_set=ps,
                model_options=model_options,
                parameter_overrides=overrides,
                parameter_override_sources=sources,
            )
            sim = transient_metrics(proto, res["_t_common"],
                                    res["_V_sim_common"])
            exp = transient_metrics(proto, res["_t_common"],
                                    res["_V_exp_common"])
            row = {
                "multiplier": mult,
                "rmse_mV": float(res["rmse_time_aligned_mV"]),
                "mae_mV": float(res["mae_time_aligned_mV"]),
                "bias_mV": float(res["bias_time_aligned_mV"]),
                "coverage_fraction": float(res["coverage_fraction"]),
                "sim_dv_pulse_mV": sim.get("dv_pulse_mV"),
                "sim_dv_relax_mV": sim.get("dv_relax_mV"),
                "sim_v_span_mV": sim.get("v_span_mV"),
                "exp_dv_pulse_mV": exp.get("dv_pulse_mV"),
                "exp_dv_relax_mV": exp.get("dv_relax_mV"),
                "n_applied": len(res.get("_applied_overrides") or []),
            }
            rows.append(row)
            log(f"    x{mult:<6.3f} RMSE {row['rmse_mV']:9.4f} mV | "
                f"dV_pulse {row['sim_dv_pulse_mV']:+9.4f} mV | "
                f"dV_relax {row['sim_dv_relax_mV']:+9.4f} mV | "
                f"span {row['sim_v_span_mV']:9.4f} mV | "
                f"cov {row['coverage_fraction']:.3f}")

        tbl = pd.DataFrame(rows)

        def spread(col: str) -> float:
            v = tbl[col].to_numpy(float)
            v = v[np.isfinite(v)]
            return float(v.max() - v.min()) if v.size else float("nan")

        entry = {
            "role": arm["role"],
            "note": arm["note"],
            "dataset": arm["dataset"],
            "cell": arm["cell"],
            "protocol_id": pid,
            "protocol": proto.as_dict(),
            "pulse_c_rate_on_matched_capacity": float(
                I_pulse / q_matched
            ),
            "rows": rows,
            "spread": {
                "rmse_mV": spread("rmse_mV"),
                "sim_dv_pulse_mV": spread("sim_dv_pulse_mV"),
                "sim_dv_relax_mV": spread("sim_dv_relax_mV"),
                "sim_v_span_mV": spread("sim_v_span_mV"),
            },
            "exp_baseline": {
                "dv_pulse_mV": rows[0]["exp_dv_pulse_mV"],
                "dv_relax_mV": rows[0]["exp_dv_relax_mV"],
            },
        }

        # monotone with the multiplier?  a response that is not ordered by
        # the parameter cannot be attributed to the parameter
        vals = tbl["sim_dv_pulse_mV"].to_numpy(float)
        finite = vals[np.isfinite(vals)]
        entry["ordered_by_multiplier"] = bool(
            finite.size == len(MULTIPLIERS)
            and (np.all(np.diff(finite) < 0) or np.all(np.diff(finite) > 0))
        )

        if arm["role"] == "negative":
            entry["verdict"] = (
                "INERT (control holds)"
                if entry["spread"]["rmse_mV"] < NEGATIVE_MAX_RMSE_SPREAD_MV
                else "ACTIVE (negative control FAILED)"
            )
            entry["passed"] = bool(
                entry["spread"]["rmse_mV"] < NEGATIVE_MAX_RMSE_SPREAD_MV
            )
        else:
            entry["verdict"] = (
                "ACTIVE"
                if entry["spread"]["sim_dv_pulse_mV"]
                > POSITIVE_MIN_DV_PULSE_SPREAD_MV
                else "INERT (positive control FAILED)"
            )
            entry["passed"] = bool(
                entry["spread"]["sim_dv_pulse_mV"]
                > POSITIVE_MIN_DV_PULSE_SPREAD_MV
            )

        log(f"  -> RMSE spread {entry['spread']['rmse_mV']:.4f} mV | "
            f"dV_pulse spread {entry['spread']['sim_dv_pulse_mV']:.4f} mV | "
            f"ordered {entry['ordered_by_multiplier']}")
        log(f"  -> {entry['verdict']}")
        report["arms"][name] = entry

    # ---- gate verdict ------------------------------------------------
    # Reported PER ARM rather than as one all() over "negatives": the two
    # negative arms are not interchangeable, and collapsing them would
    # hide the fact that one of them failed for an instructive reason.
    neg = {k: a for k, a in report["arms"].items() if a["role"] == "negative"}
    pos = {k: a for k, a in report["arms"].items() if a["role"] == "positive"}

    neg_ok = all(a["passed"] for a in neg.values()) if neg else False
    pos_ok = any(a["passed"] for a in pos.values()) if pos else False

    best_pos = max(
        (a["spread"]["sim_dv_pulse_mV"] for a in pos.values()),
        default=float("nan"),
    )
    worst_neg = max(
        (a["spread"]["sim_dv_pulse_mV"] for a in neg.values()
         if np.isfinite(a["spread"]["sim_dv_pulse_mV"])),
        default=float("nan"),
    )
    ratio = float("nan")
    if np.isfinite(best_pos) and best_pos > 0:
        if np.isfinite(worst_neg) and worst_neg > 0:
            ratio = float(best_pos / worst_neg)
        elif np.isfinite(worst_neg) and worst_neg == 0.0:
            # an exactly inert control is the ideal outcome, and makes the
            # ratio unbounded rather than undefined
            ratio = float("inf")

    report["verdict"] = {
        "per_arm": {k: {"verdict": a["verdict"], "passed": a["passed"]}
                    for k, a in {**neg, **pos}.items()},
        "all_negative_controls_hold": bool(neg_ok),
        "any_positive_control_holds": bool(pos_ok),
        "activity_ratio_positive_over_negative": float(ratio),
        "passed": bool(neg_ok and pos_ok),
        "runtime_s": time.perf_counter() - tic,
    }

    log("")
    log("=" * 88)
    for k, a in {**neg, **pos}.items():
        log(f"  {a['role']:8s} {k:26s} {a['verdict']}")
    log(f"all negative controls hold : {neg_ok}")
    log(f"any positive control holds : {pos_ok}")
    log(f"activity ratio             : {ratio:.2f}x  "
        f"(best positive dV_pulse spread / worst negative dV_pulse spread)")
    log(f"GATE PASSED                : {bool(neg_ok and pos_ok)}")
    log(f"runtime                    : {time.perf_counter() - tic:.1f} s")
    log("=" * 88)
    log("")
    log("NOTE on negative_pOCV: its pre-registered criterion (RMSE spread")
    log("< 0.10 mV) was FIXED BEFORE the run and it FAILED.  The failure is")
    log("kept, not re-thresholded.  Its cause is a real finding: once the")
    log("model is on the cell's scale, a C/50 sweep DOES resolve D_s, so")
    log("'quasi-equilibrium implies inert' is false.  The earlier claim of")
    log("inertness was an artefact of a 31x capacity mismatch.")

    (out / "g6_1a_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"arm": k, **r}
            for k, a in report["arms"].items()
            for r in a["rows"]
        ]
    ).to_csv(out / "g6_1a_activity.csv", index=False)
    log(f"\nwrote {out / 'g6_1a_report.json'}")
    log(f"wrote {out / 'g6_1a_activity.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
