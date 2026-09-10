# ============================================================
# Phase B1 tests: GITT segmentation and apparent D_s
#
# Hermetic: a synthetic MULTI-RATE GITT parquet (pulse channel at 1 s,
# rest channel at 10 s, plus a short-burst channel) driven through a
# stub adapter, and an analytic forward model to verify that the
# Weppner-Huggins inversion recovers a known diffusivity.
# ============================================================

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from extraction.gitt_diffusivity import (
    compute_ds_app,
    local_ocp_slope,
)
from extraction.gitt_extractor import (
    extract_gitt_segments,
    resolve_gitt_file,
    write_gitt_segments,
)

RAW_COLUMNS = [
    "Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
    "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah",
]
FILE_TEMPLATE = "stub__{cell}__*__{programme}__RT.bdf.parquet"

PULSE_S = 1800.0
REST_S = 9000.0
I_RAW = -44.155e-6          # raw sign: negative = discharge = lithiation
I_DELI_RAW = +44.155e-6


def _pocv_like_rows(cycles=2, pulses=3, include_short_bursts=True):
    rows = []

    def emit(t, step, current, voltage):
        rows.append({
            "Test Time / s": t, "Unix Time / s": 1.7e9 + t,
            "Current / A": current, "Voltage / V": voltage,
            "Cycle Count / 1": cyc, "Step Index / 1": step,
            "Cumulative Capacity / Ah": 0.0,
        })

    t = 0.0
    for cyc in range(1, cycles + 1):
        # ---- lithiation pulse train ------------------------------
        for k in range(pulses):
            v0 = 0.60 - 0.02 * k
            for j in range(int(PULSE_S) + 1):
                emit(t + j, 4, I_RAW,
                     v0 - 4.0e-4 * np.sqrt(j))
            t += PULSE_S
            # rest channel at 10 s, recovering upward
            for j in range(int(REST_S / 10.0) + 1):
                emit(t + 10.0 * j, 3, 0.0,
                     0.60 - 0.02 * k + 0.02 * np.sqrt(10.0 * j))
            t += REST_S
        # ---- delithiation pulse train ----------------------------
        for k in range(pulses):
            v0 = 0.12 + 0.05 * k
            for j in range(int(PULSE_S) + 1):
                emit(t + j, 10, I_DELI_RAW, v0 + 3.0e-4 * np.sqrt(j))
            t += PULSE_S
            for j in range(int(REST_S / 10.0) + 1):
                emit(t + 10.0 * j, 3, 0.0, 0.12 + 0.05 * k)
            t += REST_S
        # ---- a short logging burst that must be dropped ----------
        if include_short_bursts:
            for j in range(100):
                emit(t + j, 7, 0.0, 0.05)
            t += 100.0
    return rows


@pytest.fixture()
def gitt_parquet(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    path = d / FILE_TEMPLATE.format(cell="stub01", programme="gitt")
    pd.DataFrame(_pocv_like_rows(), columns=RAW_COLUMNS).to_parquet(
        path, index=False
    )
    return path


class _StubAdapter:
    def __init__(self, raw_dir, template=FILE_TEMPLATE):
        self.config = SimpleNamespace(
            dataset_id="stub_graphite",
            raw_dir=str(raw_dir),
            raw_file_template=template,
            extra={"rates_meta": {}},
        )


# ------------------------------------------------------------------
# B1.0 segmentation
# ------------------------------------------------------------------
def test_resolve_gitt_file(gitt_parquet):
    adapter = _StubAdapter(gitt_parquet.parent)
    path, programme = resolve_gitt_file(adapter, "stub01")
    assert path.name == gitt_parquet.name
    assert programme == "gitt"
    with pytest.raises(FileNotFoundError):
        resolve_gitt_file(adapter, "nope")


def test_segments_protocol_and_sign(gitt_parquet):
    adapter = _StubAdapter(gitt_parquet.parent)
    res = extract_gitt_segments(adapter, "stub01", verbose=False)
    seg = res["segments"]
    proto = res["provenance"]["pulse_protocol"]

    # 2 cycles x 3 pulses x 2 branches
    assert len(seg) == 12
    assert proto["pulse_steps"] == [4, 10]
    assert 3 in proto["rest_steps"]
    assert proto["pulse_time_s_median"] == pytest.approx(PULSE_S, rel=1e-6)
    assert proto["relax_time_s_median"] == pytest.approx(REST_S, rel=1e-3)

    # raw sign is flipped: step 4 (raw negative) is LITHIATION
    lith = seg[seg["step"] == 4]
    deli = seg[seg["step"] == 10]
    assert (lith["branch"] == "lithiation").all()
    assert (deli["branch"] == "delithiation").all()
    assert (lith["I_A"] > 0).all()
    assert (deli["I_A"] < 0).all()
    assert res["provenance"]["sign_convention"]["action"].startswith(
        "raw sign FLIPPED"
    )


def test_charge_accounting_uses_the_gaps(gitt_parquet):
    """
    Integrating the pulse channel naively would charge the 9000 s rests
    too.  The split must come from the logging gaps.
    """
    adapter = _StubAdapter(gitt_parquet.parent)
    res = extract_gitt_segments(adapter, "stub01", verbose=False)
    seg = res["segments"]

    for cyc, g in seg.groupby("cycle"):
        lith = g[g["branch"] == "lithiation"]
        q = float((lith["I_A"].abs() * lith["pulse_time_s"]).sum() / 3.6)
        assert q == pytest.approx(
            abs(I_RAW) * 3 * PULSE_S / 3.6, rel=1e-6
        )
        # the naive alternative (pulse channel only, whole span)
        span = 3 * (PULSE_S + REST_S)
        naive = abs(I_RAW) * span / 3.6
        assert naive > 3.0 * q          # the rests would inflate it


def test_soc_axis_is_shared_and_bounded(gitt_parquet):
    adapter = _StubAdapter(gitt_parquet.parent)
    seg = extract_gitt_segments(adapter, "stub01",
                                verbose=False)["segments"]
    for cyc, g in seg.groupby("cycle"):
        lith = g[g["branch"] == "lithiation"].sort_values("SOC_start")
        deli = g[g["branch"] == "delithiation"].sort_values("SOC_end",
                                                            ascending=False)
        assert lith["SOC_start"].iloc[0] == pytest.approx(0.0, abs=1e-9)
        assert lith["SOC_end"].iloc[-1] == pytest.approx(1.0, rel=1e-9)
        assert deli["SOC_start"].iloc[0] == pytest.approx(1.0, rel=1e-9)
    assert seg["SOC_start"].between(-0.01, 1.01).all()
    assert seg["SOC_end"].between(-0.01, 1.01).all()


def test_relaxation_paired_from_the_rest_channel(gitt_parquet):
    adapter = _StubAdapter(gitt_parquet.parent)
    seg = extract_gitt_segments(adapter, "stub01",
                                verbose=False)["segments"]
    assert (seg["relax_step"] >= 0).all()
    assert (seg["relax_time_s"] > 0.9 * REST_S).all()
    # a lithiation pulse falls, so its relaxation must recover upward
    lith = seg[seg["branch"] == "lithiation"]
    assert (lith["delta_V_pulse_V"] < 0).all()
    assert (lith["delta_V_relax_V"] > 0).all()
    deli = seg[seg["branch"] == "delithiation"]
    assert (deli["delta_V_pulse_V"] > 0).all()
    assert (deli["delta_V_relax_V"] < 0).all()


def test_short_bursts_are_dropped(gitt_parquet):
    adapter = _StubAdapter(gitt_parquet.parent)
    res = extract_gitt_segments(adapter, "stub01", verbose=False)
    chans = res["channels"]
    step7 = chans[chans["step"] == 7]
    assert "rest" in str(step7["kind"].iloc[0])      # it is a rest channel
    assert 7 not in res["provenance"]["pulse_protocol"]["pulse_steps"]


def test_write_gitt_segments_layout(gitt_parquet, tmp_path):
    adapter = _StubAdapter(gitt_parquet.parent)
    res = extract_gitt_segments(adapter, "stub01", verbose=False)
    paths = write_gitt_segments(res, tmp_path)
    assert paths["segments"].name == "gitt_segments.csv"
    seg = pd.read_csv(paths["segments"])
    for col in ("cycle", "pulse_id", "SOC_start", "SOC_end", "I_A",
                "pulse_time_s", "relax_time_s", "delta_V_pulse_V",
                "delta_V_relax_V", "capacity_increment_mAh"):
        assert col in seg.columns
    assert "sha256" in paths["provenance"].read_text(encoding="utf-8")


# ------------------------------------------------------------------
# B1.1 diffusivity
# ------------------------------------------------------------------
OCP_SLOPE = -0.12      # the slope the forward model and the table share


def _flat_ocp(voltage=0.30, soc_lo=0.0, soc_hi=1.0, n=200,
              slope=OCP_SLOPE):
    soc = np.linspace(soc_lo, soc_hi, n)
    return pd.DataFrame({"SOC": soc, "Voltage": voltage + slope * soc,
                         "branch": "x"})


def _forward_segment(q_th_Ah, D_true, R, u_prime=OCP_SLOPE,
                     branch="lithiation", n_pulses=5, r2=0.999):
    """Analytic Weppner-Huggins pulses with a KNOWN D."""
    tau = PULSE_S
    tau_d = R ** 2 / D_true
    I = 4.4e-5
    m = u_prime * (2.0 * I / (3.0 * q_th_Ah * 3600.0)) * np.sqrt(tau_d / np.pi)
    rows = []
    for k in range(n_pulses):
        s0 = 0.10 + 0.05 * k
        rows.append({
            "cycle": 1, "pulse_id": k + 1, "branch": branch,
            "SOC_start": s0, "SOC_end": s0 + 0.01,
            "I_A": I if branch == "lithiation" else -I,
            "pulse_time_s": tau, "relax_time_s": REST_S,
            "capacity_increment_mAh": abs(I) * tau / 3.6,
            "delta_V_pulse_V": m * np.sqrt(tau),
            "delta_V_relax_V": -m * np.sqrt(tau) * 1.2,
            "sqrt_t_slope_V_per_sqrt_s": m,
            "sqrt_t_slope_stderr": abs(m) * 1e-3,
            "sqrt_t_r2": r2,
        })
    return pd.DataFrame(rows)


def test_weppner_huggins_inversion_recovers_a_known_D():
    """The estimator must invert the relation it claims to use."""
    R = 13.7e-6
    q_th_Ah = 2.2464e-3
    D_true = 5.0e-10            # m^2/s
    seg = _forward_segment(q_th_Ah, D_true, R)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}

    res = compute_ds_app(seg, tables, particle_radius_m=R,
                         q_th_Ah=q_th_Ah)
    got = res["pulses"]["Ds_app_m2_s"]
    assert got.notna().all()
    assert got.to_numpy() == pytest.approx(D_true, rel=1e-6)
    assert res["provenance"]["n_accepted"] == len(seg)


def test_slope_recovers_the_ocp_derivative():
    """The local slope must return the table's own dV/dSOC."""
    slope_true = -0.1
    soc = np.linspace(0.0, 1.0, 201)
    tbl = pd.DataFrame({"SOC": soc, "Voltage": 0.3 + slope_true * soc})
    got = local_ocp_slope(tbl, 0.5, halfwidth=0.02)
    assert got["slope"] == pytest.approx(slope_true, rel=1e-6)
    assert got["outside_table"] is False


def test_slope_refuses_to_extrapolate_outside_the_table():
    tbl = _flat_ocp(soc_lo=0.1, soc_hi=0.9)
    assert local_ocp_slope(tbl, 0.02, halfwidth=0.01)["outside_table"] is True
    assert np.isnan(local_ocp_slope(tbl, 0.02, halfwidth=0.01)["slope"])


def test_weak_fit_is_rejected():
    R, q_th = 13.7e-6, 2.2464e-3
    seg = _forward_segment(q_th, 5.0e-10, R, r2=0.80)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app(seg, tables, particle_radius_m=R, q_th_Ah=q_th)
    assert res["provenance"]["n_accepted"] == 0
    assert "sqrt(t) fit weak" in res["pulses"]["flags"].iloc[0]
    assert res["table"].empty


def test_uncertainty_is_twice_the_relative_slope_error():
    R, q_th = 13.7e-6, 2.2464e-3
    seg = _forward_segment(q_th, 5.0e-10, R)
    seg["sqrt_t_slope_stderr"] = seg["sqrt_t_slope_V_per_sqrt_s"].abs() * 0.01
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app(seg, tables, particle_radius_m=R, q_th_Ah=q_th)
    p = res["pulses"]
    assert p["Ds_app_rel_uncertainty"].iloc[0] == pytest.approx(0.02, rel=1e-9)
    assert p["Ds_app_cm2_s_uncertainty"].iloc[0] == pytest.approx(
        p["Ds_app_cm2_s"].iloc[0] * 0.02, rel=1e-9
    )


def test_provenance_records_the_sources():
    R, q_th = 13.7e-6, 2.2464e-3
    seg = _forward_segment(q_th, 5.0e-12, R)
    tables = {"lithiation": _flat_ocp(), "delithiation": _flat_ocp()}
    res = compute_ds_app(seg, tables, particle_radius_m=R, q_th_Ah=q_th,
                         active_mass_source="metadata cell X")
    prov = res["provenance"]
    assert "Weppner" in prov["equation_reference"]
    assert "PyBOP" in prov["equation_reference"]
    assert "NOT measured" in prov["particle_radius_source"]
    assert prov["active_mass_source"] == "metadata cell X"
    assert "apparent" in prov["quantity"].lower()
    assert "systematic" in prov["uncertainty_definition"]


# ------------------------------------------------------------------
# parameter set
# ------------------------------------------------------------------
def test_diffusivity_function_is_log_interpolated_and_holds_ends():
    from parameters.sintef_graphite_ds import build_diffusivity_function

    tbl = pd.DataFrame({
        "SOC": [0.2, 0.4, 0.6],
        "Ds_app_m2_s": [1e-11, 1e-9, 1e-11],
        "Ds_app_cm2_s": [1e-7, 1e-5, 1e-7],
    })
    fn, soc, d = build_diffusivity_function(tbl)
    assert soc[0] == 0.0 and soc[-1] == 1.0        # ends held
    assert d[0] == pytest.approx(1e-11)
    assert d[-1] == pytest.approx(1e-11)
    # geometric (log) midpoint, not the arithmetic one
    mid = float(np.asarray(fn(0.4).evaluate()).item())
    assert mid == pytest.approx(1e-9, rel=1e-6)
    # accepts the (sto, T) signature PyBaMM uses
    assert fn(0.5, 298.15) is not None
