# ============================================================
# Phase A2 — Residual-guided Targeted Sensitivity
# Common definitions: representative runs + parameter set.
#
# Platform v0.4 + Atlas A1 are FROZEN.  This phase never
# modifies battery_sim/ scientific logic (read-only imports).
# No fitting anywhere in A2.
#
# Representative runs (6, per the Phase A2 brief; rationale in
# docs/targeted_sensitivity_A2.md).  NOT expanded to all 18 runs.
#   chen2020/02/C0p5   exact (A); CC;  bias + late-discharge error
#                       (legacy rate label "C2" == C/2)
#   chen2020/02/C1p5   exact (A); CC;  counter-example: low late error
#   calce_cs2/33/C0p5  surrogate (B); CC; bias dominated
#   calce_20r/2/DST_50SOC  surrogate (B); dynamic; 50% SOC
#   calce_20r/2/DST_80SOC  surrogate (B); dynamic; 80% SOC
#                          (initial-state / domain contrast)
#   calce_a123/008/FUDS  ONE A123 dynamic representative, chosen
#                          from the frozen A1 atlas as the A123
#                          window with the MOST PRONOUNCED dynamic
#                          residual (see A123_SELECTION below).
#
# Revision note (2026-09-08): the first A2 round covered 7 runs
# (it also carried calce_a123/007/DST and 008/DST and was archived
# to _archive_7run/).  The Phase A2 brief fixes the panel at 6 runs
# and asks for ONE A123 representative -> 008/FUDS replaces the two
# A123 DST runs.  Perturbation machinery, delta and metrics are
# unchanged.
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
    ("calce_a123", "008", "FUDS"): "A123 008 FUDS",
}

# Evidence for the A123 representative choice, read DIRECTLY from the
# frozen A1 atlas (outputs/analysis/residual_atlas/decomposition.csv).
# "dynamic residual" = the non-bias part of the residual; ranked by
# (a) dynamic_residual_component = share of RMSE^2 that is NOT bias
# and (b) residual_std_mV = absolute size of that non-bias part.
# Both criteria pick the same window -> choice is not threshold-tuned.
A123_SELECTION = {
    "chosen": "calce_a123/008/FUDS",
    "criterion": (
        "largest dynamic (non-bias) residual among the six A123 "
        "dynamic windows, on BOTH the relative share and the "
        "absolute magnitude"
    ),
    "candidates": {
        # window: (dynamic_residual_component, residual_std_mV, RMSE_mV)
        "calce_a123/007/DST": (0.6725, 163.756, 199.686),
        "calce_a123/007/FUDS": (0.6924, 164.860, 198.120),
        "calce_a123/007/US06": (0.5888, 135.485, 176.559),
        "calce_a123/008/DST": (0.6802, 174.498, 211.576),
        "calce_a123/008/FUDS": (0.6960, 189.132, 226.699),
        "calce_a123/008/US06": (0.5986, 161.719, 209.031),
    },
    "source": "outputs/analysis/residual_atlas/decomposition.csv (A1)",
    "note": (
        "surrogate (B) parameter match (Prada2013 <-> LFP): the A123 "
        "block is a model-structure probe, NOT a validation"
    ),
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
    "calce_a123/008/FUDS": (
        "surrogate (B) dynamic LFP; chosen from the A1 atlas as the "
        "A123 window with the most pronounced DYNAMIC residual: "
        "dynamic component 0.696 (max of the six A123 dynamic "
        "windows) and residual_std 189.13 mV (also max); "
        "bias_fraction only 0.304 -> the error is dominated by the "
        "dynamic, not the offset, part"
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
