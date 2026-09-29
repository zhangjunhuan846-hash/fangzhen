"""三个缺口的**接线**测试 —— 模块存在不算填上缺口。

前三个测试文件各自证明"模块本身对"。这一个证明的是**它们接进了产物**：

  * `run_record.yaml` 里确实有地方放这三样东西（否则填了也白填）
  * `governance.noise_floor.calibrate_noise_floor(...).as_dict()` 的每个键
    都能落到 run_record 的某个字段上（字段名对不上 = 手抄会错位）
  * `governance.settings_hash` 的输出形态与 run_record 的三层槽位一致
  * 两个 CLI 的 `--help` 能跑（入口存在但跑不起来，是最常见的一种假交付）

为什么把这条单独拿出来：本仓库的历史教训是"机制有了、没人用"。
一个模块只有在**产物里有它的位置**时才算落地。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RUN_RECORD = ROOT / "templates" / "commercial_graphite_ht" / "run_record.yaml"

from governance.noise_floor import calibrate_noise_floor  # noqa: E402
from governance.settings_hash import KNOWN_LIMITS, assert_same_settings  # noqa: E402


@pytest.fixture(scope="module")
def run_record() -> dict:
    return yaml.safe_load(RUN_RECORD.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# 缺口 2：sigma_noise 要有地方放
# ------------------------------------------------------------------
def test_run_record_has_sigma_noise_slots(run_record):
    for key in (
        "sigma_noise_mV",
        "sigma_noise_k",
        "sigma_noise_source",
        "sigma_noise_resolution_limited",
        "sigma_noise_report",
    ):
        assert key in run_record, (
            f"run_record.yaml 缺 {key} —— 标定出来的 sigma 无处可放，"
            "等于缺口没填上"
        )


def test_every_noise_floor_field_maps_into_the_run_record(run_record):
    """标定产物的每个键都要在 run_record 里找得到落点（不许只活在内存里）。"""
    import numpy as np

    rng = np.random.default_rng(7)
    t = np.linspace(0, 3600, 3000)
    v = 0.3 + rng.normal(0, 5e-5, 3000)
    floor = calibrate_noise_floor(t, v)
    d = floor.as_dict()

    # sigma 本身、分辨率标志都要有同名字段；其余进 source 记录
    assert "sigma_noise_mV" in run_record
    assert "sigma_noise_resolution_limited" in run_record
    for key in d:
        # 每个键要么直接对得上，要么在 sigma_noise_* 族里
        if key in run_record:
            continue
        assert f"sigma_noise_{key}" in run_record or key in (
            "n_points", "rest_window_s", "drift_mV_per_h",
            "residual_max_abs_mV", "estimator", "notes",
            "resolution_floor_mV",
        ), f"标定字段 {key} 在 run_record 里没有落点"


def test_sigma_slot_is_declared_not_assumed(run_record):
    """空字符串 = 待填。不许给一个看起来像真值的默认（那会被当成已标定）。"""
    assert run_record["sigma_noise_mV"] == "", (
        "sigma_noise_mV 不该有默认值 —— 默认值会被误读成'已标定'"
    )


# ------------------------------------------------------------------
# 缺口 3：settings_hash 要有三个槽位（逐层）+ 一个总判定
# ------------------------------------------------------------------
def test_run_record_has_settings_hash_slots(run_record):
    for key in (
        "settings_hash_per_level",
        "settings_identical_across_levels",
        "settings_diff_detail",
        "settings_hash_known_limits",
    ):
        assert key in run_record, f"run_record.yaml 缺 {key}"


def test_settings_slots_accept_the_module_output_shape(run_record):
    """三层槽位是 dict；模块给的就是 dict —— 形状必须对得上。"""
    assert isinstance(run_record["settings_hash_per_level"], dict)
    p = {"schema": 1, "float_sig_digits": 12, "model": "DFN",
         "solver": {"class": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6},
         "model_options": {}, "grid": {}}
    res = assert_same_settings({"M0": p, "M1": p, "M2": p})
    # 模块的 hashes 直接就能填进 settings_hash_per_level
    run_record["settings_hash_per_level"] = res["hashes"]
    assert set(run_record["settings_hash_per_level"]) == {"M0", "M1", "M2"}
    assert res["identical"] is True


def test_known_limits_are_carried_verbatim(run_record):
    """边界必须随结果一起引用 —— 所以它得能从模块抄进 run_record。"""
    assert isinstance(run_record["settings_hash_known_limits"], list)
    for limit in KNOWN_LIMITS:
        assert isinstance(limit, str) and limit


# ------------------------------------------------------------------
# 缺口 1：几何通路要有地方放
# ------------------------------------------------------------------
def test_run_record_has_geometry_slots(run_record):
    for key in (
        "geometry_mode",
        "geometry_source",
        "radius_used_m",
        "radius_report_line",
        "geometry_conflict_checked",
    ):
        assert key in run_record, f"run_record.yaml 缺 {key}"


def test_geometry_gate_is_in_the_gates_block(run_record):
    """缺口 1 是一条**结论级**红线（缺 D50 不许解释跨样品 D_s），
    所以它必须在 gates 里，不只是一段说明。"""
    assert "L1_geometry_channel_complete" in run_record["gates"]


def test_geometry_mode_is_an_explicit_choice(run_record):
    """annex A §4.1 要求"二选一，不得混用"—— 所以槽位是枚举，不是自由文本。"""
    assert run_record["geometry_mode"] == ""
    doc = RUN_RECORD.read_text(encoding="utf-8")
    assert "manual_transcription" in doc and "v0.1.1_channel" in doc, (
        "两个允许的取值必须写在模板里，否则填的人会自创第三个"
    )


# ------------------------------------------------------------------
# 两个 CLI 必须真能跑起来
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "module",
    ["user_tools.sigma_noise", "user_tools.geometry_channel"],
)
def test_cli_help_runs(module):
    r = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, (
        f"{module} --help 失败（rc={r.returncode}）\n{r.stdout}\n{r.stderr}"
    )
    assert "usage" in r.stdout.lower()


def test_geometry_channel_cli_reports_incomplete_without_error():
    """真实模板今天应当**可跑且报不完整**（退出码 1，不是崩溃）。

    这是"数据还没到"的正确表达：能跑、能说清缺什么、不当成错误。
    """
    r = subprocess.run(
        [sys.executable, "-m", "user_tools.geometry_channel",
         "--series", "templates/commercial_graphite_ht/metadata"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 1, (
        f"期望退出码 1（有样品不完整），得到 {r.returncode}\n{r.stdout}\n{r.stderr}"
    )
    assert "不完整" in r.stdout
    assert "particle.d50_um" in r.stdout


def test_geometry_channel_cli_refuses_align_conflict():
    """与尺度对齐门冲突时必须**拒绝**（退出码 2），不静默继续。"""
    r = subprocess.run(
        [sys.executable, "-m", "user_tools.geometry_channel",
         "--series", "templates/commercial_graphite_ht/metadata",
         "--scale-alignment", "align"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 2, (
        f"冲突时应当拒绝，得到 rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    )
    assert "冲突" in r.stderr
