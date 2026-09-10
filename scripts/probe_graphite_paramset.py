"""Inspect the built-in Ecker2015_graphite_halfcell set: keys + OCP direction."""
import pybamm

ps = pybamm.ParameterValues("Ecker2015_graphite_halfcell")

keys = [k for k in ps.keys() if any(
    s in k for s in ("Initial concentration", "Maximum concentration",
                     "OCP", "cut-off", "Nominal cell capacity",
                     "Electrode height", "Electrode width", "Typical current",
                     "Initial temperature", "Ambient temperature",
                     "Lower voltage", "Upper voltage", "Electrode thickness",
                     "Active material volume fraction", "Porosity")
)]
for k in keys:
    v = ps[k]
    if callable(v):
        print(f"  {k}: <callable {getattr(v, '__class__', type(v)).__name__}>")
    else:
        print(f"  {k}: {v}")

print()
print("=== 石墨 OCP 文件（Ecker2015 half-cell 用的那个）===")
import numpy as np
for k in ps.keys():
    if "OCP" in k and "negative" in k.lower():
        v = ps[k]
        if isinstance(v, pybamm.Interpolant):
            x = np.asarray(v.x[0], dtype=float)
            y = np.asarray(v.y[0], dtype=float)
            print(f"  {k}: n={len(x)} | stoich {x.min():.4f}..{x.max():.4f} "
                  f"| V {y.min():.4f}..{y.max():.4f}")
            order = np.argsort(x)
            xs, ys = x[order], y[order]
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                i = int(frac * (len(xs) - 1))
                print(f"     x={xs[i]:.3f} -> V={ys[i]:.4f}")
        else:
            print(f"  {k}: {type(v).__name__}")
print()
print("Li 对电极相关键：")
for k in ps.keys():
    if "lithium" in k.lower() and ("counter" in k.lower() or "Initial concentration" in k):
        print(f"  {k}: {ps[k] if not callable(ps[k]) else '<callable>'}")
