"""Parameter identification on top of the frozen platform kernel.

Scope discipline (G5.0): this package answers ONE question --

    given a synthetic voltage response generated at a known D_s, can the
    current pipeline find that D_s back?

It deliberately does NOT touch the platform's runner / evaluator / factory /
registry / rates / paths, and it does not add curve-valued parameters, extra
models, or agent hooks.  Those come later, if and when G5.0 passes.

Public surface::

    from identification.forward import build_problem, DS_KEY, Z_NAME
    from identification.synthetic import generate
"""

from identification.forward import (  # noqa: F401
    DS_KEY,
    DOMAIN,
    TARGET,
    Z_NAME,
    EvaluationRecord,
    Observation,
    ReplayCase,
    build_problem,
    make_replay_simulator,
    replay,
)

__all__ = [
    "DS_KEY",
    "DOMAIN",
    "TARGET",
    "Z_NAME",
    "EvaluationRecord",
    "Observation",
    "ReplayCase",
    "build_problem",
    "make_replay_simulator",
    "replay",
]
