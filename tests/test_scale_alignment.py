"""Contract tests for the scale-alignment gate (governance/scale_alignment.py).

The gate exists because the same mistake was made twice, in two different
projects on the same platform: a model that is not the size of the cell it
is being replayed against makes every parameter look inert.  G5 read it as
"quasi-equilibrium does not excite solid diffusion"; G6 read it as
"C/10 GITT pulses barely move the voltage".  Both were 31x scale errors.

So these tests pin the things that would let that happen again:

  * the capacity a parameter set describes is READ FROM THE MODEL, not
    assumed to be the cell's
  * the capacity a record passed is the SWEEP, not one pulse
  * the verdict is a DECLARED tolerance -- the same numbers with a wider
    tolerance must flip it, which proves no hidden constant is deciding
  * the replay entry point REFUSES a misaligned window instead of running
    it and producing a number that looks meaningful
  * the old helper and the governance record cannot drift apart: they are
    compared value by value rather than trusted to agree
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pybamm = pytest.importorskip("pybamm")

from governance.scale_alignment import (  # noqa: E402
    ALIGNMENT_TOLERANCE_DEX,
    DEFAULT_KNOBS,
    NEXT_STAGE,
    PIPELINE_STAGES,
    STAGE,
    ScaleMisalignment,
    alignment_overrides,
    assert_aligned,
    audit,
    geometry_audit,
    measure_window_charge_Ah,
)
from battery_sim.registry import get_dataset  # noqa: E402
from battery_sim.simulation.protocol_replay import (  # noqa: E402
    capacity_consistency_overrides,
    run_protocol_replay,
)

DATASET = "dlr_gitt"
CELL = "Hydra.0b_A"
TRIPLET = "GITT-discharge#t120"
SWEEP = "GITT-discharge"
PARAM_SET = "Ecker2015_graphite_halfcell"

#: the two numbers the gate exists to separate: what the record passes and
#: what the parameter set describes.
MEASURED_SWEEP_AH = 6.5277e-3
REFERENCE_MODEL_AH = 0.2023983
SINTEF_DATASET = "sintef_graphite"
SINTEF_CELL = "4ccc47"
SINTEF_RATE = "pOCV-deli"


@pytest.fixture(scope="module")
def adapter():
    return get_dataset(DATASET)


@pytest.fixture(scope="module")
def sintef():
    return get_dataset(SINTEF_DATASET)


# ------------------------------------------------------------------
# The pipeline this concept belongs to
# ------------------------------------------------------------------
def test_pipeline_order_puts_alignment_before_parameter_inference():
    """The ordering IS the finding, so it is declared as data.

    Alignment before excitation, excitation before inference: skipping
    ahead makes "the parameter is not identifiable" un-attributable,
    because scale mismatch and absent excitation look identical.
    """
    order = list(PIPELINE_STAGES)
    assert order == [
        "dataset", "geometry_audit", "capacity_alignment",
        "protocol_excitation", "parameter_inference",
    ]
    assert order.index("capacity_alignment") < order.index("protocol_excitation")
    assert order.index("protocol_excitation") < order.index("parameter_inference")
    assert STAGE == "capacity_alignment"
    assert NEXT_STAGE == "protocol_excitation"


# ------------------------------------------------------------------
# Stage 1: geometry audit
# ------------------------------------------------------------------
def test_geometry_audit_reproduces_the_known_capacity():
    g = geometry_audit(PARAM_SET)
    assert g["capacity_Ah"] == pytest.approx(REFERENCE_MODEL_AH, rel=5e-4)
    assert g["electrode_slot"] == "positive"
    assert set(g["footprint_dimensions_m"]) == set(DEFAULT_KNOBS)


def test_geometry_audit_reads_the_positive_slot_of_a_half_cell():
    """A half cell puts its WORKING electrode in the positive slot here.

    Reading these keys by full-cell name returns nothing, so the channel
    is recorded rather than left implicit -- the same trap that made every
    graphite parameter look ABSENT in G6.0.
    """
    g = geometry_audit(PARAM_SET)
    assert "positive" in g["electrode_slot_note"]
    assert g["c_max_mol_m3"] > 0
    assert g["thickness_m"] > 0


def test_unknown_parameter_set_fails_loudly():
    """An unusable geometry must raise, never fall through to a default.

    Two distinct failures, both loud: pybamm rejects an unknown set name
    itself (ValueError), and a set that simply lacks a geometry key is
    reported as a KeyError naming the key -- not silently treated as
    "some other cell".
    """
    with pytest.raises((KeyError, ValueError)):
        geometry_audit("no_such_parameter_set_at_all")
    with pytest.raises(KeyError):
        geometry_audit(PARAM_SET, knobs=("No such knob [m]",))


# ------------------------------------------------------------------
# Stage 2: capacity alignment
# ------------------------------------------------------------------
def test_measured_charge_comes_from_the_record_sweep(adapter):
    """The reference charge is a measurement, and it is the SWEEP.

    One pulse-rest triplet passes only its own pulse.  Treating that as
    the cell capacity scaled the model down by ~7400x, drove it into the
    cut-off and produced NaN transients -- which reads exactly like an
    inert parameter.
    """
    sweep = measure_window_charge_Ah(adapter, CELL, SWEEP)
    triplet = measure_window_charge_Ah(adapter, CELL, TRIPLET)
    assert sweep == pytest.approx(MEASURED_SWEEP_AH, rel=2e-3)
    assert sweep / triplet > 200.0


def test_audit_quantifies_the_c_rate_deficit(adapter):
    """The two C-rates are the point: only the second one decides physics."""
    rec = audit(adapter, TRIPLET, CELL)
    assert rec["verdict"] == "misaligned"
    assert rec["model_capacity_Ah"] == pytest.approx(REFERENCE_MODEL_AH, rel=5e-4)
    assert rec["measured_charge_Ah"] == pytest.approx(MEASURED_SWEEP_AH, rel=2e-3)
    assert rec["capacity_ratio_model_over_measured"] == pytest.approx(31.0, abs=0.2)
    # what the readout says ...
    assert rec["c_rate_on_cell"] == pytest.approx(0.1004, abs=1e-3)
    # ... and what the model would actually do
    assert rec["c_rate_on_model_unscaled"] == pytest.approx(0.00324, abs=1e-4)
    assert rec["c_rate_deficit_factor"] == pytest.approx(31.0, abs=0.2)


def test_verdict_is_a_declared_tolerance_not_a_hidden_constant(adapter):
    """Same numbers, wider tolerance, opposite verdict.

    If the answer were baked into the arithmetic this would not move --
    which is how a threshold silently becomes a physical claim.
    """
    strict = audit(adapter, TRIPLET, CELL)
    loose = audit(adapter, TRIPLET, CELL, tolerance_dex=5.0)
    assert strict["verdict"] == "misaligned"
    assert loose["verdict"] == "aligned"
    assert strict["capacity_ratio_model_over_measured"] == \
        loose["capacity_ratio_model_over_measured"]
    assert ALIGNMENT_TOLERANCE_DEX == 0.05


def test_alignment_keeps_the_footprint_aspect_ratio(adapter):
    """Scaling both linear dimensions by the same factor keeps the shape.

    The knobs are the footprint, not the porosity or the thickness: to
    reach a 31x capacity ratio those two would have to take physically
    absurd values (eps_am 0.012, thickness 2.4 um).
    """
    rec = alignment_overrides(adapter, TRIPLET, CELL)
    root = rec["footprint_scale_linear"]
    for k in DEFAULT_KNOBS:
        assert k in rec["overrides"]
    assert root == pytest.approx(np.sqrt(rec["footprint_scale_area"]), rel=1e-12)

    g = rec["geometry"]
    new_area = 1.0
    for k in DEFAULT_KNOBS:
        new_area *= rec["overrides"][k]
    assert new_area / g["area_m2"] == pytest.approx(rec["footprint_scale_area"],
                                                    rel=1e-12)
    # and the scaled model's capacity now equals the recorded charge
    scaled_Ah = g["capacity_Ah"] * rec["footprint_scale_area"]
    assert scaled_Ah == pytest.approx(rec["measured_charge_Ah"], rel=1e-9)


def test_alignment_source_is_recorded_for_every_knob(adapter):
    rec = alignment_overrides(adapter, TRIPLET, CELL)
    assert set(rec["source"]) == set(rec["overrides"])
    for k, s in rec["source"].items():
        assert s["source"].startswith("CAPACITY ALIGNMENT")
        assert s["charge_reference"]
        assert "mAh" in s["basis"]
        assert s["stage"] == STAGE


# ------------------------------------------------------------------
# The gate itself
# ------------------------------------------------------------------
def test_assert_aligned_raises_a_dedicated_type(adapter):
    """Not ValueError: a caller must be able to branch on it.

    Scale misalignment is FIXABLE (a recipe is returned); a typo in a
    parameter name is not.  Collapsing both into one exception type is how
    the two get confused.
    """
    assert issubclass(ScaleMisalignment, RuntimeError)
    with pytest.raises(ScaleMisalignment) as exc:
        assert_aligned(adapter, TRIPLET, CELL)
    msg = str(exc.value)
    assert "31" in msg            # the ratio
    assert "C/309" in msg         # the C-rate it would actually run at


def test_assert_aligned_returns_the_record_when_it_does_pass(adapter):
    rec = assert_aligned(adapter, TRIPLET, CELL, tolerance_dex=5.0)
    assert rec["verdict"] == "aligned"


# ------------------------------------------------------------------
# The entry point must refuse, not warn
# ------------------------------------------------------------------
def test_protocol_replay_refuses_a_misaligned_window_by_default(adapter):
    with pytest.raises(ScaleMisalignment):
        run_protocol_replay(adapter, TRIPLET, cell=CELL, quiet=True)


def test_protocol_replay_align_mode_reproduces_the_documented_scale(adapter):
    res = run_protocol_replay(adapter, TRIPLET, cell=CELL,
                              scale_alignment="align", quiet=True)
    applied = res["replay"]["_applied_overrides"]
    keys = {e["key"] for e in applied}
    assert set(DEFAULT_KNOBS) <= keys
    meta = json.loads((res["output_dir"] / "run_metadata.json").read_text(
        encoding="utf-8"))
    sa = meta["scale_alignment"]
    assert sa["verdict"] == "misaligned"       # the state BEFORE aligning
    assert sa["applied"] is True
    assert sa["footprint_scale_area"] == pytest.approx(0.032252, rel=1e-3)


def test_assume_mode_records_that_it_was_assumed(adapter):
    res = run_protocol_replay(adapter, TRIPLET, cell=CELL,
                              scale_alignment="assume", quiet=True)
    meta = json.loads((res["output_dir"] / "run_metadata.json").read_text(
        encoding="utf-8"))
    assert meta["scale_alignment"]["verdict"] == "assumed_by_caller"
    assert "no evidence" in meta["scale_alignment"]["note"]


def test_align_mode_will_not_overwrite_a_caller_override(adapter):
    """Two sources for one number is how a provenance chain breaks."""
    with pytest.raises(ValueError):
        run_protocol_replay(
            adapter, TRIPLET, cell=CELL, scale_alignment="align",
            parameter_overrides={DEFAULT_KNOBS[0]: 0.02}, quiet=True,
        )


def test_unknown_scale_alignment_mode_is_rejected(adapter):
    with pytest.raises(ValueError):
        run_protocol_replay(adapter, TRIPLET, cell=CELL,
                            scale_alignment="trust-me", quiet=True)


# ------------------------------------------------------------------
# One capability, one implementation
# ------------------------------------------------------------------
def test_old_helper_and_governance_record_cannot_drift(adapter):
    """Definition-class: compare the two APIs value by value.

    `capacity_consistency_overrides` predates the gate and is what G6.1a
    calls.  It now delegates, so this test is the thing that would fail if
    someone re-implemented the arithmetic in either place.
    """
    old = capacity_consistency_overrides(adapter, TRIPLET, CELL)
    new = alignment_overrides(adapter, TRIPLET, CELL)
    assert old["scale"] == pytest.approx(new["footprint_scale_area"], rel=1e-12)
    assert old["charge_reference"] == new["charge_reference"]
    assert old["model_capacity_Ah"] == pytest.approx(new["model_capacity_Ah"],
                                                     rel=1e-12)
    assert old["measured_charge_Ah"] == pytest.approx(new["measured_charge_Ah"],
                                                      rel=1e-12)
    assert set(old["overrides"]) == set(new["overrides"])
    for k in old["overrides"]:
        assert old["overrides"][k] == pytest.approx(new["overrides"][k], rel=1e-12)


def test_the_gate_is_not_dlr_specific(sintef):
    """The SINTEF p-OCV line has the same disease at a different ratio.

    A gate that only knows about one dataset is not a gate; this is the
    same failure mode that produced the retracted "quasi-equilibrium is
    inert" claim in G5/G6.
    """
    rec = audit(sintef, SINTEF_RATE, SINTEF_CELL)
    assert rec["verdict"] == "misaligned"
    assert rec["capacity_ratio_model_over_measured"] == pytest.approx(113.4,
                                                                     rel=0.02)
    assert rec["c_rate_on_model_unscaled"] < rec["c_rate_on_cell"]
