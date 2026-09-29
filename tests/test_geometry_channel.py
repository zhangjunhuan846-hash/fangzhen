"""几何 → 模型 参数通路（governance/geometry_channel.py）的契约测试。

这个通路存在的理由只有一个：**实测值此前到不了模型**。
所以测试必须钉住的不是"函数能跑"，而是：

  * 四个实测量缺一项就**整块不给**（不部分覆盖 —— 混合几何无法复算）
  * 每一键都带 source（值 / 来自哪个元数据 / 公式）
  * `R_p` 与 `L` 的换算**只有一种口径**（D50/2；不是 D50，不是 D10/2）
  * 与尺度对齐门冲突时**硬失败**，不静默挑一个（双重缩放是最坏的错）
  * 报告行必须写出用的是哪个 R —— 不打印就等于把粒径变化读成扩散变化
  * 它**不碰**冻结内核（不 import baseline / pybamm_factory）

最后一条用 AST 检查：只要有人把通路接到校验路径上去，
"数据还没到"就会变成"导入即失败"。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from governance.geometry_channel import (
    CHANNEL_KEYS,
    REQUIRED_MEASUREMENTS,
    SCALE_ALIGNMENT_KNOBS,
    assert_geometry_channel_consistent,
    geometry_channel_conflicts,
    geometry_override_channel,
    radius_report_line,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "commercial_graphite_ht" / "metadata"

#: 一份"填齐了"的最小元数据。**故意用假数**，只测通路不测物理。
FILLED = {
    "sample_id": "TEST-FILLED",
    "material_class": "pristine",
    "source": "test:geometry-channel",
    "electrode": {
        "mass_loading_mg_cm2": 1.8,
        "coating_thickness_um": 74.0,
        "area_cm2": 1.13097,
        "binder": "PVDF:SuperP:active = 8:1:91",
        "porosity": 0.33,
    },
    "particle": {"d50_um": 17.58},
    "cell": {
        "format": "CR2032",
        "counter_electrode": "Li 片 φ15.6 mm × 0.45 mm（过量）",
        "counter_electrode_type": "lithium_metal",
        "working_electrode_material": "graphite",
        "voltage_window_V": [0.005, 1.5],
        "electrolyte": "1 M LiPF6 in EC:DEC = 1:1",
        "separator": "Celgard 2400",
        "assembly_environment": "H2O < 1 ppm, O2 < 1 ppm",
    },
    "processing": {
        "applied": False,
        "not_applied_reason": "test fixture：未处理参照系",
    },
    "measurements": [
        {
            "technique": "CC_charge_discharge",
            "file": "data/raw/graphite_ht/TEST-FILLED/raw/electrochemistry/gcd_0p1C.csv",
            "role": "identification",
            "notes": "test fixture",
        }
    ],
    "parameter_sources": {"Ds": None, "k0": None, "Rct": None},
    "structure": {},
}


@pytest.fixture
def filled_meta(tmp_path):
    p = tmp_path / "TEST-FILLED.yaml"
    p.write_text(yaml.safe_dump(FILLED, allow_unicode=True), encoding="utf-8")
    return p


def _unfill(meta, dotted):
    """把某个点路径置空（模拟"数据还没到"）。"""
    node = meta
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = None
    return meta


# ------------------------------------------------------------------
# 1. 缺项 = 整块不给
# ------------------------------------------------------------------
@pytest.mark.parametrize("field", REQUIRED_MEASUREMENTS)
def test_missing_any_measurement_blocks_the_whole_channel(filled_meta, tmp_path, field):
    """缺**任一**实测量，四个覆盖一个都不给 —— 不部分覆盖。"""
    meta = _unfill(
        {k: (dict(v) if isinstance(v, dict) else v) for k, v in FILLED.items()},
        field,
    )
    # 深拷贝嵌套（_unfill 会就地改）
    import copy

    meta = copy.deepcopy(FILLED)
    _unfill(meta, field)
    p = tmp_path / f"missing_{field.replace('.', '_')}.yaml"
    p.write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")

    rec = geometry_override_channel(p)
    assert rec["incomplete"] is True
    assert rec["complete"] is False
    assert field in rec["missing"]
    assert "parameter_overrides" not in rec, (
        "不完整时**不能**给出覆盖 —— 部分覆盖会产生混合几何"
    )
    assert "parameter_override_sources" not in rec
    assert field in rec["reason"]


def test_missing_blocks_even_with_require_complete_false_by_default(filled_meta):
    """完整时给出覆盖；且 **不是** 部分覆盖（键数恰好等于 CHANNEL_KEYS）。"""
    rec = geometry_override_channel(filled_meta)
    assert rec["complete"] is True
    assert set(rec["parameter_overrides"]) == set(CHANNEL_KEYS)


def test_require_complete_raises_instead_of_returning(filled_meta, tmp_path):
    import copy

    meta = copy.deepcopy(FILLED)
    _unfill(meta, "particle.d50_um")
    p = tmp_path / "strict.yaml"
    p.write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KeyError) as exc:
        geometry_override_channel(p, require_complete=True)
    assert "particle.d50_um" in str(exc.value)


# ------------------------------------------------------------------
# 2. 换算口径只有一种
# ------------------------------------------------------------------
def test_radius_is_d50_over_two_not_d50(filled_meta):
    rec = geometry_override_channel(filled_meta)
    assert rec["radius_used_m"] == pytest.approx(17.58e-6 / 2.0)
    assert rec["thickness_used_m"] == pytest.approx(74.0e-6)
    # 反例：写成 D50 会差整整 2 倍
    assert rec["radius_used_m"] != pytest.approx(17.58e-6)


def test_every_override_carries_a_source(filled_meta):
    rec = geometry_override_channel(filled_meta)
    src = rec["parameter_override_sources"]
    assert set(src) == set(rec["parameter_overrides"])
    for key in CHANNEL_KEYS:
        entry = src[key]
        assert entry["value"] == pytest.approx(rec["parameter_overrides"][key])
        assert entry["source"] == "measured"
        assert str(filled_meta) in entry["origin"], (
            "来源必须指向具体元数据文件（否则半年后无人能复算）"
        )
        assert entry["formula"], f"{key} 缺公式说明"


def test_channel_deliberately_does_not_cover_porosity(filled_meta):
    """载量与真密度算 eps_am 需要配方，本通路**不猜**。"""
    rec = geometry_override_channel(filled_meta)
    assert "Positive electrode porosity" not in rec["parameter_overrides"]
    assert "Positive electrode porosity" in rec["not_covered"]


# ------------------------------------------------------------------
# 3. 报告行必须写出 R
# ------------------------------------------------------------------
def test_report_line_names_the_radius(filled_meta):
    rec = geometry_override_channel(filled_meta)
    line = radius_report_line(rec)
    assert "17.58" in line and "8.790" in line, line
    assert "实测" in line


def test_report_line_says_parameter_set_default_when_incomplete(tmp_path):
    import copy

    meta = copy.deepcopy(FILLED)
    _unfill(meta, "particle.d50_um")
    p = tmp_path / "incomplete.yaml"
    p.write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    rec = geometry_override_channel(p)
    line = radius_report_line(rec)
    assert "参数集默认值" in line
    assert "不能据此解释" in line or "不能" in line


# ------------------------------------------------------------------
# 4. 与尺度对齐门冲突 = 硬失败
# ------------------------------------------------------------------
def test_align_mode_conflicts_and_refuses():
    problems = geometry_channel_conflicts(scale_alignment_mode="align")
    assert problems, "align 与几何通路会双重缩放容量，必须报冲突"
    joined = " ".join(problems)
    for knob in SCALE_ALIGNMENT_KNOBS:
        assert knob in joined
    with pytest.raises(ValueError) as exc:
        assert_geometry_channel_consistent(
            scale_alignment_mode="align", context="TEST"
        )
    assert "TEST" in str(exc.value)


@pytest.mark.parametrize("mode", ["check", "assume", None])
def test_non_align_modes_do_not_conflict(mode):
    assert geometry_channel_conflicts(scale_alignment_mode=mode) == []


def test_caller_supplied_channel_keys_conflict():
    """调用方已提供同一键 ⇒ 通路会覆盖它 ⇒ 必须报，不静默改。"""
    problems = geometry_channel_conflicts(
        scale_alignment_mode="check",
        parameter_overrides={"Positive particle radius [m]": 6.0e-6},
    )
    assert problems
    assert "Positive particle radius [m]" in " ".join(problems)


def test_geometry_keys_and_knobs_do_not_overlap():
    """两套旋钮必须**不相交** —— 相交就意味着双重缩放是可能的。"""
    assert not (set(CHANNEL_KEYS) & set(SCALE_ALIGNMENT_KNOBS))


# ------------------------------------------------------------------
# 5. 不碰冻结内核
# ------------------------------------------------------------------
def test_channel_does_not_import_the_frozen_kernel():
    """几何通路只做翻译。一旦它 import 校验路径，'数据还没到'会变成'导入即失败'。"""
    src = (ROOT / "governance" / "geometry_channel.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {
        "battery_sim.simulation.baseline",
        "battery_sim.simulation.protocol_replay",
        "battery_sim.models.pybamm_factory",
        "run_pipeline",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name)
    hit = {m for m in imported if m in banned}
    assert not hit, f"几何通路不得 import 冻结内核：{sorted(hit)}"


def test_channel_module_is_pure_stdlib_plus_metadata():
    """不得 import numpy/pandas/pybamm —— 它是翻译层，不是计算层。"""
    src = (ROOT / "governance" / "geometry_channel.py").read_text(encoding="utf-8")
    for heavy in ("import numpy", "import pandas", "import pybamm"):
        assert heavy not in src, f"几何通路出现了 {heavy}"


# ------------------------------------------------------------------
# 6. 仓库里的真实模板：现在应当全部"不完整"（数据还没到）
# ------------------------------------------------------------------
def test_real_templates_are_incomplete_today():
    """四份模板故意留空 7 个人填量 ⇒ 通路今天应报 incomplete。

    这不是失败，是"数据还没到"的正确表达。**若哪天它们变成 complete，
    说明有人填了数** —— 那时这条测试要改成断言覆盖值，而不是删掉它。
    """
    samples = ("CG-AR", "CG-600", "CG-800", "CG-900")
    for sample in samples:
        p = TEMPLATE_DIR / f"{sample}.yaml"
        if not p.is_file():
            pytest.skip(f"{p} 不在仓库")
        rec = geometry_override_channel(p)
        assert rec["incomplete"] is True, (
            f"{sample}: 模板被填了实测值 —— 请把本测试改成断言实际覆盖值"
        )
        # 缺的必须是四个人填量（或它们的子集），不是别的
        assert set(rec["missing"]) <= set(REQUIRED_MEASUREMENTS)
        assert "parameter_overrides" not in rec
