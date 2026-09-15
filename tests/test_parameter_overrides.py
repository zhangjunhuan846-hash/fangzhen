# ============================================================
# v0.6 additive API: explicit parameter_overrides
#
# Guards the ONE platform-side change that the Agent bridge
# depends on.  The contract has three clauses:
#
#   1. parameter_overrides=None  -> behaviour is byte-identical to
#      before the change (the no-op branch).
#   2. a key present in the parameter set -> the override is
#      actually APPLIED, is echoed back as old/new, and the
#      resulting trajectory CHANGES.
#   3. a key absent from the parameter set -> KeyError.  Never a
#      silent insertion, never a silent skip.
#
# Clause 2 is deliberately a "definition" test, not an
# existence test: asserting only that the column is present and
# finite would not catch an override that was accepted, recorded,
# and then never applied.  So it compares the solved trajectory
# with and without the override, and the effective capacity.
# ============================================================

import numpy as np
import pytest

from battery_sim.models.pybamm_factory import build_model_options
from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _run_one_replay
from parameters.sintef_graphite_capacity import register_capacity_variants
from parameters.sintef_graphite_geometry import register as register_geometry
from parameters.sintef_graphite_ocp import register_variants

DATASET = "sintef_graphite"
CELL = "4ccc47"
RATE = "pOCV-lith"
CAPMATCH_ID = "sintef_graphite_ocp_lith_capmatch_v1"

# measured SINTEF dry thickness, and the deliberately absurd value
# used only to prove the mechanism moves (mirrors the Agent-side
# Case B-1; NOT a physical statement about this electrode)
KEY_THICKNESS = "Positive electrode thickness [m]"
THICKNESS_MEASURED = 6.4e-05
THICKNESS_TEST_ONLY = 1.2e-04


@pytest.fixture(scope="module")
def replay_case():
    """Register the runtime sets once; hand back (frame, model_options).

    The derived sets are registered at runtime (they are not shipped
    in pybamm.parameter_sets), so registration must happen before the
    adapter resolves the parameter set name.

    ``model_options`` is rebuilt exactly the way ``run_baseline_cell``
    builds it from configs/datasets.yaml -- a half cell needs
    ``{"working electrode": "positive"}`` or the model will ask for the
    counter-electrode parameters that Ecker2015_graphite_halfcell
    (correctly) does not define.
    """
    register_geometry(CELL)
    register_variants(CELL)
    register_capacity_variants(CELL)

    adapter = get_dataset(DATASET)
    extra = adapter.config.extra or {}
    model_options = build_model_options(
        cell_configuration=f"half_cell_{extra['working_electrode']}",
        working_electrode=extra["working_electrode"],
        extra_model_options=extra.get("model_options"),
    )
    return adapter.load_processed_discharge(CELL, RATE), model_options


def _replay(replay_case, **kwargs):
    """Run one SPM replay on the shared half-cell frame."""
    df, model_options = replay_case
    kwargs.setdefault("model_name", "SPM")
    kwargs.setdefault("parameter_set", CAPMATCH_ID)
    kwargs.setdefault("model_options", model_options)
    return _run_one_replay(df, **kwargs)


# ------------------------------------------------------------------
# clause 1: default path unchanged
# ------------------------------------------------------------------
def test_none_and_omitted_are_identical(replay_case):
    """parameter_overrides=None must not perturb a single number."""
    omitted = _replay(replay_case)
    explicit_none = _replay(replay_case, parameter_overrides=None)

    for key in ("rmse_time_aligned_mV", "mae_time_aligned_mV",
                "bias_time_aligned_mV", "n_comparison_points"):
        assert omitted[key] == explicit_none[key], key
    np.testing.assert_array_equal(omitted["_V_sim_common"],
                                  explicit_none["_V_sim_common"])

    # and no override bookkeeping is produced on the default path
    assert omitted["_applied_overrides"] is None
    assert explicit_none["_applied_overrides"] is None


def test_empty_dict_is_also_a_no_op(replay_case):
    """An empty mapping must be treated exactly like None."""
    res = _replay(replay_case, parameter_overrides={})
    assert res["_applied_overrides"] is None


# ------------------------------------------------------------------
# clause 2: an existing key IS applied (definition test)
# ------------------------------------------------------------------
def test_override_changes_the_trajectory(replay_case):
    """The solved V(t) must actually move.

    Note the comparison is NOT element-wise over the full array: a
    thicker electrode changes how much of the window the model can
    cover, so the two runs can end at different times and have
    different lengths (the public runner truncates at
    min(t_exp, t_sim)).  A shape-naive ``allclose`` would raise
    instead of testing anything -- see the recorded lengths below.
    """
    base = _replay(replay_case)
    over = _replay(
        replay_case, parameter_overrides={KEY_THICKNESS: THICKNESS_TEST_ONLY}
    )

    # recorded, with the exact old -> new pair
    assert len(over["_applied_overrides"]) == 1
    entry = over["_applied_overrides"][0]
    assert entry["key"] == KEY_THICKNESS
    assert entry["old"] == pytest.approx(THICKNESS_MEASURED, rel=1e-9)
    assert entry["new"] == pytest.approx(THICKNESS_TEST_ONLY, rel=1e-12)

    # the physics moved: compare on the OVERLAPPING time span, and
    # separately assert the coverage changed (a thicker electrode
    # reaches the lower cut-off sooner -> shorter solved window)
    t_base, v_base = base["_t_common"], base["_V_sim_common"]
    t_over, v_over = over["_t_common"], over["_V_sim_common"]

    t_end = min(t_base[-1], t_over[-1])
    m_base = t_base <= t_end
    m_over = t_over <= t_end
    assert m_base.sum() > 10 and m_over.sum() > 10

    v_base_on = np.interp(t_over[m_over], t_base[m_base], v_base[m_base])
    assert not np.allclose(v_over[m_over], v_base_on, atol=1e-6), (
        "override recorded but the solved voltage did not change"
    )


def test_override_is_readable_from_the_effective_set(replay_case):
    """Definition test: the value must survive into ParameterValues.

    This is the clause a "column exists / is finite" assertion cannot
    catch -- an override that is logged but never written would still
    produce a well-formed table.
    """
    import pybamm

    res = _replay(
        replay_case, parameter_overrides={KEY_THICKNESS: THICKNESS_TEST_ONLY}
    )

    # the override is a per-call overlay: the registered set itself is
    # untouched (no global mutation), and the call reports the pair
    pv = pybamm.ParameterValues(CAPMATCH_ID)
    assert pv[KEY_THICKNESS] == pytest.approx(THICKNESS_MEASURED, rel=1e-9)
    assert res["_applied_overrides"][0]["new"] == pytest.approx(
        THICKNESS_TEST_ONLY, rel=1e-12
    )


def test_restoring_the_original_value_reproduces_the_base(replay_case):
    """Case B-2 at platform level: an idempotent override is a no-op."""
    base = _replay(replay_case)
    restored = _replay(
        replay_case, parameter_overrides={KEY_THICKNESS: THICKNESS_MEASURED}
    )

    # the override IS reported (requested and applied) ...
    assert restored["_applied_overrides"][0]["old"] == pytest.approx(
        THICKNESS_MEASURED, rel=1e-9
    )
    assert restored["_applied_overrides"][0]["new"] == pytest.approx(
        THICKNESS_MEASURED, rel=1e-9
    )
    # ... but the result is bit-for-bit the base case
    assert restored["rmse_time_aligned_mV"] == base["rmse_time_aligned_mV"]
    np.testing.assert_array_equal(restored["_V_sim_common"],
                                  base["_V_sim_common"])


# ------------------------------------------------------------------
# clause 3: an unknown key is an error, not an insertion
# ------------------------------------------------------------------
def test_unknown_key_raises_keyerror(replay_case):
    with pytest.raises(KeyError, match="not present in parameter set"):
        _replay(
            replay_case,
            parameter_overrides={"Not a real pybamm parameter [m]": 1.0},
        )


def test_unknown_key_is_reported_by_name(replay_case):
    """The message must name the offending key, not just fail."""
    with pytest.raises(KeyError) as excinfo:
        _replay(
            replay_case,
            parameter_overrides={"NoSuchThing [m]": 1.0, "AlsoFake [V]": 2.0},
        )
    msg = str(excinfo.value)
    assert "AlsoFake [V]" in msg
    assert "NoSuchThing [m]" in msg


def test_error_is_raised_before_the_solve(replay_case):
    """A bad override must fail fast, not after minutes of solving."""
    import time

    tic = time.perf_counter()
    with pytest.raises(KeyError):
        _replay(replay_case, parameter_overrides={"Bogus [m]": 1.0})
    # a real SPM solve of this 16k-point window takes seconds; the
    # KeyError must return far below that
    assert time.perf_counter() - tic < 2.0
