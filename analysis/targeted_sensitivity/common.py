# ============================================================
# Phase A2 — Residual-guided Targeted Sensitivity
# Common definitions: representative runs + parameter set.
#
# Platform v0.4 + Atlas A1 are FROZEN.  This phase never
# modifies battery_sim/ scientific logic (read-only imports).
# No fitting anywhere in A2.
#
# Representative runs (rationale in docs/targeted_sensitivity_A2.md):
#   chen2020/02/C0p5   exact (A); CC;  bias + late-discharge error
#                       (legacy rate label "C2" == C/2)
#   chen2020/02/C1p5   exact (A); CC;  counter-example: low late error
#   calce_cs2/33/C0p5  surrogate (B); CC; bias dominated
#   calce_20r/2/DST_50SOC  surrogate (B); dynamic; 50% SOC
#   calce_20r/2/DST_80SOC  surrogate (B); dynamic; 80% SOC
#                          (initial-state / domain contrast)
#   calce_a123/007/DST surrogate (B); dynamic; LFP
#   calce_a123/008/DST added ONLY because the 007 vs 008 residual
#                          shapes differ clearly (|r| < 0.5 on an
#                          elapsed-fraction grid for DST/FUDS/US06)
#
# First round parameter block (already-validated perturbation
# machinery, keys from configs/sensitivity.yaml):
#   Dsn Dsp j0n j0p De kappa_e Rn Rp brug_e
# Central-difference factor: delta = 0.20 (both signs).
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

from residual_atlas import available_runs  # noqa: E402


DELTA = 0.20
FACTORS = (1.0 - DELTA, 1.0 + DELTA)

# The nine first-round dynamic parameters (validated machinery).
PARAMETERS = [
    "Dsn", "Dsp", "j0n", "j0p", "De", "kappa_e", "Rn", "Rp", "brug_e",
]

# Selected (dataset, cell, rate_slug) triples -> short plot label.
SELECTED = {
    ("chen2020", "02", "C0p5"): "Chen2020 C2(C/2)",
    ("chen2020", "02", "C1p5"): "Chen2020 1p5C",
    ("calce_cs2", "33", "C0p5"): "CS2_33 0.5C",
    ("calce_20r", "2", "DST_50SOC"): "20R DST 50SOC",
    ("calce_20r", "2", "DST_80SOC"): "20R DST 80SOC",
    ("calce_a123", "007", "DST"): "A123 007 DST",
    ("calce_a123", "008", "DST"): "A123 008 DST",
}

SELECTION_RATIONALE = {
    "chen2020/02/C0p5": (
        "exact (A) CC; strongest bias + late-discharge rise in the "
        "exact block (RMSE 123.88, Bias 93.49 mV)"
    ),
    "chen2020/02/C1p5": (
        "exact (A) CC; internal counter-example with LOW late-error "
        "(RMSE 48.04 mV) -> different residual structure"
    ),
    "calce_cs2/33/C0p5": (
        "surrogate (B) CC; bias dominated (bias_fraction 0.78)"
    ),
    "calce_20r/2/DST_50SOC": (
        "surrogate (B) dynamic; 50% SOC window (Bias 134 mV)"
    ),
    "calce_20r/2/DST_80SOC": (
        "surrogate (B) dynamic; 80% SOC window (Bias 263 mV, ~2x "
        "50SOC) -> initial-state/domain contrast"
    ),
    "calce_a123/007/DST": (
        "surrogate (B) dynamic LFP; dynamic-residual-component "
        "regime (0.67)"
    ),
    "calce_a123/008/DST": (
        "second A123 cell added: 007 vs 008 residual shapes differ "
        "clearly (fraction-grid corr DST 0.44 < 0.5); "
        "largest DST dynamic component (0.68)"
    ),
}


def selected_runs() -> list[dict]:
    """Subset of the frozen atlas registry for the A2 first round."""
    chosen = []
    for run in available_runs():
        key = (run["dataset"], run["cell"], run["rate_slug"])
        if key in SELECTED:
            run = dict(run)
            run["label"] = SELECTED[key]
            run["run_id"] = "/".join(
                (run["dataset"], run["cell"], run["rate_slug"])
            )
            run["rationale"] = SELECTION_RATIONALE[run["run_id"]]
            chosen.append(run)
    chosen.sort(key=lambda r: r["run_id"])
    return chosen
