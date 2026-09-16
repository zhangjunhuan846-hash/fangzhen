# ============================================================
# Battery Dataset Simulation Platform
# Recorded-protocol replay entry
#
# WHY NOT ``run_baseline_cell``
#   ``run_baseline_cell`` replays ONE rated discharge window per rate
#   and reports capacity-style columns that only mean something for a
#   continuous-current sweep (``current_peak_discharge_A``, forced-window
#   capacity, ...).  A pulse-relax protocol is a different object: its
#   observables are the pulse overvoltage and the relaxation recovery,
#   not a capacity.  Forcing it through the baseline entry would either
#   mis-report those columns or require special-casing inside a frozen
#   function.
#
# WHAT IS REUSED
#   Everything below the window: ``_run_one_replay`` is the same
#   validated simulation core (same model factory, same parameter
#   loading, same override path with its before/after provenance, same
#   time-aligned error family, same CSV/metadata writing helpers).  This
#   module adds the protocol-specific resolution and reporting ON TOP,
#   so the numerics cannot drift between the two entries.
#
# This is additive: nothing in the frozen runner / evaluator / factory /
# registry / rates.py / paths.py is modified.
# ============================================================

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from battery_sim.excitation import Protocol
from battery_sim.logging_utils import timestamp_utc
from battery_sim.models.pybamm_factory import resolve_model_options
from battery_sim.paths import ensure_dir, platform_output_dir
from battery_sim.simulation.baseline import _json_safe, _run_one_replay

#: Output mode directory.  Deliberately distinct from "baseline": a
#: protocol replay is not a baseline comparison and must not overwrite
#: one, nor be mistaken for one when the outputs are read back.
OUTPUT_MODE = "protocol"

#: How a replay handles the scale-alignment precondition.
#:   "check"  (default) refuse to run when the model is not on the cell's
#:            scale -- the gate.  Silent scale mismatch reads as parameter
#:            inertness, and that mistake has been made twice already.
#:   "align"  apply the footprint recipe that puts Q_model on Q_measured.
#:   "assume" proceed without checking, for replays whose scale is right
#:            BY CONSTRUCTION (e.g. the parameter set is the cell's own).
#:            Recorded as such, so the assumption is auditable.
SCALE_ALIGNMENT_MODES = ("check", "align", "assume")


def _apply_scale_alignment(
    adapter,
    cell: str,
    protocol_id: str,
    mode: Optional[str],
    parameter_overrides: Optional[dict],
    parameter_override_sources: Optional[dict],
):
    """Enforce / apply the scale-alignment precondition (see governance).

    Returns ``{"record", "parameter_overrides", "parameter_override_sources"}``.
    """
    from governance.scale_alignment import (
        ScaleMisalignment,
        alignment_overrides,
        audit,
    )

    mode = "check" if mode is None else str(mode)
    if mode not in SCALE_ALIGNMENT_MODES:
        raise ValueError(
            f"scale_alignment must be one of {SCALE_ALIGNMENT_MODES}, "
            f"got {mode!r}"
        )
    overrides = dict(parameter_overrides or {})
    sources = dict(parameter_override_sources or {})

    if mode == "assume":
        return {
            "record": {
                "stage": "capacity_alignment",
                "verdict": "assumed_by_caller",
                "note": (
                    "the caller declared the model to be on the cell's "
                    "scale; no audit was performed, so this replay carries "
                    "no evidence that it is"
                ),
            },
            "parameter_overrides": overrides or None,
            "parameter_override_sources": sources or None,
        }

    rec = audit(adapter, protocol_id, cell)

    if mode == "check":
        if rec["verdict"] != "aligned":
            raise ScaleMisalignment(
                f"{rec['dataset_id']} / {rec['protocol_id']}: model is "
                f"{rec['model_capacity_Ah'] * 1e3:.3f} mAh, record passed "
                f"{rec['measured_charge_Ah'] * 1e3:.4f} mAh "
                f"(x{rec['capacity_ratio_model_over_measured']:.1f}). "
                f"Re-run with scale_alignment='align' to apply the "
                f"footprint recipe, or 'assume' to state explicitly that "
                f"the scale is right.  Running as-is would put a window "
                f"read at C/{1.0 / rec['c_rate_on_cell']:.0f} at "
                f"C/{1.0 / rec['c_rate_on_model_unscaled']:.0f}."
            )
        return {
            "record": rec,
            "parameter_overrides": overrides or None,
            "parameter_override_sources": sources or None,
        }

    # mode == "align"
    al = alignment_overrides(adapter, protocol_id, cell)
    clash = sorted(set(al["overrides"]) & set(overrides))
    if clash:
        raise ValueError(
            f"scale_alignment='align' would overwrite caller-supplied "
            f"override(s) {clash}; pass them out of parameter_overrides or "
            f"use scale_alignment='assume' and align them yourself"
        )
    return {
        "record": {
            **rec,
            "mode": "align",
            "applied": True,
            "footprint_scale_area": al["footprint_scale_area"],
            "footprint_scale_linear": al["footprint_scale_linear"],
            "overrides_applied": sorted(al["overrides"]),
        },
        "parameter_overrides": {**al["overrides"], **overrides},
        "parameter_override_sources": {**al["source"], **sources},
    }


def protocol_slug(protocol_id: str) -> str:
    """Filesystem-safe name for a protocol id."""
    s = re.sub(r"[^0-9A-Za-z_.+-]+", "_", str(protocol_id)).strip("_")
    return s or "protocol"


def transient_metrics(
    protocol: Protocol,
    t_s: np.ndarray,
    voltage_V: np.ndarray,
) -> Dict[str, float]:
    """Pulse and relaxation amplitudes of a simulated trace, in mV.

    The activity gate's pre-registered observables.  They are measured
    from the SIMULATED trace on the same segment boundaries the recorded
    protocol declares, so the simulated and measured numbers are directly
    comparable instead of each being computed its own way.

    A trace that does not reach the segment boundary is reported as NaN
    rather than silently clamped to the last sample: "the replay stopped
    early" and "the transient was small" are different results.
    """
    segs = [s for s in protocol.segments]
    current_carrying = [i for i, s in enumerate(segs)
                        if s.is_current_carrying]
    out: Dict[str, float] = {}
    if not current_carrying:
        return out

    t_s = np.asarray(t_s, dtype=float)
    voltage_V = np.asarray(voltage_V, dtype=float)
    if t_s.size == 0:
        return out

    i_pulse = current_carrying[0]
    pre = segs[i_pulse - 1] if i_pulse > 0 else None
    post = (segs[i_pulse + 1]
            if i_pulse + 1 < len(segs) and not
            segs[i_pulse + 1].is_current_carrying else None)

    def _at(t_target: float) -> float:
        """Voltage at (or just before) ``t_target``; NaN if unreached."""
        if not np.isfinite(t_target):
            return float("nan")
        if t_target > t_s[-1] + 1e-9:
            return float("nan")
        idx = int(np.searchsorted(t_s, t_target, side="right")) - 1
        if idx < 0:
            return float("nan")
        return float(voltage_V[idx])

    v_pre = _at(pre.t_stop_s) if pre is not None else float("nan")
    v_pulse_end = _at(segs[i_pulse].t_stop_s)
    v_relax_end = (_at(post.t_stop_s) if post is not None
                   else float(voltage_V[-1]))

    out: Dict[str, float] = {}
    out["v_pre_V"] = v_pre
    out["v_pulse_end_V"] = v_pulse_end
    out["v_relax_end_V"] = v_relax_end
    out["dv_pulse_mV"] = (v_pulse_end - v_pre) * 1e3
    out["dv_relax_mV"] = (v_relax_end - v_pulse_end) * 1e3
    out["v_span_mV"] = float(np.ptp(voltage_V)) * 1e3
    return out


def capacity_consistency_overrides(
    adapter,
    protocol_id: str,
    cell: Optional[str] = None,
    *,
    parameter_set: Optional[str] = None,
    charge_reference: Optional[str] = None,
    knobs: Sequence[str] = ("Electrode height [m]", "Electrode width [m]"),
) -> Dict[str, object]:
    """Scale the model's electrode footprint to the cell's own capacity.

    WHY THIS IS NEEDED.  A parameter set describes ONE cell.  Applied to a
    different cell, the same amperes are a different C-rate, and a
    protocol that is genuinely diffusion-limited on the real cell can be
    numerically inert on the model -- not because the model is wrong
    about the physics, but because it is the wrong SIZE.  Measured here:
    Ecker2015_graphite_halfcell is an 86 cm2, 202 mAh cell, while the DLR
    record passes 6.55 mAh over its discharge sweep, so the C/10 GITT
    pulse lands at C/309 and moves the voltage by 0.4 mV instead of 17.

    A scale mismatch therefore masquerades as parameter inertness, which
    is exactly the conclusion an activity gate is trying to reach.  So
    the gate has to remove it first.

    This is now a thin adapter over ``governance.scale_alignment``, which
    is where the concept lives (``docs/scale_alignment_gate.md``): the
    capacity arithmetic exists in exactly one place, so the gate, this
    helper and any future caller cannot drift apart.  ``scale`` here is
    the AREA factor; the governance record also carries the linear factor
    and the C-rate the model would have been at without it.

    Returns ``{"overrides", "source", "scale", "model_capacity_Ah",
    "measured_charge_Ah"}``; ``overrides`` plugs straight into
    ``run_protocol_replay(parameter_overrides=...)`` and ``source`` into
    ``parameter_override_sources=...`` so the scaling is as auditable as
    any other override.
    """
    from governance.scale_alignment import alignment_overrides

    rec = alignment_overrides(
        adapter,
        str(protocol_id),
        cell,
        parameter_set=parameter_set,
        charge_reference=charge_reference,
        knobs=tuple(knobs),
    )
    return {
        "overrides": rec["overrides"],
        "source": rec["source"],
        "scale": rec["footprint_scale_area"],
        "charge_reference": rec["charge_reference"],
        "model_capacity_Ah": rec["model_capacity_Ah"],
        "measured_charge_Ah": rec["measured_charge_Ah"],
    }


def run_protocol_replay(
    adapter,
    protocol_id: str,
    model_name: str = "SPM",
    cell: Optional[str] = None,
    parameter_set: Optional[str] = None,
    parameter_overrides: Optional[dict] = None,
    parameter_override_sources: Optional[dict] = None,
    scale_alignment: Optional[str] = None,
    plot: bool = False,
    quiet: bool = False,
) -> dict:
    """Replay ONE recorded protocol window through the platform.

    Returns ``{"metrics": DataFrame, "output_dir": Path, "runtime_s":
    float, "protocol": dict, "replay": dict}``.

    ``parameter_overrides`` / ``parameter_override_sources`` carry the
    identical contract as ``run_baseline_cell`` -- a key not in the
    parameter set raises ``KeyError``, and the before/after pair plus the
    caller-declared source are recorded per window.  That is what makes a
    function-valued override auditable here as well.

    ``scale_alignment`` is the precondition gate (see
    ``governance/scale_alignment.py`` and ``docs/scale_alignment_gate.md``):
    ``None``/``"check"`` refuses to replay a window whose scale does not
    match the parameter set, ``"align"`` applies the footprint recipe,
    ``"assume"`` takes the caller's word for it and records that it did.
    The default is ``check`` because a silent scale mismatch is
    indistinguishable from parameter inertness in the results.
    """
    from battery_sim.datasets.base import BatteryDatasetAdapter

    if (type(adapter).load_processed_protocol
            is BatteryDatasetAdapter.load_processed_protocol):
        raise TypeError(
            f"{type(adapter).__name__} does not expose recorded protocols "
            f"(it does not override load_processed_protocol); use "
            f"run_baseline_cell instead"
        )

    if cell is None:
        cells: List[str] = list(adapter.list_cells())
        if not cells:
            raise ValueError(
                f"dataset '{adapter.config.dataset_id}' declares no cells"
            )
        cell = cells[0]
    cell = str(cell)

    if parameter_set is None:
        parameter_set = adapter.config.parameter_set

    model_options = resolve_model_options(adapter)

    # the precondition runs BEFORE the window is even loaded, so a
    # misaligned replay cannot produce a number that looks meaningful
    al = _apply_scale_alignment(
        adapter, cell, protocol_id, scale_alignment,
        parameter_overrides, parameter_override_sources,
    )
    parameter_overrides = al["parameter_overrides"]
    parameter_override_sources = al["parameter_override_sources"]

    df = adapter.load_processed_protocol(cell, protocol_id)
    protocol = adapter.load_protocol(protocol_id)

    if not quiet:
        print(
            f"[PROTOCOL] {adapter.config.dataset_id} cell{cell} "
            f"{protocol.protocol_id} ({protocol.kind}) {model_name.upper()}",
            flush=True,
        )

    out_dir = ensure_dir(
        platform_output_dir(
            adapter.config.dataset_id, OUTPUT_MODE, model_name, cell
        )
    )

    tic = time.perf_counter()
    res = _run_one_replay(
        df,
        model_name=model_name,
        parameter_set=parameter_set,
        model_options=model_options,
        parameter_overrides=parameter_overrides,
        parameter_override_sources=parameter_override_sources,
    )
    runtime_s = time.perf_counter() - tic

    slug = protocol_slug(protocol.protocol_id)

    # ---- the gate's observables, simulated -------------------------
    sim_tr = transient_metrics(protocol, res["_t_common"],
                               res["_V_sim_common"])
    exp_tr = transient_metrics(protocol, res["_t_common"],
                               res["_V_exp_common"])

    row: Dict[str, object] = {
        "cell": cell,
        "model": model_name.upper(),
        "dataset_id": adapter.config.dataset_id,
        "protocol_id": protocol.protocol_id,
        "protocol_kind": protocol.kind,
        "parameter_set": parameter_set,
        "n_segments": len(protocol.segments),
        "protocol_duration_s": protocol.duration_s,
        "duty_cycle": protocol.duty_cycle,
        "protocol_temperature_C": protocol.temperature_C,
        "output_mode": OUTPUT_MODE,
    }
    for k, v in res.items():
        if not k.startswith("_"):
            row[k] = v
    # measured and simulated transients are prefixed so that a reader can
    # never mistake one for the other in a metrics table
    for k, v in exp_tr.items():
        row[f"exp_{k}"] = v
    for k, v in sim_tr.items():
        row[f"sim_{k}"] = v
    if sim_tr.get("dv_pulse_mV") is not None and \
            exp_tr.get("dv_pulse_mV") not in (None, 0.0):
        row["dv_pulse_error_mV"] = (
            sim_tr["dv_pulse_mV"] - exp_tr["dv_pulse_mV"]
        )
    if sim_tr.get("dv_relax_mV") is not None and \
            exp_tr.get("dv_relax_mV") not in (None, 0.0):
        row["dv_relax_error_mV"] = (
            sim_tr["dv_relax_mV"] - exp_tr["dv_relax_mV"]
        )

    applied = res.get("_applied_overrides")
    if applied:
        row["applied_overrides"] = json.dumps(
            [
                {
                    "key": e["key"],
                    "old": e["old"],
                    "new": e["new"],
                    "source": e.get("source"),
                }
                for e in applied
            ],
            ensure_ascii=False,
            default=str,
        )

    metrics = pd.DataFrame([row])

    pd.DataFrame(
        {
            "time_s": res["_t_common"],
            "voltage_exp_V": res["_V_exp_common"],
            "voltage_sim_V": res["_V_sim_common"],
            "residual_V": res["_residual"],
        }
    ).to_csv(out_dir / f"{slug}_time_aligned.csv", index=False)

    metrics.to_csv(out_dir / "metrics.csv", index=False)

    mapping_rows = res.get("_mapping_rows") or []
    meta = {
        "dataset_id": adapter.config.dataset_id,
        "cell": cell,
        "model": model_name.upper(),
        "generated_utc": timestamp_utc(),
        "output_mode": OUTPUT_MODE,
        "protocol": protocol.as_dict(),
        "protocol_window": df.attrs.get("protocol", {}),
        "scale_alignment": _json_safe(al["record"]),
        "n_points_replayed": int(len(res["_t_common"])),
        "runtime_s": runtime_s,
        "parameter_overrides_requested": _json_safe(
            dict(parameter_overrides) if parameter_overrides else None
        ),
        "parameter_overrides_applied": _json_safe(applied) if applied else None,
        "parameter_override_sources": _json_safe(
            dict(parameter_override_sources)
            if parameter_override_sources else None
        ),
        "parameter_mapping": _json_safe(mapping_rows) if mapping_rows else None,
        "measured_transient": exp_tr,
        "simulated_transient": sim_tr,
        "window_provenance": _json_safe(
            dict(df.attrs.get("provenance", {}) or {})
        ),
        "window_initialisation": _json_safe(
            dict(df.attrs.get("initialisation", {}) or {})
        ),
    }
    (out_dir / "run_metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    if not quiet:
        print(
            f"          RMSE(t)={row.get('rmse_time_aligned_mV', float('nan')):7.3f} mV"
            f" | duty {protocol.duty_cycle * 100:.3f} %"
            f" | dV_pulse sim {sim_tr.get('dv_pulse_mV', float('nan')):+.3f} mV"
            f" vs exp {exp_tr.get('dv_pulse_mV', float('nan')):+.3f} mV"
            f" | {runtime_s:.1f} s",
            flush=True,
        )

    return {
        "metrics": metrics,
        "output_dir": out_dir,
        "runtime_s": runtime_s,
        "protocol": protocol.as_dict(),
        "replay": res,
    }


__all__ = [
    "OUTPUT_MODE",
    "SCALE_ALIGNMENT_MODES",
    "capacity_consistency_overrides",
    "protocol_slug",
    "run_protocol_replay",
    "transient_metrics",
]
