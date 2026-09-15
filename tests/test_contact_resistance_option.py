# ============================================================
# `Contact resistance [Ohm]` is numerically active ONLY when the
# `contact resistance` model option is enabled.
#
# This is the cleanest example in the platform of why "consumed" is an
# ambiguous word, and why the capability gate needs five levels rather
# than one:
#
#   representable      yes  -- it is a plain int in Chen2020
#   accepted           yes  -- a scalar override is allowed
#   resolved           yes  -- the model references the key
#   numerically_active NO   -- under the default options
#   numerically_active YES  -- once `contact resistance` is enabled
#
# Measured (Chen2020 / cell 02 / C2, R: 0 -> 0.02):
#
#   model   default options      contact resistance enabled
#   SPM     +0.000000            -37.633371
#   SPMe    +0.000000            -31.699445
#   DFN     +0.000000            -31.660093
#
# Two traps are pinned here as tests, because both cost real time:
#
#   1. The option value must be the STRING "true".  A boolean True is
#      rejected by pybamm with OptionError -- and if that error is
#      swallowed by a broad except, the probe silently "proves" the
#      parameter is inert when nothing was ever enabled.
#   2. The option belongs here, in an ISOLATED fixture, not in
#      configs/datasets.yaml.  That file says how a dataset runs BY
#      DEFAULT; making it carry a capability probe would change what
#      "the Chen2020 baseline" means for every other user of it.
# ============================================================

import pytest

from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _run_one_replay

DATASET = "chen2020"
CELL = "02"
RATE = "C2"
PARAM_SET = "Chen2020"

KEY = "Contact resistance [Ohm]"
R_ZERO = 0.0
R_NONZERO = 0.02

ENABLED = {"contact resistance": "true"}
MODELS = ("SPM", "SPMe", "DFN")


def _replay(model: str, options, overrides=None) -> float:
    """One replay through the real platform path, options given explicitly."""
    adapter = get_dataset(DATASET)
    df = adapter.load_processed_discharge(CELL, RATE)
    res = _run_one_replay(
        df,
        model_name=model,
        parameter_set=PARAM_SET,
        model_options=options,
        parameter_overrides=overrides,
    )
    return float(res["rmse_time_aligned_mV"])


# ------------------------------------------------------------------
# the trap: the option value is a string, not a boolean
# ------------------------------------------------------------------
def test_a_boolean_option_value_is_rejected_by_pybamm():
    """Pin the trap so nobody "fixes" the tests below by using True.

    A boolean silently made an earlier probe inconclusive: the
    OptionError was caught by a broad ``except`` and the run looked
    like a successful no-op, which reads as "the parameter is inert".
    """
    with pytest.raises(Exception) as excinfo:
        _replay("SPM", {"contact resistance": True})
    assert "contact resistance" in str(excinfo.value)


# ------------------------------------------------------------------
# default options: the override is accepted and has NO effect
# ------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS)
def test_under_default_options_the_override_changes_nothing(model):
    """``representable`` and ``accepted`` are not ``numerically_active``."""
    base = _replay(model, None)
    over = _replay(model, None, {KEY: R_NONZERO})
    assert over == base, (
        f"{model}: contact resistance moved the solution under the "
        f"DEFAULT options -- if this starts failing, the default model "
        f"configuration changed and STATUS.md needs updating"
    )


# ------------------------------------------------------------------
# enabled: the SAME override now moves the solution
# ------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS)
def test_with_the_option_enabled_the_override_is_numerically_active(model):
    """The definition test: the value must reach the equation.

    Asserting only that the override is accepted would pass in both
    configurations and prove nothing.  This compares solved results.
    """
    base = _replay(model, ENABLED)
    over = _replay(model, ENABLED, {KEY: R_NONZERO})
    assert over != base, (
        f"{model}: contact resistance is inert even with the option "
        f"enabled -- then the option is not doing what its name says"
    )


@pytest.mark.parametrize("model", MODELS)
def test_the_effect_is_large_enough_to_identify(model):
    """A parameter worth fitting must move the metric MORE than noise.

    When the option is enabled the shift is tens of mV -- far above
    solver noise -- which is what makes R_ohm a plausible member of an
    identification vector, conditional on this option.
    """
    base = _replay(model, ENABLED)
    over = _replay(model, ENABLED, {KEY: R_NONZERO})
    assert abs(over - base) > 1.0


# ------------------------------------------------------------------
# the isolation contract
# ------------------------------------------------------------------
def test_the_option_is_not_in_the_datasets_config():
    """The canonical config must not carry this probe.

    ``configs/datasets.yaml`` expresses how the dataset runs by
    default.  If this ever fails it means the probe leaked into the
    official configuration, changing what "the Chen2020 baseline"
    means for everyone -- and quietly making the tests above pass for
    the wrong reason.
    """
    from pathlib import Path

    import battery_sim.paths as paths

    text = (Path(paths.ROOT) / "configs" / "datasets.yaml").read_text(
        encoding="utf-8"
    )
    # Look only at the chen2020 block.
    start = text.index("chen2020:")
    end = text.index("\ncalce_cs2:", start)
    block = text[start:end]
    assert "contact resistance" not in block, (
        "the contact-resistance probe leaked into the canonical "
        "chen2020 configuration"
    )
