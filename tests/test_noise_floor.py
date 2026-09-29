"""sigma_noise 标定（governance/noise_floor.py）的契约测试。

这个模块决定预注册负对照 **N1** 是不是一个**非空判据**。
所以测试的核心不是"能算出数"，而是：

  * 已知噪声的合成序列，估出的 sigma 必须**回到已知值**（校准测试）
  * **去趋势**必须真的执行：加一段漂移后，去趋势的 sigma 不许膨胀
    —— 这一条正是"std 会把漂移算成噪声"的护栏
  * **稳健性**：混入一个跳点，MAD 估计几乎不动而 std 显著膨胀
    （两个都算出来并列报，就是为了让这件事可见）
  * **分辨率下限**必须报出来，否则 N1 会被一个"看起来很小"的分辨率满足掉
  * 点太少 / 时间列坏了 ⇒ 抛错，**不给一个能用的数**（fail loud）
  * N1 阈值 = k * sigma，且口径（k 与 sigma）必须一起出现在 statement 里
"""

from __future__ import annotations

import numpy as np
import pytest

from governance.noise_floor import (
    DEFAULT_REST_WINDOW_S,
    EXAMPLE_K,
    K_PREREGISTRATION_RELPATH,
    MAD_TO_SIGMA,
    MIN_POINTS,
    NoiseFloorUnavailable,
    calibrate_noise_floor,
    load_preregistered_k,
    render_noise_floor_report,
    render_preregistration_template,
)

RNG_SEED = 20260928
SIGMA_MV_TRUE = 0.05          # 50 µV 噪声底（一台好恒电位仪的量级）
T_SPAN_S = 3600.0             # 比默认 30 min 窗口长，以测"只取最后一段"
N = 6000


def _series(sigma_mV=SIGMA_MV_TRUE, drift_mV_per_h=0.0, spike_at=None,
            spike_mV=0.0, seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, T_SPAN_S, N)
    v_mV = 300.0 + rng.normal(0.0, sigma_mV, N)
    v_mV = v_mV + drift_mV_per_h * (t / 3600.0)
    if spike_at is not None:
        v_mV[spike_at] += spike_mV
    return t, v_mV / 1000.0


# ------------------------------------------------------------------
# 1. 校准：估出的 sigma 必须回到已知值
# ------------------------------------------------------------------
def test_recovers_known_sigma():
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    assert floor.sigma_mV == pytest.approx(SIGMA_MV_TRUE, rel=0.15), (
        f"估出 {floor.sigma_mV:.4f} mV，真值 {SIGMA_MV_TRUE} mV"
    )
    assert floor.n_points >= MIN_POINTS


def test_window_is_the_last_rest_segment():
    """只取**最后** 1800 s —— 静置初期的松弛不是噪声。"""
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    assert floor.window_s == pytest.approx(DEFAULT_REST_WINDOW_S, rel=1e-6)
    assert floor.n_points == pytest.approx(N // 2, rel=0.02)


# ------------------------------------------------------------------
# 2. 去趋势：漂移不许被算成噪声
# ------------------------------------------------------------------
def test_detrend_keeps_sigma_stable_under_drift():
    """加漂移后，去趋势的 sigma 几乎不动。"""
    t, v_flat = _series(drift_mV_per_h=0.0)
    t2, v_drift = _series(drift_mV_per_h=20.0)
    flat = calibrate_noise_floor(t, v_flat)
    drifted = calibrate_noise_floor(t2, v_drift)
    assert drifted.sigma_mV == pytest.approx(flat.sigma_mV, rel=0.25), (
        "去趋势失败：漂移被算进了噪声"
    )
    # 漂移本身要报出来，且符号/量级对
    assert drifted.drift_mV_per_h == pytest.approx(20.0, rel=0.10)


def test_without_detrend_drift_inflates_sigma():
    """反例：关掉去趋势，sigma 必须**显著变大** —— 证明这个开关真的在起作用。

    一条永远为真的断言（哪个开关都不影响结果）是装饰，不是判据。
    """
    t, v = _series(drift_mV_per_h=20.0)
    off = calibrate_noise_floor(t, v, detrend=False)
    on = calibrate_noise_floor(t, v, detrend=True)
    assert off.sigma_mV > on.sigma_mV * 1.5, (
        f"detrend 开关没有效果（off={off.sigma_mV:.4f}, on={on.sigma_mV:.4f}）"
        " —— 那它就不是一个判据"
    )
    assert np.isnan(off.drift_mV_per_h)


# ------------------------------------------------------------------
# 3. 稳健性：跳点
# ------------------------------------------------------------------
def test_mad_resists_a_single_spike():
    t, v = _series()
    t2, v2 = _series(spike_at=N // 2, spike_mV=50.0)  # 50 mV 接触毛刺
    clean = calibrate_noise_floor(t, v)
    spiked = calibrate_noise_floor(t2, v2)
    assert spiked.sigma_mV == pytest.approx(clean.sigma_mV, rel=0.30), (
        "MAD 未能顶住单个跳点"
    )


def test_std_is_reported_alongside_for_contrast():
    """std 与 MAD 的对照必须写进 notes —— 这是发现跳点最快的方式。"""
    t, v = _series(spike_at=N // 2, spike_mV=50.0)
    spiked = calibrate_noise_floor(t, v, estimator="mad")
    assert "std" in spiked.notes, "MAD 估计里应同时报 std 作为对照"
    std_est = calibrate_noise_floor(t, v, estimator="std")
    assert std_est.sigma_mV > spiked.sigma_mV, (
        "混了跳点时 std 必须大于 MAD（否则说明跳点没进去）"
    )
    assert "MAD" in std_est.notes


def test_mad_constant_is_declared_not_hidden():
    """1.4826 必须在模块里可读 —— 它进了所有下游判据。"""
    assert MAD_TO_SIGMA == pytest.approx(1.4826)


# ------------------------------------------------------------------
# 4. 分辨率下限
# ------------------------------------------------------------------
def test_resolution_floor_is_reported_when_sigma_is_tiny():
    t, v = _series(sigma_mV=1e-5)   # 远低于 24-bit/5V 的分辨率下限
    floor = calibrate_noise_floor(t, v)
    assert floor.resolution_floor_mV is not None
    assert floor.resolution_limited is True
    assert "分辨率" in floor.notes


def test_resolution_not_flagged_when_sigma_is_real():
    t, v = _series(sigma_mV=0.05)
    floor = calibrate_noise_floor(t, v)
    assert floor.resolution_limited is False


# ------------------------------------------------------------------
# 5. fail loud
# ------------------------------------------------------------------
def test_too_few_points_raises():
    t = np.linspace(0, 10, MIN_POINTS - 1)
    v = np.full_like(t, 0.3)
    with pytest.raises(NoiseFloorUnavailable):
        calibrate_noise_floor(t, v)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        calibrate_noise_floor([0, 1, 2], [0.3, 0.3])


def test_zero_span_raises():
    t = np.zeros(100)
    v = np.full(100, 0.3)
    with pytest.raises(NoiseFloorUnavailable):
        calibrate_noise_floor(t, v)


def test_bad_estimator_raises():
    t, v = _series()
    with pytest.raises(ValueError):
        calibrate_noise_floor(t, v, estimator="mean")


def test_nonpositive_k_raises():
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    with pytest.raises(ValueError):
        floor.calibrated_threshold_mV(0.0)


# ------------------------------------------------------------------
# 6. N1 判据接线
# ------------------------------------------------------------------
def test_threshold_states_k_and_sigma_together():
    """带宽离开水平没法读 —— 同一个道理，阈值离开 k 与 sigma 也没法读。"""
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    thr = floor.calibrated_threshold_mV(3.0)
    assert thr["threshold_mV"] == pytest.approx(3.0 * floor.sigma_mV)
    assert thr["k"] == 3.0
    assert thr["sigma_mV"] == floor.sigma_mV
    assert "3" in thr["statement"] and "sigma_noise" in thr["statement"]
    assert f"{floor.sigma_mV:.3f}" in thr["statement"]


def test_as_dict_carries_everything_run_record_needs():
    t, v = _series()
    d = calibrate_noise_floor(t, v).as_dict()
    for key in (
        "sigma_noise_mV", "n_points", "rest_window_s", "drift_mV_per_h",
        "residual_max_abs_mV", "estimator", "resolution_floor_mV",
        "resolution_limited", "notes",
    ):
        assert key in d, f"run_record 需要的字段缺 {key}"


def test_report_renders_and_flags_resolution_limit():
    t, v = _series(sigma_mV=1e-5)
    floor = calibrate_noise_floor(t, v)
    text = render_noise_floor_report(floor, k=3.0)
    assert "sigma_noise" in text
    assert "N1" in text
    assert "受分辨率限制" in text


# ------------------------------------------------------------------
# 7. k 是**预注册量**，不许有"看起来像决定的默认值"
#
# 这一组的存在理由与 settings_hash 的缺失字段同源：
# 一个静默的默认值比没有默认值更危险 —— 报告读起来像"我们定了 k"，
# 而其实没人定过。所以 k=None 必须可见，不能悄悄变成 3.0。
# ------------------------------------------------------------------
def test_k_has_no_silent_default_in_the_threshold():
    """不传 k 时**不许**给出一个像已定的 k。"""
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    thr = floor.calibrated_threshold_mV(None)
    assert thr["k"] is None, "k=None 却回填了一个数值 k —— 这就是静默默认值"
    assert thr["is_preregistered"] is False
    assert thr["example_k"] == EXAMPLE_K
    assert "尚未预注册" in thr["statement"], (
        "未预注册的口径没写进 statement —— 数字会脱离语境被引用"
    )


def test_preregistered_k_is_flagged_as_such():
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    thr = floor.calibrated_threshold_mV(3.0)
    assert thr["k"] == 3.0
    assert thr["is_preregistered"] is True
    assert "尚未预注册" not in thr["statement"]


def test_the_example_k_is_not_the_decision():
    """示例值与"已决定"必须能分开 —— 否则示例会被当结论抄进方案。"""
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    assert floor.calibrated_threshold_mV(None)["is_preregistered"] is False
    assert floor.calibrated_threshold_mV(EXAMPLE_K)["is_preregistered"] is True, (
        "显式传 EXAMPLE_K 是'我确实选了 3'，与不传是两件事"
    )


def test_report_says_k_is_not_preregistered_when_k_is_missing():
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    text = render_noise_floor_report(floor)          # 默认 k=None
    assert "k 未预注册" in text, (
        "默认渲染没有警示 —— 报告会读成一个已经成立的判据"
    )
    assert K_PREREGISTRATION_RELPATH in text


def test_report_does_not_warn_when_k_is_given():
    t, v = _series()
    floor = calibrate_noise_floor(t, v)
    assert "k 未预注册" not in render_noise_floor_report(floor, k=3.0)


def test_load_preregistered_k_returns_none_when_absent(tmp_path):
    """没有文件 ⇒ None。**不许猜**一个 k 出来。"""
    missing = tmp_path / "nope.yaml"
    assert load_preregistered_k(missing) is None


def test_load_preregistered_k_returns_none_when_field_is_null(tmp_path):
    p = tmp_path / "prereg.yaml"
    p.write_text("k: null\nrationale: ''\n", encoding="utf-8")
    assert load_preregistered_k(p) is None


def test_load_preregistered_k_reads_a_real_value(tmp_path):
    p = tmp_path / "prereg.yaml"
    p.write_text("k: 4.5\nrationale: 'n=6000 点极值'\n", encoding="utf-8")
    assert load_preregistered_k(p) == pytest.approx(4.5)


def test_load_preregistered_k_rejects_nonpositive(tmp_path):
    p = tmp_path / "prereg.yaml"
    p.write_text("k: 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_preregistered_k(p)


def test_shipped_template_has_no_decided_k():
    """**仓库里出厂的那份模板必须是空的。**

    如果它哪天带上了具体 k，说明有人在没做空跑、没写 rationale 的情况下
    把示例值"转正"了 —— 这正是预注册要防的事。
    """
    text = render_preregistration_template()
    assert "k: null" in text
    assert "rationale" in text, "模板必须留 rationale 位，否则 k 会变成孤零零的数字"
    loaded = load_preregistered_k(K_PREREGISTRATION_RELPATH)
    assert loaded is None, (
        f"仓库里的 {K_PREREGISTRATION_RELPATH} 已经有 k={loaded} —— "
        "预注册量不该在没有空跑数据时被填上"
    )
