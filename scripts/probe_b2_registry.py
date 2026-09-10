#!/usr/bin/env python3
"""
Set-id integrity check for the constant-D sensitivity lattice.

Phase B2 first shipped a branch-LESS set id, so the lithiation and the
delithiation lattice both resolved to ``..._Dsweep_<D>_v2`` and the
second branch silently overwrote the first.  The lithium window then ran
on the DELITHIATION OCP, which extrapolates to ~4.5 V outside its own
table and tripped the solver's Maximum-voltage event at t = 0.

This script is the standing guard for that failure mode: it registers the
lattice, asserts every (branch, D) id is distinct, and proves that each
id resolves to the OCP of ITS OWN branch by evaluating the curve at fixed
stoichiometries.

    python scripts/probe_b2_registry.py

Exits non-zero if any id collides or resolves to the wrong branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
SUFFIX = "_v2"
CELL = "4ccc47"
OCP = "Positive electrode OCP [V]"
XS = (0.001, 0.01, 0.2, 0.9)
BRANCHES = ("lithiation", "delithiation")
VALUES = (1e-14, 1e-16)

from parameters.sintef_graphite_ds_sweep import (          # noqa: E402
    KEY_DIFFUSIVITY,
    branch_token,
    register_constant_d_sweep,
)
from parameters.sintef_graphite_geometry import (           # noqa: E402
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (                # noqa: E402
    _ocp_function,
    load_ocp_tables,
    register_variants,
)

import pybamm                                               # noqa: E402


def evaluate(fn, xs=XS):
    out = []
    for x in xs:
        node = fn(x)
        out.append(round(float(np.asarray(
            node.evaluate() if hasattr(node, "evaluate") else node
        ).reshape(-1)[0]), 6))
    return out


def _as_float(entry) -> float:
    return float(np.asarray(entry.evaluate()).reshape(-1)[0]) \
        if hasattr(entry, "evaluate") else float(entry)


def main() -> int:
    if not V2_DIR.is_dir():
        print(f"SKIP: frozen OCP v2 tables not present at {V2_DIR}")
        return 0

    register_geometry(CELL)
    register_variants(CELL, V2_DIR, set_id_suffix=SUFFIX)
    ids = register_constant_d_sweep(
        CELL, values=VALUES, ocp_dir=V2_DIR, set_id_suffix=SUFFIX,
    )

    print(f"registered {len(ids)} sets")
    for (br, d), sid in sorted(ids.items()):
        print(f"  ({br:13s}, {d:8.2e}) -> {sid}")

    if len(set(ids.values())) != len(ids):
        print("FAIL: duplicate set ids -- branches would overwrite each other")
        return 1
    print("OK: every (branch, D) id is distinct")

    # branch correctness: each id must resolve to its OWN branch's OCP
    tables = load_ocp_tables(V2_DIR)
    expected = {}
    for br in BRANCHES:
        srt = tables[br].sort_values("SOC")
        ocp, _soc, _v = _ocp_function(
            srt["SOC"].to_numpy(float), srt["Voltage"].to_numpy(float)
        )
        expected[br] = evaluate(ocp)
    print(f"  expected OCP at x={XS}: {expected}")

    failed = False
    for (br, d), sid in sorted(ids.items()):
        pv = pybamm.ParameterValues(sid)
        got = evaluate(pv[OCP])
        ok = all(abs(a - b) < 1e-6 for a, b in zip(got, expected[br]))
        print(f"  {sid}: token={branch_token(br)!r} "
              f"D={_as_float(pv[KEY_DIFFUSIVITY]):.3e} OCP={got} "
              f"{'ok' if ok else 'WRONG BRANCH'}")
        failed |= not ok

    if failed:
        print("FAIL: at least one id resolved to the wrong branch's OCP")
        return 1
    print("OK: every id resolves to its own branch's OCP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
