"""Capability gate: is particle_radius actually usable for identification?

Before a joint D_s-R_p study can mean anything, three things must hold for
the SECOND parameter:

  1. it EXISTS in the parameter set in use;
  2. it is CONSUMED by the model (the number reaches the equations);
  3. it is NUMERICALLY ACTIVE -- perturbing it moves the solution, by enough
     to be identifiable rather than by solver noise.

Condition 2 alone is not enough, as this platform learnt earlier: a
deletion probe says SPM "resolves" electrode porosity, yet overriding it
changes nothing.  Only a measured change in the solution counts.

Measured on chen2020 / cell 02, both models, with the platform's own runner.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.baseline import _run_one_replay  # noqa: E402

RADIUS = "Positive particle radius [m]"
DIFFUS = "Positive particle diffusivity [m2.s-1]"
CELL, DATASET = "02", "chen2020"
RATES = ("C10", "C2", "1C", "1p5C")

import pybamm  # noqa: E402

pv = pybamm.ParameterValues("Chen2020")
r_nom = float(pv[RADIUS])
d_nom = float(pv[DIFFUS])

print("=" * 78)
print("condition 1  existence in the parameter set")
print("=" * 78)
print(f"  {RADIUS}")
print(f"     present : {RADIUS in pv}")
print(f"     type    : {type(pv[RADIUS]).__name__}")
print(f"     nominal : {r_nom:.6e} m  ({r_nom*1e6:.3f} um)")
print(f"  {DIFFUS}")
print(f"     nominal : {d_nom:.6e} m2/s")
print(f"  tau_d = R^2/D = {r_nom**2/d_nom:.3f} s")

print()
print("=" * 78)
print("conditions 2+3  consumed AND numerically active")
print("=" * 78)
adapter = get_dataset(DATASET)


def rmse(rate, model, key=None, factor=1.0):
    overrides = None
    if key is not None:
        nom = r_nom if key == RADIUS else d_nom
        overrides = {key: nom * factor}
    df = adapter.load_processed_discharge(CELL, rate)
    res = _run_one_replay(
        df, model_name=model, parameter_set="Chen2020",
        model_options=None, parameter_overrides=overrides,
    )
    return float(res["rmse_time_aligned_mV"])


rows = []
for model in ("SPM", "SPMe"):
    for rate in RATES:
        base = rmse(rate, model)
        for label, key, factor in (
            ("R_p -20%", RADIUS, 0.8),
            ("R_p +20%", RADIUS, 1.2),
            ("D_s -20%", DIFFUS, 0.8),
        ):
            try:
                v = rmse(rate, model, key, factor)
                d = v - base
                tag = "ACTIVE" if abs(d) > 0.05 else "inert "
                rows.append((model, rate, label, base, v, d, tag))
            except Exception as exc:  # noqa: BLE001
                rows.append((model, rate, label, base, None,
                             None, f"ERR {type(exc).__name__}"))

hdr = f"  {'model':5s} {'rate':6s} {'perturb':9s} {'base':>10s} {'perturbed':>12s} {'delta':>10s}  verdict"
print(hdr)
print("  " + "-" * (len(hdr) - 2))
for model, rate, label, base, v, d, tag in rows:
    if v is None:
        print(f"  {model:5s} {rate:6s} {label:9s} {base:10.4f} {'-':>12s} "
              f"{'-':>10s}  {tag}")
    else:
        print(f"  {model:5s} {rate:6s} {label:9s} {base:10.4f} {v:12.4f} "
              f"{d:+10.4f}  {tag}")

print()
print("=" * 78)
print("can a radius bias be distinguished from a diffusivity bias?")
print("=" * 78)
print("  equal tau_d requires 2*d(log10 R) = d(log10 D),")
print("  so a +/-20 % radius change sits at 2*0.079 = 0.158 dex of D.")
for model in ("SPM", "SPMe"):
    for rate in RATES[:2]:
        b = rmse(rate, model)
        dr = rmse(rate, model, RADIUS, 1.2) - b
        dd = rmse(rate, model, DIFFUS, 10 ** 0.158) - b
        print(f"  {model:5s} {rate:6s}  R_p +20% -> {dr:+8.4f} mV   "
              f"D_s x1.44 (same tau_d) -> {dd:+8.4f} mV")
