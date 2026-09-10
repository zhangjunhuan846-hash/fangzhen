#!/usr/bin/env python3
# ============================================================
# Phase B1.6 probe: what does the fit FORM do to the sqrt(t) slope?
#
# Phase B1.5 measured, on model-generated pulses of this very protocol,
# that a first-order V = a + m*sqrt(t) fit inflates the diffusion slope
# by a median 2.9x, because the equilibrium voltage drifts linearly
# while the pulse is on.  This probe makes that statement analytic:
# generate V = a + b*t + m*sqrt(t) with a KNOWN m, fit both forms, and
# report the recovered slopes and the implied diffusivity bias.
#
# D scales with m^2 and inversely, so a slope inflated by k biases
# D low by k^2.  Nothing here is fitted to the SINTEF data: it is a
# property of the two regression forms, which is why it can be stated
# before the real pulses are re-reduced.
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.gitt_extractor import (  # noqa: E402
    _fit_quadratic_sqrt_t,
    _fit_sqrt_t,
)

PULSE_S = 1800.0        # the SINTEF GITT pulse length
IR_SKIP_S = 60.0        # the ohmic/initial transient that is dropped
DT_S = 1.0              # the pulse channel logs at 1 s

# the drift expected over one pulse: the pulse moves the bulk
# stoichiometry by ~3.6% SOC (Phase B1 protocol), and the frozen OCP
# is O(1) V per unit SOC, so the equilibrium voltage moves by a few
# tens of mV across the pulse -- that is the term the first-order fit
# has nowhere to put.
DRIFT_PER_PULSE_V = -0.03


def main() -> int:
    t = np.arange(0.0, PULSE_S + DT_S, DT_S)
    b_true = DRIFT_PER_PULSE_V / PULSE_S
    print(f"pulse {PULSE_S:.0f} s, fit window t >= {IR_SKIP_S:.0f} s, "
          f"analytical drift {DRIFT_PER_PULSE_V * 1e3:+.1f} mV over the pulse")
    print()
    print(f"{'m_true':>12} {'m (1st order)':>15} {'m (2nd order)':>15} "
          f"{'inflation':>10} {'D bias (1st)':>13} {'D bias (2nd)':>13}")
    for m_true in (5e-4, 2e-3, 8e-3):
        v = 0.30 + b_true * t + m_true * np.sqrt(t)
        f1 = _fit_sqrt_t(t, v, IR_SKIP_S)
        f2 = _fit_quadratic_sqrt_t(t, v, IR_SKIP_S)
        k1 = f1["slope"] / m_true
        k2 = f2["sqrt_slope"] / m_true
        print(f"{m_true:12.3e} {f1['slope']:15.6e} {f2['sqrt_slope']:15.6e} "
              f"{k1:10.4f} {1.0 / k1 ** 2:13.4f} {1.0 / k2 ** 2:13.4f}")
    print()
    print("D is recovered as tau_d = pi*(3 Q_th m / (2 I U'))^2 and D = R^2/tau_d,")
    print("so an over-estimated m over-estimates tau_d and under-estimates D by m^2.")
    print("Both fits are applied to the SAME samples of the SAME pulse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
