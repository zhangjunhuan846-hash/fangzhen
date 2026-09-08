# ============================================================
# Battery Dataset Simulation Platform v0.1
# Chen2020 adapter tests (Step 11)
#
# Expected values come from the validated reference data
# (cell02 raw record) and the reproduction golden outputs.
# ============================================================

import pytest

from battery_sim.registry import get_dataset


@pytest.fixture(scope="module")
def adapter():
    return get_dataset("chen2020")


@pytest.fixture(scope="module")
def cell02(adapter):
    return adapter.load_raw("02")


def test_raw_load_columns(adapter):
    df = adapter.load_raw("02")

    assert not df.empty

    for col in [
        "Cycle C",
        "Step",
        "Test Time [s]",
        "Step Time [s]",
        "Capacity [Ah]",
        "Current [A]",
        "Voltage [V]",
        "Md",
        "Temperature Chamber [degC]",
    ]:
        assert col in df.columns


def test_initial_voltage_cell02(adapter):
    # reference: ~3.1315 V (tail-of-rest median)
    assert adapter.get_initial_state("02") == pytest.approx(
        3.13150,
        abs=5e-4,
    )


def test_ambient_temperature_cell02(adapter):
    # reference: chamber median over pre-discharge rests ~26.71 degC
    assert adapter.get_ambient_temperature("02") == pytest.approx(
        26.71,
        abs=0.05,
    )


@pytest.mark.parametrize(
    "rate, expected_q",
    [
        ("C10", 4.998),
        ("C2", 4.924),
        ("1C", 4.930),
        ("1p5C", 4.923),
    ],
)
def test_discharge_cutoff_capacity(adapter, rate, expected_q):
    df = adapter.load_discharge("02", rate)

    assert not df.empty

    for col in ["time_s", "current_A", "voltage_V", "capacity_Ah"]:
        assert col in df.columns

    assert df["capacity_Ah"].iloc[-1] == pytest.approx(
        expected_q,
        abs=5e-3,
    )


def test_list_rates(adapter):
    assert adapter.list_rates() == ["C10", "C2", "1C", "1p5C"]
