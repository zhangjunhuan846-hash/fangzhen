"""回收石墨 adapter 的自检契约（导师 Step 2：空模板也要 PASS）。

同时守一件事：**这个 adapter 不许假装有它没有的能力**。
"""

from __future__ import annotations

import pytest

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.datasets.recycled_graphite import (
    DATASET_ID,
    DEFAULT_METADATA_REL,
    DEFAULT_ROOT_REL,
    LAYOUT_DIRS,
    PENDING_SOURCE,
    RecycledGraphiteAdapter,
    main,
    render_check,
)


def _complete_metadata() -> dict:
    """一份**契约完整**但结构还没测的材料元数据。"""
    return {
        "sample_id": "RG_500-a",
        "material_class": "recycled",
        "regeneration_condition": "500 C, Ar, 2 h",
        "source": "本实验室 2026-09 批次",
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0,
                      "area_cm2": 1.54},
        "particle": {"d50_um": 12.0},
        "cell": {"counter_electrode": "Li φ15.6 mm",
                 "electrolyte": "1 M LiPF6 EC:DEC"},
        "measurements": [
            {"technique": "GITT", "file": "data/raw/LIB/rg/gitt.txt",
             "role": "identification"},
        ],
        "structure": {
            "xrd": {"available": False,
                    "not_available_reason": "样品量不足"},
            "raman": {"available": False,
                      "not_available_reason": "排期未到"},
            "bet": {"available": False,
                    "not_available_reason": "未测"},
        },
    }


def _write_metadata(tmp_path, meta) -> str:
    import yaml

    path = tmp_path / "metadata.yaml"
    path.write_text(yaml.safe_dump(meta, allow_unicode=True),
                    encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------
# 空模板：契约成立、等数据
# ------------------------------------------------------------------
def test_empty_template_passes(tmp_path):
    """导师 Step 2 的通过条件：什么都没有时 validate() 也要 ok。"""
    adapter = RecycledGraphiteAdapter(root=str(tmp_path))
    result = adapter.validate()
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["pending"], "应当列出待办（metadata 未建、目录未建）"
    assert any("metadata.yaml" in p for p in result["pending"])


def test_empty_template_lists_every_layout_dir(tmp_path):
    result = RecycledGraphiteAdapter(root=str(tmp_path)).validate()
    assert set(result["layout"]) == set(LAYOUT_DIRS)
    assert all(v is False for v in result["layout"].values())


def test_require_data_turns_pending_into_errors(tmp_path):
    adapter = RecycledGraphiteAdapter(root=str(tmp_path))
    strict = adapter.validate(require_data=True)
    assert strict["ok"] is False
    assert strict["pending"] == []
    assert any("require_data" in e for e in strict["errors"])


def test_metadata_ready_but_data_missing_is_still_ok(tmp_path):
    meta_path = _write_metadata(tmp_path, _complete_metadata())
    for rel in LAYOUT_DIRS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    adapter = RecycledGraphiteAdapter(root=str(tmp_path),
                                     metadata_path=meta_path)
    result = adapter.validate()
    assert result["ok"] is True, result["errors"]
    assert any("gitt.txt" in p for p in result["pending"])
    assert result["n_declared_files"] == 1
    # 结构三个块都写了原因 ⇒ 出现在 pending 里而不是错误里
    assert sum("structure." in p for p in result["pending"]) == 3


def test_available_structure_without_a_file_is_pending_not_an_error(tmp_path):
    meta = _complete_metadata()
    meta["structure"]["raman"] = {
        "available": True, "file": "data/raw/LIB/rg/raman.txt",
        "role": "exploration", "laser_wavelength_nm": 532.0, "id_ig": 1.02,
        "source": {"type": "experiment", "instrument": "Horiba",
                   "operator": "ZJH", "date": "2026-09-20"},
    }
    meta_path = _write_metadata(tmp_path, meta)
    result = RecycledGraphiteAdapter(root=str(tmp_path),
                                     metadata_path=meta_path).validate()
    assert result["ok"] is True, result["errors"]
    assert "raman" in result["structure_available"]
    assert any("raman" in p and "未就位" in p for p in result["pending"])


def test_interpretation_key_makes_the_contract_fail(tmp_path):
    meta = _complete_metadata()
    meta["structure"]["raman"] = {
        "available": True, "file": "x.txt", "role": "exploration",
        "laser_wavelength_nm": 532.0, "id_ig": 1.02, "defect_level": "high",
        "source": {"type": "experiment", "instrument": "i", "operator": "o",
                   "date": "d"},
    }
    meta_path = _write_metadata(tmp_path, meta)
    result = RecycledGraphiteAdapter(root=str(tmp_path),
                                     metadata_path=meta_path).validate()
    assert result["ok"] is False
    assert any("defect_level" in e and "id_ig" in e for e in result["errors"])


# ------------------------------------------------------------------
# 能力声明与路径（契约，不是习惯）
# ------------------------------------------------------------------
def test_adapter_does_not_claim_recorded_protocol_capability():
    """没有数据就说没有数据能力：基类接口必须保持**未覆盖**。"""
    assert (RecycledGraphiteAdapter.load_processed_protocol
            is BatteryDatasetAdapter.load_processed_protocol)
    assert (RecycledGraphiteAdapter.load_protocol
            is BatteryDatasetAdapter.load_protocol)
    assert RecycledGraphiteAdapter.list_protocols is \
        BatteryDatasetAdapter.list_protocols


def test_placeholder_source_is_reported_rather_than_silently_accepted(tmp_path):
    adapter = RecycledGraphiteAdapter(root=str(tmp_path))
    assert adapter.source == PENDING_SOURCE
    assert any("source" in p for p in adapter.validate()["pending"])


def test_documented_default_paths():
    assert DATASET_ID == "recycled_graphite"
    assert DEFAULT_ROOT_REL == "data/raw/LIB/recycled_graphite"
    assert DEFAULT_METADATA_REL.endswith("/metadata.yaml")


def test_hooks_fail_loudly_until_data_arrives(tmp_path):
    adapter = RecycledGraphiteAdapter(root=str(tmp_path))
    for call in (adapter.read_source_table, adapter.read_initial_state,
                 adapter.read_ambient_temperature):
        with pytest.raises(NotImplementedError):
            call("RG_500-a")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def test_cli_exits_zero_on_an_empty_template(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "PENDING" in out


def test_cli_exits_nonzero_when_data_is_required(tmp_path):
    assert main(["--root", str(tmp_path), "--require-data"]) == 1


def test_render_check_explains_what_pass_means(tmp_path):
    result = RecycledGraphiteAdapter(root=str(tmp_path)).validate()
    text = render_check(result)
    assert "契约成立" in text
    assert "等数据" in text
