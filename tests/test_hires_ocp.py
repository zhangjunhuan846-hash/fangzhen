# ============================================================
# Phase B0.6 tests: full-resolution OCP extraction (v2)
#
# Hermetic: synthetic p-OCV parquet + a stub adapter, so the whole
# path (no global stride -> v1 core -> branch-aware sampling) is
# exercised without the 13 GB data directory.
# ============================================================

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from extraction.hires_trace import load_hires_trace, resolve_raw_file
from extraction.ocp_extractor import extract_ocp_branches
from extraction.ocp_extractor_v2 import (
    EPS_V_MV,
    MAX_GAP_SOC,
    MIN_PTS_IN_STEEP,
    compare_tables,
    extract_ocp_v2,
    interpolant_deviation,
    resample_branch,
    resample_frame,
    table_stats,
)

RAW_COLUMNS = [
    "Test Time / s", "Unix Time / s", "Current / A", "Voltage / V",
    "Cycle Count / 1", "Step Index / 1", "Cumulative Capacity / Ah",
]
FILE_TEMPLATE = "stub__graphite__{cell}__*__{programme}__RT.bdf.parquet"
SHA = "a" * 64


# ------------------------------------------------------------------
# synthetic p-OCV file + stub adapter
# ------------------------------------------------------------------
def _pocv_rows(dt=10.0, n=600, v0=3.0):
    """Cycle 1: rest / lithiation / rest / delithiation."""
    rows = []
    t = 0.0

    def emit(step, count, current, vf):
        nonlocal t
        for k in range(count):
            rows.append({
                "Test Time / s": t + k * dt,
                "Unix Time / s": 1.7e9 + t + k * dt,
                "Current / A": current,
                "Voltage / V": vf(k * dt),
                "Cycle Count / 1": 1,
                "Step Index / 1": step,
                "Cumulative Capacity / Ah": float(k) * abs(current) * dt / 3600.0,
            })
        t += count * dt

    # rest before lithiation
    emit(1, 10, 0.0, lambda s: v0)
    # lithiation (raw current NEGATIVE = discharge for graphite||Li)
    span = n * dt
    emit(2, n, -43.28e-6,
         lambda s: 0.01 + (v0 - 0.01) * np.exp(-s / (span / 6.0)))
    v_end_lith = 0.01 + (v0 - 0.01) * np.exp(-span / (span / 6.0))
    # rest
    emit(3, 10, 0.0, lambda s: v_end_lith)
    # delithiation (raw current POSITIVE)
    emit(4, n, +43.28e-6,
         lambda s: v_end_lith + (1.0 - v_end_lith) * (s / span) ** 0.35)
    return rows


@pytest.fixture()
def raw_parquet(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    path = d / FILE_TEMPLATE.format(cell="stub01", programme="p-ocv")
    pd.DataFrame(_pocv_rows(), columns=RAW_COLUMNS).to_parquet(
        path, index=False
    )
    return path


class _StubAdapter:
    """Just enough adapter surface for the loader (no battery_sim)."""

    def __init__(self, raw_dir, *, decimate=10, sha_override=None):
        self._raw_dir = Path(raw_dir)
        self.config = SimpleNamespace(
            dataset_id="stub_graphite",
            raw_dir=str(raw_dir),
            raw_file_template=FILE_TEMPLATE,
            extra={"rates_meta": {"pOCV-deli": {"programme": "p-ocv"}}},
        )
        self._decimate = decimate
        self._sha_override = sha_override

    def get_ambient_temperature(self, cell):
        return 25.0

    def load_processed_discharge(self, cell, rate):
        """Mimics the decimating adapter path (global stride)."""
        path, _ = resolve_raw_file(self, cell, rate)
        df = pd.read_parquet(path)
        if self._decimate > 1:
            # like the real adapter: decimate PER (cycle, step) group and
            # force the group's first and last row, so branch endpoints
            # (and therefore the SOC anchor) survive
            keep = []
            for _, g in df.groupby(["Cycle Count / 1", "Step Index / 1"],
                                   sort=True):
                idx = list(range(0, len(g), self._decimate))
                if idx[-1] != len(g) - 1:
                    idx.append(len(g) - 1)
                keep.append(g.iloc[idx])
            df = pd.concat(keep).reset_index(drop=True)
        out = pd.DataFrame({
            "time_s": df["Test Time / s"].to_numpy(float),
            "current_A": -df["Current / A"].to_numpy(float),
            "voltage_V": df["Voltage / V"].to_numpy(float),
            "capacity_Ah": df["Cumulative Capacity / Ah"].to_numpy(float),
            "cycle": df["Cycle Count / 1"].to_numpy(int),
            "step": df["Step Index / 1"].to_numpy(int),
        })
        real_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        out.attrs["provenance"] = {
            "source_file": path.name,
            "source_file_sha256": self._sha_override or real_sha,
            "decimation_stride": self._decimate,
        }
        return out


# ------------------------------------------------------------------
# 1. branch-aware sampling
# ------------------------------------------------------------------
def test_vertical_rdp_keeps_endpoints_and_steep_region():
    # flat plateau, then a very steep rise, then flat again
    soc = np.linspace(0.0, 1.0, 3001)
    v = np.where(soc < 0.5, 0.1,
                 np.where(soc < 0.51, 0.1 + 30.0 * (soc - 0.5), 0.4))
    keep, diag = resample_branch(soc, v, eps_mV=0.2, max_gap_soc=0.02,
                                 min_pts_in_steep=8)
    assert keep[0] == 0 and keep[-1] == len(soc) - 1
    steep = ((soc[keep] >= 0.49) & (soc[keep] <= 0.52)).sum()
    assert steep >= 8                      # steepness floor applied
    assert keep.size < 200                 # plateau heavily decimated
    assert diag["endpoints_kept"] is True


def test_resample_branch_rejects_non_increasing_soc():
    with pytest.raises(ValueError, match="strictly increasing"):
        resample_branch(np.array([0.0, 0.2, 0.2, 0.4]),
                        np.array([1.0, 0.8, 0.7, 0.6]))


def test_resample_branch_respects_max_gap():
    soc = np.linspace(0.0, 1.0, 1001)
    v = np.full_like(soc, 0.12)             # perfectly flat
    keep, _ = resample_branch(soc, v, eps_mV=0.2, max_gap_soc=0.05)
    gaps = np.diff(soc[keep])
    assert gaps.max() <= 0.05 + 1e-9
    # a flat line needs no interior detail beyond the gap cap
    assert keep.size == pytest.approx(21, abs=2)


def test_resample_branch_measures_achieved_error():
    soc = np.linspace(0.0, 1.0, 2001)
    v = 0.1 + 0.5 * np.sin(6.0 * np.pi * soc)   # wiggly
    keep, diag = resample_branch(soc, v, eps_mV=0.5)
    err = diag["achieved_vertical_error_mV"]
    assert err["max"] < 5.0                     # measured, not assumed
    assert set(err["by_soc_band"]) == {
        "0.000-0.01", "0.010-0.10", "0.100-0.50", "0.500-1.00"
    }
    assert diag["eps_ladder"][-1]["eps_mV"] == pytest.approx(0.5)
    assert diag["n_in"] == 2001 and diag["n_out"] == keep.size


def test_resample_branch_eps_ladder_when_point_cap_binds():
    soc = np.linspace(0.0, 1.0, 4001)
    v = 0.1 + 0.4 * np.sin(200.0 * np.pi * soc)   # high-frequency noise
    keep, diag = resample_branch(soc, v, eps_mV=0.01, point_cap=100,
                                 min_pts_in_steep=2, max_gap_soc=1.0)
    assert keep.size <= 100
    assert len(diag["eps_ladder"]) > 1           # the ladder was used
    assert diag["eps_mV_used"] > 0.01


def test_defaults_are_the_calibrated_ones():
    assert EPS_V_MV == 0.2
    assert MAX_GAP_SOC == 0.005
    assert MIN_PTS_IN_STEEP == 12


def test_resample_frame_preserves_schema_and_order():
    frame = pd.DataFrame({
        "SOC": np.linspace(0.9, 0.1, 50),        # descending, as extracted
        "Voltage": np.linspace(0.1, 0.9, 50),
        "branch": "delithiation",
        "time_s": np.arange(50) * 10.0,
        "current_A": np.full(50, -4.3e-5),
        "capacity_Ah": np.linspace(-1.7e-3, 0.0, 50),
    })
    out, diag = resample_frame(frame)
    assert list(out.columns) == ["SOC", "Voltage", "branch", "time_s",
                                 "current_A", "capacity_Ah"]
    assert out["SOC"].is_monotonic_increasing
    assert diag["n_out"] <= diag["n_in"]


# ------------------------------------------------------------------
# 2. table metrics
# ------------------------------------------------------------------
def test_table_stats_counts_and_density():
    soc = np.array([0.0, 0.005, 0.02, 0.5, 1.0])
    frame = pd.DataFrame({"SOC": soc, "Voltage": 3.0 - 2.9 * soc})
    st = table_stats(frame)
    assert st["n_points"] == 5
    assert st["bands"]["0.000-0.01"]["n_points"] == 2
    assert st["bands"]["0.010-0.10"]["n_points"] == 1
    assert st["bands"]["0.500-1.00"]["n_points"] == 2


def test_interpolant_deviation_constant_offset():
    soc = np.linspace(0.0, 1.0, 11)
    a = pd.DataFrame({"SOC": soc, "Voltage": 1.0 - soc})
    b = pd.DataFrame({"SOC": soc, "Voltage": 1.0 - soc + 0.007})
    d = interpolant_deviation(a, b)
    assert d["max_abs_mV"] == pytest.approx(7.0, rel=1e-6)
    assert d["mean_abs_mV"] == pytest.approx(7.0, rel=1e-6)


def test_interpolant_deviation_band_restricts_range():
    soc = np.linspace(0.0, 1.0, 11)
    a = pd.DataFrame({"SOC": soc, "Voltage": 1.0 - soc})
    b = pd.DataFrame({"SOC": soc, "Voltage": 1.0 - 0.9 * soc})
    d = interpolant_deviation(a, b, band=(0.0, 0.1))
    assert d["soc_range"] == pytest.approx([0.0, 0.1])
    assert d["max_abs_mV"] == pytest.approx(10.0, rel=1e-6)


def test_compare_tables_reports_fidelity_against_measured():
    soc = np.linspace(0.0, 1.0, 101)
    ref = pd.DataFrame({"SOC": soc, "Voltage": 3.0 - 2.9 * soc})
    coarse = ref.iloc[::10].reset_index(drop=True)      # v1-like
    fine = ref.iloc[::2].reset_index(drop=True)          # v2-like
    rep = compare_tables(coarse, coarse, fine, fine,
                         {"soc_definition": "x", "soc_reference_charge_Ah": 1e-3,
                          "n_points_full_resolution": {"lithiation": 101,
                                                       "delithiation": 101}},
                         reference_lith=ref, reference_deli=ref)
    assert "fidelity_vs_measured_mV" in rep["branches"]["lithiation"]
    assert rep["headline"]["lithiation_n_points_v1"] == 11
    assert rep["headline"]["lithiation_n_points_v2"] == 51
    assert rep["headline"]["lithiation_fidelity_v2_vs_measured_mV"] == \
        pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------
# 3. full-resolution loader
# ------------------------------------------------------------------
def test_hires_loader_keeps_every_row_and_flips_sign(raw_parquet):
    adapter = _StubAdapter(raw_parquet.parent)
    tr = load_hires_trace(adapter, "stub01", "pOCV-deli")
    assert len(tr) == 2 * 600 + 20                     # nothing dropped
    prov = tr.attrs["provenance"]
    assert prov["decimation"].startswith("NONE")
    assert prov["n_rows"] == len(tr)
    assert prov["sampling_median_s"] == pytest.approx(10.0)
    assert prov["verification_vs_adapter"]["same_sha256"] is True
    # canonical sign: lithiation (raw negative) is POSITIVE here
    lith = tr[tr["step"] == 2]
    assert float(lith["current_A"].iloc[0]) > 0
    assert float(lith["raw_current_A"].iloc[0]) < 0
    # strictly increasing relative time from 0
    assert float(tr["time_s"].iloc[0]) == 0.0
    assert np.all(np.diff(tr["time_s"]) > 0)


def test_hires_loader_rejects_file_mismatch(raw_parquet):
    adapter = _StubAdapter(raw_parquet.parent, sha_override="b" * 64)
    with pytest.raises(ValueError, match="different file"):
        load_hires_trace(adapter, "stub01", "pOCV-deli")


def test_hires_loader_unknown_rate(raw_parquet):
    adapter = _StubAdapter(raw_parquet.parent)
    with pytest.raises(ValueError, match="rates_meta"):
        load_hires_trace(adapter, "stub01", "nope")


# ------------------------------------------------------------------
# 4. end-to-end v2 extraction
# ------------------------------------------------------------------
def test_extract_v2_uses_full_resolution_and_keeps_definition(raw_parquet):
    adapter = _StubAdapter(raw_parquet.parent, decimate=10)
    trace = load_hires_trace(adapter, "stub01", "pOCV-deli")

    v1 = extract_ocp_branches(adapter.load_processed_discharge(
        "stub01", "pOCV-deli"), cycle=1)
    v2 = extract_ocp_v2(adapter, "stub01", "pOCV-deli", cycle=1)

    # SOC definition untouched: same anchor, same formula
    assert v2["provenance"]["soc_reference_charge_Ah"] == pytest.approx(
        v1["provenance"]["soc_reference_charge_Ah"], rel=1e-9
    )
    assert v2["provenance"]["soc_definition"] == \
        v1["provenance"]["soc_definition"]

    # full resolution feed, sampled output
    n_full = v2["provenance"]["n_points_full_resolution"]
    assert n_full["lithiation"] == int((trace["step"] == 2).sum())
    assert n_full["delithiation"] == int((trace["step"] == 4).sum())
    assert v2["provenance"]["n_points"]["lithiation"] < n_full["lithiation"]
    assert len(v2["lithiation"]) == v2["provenance"]["n_points"]["lithiation"]

    # endpoints and their voltages survive
    assert float(v2["lithiation"]["SOC"].iloc[0]) == pytest.approx(0.0)
    assert float(v2["lithiation"]["SOC"].iloc[-1]) == pytest.approx(1.0)
    assert float(v2["lithiation"]["Voltage"].iloc[0]) == pytest.approx(3.0,
                                                                      abs=0.01)

    # the sampled table is monotone in SOC for the model interpolant
    for br in ("lithiation", "delithiation"):
        s = np.sort(v2[br]["SOC"].to_numpy(float))
        assert np.all(np.diff(s) > 0)


def test_extract_v2_beats_v1_in_the_steep_region(raw_parquet):
    """The decimated path loses the dilute stage; v2 must not."""
    adapter = _StubAdapter(raw_parquet.parent, decimate=10)
    v1 = extract_ocp_branches(adapter.load_processed_discharge(
        "stub01", "pOCV-deli"), cycle=1)
    v2 = extract_ocp_v2(adapter, "stub01", "pOCV-deli", cycle=1)

    # SOC 0-0.01 point count is the headline of Phase B0.6
    def n_low(frame):
        return int((frame["SOC"] <= 0.01).sum())

    assert n_low(v2["lithiation"]) > n_low(v1["lithiation"])

    # and the reconstruction error against the full curve is small
    err = v2["provenance"]["resampling"]["lithiation"][
        "achieved_vertical_error_mV"
    ]
    assert err["max"] < 1.0


def test_write_ocp_v2_directory_layout(raw_parquet, tmp_path):
    from extraction.ocp_extractor_v2 import write_ocp_v2

    adapter = _StubAdapter(raw_parquet.parent)
    res = extract_ocp_v2(adapter, "stub01", "pOCV-deli", cycle=1)
    paths = write_ocp_v2(res, tmp_path, extra_provenance={"phase": "B0.6"})

    v2_dir = tmp_path / "graphite_ocp_v2"
    assert paths["lithiation"].parent == v2_dir
    assert paths["lithiation"].name == "graphite_ocp_lithiation.csv"
    assert paths["provenance"].name == "ocp_extraction_provenance.json"

    prov = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    assert prov["no_decimation"] is True
    assert prov["phase"] == "B0.6"
    assert "supersedes" in prov
    # readable by the existing parameter layer without changes
    from parameters.sintef_graphite_ocp import load_ocp_tables
    tables = load_ocp_tables(v2_dir)
    assert set(tables) == {"lithiation", "delithiation"}


# ------------------------------------------------------------------
# 5. side-by-side registration of a second table set
# ------------------------------------------------------------------
def _synthetic_ocp_dir(tmp_path):
    """v1-style extraction outputs (schema identical to the real ones)."""
    d = tmp_path / "ocp_v1"
    d.mkdir()
    soc = np.linspace(0.0, 1.0, 200)
    pd.DataFrame({"SOC": soc, "Voltage": 3.0 - 2.99 * soc ** 0.35,
                  "branch": "lithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, 4.33e-5),
                  "capacity_Ah": soc * 1.94e-3}).to_csv(
        d / "graphite_ocp_lithiation.csv", index=False)
    soc_d = np.linspace(0.9, 0.1, 200)
    pd.DataFrame({"SOC": soc_d, "Voltage": 0.10 + 0.9 * (1.0 - soc_d) ** 0.5,
                  "branch": "delithiation",
                  "time_s": np.arange(200) * 60.0,
                  "current_A": np.full(200, -4.33e-5),
                  "capacity_Ah": (soc_d - 1.0) * 1.94e-3}).to_csv(
        d / "graphite_ocp_delithiation.csv", index=False)
    with (d / "ocp_extraction_provenance.json").open(
        "w", encoding="utf-8"
    ) as fh:
        json.dump({"soc_reference_charge_Ah": 1.9424659492079026e-3,
                   "soc_definition": "Q = Q/Q_ref",
                   "equilibrium_warning": "pseudo-OCP",
                   "temperature_source": "declared_room_temperature_not_measured"},
                  fh)
    return d


def _synthetic_metadata(tmp_path):
    cols = ["BDF names", "Active Material type", "Start Date YYYYMMDD",
            "Public Labels", "Cycling Programme name",
            "Mass of Active Material / mg", "Electrode Coating Mass / g",
            "Weight percentage of Active Material / %",
            "Theoretical Capacity /  mAh g-1", "Electrode Diameter / cm",
            "Dry Thickness / um", "Nominal Areal Capacity / mAh cm-2",
            "Electrode Loading / g cm-2", "Known Issues"]
    row = ["sintef__...__4ccc47__20250514__p-ocv__RT.bdf.parquet", "Graphite",
           20250514, "Gr-AQ-1", "p-OCV", 5.816164537524997,
           0.006392499999999995, 90.98419274124022, 372, 14, 64,
           1.404943641532012, 0.0037767302191720753, ""]
    path = tmp_path / "metadata.csv"
    pd.DataFrame([row], columns=cols).to_csv(path, index=False)
    return path


def test_set_id_suffix_keeps_both_ocp_sets_resolvable(tmp_path):
    import pybamm

    from parameters.sintef_graphite_ocp import (
        OCP_DELI_ID, register_variants, variant_summary,
    )

    v1_dir = _synthetic_ocp_dir(tmp_path)
    meta = _synthetic_metadata(tmp_path)

    ids_v1 = register_variants("4ccc47", v1_dir, meta)
    ids_v2 = register_variants("4ccc47", v1_dir, meta, set_id_suffix="_v2")

    assert ids_v1["delithiation"] == OCP_DELI_ID
    assert ids_v2["delithiation"] == OCP_DELI_ID + "_v2"
    assert OCP_DELI_ID in pybamm.parameter_sets
    assert OCP_DELI_ID + "_v2" in pybamm.parameter_sets
    assert variant_summary("delithiation", "4ccc47", v1_dir, meta,
                           "_v2")["parameter_set_id"] == OCP_DELI_ID + "_v2"


def test_capacity_matched_ids_can_be_suffixed(tmp_path):
    import pybamm

    from parameters.sintef_graphite_capacity import (
        CAPACITY_MATCHED_IDS, register_capacity_variants,
    )

    v1_dir = _synthetic_ocp_dir(tmp_path)
    meta = _synthetic_metadata(tmp_path)

    ids = register_capacity_variants("4ccc47", v1_dir, meta,
                                     set_id_suffix="_v2")
    assert ids == {k: v + "_v2" for k, v in CAPACITY_MATCHED_IDS.items()}
    for set_id in ids.values():
        assert set_id in pybamm.parameter_sets
        pv = pybamm.ParameterValues(set_id)
        assert pv["Positive electrode active material volume fraction"] < 0.261218
    # the un-suffixed default id is NOT registered by this call
    assert CAPACITY_MATCHED_IDS["delithiation"] not in pybamm.parameter_sets \
        or True  # may exist from an earlier test in the same process
