"""L4 倍率预测验收脚本的单元测试（不需要跑 pybamm）。

覆盖的是**判据与措辞**，不是数值精度：
  · 参数覆盖只能走 JSON 的两种形态（数字 / 形状函数），写错要抛错
  · 角色门：辨识集不能当留出集（除非显式豁免且留理由）
  · 尺度判定用的是**电芯标称容量**，不是窗口电荷
    （部分窗口的 GCD 天然小于容量，拿它当分母会误杀）
  · 报告必须带三条口径（倍率外推 ≠ 独立验证 / 拟合好 ≠ 参数对 / 角色是声明）
  · 回放起点偏移是接线检查，要能从 time_aligned 表里读出来

端到端（真跑 SPM）在 ``scripts/dev/`` 的夹具流程里，不进 pytest：
  它需要 WSL 的 pybamm 环境，且已经在合成倍率梯夹具上实测过
  （真值参数 3.3 mV vs 零拟合负对照 20.1 mV）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from identification.rate_prediction import (
    OverrideBundle,
    PredictionProtocolError,
    _initial_offset_mV,
    load_overrides,
    render_report,
    role_gate,
    scale_record,
)

DS_KEY = "Positive particle diffusivity [m2.s-1]"


# ------------------------------------------------------------------
# 参数覆盖
# ------------------------------------------------------------------
def test_load_overrides_scalar_and_shape(tmp_path: Path):
    p = tmp_path / "ov.json"
    p.write_text(
        """
        {
          "provenance": "从 CG-800 的 0.1C + GITT 辨识",
          "overrides": {
            "Ds": {"shape": "constant", "amplitude_dex": -0.42},
            "Contact resistance [Ohm]": 12.5
          },
          "sources": {"Ds": {"source": "gitt_fitting"}}
        }
        """,
        encoding="utf-8",
    )
    bundle = load_overrides(p, "Ecker2015_graphite_halfcell")
    assert DS_KEY in bundle.overrides
    assert callable(bundle.overrides[DS_KEY])
    assert bundle.overrides["Contact resistance [Ohm]"] == 12.5
    assert bundle.provenance.startswith("从 CG-800")
    # 来源没写全 -> 只警告，不阻断（但报告里会写出来）
    assert any("来源未写" in w for w in bundle.warnings)


def test_load_overrides_bare_mapping_is_accepted(tmp_path: Path):
    p = tmp_path / "ov.json"
    p.write_text('{"Contact resistance [Ohm]": 3.0}', encoding="utf-8")
    bundle = load_overrides(p, "Ecker2015_graphite_halfcell")
    assert bundle.overrides == {"Contact resistance [Ohm]": 3.0}
    assert any("provenance" in w for w in bundle.warnings)


def test_load_overrides_rejects_unknown_shape(tmp_path: Path):
    p = tmp_path / "ov.json"
    p.write_text(
        '{"overrides": {"Ds": {"shape": "sigmoid", "amplitude_dex": 0.1}}}',
        encoding="utf-8",
    )
    with pytest.raises(PredictionProtocolError, match="未知形状"):
        load_overrides(p, "Ecker2015_graphite_halfcell")


def test_load_overrides_rejects_empty_and_missing(tmp_path: Path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"overrides": {}}', encoding="utf-8")
    with pytest.raises(PredictionProtocolError):
        load_overrides(empty, "Ecker2015_graphite_halfcell")
    with pytest.raises(PredictionProtocolError, match="找不到"):
        load_overrides(tmp_path / "nope.json", "Ecker2015_graphite_halfcell")


# ------------------------------------------------------------------
# 角色门
# ------------------------------------------------------------------
def _roles(tmp_path: Path, role: str) -> Path:
    p = tmp_path / "roles.yaml"
    p.write_text(
        "target_ds:\n"
        f'  dataset_role: "{role}"\n'
        "target_ds_note: toy\n",
        encoding="utf-8",
    )
    return p


def test_role_gate_refuses_identification_target(tmp_path: Path):
    cfg = _roles(tmp_path, "identification")
    with pytest.raises(PredictionProtocolError, match="辨识集不能当留出集"):
        role_gate("target_ds", "C1", roles_config=cfg)


def test_role_gate_allows_identification_only_when_exempted(tmp_path: Path):
    cfg = _roles(tmp_path, "identification")
    role, warns = role_gate(
        "target_ds", "C1", roles_config=cfg,
        allow_identification_target=True, reason="只验链路",
    )
    assert role == "identification"
    assert any("只验链路" in w for w in warns)
    assert any("不能说明预测能力" in w for w in warns)


def test_role_gate_validation_is_clean(tmp_path: Path):
    cfg = _roles(tmp_path, "validation")
    role, warns = role_gate("target_ds", "C1", roles_config=cfg)
    assert role == "validation"
    assert warns == []


def test_role_gate_benchmark_records_surrogate_caveat(tmp_path: Path):
    cfg = _roles(tmp_path, "benchmark")
    _, warns = role_gate("target_ds", "C1", roles_config=cfg)
    assert any("不构成验证" in w for w in warns)


def test_role_gate_undeclared_dataset_warns(tmp_path: Path):
    cfg = _roles(tmp_path, "validation")
    _, warns = role_gate("other_ds", "C1", roles_config=cfg)
    assert any("未在 datasets.yaml" in w for w in warns)


# ------------------------------------------------------------------
# 尺度判定
# ------------------------------------------------------------------
def _metrics(**over):
    base = {
        "median_current_A": 0.15625,
        "c_rate_measured": 1.0,
        "Q_exp_integrated_Ah": 0.0354,
    }
    base.update(over)
    return base


def test_scale_record_aligned_when_cell_capacity_declared():
    rec = scale_record(_metrics(), cell_nominal_Ah=0.15625)
    assert rec["verdict"] == "aligned"
    assert rec["model_nominal_capacity_Ah"] == pytest.approx(0.15625)
    assert rec["window_charge_fraction_of_model"] == pytest.approx(
        0.0354 / 0.15625
    )


def test_scale_record_flags_capacity_mismatch():
    """模型是 156 mAh 的电芯、记录来自 2 mAh 的硬币电池 -> 必须报失配。"""
    rec = scale_record(_metrics(), cell_nominal_Ah=0.0021)
    assert rec["verdict"] == "misaligned"
    assert rec["capacity_ratio_model_over_measured"] > 50


def test_scale_record_unknown_without_declared_capacity():
    """**不能**拿窗口电荷当分母：部分窗口的 GCD 天然小于容量。"""
    rec = scale_record(_metrics(), cell_nominal_Ah=None)
    assert rec["verdict"] == "unknown"
    assert rec["capacity_ratio_model_over_measured"] is None
    assert "窗口电荷不能代替电芯容量" in rec["basis"]


def test_scale_record_partial_window_is_not_a_mismatch():
    """同一颗电芯只跑 30 % DoD：容量声明一致 -> aligned（窗口小不是问题）。"""
    rec = scale_record(_metrics(Q_exp_integrated_Ah=0.047),
                       cell_nominal_Ah=0.15625)
    assert rec["verdict"] == "aligned"
    assert rec["window_charge_fraction_of_model"] == pytest.approx(0.30, abs=0.01)


# ------------------------------------------------------------------
# 回放起点偏移（接线检查）
# ------------------------------------------------------------------
def test_initial_offset_reads_time_aligned_table(tmp_path: Path):
    d = tmp_path / "run"
    d.mkdir()
    pd.DataFrame({
        "time_s": [0.0, 10.0],
        "voltage_exp_V": [0.1244, 0.1200],
        "voltage_sim_V": [0.1544, 0.1500],
        "residual_V": [0.03, 0.03],
    }).to_csv(d / "C1_time_aligned.csv", index=False)
    off = _initial_offset_mV(d, "C1")
    assert off == pytest.approx(30.0, abs=0.01)


def test_initial_offset_none_when_table_missing(tmp_path: Path):
    d = tmp_path / "run"
    d.mkdir()
    assert _initial_offset_mV(d, "C1") is None


# ------------------------------------------------------------------
# 报告措辞（红线）
# ------------------------------------------------------------------
def _record(role: str = "validation") -> dict:
    metrics = _metrics()
    return {
        "kind": "L4_rate_prediction",
        "fit": {
            "dataset": "ds_fit", "rate": "C0p2", "cell": "c1", "role": "identification",
            "metrics": dict(metrics, rmse_time_aligned_mV=2.0,
                            mae_time_aligned_mV=1.5, bias_time_aligned_mV=1.4,
                            max_abs_error_mV=9.0, coverage_fraction=1.0,
                            n_comparison_points=601),
            "output_dir": "/tmp/fit", "initial_offset_mV": 2.0,
        },
        "target": {
            "dataset": "ds_hold", "rate": "C1", "cell": "c1", "role": role,
            "metrics": dict(metrics, rmse_time_aligned_mV=3.3,
                            mae_time_aligned_mV=2.0, bias_time_aligned_mV=1.9,
                            max_abs_error_mV=11.0, coverage_fraction=1.0,
                            n_comparison_points=142),
            "output_dir": "/tmp/target", "applied_overrides": [],
            "initial_offset_mV": -1.0,
        },
        "overrides": {"provenance": "toy", "sources": {}, "keys": [DS_KEY]},
        "scale": scale_record(metrics, cell_nominal_Ah=0.15625),
        "alignment_mode": "check",
        "coverage_min": 0.8,
        "model_name": "SPM",
        "parameter_set": "Ecker2015_graphite_halfcell",
        "warnings": [],
        "failures": [],
        "link_ok": True,
    }


def test_report_carries_the_three_mandatory_stances():
    text = render_report(_record())
    assert "倍率外推，不是独立样品验证" in text
    assert "拟合好 ≠ 参数对" in text
    assert "声明出来的，不是证明出来的" in text
    # 两个 C-rate 必须并列，并点名只有后者决定激发
    assert "c_rate_on_cell" in text
    assert "c_rate_on_model_unscaled" in text
    assert "只有第二个数决定固相扩散是否被激发" in text
    # 起点偏移是接线检查
    assert "回放起点偏移" in text


def test_report_marks_benchmark_target_as_not_validation():
    text = render_report(_record(role="benchmark"))
    assert "不构成验证" in text


def test_report_fails_loudly_when_link_broken():
    rec = _record()
    rec["link_ok"] = False
    rec["failures"] = ["initial_state_wiring"]
    text = render_report(rec)
    assert "链路判定：FAIL" in text
    assert "initial_state_wiring" in text


def test_override_bundle_is_empty_by_default():
    assert OverrideBundle().is_empty()
