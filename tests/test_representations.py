"""G6.2a 表示层的契约测试：归一化、符号/数值一致、覆盖语义。

这一层最可能的错误是**静默**的：符号侧与数值侧对同一个 x 给出不同的 φ，
或者"幅度"在两个形状之间根本不是同一个量（少一个 √3 而已）。
所以每条声明都要能被测。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from identification import representations
from identification.representations import (
    REGION_EDGES,
    SHAPE_CONSTANT,
    SHAPE_LINEAR,
    SHAPE_NAMES,
    SHAPE_RMS_TOL,
    SHAPE_THREE_REGION,
    SHAPES,
    cross_rmse_mV,
    override_source,
    phi_linear,
    phi_three_region,
    shape_override,
    shape_rms,
)

ROOT = Path(__file__).resolve().parents[1]
PARAM_SET = "Ecker2015_graphite_halfcell"
DS_KEY = "Positive particle diffusivity [m2.s-1]"

pybamm = pytest.importorskip("pybamm")


# ------------------------------------------------------------------
# 归一化：三个形状的"幅度"必须是同一个量
# ------------------------------------------------------------------
def test_shapes_are_rms_normalised_and_zero_mean():
    for name in SHAPE_NAMES:
        mean, rms = shape_rms(name)
        assert rms == pytest.approx(1.0, abs=SHAPE_RMS_TOL), name
        if name != SHAPE_CONSTANT:
            assert mean == pytest.approx(0.0, abs=SHAPE_RMS_TOL), name


def test_the_tolerance_can_still_catch_a_missing_sqrt3():
    """容差的意义：漏掉 √3 会让 rms 变成 1/√3 ≈ 0.577，必须被抓到。"""
    x = np.linspace(0.0, 1.0, 2001)
    unnormalised_rms = float(np.sqrt(np.mean((2.0 * x - 1.0) ** 2)))
    assert unnormalised_rms == pytest.approx(1.0 / np.sqrt(3.0), abs=1e-3)
    assert abs(unnormalised_rms - 1.0) > SHAPE_RMS_TOL


def test_rms_uses_quadrature_not_a_sample_mean():
    """均匀网格上的样本均值对 x² 有一阶偏差（曾把 linear 读成 1.0005）。"""
    _, rms = shape_rms(SHAPE_LINEAR, n=2001)
    x = np.linspace(0.0, 1.0, 2001)
    sample_mean_rms = float(np.sqrt(np.mean((np.sqrt(3.0) * (2 * x - 1)) ** 2)))
    assert abs(rms - 1.0) < abs(sample_mean_rms - 1.0)
    assert abs(rms - 1.0) < 1e-5


# ------------------------------------------------------------------
# 符号 / 数值两条路径必须一致
# ------------------------------------------------------------------
def test_symbolic_and_numeric_paths_agree_at_every_shape():
    """pybamm 把**符号**传进函数型参数（实测：Maximum(...)），

    而 `EqualHeaviside` 的约定与直觉相反（left <= right 才返回 1）。
    两边不一致会让"接口通了"变成一句假话。
    """
    xs = [0.05, 0.2, 0.4, 0.55, 0.8, 0.95]
    for name in SHAPE_NAMES:
        for x in xs:
            sym = float(SHAPES[name](pybamm.Scalar(x)).evaluate())
            num = float(SHAPES[name](x))
            assert sym == pytest.approx(num, abs=1e-12), f"{name} @ x={x}"


def test_three_region_takes_the_declared_values_on_each_third():
    lo, hi = REGION_EDGES
    assert float(phi_three_region(0.1)) == pytest.approx(1.0 / np.sqrt(2.0))
    assert float(phi_three_region(0.5)) == pytest.approx(-2.0 / np.sqrt(2.0))
    assert float(phi_three_region(0.9)) == pytest.approx(1.0 / np.sqrt(2.0))
    assert float(phi_three_region(lo + 0.01)) == pytest.approx(-np.sqrt(2.0))
    assert float(phi_three_region(hi + 0.01)) == pytest.approx(1.0 / np.sqrt(2.0))


# ------------------------------------------------------------------
# override：函数型、全转发、零幅度精确等于参考
# ------------------------------------------------------------------
def test_override_forwards_every_argument(monkeypatch):
    """f(sto, T) 必须**全转发**。

    用 fixture 参考而不是真实参数集：Ecker2015 的 D_s 是含 ``exp(…/R)`` 的
    pybamm **符号**，``ref(0.5, 298.15)`` 返回 ``Multiplication`` 而不是数，
    两个符号对象之间的 ``==`` 会返回真值对象 ⇒ 断言恒成立（假通过）。
    所以参考换成一个真正的浮点函数，并记录它被怎么调用。
    （同一手法见 tests/test_recovery_stats.py。）
    """
    seen = []

    def ref(sto, T):
        seen.append((sto, T))
        return 2.0 * sto + T

    monkeypatch.setattr(representations, "load_parameter_values",
                        lambda ps: {DS_KEY: ref})
    f = shape_override(PARAM_SET, SHAPE_LINEAR, 0.5)
    for x, T in ((0.1, 298.15), (0.5, 310.0), (0.9, 273.15)):
        expect = ref(x, T) * 10.0 ** (0.5 * float(phi_linear(x)))
        assert f(x, T) == pytest.approx(expect, rel=1e-12)
    # 两个参数都**原样**到达（wrapper 不许替换或丢掉任何一个）
    assert set(seen) == {(0.1, 298.15), (0.5, 310.0), (0.9, 273.15)}


def test_a_wrong_amplitude_is_caught_by_that_assertion(monkeypatch):
    """反例守卫：把幅度写错，上面那条断言必须发现（否则它是空的）。"""

    def ref(sto, T):
        return 2.0 * sto + T

    monkeypatch.setattr(representations, "load_parameter_values",
                        lambda ps: {DS_KEY: ref})
    right = shape_override(PARAM_SET, SHAPE_LINEAR, 0.5)
    wrong = shape_override(PARAM_SET, SHAPE_LINEAR, 0.9)
    assert wrong(0.4, 298.15) != pytest.approx(right(0.4, 298.15), rel=1e-6)


def test_zero_amplitude_is_exactly_the_reference(monkeypatch):
    """amp=0 必须**精确**等于参考：形状本身不许夹带偏移。"""

    def ref(sto, T):
        return 2.0 * sto + T

    monkeypatch.setattr(representations, "load_parameter_values",
                        lambda ps: {DS_KEY: ref})
    for name in SHAPE_NAMES:
        f = shape_override(PARAM_SET, name, 0.0)
        assert f(0.37, 300.0) == ref(0.37, 300.0)      # 精确相等，不是 approx
        assert f.__name__


def test_shapes_accept_array_input_but_return_a_float_for_a_float():
    """标量必须回 **float**：`pybamm_symbol * 0d-array` 会在域合并时崩

    （实测 AttributeError: 'numpy.ndarray' object has no attribute 'domains'）。
    数组输入是允许的：形状本身是逐点的。
    """
    for name in SHAPE_NAMES:
        scalar = SHAPES[name](0.5)
        assert isinstance(scalar, float), f"{name} 返回了 {type(scalar).__name__}"
        arr = SHAPES[name](np.array([0.1, 0.5, 0.9]))
        assert isinstance(arr, np.ndarray)
        assert arr.shape == (3,)
        assert np.all(np.isfinite(arr))
        assert arr[1] == pytest.approx(float(SHAPES[name](0.5)))


def test_override_reproduces_the_reference_numerically_on_the_real_set():
    """真实参数集上做一次**数值**核对（不是符号比较）。

    ``ref(...)`` 是符号，但可以 ``.evaluate()`` 出数（实测可用），
    所以真实参数集上的缩放关系是可验的。
    """
    from battery_sim.models.pybamm_factory import load_parameter_values

    ref = load_parameter_values(PARAM_SET)[DS_KEY]
    assert callable(ref)
    x, T = 0.4, 298.15
    base = float(ref(x, T).evaluate())
    assert base > 0
    for name in SHAPE_NAMES:
        amp = 0.25
        got = float(shape_override(PARAM_SET, name, amp)(x, T).evaluate())
        expect = base * 10.0 ** (amp * float(SHAPES[name](x)))
        assert got == pytest.approx(expect, rel=1e-12), name


def test_unknown_shape_is_rejected():
    with pytest.raises(KeyError):
        shape_override(PARAM_SET, "wavy", 0.0)
    with pytest.raises(KeyError):
        shape_rms("wavy")


# ------------------------------------------------------------------
# 溯源条目：只放可核对的量，且 material 模式下干净
# ------------------------------------------------------------------
def test_override_source_records_only_checkable_quantities():
    src = override_source(SHAPE_THREE_REGION, 0.5)
    assert src["shape"] == SHAPE_THREE_REGION
    assert src["amplitude_dex"] == pytest.approx(0.5)
    assert src["phi_rms"] == pytest.approx(1.0, abs=SHAPE_RMS_TOL)
    assert src["phi_mean"] == pytest.approx(0.0, abs=SHAPE_RMS_TOL)
    assert [float(v) for v in src["region_edges"]] == list(REGION_EDGES)


def test_override_source_survives_the_material_mode_guard():
    from governance.analysis_mode import MODE_MATERIAL, check_payload

    check_payload(MODE_MATERIAL, override_source(SHAPE_CONSTANT, 0.0))


# ------------------------------------------------------------------
# 轨迹比较
# ------------------------------------------------------------------
def test_cross_rmse_refuses_mismatched_trajectories():
    with pytest.raises(ValueError):
        cross_rmse_mV(np.zeros(3), np.zeros(4))


def test_cross_rmse_ignores_nan_tails():
    a = np.array([1.0, 1.0, np.nan])
    b = np.array([1.1, 1.1, np.nan])
    out = cross_rmse_mV(a, b)
    assert out["n_points"] == 2
    assert out["rmse_mV"] == pytest.approx(100.0)
    assert out["max_abs_mV"] == pytest.approx(100.0)


def test_cross_rmse_reports_nan_when_nothing_overlaps():
    out = cross_rmse_mV(np.array([np.nan]), np.array([1.0]))
    assert out["n_points"] == 0
    assert np.isnan(out["rmse_mV"])


# ------------------------------------------------------------------
# 源码级守卫：扫描变量换了，代价函数不许换
# ------------------------------------------------------------------
def test_replay_scan_takes_an_injected_builder_but_keeps_one_cost_definition():
    src = (ROOT / "identification" / "replay_scan.py").read_text(
        encoding="utf-8")
    assert "override_builder" in src
    assert "override_source_fn" in src
    assert src.count("def cost(") == 1
    assert "def compare(" in src


def test_g6_2a_does_not_re_implement_the_scan_or_the_band():
    src = (ROOT / "scripts" / "graphite" / "g6_2a_representations.py").read_text(
        encoding="utf-8")
    assert "identification.replay_scan" in src
    assert "identification.recovery_stats" in src
    assert "def band_width(" not in src
    assert "def cost(" not in src
