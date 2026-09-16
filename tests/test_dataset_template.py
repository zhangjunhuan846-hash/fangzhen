"""数据集接入契约的测试：canonical 格式、材料元数据、模板骨架。

这些测试守的是"换数据集时一定会踩的坑"——**四类陷阱都是静默的**，
所以必须有测试把它们钉成会报错的检查。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.datasets.material_metadata import (
    PARAMETER_SOURCE_VOCAB,
    load_metadata,
    missing_fields,
    render,
    validate,
    validate_parameter_source,
)
from battery_sim.datasets.template import (
    CANONICAL_COLUMNS,
    NewDatasetAdapter,
    validate_canonical,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_METADATA = (
    ROOT / "templates" / "recycled_graphite" / "metadata.example.yaml"
)


def _table(n: int = 11, *, current: float = 1e-3, v0: float = 0.8,
           dv: float = -0.01, t0: float = 0.0, dt: float = 100.0,
           scale_v: float = 1.0) -> pd.DataFrame:
    """一张干净的放电表（放大倍数只用来制造单位陷阱）。"""
    t = t0 + np.arange(n) * dt
    i = np.full(n, current)
    v = (v0 + np.arange(n) * dv) * scale_v
    charge = np.concatenate([[0.0], np.cumsum(i[1:] * dt)]) / 3600.0
    return pd.DataFrame({
        "time_s": t, "current_A": i, "voltage_V": v, "capacity_Ah": charge,
    })


# ------------------------------------------------------------------
# canonical 契约
# ------------------------------------------------------------------
def test_a_clean_discharge_passes():
    result = validate_canonical(_table(), what="toy",
                                expect_current_sign="discharge")
    assert result["ok"], result["errors"]
    assert result["stats"]["n_rows"] == 11


def test_missing_canonical_column_is_an_error_not_a_silent_reindex():
    df = _table().drop(columns=["capacity_Ah"])
    result = validate_canonical(df)
    assert not result["ok"]
    assert any("capacity_Ah" in e for e in result["errors"])


def test_zero_current_is_an_error():
    """整列零电流不是"没有结论"，是解析错了；必须报错。"""
    result = validate_canonical(_table(current=0.0))
    assert not result["ok"]
    assert any("电流整列为 0" in e for e in result["errors"])


def test_time_not_starting_at_zero_is_an_error():
    """绝对时间戳会让整条剖面平移，而平移在电压上看不出来。"""
    result = validate_canonical(_table(t0=1.7e9))
    assert not result["ok"]
    assert any("不是从 0 开始" in e for e in result["errors"])


def test_non_monotone_time_is_an_error():
    df = _table()
    df.loc[5, "time_s"] = df.loc[4, "time_s"]
    result = validate_canonical(df)
    assert not result["ok"]
    assert any("非递增" in e for e in result["errors"])


def test_voltage_in_millivolts_is_a_warning_not_an_error():
    """单位错是**能修**的，所以先 warn 再让人判断，而不是直接判死。"""
    result = validate_canonical(_table(scale_v=1000.0))
    assert result["ok"]
    assert any("mV" in w for w in result["warnings"])


def test_capacity_column_disagreeing_with_the_integral_is_a_warning():
    df = _table()
    df["capacity_Ah"] = df["capacity_Ah"] * 3.0
    result = validate_canonical(df)
    assert result["ok"]
    assert any("积分电荷" in w for w in result["warnings"])


def test_sign_convention_is_checked_against_the_declaration():
    df = _table(current=-1e-3)
    result = validate_canonical(df, expect_current_sign="discharge")
    assert any("符号翻转漏了" in w for w in result["warnings"])


def test_validate_canonical_reports_the_resolution_of_its_own_grid():
    result = validate_canonical(_table())
    assert result["stats"]["dt_min_s"] == result["stats"]["dt_max_s"] == 100.0


# ------------------------------------------------------------------
# 模板骨架
# ------------------------------------------------------------------
def _cfg(**kwargs) -> SimpleNamespace:
    base = dict(
        dataset_id="toy", name="toy", chemistry="graphite", ion="Li",
        raw_dir="", extra={}, cells=[], rates=[],
        nominal_capacity_Ah=None, lower_voltage_cutoff_V=None,
        upper_voltage_cutoff_V=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_template_refuses_to_construct_without_a_declared_source():
    with pytest.raises(ValueError) as exc:
        NewDatasetAdapter(_cfg())
    assert "extra.source" in str(exc.value)


def test_template_constructs_with_a_source_and_exposes_it():
    adapter = NewDatasetAdapter(_cfg(extra={"source": "doi:10.0000/toy"}))
    assert adapter.get_metadata()["source"] == "doi:10.0000/toy"


def test_template_does_not_claim_recorded_protocol_capability():
    """能力是"覆盖了才算"：模板必须保持基类接口未覆盖。

    否则 `type(adapter).load_processed_protocol is not Base.X` 会恒真，
    平台会以为每个新数据集都有录制型协议。
    """
    assert (NewDatasetAdapter.load_processed_protocol
            is BatteryDatasetAdapter.load_processed_protocol)
    assert (NewDatasetAdapter.load_protocol
            is BatteryDatasetAdapter.load_protocol)


def test_template_hooks_fail_loudly_with_a_checklist():
    adapter = NewDatasetAdapter(_cfg(extra={"source": "doi:10.0000/toy"}))
    for call in (adapter.read_source_table, adapter.read_initial_state,
                 adapter.read_ambient_temperature):
        with pytest.raises(NotImplementedError):
            call("cell-1")


def test_load_discharge_returns_canonical_columns_in_contract_order():
    class ToyAdapter(NewDatasetAdapter):
        def read_source_table(self, cell):
            return _table()

        def select_discharge_window(self, raw, cell, rate):
            return raw[list(CANONICAL_COLUMNS)[::-1]]      # 故意乱序

        def read_initial_state(self, cell):
            return 0.8

        def read_ambient_temperature(self, cell):
            return 25.0

    adapter = ToyAdapter(_cfg(extra={"source": "doi:10.0000/toy"}))
    df = adapter.load_discharge("cell-1", "c10")
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert df.attrs["contract_check"]["ok"] is True
    assert df.attrs["canonical_convention"] == "discharge = +A"


# ------------------------------------------------------------------
# 材料元数据
# ------------------------------------------------------------------
def test_missing_fields_are_listed_instead_of_guessed():
    missing = missing_fields({})
    for path in ("sample_id", "electrode.mass_loading_mg_cm2",
                 "particle.d50_um", "cell.electrolyte", "measurements"):
        assert path in missing


def test_regeneration_condition_is_required_for_recycled_material():
    meta = {"material_class": "recycled"}
    assert "regeneration_condition" in missing_fields(meta)
    meta["regeneration_condition"] = "500 C, Ar, 2 h"
    assert "regeneration_condition" not in missing_fields(meta)


def _complete_metadata(**overrides) -> dict:
    meta = {
        "sample_id": "RG_500-a",
        "material_class": "recycled",
        "regeneration_condition": "500 C, Ar, 2 h",
        "source": "本实验室 2026-08 批次",
        "electrode": {"mass_loading_mg_cm2": 1.8,
                      "coating_thickness_um": 45.0,
                      "area_cm2": 1.54},
        "particle": {"d50_um": 12.0},
        "cell": {"counter_electrode": "Li φ15.6 mm",
                 "electrolyte": "1 M LiPF6 EC:DEC"},
        "measurements": [
            {"technique": "GITT", "file": "gitt.txt",
             "role": "identification"},
        ],
    }
    meta.update(overrides)
    return meta


def test_complete_metadata_passes_with_warnings_only():
    result = validate(_complete_metadata())
    assert result["errors"] == []
    assert any("EIS" in w for w in result["warnings"])


def test_unknown_technique_is_an_error():
    meta = _complete_metadata(measurements=[
        {"technique": "EIS_ish", "file": "x.txt"},
    ])
    result = validate(meta)
    assert any("TECHNIQUE_VOCAB" in e or "不在词表" in e for e in result["errors"])


def test_measurement_without_a_file_is_an_error():
    meta = _complete_metadata(measurements=[
        {"technique": "GITT", "file": ""},
    ])
    result = validate(meta)
    assert any("缺 file" in e for e in result["errors"])


def test_negative_geometry_is_an_error():
    meta = _complete_metadata()
    meta["particle"]["d50_um"] = -3.0
    assert any("必须为正" in e for e in validate(meta)["errors"])


def test_parameter_source_vocabulary_is_closed():
    assert validate_parameter_source("Ds", "gitt_fitting") == "gitt_fitting"
    with pytest.raises(ValueError):
        validate_parameter_source("Ds", "拟合得到")
    assert "not_measured" in PARAMETER_SOURCE_VOCAB


def test_example_template_stays_incomplete_on_purpose():
    """模板必须保持"填完才能用"：它一旦能通过校验，就说明有人填了假值。"""
    result = validate(load_metadata(EXAMPLE_METADATA))
    assert result["errors"], "示例模板应当是未填状态"
    assert "sample_id" in result["missing"]


def test_metadata_render_says_what_to_do_when_absent():
    text = render(None)
    assert "未提供" in text
    assert "D ∝ R²" in text
