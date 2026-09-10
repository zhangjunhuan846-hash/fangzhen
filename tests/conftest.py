# ============================================================
# Battery Dataset Simulation Platform v0.1
# pytest shared setup
#
# Makes the project root importable regardless of the pytest
# invocation directory (works on native Windows and inside WSL).
# ============================================================

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True, scope="session")
def _isolate_platform_outputs(tmp_path_factory):
    """
    Keep pytest from rewriting the TRACKED runs under outputs/platform/.

    Several tests re-run the public pipeline to compare against the frozen
    metrics.  Those runs land in outputs/platform/<dataset>/... and only
    differ in runtime/timestamp, so every test session used to leave the
    working tree dirty and every commit needed a
    ``git checkout -- outputs/platform/`` first.

    The run directory is resolved from ``battery_sim.paths``, so for the
    whole session the root is repointed at a throwaway directory.  Two
    things must be patched: ``paths.PLATFORM_OUTPUT_ROOT`` (read at call
    time by ``platform_output_dir``) and the by-value copy that
    ``simulation/benchmark.py`` took at import.

    Nothing in the frozen platform is modified: only the value of a module
    attribute is swapped, for the duration of the session.
    """
    import battery_sim.paths as paths

    target = tmp_path_factory.mktemp("platform_outputs")
    patched = []

    def _patch(module, name, value):
        if hasattr(module, name):
            patched.append((module, name, getattr(module, name)))
            setattr(module, name, value)

    _patch(paths, "PLATFORM_OUTPUT_ROOT", target)
    try:
        from battery_sim.simulation import benchmark
    except Exception:                       # pragma: no cover - import guard
        benchmark = None
    if benchmark is not None:
        _patch(benchmark, "PLATFORM_OUTPUT_ROOT", target)

    yield target

    for module, name, old in patched:
        setattr(module, name, old)

