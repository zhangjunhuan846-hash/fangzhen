"""自动报告的测试：带宽重建、治理守卫、渲染。

报告层是"把产物翻成结论"的一步，也是最容易把 not measured 写成"不显著"、
把 bounded 写成"是 X"的一步，所以它自己要有契约测试。
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from governance.analysis_mode import (
    MODE_BENCHMARK,
    MODE_MATERIAL,
    ModeViolation,
    VERDICT_BOUNDED,
    VERDICT_IDENTIFIABLE,
    VERDICT_NOT_MEASURED,
    VERDICT_UNCONSTRAINED,
)
from identification.parameter_report import (
    ParameterProbe,
    ReportInputError,
    band_from_window_row,
    best_window_probe,
    render_report,
    unmeasured_probes,
)

COLUMNS = [
    "protocol_id", "applicable", "band_width_dex", "band_left_dex",
    "band_right_dex", "band_truncated", "band_resolution_dex",
]


def _row(protocol_id: str, width, *, left=None, right=None, truncated=False,
         applicable=True, **extra) -> dict:
    row = {
        "protocol_id": protocol_id, "applicable": applicable,
        "band_width_dex": width, "band_left_dex": left,
        "band_right_dex": right, "band_truncated": truncated,
        "band_resolution_dex": 0.05,
    }
    row.update(extra)
    return row


def _windows(rows) -> pd.DataFrame:
    return pd.DataFrame(rows).reindex(columns=COLUMNS + [
        c for c in (rows[0].keys() if rows else []) if c not in COLUMNS
    ])


# ------------------------------------------------------------------
# 带宽重建
# ------------------------------------------------------------------
def test_left_truncation_is_recovered_from_the_edge_distance():
    """估计器撞界时把带边缘吸附到扫描边界 ⇒ 距离 ≈ 扫描半宽 就是截断。"""
    band = band_from_window_row(_row("w", 1.4, left=1.0, right=0.4,
                                     truncated=True))
    assert band["truncated_left"] is True
    assert band["truncated_right"] is False


def test_closed_band_keeps_both_sides_closed():
    band = band_from_window_row(_row("w", 0.0988, left=0.05, right=0.0488))
    assert band["truncated_left"] is False
    assert band["truncated_right"] is False


def test_unrecoverable_truncation_falls_back_to_the_conservative_reading():
    """表里说截断了但两侧都不贴边 → 按 unconstrained 处理，不猜方向。"""
    band = band_from_window_row(_row("w", 1.2, left=0.6, right=0.6,
                                     truncated=True))
    assert band["truncated_left"] and band["truncated_right"]


def test_missing_width_yields_no_band():
    assert band_from_window_row(_row("w", None, left=None, right=None)) is None


# ------------------------------------------------------------------
# 选窗口
# ------------------------------------------------------------------
def test_narrow_closed_window_wins_over_a_truncated_one():
    windows = _windows([
        _row("GITT-charge#t1", 1.4, left=1.0, right=0.4, truncated=True),
        _row("GITT-charge#t2", 0.90, left=0.5, right=0.40),
        _row("GITT-charge#t3", 0.0988, left=0.05, right=0.0488),
    ])
    probe, summary = best_window_probe(windows, protocol_prefix="GITT-charge")
    assert probe.protocol_id == "GITT-charge#t3"
    assert probe.verdict == VERDICT_IDENTIFIABLE
    assert summary["n_within_limit"] == 1
    assert summary["n_untruncated"] == 2


def test_truncated_only_population_falls_back_and_says_so():
    windows = _windows([
        _row("w#1", 1.2, left=1.0, right=0.2, truncated=True),
        _row("w#2", 2.0, left=1.0, right=1.0, truncated=True),
    ])
    probe, summary = best_window_probe(windows, protocol_prefix="w")
    assert probe.verdict == VERDICT_BOUNDED
    assert summary["best_is_closed"] is False
    assert "截断" in probe.note


def test_windows_that_never_reach_the_level_are_not_measured():
    windows = _windows([_row("w#1", None, applicable=False)])
    probe, summary = best_window_probe(windows)
    assert probe.verdict == VERDICT_NOT_MEASURED
    assert summary["n_never_reaching_level"] == 0  # 不可回放的窗口不算"没跨过"


def test_missing_columns_raise_instead_of_guessing():
    with pytest.raises(ReportInputError):
        best_window_probe(pd.DataFrame([{"protocol_id": "x"}]))


# ------------------------------------------------------------------
# 未测参数
# ------------------------------------------------------------------
def test_unmeasured_probe_is_a_string_and_names_what_is_missing():
    probes = unmeasured_probes(("k0",), available_techniques=("GITT",))
    assert isinstance(probes[0].rationale, str)
    assert probes[0].verdict == VERDICT_NOT_MEASURED
    assert "EIS" in probes[0].rationale


def test_unmeasured_probe_clears_when_the_technique_is_present():
    probes = unmeasured_probes(("k0",), available_techniques=("GITT", "EIS"))
    assert probes[0].verdict == VERDICT_NOT_MEASURED
    assert "缺" not in probes[0].rationale


# ------------------------------------------------------------------
# 渲染与守卫
# ------------------------------------------------------------------
def _probes():
    return [
        ParameterProbe(parameter="Ds", verdict=VERDICT_BOUNDED,
                       protocol_id="GITT-charge#t475",
                       band={"width_dex": 0.0988, "resolution_dex": 0.05,
                             "truncated_left": True,
                             "truncated_right": False},
                       rationale="单侧截断", evidence=("GITT",),
                       source="gitt_fitting", note="x0 = 0.0054；实测脉冲 |dV| = 596.6 mV"),
        ParameterProbe(parameter="k0", verdict=VERDICT_NOT_MEASURED,
                       rationale="本数据集没有 EIS 测量（缺 EIS）",
                       evidence=("EIS",), source="not_measured"),
    ]


def test_report_renders_the_five_word_vocabulary_and_keeps_not_measured():
    text = render_report(_probes(), dataset="dlr_gitt", cell="Hydra.0b",
                         analysis_mode=MODE_MATERIAL, dataset_role="benchmark")
    assert "| `Ds` | **bounded** |" in text
    assert "| `k0` | **not_measured** |" in text
    assert "not measured" in text or "not_measured" in text
    assert "0.0988" in text


def test_report_carries_the_required_wording_for_bounded_verdicts():
    text = render_report(_probes(), dataset="d", analysis_mode=MODE_MATERIAL)
    assert "one-sided sensitivity region" in text
    assert "bounds rather than point estimates" in text
    assert "不要" in text and "点估计" in text


def test_report_table_escapes_pipes_so_the_columns_survive():
    probes = [ParameterProbe(parameter="Ds", verdict=VERDICT_BOUNDED,
                             note="实测脉冲 |dV| = 596.6 mV",
                             rationale="单侧截断")]
    text = render_report(probes, dataset="d", analysis_mode=MODE_MATERIAL)
    row = [line for line in text.splitlines() if "`Ds`" in line
           and line.startswith("|")][0]
    assert "\\|dV\\|" in row
    # 7 列的表：按"未被转义的竖线"切，应当得到 7 个格子（+ 首尾空串）
    cells = re.split(r"(?<!\\)\|", row)
    assert len(cells) == 9


def test_material_mode_refuses_the_recovery_columns():
    with pytest.raises(ModeViolation):
        render_report(_probes(), dataset="d", analysis_mode=MODE_MATERIAL,
                      include_recovery=True)
    text = render_report(_probes(), dataset="d", analysis_mode=MODE_BENCHMARK,
                         include_recovery=True)
    assert "benchmark" in text


def test_report_always_states_the_model_to_model_boundary():
    text = render_report(_probes(), dataset="d", analysis_mode=MODE_MATERIAL)
    assert "model-to-model" in text
    assert "最好情况" in text


def test_report_summary_line_matches_the_mentor_format():
    text = render_report(_probes(), dataset="dlr_gitt", cell="Hydra.0b",
                         analysis_mode=MODE_MATERIAL)
    assert "  Ds  : bounded" in text
    assert "  k0  : not_measured" in text
