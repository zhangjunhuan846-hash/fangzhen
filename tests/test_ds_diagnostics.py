# ============================================================
# Phase B2 tests: D_s diagnostics + constant-D sensitivity lattice
#
# Hermetic: the diagnostic tests build a synthetic Phase B1 pulse
# table; the lattice tests build synthetic Phase B0-era extraction
# outputs + catalog metadata.  No 13 GB dataset directory is needed.
# ============================================================

import json

import numpy as np
import pandas as pd
import pytest

from extraction.ds_diagnostics import (
    DEFAULT_B1_DIR,
    REASON_TEXT,
    REJECTED,
    REQUIRED_FIELDS,
    THRESHOLDS,
    VALID,
    build_diagnostics,
    diagnostics_by_soc,
    diagnostics_provenance,
    write_diagnostics,
)
from parameters.sintef_graphite_ds_sweep import (
    DEFAULT_SWEEP_M2_S,
    KEY_DIFFUSIVITY,
    KEY_RADIUS,
    branch_token,
    build_constant_d_variant,
    constant_d_set_id,
    d_tag,
    fourier_number,
    register_constant_d_sweep,
    sweep_provenance,
    tau_d_s,
)

Q_REF_AH = 1.942466e-3
R_REF_M = 13.7e-6


def _as_float(entry) -> float:
    """A parameter value may be a pybamm symbol rather than a number."""
    if hasattr(entry, "evaluate"):
        return float(np.asarray(entry.evaluate()).reshape(-1)[0])
    return float(entry)


# ------------------------------------------------------------------
# fixtures: a synthetic Phase B1 pulse table
# ------------------------------------------------------------------
def _pulse_row(**kw) -> dict:
    base = {
        "cycle": 1, "pulse_id": 1, "branch": "lithiation",
        "SOC_start": 0.10, "SOC_end": 0.14, "SOC_mid": 0.12,
        "I_A": 4.43e-5, "pulse_time_s": 1800.0, "relax_time_s": 9000.0,
        "capacity_increment_mAh": 0.0221,
        "delta_V_pulse_mV": 12.0, "delta_V_relax_mV": -11.0,
        "dE_s_mV": 11.0, "dE_tau_expected_mV": -11.5,
        "sqrt_t_slope_V_per_sqrt_s": 2.6e-4,
        "sqrt_t_slope_stderr": 1.3e-6, "sqrt_t_r2": 0.995,
        "u_prime_V_per_soc": -0.12, "u_prime_knots": 9,
        "u_prime_halfwidth_soc": 6.0e-2,
        "u_prime_window_curvature_mV": 18.0,
        "Q_th_Ah": 2.24e-3, "R_m": R_REF_M,
        "tau_d_s": 7.2e5, "Ds_app_m2_s": 2.6e-16, "Ds_app_cm2_s": 2.6e-12,
        "Ds_app_rel_uncertainty": 0.01,
        "Ds_app_cm2_s_uncertainty": 2.6e-14,
        "Ds_app_relax_m2_s": 2.4e-16, "Ds_app_relax_cm2_s": 2.4e-12,
        "relax_over_pulse_sqrt_ratio": 0.96, "accepted": True, "flags": "",
    }
    base.update(kw)
    return base


@pytest.fixture()
def b1_dir(tmp_path):
    rows = [
        _pulse_row(pulse_id=1, SOC_mid=0.12, Ds_app_m2_s=2.6e-16,
                   Ds_app_cm2_s=2.6e-12),
        _pulse_row(pulse_id=2, SOC_mid=0.32, Ds_app_m2_s=1.1e-15,
                   Ds_app_cm2_s=1.1e-11),
        # weak sqrt(t) fit -> rejected
        _pulse_row(pulse_id=3, SOC_mid=0.52, sqrt_t_r2=0.62,
                   flags="sqrt(t) fit weak (R2=0.620)",
                   accepted=False, Ds_app_m2_s=8.0e-16,
                   Ds_app_cm2_s=8.0e-12),
        # U' unavailable (SOC outside the branch table)
        _pulse_row(pulse_id=4, SOC_mid=0.72, u_prime_V_per_soc=np.nan,
                   u_prime_knots=0, flags="SOC_mid outside the branch",
                   accepted=False, Ds_app_m2_s=np.nan,
                   Ds_app_cm2_s=np.nan),
        # direction inconsistent
        _pulse_row(pulse_id=5, SOC_mid=0.92,
                   flags="sign: dV/dt direction disagrees with I*U'",
                   accepted=False, Ds_app_m2_s=4.0e-16,
                   Ds_app_cm2_s=4.0e-12),
        # OCP not locally linear across the step
        _pulse_row(pulse_id=6, SOC_mid=0.22, u_prime_window_curvature_mV=260.0,
                   flags="OCP not locally linear over the pulse step",
                   accepted=False, Ds_app_m2_s=1.5e-15,
                   Ds_app_cm2_s=1.5e-11),
    ]
    d = tmp_path / "b1"
    d.mkdir()
    pd.DataFrame(rows).to_csv(d / "gitt_ds_app_pulses.csv", index=False)
    with (d / "gitt_ds_app_provenance.json").open("w", encoding="utf-8") as fh:
        json.dump({
            "quantity": "APPARENT / EFFECTIVE solid-state diffusivity",
            "equation_reference": "Weppner & Huggins (1977)",
            "U_prime_source": "frozen Phase B0.6 OCP table",
            "particle_radius_source": "reference set (not measured)",
        }, fh)
    return d


# ------------------------------------------------------------------
# 1. the seven required fields
# ------------------------------------------------------------------
def test_required_fields_present_and_in_brief_order(b1_dir):
    diag = build_diagnostics(b1_dir)
    assert list(diag.columns[:len(REQUIRED_FIELDS)]) == list(REQUIRED_FIELDS)


def test_default_b1_dir_is_the_phase_b1_output():
    assert DEFAULT_B1_DIR == "outputs/analysis/graphite_phaseB1"


# ------------------------------------------------------------------
# 2. validity flags and reason codes
# ------------------------------------------------------------------
def test_valid_row_has_no_reasons(b1_dir):
    diag = build_diagnostics(b1_dir)
    row = diag[diag["pulse_id"] == 1].iloc[0]
    assert row["validity_flag"] == VALID
    assert bool(row["is_valid"])
    assert row["rejection_reasons"] == ""


def test_weak_r2_is_rejected_with_the_r2_reason(b1_dir):
    row = build_diagnostics(b1_dir).set_index("pulse_id").loc[3]
    assert row["validity_flag"] == REJECTED
    assert "r2_below_threshold" in row["rejection_reasons"]
    assert THRESHOLDS["min_r2"] == 0.90


def test_missing_uprime_is_reported_as_slope_unavailable(b1_dir):
    row = build_diagnostics(b1_dir).set_index("pulse_id").loc[4]
    assert "ocp_slope_unavailable" in row["rejection_reasons"]
    # a NaN D must ALSO be flagged as undefined
    assert "undefined" in row["rejection_reasons"]


def test_sign_conflict_and_curvature_are_separate_reasons(b1_dir):
    diag = build_diagnostics(b1_dir).set_index("pulse_id")
    assert diag.loc[5, "rejection_reasons"] == "direction_inconsistent"
    assert diag.loc[6, "rejection_reasons"] == "ocp_not_locally_linear"


def test_reasons_are_exactly_the_five_declared_codes(b1_dir):
    diag = build_diagnostics(b1_dir)
    seen = set()
    for r in diag["rejection_reasons"]:
        seen |= {c for c in str(r).split(";") if c}
    assert seen <= set(REASON_TEXT)
    assert seen == {"r2_below_threshold", "ocp_slope_unavailable",
                    "undefined", "direction_inconsistent",
                    "ocp_not_locally_linear"}


def test_branch_filter(b1_dir):
    diag = build_diagnostics(b1_dir, branch="lithiation")
    assert set(diag["branch"]) == {"lithiation"}
    with pytest.raises(ValueError):
        build_diagnostics(b1_dir, branch="delithiation")


# ------------------------------------------------------------------
# 3. the dimensionless regime check
# ------------------------------------------------------------------
def test_fo_pulse_is_D_tau_over_R_squared(b1_dir):
    diag = build_diagnostics(b1_dir)
    row = diag[diag["pulse_id"] == 1].iloc[0]
    expected = row["Ds_app_m2_s"] * row["pulse_time_s"] / row["R_m"] ** 2
    assert row["Fo_pulse"] == pytest.approx(expected, rel=1e-9)
    # the Weppner-Huggins short-time law requires Fo << 1
    assert row["Fo_pulse"] < 1.0


def test_tau_d_from_D_is_the_inverse_of_Fo(b1_dir):
    row = build_diagnostics(b1_dir).set_index("pulse_id").loc[1]
    assert row["tau_d_s_from_D"] == pytest.approx(
        row["R_m"] ** 2 / row["Ds_app_m2_s"], rel=1e-9
    )
    assert row["tau_d_s_from_D"] > row["pulse_time_s"]


# ------------------------------------------------------------------
# 4. rollup + provenance
# ------------------------------------------------------------------
def test_by_soc_rollup_counts_valid_pulses(b1_dir):
    roll = diagnostics_by_soc(build_diagnostics(b1_dir), bin_width=0.02)
    assert int(roll["n_pulses"].sum()) == 6
    assert int(roll["n_valid"].sum()) == 2
    near = roll[roll["SOC"] == 0.12]
    assert float(near["valid_fraction"].iloc[0]) == 1.0


def test_by_soc_reports_decade_spread(b1_dir):
    roll = diagnostics_by_soc(build_diagnostics(b1_dir))
    # only one valid pulse per bin here -> spread is undefined, not zero
    assert roll["Ds_decades_spanned"].isna().all() or (
        roll["Ds_decades_spanned"] >= 0
    ).all()


def test_provenance_counts_and_thresholds(b1_dir):
    diag = build_diagnostics(b1_dir)
    prov = diagnostics_provenance(diag, b1_dir=b1_dir)
    assert prov["n_pulses"] == 6
    assert prov["n_valid"] == 2
    assert prov["n_rejected"] == 4
    assert prov["valid_fraction"] == pytest.approx(2 / 6)
    assert prov["rejection_counts"]["r2_below_threshold"] == 1
    assert prov["thresholds"]["min_r2"] == 0.90
    assert "not fit" in prov["wording"] or "neither" in prov["wording"]


def test_write_diagnostics_files(b1_dir, tmp_path):
    diag = build_diagnostics(b1_dir)
    paths = write_diagnostics(diag, diagnostics_by_soc(diag),
                              diagnostics_provenance(diag, b1_dir=b1_dir),
                              tmp_path / "out")
    for p in paths.values():
        assert p.is_file()
    assert paths["diagnostics"].name == "Ds_diagnostics.csv"


def test_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_diagnostics(tmp_path)


# ------------------------------------------------------------------
# 5. the constant-D lattice
# ------------------------------------------------------------------
def test_d_tag_is_stable_and_parseable():
    assert d_tag(1e-14) == "1e-14"
    assert d_tag(3e-17) == "3e-17"
    assert d_tag(1e-13) == "1e-13"


def test_set_id_carries_the_branch_token():
    """Regression: a branch-less id let the second branch overwrite the
    first, which silently ran the lithium window on the delithiation
    OCP (extrapolating to ~4.5 V and tripping the voltage event)."""
    a = constant_d_set_id("lithiation", 1e-14)
    b = constant_d_set_id("delithiation", 1e-14)
    assert a != b
    assert branch_token("lithiation") in a
    assert branch_token("delithiation") in b


def test_default_lattice_ids_are_unique_across_branches():
    ids = [constant_d_set_id(br, d)
           for br in ("lithiation", "delithiation")
           for d in DEFAULT_SWEEP_M2_S]
    assert len(ids) == len(set(ids)) == 2 * len(DEFAULT_SWEEP_M2_S)


def test_unknown_branch_is_refused():
    with pytest.raises(ValueError):
        branch_token("positive")
    with pytest.raises(ValueError):
        constant_d_set_id("positive", 1e-14)


def test_tau_and_fourier_formulas():
    R = 13.7e-6
    d = 1e-14
    assert tau_d_s(d, R) == pytest.approx(R ** 2 / d)
    assert fourier_number(d, R, 3600.0) == pytest.approx(
        d * 3600.0 / R ** 2
    )
    # a decade of D is a decade of Fo
    assert fourier_number(1e-13, R, 3600.0) == pytest.approx(
        10 * fourier_number(1e-14, R, 3600.0)
    )


def test_sweep_provenance_says_prescribed_not_estimated():
    rec = sweep_provenance(1e-15, 13.7e-6, protocols={"1C": 3600.0})
    assert rec["prescribed_D_m2_s"] == 1e-15
    assert "PRESCRIBED" in rec["origin"]
    assert "NOT extracted" in rec["origin"]
    assert rec["protocols"]["1C"]["Fo"] == pytest.approx(
        1e-15 * 3600.0 / (13.7e-6) ** 2
    )
    assert rec["protocols"]["1C"]["equilibrated"] is False


# ------------------------------------------------------------------
# fixtures for the lattice builds (synthetic extraction outputs)
# ------------------------------------------------------------------
@pytest.fixture()
def ocp_dir(tmp_path):
    d = tmp_path / "ocp"
    d.mkdir()
    soc = np.linspace(0.0, 1.0, 200)
    pd.DataFrame({"SOC": soc, "Voltage": 3.0 - 2.99 * soc ** 0.35,
                  "branch": "lithiation", "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, 4.33e-5),
                  "capacity_Ah": soc * Q_REF_AH}).to_csv(
        d / "graphite_ocp_lithiation.csv", index=False)
    soc_d = np.linspace(0.9, 0.1, 200)
    pd.DataFrame({"SOC": soc_d, "Voltage": 0.10 + 0.9 * (1.0 - soc_d) ** 0.5,
                  "branch": "delithiation", "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, -4.33e-5),
                  "capacity_Ah": (soc_d - 1.0) * Q_REF_AH}).to_csv(
        d / "graphite_ocp_delithiation.csv", index=False)
    with (d / "ocp_extraction_provenance.json").open("w",
                                                     encoding="utf-8") as fh:
        json.dump({
            "soc_reference_charge_Ah": Q_REF_AH,
            "soc_reference_charge_mAh": Q_REF_AH * 1e3,
            "soc_definition": "lithiation SOC = Q/Q_ref",
            "equilibrium_warning": (
                "pseudo-OCP: contains the C/50 polarisation"
            ),
        }, fh)
    return d


@pytest.fixture()
def metadata_csv(tmp_path):
    cols = [
        "BDF names", "Active Material type", "Start Date YYYYMMDD",
        "Public Labels", "Cycling Programme name",
        "Mass of Active Material / mg", "Electrode Coating Mass / g",
        "Weight percentage of Active Material / %",
        "Theoretical Capacity /  mAh g-1", "Electrode Diameter / cm",
        "Dry Thickness / um", "Nominal Areal Capacity / mAh cm-2",
        "Electrode Loading / g cm-2", "Known Issues",
    ]
    row = [
        "sintef__sintef-graphite-R2032-intelligent-4ccc47__20250514__"
        "p-ocv__RT.bdf.parquet",
        "Graphite", 20250514, "Gr-AQ-1", "p-OCV",
        5.816164537524997, 0.006392499999999995, 90.98419274124022,
        372, 14, 64, 1.404943641532012, 0.0037767302191720753, "",
    ]
    path = tmp_path / "metadata.csv"
    pd.DataFrame([row], columns=cols).to_csv(path, index=False)
    return path


def test_constant_d_replaces_only_the_diffusivity(ocp_dir, metadata_csv):
    """Every other entry is carried over object-identically."""
    from parameters.sintef_graphite_capacity import (
        changed_keys_against,
    )

    reference, pv, info = build_constant_d_variant(
        "lithiation", 1e-15, "4ccc47", ocp_dir=ocp_dir,
        metadata_csv=metadata_csv,
    )
    changed = changed_keys_against(reference, pv)
    assert changed == [KEY_DIFFUSIVITY]
    assert _as_float(pv[KEY_DIFFUSIVITY]) == pytest.approx(1e-15)
    assert float(pv[KEY_RADIUS]) == pytest.approx(R_REF_M, rel=1e-9)
    assert info["set_id"] == constant_d_set_id("lithiation", 1e-15)
    assert info["branch"] == "lithiation"


def test_constant_d_rejects_nonpositive_values(ocp_dir, metadata_csv):
    for bad in (0.0, -1e-15, float("nan")):
        with pytest.raises(ValueError):
            build_constant_d_variant("lithiation", bad, "4ccc47",
                                     ocp_dir=ocp_dir,
                                     metadata_csv=metadata_csv)


def test_register_sweep_is_unique_and_resolvable(ocp_dir, metadata_csv):
    import pybamm

    ids = register_constant_d_sweep(
        "4ccc47", values=[1e-14, 1e-16],
        ocp_dir=ocp_dir, metadata_csv=metadata_csv,
    )
    assert len(set(ids.values())) == 4
    assert set(ids) == {("lithiation", 1e-14), ("lithiation", 1e-16),
                        ("delithiation", 1e-14), ("delithiation", 1e-16)}
    for (br, d), sid in ids.items():
        assert sid in pybamm.parameter_sets
        pv = pybamm.ParameterValues(sid)
        assert _as_float(pv[KEY_DIFFUSIVITY]) == pytest.approx(d)


def test_duplicate_ids_are_refused(monkeypatch, ocp_dir, metadata_csv):
    """The defensive check behind the branch-token fix."""
    import parameters.sintef_graphite_ds_sweep as mod

    monkeypatch.setattr(
        mod, "constant_d_set_id", lambda b, d: "sintef_graphite_Dsweep_fixed"
    )
    with pytest.raises(ValueError, match="duplicate sweep set id"):
        mod.register_constant_d_sweep(
            "4ccc47", values=[1e-14, 3e-14], branches=("lithiation",),
            ocp_dir=ocp_dir, metadata_csv=metadata_csv,
        )


def test_write_sweep_manifest_records_origin_and_Fo(ocp_dir, metadata_csv,
                                                    tmp_path):
    from parameters.sintef_graphite_ds_sweep import write_sweep_manifest

    path = write_sweep_manifest(
        tmp_path / "out", cell="4ccc47", values=[1e-14],
        protocols={"1C": 3600.0}, ocp_dir=ocp_dir, metadata_csv=metadata_csv,
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["grade"] == (
        "prescribed_constant_D_sensitivity_grid_not_an_estimate"
    )
    assert "not a diffusivity estimate" in doc["what_this_is_not"]
    entries = doc["entries"]
    assert len(entries) == 2
    for e in entries:
        assert "PRESCRIBED" in e["origin"]
        assert e["protocols"]["1C"]["Fo"] == pytest.approx(
            1e-14 * 3600.0 / e["particle_radius_m"] ** 2
        )
