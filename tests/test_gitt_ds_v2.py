# ============================================================
# Phase B1.6 tests: the fit form in the GITT diffusivity
#
# Hermetic.  Three layers:
#   1. the second-order regression itself, on an ANALYTIC pulse
#      V = a + b*t + m*sqrt(t) with a known m -- it must return m
#      exactly, and the first-order fit must be shown to be biased
#      while still scoring a high R^2 (the Phase B1.5 finding);
#   2. the B1.6 inversion, which must recover a known D when the
#      drift term is present (the Phase B1 forward test does the
#      same for the drift-free case);
#   3. the extractor must emit BOTH fits from the same pulse, so the
#      Phase B1 columns keep their meaning.
# ============================================================

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from extraction import gitt_diffusivity as v1
from extraction import gitt_diffusivity_v2 as v2
from extraction.gitt_diffusivity import compute_ds_app
from extraction.gitt_diffusivity_v2 import compute_ds_app_v2, write_ds_app_v2
from extraction.gitt_extractor import (
    _fit_quadratic_sqrt_t,
    _fit_sqrt_t,
    extract_gitt_segments,
)

PULSE_S = 1800.0
REST_S = 9000.0
IR_SKIP_S = 60.0
OCP_SLOPE = -0.12
R_PARTICLE = 13.7e-6
Q_TH_AH = 2.2464e-3


# ------------------------------------------------------------------
# 1. the regression form
# ------------------------------------------------------------------
def _analytic_pulse(m_true, b_true=-1.7e-5, a_true=0.31):
    t = np.arange(0.0, PULSE_S + 1.0, 1.0)
    return t, a_true + b_true * t + m_true * np.sqrt(t)


def test_quadratic_fit_recovers_drift_and_diffusion_exactly():
    t, v = _analytic_pulse(m_true=2.0e-3)
    fit = _fit_quadratic_sqrt_t(t, v, IR_SKIP_S)
    assert fit["sqrt_slope"] == pytest.approx(2.0e-3, rel=1e-9)
    assert fit["t_slope"] == pytest.approx(-1.7e-5, rel=1e-9)
    assert fit["intercept"] == pytest.approx(0.31, rel=1e-9)
    assert fit["r2"] == pytest.approx(1.0, abs=1e-12)


def test_first_order_slope_is_biased_by_the_drift_but_scores_a_high_r2():
    """
    This is the Phase B1.5 finding in its analytic form: the wrong fit
    form can be badly wrong while R^2 stays above the Phase B1 gate.
    """
    t, v = _analytic_pulse(m_true=2.0e-3)
    f1 = _fit_sqrt_t(t, v, IR_SKIP_S)
    f2 = _fit_quadratic_sqrt_t(t, v, IR_SKIP_S)
    # the drift is real over 1800 s: ~30 mV
    assert abs(-1.7e-5 * PULSE_S) > 0.02
    # the second-order fit has the true slope, the first-order one does not
    assert f2["sqrt_slope"] == pytest.approx(2.0e-3, rel=1e-9)
    assert f1["slope"] != pytest.approx(2.0e-3, rel=0.05)
    # ... yet BOTH pass the Phase B1 R^2 gate
    assert f1["r2"] >= v1.MIN_R2
    assert f2["r2"] >= v1.MIN_R2


def test_quadratic_fit_matches_the_first_order_one_without_drift():
    """With b = 0 the two forms must agree: the extra term is harmless."""
    t, v = _analytic_pulse(m_true=3.0e-3, b_true=0.0)
    f1 = _fit_sqrt_t(t, v, IR_SKIP_S)
    f2 = _fit_quadratic_sqrt_t(t, v, IR_SKIP_S)
    assert f2["sqrt_slope"] == pytest.approx(f1["slope"], rel=1e-9)
    assert f2["t_slope"] == pytest.approx(0.0, abs=1e-9)


def test_quadratic_fit_refuses_a_window_too_short_to_fit_three_terms():
    t = np.arange(0.0, 4.0, 1.0)          # 4 samples, 3 coefficients
    v = np.linspace(0.3, 0.4, 4)
    fit = _fit_quadratic_sqrt_t(t, v, 0.0)
    assert fit["n_fit"] == 4
    assert np.isnan(fit["sqrt_slope"])
    assert np.isnan(fit["t_slope"])


# ------------------------------------------------------------------
# 2. the inversion
# ------------------------------------------------------------------
def _flat_ocp(voltage=0.30, soc_lo=0.0, soc_hi=1.0, n=200,
              slope=OCP_SLOPE):
    soc = np.linspace(soc_lo, soc_hi, n)
    return pd.DataFrame({"SOC": soc, "Voltage": voltage + slope * soc})


def _segments_with_both_fits(D_true, drift_ratio=2.9,
                             branch="lithiation", n_pulses=5, r2=0.999):
    """
    Analytic Weppner-Huggins pulses with a KNOWN D, plus the slope a
    first-order fit would have reported (inflated by `drift_ratio`).
    """
    tau_d = R_PARTICLE ** 2 / D_true
    I = 4.4e-5
    m = OCP_SLOPE * (2.0 * I / (3.0 * Q_TH_AH * 3600.0)) \
        * np.sqrt(tau_d / np.pi)
    rows = []
    for k in range(n_pulses):
        s0 = 0.10 + 0.05 * k
        rows.append({
            "cycle": 1, "pulse_id": k + 1, "branch": branch,
            "SOC_start": s0, "SOC_end": s0 + 0.01,
            "I_A": I if branch == "lithiation" else -I,
            "pulse_time_s": PULSE_S, "relax_time_s": REST_S,
            "capacity_increment_mAh": abs(I) * PULSE_S / 3.6,
            "delta_V_pulse_V": m * np.sqrt(PULSE_S),
            "delta_V_relax_V": -m * np.sqrt(PULSE_S) * 1.2,
            # the drift-free fit: the value B1.6 must invert
            "sqrt_t_slope_V_per_sqrt_s": m * drift_ratio,
            "sqrt_t_slope_stderr": abs(m) * 1e-3,
            "sqrt_t_r2": r2,
            # the first-order fit of the same pulse (the B1 value)
            "quad_sqrt_t_slope_V_per_sqrt_s": m,
            "quad_sqrt_t_slope_stderr": abs(m) * 1e-3,
            "quad_t_slope_V_per_s": -1.7e-5,
            "quad_r2": r2,
        })
    return pd.DataFrame(rows)


def test_v2_inversion_recovers_a_known_D():
    D_true = 5.0e-10
    seg = _segments_with_both_fits(D_true)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                            q_th_Ah=Q_TH_AH)
    got = res["pulses"]["Ds_app_m2_s"]
    assert got.notna().all()
    assert got.to_numpy() == pytest.approx(D_true, rel=1e-6)
    assert res["provenance"]["n_accepted"] == len(seg)


def test_v2_uses_the_quadratic_column_not_the_linear_one():
    """
    The whole point of B1.6: the two tables must differ by exactly the
    fit form, by the factor (slope ratio)^2 that D inherits.
    """
    D_true = 5.0e-10
    ratio = 2.9
    seg = _segments_with_both_fits(D_true, drift_ratio=ratio)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    got_v2 = compute_ds_app_v2(
        seg, tables, particle_radius_m=R_PARTICLE, q_th_Ah=Q_TH_AH
    )["pulses"]["Ds_app_m2_s"]
    got_v1 = compute_ds_app(
        seg, tables, particle_radius_m=R_PARTICLE, q_th_Ah=Q_TH_AH
    )["pulses"]["Ds_app_m2_s"]
    assert got_v2.to_numpy() == pytest.approx(D_true, rel=1e-6)
    assert got_v1.to_numpy() == pytest.approx(D_true / ratio ** 2, rel=1e-6)


def test_v2_paired_ratio_equals_the_two_diffusivities():
    """
    The paired ratio is D_v2/D_v1, computed independently here from the
    two tables.  This is the test that pins the DEFINITION -- an inverted
    exponent still passes every "the column exists / is finite" check.
    """
    D_true = 5.0e-10
    ratio = 2.9
    seg = _segments_with_both_fits(D_true, drift_ratio=ratio)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    p2 = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                           q_th_Ah=Q_TH_AH)["pulses"]
    p1 = compute_ds_app(seg, tables, particle_radius_m=R_PARTICLE,
                        q_th_Ah=Q_TH_AH)["pulses"]
    direct = (p2["Ds_app_m2_s"] / p1["Ds_app_m2_s"]).to_numpy()
    assert np.allclose(p2["Ds_ratio_vs_linear"].to_numpy(), direct,
                       rtol=1e-9)
    # a first-order slope INFLATED by 2.9x means D_v1 is 2.9^2 SMALLER
    assert direct[0] == pytest.approx(ratio ** 2, rel=1e-9)


def test_v2_reports_the_fit_effect_on_the_pulses():
    seg = _segments_with_both_fits(5.0e-10, drift_ratio=2.9)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                            q_th_Ah=Q_TH_AH)
    eff = res["provenance"]["fit_effect_on_these_pulses"]
    assert eff["n_pulses"] == len(seg)
    assert eff["slope_ratio_linear_over_quad"]["p50"] \
        == pytest.approx(2.9, rel=1e-9)
    assert eff["Ds_ratio_v2_over_v1"]["p50"] \
        == pytest.approx(2.9 ** 2, rel=1e-9)
    p = res["pulses"]
    assert p["Ds_ratio_vs_linear"].iloc[0] == pytest.approx(2.9 ** 2,
                                                            rel=1e-9)


def test_v2_compares_the_fitted_drift_with_the_expected_equilibrium_drift():
    """
    The correction only means what it claims if the fitted linear term IS
    the equilibrium drift U'*I/Q_th.  The column that answers this must
    exist on every accepted pulse, be signed, and be summarised.
    """
    seg = _segments_with_both_fits(5.0e-10)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                            q_th_Ah=Q_TH_AH)
    p = res["pulses"]
    expected = OCP_SLOPE * 4.4e-5 / (Q_TH_AH * 3600.0)
    assert p["dUdt_expected_V_per_s"].iloc[0] == pytest.approx(expected,
                                                               rel=1e-12)
    # the fixture's drift is -1.7e-5 V/s, ~26x the pure-drift value
    assert p["t_slope_over_expected_drift"].iloc[0] == pytest.approx(
        -1.7e-5 / expected, rel=1e-9)
    eff = res["provenance"]["fit_effect_on_these_pulses"]
    assert eff["drift_term_over_expected_equilibrium_drift"]["p50"] \
        == pytest.approx(-1.7e-5 / expected, rel=1e-9)
    assert eff["drift_term_sign_matches_expected_fraction"] == 1.0


def test_v2_gates_are_the_phase_b1_gates():
    """One definition of each gate: imported, so they cannot drift."""
    assert v2.MIN_R2 == v1.MIN_R2
    assert v2.MIN_ABS_UPRIME == v1.MIN_ABS_UPRIME
    assert v2.MAX_WINDOW_CURVATURE_MV == v1.MAX_WINDOW_CURVATURE_MV
    assert v2.SLOPE_HALFWIDTH_FACTOR == v1.SLOPE_HALFWIDTH_FACTOR
    assert v2.local_ocp_slope is v1.local_ocp_slope


def test_v2_rejects_a_weak_quadratic_fit():
    seg = _segments_with_both_fits(5.0e-10, r2=0.80)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                            q_th_Ah=Q_TH_AH)
    assert res["provenance"]["n_accepted"] == 0
    assert "quadratic fit weak" in res["pulses"]["flags"].iloc[0]
    assert res["table"].empty


def test_v2_refuses_segments_from_the_b1_extractor():
    """A B1 segmentation has no quadratic columns: say so, do not guess."""
    seg = _segments_with_both_fits(5.0e-10).drop(
        columns=["quad_sqrt_t_slope_V_per_sqrt_s"]
    )
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    with pytest.raises(KeyError, match="quad_sqrt_t_slope_V_per_sqrt_s"):
        compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                          q_th_Ah=Q_TH_AH)


def test_v2_refuses_to_extrapolate_hysteresis_into_a_flat_ocp():
    flat = pd.DataFrame({"SOC": np.linspace(0, 1, 50),
                         "Voltage": np.full(50, 0.3)})
    seg = _segments_with_both_fits(5.0e-10)
    res = compute_ds_app_v2(seg, {"lithiation": flat, "delithiation": flat},
                            particle_radius_m=R_PARTICLE, q_th_Ah=Q_TH_AH)
    assert res["provenance"]["n_accepted"] == 0
    assert "undefined" in res["pulses"]["flags"].iloc[0]


# ------------------------------------------------------------------
# 3. writability of the parameter-set table
# ------------------------------------------------------------------
def test_write_ds_app_v2_is_readable_by_the_b1_parameter_builder(tmp_path):
    from parameters.sintef_graphite_ds import load_ds_table

    seg = _segments_with_both_fits(5.0e-10, branch="lithiation")
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                            q_th_Ah=Q_TH_AH)
    paths = write_ds_app_v2(res, tmp_path)
    assert paths["table"].name == "graphite_Ds_app.csv"
    assert paths["provenance"].is_file()
    tab = load_ds_table(tmp_path, "lithiation")
    assert len(tab) >= 2
    assert (tab["Ds_app_m2_s"] > 0).all()


def test_provenance_states_the_fit_form_and_the_shared_gates():
    seg = _segments_with_both_fits(5.0e-10)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    prov = compute_ds_app_v2(seg, tables, particle_radius_m=R_PARTICLE,
                             q_th_Ah=Q_TH_AH)["provenance"]
    assert "b*t" in prov["fit_form"]
    assert "Phase B1.5" in prov["fit_form_correction_vs_phase_B1"]
    assert "IMPORTED" in prov["shared_with_phase_B1"]
    assert "apparent" in prov["quantity"].lower()
    assert "not a material constant" in prov["wording"]


# ------------------------------------------------------------------
# 4. the extractor emits both fits
# ------------------------------------------------------------------
RAW_COLUMNS = [
    "Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
    "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah",
]
FILE_TEMPLATE = "stub__{cell}__*__{programme}__RT.bdf.parquet"
I_RAW = -44.155e-6


def _stub_rows(cycles=1, pulses=2):
    rows = []
    t = 0.0

    def emit(tt, step, current, voltage):
        rows.append({
            "Test Time / s": tt, "Unix Time / s": 1.7e9 + tt,
            "Current / A": current, "Voltage / V": voltage,
            "Cycle Count / 1": cyc, "Step Index / 1": step,
            "Cumulative Capacity / Ah": 0.0,
        })

    for cyc in range(1, cycles + 1):
        for k in range(pulses):
            v0 = 0.60 - 0.02 * k
            for j in range(int(PULSE_S) + 1):
                emit(t + j, 4, I_RAW, v0 - 4.0e-4 * np.sqrt(j))
            t += PULSE_S
            for j in range(int(REST_S / 10.0) + 1):
                emit(t + 10.0 * j, 3, 0.0, v0 + 0.02 * np.sqrt(10.0 * j))
            t += REST_S
    return rows


class _StubAdapter:
    def __init__(self, raw_dir):
        self.config = SimpleNamespace(
            dataset_id="stub_graphite",
            raw_dir=str(raw_dir),
            raw_file_template=FILE_TEMPLATE,
            extra={"rates_meta": {}},
        )


@pytest.fixture()
def stub_segments(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    p = d / FILE_TEMPLATE.format(cell="stub01", programme="gitt")
    pd.DataFrame(_stub_rows(), columns=RAW_COLUMNS).to_parquet(p,
                                                               index=False)
    res = extract_gitt_segments(_StubAdapter(d), "stub01", verbose=False)
    return res


def test_extractor_emits_both_fits(stub_segments):
    seg = stub_segments["segments"]
    for col in ("sqrt_t_slope_V_per_sqrt_s", "sqrt_t_r2",
                "quad_sqrt_t_slope_V_per_sqrt_s", "quad_sqrt_t_slope_stderr",
                "quad_t_slope_V_per_s", "quad_r2",
                "sqrt_t_slope_excess_over_quad"):
        assert col in seg.columns
    assert seg["quad_r2"].min() > 0.99


def test_both_fits_agree_when_the_pulse_has_no_drift(stub_segments):
    """The synthetic pulse is a pure sqrt(t) signal, so b must vanish
    and the two slopes must coincide."""
    seg = stub_segments["segments"]
    assert seg["quad_t_slope_V_per_s"].abs().max() < 1e-6
    rel = (seg["quad_sqrt_t_slope_V_per_sqrt_s"]
           / seg["sqrt_t_slope_V_per_sqrt_s"] - 1.0).abs()
    assert rel.max() < 1e-6
    assert seg["sqrt_t_slope_excess_over_quad"].abs().max() < 1e-9


def test_provenance_describes_both_fits(stub_segments):
    fits = stub_segments["provenance"]["fits"]
    assert "sqrt(t)" in fits["first_order"]
    assert "b*t" in fits["second_order"]
    assert "quad_" in fits["columns"]
