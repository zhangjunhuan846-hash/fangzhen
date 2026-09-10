# ============================================================
# Phase B1.5 tests: the GITT pulse overpotential budget
#
# The closed-form fit tests are pure numpy; the budget tests run a real
# SPM solve on PyBaMM's BUILT-IN Ecker2015_graphite_halfcell set with a
# synthetic OCP table, so they need no dataset directory.
# ============================================================

import numpy as np
import pandas as pd
import pytest

from extraction.gitt_pulse_budget import (
    ELECTROLYTE_TAU_NOTE,
    VARS,
    ocp_lookup,
    pulse_budget,
    sqrt_t_fits,
    timescales,
)

SET = "Ecker2015_graphite_halfcell"


def _ocp_table(n=400, v_hi=1.4, v_lo=0.02):
    """A standalone synthetic table, only for the OCP-helper tests."""
    soc = np.linspace(0.0, 1.0, n)
    return pd.DataFrame({
        "SOC": soc,
        "Voltage": v_lo + (v_hi - v_lo) * (1.0 - soc) ** 1.5,
        "branch": "lithiation",
    })


def _ocp_table_from_set(set_id: str = SET, n: int = 400):
    """
    The OCP table of the parameter set the model will actually use.

    The decomposition defines eta_total = V - OCP(x_avg), so the table
    MUST be the model's own OCP; a standalone synthetic table would put a
    constant offset into every component.  In production this is the
    frozen Phase B0.6 table (same object the model interpolates).
    """
    import pybamm

    pv = pybamm.ParameterValues(set_id)
    fn = pv["Positive electrode OCP [V]"]
    soc = np.linspace(1e-9, 1.0, n)
    vals = []
    for x in soc:
        node = fn(pybamm.Scalar(float(x)))
        vals.append(float(np.asarray(node.evaluate()).reshape(-1)[0]))
    return pd.DataFrame({"SOC": soc, "Voltage": vals,
                         "branch": "lithiation"})


# ------------------------------------------------------------------
# 1. the fit-form diagnostic
# ------------------------------------------------------------------
def test_one_term_fit_recovers_a_pure_sqrt_t_ramp():
    t = np.linspace(0.0, 1800.0, 181)
    m_true = -1.0e-4
    V = 0.5 + m_true * np.sqrt(t)
    f = sqrt_t_fits(t, V, tau=1800.0, ir_skip_s=60.0)
    assert f["m1"] == pytest.approx(m_true, rel=1e-6)
    assert f["dE_1term_mV"] == pytest.approx(1e3 * abs(m_true) * np.sqrt(1800.0),
                                             rel=1e-6)
    assert f["drift_mV"] == pytest.approx(0.0, abs=1e-6)
    assert f["r2_1term"] == pytest.approx(1.0, abs=1e-9)


def test_one_term_fit_is_contaminated_by_a_linear_drift():
    """The point of the phase: a linear equilibrium drift inflates the
    apparent sqrt(t) signal."""
    t = np.linspace(0.0, 1800.0, 181)
    m_true, b_true = -2.0e-4, -1.0e-5
    V = 0.5 + b_true * t + m_true * np.sqrt(t)
    f = sqrt_t_fits(t, V, tau=1800.0, ir_skip_s=60.0)
    # the one-term read is biased
    assert abs(f["m1"]) > 1.5 * abs(m_true)
    assert f["r2_1term"] < 0.999
    # the two-term read separates them almost exactly
    assert f["m2"] == pytest.approx(m_true, rel=1e-6)
    assert f["b"] == pytest.approx(b_true, rel=1e-6)
    assert f["r2_2term"] == pytest.approx(1.0, abs=1e-9)


def test_fit_declares_nan_when_too_few_points():
    t = np.linspace(0.0, 100.0, 5)
    f = sqrt_t_fits(t, 1.0 - 1e-5 * t, tau=100.0, ir_skip_s=60.0)
    assert np.isnan(f["dE_1term_mV"])


# ------------------------------------------------------------------
# 2. the OCP helper
# ------------------------------------------------------------------
def test_ocp_lookup_is_scalar_in_scalar_out_and_array_in_array_out():
    tbl = _ocp_table()
    f = ocp_lookup(tbl)
    assert isinstance(f(0.5), float)
    out = f(np.array([0.0, 0.5, 1.0]))
    assert isinstance(out, np.ndarray) and out.shape == (3,)
    assert out[0] > out[-1]          # graphite OCP falls with lithiation


# ------------------------------------------------------------------
# 3. timescales
# ------------------------------------------------------------------
def test_timescales_formulas_and_the_D_e_caveat():
    ts = timescales(
        parameter_set=SET, R_m=13.7e-6, L_m=64e-6,
        porosity=0.4, brug=1.5, d_solid_m2_s=1.2e-14,
        d_solid_gitt_median_m2_s=3.8e-16, t_pulse_s=1800.0,
    )
    assert ts["tau_solid_at_reference_D_s"] == pytest.approx(
        13.7e-6 ** 2 / 1.2e-14
    )
    assert ts["tau_pulse_s"] == 1800.0
    assert np.isnan(ts["tau_electrolyte_s"])
    assert ts["electrolyte_tau_note"] == ELECTROLYTE_TAU_NOTE
    assert "cannot be evaluated" in ts["electrolyte_tau_note"]


def test_timescales_computes_tau_electrolyte_when_given_D_e():
    ts = timescales(
        parameter_set=SET, R_m=13.7e-6, L_m=64e-6,
        porosity=0.4, brug=1.5, d_solid_m2_s=1.2e-14,
        d_solid_gitt_median_m2_s=3.8e-16, t_pulse_s=1800.0,
        d_electrolyte_m2_s=1.0e-10,
    )
    d_eff = 1.0e-10 * 0.4 ** 1.5
    assert ts["tau_electrolyte_s"] == pytest.approx(64e-6 ** 2 / d_eff)
    assert ts["Fo_pulse_over_tau_electrolyte_s"] == pytest.approx(
        1800.0 / ts["tau_electrolyte_s"]
    )


# ------------------------------------------------------------------
# 4. the budget itself (one real solve)
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def budget_default():
    return pulse_budget(
        model_name="SPM", parameter_set=SET,
        ocp_table=_ocp_table_from_set(),
        soc_start=0.5, current_A=4.4e-5, pulse_time_s=1800.0, n_eval=61,
    )


def test_budget_decomposition_closes(budget_default):
    b = budget_default
    assert b["dE_solid_mV"] + b["dE_other_mV"] == pytest.approx(
        b["dE_polarisation_mV"], abs=1e-6
    )
    # dE_polarisation is eta_total AT THE PULSE END, i.e. V_end - OCP_end
    assert b["dE_polarisation_mV"] == pytest.approx(
        1e3 * (b["V_end_V"] - b["OCP_avg_end_V"]), abs=1e-6
    )
    assert b["dV_total_mV"] == pytest.approx(
        1e3 * (b["V_end_V"] - b["V_start_V"]), abs=1e-9
    )
    # with the model's own OCP the total polarisation is a few mV, not a
    # constant offset (which is what a mismatched table would produce)
    assert abs(b["dE_polarisation_mV"]) < 50.0


def test_budget_f_solid_is_a_share(budget_default):
    b = budget_default
    assert 0.0 <= b["f_solid"] <= 1.0
    assert b["D_bias_predicted"] == pytest.approx(b["f_solid"] ** 2)


def test_budget_reports_the_measured_quantities(budget_default):
    b = budget_default
    for key in ("x_avg_start", "x_avg_end", "x_surf_end", "D_eff_at_end_m2_s",
                "tau_solid_s", "Fourier_solid", "dE_1term_mV",
                "dE_2term_mV", "drift_mV", "r2_1term", "r2_2term",
                "D_bias_of_1term_fit", "D_bias_of_2term_fit",
                "dc_e_relative", "Q_th_As"):
        assert key in b, key
    assert b["x_avg_end"] > b["x_avg_start"]      # the pulse lithiates
    assert np.isfinite(b["Q_th_As"]) and b["Q_th_As"] > 0


def test_a_smaller_diffusivity_raises_the_solid_share(budget_default):
    """Mechanistic check: starving the particle must move more of the
    pulse polarisation into the solid-diffusion term."""
    smaller = pulse_budget(
        model_name="SPM", parameter_set=SET,
        ocp_table=_ocp_table_from_set(),
        soc_start=0.5, current_A=4.4e-5, pulse_time_s=1800.0, n_eval=61,
        parameter_overrides={
            "Positive particle diffusivity [m2.s-1]": 1e-16,
        },
    )
    assert smaller["D_eff_at_end_m2_s"] < budget_default["D_eff_at_end_m2_s"]
    assert smaller["f_solid"] > budget_default["f_solid"]


def test_unknown_override_key_is_refused():
    with pytest.raises(KeyError):
        pulse_budget(
            model_name="SPM", parameter_set=SET,
            ocp_table=_ocp_table_from_set(n=50),
            soc_start=0.5, current_A=4.4e-5, pulse_time_s=1800.0, n_eval=19,
            parameter_overrides={"Not a real key": 1.0},
        )


def test_variable_map_uses_the_scalar_particle_variables():
    """Regression: the 'X-averaged ... particle concentration' variables
    are still r-resolved (shape (n_r, n_t)); the budget needs the scalars."""
    assert VARS["x_avg"] == "Average positive particle stoichiometry"
    assert VARS["x_surf"] == (
        "X-averaged positive particle surface stoichiometry"
    )
    assert "X-averaged positive particle stoichiometry" not in VARS.values()
