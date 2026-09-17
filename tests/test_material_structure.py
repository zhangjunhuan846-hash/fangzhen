"""结构表征契约（XRD / Raman / BET）：只收测量量、键是闭集、逐块来源。

这一层最容易出的错是把**解释**当数据写进来（`defect_level: high`），
或者把"没测"写成留空。两者在下游都无法与"测了什么"区分，所以都要拦。
"""

from __future__ import annotations

import pytest

from battery_sim.datasets.material_metadata import (
    INTERPRETATION_KEYS,
    SOURCE_TYPES,
    STRUCTURE_BLOCKS,
    STRUCTURE_FIELDS,
    STRUCTURE_REQUIRED,
    render,
    structure_available,
    structure_pending,
    validate,
    validate_structure,
)

SOURCE = {"type": "experiment", "instrument": "Horiba LabRAM",
          "operator": "ZJH", "date": "2026-09-20"}

KEY_FIELD = {"xrd": "d002_nm", "raman": "id_ig", "bet": "surface_area_m2_g"}


def _available(block: str, **over) -> dict:
    entry = {
        "xrd": {"available": True, "file": "raw/structure/xrd.raw",
                "role": "exploration", "wavelength_nm": 0.15406,
                "d002_nm": 0.336, "source": dict(SOURCE)},
        "raman": {"available": True, "file": "raw/structure/raman.txt",
                  "role": "exploration", "laser_wavelength_nm": 532.0,
                  "id_ig": 1.02, "source": dict(SOURCE)},
        "bet": {"available": True, "file": "raw/structure/bet.txt",
                "role": "exploration", "adsorption_gas": "N2",
                "surface_area_m2_g": 56.3, "pore_volume_cm3_g": 0.11,
                "pore_size_distribution": "raw/structure/bet_psd.csv",
                "source": dict(SOURCE)},
    }[block]
    entry.update(over)
    return entry


def _meta(structure) -> dict:
    return {
        "sample_id": "RG_500-a",
        "material_class": "recycled",
        "regeneration_condition": "500 C, Ar, 2 h",
        "source": "本实验室 2026-09 批次",
        "recycling": {
            "source": {"battery_type": "18650 NMC/石墨",
                       "cathode_type": "NMC532",
                       "graphite_origin": "人造石墨"},
            "treatment": {"method": "热处理", "temperature_C": 500.0,
                          "duration_h": 2.0, "atmosphere": "Ar"},
        },
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0, "area_cm2": 1.54},
        "particle": {"d50_um": 12.0},
        "cell": {"counter_electrode": "Li φ15.6 mm",
                 "electrolyte": "1 M LiPF6 EC:DEC"},
        "measurements": [{"technique": "GITT", "file": "gitt.txt",
                          "role": "identification"}],
        "structure": structure,
    }


# ------------------------------------------------------------------
# 闭集与必填
# ------------------------------------------------------------------
def test_every_block_allows_exactly_the_declared_fields():
    for block in STRUCTURE_BLOCKS:
        result = validate_structure(_meta({"xrd": _available("xrd")})) \
            if block == "xrd" else validate_structure(
                _meta({block: _available(block)}))
        assert result["errors"] == [], block
    # 白名单里的字段去掉必填项之后才应该报错
    assert "d002_nm" in STRUCTURE_FIELDS["xrd"]
    assert "pore_volume_cm3_g" in STRUCTURE_FIELDS["bet"]


@pytest.mark.parametrize("block", STRUCTURE_BLOCKS)
def test_available_block_requires_its_key_measurement(block):
    entry = _available(block)
    del entry[KEY_FIELD[block]]
    result = validate_structure(_meta({block: entry}))
    assert any(KEY_FIELD[block] in e for e in result["errors"])


@pytest.mark.parametrize("block", STRUCTURE_BLOCKS)
def test_available_block_requires_a_file_and_a_role(block):
    for missing in ("file", "role"):
        entry = _available(block)
        del entry[missing]
        errors = validate_structure(_meta({block: entry}))["errors"]
        assert any(missing in e for e in errors), (block, missing)


def test_bet_must_carry_pore_volume_not_only_area():
    """回石墨更关心孔结构：只留面积是这个契约明确要避免的写法。"""
    entry = _available("bet")
    del entry["pore_volume_cm3_g"]
    errors = validate_structure(_meta({"bet": entry}))["errors"]
    assert any("pore_volume_cm3_g" in e for e in errors)


def test_unknown_key_is_rejected_and_interpretation_keys_point_at_the_right_field():
    entry = _available("raman")
    entry["defect_level"] = "high"
    errors = validate_structure(_meta({"raman": entry}))["errors"]
    assert any("defect_level" in e and "id_ig" in e for e in errors)

    entry2 = _available("raman")
    entry2["graphitization"] = "good"
    errors2 = validate_structure(_meta({"raman": entry2}))["errors"]
    assert any("graphitization" in e for e in errors2)

    entry3 = _available("raman")
    entry3["mystery"] = 1
    errors3 = validate_structure(_meta({"raman": entry3}))["errors"]
    assert any("不在允许字段内" in e for e in errors3)


def test_every_interpretation_key_has_a_replacement_hint():
    for key, hint in INTERPRETATION_KEYS.items():
        assert hint.strip(), key
    assert "id_ig" in INTERPRETATION_KEYS["defect_level"]


# ------------------------------------------------------------------
# 来源（谁测的 / 哪台仪器 / 哪一天）
# ------------------------------------------------------------------
def test_source_must_name_type_instrument_operator_and_date():
    for missing in ("type", "instrument", "operator", "date"):
        src = dict(SOURCE)
        del src[missing]
        entry = _available("xrd", source=src)
        errors = validate_structure(_meta({"xrd": entry}))["errors"]
        assert any(f"source.{missing}" in e for e in errors), missing


def test_source_type_vocabulary_is_closed():
    entry = _available("xrd", source={**SOURCE, "type": "vibes"})
    errors = validate_structure(_meta({"xrd": entry}))["errors"]
    assert any("source.type" in e and "vibes" in e for e in errors)
    assert SOURCE_TYPES == ("experiment", "literature", "vendor", "estimate")


def test_source_must_be_a_mapping():
    entry = _available("xrd", source="Horiba")
    errors = validate_structure(_meta({"xrd": entry}))["errors"]
    assert any("source" in e and "mapping" in e for e in errors)


# ------------------------------------------------------------------
# 缺失处理方式
# ------------------------------------------------------------------
def test_unavailable_block_must_state_a_reason():
    entry = {"available": False}
    result = validate_structure(_meta({"bet": entry}))
    assert any("not_available_reason" in e for e in result["errors"])
    # 报了错就不再进 pending（缺席有说法 vs 没说法是两件事）
    assert not any("structure.bet" in p for p in result["pending"])


def test_unavailable_block_with_measurements_is_flagged():
    entry = {"available": False, "not_available_reason": "未测",
             "id_ig": 1.02, "file": "x.txt", "role": "exploration"}
    result = validate_structure(_meta({"raman": entry}))
    assert result["errors"] == []
    assert any("自相矛盾" in w for w in result["warnings"])
    assert any("raman" in p and "未测" in p for p in result["pending"])


def test_missing_block_is_pending_not_an_error():
    result = validate_structure(_meta({}))
    assert result["errors"] == []
    assert len(result["pending"]) == len(STRUCTURE_BLOCKS)


def test_structure_block_absent_entirely_is_pending():
    meta = _meta({})
    del meta["structure"]
    result = validate_structure(meta)
    assert result["errors"] == []
    assert any("structure" in p for p in result["pending"])


def test_structure_must_be_a_mapping():
    assert validate_structure({"structure": "xrd"})["errors"]


# ------------------------------------------------------------------
# 数值与单位（单位写在字段名里）
# ------------------------------------------------------------------
def test_implausible_value_warns_but_does_not_fail():
    entry = _available("xrd", d002_nm=3.36)      # 0.336 nm 少写一位小数
    result = validate_structure(_meta({"xrd": entry}))
    assert result["errors"] == []
    assert any("d002_nm" in w and "单位" in w for w in result["warnings"])


def test_negative_measurement_is_an_error():
    entry = _available("bet", surface_area_m2_g=-1.0)
    errors = validate_structure(_meta({"bet": entry}))["errors"]
    assert any("必须为正" in e for e in errors)


def test_non_numeric_measurement_is_an_error():
    entry = _available("raman", id_ig="high")
    errors = validate_structure(_meta({"raman": entry}))["errors"]
    assert any("不是数字" in e for e in errors)


def test_pore_size_distribution_accepts_a_path_or_a_mapping():
    ok_path = _available("bet", pore_size_distribution="psd.csv")
    assert validate_structure(_meta({"bet": ok_path}))["errors"] == []
    ok_map = _available("bet",
                        pore_size_distribution={"file": "psd.csv",
                                                "bins": 40})
    assert validate_structure(_meta({"bet": ok_map}))["errors"] == []
    bad = _available("bet", pore_size_distribution="")
    assert any("pore_size_distribution" in e
               for e in validate_structure(_meta({"bet": bad}))["errors"])


# ------------------------------------------------------------------
# 与总校验、报告渲染的接线
# ------------------------------------------------------------------
def test_full_validate_reports_structure_errors_and_pending():
    meta = _meta({"raman": _available("raman")})
    result = validate(meta)
    assert result["errors"] == []
    assert any("xrd" in p for p in result["pending"])
    assert any("bet" in p for p in result["pending"])


def test_helpers_split_available_from_pending():
    meta = _meta({"xrd": _available("xrd"),
                  "raman": {"available": False,
                            "not_available_reason": "排期未到"}})
    assert list(structure_available(meta)) == ["xrd"]
    assert any("raman" in p and "排期未到" in p
               for p in structure_pending(meta))


def test_render_shows_the_measured_value_and_the_gap():
    meta = _meta({"xrd": _available("xrd")})
    text = render(meta)
    assert "structure       :" in text
    assert "d002_nm=0.336nm" in text
    assert "structure gap   :" in text
