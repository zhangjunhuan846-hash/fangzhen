"""G5.4 -- multi-protocol identifiability and model consistency.

Two questions, answered together:

    1. do additional protocols improve D_s / R_p separability?
    2. do they EXPOSE model-form inconsistency?

Both are open.  Four parallel ridges need not be useless: they can differ in
centre, curvature and width, and under mismatch each protocol may want its own
optimum, in which case a joint fit is forced into a compromise that no single
protocol is happy with.  That compromise is the second question's answer.

THE OBJECTIVE -- equal weight per protocol, not a pooled SSE.

Pooling raw residuals would silently weight protocols by how many points they
have and how long they run, so a long low-rate discharge would outvote a short
high-rate one.  Instead each protocol is normalised to its own mean square and
the protocols are averaged:

    J(theta) = (1/K) * sum_k  (1/N_k) * sum_i [ V_sim(k,i) - V_obs(k,i) ]^2

That is implemented WITHOUT a custom cost class: each protocol's voltages are
pre-scaled by 1/sqrt(N_k) before being concatenated, so a plain
``pybop.SumSquaredError`` over the concatenated series evaluates to exactly
K * J.  Minimising it minimises J.  Doing it this way keeps PyBOP's own cost,
its failure handling and its sensitivity plumbing intact.

Measurements reported, because RMSE alone says nothing about identifiability:

    optimum vs truth, per-protocol residual AT the joint optimum,
    local Hessian -> condition number and corr(D_s, R_p), profile width.

The per-protocol residual is the model-consistency diagnostic: if each rate
wants a different parameter set, the joint optimum leaves a rate-dependent
residue that no shared parameter can remove.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from identification.forward import (
    R_NAME,
    Z_NAME,
    Observation,
    ReplayCase,
    make_replay_simulator,
    replay_with,
    _source_record,
)
from identification.forward import PARAM_KEYS, RP_KEY, TARGET, DOMAIN


@dataclass
class ProtocolSet:
    """A named group of rates fitted JOINTLY."""

    name: str
    rates: Tuple[str, ...]

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.name} = {' + '.join(self.rates)}"


#: The four nested protocol sets of the gate.
PROTOCOL_SETS = (
    ProtocolSet("P1", ("C10",)),
    ProtocolSet("P2", ("C10", "C2")),
    ProtocolSet("P3", ("C10", "C2", "1C")),
    ProtocolSet("P4", ("C10", "C2", "1C", "1p5C")),
)


@dataclass
class MultiObservation:
    """Several protocols sharing one parameter vector."""

    protocols: List[Observation]
    name: str = ""

    def __post_init__(self):
        self.scales = [1.0 / math.sqrt(len(p.time_s)) for p in self.protocols]
        self.n_points = [len(p.time_s) for p in self.protocols]

    @property
    def total_points(self) -> int:
        return int(sum(self.n_points))

    def as_pybop_dataset(self):
        """Concatenated, per-protocol-normalised series.

        The time axis is shifted so each protocol occupies its own band, which
        keeps the concatenation monotone and prevents the interpolator from
        connecting the end of one protocol to the start of the next.
        """
        import pybop

        ts, vs = [], []
        offset = 0.0
        gap = 1.0
        for p, s in zip(self.protocols, self.scales):
            t = np.asarray(p.time_s, dtype=float)
            v = np.asarray(p.voltage_V, dtype=float)
            ts.append(t + offset)
            vs.append(v * s)
            offset += float(t[-1]) + gap
        return pybop.Dataset(
            {DOMAIN: np.concatenate(ts), TARGET: np.concatenate(vs)},
            domain=DOMAIN,
        )


def make_multiproto_simulator(
    parameters,
    multi: MultiObservation,
    output_root: Path,
    audit_dir: Path,
    replay_case: Optional[ReplayCase] = None,
    min_coverage: float = 0.5,
    rp_bounds: Optional[Tuple[float, float]] = None,
    fixed_overrides: Optional[Dict[str, float]] = None,
):
    """PyBOP simulator running EVERY protocol in the set for one parameter vector."""
    import pybop

    scales = list(multi.scales)
    obs_list = list(multi.protocols)
    # Each protocol runs its OWN rate -- a joint fit spans protocols, so the
    # case cannot be a single object.  What the joint fit DOES share is the
    # model form (``replay_case.model_name``) and the parameter set.
    cases = []
    for o in obs_list:
        tmpl = replay_case if replay_case is not None else o.case
        cases.append(ReplayCase(
            dataset_id=tmpl.dataset_id or o.case.dataset_id,
            cell=o.case.cell,
            rate=o.case.rate,
            model_name=tmpl.model_name,
            parameter_set=tmpl.parameter_set or o.case.parameter_set,
        ).resolve())

    class MultiProtocolSimulator(pybop.BaseSimulator):
        def __init__(self):
            super().__init__(parameters=parameters)
            self.multi = multi
            self.scales = scales
            self.obs_list = obs_list
            self.cases = cases
            self.output_root = Path(output_root)
            self.audit_dir = Path(audit_dir)
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            self.min_coverage = float(min_coverage)
            self.rp_bounds = rp_bounds
            # Constants injected on EVERY evaluation.  Dropping a parameter
            # from the optimisation does NOT pin it -- the model silently falls
            # back to its default, which is how an earlier version of this gate
            # produced identical results for two different pinned radii.
            self.fixed_overrides = dict(fixed_overrides or {})
            self.records: List[Dict[str, Any]] = []

        def solve(self, inputs=None, calculate_sensitivities=False):
            idx = len(self.records) + 1
            overrides: Dict[str, float] = {}
            srcs: Dict[str, Any] = {}
            values: Dict[str, float] = {}
            for name, key in PARAM_KEYS.items():
                if name not in inputs:
                    continue
                zz = float(inputs[name])
                values[name] = zz
                overrides[key] = 10.0 ** zz
                srcs[key] = _source_record(name, zz)

            for key, val in self.fixed_overrides.items():
                overrides[key] = float(val)
                srcs.setdefault(key, {
                    "source": "INDEPENDENT MEASUREMENT (pinned, not fitted)",
                    "method": "identification/G5.4 group C",
                })

            per_protocol: List[Dict[str, Any]] = []
            chunks_t, chunks_v = [], []
            offset = 0.0
            gap = 1.0
            failed = False

            for o, case, s in zip(self.obs_list, self.cases, self.scales):
                t_sim, v_sim, res = replay_with(
                    case, overrides, srcs, output_root=self.output_root
                )
                t_obs = np.asarray(o.time_s, dtype=float)
                t_end = min(float(t_obs[-1]), float(t_sim[-1]))
                mask = t_obs <= t_end
                coverage = float(t_end / t_obs[-1]) if t_obs[-1] > 0 else 0.0
                n = int(mask.sum())
                if n < 2 or coverage < self.min_coverage:
                    failed = True
                t_grid = t_obs[mask] if n else t_obs[:0]
                v_on = (np.interp(t_grid, t_sim, v_sim) if n else t_obs[:0])
                per_protocol.append({
                    "rate": o.case.rate,
                    "n_points": n,
                    "coverage": coverage,
                    "unreachable": bool(n < 2 or coverage < self.min_coverage),
                    "cost": None,
                })
                if n:
                    chunks_t.append(t_grid + offset)
                    chunks_v.append(v_on * s)
                    offset += float(t_grid[-1]) + gap

                self.records.append({
                    "index": idx,
                    "values": dict(values),
                    "requested": dict(res.get("applied_overrides") or {}),
                    "applied": list(res.get("parameter_overrides_applied") or []),
                    "rate": o.case.rate,
                    "coverage": coverage,
                    "n_points": n,
                    "json_path": str(Path(res["output_dir"]) / "run_metadata.json"),
                })

            # record the per-protocol residuals THIS candidate achieves, so the
            # joint optimum can be audited rate by rate
            self.records[-1]["per_protocol"] = per_protocol

            sol = pybop.Solution(inputs=inputs)
            if failed or not chunks_v:
                sol.set_solution_variable(
                    TARGET, data=np.full(2, np.nan, dtype=float))
                return sol
            sol.set_solution_variable(
                TARGET, data=np.concatenate(chunks_v).astype(float))
            return sol

        def solve_batch(self, inputs=None, calculate_sensitivities=False):
            return [self.solve(x, calculate_sensitivities) for x in inputs]

        @property
        def has_sensitivities(self):
            return False

        def write_audit(self, path: Path) -> None:
            import json
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.records, indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8")

    return MultiProtocolSimulator()


def build_joint_problem(
    multi: MultiObservation,
    output_root: Path,
    audit_dir: Path,
    replay_case: Optional[ReplayCase] = None,
    z_bounds: Sequence[float] = (-16.0, -13.0),
    r_bounds: Sequence[float] = (math.log10(1e-6), math.log10(2e-5)),
    z_init: float = -14.699,
    r_init: float = -5.282,
    fixed_radius: Optional[float] = None,
):
    """Joint problem over the protocol set. fixed_radius PINS R_p (group C).

    Pinning means injecting a constant override, not merely removing R_p from
    the parameter list -- otherwise the model quietly uses its default value
    and the constraint has no effect.
    """
    import pybop

    params = {Z_NAME: (float(z_init), tuple(float(b) for b in z_bounds))}
    fixed_overrides = None
    if fixed_radius is None:
        params[R_NAME] = (float(r_init), tuple(float(b) for b in r_bounds))
    else:
        fixed_overrides = {RP_KEY: float(fixed_radius)}

    parameters = pybop.Parameters({
        n: pybop.Parameter(initial_value=v[0], bounds=list(v[1]))
        for n, v in params.items()
    })
    sim = make_multiproto_simulator(
        parameters, multi, output_root=output_root, audit_dir=audit_dir,
        replay_case=replay_case, min_coverage=0.5,
        fixed_overrides=fixed_overrides,
    )
    cost = pybop.SumSquaredError(
        dataset=multi.as_pybop_dataset(), target=TARGET)
    return pybop.Problem(simulator=sim, cost=cost), sim


def _cost_of(problem, inputs) -> float:
    ev = problem.evaluate(inputs)
    return float(np.ravel(np.asarray(ev.values, dtype=float))[0])


def local_geometry(
    problem,
    z_opt: float,
    r_opt: Optional[float],
    h: float = 0.05,
    n_points_scale: Optional[float] = None,
) -> Dict[str, Any]:
    """Local Hessian from a 3x3 (or 1-D) stencil, then curvature facts.

    Reports the condition number and corr(D_s, R_p) because those, not the
    location of the minimum, say whether the two parameters are separable.
    """
    if r_opt is None:
        pts = {d: _cost_of(problem, {Z_NAME: z_opt + d})
               for d in (-h, 0.0, h)}
        h11 = (pts[h] - 2 * pts[0.0] + pts[-h]) / (h * h)
        return {
            "kind": "1-D (R_p fixed)",
            "h_dex": h,
            "h_zz": float(h11),
            "condition_number": None,
            "corr_Ds_Rp": None,
            "cost_at_optimum": pts[0.0],
        }

    offsets = (-0.20, -0.05, 0.0, 0.05, 0.20)
    grid = {}
    for dz in offsets:
        for dr in offsets:
            grid[(dz, dr)] = _cost_of(
                problem, {Z_NAME: z_opt + dz, R_NAME: r_opt + dr})

    base = grid[(0.0, 0.0)]

    def _ratio(num, den):
        if not (np.isfinite(num) and np.isfinite(den)) or den <= 0:
            return None
        return float(num / den)

    # SHARPNESS, not "rise from the minimum".  On the synthetic control arm the
    # cost at the optimum is machine zero, so any ratio normalised by it explodes
    # (measured: 5e9).  Dividing the small-offset cost by the WIDE-offset cost
    # gives a scale-free number that stays finite in both arms: near 0 means the
    # direction is already stiff at small offsets, near 1 means the cost is
    # still climbing slowly, i.e. a long flat ridge.
    sharp_D = _ratio(grid[(0.05, 0.0)], grid[(0.20, 0.0)])
    sharp_R = _ratio(grid[(0.0, 0.05)], grid[(0.0, 0.20)])
    rise_D = _ratio(grid[(0.05, 0.0)], base) if base > 0 else None
    rise_R = _ratio(grid[(0.0, 0.05)], base) if base > 0 else None

    h = 0.05
    hzz = (grid[(h, 0)] - 2 * base + grid[(-h, 0)]) / (h * h)
    hrr = (grid[(0, h)] - 2 * base + grid[(0, -h)]) / (h * h)
    hzr = (grid[(h, h)] - grid[(h, -h)] - grid[(-h, h)] + grid[(-h, -h)]) / (
        4 * h * h)
    H = np.array([[hzz, hzr], [hzr, hrr]], dtype=float)
    ev = np.linalg.eigvalsh(H)
    cond = float(abs(ev[-1]) / abs(ev[0])) if min(abs(ev)) > 0 else float("inf")
    denom = math.sqrt(abs(hzz * hrr)) if hzz * hrr else float("nan")
    corr = float(-hzr / denom) if denom and np.isfinite(denom) else float("nan")

    # A stencil correlation outside [-1, 1] means the 2x2 form is not positive
    # definite, i.e. the cost is not locally quadratic at this step. Reporting
    # such a number as a correlation would be nonsense, so it is withheld.
    corr_reliable = bool(np.isfinite(corr) and -1.0 <= corr <= 1.0)

    return {
        "kind": "2-D",
        "h_dex": h,
        "hessian": H.tolist(),
        "eigenvalues": [float(x) for x in ev],
        "condition_number": cond,
        "corr_Ds_Rp": corr if corr_reliable else None,
        "corr_Ds_Rp_raw": corr,
        "corr_reliable": corr_reliable,
        "sharpness_D": sharp_D,
        "sharpness_R": sharp_R,
        "rise_D_at_0p05": rise_D,
        "rise_R_at_0p05": rise_R,
        "cost_at_optimum": base,
        "stencil": {f"{k[0]:+.2f},{k[1]:+.2f}": v for k, v in grid.items()},
    }


def per_protocol_residuals(
    multi: MultiObservation,
    optimal_inputs: Dict[str, float],
    output_root: Path,
    audit_dir: Path,
    replay_case: Optional[ReplayCase] = None,
    case_model: str = "SPM",
) -> List[Dict[str, Any]]:
    """Residual of EACH protocol at a shared parameter vector.

    This is the model-consistency diagnostic. A single parameter vector that
    fits every protocol equally well is consistent; one that is forced into a
    compromise shows up as a rate-dependent residual.
    """
    out = []
    overrides, srcs = {}, {}
    for name, key in PARAM_KEYS.items():
        if name in optimal_inputs:
            zz = float(optimal_inputs[name])
            overrides[key] = 10.0 ** zz
            srcs[key] = _source_record(name, zz, note="joint optimum")

    for o in multi.protocols:
        case = ReplayCase(
            dataset_id=o.case.dataset_id, cell=o.case.cell, rate=o.case.rate,
            model_name=(replay_case.model_name if replay_case is not None
                        else case_model),
            parameter_set=o.case.parameter_set,
        ).resolve()
        t_sim, v_sim, _ = replay_with(
            case, overrides, srcs, output_root=output_root)
        t_obs = np.asarray(o.time_s, dtype=float)
        t_end = min(float(t_obs[-1]), float(t_sim[-1]))
        mask = t_obs <= t_end
        if mask.sum() < 2:
            out.append({"rate": o.case.rate, "n_points": int(mask.sum()),
                        "coverage": 0.0, "rms_mV": None, "bias_mV": None})
            continue
        v_on = np.interp(t_obs[mask], t_sim, v_sim)
        d = v_on - np.asarray(o.voltage_V)[mask]
        out.append({
            "rate": o.case.rate,
            "n_points": int(mask.sum()),
            "coverage": float(t_end / t_obs[-1]),
            "rms_mV": float(np.sqrt(np.mean(d ** 2)) * 1000.0),
            "bias_mV": float(np.mean(d) * 1000.0),
        })
    return out
