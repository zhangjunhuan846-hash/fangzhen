"""G6 capability gate: can a FUNCTION-VALUED parameter be overridden at all?

G5 identified a scalar.  Graphite's ``Positive particle diffusivity`` is a
callable, so G6 cannot even start until a callable can be pushed through the
platform's override API, actually change the trajectory, and be recorded.

Three things are tested, in increasing order of strictness:

  1. ACCEPTED      -- the platform's override loop writes the callable and the
                      run completes.
  2. ACTIVE        -- the callable actually changes V(t) relative to the
                      reference function.  A parameter can be accepted and
                      consumed and still be numerically inert; this platform
                      has been bitten by exactly that before.
  3. AUDITABLE     -- the provenance record survives.  ``applied_overrides``
                      is written to run_metadata.json, and a callable is not
                      JSON-serialisable, so this is the most likely failure.

Usage (inside the pybamm env):
    python scripts/graphite/probe_callable_override.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pybamm

from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import run_baseline_cell

DATASET = "sintef_graphite"
CELL = None      # resolved from the adapter's own catalogue
RATE = None      # ditto -- do not hard-code names that may not exist
KEY = "Positive particle diffusivity [m2.s-1]"


def run_once(adapter, key, value, source=None):
    """Public entry point: the adapter supplies the half-cell configuration."""
    res = run_baseline_cell(
        adapter,
        "SPM",
        CELL,
        rate=RATE,
        parameter_set="Ecker2015_graphite_halfcell",
        plot=False,
        quiet=True,
        parameter_overrides={key: value},
        parameter_override_sources=({key: source} if source else None),
    )
    m = res.get("metrics")
    rms = None
    try:
        if m is not None and len(m):
            rms = float(m.iloc[0]["rmse_time_aligned_mV"])
    except Exception:  # noqa: BLE001
        rms = None
    return res, rms


def main() -> int:
    global CELL, RATE
    adapter = get_dataset(DATASET)
    # The adapter does not expose plain ``cells``/``rates`` attributes, so the
    # names come from configs/datasets.yaml (p-OCV cell 4ccc47, rate pOCV-deli)
    # rather than from an invented attribute that silently returns empty.
    CELL = CELL or "4ccc47"
    RATE = RATE or "pOCV-deli"
    pv = pybamm.ParameterValues("Ecker2015_graphite_halfcell")
    ref = pv[KEY]
    print("=" * 78)
    print("G6 capability gate -- function-valued parameter override")
    print("=" * 78)
    print(f"  dataset : {DATASET}   cell {CELL}   rate {RATE}")
    print(f"  key     : {KEY}")
    print(f"  reference: {type(ref).__name__} {getattr(ref, '__name__', '')}")
    if callable(ref):
        import inspect as _insp
        try:
            sig = str(_insp.signature(ref))
        except Exception:  # noqa: BLE001
            sig = "(?)"
        print(f"  reference SIGNATURE : {sig}")
        try:
            print(f"  ref(0.5, 298.15) = {float(ref(0.5, 298.15)):.6e}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ref call failed: {exc}")
    else:
        print(f"  ref = {ref!r}")

    # ---- condition 1 + 2: accepted and active ---------------------
    print()
    print("-- 1/2. accepted + numerically active ------------------------")
    results = {}
    for a0 in (0.0, 0.5, -0.5):
        scale = 10.0 ** a0

        # The reference is f(stoichiometry, temperature): forward ALL
        # positional arguments rather than just the first, so the wrapper
        # does not silently drop a dependence the model relies on.
        def scaled(*args, _scale=scale, _ref=ref):
            return _scale * _ref(*args)

        scaled.__name__ = f"graphite_diffusivity_scaled_1e{a0:+.1f}"

        try:
            res, rms = run_once(adapter, KEY, scaled)
            results[a0] = {"ok": True, "rmse": rms}
            print(f"   a0={a0:+.1f}  scale={scale:8.4f}  ->  ran, "
                  f"RMSE = {'n/a' if rms is None else f'{rms:.4f} mV'}")
        except Exception as exc:  # noqa: BLE001
            results[a0] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(f"   a0={a0:+.1f}  ->  FAILED: {type(exc).__name__}: "
                  f"{str(exc)[:150]}")

    ok = [v for v in results.values() if v["ok"]]
    if len(ok) == 3:
        rms = [v["rmse"] for v in ok]
        spread = max(rms) - min(rms) if all(r is not None for r in rms) else None
        print(f"   -> accepted on all three; RMSE spread "
              f"{'n/a' if spread is None else f'{spread:.4f} mV'}")
        print(f"   -> ACTIVE: {bool(spread and spread > 0.05)}")
    print()

    # ---- condition 3: auditability --------------------------------
    print("-- 3. auditable (the metadata JSON must survive) -------------")
    out_dirs = []
    try:
        res, _ = run_once(adapter, KEY, (lambda *a: 1.2 * ref(*a)),
                          source={"source": "gate probe"})
        out_dirs.append(res["output_dir"])
        meta = Path(res["output_dir"]) / "run_metadata.json"
        print(f"   run completed, output_dir = {res['output_dir']}")
        if meta.is_file():
            txt = meta.read_text(encoding="utf-8")
            d = json.loads(txt)
            ap = d.get("_applied_overrides") or d.get("applied_overrides")
            print(f"   run_metadata.json present, applied_overrides = {str(ap)[:160]}")
        else:
            print("   run_metadata.json MISSING")
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {str(exc)[:300]}")

    print()
    print("=" * 78)
    print("verdict")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
