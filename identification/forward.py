"""Forward model: the platform's replay, driven by PyBOP.

The chain this module exists to close:

    candidate D_s
        -> parameter_overrides        (platform additive API)
        -> PyBaMM solve               (the platform's own runner)
        -> V(t) on the observation grid
        -> cost                       (PyBOP cost, this module)
        -> PyBOP optimiser            (PyBOP drives the loop)

Everything below the cost is the PLATFORM.  Nothing here re-implements the
simulation: ``run_baseline_cell`` is the same public entry point the rest of
the platform uses, and the only thing this module adds is the adapter that
lets PyBOP call it.

Two design choices that are visible in the results and therefore must be
stated rather than buried:

1. THE OPTIMISED VARIABLE IS log10(D_s), not D_s.
   D_s lives at ~1e-15.  Handing that to a gradient-based optimiser in
   LINEAR space is asking for trouble, so the parameter PyBOP sees is
   ``z = log10(D_s)`` and the override writes ``10**z``.  This also makes
   the bounds meaningful: ``z in [-16, -13]`` is a factor-of-1000 span.

2. THE COST IS COMPUTED ON THE OVERLAP OF THE TWO TIME AXES.
   A candidate with a larger D_s reaches the voltage cut-off later and one
   with a smaller D_s reaches it sooner, so the simulated window length
   depends on the candidate.  The observation grid is fixed, so each
   evaluation is scored on ``t <= min(t_obs_end, t_sim_end)`` and the
   covered FRACTION is recorded in the audit.  A candidate that covers less
   than ``min_coverage`` of the observation window is reported as a failure
   (infinite cost) rather than scored on a sliver -- scoring a sliver would
   let a wildly wrong parameter look good.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import run_baseline_cell

#: The pybamm keys this package can identify.
DS_KEY = "Positive particle diffusivity [m2.s-1]"
RP_KEY = "Positive particle radius [m]"

#: Name of the optimised variable as PyBOP sees it.
Z_NAME = "log10_Ds"
R_NAME = "log10_Rp"

#: logical optimisation variable -> pybamm parameter key.
#:
#: Everything the simulator writes goes through this table, so a one-parameter
#: problem and a two-parameter problem share exactly one code path and cannot
#: drift apart.  Adding a third parameter means adding a row here.
PARAM_KEYS: Dict[str, str] = {
    Z_NAME: DS_KEY,
    R_NAME: RP_KEY,
}

#: The variable compared against the data.
TARGET = "Voltage [V]"
DOMAIN = "Time [s]"


def _source_record(name: str, z: float, note: str = "") -> Dict[str, Any]:
    return {
        "logical_name": {Z_NAME: "particle_diffusivity",
                         R_NAME: "particle_radius"}.get(name, name),
        "source": "PyBOP candidate evaluation",
        "method": "identification joint-parameter recovery",
        "unit": "m2/s" if name == Z_NAME else "m",
        "z": z,
        **({"note": note} if note else {}),
    }


@dataclass
class EvaluationRecord:
    """One candidate evaluation, fully attributable.

    ``z`` and ``ds`` describe the ONE-parameter (diffusivity) case and are NaN
    when that parameter was not part of the problem.  ``values`` carries the
    optimised variables for the general case, so a joint two-parameter run
    records both of its coordinates rather than pretending to be one-parameter.
    """

    index: int
    z: float
    ds: float
    requested: Dict[str, float]
    applied: List[Dict[str, Any]]
    sources: Optional[Dict[str, Any]]
    cost: float
    rmse_mV: Optional[float]
    overlap_fraction: float
    n_points: int
    json_path: str
    status: str
    values: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "z": self.z,
            "ds": self.ds,
            "values": self.values,
            "requested": self.requested,
            "applied": self.applied,
            "sources": self.sources,
            "cost": self.cost,
            "rmse_mV": self.rmse_mV,
            "overlap_fraction": self.overlap_fraction,
            "n_points": self.n_points,
            "json_path": self.json_path,
            "status": self.status,
        }


@dataclass
class ReplayCase:
    """Which measured window the forward model replays."""

    dataset_id: str
    cell: str
    rate: str
    model_name: str = "SPM"
    parameter_set: Optional[str] = None
    rate_slug: str = ""

    def resolve(self) -> "ReplayCase":
        adapter = get_dataset(self.dataset_id)
        info = adapter.rate_info(self.rate)
        return ReplayCase(
            dataset_id=self.dataset_id,
            cell=self.cell,
            rate=self.rate,
            model_name=self.model_name,
            parameter_set=self.parameter_set or adapter.config.parameter_set,
            rate_slug=str(info["rate_slug"]),
        )


@dataclass
class Observation:
    """A synthetic pseudo-experiment on a fixed time grid."""

    time_s: np.ndarray
    voltage_V: np.ndarray
    ds_true: float
    case: ReplayCase
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_pybop_dataset(self):
        import pybop

        return pybop.Dataset(
            {DOMAIN: np.asarray(self.time_s, dtype=float),
             TARGET: np.asarray(self.voltage_V, dtype=float)},
            domain=DOMAIN,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            time_s=np.asarray(self.time_s, dtype=float),
            voltage_V=np.asarray(self.voltage_V, dtype=float),
            ds_true=np.array([self.ds_true]),
        )
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "ds_true": self.ds_true,
                    "dataset_id": self.case.dataset_id,
                    "cell": self.case.cell,
                    "rate": self.case.rate,
                    "rate_slug": self.case.rate_slug,
                    "model_name": self.case.model_name,
                    "parameter_set": self.case.parameter_set,
                    "n_points": int(len(self.time_s)),
                    "t_end_s": float(self.time_s[-1]),
                    **self.meta,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "Observation":
        npz = np.load(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        case = ReplayCase(
            dataset_id=meta["dataset_id"],
            cell=meta["cell"],
            rate=meta["rate"],
            model_name=meta["model_name"],
            parameter_set=meta["parameter_set"],
            rate_slug=meta["rate_slug"],
        )
        return cls(
            time_s=npz["time_s"],
            voltage_V=npz["voltage_V"],
            ds_true=float(npz["ds_true"][0]),
            case=case,
            meta=meta,
        )


def _read_time_aligned(out_dir: Path, rate_slug: str):
    """Read (t, V_sim) from the platform's time-aligned table."""
    csv = out_dir / f"{rate_slug}_time_aligned.csv"
    if not csv.is_file():
        raise FileNotFoundError(f"time-aligned table missing: {csv}")
    data = np.genfromtxt(csv, delimiter=",", names=True, encoding="utf-8")
    return (
        np.asarray(data["time_s"], dtype=float),
        np.asarray(data["voltage_sim_V"], dtype=float),
    )


def replay_with(
    case: ReplayCase,
    overrides: Dict[str, float],
    sources: Optional[Dict[str, Any]] = None,
    output_root: Optional[Path] = None,
):
    """Run ONE platform replay with an arbitrary override set.

    ``overrides`` maps pybamm keys to values.  The general form exists so that
    a joint two-parameter problem and a single-parameter problem go through
    the same door into the platform -- and so that the platform's override API
    is exercised identically in both.
    """
    import battery_sim.paths as paths

    saved = paths.PLATFORM_OUTPUT_ROOT
    if output_root is not None:
        paths.PLATFORM_OUTPUT_ROOT = Path(output_root)
    try:
        adapter = get_dataset(case.dataset_id)
        res = run_baseline_cell(
            adapter,
            case.model_name,
            case.cell,
            rate=case.rate,
            parameter_set=case.parameter_set,
            plot=False,
            quiet=True,
            parameter_overrides={k: float(v) for k, v in overrides.items()},
            parameter_override_sources=(dict(sources) if sources else None),
        )
    finally:
        paths.PLATFORM_OUTPUT_ROOT = saved

    t, v = _read_time_aligned(Path(res["output_dir"]), case.rate_slug)
    return t, v, res


def replay(
    case: ReplayCase,
    ds: float,
    *,
    source_record: Optional[Dict[str, Any]] = None,
    output_root: Optional[Path] = None,
):
    """Run ONE replay with a given D_s. Convenience wrapper over replay_with."""
    return replay_with(
        case,
        {DS_KEY: float(ds)},
        {DS_KEY: source_record} if source_record else None,
        output_root,
    )


def make_replay_simulator(
    parameters,
    observation: Observation,
    output_root: Path,
    audit_dir: Path,
    min_coverage: float = 0.5,
    replay_case: Optional[ReplayCase] = None,
    param_names: Sequence[str] = (Z_NAME,),
):
    """Build a PyBOP simulator whose forward model is the platform replay.

    Deliberately a FACTORY rather than a module-level subclass: the class
    body has to inherit from ``pybop.BaseSimulator``, and doing that at
    import time would make PyBOP a hard dependency of this whole package.
    The platform's own tests must keep running without PyBOP installed, so
    the class is defined on first call instead.

    ``replay_case`` decouples the INVERSE model from the TRUTH model.  By
    default the inverse replays the same case that produced the observation,
    which is the G5.0/G5.1 setting.  Passing a different case is what makes a
    model-mismatch test possible: the observation can be generated by SPMe
    while the inverse uses SPM.  Keeping these two separate -- and recording
    both -- is the whole point; silently assuming they match is how a
    mismatch test turns into another inverse crime.
    """
    import pybop

    inverse_case = replay_case

    class PlatformReplaySimulator(pybop.BaseSimulator):
        """PyBOP simulator backed by ``run_baseline_cell``.

        ``solve`` is the whole point: it turns a PyBOP input dict into one
        platform replay, and records what the platform REPORTED against
        what was ASKED FOR, so a finished fit can be audited candidate by
        candidate.
        """

        def __init__(self):
            super().__init__(parameters=parameters)
            self.observation = observation
            # what the INVERSE runs; may differ from the truth model
            self.case = (inverse_case or observation.case).resolve()
            self.truth_case = observation.case.resolve()
            self.model_mismatch = bool(
                self.case.model_name != self.truth_case.model_name
            )
            self.output_root = Path(output_root)
            self.audit_dir = Path(audit_dir)
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            self.min_coverage = float(min_coverage)
            # The ONE table mapping optimised variables to pybamm keys.
            # A one-parameter and a two-parameter problem therefore share a
            # single code path and cannot drift apart.
            unknown = [n for n in param_names if n not in PARAM_KEYS]
            if unknown:
                raise KeyError(f"no pybamm key registered for {unknown}; "
                               f"known: {sorted(PARAM_KEYS)}")
            self.param_keys = {n: PARAM_KEYS[n] for n in param_names}
            self.records: List[EvaluationRecord] = []
            self.n_calls = 0

        # ---- the forward model ---------------------------------------
        def solve(self, inputs=None, calculate_sensitivities=False):
            if inputs is None:
                raise ValueError("an input dict is required")
            if not isinstance(inputs, dict):
                inputs = dict(inputs)

            # Index from the record list, NOT a call counter: PyBOP shallow-
            # copies the simulator when it builds the Problem, so the list is
            # shared while instance attributes are not.  Deriving the index
            # from the shared list keeps the audit correct under that copy.
            idx = len(self.records) + 1

            values: Dict[str, float] = {}
            overrides: Dict[str, float] = {}
            srcs: Dict[str, Any] = {}
            for name, key in self.param_keys.items():
                if name not in inputs:
                    continue
                zz = float(inputs[name])
                values[name] = zz
                overrides[key] = 10.0 ** zz
                srcs[key] = _source_record(name, zz)

            if not overrides:
                raise ValueError(
                    f"none of the problem's parameters "
                    f"{sorted(self.param_keys)} were supplied; "
                    f"got {sorted(inputs)}"
                )

            z_D = values.get(Z_NAME, float("nan"))
            ds = (10.0 ** z_D) if Z_NAME in values else float("nan")

            t_sim, v_sim, res = replay_with(
                self.case, overrides, srcs, output_root=self.output_root
            )

            t_obs = np.asarray(self.observation.time_s, dtype=float)
            t_end = min(float(t_obs[-1]), float(t_sim[-1]))
            mask_obs = t_obs <= t_end
            coverage = float(t_end / t_obs[-1]) if t_obs[-1] > 0 else 0.0

            requested = dict(res.get("applied_overrides") or {})
            applied = list(res.get("parameter_overrides_applied") or [])
            sources = res.get("parameter_override_sources")

            if mask_obs.sum() < 2 or coverage < self.min_coverage:
                self._record(EvaluationRecord(
                    index=idx, z=z_D, ds=ds, values=dict(values),
                    requested=requested, applied=applied, sources=sources,
                    cost=math.inf, rmse_mV=None,
                    overlap_fraction=coverage,
                    n_points=int(mask_obs.sum()),
                    json_path=str(Path(res["output_dir"]) / "run_metadata.json"),
                    status="insufficient_overlap",
                ))
                return self._nan_solution(inputs)

            t_grid = t_obs[mask_obs]
            v_on_grid = np.interp(t_grid, t_sim, v_sim)

            metrics = res["metrics"]
            rmse = (
                float(metrics.iloc[0]["rmse_time_aligned_mV"])
                if metrics is not None and len(metrics) else None
            )
            self._record(EvaluationRecord(
                index=idx, z=z_D, ds=ds, values=dict(values),
                requested=requested, applied=applied, sources=sources,
                cost=math.nan,          # the cost function fills this in
                rmse_mV=rmse,
                overlap_fraction=coverage,
                n_points=int(mask_obs.sum()),
                json_path=str(Path(res["output_dir"]) / "run_metadata.json"),
                status="ok",
            ))

            solution = pybop.Solution(inputs=inputs)
            solution.set_solution_variable(
                TARGET, data=np.asarray(v_on_grid, dtype=float)
            )
            return solution

        def solve_batch(self, inputs=None, calculate_sensitivities=False):
            if inputs is None:
                raise ValueError("inputs are required")
            return [self.solve(x, calculate_sensitivities) for x in inputs]

        @property
        def has_sensitivities(self):
            return False

        # ---- audit ---------------------------------------------------
        def _record(self, rec: EvaluationRecord):
            self.records.append(rec)
            (self.audit_dir / f"eval_{rec.index:04d}.json").write_text(
                json.dumps(rec.as_dict(), indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8",
            )

        def _nan_solution(self, inputs):
            sol = pybop.Solution(inputs=inputs)
            sol.set_solution_variable(
                TARGET, data=np.full(2, np.nan, dtype=float)
            )
            return sol

        def write_audit(self, path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps([r.as_dict() for r in self.records],
                           indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

    return PlatformReplaySimulator()


def build_problem(observation: Observation, output_root: Path, audit_dir: Path,
                  z_bounds=(-16.0, -13.0), z_initial: float = -14.398,
                  replay_case: Optional[ReplayCase] = None,
                  params: Optional[Dict[str, tuple]] = None):
    """Assemble the PyBOP Problem: parameters + simulator + cost.

    ``z_initial`` defaults to log10(4e-15), the Chen2020 nominal D_s -- i.e.
    the optimiser starts from the platform's own value, which is the least
    helpful starting point for a recovery test.  The multi-start driver
    overrides it deliberately.

    ``replay_case`` lets the INVERSE model differ from the model that
    generated the observation (see ``make_replay_simulator``).
    """
    import pybop

    # ``params`` is the JOINT form: {logical_name: (initial_value, (lo, hi))}.
    # The legacy single-parameter arguments remain the default so that
    # G5.0/G5.1/G5.2 keep working unchanged.
    if params is None:
        params = {Z_NAME: (float(z_initial), tuple(float(b) for b in z_bounds))}
    names = tuple(params)

    parameters = pybop.Parameters({
        n: pybop.Parameter(
            initial_value=float(params[n][0]),
            bounds=[float(params[n][1][0]), float(params[n][1][1])],
        )
        for n in names
    })

    simulator = make_replay_simulator(
        parameters,
        observation=observation,
        output_root=Path(output_root),
        audit_dir=Path(audit_dir),
        replay_case=replay_case,
        param_names=names,
    )

    cost = pybop.SumSquaredError(
        dataset=observation.as_pybop_dataset(), target=TARGET
    )
    problem = pybop.Problem(simulator=simulator, cost=cost)
    return problem, simulator


def predict_at(
    observation: Observation,
    ds: float,
    output_root: Path,
    audit_dir: Path,
    replay_case: Optional[ReplayCase] = None,
    z_bounds=(-16.0, -13.0),
) -> Dict[str, Any]:
    """Score ONE fixed D_s against an observation -- no fitting.

    This is what a cross-protocol transfer test needs: the parameter was
    identified on protocol A, so evaluating it on protocol B must NOT
    re-optimise.  Re-fitting on B would answer a different question.

    Returns the cost and the residual in physical units, plus the coverage
    of the comparison window.
    """
    z = math.log10(float(ds))
    problem, sim = build_problem(
        observation, output_root=Path(output_root), audit_dir=Path(audit_dir),
        z_bounds=z_bounds, z_initial=z, replay_case=replay_case,
    )
    cost = float(np.ravel(np.asarray(problem.evaluate({Z_NAME: z}).values))[0])
    n_points = int(len(observation.time_s))
    rec = sim.records[-1] if sim.records else None
    return {
        "ds": float(ds),
        "z": float(z),
        "cost": cost,
        "fit_rms_mV": (math.sqrt(cost / n_points) * 1000.0
                       if np.isfinite(cost) and n_points else None),
        "n_points": n_points,
        "coverage": (rec.overlap_fraction if rec else None),
        "status": (rec.status if rec else "no_record"),
        "replay_model": sim.case.model_name,
        "truth_model": sim.truth_case.model_name,
        "audit_path": str(Path(audit_dir)),
    }
