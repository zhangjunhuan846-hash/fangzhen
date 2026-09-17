"""材料元数据入口的电压窗口检查（`material_metadata.validate_voltage_window`）。

这条门存在的唯一理由：**同一份规则要覆盖两个入口**。
自服务导入通道（`user_tools/validate.py`）查了，材料元数据入口也必须查 ——
否则会出现「demo 数据很严格、自己的实验数据反而绕过」。
所以这里的用例一半在验行为，一半在验「规则确实只有一份」。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from battery_sim.datasets.chemistry_windows import (
    COUNTER_ELECTRODE_TYPES,
    SYS_GRAPHITE_HALFCELL_LI,
    WORKING_ELECTRODE_MATERIALS,
    resolve_system,
)
from battery_sim.datasets.material_metadata import (
    validate as validate_metadata,
    validate_voltage_window,
)
from user_tools import spec

TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / \
    "commercial_graphite_ht" / "metadata"


def _meta(**cell_over):
    cell = {
        "format": "CR2032",
        "counter_electrode": "Li 片 φ15.6 mm × 0.45 mm（过量）",
        "counter_electrode_type": "lithium_metal",
        "working_electrode_material": "graphite",
        "voltage_window_V": [0.005, 1.5],
        "electrolyte": "1 M LiPF6 in EC:DEC = 1:1",
        "separator": "Celgard 2400",
        "assembly_environment": "<1 ppm H2O/O2",
    }
    cell.update(cell_over)
    return {"sample_id": "CG-X", "material_class": "pristine", "cell": cell}


# ------------------------------------------------------------------
# 判据
# ------------------------------------------------------------------
def test_graphite_window_passes():
    res = validate_voltage_window(_meta())
    assert res["errors"] == []
    assert res["warnings"] == []


def test_window_wider_than_hard_bounds_is_an_error():
    res = validate_voltage_window(_meta(voltage_window_V=[0.001, 15.0]))
    assert any("物理界" in e for e in res["errors"])


def test_window_outside_nominal_only_warns():
    """2.0 V 上限是合法的深脱锂实验 -> 只警告（与自服务通道同一口径）。"""
    res = validate_voltage_window(_meta(voltage_window_V=[0.005, 2.0]))
    assert res["errors"] == []
    assert any("常用窗口" in w for w in res["warnings"])


def test_missing_declaration_skips_with_reason_not_pass():
    res = validate_voltage_window(
        _meta(working_electrode_material=None, counter_electrode_type=None)
    )
    assert res["errors"] == []
    assert any("被跳过" in w and "跳过 ≠ 通过" in w for w in res["warnings"])


def test_missing_window_value_warns():
    res = validate_voltage_window(_meta(voltage_window_V=None))
    assert res["errors"] == []
    assert any("cell.voltage_window_V" in w for w in res["warnings"])


def test_bad_closed_set_values_are_errors():
    res = validate_voltage_window(
        _meta(working_electrode_material="hard_carbon")
    )
    assert any("不在词表" in e for e in res["errors"])
    res2 = validate_voltage_window(_meta(counter_electrode_type="sodium"))
    assert any("不在词表" in e for e in res2["errors"])


def test_window_shape_is_checked():
    res = validate_voltage_window(_meta(voltage_window_V=[0.005]))
    assert any("必须是" in e for e in res["errors"])
    # 也接受 {lower_V, upper_V} 写法（人写 yaml 时两种都很自然）
    res2 = validate_voltage_window(
        _meta(voltage_window_V={"lower_V": 0.005, "upper_V": 1.5})
    )
    assert res2["errors"] == []


def test_window_check_is_part_of_full_validation():
    """整份 validate() 里必须能看到这条门的结果（不能只在单测里成立）。"""
    meta = _meta(voltage_window_V=[0.001, 15.0])
    meta.update({
        "source": "toy",
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0, "area_cm2": 86.0},
        "particle": {"d50_um": 12.0},
        "measurements": [{"technique": "GITT", "file": "x.csv",
                          "role": "identification"}],
    })
    res = validate_metadata(meta)
    assert any("cell.voltage_window_V" in e for e in res["errors"])


# ------------------------------------------------------------------
# 构型/材料这一对声明
# ------------------------------------------------------------------
def test_electrode_pair_alone_resolves_half_cell():
    """`working_electrode_material=graphite` + `counter=lithium_metal`
    这一对本身就唯一确定半电池（全电池没有锂金属对电极）——
    不需要再声明 cell_configuration。"""
    window, why = resolve_system(
        working_electrode_material="graphite", counter_electrode="lithium_metal"
    )
    assert why == ""
    assert window is not None and window.system_id == SYS_GRAPHITE_HALFCELL_LI


def test_contradictory_declaration_is_refused_not_guessed():
    """写成 full_cell 却有锂金属对电极 -> 报矛盾，而不是挑一个信。"""
    window, why = resolve_system(
        chemistry="NMC", cell_configuration="full_cell",
        counter_electrode="lithium_metal",
        working_electrode_material="graphite",
    )
    assert window is None
    assert "自相矛盾" in why


def test_no_configuration_and_no_decisive_pair_is_not_guessed():
    window, why = resolve_system(chemistry="NMC")
    assert window is None
    assert "未声明" in why


# ------------------------------------------------------------------
# 规则只有一份（防止"两个入口两套标准"）
# ------------------------------------------------------------------
def test_vocabularies_have_a_single_source():
    """两个入口的词表必须来自 chemistry_windows.py（加新体系时不会只改一半）。"""
    assert list(spec.ALLOWED_WORKING_ELECTRODE_MATERIAL) == \
        [*WORKING_ELECTRODE_MATERIALS, ""]
    assert list(spec.ALLOWED_COUNTER_ELECTRODE) == \
        [*COUNTER_ELECTRODE_TYPES, ""]


# ------------------------------------------------------------------
# 四个真实模板
# ------------------------------------------------------------------
@pytest.mark.parametrize("name", ["CG-AR", "CG-600", "CG-800", "CG-900"])
def test_templates_declare_the_anchor_fields(name):
    """模板必须自带锚定声明（否则四个真实样品全会掉进"检查被跳过"）。"""
    meta = yaml.safe_load((TEMPLATES / f"{name}.yaml").read_text(encoding="utf-8"))
    res = validate_voltage_window(meta)
    assert not [w for w in res["warnings"] if "被跳过" in w], res["warnings"]
    assert res["errors"] == []
