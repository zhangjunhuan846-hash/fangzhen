"""Contract tests for the shared recovery statistics (G6 identifiability).

Two things are pinned here:

  * the estimator itself, against CLOSED-FORM answers rather than against
    its own previous output.  A band width is easy to compute plausibly
    and wrongly, and the wrong version would keep producing numbers.
  * the fact that G6.1b-1 and G6.1c share ONE estimator.  Two copies
    would drift silently, and the project has already paid for that
    lesson twice (the half-cell option translation, the capability table),
    so the guard is a source-level check rather than a comment.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from identification.recovery_stats import (
    PROBE_MAX_DEX,
    PROBE_STEP_DEX,
    band_width,
    curvature_stats,
    probe_grid,
)

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------
# The probe grid
# ------------------------------------------------------------------
def test_probe_grid_is_symmetric_uniform_and_spans_the_documented_range():
    g = probe_grid()
    assert g[0] == pytest.approx(-PROBE_MAX_DEX)
    assert g[-1] == pytest.approx(PROBE_MAX_DEX)
    assert 0.0 in set(np.round(g, 6))
    assert np.allclose(np.diff(g), PROBE_STEP_DEX, atol=1e-9)
    assert np.allclose(g, -g[::-1])


def test_probe_grid_resolves_below_the_limit_it_is_compared_against():
    """The grid must be finer than the 0.30 dex limit it is judged by.

    A grid coarser than the threshold would make the pass/fail decision
    depend on grid placement rather than on the physics.
    """
    assert PROBE_STEP_DEX <= 0.30 / 3.0


# ------------------------------------------------------------------
# band_width, against closed forms
# ------------------------------------------------------------------
def test_band_width_recovers_a_known_parabola():
    """J(a) = (a/0.5)^2 reaches 1 mV^2 exactly at a = +/-0.5."""
    g = probe_grid()
    cost = (g / 0.5) ** 2
    b = band_width(g, cost, 0.0, 1.0)
    assert b["width_dex"] == pytest.approx(1.0, abs=1e-9)
    assert b["left_dex"] == pytest.approx(0.5, abs=1e-9)
    assert b["right_dex"] == pytest.approx(0.5, abs=1e-9)
    assert b["truncated"] is False


def test_band_width_interpolates_and_reports_the_gap_it_interpolated_over():
    """A linear J crosses between two MEASURED points; report their gap."""
    g = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
    cost = np.abs(g) * 2.0          # crosses 1.0 at a = +/-0.5 exactly
    b = band_width(g, cost, 0.0, 1.0)
    assert b["width_dex"] == pytest.approx(1.0, abs=1e-12)
    assert b["resolution_dex"] == pytest.approx(0.5, abs=1e-12)

    # a coarser grid must give a coarser reported resolution
    g2 = np.array([-1.0, 0.0, 1.0])
    b2 = band_width(g2, np.abs(g2) * 2.0, 0.0, 1.0)
    assert b2["resolution_dex"] == pytest.approx(1.0, abs=1e-12)


def test_band_width_flags_truncation_instead_of_reporting_a_width():
    """A band that runs to the edge is a LOWER BOUND, and must say so."""
    g = probe_grid()
    cost = (g / 50.0) ** 2          # never reaches 1 mV^2 inside the scan
    b = band_width(g, cost, 0.0, 1.0)
    assert b["truncated"] is True
    assert b["truncated_left"] is True and b["truncated_right"] is True
    assert b["width_dex"] == pytest.approx(2.0 * PROBE_MAX_DEX, abs=1e-9)


def test_band_width_snaps_to_a_measured_point_rather_than_interpolating_it():
    """The minimum is never interpolated (the G5.0 lesson).

    Handing in an off-grid argmin must return the band around the nearest
    MEASURED minimum, not a parabola fitted through the neighbouring
    points.
    """
    g = probe_grid()
    cost = ((g - 0.30) / 0.5) ** 2      # minimum at 0.30, which IS on grid
    on_grid = band_width(g, cost, 0.30, 1.0)
    off_grid = band_width(g, cost, 0.31, 1.0)
    assert off_grid["width_dex"] == pytest.approx(on_grid["width_dex"], abs=1e-12)
    assert on_grid["left_dex"] == pytest.approx(0.5, abs=1e-9)
    assert on_grid["right_dex"] == pytest.approx(0.5, abs=1e-9)
    assert on_grid["truncated"] is False


def test_band_width_drops_unreachable_points_and_says_so():
    """inf is 'this run did not happen', not 'this cost is small'.

    Where the band ends on that side is then UNKNOWN, so the edge is the
    last measured in-band point and the side is flagged: with the flag
    set, every width this module returns is a lower bound.
    """
    g = probe_grid()
    cost = (g / 0.5) ** 2
    cost[g > 0.2] = np.inf
    b = band_width(g, cost, 0.0, 1.0)
    assert b["truncated_right"] is True
    assert b["truncated_left"] is False
    assert b["right_dex"] == pytest.approx(0.2, abs=1e-9)
    assert b["left_dex"] == pytest.approx(0.5, abs=1e-9)
    assert b["n_points"] == int(np.isfinite(cost).sum())


def test_band_width_of_an_empty_or_level_free_curve_is_nan_not_zero():
    b = band_width(np.array([]), np.array([]), 0.0, 1.0)
    assert np.isnan(b["width_dex"])
    assert b["truncated"] is True


# ------------------------------------------------------------------
# curvature / one-sidedness
# ------------------------------------------------------------------
def test_curvature_and_asymmetry_match_the_closed_form():
    """J(a) = (a - c)^2, measured around a_hat = 0 with c != 0.

    The second difference is exact for a parabola, and the asymmetry has a
    closed form, so this is a definition-class check rather than a
    "smoke test".
    """
    h, c = 0.02, 0.1

    def J(a):
        return (a - c) ** 2

    s = curvature_stats(J, 0.0, h)
    assert s["curvature_Jpp_mV2_per_dex2"] == pytest.approx(2.0, rel=1e-9)
    expect_asym = (((h - c) ** 2) - ((-h - c) ** 2)) / (((h - c) ** 2) + ((-h - c) ** 2))
    assert s["curvature_asymmetry"] == pytest.approx(expect_asym, rel=1e-12)
    assert s["curvature_asymmetry"] < 0     # off-centre low -> raising is cheaper


def test_curvature_of_a_symmetric_valley_is_symmetric():
    s = curvature_stats(lambda a: a ** 2, 0.0, 0.02)
    assert s["curvature_asymmetry"] == pytest.approx(0.0, abs=1e-12)
    assert s["curvature_Jpp_mV2_per_dex2"] == pytest.approx(2.0, rel=1e-9)


def test_curvature_is_nan_when_a_side_is_unreachable():
    def J(a):
        return float("inf") if a > 0 else a ** 2

    s = curvature_stats(J, 0.0, 0.02)
    assert np.isnan(s["curvature_Jpp_mV2_per_dex2"])
    assert np.isnan(s["curvature_asymmetry"])


# ------------------------------------------------------------------
# One estimator, two scripts
# ------------------------------------------------------------------
def test_g6_1b1_does_not_reimplement_the_band_estimator():
    """Source-level guard against a second copy of the crossing search."""
    src = (ROOT / "scripts/graphite/g6_1b1_global_recovery.py").read_text(
        encoding="utf-8")
    assert "identification.recovery_stats" in src
    assert "def _cross(" not in src
    assert "def band_width(" not in src


def test_g6_1c_does_not_reimplement_the_band_estimator():
    src = (ROOT / "scripts/graphite/g6_1c_excitation_map.py").read_text(
        encoding="utf-8")
    assert "identification.recovery_stats" in src
    assert "def _cross(" not in src
    assert "def band_width(" not in src


def test_g6_1c_does_not_reimplement_the_replay_scan():
    """Same guard for the evaluator: one cost definition, two gates."""
    src = (ROOT / "scripts/graphite/g6_1c_excitation_map.py").read_text(
        encoding="utf-8")
    assert "identification.replay_scan" in src
    assert "class MultiplierScan" not in src
    assert "def _run_one_replay(" not in src


# ------------------------------------------------------------------
# The multiplier override keeps the function's argument list intact
# ------------------------------------------------------------------
import identification.replay_scan as replay_scan  # noqa: E402
from identification.replay_scan import DS_KEY  # noqa: E402

PARAM_SET = "Ecker2015_graphite_halfcell"


def test_multiplier_override_is_a_function_and_the_reference_is_too():
    """The parameter set's own D_s is a function; so is the override.

    A scalar here would silently test a different capability, and this
    parameter set would reject it anyway.  Guarded on the REAL set, not on
    a fixture, because "is it a function" is a property of the set.
    """
    pybamm = pytest.importorskip("pybamm")  # noqa: F841
    from battery_sim.models.pybamm_factory import load_parameter_values

    assert callable(load_parameter_values(PARAM_SET)[DS_KEY])
    assert callable(replay_scan.build_multiplier_override(PARAM_SET, 0.0))


def test_multiplier_override_scales_and_forwards_every_argument(monkeypatch):
    """f(sto, T) must be forwarded ALL the way.

    Dropping an argument would silently drop the temperature dependence
    instead of failing, so the wrapper is checked against a reference
    whose value depends on both arguments and which records how it was
    called.  A fixture rather than the real set, because the real D_s
    returns a pybamm Symbol (an expression in T), and an expression
    cannot be numerically compared without inventing a value for T.
    """
    seen = []

    def ref(sto, T):
        seen.append((sto, T))
        return 2.0 * sto + T

    monkeypatch.setattr(replay_scan, "load_parameter_values",
                        lambda ps: {replay_scan.DS_KEY: ref})
    a = 0.5
    f = replay_scan.build_multiplier_override("any_set", a)
    assert f(0.3, 300.0) == pytest.approx((10.0 ** a) * (2 * 0.3 + 300.0))
    assert seen == [(0.3, 300.0)]

    f0 = replay_scan.build_multiplier_override("any_set", 0.0)
    assert f0(0.7, 310.0) == pytest.approx(ref(0.7, 310.0))
    assert seen[-1] == (0.7, 310.0)


def test_multiplier_override_refuses_a_scalar_parameter(monkeypatch):
    """A scalar D_s must fail loudly rather than be silently wrapped.

    Wrapping a number would look like it worked and would be a different
    experiment (the gates are about FUNCTION-valued parameters).
    """
    monkeypatch.setattr(replay_scan, "load_parameter_values",
                        lambda ps: {replay_scan.DS_KEY: 4e-15})
    with pytest.raises(TypeError):
        replay_scan.build_multiplier_override("any_set", 0.0)


def test_multiplier_override_reports_the_a_value_it_used(monkeypatch):
    """The wrapper is named after a0, so a provenance trace can name it."""
    monkeypatch.setattr(replay_scan, "load_parameter_values",
                        lambda ps: {replay_scan.DS_KEY: lambda *args: 1.0})
    assert "+0.5000" in replay_scan.build_multiplier_override("s", 0.5).__name__
