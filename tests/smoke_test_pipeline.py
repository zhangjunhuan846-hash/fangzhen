# ============================================================
# Battery Dataset Simulation Platform v0.1
# Pipeline smoke regression test (Step 11)
#
# Required automatic checks:
#   1. registry finds chen2020
#   2. adapter reads cell02
#   3. C10/C2/1C/1p5C available
#   4. SPMe model builds
#   5. reproduction cell02 completes
#   6. solution / coverage valid
#   7. per-rate RMSE inside tight deterministic tolerance
#      (cell02 SPMe golden: C10 82.33 / C2 115.81 /
#       1C 70.02 / 1p5C 46.84 mV, tolerance +/- 0.5 mV)
#
# The full reproduction solve happens once (module fixture).
# ============================================================

import pytest

from battery_sim.registry import get_dataset, list_datasets

pybamm = pytest.importorskip("pybamm")

from battery_sim.models.pybamm_factory import build_model  # noqa: E402
from battery_sim.simulation.reproduction import (  # noqa: E402
    run_reproduction_cell,
)


# ------------------------------------------------------------------
# 1. registry
# ------------------------------------------------------------------
def test_smoke_registry_finds_chen2020():
    df = list_datasets()
    assert "chen2020" in df["ID"].tolist()


# ------------------------------------------------------------------
# 2. adapter reads cell02 + 3. rates available
# ------------------------------------------------------------------
def test_smoke_adapter_reads_cell02():
    adapter = get_dataset("chen2020")
    raw = adapter.load_raw("02")
    assert not raw.empty


def test_smoke_all_rates_available():
    adapter = get_dataset("chen2020")
    rates = adapter.list_rates()
    for rate in ["C10", "C2", "1C", "1p5C"]:
        assert rate in rates


# ------------------------------------------------------------------
# 4. model builds
# ------------------------------------------------------------------
def test_smoke_spme_builds():
    model = build_model("SPMe")
    assert model.__class__.__name__ == "SPMe"


# ------------------------------------------------------------------
# 5-7. reproduction cell02 + regression (single solve)
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def cell02_spme_result():
    adapter = get_dataset("chen2020")
    return run_reproduction_cell(
        adapter,
        model_name="SPMe",
        cell="02",
        parameter_set="Chen2020",
        output_dir=None,
        plot=False,
        quiet=True,
    )


GOLDEN_RMSE_MV = {
    "C10": 82.33,
    "C2": 115.81,
    "1C": 70.02,
    "1p5C": 46.84,
}


def test_smoke_reproduction_completes(cell02_spme_result):
    metrics = cell02_spme_result["metrics"]

    assert len(metrics) == 4

    # 6. coverage / solution valid
    assert metrics["n_points"].min() > 0
    assert metrics["rmse_Qaligned_mV"].notna().all()

    for _, row in metrics.iterrows():
        assert row["Q_sim_Ah"] > 0.0
        assert row["cutoff_capacity_error_pct"] > -20.0


@pytest.mark.parametrize("rate", ["C10", "C2", "1C", "1p5C"])
def test_smoke_rmse_within_golden_tolerance(cell02_spme_result, rate):
    metrics = cell02_spme_result["metrics"]

    row = metrics[metrics["rate"] == rate].iloc[0]

    assert row["rmse_Qaligned_mV"] == pytest.approx(
        GOLDEN_RMSE_MV[rate],
        abs=0.5,
    )
