"""用户数据 QC 的两项新增门（A 体系锚定窗口 / B 脉冲协议升级）。

这两项都只走 ``user_tools`` 这条通道（自服务导入），不动平台冻结内核。

为什么值得单独写测试
--------------------
* 体系窗口规则是**闭集 + 边界值**：一旦把 ``hard`` 写宽了，20 V 的石墨数据
  会被放过去，而那正是这项检查存在的理由。
* 脉冲协议的判据是**分级**的：同一份数据在 ``protocol_type='GCD'`` 下只能
  WARN、在 ``'GITT'`` 下必须 FAIL。分级写反了，等于把唯一能挡住
  "脉冲时长错了但没人发现" 的门拆掉。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_sim.datasets.chemistry_windows import (
    SYS_GRAPHITE_HALFCELL_LI,
    SYS_NMC_FULLCELL,
    WINDOWS,
    check_declared_window,
    check_measured_window,
    resolve_system,
)
from user_tools import validate
from user_tools.spec import is_pulse_protocol, protocol_type_of

# ------------------------------------------------------------------
# 夹具
# ------------------------------------------------------------------
BASE_EXP = {
    "dataset_name": "toy",
    "sample_id": "CG-800",
    "chemistry": "other",
    "cell_configuration": "half_cell",
    "working_electrode": "negative",
    "working_electrode_material": "graphite",
    "counter_electrode": "lithium_metal",
    "voltage_lower": 0.005,
    "voltage_upper": 1.5,
    "current_sign": "discharge_positive",
    "protocol_type": "GCD",
    "nominal_capacity": 0.002,
}


def _exp(**over):
    exp = dict(BASE_EXP)
    exp.update(over)
    return exp


def _frame(t, i, v) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_s": np.asarray(t, dtype=float),
            "current_A": np.asarray(i, dtype=float),
            "voltage_V": np.asarray(v, dtype=float),
        }
    )


def _codes(issues, code):
    return [x for x in issues if x["code"] == code]


def _severities(issues, code):
    return [x["severity"] for x in _codes(issues, code)]


def _gcd_frame(*, gap_at: int | None = None, v_top: float = 1.2):
    """一段 GCD：600 s 静置 + 3000 s 放电（10 s 采样），电压 1.2 → 0.01 V。"""
    t = np.arange(0.0, 3600.0 + 10.0, 10.0)
    i = np.where(t < 600.0, 0.0, 2e-4)
    v = np.interp(t, [0.0, 600.0, 3600.0], [v_top, v_top, 0.01])
    if gap_at is not None:
        # 参数按**秒**给（比索引好读）；超出数组长度时按秒换算成索引
        idx = int(gap_at) if int(gap_at) < t.size else int(round(gap_at / 10.0))
        keep = np.ones(t.size, dtype=bool)
        # 30 个点 = 300 s 空洞 = 中位间隔的 30 倍（判据是 > 20 倍，
        # 所以这里刻意越过阈值；200 s 那种"刚够 20 倍"的空洞由
        # GITT_PULSE_RESOLUTION 的 3 倍判据去挡，见下面的用例）
        keep[idx + 1: idx + 31] = False
        t, i, v = t[keep], i[keep], v[keep]
    return _frame(t, i, v)


def _gitt_frame(
    *,
    pulse_s: float = 600.0,
    rest_s: float = 600.0,
    n_pulses: int = 6,
    uneven_at: int | None = None,
    uneven_s: float = 900.0,
    drop_inside_pulse_at: int | None = None,
):
    """按 rest→pulse→rest 造一段 GITT 记录（与平台夹具同构）。"""
    blocks = [(rest_s, 0.0)]
    for k in range(n_pulses):
        dur = uneven_s if k == uneven_at else pulse_s
        blocks.append((dur, 2e-4))
        blocks.append((rest_s, 0.0))
    t, i = [0.0], [0.0]
    now = 0.0
    for dur, cur in blocks:
        n = int(round(dur / 10.0))
        for _ in range(n):
            now += 10.0
            t.append(now)
            i.append(cur)
    t = np.array(t)
    i = np.array(i)
    if drop_inside_pulse_at is not None:
        keep = np.ones(t.size, dtype=bool)
        keep[drop_inside_pulse_at + 1: drop_inside_pulse_at + 4] = False
        t, i = t[keep], i[keep]
    v = 1.1 - 2.0e-5 * t
    return _frame(t, i, v)


# ------------------------------------------------------------------
# A. 体系锚定窗口：规则解析
# ------------------------------------------------------------------
def test_resolve_graphite_halfcell():
    win, why = resolve_system(
        chemistry="other",
        cell_configuration="half_cell",
        working_electrode="negative",
        counter_electrode="lithium_metal",
        working_electrode_material="graphite",
    )
    assert why == ""
    assert win is not None and win.system_id == SYS_GRAPHITE_HALFCELL_LI
    assert win.nominal == (0.005, 1.5)


def test_resolve_accepts_platform_physical_working_electrode_wording():
    """configs 里写的是 graphite_negative，必须也能命中（同一件事两种写法）。"""
    win, _ = resolve_system(
        cell_configuration="half_cell",
        counter_electrode="lithium_metal",
        physical_working_electrode="graphite_negative",
    )
    assert win is not None and win.system_id == SYS_GRAPHITE_HALFCELL_LI


def test_resolve_nmc_fullcell():
    win, why = resolve_system(chemistry="NMC", cell_configuration="full_cell")
    assert why == ""
    assert win is not None and win.system_id == SYS_NMC_FULLCELL


def test_resolve_halfcell_without_material_declaration_is_not_guessed():
    """半电池但没说工作电极材料 -> 不猜成石墨，返回原因。"""
    win, why = resolve_system(
        chemistry="NMC",
        cell_configuration="half_cell",
        counter_electrode="lithium_metal",
    )
    assert win is None
    assert "石墨" in why


def test_resolve_unknown_fullcell_chemistry_is_not_guessed():
    win, why = resolve_system(chemistry="sodium", cell_configuration="full_cell")
    assert win is None
    assert "sodium" in why


# ------------------------------------------------------------------
# A. 体系锚定窗口：两级判据
# ------------------------------------------------------------------
def test_declared_window_wider_than_hard_bounds_fails():
    win = WINDOWS[SYS_GRAPHITE_HALFCELL_LI]
    errs, warns = check_declared_window(win, 0.001, 15.0)
    assert errs, "石墨半电池填 [0.001, 15] V 必须报错"
    assert not warns


def test_declared_window_outside_nominal_but_inside_hard_only_warns():
    """2.0 V 上限是合法的深脱锂实验 -> 只警告，不判死。"""
    win = WINDOWS[SYS_GRAPHITE_HALFCELL_LI]
    errs, warns = check_declared_window(win, 0.005, 2.0)
    assert errs == []
    assert warns


def test_measured_voltage_20v_fails():
    win = WINDOWS[SYS_GRAPHITE_HALFCELL_LI]
    errs, _ = check_measured_window(win, 0.02, 20.0)
    assert errs


def test_validate_fails_on_declared_window_wider_than_system():
    issues = validate.validate(
        _gcd_frame(), _exp(voltage_upper=15.0), {}
    )
    assert "FAIL" in _severities(issues, "VOLTAGE_WINDOW_SYSTEM")
    assert validate.summarize(issues)["simulation_allowed"] is False


def test_validate_passes_platform_graphite_window():
    issues = validate.validate(_gcd_frame(), _exp(), {})
    assert _severities(issues, "VOLTAGE_WINDOW_SYSTEM") == ["PASS"]
    assert _severities(issues, "VOLTAGE_SYSTEM_RANGE") == ["PASS"]
    assert validate.summarize(issues)["n_fail"] == 0


def test_validate_warns_when_system_cannot_be_anchored():
    exp = _exp()
    exp.pop("working_electrode_material")
    issues = validate.validate(_gcd_frame(), exp, {})
    assert _severities(issues, "VOLTAGE_WINDOW_SYSTEM") == ["WARN"]


def test_validate_fullcell_nmc_window_untouched():
    """回归：既有全电池数据（2.5–4.2 V）不应因为新门变成 FAIL。"""
    t = np.arange(0.0, 3600.0, 10.0)
    i = np.full(t.size, 1e-3)
    v = np.interp(t, [0.0, 3600.0], [4.2, 2.6])
    exp = {
        "dataset_name": "toy-full",
        "sample_id": "X",
        "chemistry": "NMC",
        "cell_configuration": "full_cell",
        "voltage_lower": 2.5,
        "voltage_upper": 4.2,
        "current_sign": "discharge_positive",
        "protocol_type": "GCD",
    }
    issues = validate.validate(_frame(t, i, v), exp, {})
    assert _severities(issues, "VOLTAGE_WINDOW_SYSTEM") == ["PASS"]
    assert validate.summarize(issues)["n_fail"] == 0


# ------------------------------------------------------------------
# B. 协议类型解析
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "exp,expected",
    [
        ({"protocol_type": "GITT"}, "GITT"),
        ({"protocol_type": "gitt"}, "GITT"),
        ({"protocol": "GITT 10min/30min"}, "GITT"),
        ({"protocol": "PITT"}, "PITT"),
        ({"protocol": "CC_Cover5"}, ""),
        ({"protocol": "GCD 0.1C"}, "GCD"),
        ({}, ""),
    ],
)
def test_protocol_type_of(exp, expected):
    assert protocol_type_of(exp) == expected


def test_is_pulse_protocol_only_for_pulse_types():
    assert is_pulse_protocol("GITT")
    assert is_pulse_protocol("PITT")
    assert not is_pulse_protocol("GCD")
    assert not is_pulse_protocol("")


# ------------------------------------------------------------------
# B. 采样间断：分级
# ------------------------------------------------------------------
def test_sampling_gap_is_warn_for_gcd():
    issues = validate.validate(_gcd_frame(gap_at=2500), _exp(), {})
    assert "WARN" in _severities(issues, "SAMPLING_INTERVAL_GAP")
    assert validate.summarize(issues)["simulation_allowed"] is True


def test_sampling_gap_is_fail_for_gitt():
    issues = validate.validate(
        _gcd_frame(gap_at=2500), _exp(protocol_type="GITT"), {}
    )
    assert "FAIL" in _severities(issues, "SAMPLING_INTERVAL_GAP")
    assert validate.summarize(issues)["simulation_allowed"] is False


# ------------------------------------------------------------------
# B. 脉冲结构
# ------------------------------------------------------------------
def test_gitt_frame_structure_passes_with_declared_pulse():
    issues = validate.validate(
        _gitt_frame(),
        _exp(protocol_type="GITT", pulse_duration_s=600.0,
             relax_duration_s=600.0),
        {},
    )
    assert _severities(issues, "GITT_STRUCTURE") == ["PASS"]
    assert _severities(issues, "GITT_PULSE_DURATION") == ["PASS"]
    assert _severities(issues, "GITT_PULSE_UNIFORMITY") == ["PASS"]


def test_declared_pulse_length_mismatch_is_fail():
    """声明 660 s、实测 600 s（差 9 %）—— 这正是「10 min 被写成 11 min」那一类错。"""
    issues = validate.validate(
        _gitt_frame(), _exp(protocol_type="GITT", pulse_duration_s=660.0), {}
    )
    assert "FAIL" in _severities(issues, "GITT_PULSE_DURATION")


def test_missing_declared_pulse_length_warns_and_reports_measured():
    issues = validate.validate(_gitt_frame(), _exp(protocol_type="GITT"), {})
    hits = _codes(issues, "GITT_PULSE_DURATION")
    assert [h["severity"] for h in hits] == ["WARN"]
    assert "600" in hits[0]["evidence"]


def test_uneven_pulse_lengths_fail():
    issues = validate.validate(
        _gitt_frame(uneven_at=2),
        _exp(protocol_type="GITT", pulse_duration_s=600.0),
        {},
    )
    assert "FAIL" in _severities(issues, "GITT_PULSE_UNIFORMITY")


def test_non_pulse_data_declared_as_gitt_fails_structure():
    issues = validate.validate(
        _gcd_frame(), _exp(protocol_type="GITT"), {}
    )
    assert "FAIL" in _severities(issues, "GITT_STRUCTURE")


def test_gap_inside_pulse_fails_resolution():
    """脉冲内部掉点：ΔV 与时长都不可信，必须 FAIL（不是 WARN）。"""
    issues = validate.validate(
        _gitt_frame(drop_inside_pulse_at=70),
        _exp(protocol_type="GITT", pulse_duration_s=600.0),
        {},
    )
    assert "FAIL" in _severities(issues, "GITT_PULSE_RESOLUTION")


def test_gcd_frame_skips_pulse_checks_entirely():
    """GCD 数据不该出现脉冲类检查项（否则报告会被无关条目淹掉）。"""
    issues = validate.validate(_gitt_frame(), _exp(protocol_type="GCD"), {})
    for code in ("GITT_STRUCTURE", "GITT_PULSE_DURATION",
                 "GITT_PULSE_UNIFORMITY", "GITT_PULSE_RESOLUTION"):
        assert _codes(issues, code) == []
