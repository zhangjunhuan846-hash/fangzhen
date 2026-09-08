# ============================================================
# H7 debug - inspect _find_window run boundaries for Cover10
# ============================================================
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset  # noqa: E402

adapter = get_dataset("birmingham_ncm920305")

raw = adapter._load_raw_file(adapter._raw_path("Cover10"))
print(f"raw n={len(raw)}")

I = raw["current_A"].to_numpy(float)
V = raw["voltage_V"].to_numpy(float)
t = raw["time_s"].to_numpy(float)
peak = float(np.abs(I).max())
thr = 0.02 * peak
active = np.abs(I) >= thr

# list contiguous active runs (start idx, end idx, len, V at end)
runs = []
cur = None
for i, a in enumerate(active):
    if a and cur is None:
        cur = [i, i]
    elif a:
        cur[1] = i
    elif cur is not None:
        runs.append(cur)
        cur = None
if cur is not None:
    runs.append(cur)

print(f"n_runs={len(runs)}  threshold={thr:.2e} A")
for k, (s, e) in enumerate(runs):
    print(f"  run{k}: idx[{s}:{e}] len={e-s+1} t=[{t[s]:.3f},{t[e]:.3f}] "
          f"I_end={I[e]:.6f} V_end={V[e]:.4f}")

best = max(runs, key=lambda r: r[1] - r[0] + 1)
s0, e0 = best
print(f"\nbest run ends idx={e0} V={V[e0]:.4f}")
# walk backwards for rest
rs = s0
while rs - 1 >= 0 and not active[rs - 1]:
    rs -= 1
print(f"rest_start={rs}  rest points={s0 - rs}  "
      f"V_rest0={V[rs]:.4f} t_rest0={t[rs]:.3f}")
