"""G6.0 -- dump the graphite parameter set so its provenance can be audited.

Produces the "current value" column of the provenance table.  Nothing here
interprets the values; the point is to have an exact, reproducible list of
what the model actually uses, so that every row can then be traced to a
measurement, a paper, a fit, or an assumption.

Usage (inside the pybamm env):
    python scripts/graphite/dump_graphite_parameters.py
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pybamm

PARAMETER_SET = "Ecker2015_graphite_halfcell"
OUT = Path("outputs/graphite/g6_0_parameter_set.json")

#: Grouped the way the audit is meant to be read, not alphabetically.
GROUPS = {
    "geometry": [
        "Negative electrode thickness [m]",
        "Electrode height [m]",
        "Electrode width [m]",
        "Separator thickness [m]",
    ],
    "composition": [
        "Negative electrode porosity",
        "Negative electrode active material volume fraction",
        "Separator porosity",
        "Negative electrode density [kg.m-3]",
    ],
    "particle": [
        "Negative particle radius [m]",
        "Negative particle diffusivity [m2.s-1]",
        "Maximum concentration in negative electrode [mol.m-3]",
        "Initial concentration in negative electrode [mol.m-3]",
    ],
    "kinetics": [
        "Negative electrode exchange-current density [A.m-2]",
        "Negative electrode charge transfer coefficient",
        "Negative electrode double-layer capacity [F.m-2]",
    ],
    "thermodynamics": [
        "Negative electrode OCP [V]",
        "Negative electrode OCP entropic change [V.K-1]",
    ],
    "transport": [
        "Negative electrode conductivity [S.m-1]",
        "Negative electrode Bruggeman coefficient (electrolyte)",
        "Negative electrode Bruggeman coefficient (electrode)",
        "Separator Bruggeman coefficient (electrolyte)",
    ],
    "thermal": [
        "Negative electrode specific heat capacity [J.kg-1.K-1]",
        "Negative electrode thermal conductivity [W.m-1.K-1]",
        "Ambient temperature [K]",
        "Initial temperature [K]",
    ],
    "protocol": [
        "Typical current [A]",
        "Typical cell capacity [A.h]",
        "Lower voltage cut-off [V]",
        "Upper voltage cut-off [V]",
    ],
}


def describe(v):
    """Value, plus the identity of a callable so a function parameter is visible."""
    if callable(v):
        name = getattr(v, "__name__", "")
        mod = getattr(v, "__module__", "")
        try:
            src = inspect.getsourcefile(v)
        except Exception:  # noqa: BLE001
            src = None
        return {"kind": "callable", "name": name, "module": mod,
                "source_file": src}
    return {"kind": type(v).__name__, "value": v}


def main() -> int:
    pv = pybamm.ParameterValues(PARAMETER_SET)
    rows = {}
    for group, keys in GROUPS.items():
        rows[group] = {}
        for k in keys:
            try:
                rows[group][k] = describe(pv[k])
            except Exception:  # noqa: BLE001
                rows[group][k] = {"kind": "ABSENT"}

    # everything else, so nothing is silently out of scope
    listed = {k for ks in GROUPS.values() for k in ks}
    others = {}
    for k in sorted(pv.keys()):
        if k in listed:
            continue
        try:
            others[k] = describe(pv[k])
        except Exception:  # noqa: BLE001
            others[k] = {"kind": "ERROR"}
    rows["_not_grouped"] = others

    payload = {
        "gate": "G6.0",
        "purpose": ("exact list of what the graphite model consumes, as the "
                    "input to a per-parameter provenance audit"),
        "parameter_set": PARAMETER_SET,
        "pybamm_version": pybamm.__version__,
        "n_parameters": len(pv),
        "groups": rows,
        "note": ("values only; NO provenance is claimed here. Every row still "
                 "has to be traced to a measurement / paper / fit / "
                 "assumption"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")

    print(f"parameter set : {PARAMETER_SET}  (pybamm {pybamm.__version__})")
    print(f"n parameters  : {len(pv)}")
    print(f"written       : {OUT}")
    for group, ks in GROUPS.items():
        print(f"\n[{group}]")
        for k in ks:
            d = rows[group][k]
            if d["kind"] == "callable":
                print(f"   {k:62s} CALLABLE {d['name']}")
            elif d["kind"] == "ABSENT":
                print(f"   {k:62s} -- ABSENT --")
            else:
                print(f"   {k:62s} {d['value']!r}")
    print(f"\n[{len(others)} other keys written to the json]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
