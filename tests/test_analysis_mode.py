"""分析模式与判定词汇的测试。

守两件事：
  1. 判定规则是**声明的表格**，不是随手写的阈值
  2. material 模式下 benchmark 专属内容**进不来**（否则会把模拟写成实验结论）
"""

from __future__ import annotations

import pytest

from governance.analysis_mode import (
    ALLOWED_VERDICTS,
    MODE_BENCHMARK,
    MODE_MATERIAL,
    ModeViolation,
    VERDICT_BOUNDED,
    VERDICT_IDENTIFIABLE,
    VERDICT_NOT_IDENTIFIABLE,
    VERDICT_NOT_MEASURED,
    VERDICT_UNCONSTRAINED,
    assert_benchmark_only,
    check_payload,
    classify_band,
    normalise_mode,
    party_role_caution,
    render_verdict,
)

LIMIT = 0.30
LEVEL = 1.0
SCAN = 2.0


def _band(width, *, left=None, right=None, tl=False, tr=False, res=0.05,
          n_points=43):
    return {
        "width_dex": width, "left_dex": left, "right_dex": right,
        "truncated_left": tl, "truncated_right": tr,
        "resolution_dex": res, "n_points": n_points,
    }


# ------------------------------------------------------------------
# 判定表
# ------------------------------------------------------------------
def test_narrow_untruncated_band_is_identifiable():
    result = classify_band(_band(0.0988, left=0.05, right=0.0488),
                           level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_IDENTIFIABLE
    assert result["reportable_value_kind"] == "value"


def test_wide_untruncated_band_is_not_identifiable():
    result = classify_band(_band(0.90, left=0.5, right=0.4),
                           level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_NOT_IDENTIFIABLE
    assert result["reportable_value_kind"] == "none"


def test_one_sided_truncation_is_bounded_and_forbids_a_point_estimate():
    """左侧截断 ⇒ a 没有下界，可报的是**上界**。"""
    result = classify_band(_band(1.4, left=1.0, right=0.4, tl=True),
                           level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_BOUNDED
    assert result["reportable_value_kind"] == "one_sided_upper_bound"
    assert result["bounded_side"] == "upper"
    assert "上界" in result["reason"]


def test_right_truncation_gives_the_g6_1c_case_a_lower_bound_on_the_parameter():
    """G6.1c 实测缺的那一半在 D_s 偏大侧 ⇒ 只给下界。"""
    result = classify_band(_band(1.35, left=0.35, right=1.0, tr=True),
                           level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_BOUNDED
    assert result["reportable_value_kind"] == "one_sided_lower_bound"
    assert "下界" in result["reason"]


def test_both_sides_truncated_is_unconstrained():
    result = classify_band(_band(2.0, left=1.0, right=1.0, tl=True, tr=True),
                           level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_UNCONSTRAINED
    assert result["reportable_value_kind"] == "none"


def test_absent_band_is_not_measured():
    result = classify_band(None, level_mV=LEVEL, limit_dex=LIMIT,
                           scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_NOT_MEASURED


def test_zero_probe_points_is_not_measured():
    """0 点 = 最小点根本不可达（不是"带宽为 0"）。"""
    result = classify_band(_band(0.0, n_points=0), level_mV=LEVEL,
                           limit_dex=LIMIT, scan_range_dex=SCAN)
    assert result["verdict"] == VERDICT_NOT_MEASURED


def test_missing_probe_point_count_is_tolerated():
    """汇总表常常没有点数；缺省 ≠ 0，不该被判成未测。"""
    band = _band(0.0988, left=0.05, right=0.0488)
    band.pop("n_points")
    assert classify_band(band, level_mV=LEVEL, limit_dex=LIMIT,
                         scan_range_dex=SCAN)["verdict"] == VERDICT_IDENTIFIABLE


def test_every_reason_carries_level_limit_scan_and_resolution():
    """带宽离开水平/上限/扫描范围/分辨率是没法读的（G6.1b-1 的红线）。"""
    for band in (_band(0.0988, left=0.05, right=0.0488),
                 _band(0.90, left=0.5, right=0.4),
                 _band(1.4, left=1.0, right=0.4, tl=True),
                 _band(2.0, left=1.0, right=1.0, tl=True, tr=True)):
        result = classify_band(band, level_mV=LEVEL, limit_dex=LIMIT,
                               scan_range_dex=SCAN)
        reason = result["reason"]
        assert "分辨率" in reason
        assert ("1 mV" in reason) or ("1 mV" in reason.replace("1.0", "1"))
        assert result["limit_dex"] == LIMIT
        assert result["scan_range_dex"] == SCAN


def test_verdict_vocabulary_is_exactly_five_words():
    assert set(ALLOWED_VERDICTS) == {
        VERDICT_IDENTIFIABLE, VERDICT_NOT_IDENTIFIABLE, VERDICT_BOUNDED,
        VERDICT_UNCONSTRAINED, VERDICT_NOT_MEASURED,
    }


def test_render_verdict_glosses_every_allowed_word():
    for word in ALLOWED_VERDICTS:
        text = render_verdict(word, parameter="Ds")
        assert word in text
        assert "未知" not in text


# ------------------------------------------------------------------
# 模式守卫
# ------------------------------------------------------------------
def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        normalise_mode("whatever")
    assert normalise_mode(" MATERIAL ") == MODE_MATERIAL


def test_material_mode_refuses_truth_recovery():
    with pytest.raises(ModeViolation) as exc:
        assert_benchmark_only(MODE_MATERIAL, "truth_recovery")
    assert "analysis_mode='benchmark'" in str(exc.value)


def test_benchmark_mode_allows_truth_recovery():
    assert_benchmark_only(MODE_BENCHMARK, "truth_recovery")
    assert_benchmark_only(MODE_BENCHMARK, "synthetic_truth")


def test_check_payload_flags_benchmark_fields_in_material_mode():
    payload = {"windows": [{"protocol_id": "x", "cost_at_truth_mV2": 0.0}]}
    with pytest.raises(ModeViolation):
        check_payload(MODE_MATERIAL, payload)
    hits = check_payload(MODE_BENCHMARK, payload)
    assert hits == ["windows[0].cost_at_truth_mV2"]


def test_mode_violation_is_not_a_value_error():
    """模式用错可修（换模式），参数名写错不可修 —— 调用方要能分别捕获。"""
    assert issubclass(ModeViolation, RuntimeError)
    assert not issubclass(ModeViolation, ValueError)


def test_party_role_caution_flags_the_benchmark_combination():
    text = party_role_caution(MODE_MATERIAL, "benchmark")
    assert text and "不构成" in text
    assert party_role_caution(MODE_MATERIAL, "identification") is None
    assert party_role_caution(MODE_BENCHMARK, "benchmark") is None
