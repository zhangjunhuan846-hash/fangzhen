"""List every key in the graphite half-cell parameter set, with its value.

Companion to dump_graphite_parameters.py: that one groups the keys the audit
cares about, this one shows ALL of them, because the half-cell set does not
use the same key names as a full-cell set and a grouped dump can therefore
report "ABSENT" for a parameter that is actually present under another name.
"""
from __future__ import annotations

import pybamm

PARAMETER_SET = "Ecker2015_graphite_halfcell"


def main() -> int:
    pv = pybamm.ParameterValues(PARAMETER_SET)
    keys = sorted(pv.keys())
    print(f"parameter set : {PARAMETER_SET}")
    print(f"total keys    : {len(keys)}")
    print()
    for k in keys:
        v = pv[k]
        if callable(v):
            print(f"  {k:66s} CALLABLE {getattr(v, '__name__', '')}")
        else:
            print(f"  {k:66s} {repr(v)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
