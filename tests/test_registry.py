# ============================================================
# Battery Dataset Simulation Platform v0.1
# Registry tests (Step 11)
# ============================================================

import pytest

from battery_sim.registry import (
    get_dataset,
    get_dataset_config,
    list_datasets,
    RegistryError,
)


def test_list_datasets_has_chen2020():
    df = list_datasets()

    assert "chen2020" in df["ID"].tolist()

    row = df[df["ID"] == "chen2020"].iloc[0]

    assert row["Chemistry"] == "NMC_Graphite"
    assert row["Cells"] == "02,03,04"
    assert row["Parameter set"] == "Chen2020"


def test_get_dataset_config_fields():
    cfg = get_dataset_config("chen2020")

    assert cfg.name == "Chen2020 LG M50"
    assert cfg.cells == ["02", "03", "04"]
    assert cfg.rates == ["C10", "C2", "1C", "1p5C"]
    assert cfg.supported_models == ["SPM", "SPMe", "DFN"]
    assert cfg.parameter_set == "Chen2020"
    assert cfg.adapter == "chen2020"
    assert cfg.protocol == "chen2020"


def test_adapter_resolution_convention():
    adapter = get_dataset("chen2020")

    assert type(adapter).__name__ == "Chen2020Adapter"
    assert adapter.list_cells() == ["02", "03", "04"]


def test_unknown_dataset_raises():
    with pytest.raises(RegistryError):
        get_dataset_config("does_not_exist")
