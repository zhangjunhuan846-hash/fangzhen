"""Replay ONE recorded window as a function of the D_s multiplier.

WHY THIS IS SHARED
    G6.1b-1 scans three synthetic truths on two windows; G6.1c scans the
    reference on 239 windows.  Both need the identical object: a window
    whose simulated trajectory can be evaluated at an arbitrary
    ``a0`` (where ``D_s(x) = D_ref(x) * 10**a0``), cached by ``a0``, with
    one definition of the cost between two trajectories.

    Two copies would drift -- and the drift would be silent, because both
    copies would keep returning plausible numbers.  That is the failure
    mode this project has already paid for twice (the half-cell option
    translation, the parameter capability table).

THE CACHING IS NOT AN OPTIMISATION, IT IS THE MEASUREMENT DESIGN
    The cost of a synthetic recovery is ``||V(a) - V(a_truth)||``, and
    ``V(a_truth)`` is itself one point of the same scan.  Sharing that
    evaluation is exactly the inverse crime both gates declare: the
    observation is not independent data.  It is kept because it is the
    correct way to test the WIRING, and it is reported in both scripts so
    that a reader cannot mistake the result for identifiability.

WHY THE COST IS MODEL-TO-MODEL
    A residual against the measurement would be dominated by the
    parameter set being calibrated for a different cell, which is a
    different question (and is what G6.1a measured).  Here the question is
    how far the parameter can move before the TRAJECTORY notices.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from battery_sim.models.pybamm_factory import load_parameter_values
from battery_sim.simulation.baseline import (
    _filter_and_downsample,
    _run_one_replay,
)
from battery_sim.simulation.protocol_replay import transient_metrics

#: The function-valued parameter these gates are about.
DS_KEY = "Positive particle diffusivity [m2.s-1]"

#: A run that stopped early is not "a small transient", it is a run that
#: did not happen.  Below this coverage the point is dropped and reported
#: as unreachable -- better to fail than to fit a fragment.
MIN_COVERAGE = 0.98


def build_multiplier_override(parameter_set: str, a_dex: float):
    """Wrap the parameter set's own D_s(x,T) by ``10**a_dex``.

    The result is a CALLABLE, not a number, so the shape of D_s(x) is
    preserved and only its level moves.  A scalar override here would be
    testing a different capability -- and would in fact be rejected, since
    D_s is a function in this parameter set.
    """
    pv = load_parameter_values(parameter_set)
    if DS_KEY not in pv:
        raise KeyError(f"{parameter_set}: no {DS_KEY!r}")
    ref = pv[DS_KEY]
    if not callable(ref):
        raise TypeError(
            f"{parameter_set}: {DS_KEY!r} is {type(ref).__name__}, not a "
            f"function; the scalar-versus-function distinction is the whole "
            f"point of these gates"
        )
    mult = float(10.0 ** float(a_dex))

    def scaled(*args, _m=mult, _ref=ref):
        # *args, not (sto, T): the reference signature is f(sto, T) today,
        # but dropping an argument would silently drop the temperature
        # dependence rather than fail
        return _m * _ref(*args)

    scaled.__name__ = f"graphite_diffusivity_10p{a_dex:+.4f}"
    return scaled


class MultiplierScan:
    """One recorded protocol window, evaluated as a function of ``a0``."""

    def __init__(self, adapter, cell, protocol_id, df, protocol,
                 parameter_set, model_options, alignment,
                 zero_current: bool = False):
        self.adapter = adapter
        self.cell = cell
        self.protocol_id = protocol_id
        self.protocol = protocol
        self.parameter_set = parameter_set
        self.model_options = model_options
        self.alignment = alignment
        self.zero_current = bool(zero_current)

        frame = df
        if self.zero_current:
            frame = df.copy()
            frame["current_A"] = np.zeros(len(frame), dtype=float)
        # the reference grid _run_one_replay itself uses: strictly
        # increasing time, capped at 2000 points.  Reproducing it here
        # keeps every run index-aligned, so a truncated run becomes a NaN
        # tail rather than a silently different axis.
        t_ref, _, _ = _filter_and_downsample(
            frame["time_s"].to_numpy(dtype=float),
            frame["current_A"].to_numpy(dtype=float),
            frame["voltage_V"].to_numpy(dtype=float),
        )
        self.frame = frame
        self.t_ref = t_ref
        self.n_ref = int(t_ref.size)
        self._cache: Dict[float, Dict[str, Any]] = {}
        self.n_sim = 0
        self.runtime_s = 0.0

    # --------------------------------------------------------------
    def evaluate(self, a_dex: float, *, force: bool = False) -> Dict[str, Any]:
        import time

        key = round(float(a_dex), 6)
        if not force and key in self._cache:
            return self._cache[key]

        V_ref = np.full(self.n_ref, np.nan, dtype=float)
        tic = time.perf_counter()
        res = _run_one_replay(
            self.frame,
            model_name="SPM",
            parameter_set=self.parameter_set,
            model_options=self.model_options,
            parameter_overrides={
                DS_KEY: build_multiplier_override(self.parameter_set, key),
                **self.alignment["overrides"],
            },
            parameter_override_sources={
                DS_KEY: {
                    "source": "G6.1b-1/G6.1c log-multiplier scan",
                    "method": "log10 D_s(x) = log10 D_ref(x) + a0",
                    "a0_dex": key,
                    "multiplier": float(10.0 ** key),
                },
                **self.alignment["source"],
            },
        )
        self.runtime_s += time.perf_counter() - tic
        self.n_sim += 1

        t_common = np.asarray(res["_t_common"], dtype=float)
        V_sim = np.asarray(res["_V_sim_common"], dtype=float)
        n_common = int(t_common.size)
        # t_common is a prefix of t_ref (same filter, same cap), so this is
        # an assignment, not an interpolation: no extra error is injected
        # between the simulated trace and the reference axis.
        if n_common > 0:
            V_ref[:n_common] = V_sim

        tr = transient_metrics(self.protocol, t_common, V_sim)
        pre = self.protocol.segments[0] if self.protocol.segments else None
        rec = {
            "a_dex": key,
            "V_ref": V_ref,
            "coverage_fraction": n_common / self.n_ref,
            "n_common": n_common,
            "n_applied": len(res.get("_applied_overrides") or []),
            "rmse_vs_measured_mV": float(res["rmse_time_aligned_mV"]),
            "dv_pulse_mV": tr.get("dv_pulse_mV"),
            "dv_relax_mV": tr.get("dv_relax_mV"),
            "v_span_mV": tr.get("v_span_mV"),
            "pre_pulse_stop_s": float(pre.t_stop_s) if pre is not None else None,
        }
        self._cache[key] = rec
        return rec

    # --------------------------------------------------------------
    def reachable(self, rec: Dict[str, Any]) -> bool:
        return bool(rec["coverage_fraction"] >= MIN_COVERAGE)

    def cost(self, a_dex: float, a_truth_dex: float) -> float:
        """J(a | a_0) = mean squared model-to-model voltage difference, mV^2.

        The difference is confined to the pulse and the relaxation: during
        the pre-pulse rest both runs sit at the same state and D_s cannot
        matter.  :meth:`pre_pulse_leak_mV` measures exactly that.
        """
        ra = self.evaluate(a_dex)
        rb = self.evaluate(a_truth_dex)
        if not (self.reachable(ra) and self.reachable(rb)):
            return float("inf")
        m = np.isfinite(ra["V_ref"]) & np.isfinite(rb["V_ref"])
        if m.sum() < MIN_COVERAGE * self.n_ref:
            return float("inf")
        d = (ra["V_ref"][m] - rb["V_ref"][m]) * 1e3
        return float(np.mean(d ** 2))

    def compare(self, a_dex: float, a_truth_dex: float) -> Dict[str, float]:
        ra = self.evaluate(a_dex)
        rb = self.evaluate(a_truth_dex)
        m = np.isfinite(ra["V_ref"]) & np.isfinite(rb["V_ref"])
        d = (ra["V_ref"][m] - rb["V_ref"][m]) * 1e3
        if not d.size:
            return {"rmse_mV": float("nan"), "max_abs_mV": float("nan")}
        return {
            "rmse_mV": float(np.sqrt(np.mean(d ** 2))),
            "max_abs_mV": float(np.max(np.abs(d))),
        }

    def pre_pulse_leak_mV(self, a_dex: float) -> float:
        """How far the override moved the trace BEFORE the pulse.

        Must be ~0: both runs rest at the same state.  A larger number
        would mean the comparison is contaminated outside the excitation,
        i.e. that the cost surface is not a clean function of D_s.
        """
        ra = self.evaluate(a_dex)
        r0 = self.evaluate(0.0)
        stop = ra.get("pre_pulse_stop_s")
        if stop is None:
            return float("nan")
        n = int(np.searchsorted(self.t_ref, stop, side="right"))
        if n <= 0:
            return float("nan")
        d = (ra["V_ref"][:n] - r0["V_ref"][:n]) * 1e3
        d = d[np.isfinite(d)]
        return float(np.max(np.abs(d))) if d.size else float("nan")


__all__ = [
    "DS_KEY",
    "MIN_COVERAGE",
    "MultiplierScan",
    "build_multiplier_override",
]
