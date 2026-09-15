# ============================================================
# v0.7 additive API: TRACEABLE parameter overrides
#
# The v0.6 tests guarded the mechanism (an override is applied, or
# it raises).  They did NOT guard the RECORD -- and that gap is why
# the same key name could mean two different things in two places:
#
#   * metrics column ``applied_overrides``  -> real [{key,old,new}]
#   * return dict  ``applied_overrides``    -> the REQUEST mapping
#
# A consumer trying to recover ``old`` therefore had to guess, and
# one did: it parses the metrics CSV instead, with a fallback that
# assumes ``.items()``.  Nothing failed, because nothing asserted.
#
# These tests assert the record itself:
#
#   requested  -- what the caller asked for
#   applied    -- what took effect, with ``old`` read from the set
#   source     -- where the value came from
#
# and that the three places carrying ``applied`` agree.
# ============================================================

import json

import pytest

from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import run_baseline_cell
from parameters.sintef_graphite_capacity import register_capacity_variants
from parameters.sintef_graphite_geometry import register as register_geometry
from parameters.sintef_graphite_ocp import register_variants

DATASET = "sintef_graphite"
CELL = "4ccc47"
MODEL = "SPM"

# measured SINTEF dry thickness (read, not hardcoded from the request)
KEY = "Positive electrode thickness [m]"
MEASURED = 6.4e-05
TEST_ONLY = 1.2e-04          # deliberately absurd; NOT a physical claim
SOURCE = "test:provenance-contract"


@pytest.fixture(scope="module", autouse=True)
def _register():
    register_geometry(CELL)
    register_variants(CELL)
    register_capacity_variants(CELL)


def _run(overrides=None, sources=None):
    return run_baseline_cell(
        get_dataset(DATASET),
        MODEL,
        CELL,
        parameter_set="sintef_graphite_ocp_lith_capmatch_v1",
        plot=False,
        quiet=True,
        parameter_overrides=overrides,
        parameter_override_sources=sources,
    )


def _metadata(result):
    path = result["output_dir"] / "run_metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# 1. the default path is untouched
# ------------------------------------------------------------------
def test_no_override_records_nothing_and_changes_nothing():
    result = _run()
    meta = _metadata(result)

    assert meta["parameter_overrides_requested"] is None
    assert meta["parameter_overrides_applied"] is None
    assert meta["parameter_override_sources"] is None
    assert result["applied_overrides"] is None
    assert result["parameter_overrides_applied"] is None


def test_requested_and_applied_are_null_when_the_request_is_empty():
    """An empty mapping is not a request."""
    result = _run(overrides={})
    meta = _metadata(result)
    assert meta["parameter_overrides_requested"] is None
    assert meta["parameter_overrides_applied"] is None


# ------------------------------------------------------------------
# 2. requested vs applied -- the two must not be conflated
# ------------------------------------------------------------------
def test_requested_is_recorded_verbatim():
    result = _run(overrides={KEY: TEST_ONLY})
    meta = _metadata(result)
    assert meta["parameter_overrides_requested"] == {KEY: TEST_ONLY}


def test_applied_carries_the_before_after_pair_not_the_request():
    """The core distinction.

    ``requested`` is ``{key: new}``.  ``applied`` must additionally
    carry the value that was READ FROM THE SET.  If the two ever
    collapse, every audit row silently becomes ``old == new`` and the
    record can no longer show what changed.

    The run-level list has one entry PER RATE (this cell has two:
    pOCVdeli and pOCVlith), so the assertions are per entry rather
    than assuming a single row.
    """
    result = _run(overrides={KEY: TEST_ONLY})
    meta = _metadata(result)

    applied = meta["parameter_overrides_applied"]
    assert isinstance(applied, list) and applied, "applied must not be empty"
    assert not isinstance(applied, dict), "applied must not be the request"

    for entry in applied:
        assert entry["old"] == pytest.approx(MEASURED, rel=1e-9)
        assert entry["new"] == pytest.approx(TEST_ONLY, rel=1e-12)
        assert entry["old"] != entry["new"], (
            "old == new means the trail is dead"
        )

    # every rate is represented exactly once
    rates = set(entry["rate_slug"] for entry in applied)
    assert len(rates) == len(applied) == len(result["metrics"])


def test_the_run_level_record_covers_every_rate():
    """A multi-rate run must not silently record only the first rate."""
    result = _run(overrides={KEY: TEST_ONLY})
    applied = _metadata(result)["parameter_overrides_applied"]
    assert {e["rate_slug"] for e in applied} == set(
        result["metrics"]["rate_slug"]
    )


def test_an_idempotent_override_reports_old_equal_to_new():
    """Restoring the original value is still a recorded event.

    The point is that the equality is MEASURED, not assumed: the
    entry says old == new because that is what happened.
    """
    result = _run(overrides={KEY: MEASURED})
    entry = _metadata(result)["parameter_overrides_applied"][0]
    assert entry["old"] == pytest.approx(entry["new"], rel=1e-12)
    assert entry["old"] == pytest.approx(MEASURED, rel=1e-9)


# ------------------------------------------------------------------
# 3. source -- the third leg
# ------------------------------------------------------------------
def test_source_is_recorded_when_supplied():
    result = _run(overrides={KEY: TEST_ONLY}, sources={KEY: SOURCE})
    meta = _metadata(result)
    assert meta["parameter_override_sources"] == {KEY: SOURCE}
    assert meta["parameter_overrides_applied"][0]["source"] == SOURCE


def test_a_rich_source_record_is_carried_through_unchanged():
    record = {"logical_name": "electrode_thickness", "source": "experiment",
              "method": "SEM cross-section", "unit": "m"}
    result = _run(overrides={KEY: TEST_ONLY}, sources={KEY: record})
    meta = _metadata(result)
    assert meta["parameter_override_sources"][KEY] == record
    assert meta["parameter_overrides_applied"][0]["source"] == record


def test_a_missing_source_is_recorded_as_none_not_invented():
    """Silence must be distinguishable from a fabricated provenance."""
    result = _run(overrides={KEY: TEST_ONLY})
    entry = _metadata(result)["parameter_overrides_applied"][0]
    assert entry["source"] is None
    assert _metadata(result)["parameter_override_sources"] is None


def test_a_source_can_be_supplied_for_keys_this_run_did_not_override():
    """The sources map is the caller's DECLARATION, not a record.

    A caller may legitimately hand over one shared map covering more
    keys than this particular run overrides -- refusing that would be
    wrong, and silently dropping it would lose information.  So the
    map is echoed, and the AUTHORITY on what happened stays with the
    applied entries, which each carry their own ``source``.

    A reader must therefore cross-reference: ``applied`` says what
    took effect, ``sources`` says what the caller claimed.
    """
    stray = "Some other key [m]"
    result = _run(
        overrides={KEY: TEST_ONLY},
        sources={KEY: SOURCE, stray: "declared but never applied"},
    )
    meta = _metadata(result)

    # only the requested key was applied, and only it carries a source
    applied = meta["parameter_overrides_applied"]
    assert {e["key"] for e in applied} == {KEY}
    for entry in applied:
        assert entry["source"] == SOURCE

    # the declaration is echoed, so nothing the caller said is lost
    assert meta["parameter_override_sources"][stray] == (
        "declared but never applied"
    )
    # ... and it is visibly NOT part of what happened
    assert stray not in {e["key"] for e in applied}


# ------------------------------------------------------------------
# 4. the three places carrying "applied" must agree
# ------------------------------------------------------------------
def test_return_dict_metrics_column_and_metadata_all_agree():
    """One source of truth, three views.

    They are produced from the same list, so a disagreement would mean
    a second code path crept in -- which is exactly how the original
    same-name-two-meanings bug arose.

    Compared per rate: the run-level list is keyed by ``rate_slug``
    and the metrics frame has one row per rate.
    """
    result = _run(overrides={KEY: TEST_ONLY}, sources={KEY: SOURCE})
    meta = _metadata(result)

    from_return = result["parameter_overrides_applied"]
    from_meta = meta["parameter_overrides_applied"]

    by_slug_return = {e["rate_slug"]: e for e in from_return}
    by_slug_meta = {e["rate_slug"]: e for e in from_meta}
    assert set(by_slug_return) == set(by_slug_meta) == set(
        result["metrics"]["rate_slug"]
    )

    for _, row in result["metrics"].iterrows():
        slug = row["rate_slug"]
        column = json.loads(row["applied_overrides"])
        assert len(column) == 1
        col, ret, mta = column[0], by_slug_return[slug], by_slug_meta[slug]
        for a, b in ((col, ret), (col, mta)):
            assert a["key"] == b["key"]
            assert a["old"] == b["old"]
            assert a["new"] == b["new"]
            assert a["source"] == b["source"]


def test_the_legacy_key_still_holds_the_request_mapping():
    """Backward compatibility, asserted so it cannot drift silently.

    ``applied_overrides`` is MISNAMED but load-bearing: a consumer
    reads it as ``{key: value}``.  Changing its type would break that
    consumer, so the shape is pinned here.
    """
    result = _run(overrides={KEY: TEST_ONLY})
    legacy = result["applied_overrides"]
    assert isinstance(legacy, dict)
    assert legacy == {KEY: TEST_ONLY}


def test_legacy_and_authoritative_keys_are_not_the_same_object():
    """They answer different questions; conflating them is the bug."""
    result = _run(overrides={KEY: TEST_ONLY})
    assert result["applied_overrides"] != result["parameter_overrides_applied"]


# ------------------------------------------------------------------
# 5. an unknown key fails, it is never inserted
# ------------------------------------------------------------------
def test_unknown_key_raises_before_anything_is_written():
    with pytest.raises(KeyError, match="not present in parameter set"):
        _run(overrides={"Not a real pybamm parameter [m]": 1.0})


def test_unknown_key_message_names_every_offender():
    with pytest.raises(KeyError) as excinfo:
        _run(overrides={"Bogus one [m]": 1.0, "Bogus two [V]": 2.0})
    msg = str(excinfo.value)
    assert "Bogus one [m]" in msg and "Bogus two [V]" in msg


# ------------------------------------------------------------------
# 6. the override must not leak into the shared parameter set
# ------------------------------------------------------------------
def test_override_does_not_pollute_the_registered_set():
    """Definition test: the set is read-only across calls.

    An override is a per-call overlay.  If it mutated the registered
    set, a LATER run without overrides would silently inherit it --
    and every result after the first override would be wrong.
    """
    import pybamm

    from battery_sim.simulation.baseline import _run_one_replay
    from battery_sim.models.pybamm_factory import build_model_options

    set_id = "sintef_graphite_ocp_lith_capmatch_v1"
    before = pybamm.ParameterValues(set_id)[KEY]
    assert before == pytest.approx(MEASURED, rel=1e-9)

    _run(overrides={KEY: TEST_ONLY})

    after = pybamm.ParameterValues(set_id)[KEY]
    assert after == pytest.approx(before, rel=1e-12), (
        "the override leaked into the registered parameter set"
    )


def test_two_runs_in_a_row_are_independent():
    """The observable consequence of no-leak: no order dependence."""
    first = _run(overrides={KEY: TEST_ONLY})
    second = _run()

    rmse_first = float(first["metrics"].iloc[0]["rmse_time_aligned_mV"])
    rmse_second = float(second["metrics"].iloc[0]["rmse_time_aligned_mV"])
    assert rmse_first != pytest.approx(rmse_second, rel=1e-12), (
        "the overridden run and the clean run must differ"
    )

    third = _run()
    assert float(third["metrics"].iloc[0]["rmse_time_aligned_mV"]) == (
        rmse_second
    ), "the clean run changed after an overridden run -- state leaked"
