# ============================================================
# Battery Dataset Simulation Platform v0.1
# Chen2020 command-level protocol
#
# The experiment layout below is reused verbatim from the
# already-validated reference implementation:
#   scripts/runners/command_reproduction.py -> build_experiment()
#
# Command-level CC/CV/rest protocol (NOT open-loop replay).
#
# Cycle layout (solution.cycles index in parentheses):
#   0: conditioning + first full CC-CV charge
#      Rest 30 min
#      Discharge 0.5 A -> 2.5 V
#      Rest 2 h
#      Charge 1.5 A -> 4.2 V
#      CV 4.2 V -> 0.05 A
#      Rest 2 h
#   1 (idx 1): C10 validation discharge (tagged C10_discharge) + recharge
#   2 (idx 2): C2  validation discharge (tagged C2_discharge)  + recharge
#   3 (idx 3): 1C  validation discharge (tagged 1C_discharge)  + recharge
#   4 (idx 4): 1p5C validation discharge (tagged 1p5C_discharge), no recharge
#
# Current levels: C10=0.5 A, C2=2.5 A, 1C=5.0 A, 1p5C=7.5 A.
# ============================================================

from __future__ import annotations

import pybamm

# Rate -> 0-based solution cycle index (conditioning = 0)
RATE_CYCLE_INDEX = {
    "C10": 1,
    "C2": 2,
    "1C": 3,
    "1p5C": 4,
}

# Rate -> nominal discharge current (A)
RATE_CURRENT_A = {
    "C10": 0.5,
    "C2": 2.5,
    "1C": 5.0,
    "1p5C": 7.5,
}


def tagged_step(text: str, tag: str):
    """Return a pybamm experiment step tagged for later extraction."""
    return pybamm.step.string(
        text,
        period="10 seconds",
        tags=[tag],
    )


def build_experiment() -> pybamm.Experiment:
    """
    Full Chen2020 command-level experiment as a pybamm.Experiment.

    This is the formal reproduction protocol for the platform.
    """
    #
    # Cycle 0: initial conditioning + first full CC-CV charge
    #
    conditioning = (
        "Rest for 30 minutes",
        "Discharge at 0.5 A until 2.5 V",
        "Rest for 2 hours",
        "Charge at 1.5 A until 4.2 V",
        "Hold at 4.2 V until 0.05 A",
        "Rest for 2 hours",
    )

    #
    # Cycle 1: C/10 validation + recharge
    #
    c10 = (
        tagged_step(
            "Discharge at 0.5 A until 2.5 V",
            "C10_discharge",
        ),
        "Rest for 2 hours",
        "Charge at 1.5 A until 4.2 V",
        "Hold at 4.2 V until 0.05 A",
        "Rest for 2 hours",
    )

    #
    # Cycle 2: C/2
    #
    c2 = (
        tagged_step(
            "Discharge at 2.5 A until 2.5 V",
            "C2_discharge",
        ),
        "Rest for 2 hours",
        "Charge at 1.5 A until 4.2 V",
        "Hold at 4.2 V until 0.05 A",
        "Rest for 2 hours",
    )

    #
    # Cycle 3: 1C
    #
    c1 = (
        tagged_step(
            "Discharge at 5 A until 2.5 V",
            "1C_discharge",
        ),
        "Rest for 2 hours",
        "Charge at 1.5 A until 4.2 V",
        "Hold at 4.2 V until 0.05 A",
        "Rest for 2 hours",
    )

    #
    # Cycle 4: 1.5C (no recharge)
    #
    c15 = (
        tagged_step(
            "Discharge at 7.5 A until 2.5 V",
            "1p5C_discharge",
        ),
        "Rest for 2 hours",
    )

    return pybamm.Experiment(
        [
            conditioning,
            c10,
            c2,
            c1,
            c15,
        ],
        period="10 seconds",
    )
