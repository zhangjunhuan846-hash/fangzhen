"""``processing`` 工艺史契约的测试。

为什么这块必须单独立契约
    回收块（``recycling``）回答的是"材料从哪来"，它的必填性挂在
    ``material_class`` 上。而"对它做了什么"是**另一个维度**：热处理梯度实验里
    600/800/900 °C 就是自变量本身，与材料是不是回收料无关。缺了结构化的工艺，
    「两个都叫 800 °C」的样品（一个 Ar、一个空气）无法区分 ——
    样品身份不可追踪，D_s 的任何差异都无法归因。
"""
from __future__ import annotations

import pytest

from battery_sim.datasets.material_metadata import (
    PROCESSING_FIELDS,
    PROCESSING_REQUIRED_FIELDS,
    _main,
    mass_loss_pct,
    processing_summary,
    series_table,
    validate_processing,
    validate_series,
)


def _meta(sample_id="CG-800", paper_class="pristine", **processing):
    """一份最小元数据，``processing`` 由关键字给出（便于构造非法组合）。"""
    meta = {
        "sample_id": sample_id,
        "material_class": paper_class,
        "source": "本实验室 2026-09 批次",
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0, "area_cm2": 1.13},
        "particle": {"d50_um": 17.0},
        "cell": {"counter_electrode": "Li 片", "electrolyte": "1 M LiPF6"},
        "measurements": [{"technique": "GITT", "file": "g.csv"}],
        "structure": {},
    }
    if processing:
        meta["processing"] = processing
    return meta


GOOD = {"applied": True, "method": "管式炉热处理", "temperature_C": 800,
        "duration_h": 2, "atmosphere": "Ar"}


# ------------------------------------------------------------------
# 单份文件
# ------------------------------------------------------------------
def test_absent_processing_block_is_allowed_per_file():
    """单份接入不该被卡住 —— 梯度层面的强制在 validate_series。"""
    result = validate_processing(_meta())
    assert result["errors"] == [] and result["pending"] == []


def test_applied_true_requires_all_four_fields():
    for field in PROCESSING_REQUIRED_FIELDS:
        bad = dict(GOOD)
        bad.pop(field)
        result = validate_processing(_meta(**bad))
        assert any(field in e for e in result["errors"]), field


def test_applied_false_must_state_a_reason():
    """「没处理」也要有说法：它与「忘了写」在下游完全一样。"""
    result = validate_processing(_meta(applied=False))
    assert any("not_applied_reason" in e for e in result["errors"])
    ok = validate_processing(_meta(applied=False,
                                  not_applied_reason="未处理：参照系"))
    assert ok["errors"] == []
    assert any("未处理" in p for p in ok["pending"])


def test_applied_false_with_treatment_fields_is_contradictory():
    result = validate_processing(_meta(applied=False,
                                      not_applied_reason="未处理",
                                      temperature_C=800))
    assert any("自相矛盾" in w for w in result["warnings"])


def test_applied_must_be_a_bool_not_a_string():
    result = validate_processing(_meta(applied="true", **{
        k: v for k, v in GOOD.items() if k != "applied"}))
    assert any("布尔" in e for e in result["errors"])


def test_keys_are_a_closed_set():
    """自由键会让"这批样品到底怎么处理的"半年后无法回答。"""
    result = validate_processing(_meta(**{**GOOD, "quench_rate": 100}))
    assert any("未知键" in e for e in result["errors"])
    assert "quench_rate" not in PROCESSING_FIELDS


@pytest.mark.parametrize("field", ["temperature_C", "duration_h"])
def test_numeric_fields_must_be_positive(field):
    result = validate_processing(_meta(**{**GOOD, field: -1}))
    assert any("必须为正" in e for e in result["errors"])


def test_oxidative_atmosphere_at_high_temperature_warns_here_too():
    """同一条规矩要与 recycling 共用（一个实现，两个入口）。"""
    result = validate_processing(_meta(**{**GOOD, "atmosphere": "air"}))
    assert any("烧损" in w for w in result["warnings"])


def test_mass_gain_is_flagged():
    result = validate_processing(_meta(**{**GOOD, "mass_before_mg": 1000.0,
                                          "mass_after_mg": 1010.0}))
    assert any("处理前" in w for w in result["warnings"])


# ------------------------------------------------------------------
# 派生量
# ------------------------------------------------------------------
def test_mass_loss_is_computed_only_when_both_masses_are_there():
    assert mass_loss_pct(_meta(**GOOD)) is None
    assert mass_loss_pct(_meta(**{**GOOD, "mass_before_mg": 1000.0})) is None
    got = mass_loss_pct(_meta(**{**GOOD, "mass_before_mg": 1000.0,
                                 "mass_after_mg": 987.5}))
    assert got == pytest.approx(1.25)


def test_processing_summary_says_so_when_absent():
    """不留白：没声明就写"未声明"，不写空串。"""
    assert "未声明" in processing_summary(_meta())
    assert "未处理" in processing_summary(_meta(applied=False,
                                              not_applied_reason="参照系"))
    assert "800" in processing_summary(_meta(**GOOD))


# ------------------------------------------------------------------
# 系列级：每份合法 != 它们构成一条梯度
# ------------------------------------------------------------------
def _series():
    return [
        _meta("CG-AR", applied=False, not_applied_reason="参照系"),
        _meta("CG-600", **{**GOOD, "temperature_C": 600}),
        _meta("CG-800", **GOOD),
        _meta("CG-900", **{**GOOD, "temperature_C": 900}),
    ]


def test_a_well_formed_series_has_no_errors():
    assert validate_series(_series())["errors"] == []


def test_duplicate_sample_ids_are_an_error():
    metas = _series()
    metas[2]["sample_id"] = "CG-600"
    assert any("重复" in e for e in validate_series(metas)["errors"])


def test_missing_processing_block_is_an_error_at_series_level():
    """这正是「600 与 800 只差一个字符串」的情形。"""
    metas = _series()
    metas[1].pop("processing")
    errors = validate_series(metas)["errors"]
    assert any("processing" in e and "CG-600" in e for e in errors)


def test_identical_treatments_are_not_a_gradient():
    metas = _series()
    for meta in metas[1:]:
        meta["processing"] = dict(GOOD)
    assert any("不是一条梯度" in e for e in validate_series(metas)["errors"])


def test_repeated_treatment_is_a_warning_not_an_error():
    """同条件下的重复可能是平行批，不该判死，但必须问一句。"""
    metas = _series()
    metas[3]["processing"] = dict(GOOD)          # 800 与 900 变成同一工艺
    result = validate_series(metas)
    assert result["errors"] == []
    assert any("工艺完全相同" in w for w in result["warnings"])


def test_geometry_divergence_warns_because_it_contaminates_the_comparison():
    metas = _series()
    metas[1]["electrode"]["mass_loading_mg_cm2"] = 3.0   # 1.8 -> 3.0
    result = validate_series(metas)
    assert result["errors"] == []
    assert any("mass_loading" in w and "综合差异" in w for w in result["warnings"])


def test_series_table_prints_treatment_and_mass_loss():
    metas = _series()
    metas[1]["processing"]["mass_before_mg"] = 1000.0
    metas[1]["processing"]["mass_after_mg"] = 990.0
    text = series_table(metas)
    assert "sample_id" in text and "CG-900" in text
    assert "1.00 %" in text
    assert "未处理" in text


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def test_cli_on_a_series_reports_per_file_and_series(capsys, tmp_path):
    import yaml

    from battery_sim.datasets.material_metadata import load_metadata

    for meta in _series():
        (tmp_path / f"{meta['sample_id']}.yaml").write_text(
            yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    code = _main(["--series", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0                      # 系列合法（measurements 只声明了 GITT）
    assert "系列级" in out
    assert "PASS" in out
    assert load_metadata(tmp_path / "CG-800.yaml")["sample_id"] == "CG-800"
