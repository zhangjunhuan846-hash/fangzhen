"""回收石墨：recycling 契约 + adapter 自检 + 协议接口 + 夹具解析。

三件事在这里被钉住：
  1. **样品身份可追踪**：回收/再生料的 recycling 块必填，且与结构化处理史二选一；
  2. **能力不假装**：协议接口覆盖了就说覆盖，且 `list_protocols()` 只返回
     `load_protocol` 真能接受的 id（dlr_gitt 的 wart 不许重演）；
  3. **夹具可解析**：committed 的合成夹具能被 adapter 读成 canonical 并通过契约校验。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.datasets.material_metadata import (
    recycling_identity,
    recycling_summary,
    validate,
)
from battery_sim.datasets.recycled_graphite import (
    DATASET_ID,
    DEFAULT_METADATA_REL,
    DEFAULT_ROOT_REL,
    LAYOUT_DIRS,
    METADATA_NAME,
    PENDING_SOURCE,
    RecycledGraphiteAdapter,
    main,
    render_check,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "synthetic_recycled_graphite"
FIXTURE_CELL = "SYN-fresh"


def _recycling(**over) -> dict:
    block = {
        "source": {
            "battery_type": "18650 NMC/石墨 动力电池（退役）",
            "cathode_type": "NMC532",
            "graphite_origin": "人造石墨",
        },
        "treatment": {
            "method": "热处理（Ar/H2 还原）",
            "temperature_C": 800.0,
            "duration_h": 2.0,
            "atmosphere": "Ar/H2 5%",
        },
    }
    block.update(over)
    return block


def _complete_metadata(**over) -> dict:
    meta = {
        "sample_id": "RG_500-a",
        "material_class": "regenerated",
        "recycling": _recycling(),
        "source": "本实验室 2026-09 批次",
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0,
                      "area_cm2": 1.54},
        "particle": {"d50_um": 12.0},
        "cell": {"counter_electrode": "Li φ15.6 mm",
                 "electrolyte": "1 M LiPF6 EC:DEC"},
        "measurements": [
            {"technique": "GITT", "file": "data/raw/LIB/rg/gitt.csv",
             "role": "identification"},
        ],
        "structure": {
            "xrd": {"available": False, "not_available_reason": "样品量不足"},
            "raman": {"available": False, "not_available_reason": "排期未到"},
            "bet": {"available": False, "not_available_reason": "未测"},
        },
    }
    meta.update(over)
    return meta


def _write_metadata(tmp_path, meta) -> str:
    import yaml

    path = tmp_path / "metadata.yaml"
    path.write_text(yaml.safe_dump(meta, allow_unicode=True),
                    encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------
# recycling 契约：样品身份可追踪
# ------------------------------------------------------------------
def test_recycling_block_is_required_for_recycled_and_regenerated():
    for cls in ("recycled", "regenerated"):
        meta = _complete_metadata(material_class=cls)
        del meta["recycling"]
        result = validate(meta)
        assert any("recycling" in e for e in result["errors"]), cls


def test_pristine_reference_does_not_need_a_recycling_block():
    meta = _complete_metadata(material_class="pristine")
    del meta["recycling"]
    assert validate(meta)["errors"] == []


def test_regeneration_condition_and_structured_treatment_are_alternatives():
    """结构化 recycling.treatment 填了就不必再写 regeneration_condition。"""
    with_block = _complete_metadata()
    with_block.pop("regeneration_condition", None)
    assert "regeneration_condition" not in validate(with_block)["missing"]

    without_block = _complete_metadata()
    del without_block["recycling"]
    result = validate(without_block)
    assert "regeneration_condition" in result["missing"]
    assert any("recycling" in e for e in result["errors"])


def test_every_recycling_field_is_required():
    for field in ("battery_type", "cathode_type", "graphite_origin"):
        meta = _complete_metadata()
        del meta["recycling"]["source"][field]
        assert any(f"source.{field}" in e
                   for e in validate(meta)["errors"]), field
    for field in ("method", "temperature_C", "duration_h", "atmosphere"):
        meta = _complete_metadata()
        del meta["recycling"]["treatment"][field]
        assert any(f"treatment.{field}" in e
                   for e in validate(meta)["errors"]), field


def test_oxidative_atmosphere_at_high_temperature_warns():
    """石墨在空气里 >500 °C 会被烧掉 —— 先确认气氛写法，别急着解释容量损失。"""
    meta = _complete_metadata()
    meta["recycling"]["treatment"]["atmosphere"] = "air"
    result = validate(meta)
    assert result["errors"] == []
    assert any("氧化" in w or "烧损" in w for w in result["warnings"])


def test_temperature_and_duration_must_be_numbers():
    meta = _complete_metadata()
    meta["recycling"]["treatment"]["temperature_C"] = "八百"
    assert any("temperature_C" in e for e in validate(meta)["errors"])
    meta = _complete_metadata()
    meta["recycling"]["treatment"]["duration_h"] = -1.0
    assert any("duration_h" in e for e in validate(meta)["errors"])


def test_recycling_identity_and_summary_are_reportable():
    identity = recycling_identity(_complete_metadata())
    assert identity["material_class"] == "regenerated"
    assert identity["temperature_C"] == 800.0
    text = recycling_summary(_complete_metadata())
    assert "NMC532" in text and "800" in text
    assert "未声明" in recycling_summary(
        {"material_class": "pristine", "sample_id": "x"})


# ------------------------------------------------------------------
# adapter 自检
# ------------------------------------------------------------------
def test_empty_template_passes(tmp_path):
    """导师 Step 2 的通过条件：什么都没有时 validate() 也要 ok。"""
    result = RecycledGraphiteAdapter(root=str(tmp_path)).validate()
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["pending"], "应当列出待办（metadata 未建、目录未建）"
    assert any("metadata" in p for p in result["pending"])


def test_empty_template_lists_every_layout_dir(tmp_path):
    result = RecycledGraphiteAdapter(root=str(tmp_path)).validate()
    assert set(result["layout"]) == set(LAYOUT_DIRS)
    assert all(v is False for v in result["layout"].values())


def test_require_data_turns_pending_into_errors(tmp_path):
    strict = RecycledGraphiteAdapter(root=str(tmp_path)).validate(
        require_data=True)
    assert strict["ok"] is False
    assert strict["pending"] == []
    assert any("require_data" in e for e in strict["errors"])


def test_metadata_ready_but_data_missing_is_still_ok(tmp_path):
    meta_path = _write_metadata(tmp_path, _complete_metadata())
    for rel in LAYOUT_DIRS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    result = RecycledGraphiteAdapter(root=str(tmp_path),
                                    metadata_path=meta_path).validate()
    assert result["ok"] is True, result["errors"]
    assert any("gitt.csv" in p for p in result["pending"])
    assert result["n_declared_files"] == 1


def test_undone_structure_is_a_gap_not_a_missing_data_item(tmp_path):
    """“确实没做 XRD”与“文件还没拷进来”必须分开：前者不该被严格模式判错。"""
    meta_path = _write_metadata(tmp_path, _complete_metadata())
    result = RecycledGraphiteAdapter(root=str(tmp_path),
                                    metadata_path=meta_path).validate(
        require_data=True)
    # "structure." 带点：`raw/structure/ 未建` 这类**布局**缺项确实该进错误，
    # 不该被误判成"结构表征没测"。
    assert not any("structure." in e for e in result["errors"])
    assert result["ok"] is False           # 目录/文件仍未到位
    assert any("structure." in g for g in result["gaps"])


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


def test_per_sample_metadata_is_discovered_from_the_fixture():
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    assert sorted(adapter.sample_metadata) == [
        "SYN-fresh", "SYN-regenerated", "SYN-spent"]
    assert adapter.list_cells() == ["SYN-fresh", "SYN-regenerated", "SYN-spent"]


def test_placeholder_source_yields_to_the_sample_metadata():
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    assert adapter.source != PENDING_SOURCE
    assert "SYNTHETIC" in adapter.source


def test_documented_default_paths():
    assert DATASET_ID == "recycled_graphite"
    assert DEFAULT_ROOT_REL == "data/raw/LIB/recycled_graphite"
    assert METADATA_NAME == "metadata.yaml"
    assert DEFAULT_METADATA_REL.endswith("/metadata.yaml")


# ------------------------------------------------------------------
# 协议接口：能力声明 + id 必须真能载入
# ------------------------------------------------------------------
def test_protocol_capability_is_declared_and_ids_are_loadable():
    assert (RecycledGraphiteAdapter.load_processed_protocol
            is not BatteryDatasetAdapter.load_processed_protocol)
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    ids = adapter.list_protocols()
    assert ids and all(i.startswith("GITT#w") for i in ids)
    for pid in ids:
        protocol = adapter.load_protocol(pid)
        assert [s.kind for s in protocol.segments] == [
            "rest", "pulse", "rest"]
        df = adapter.load_processed_protocol(FIXTURE_CELL, pid)
        assert df.attrs["initialisation"]["method"] == \
            "fixed_initial_concentration"


def test_each_window_starts_from_its_own_rest_state():
    """窗口共用一个初值会让六个窗口读数逐位相同（实测踩过）。"""
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    x0 = [adapter.load_processed_protocol(FIXTURE_CELL, pid)
          .attrs["initialisation"]["stoichiometry_from_ocp"]
          for pid in adapter.list_protocols()]
    assert len(set(round(v, 6) for v in x0)) == len(x0)


def test_unknown_window_is_rejected_loudly():
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    with pytest.raises(ValueError) as exc:
        adapter.load_protocol("GITT#w99")
    assert "GITT#w99" in str(exc.value)


def test_hooks_fail_loudly_when_the_files_are_missing(tmp_path):
    adapter = RecycledGraphiteAdapter(root=str(tmp_path))
    with pytest.raises(FileNotFoundError) as exc:
        adapter.read_source_table("nope")
    assert "make_synthetic_recycled_graphite" in str(exc.value)


# ------------------------------------------------------------------
# 夹具解析：canonical 契约
# ------------------------------------------------------------------
def test_fixture_discharge_passes_the_canonical_contract():
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    df = adapter.load_discharge(FIXTURE_CELL, "C0p2")
    check = df.attrs["contract_check"]
    assert check["ok"], check["errors"]
    assert abs(float(df["time_s"].iloc[0])) < 1e-9
    assert float(df["capacity_Ah"].iloc[-1]) > 0


def test_fixture_initial_state_is_the_leading_rest_median():
    adapter = RecycledGraphiteAdapter(root=str(FIXTURE))
    v0 = adapter.read_initial_state(FIXTURE_CELL)
    assert 0.1 < v0 < 1.5
    assert adapter.get_ambient_temperature(FIXTURE_CELL) == pytest.approx(25.0)


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
    text = render_check(RecycledGraphiteAdapter(root=str(tmp_path)).validate())
    assert "契约成立" in text and "等数据" in text
