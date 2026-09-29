"""``user_tools/sigma_noise.py`` 命令行入口的契约测试。

为什么这个文件值得单独存在
--------------------------
这个脚本是**空白跑数据进入平台的唯一通道**，而它的产物（`outputs/noise_floor/*.json`）
会被 run_record 与 N1 判据引用。所以它有两类失效方式，都不会自己报错：

  * **报告与 JSON 不一致** —— 早先实现里报告按 k=3 渲染、JSON 写 ``"k": null``，
    引用哪一份都会得出不同结论。
  * **没有 k 时给出一个像判据的阈值** —— 与 ``settings_hash`` 的静默默认值同源。

本文件把这两条钉住：**产物之间不许自相矛盾，缺一个决定时不许装成有决定。**

这些测试**不依赖任何真实实验数据** —— 空跑记录在测试里现场合成。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from user_tools.sigma_noise import main

#: 合成空跑用的真值（与 test_noise_floor.py 同量级：一台好恒电位仪）
SIGMA_MV_TRUE = 0.05
N_POINTS = 1800


def _write_rest_csv(path: Path, *, sigma_mV=SIGMA_MV_TRUE, drift_mV_per_h=0.0,
                    prefix_rows=0) -> Path:
    """写一份合成的 30 min 空跑 CSV（`time_s` / `voltage_V`）。

    ``prefix_rows`` 用于测"只取最后一段窗口"：前面塞一段更早的静置。
    """
    rng = np.random.default_rng(20260929)
    n = N_POINTS + prefix_rows
    t = np.arange(n, dtype=float)
    v_mV = 300.0 + rng.normal(0.0, sigma_mV, n) + drift_mV_per_h * (t / 3600.0)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "voltage_V"])
        for a, b in zip(t, v_mV / 1000.0):
            w.writerow([f"{a:.3f}", f"{b:.9f}"])
    return path


@pytest.fixture
def rest_csv(tmp_path: Path) -> Path:
    return _write_rest_csv(tmp_path / "step0_rest.csv")


def _run(argv, out_md: Path) -> int:
    return main([*argv, "--out", str(out_md)])


def _load(md_path: Path) -> dict:
    return json.loads(md_path.with_suffix(".json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# 1. 正常路径：能标定，且 sigma 回到合成真值附近
# ------------------------------------------------------------------
def test_blank_run_is_calibrated_and_recovers_the_planted_sigma(rest_csv, tmp_path):
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv)], out) == 0
    payload = _load(out)
    assert payload["sigma_noise_mV"] == pytest.approx(SIGMA_MV_TRUE, rel=0.25)
    assert payload["n_points"] >= 30


# ------------------------------------------------------------------
# 2. 报告与 JSON 必须一致（早先的实现不是）
# ------------------------------------------------------------------
def test_report_and_json_agree_when_k_is_given(rest_csv, tmp_path):
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv), "--k", "3"], out) == 0
    payload = _load(out)
    text = out.read_text(encoding="utf-8")
    assert payload["k"] == pytest.approx(3.0)
    assert payload["criterion"] is not None
    assert payload["criterion"]["is_preregistered"] is True
    # 报告里出现的阈值必须就是 JSON 里那一个
    assert f"{payload['criterion']['threshold_mV']:.3f} mV" in text


def test_report_and_json_agree_when_k_is_absent(rest_csv, tmp_path):
    """没有 k 时**两边都要说没有** —— 不许一边有阈值、一边写 null。"""
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv)], out) == 0
    payload = _load(out)
    text = out.read_text(encoding="utf-8")
    assert payload["k"] is None
    assert payload["criterion"] is None
    assert payload["k_source"] == "none"
    assert "k 未预注册" in text
    assert "k_未预注册" not in text


def test_absent_k_records_why_the_criterion_is_missing(rest_csv, tmp_path):
    """缺判据要给出**可核对的原因**，不是一个空字段。"""
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv)], out) == 0
    payload = _load(out)
    reason = payload.get("criterion_unavailable_reason", "")
    assert reason, "criterion 为 null 却没写原因 —— 下游不知道该去补什么"
    assert "--k" in reason


# ------------------------------------------------------------------
# 3. k 从预注册文件读（不占命令行）
# ------------------------------------------------------------------
def test_k_is_read_from_the_preregistration_file(rest_csv, tmp_path, monkeypatch):
    """预注册文件是 k 的正规来源；命令行只在临时覆盖时用。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prereg.yaml").write_text(
        "k: 4.5\nrationale: 'n=1800 点极值统计'\n", encoding="utf-8"
    )
    out = tmp_path / "r.md"
    rc = main([
        "--csv", str(rest_csv), "--out", str(out),
        "--prereg", str(tmp_path / "prereg.yaml"),
    ])
    assert rc == 0
    payload = _load(out)
    assert payload["k"] == pytest.approx(4.5)
    assert payload["k_source"] == "prereg_file"


def test_cli_k_wins_over_the_preregistration_file(rest_csv, tmp_path):
    p = tmp_path / "prereg.yaml"
    p.write_text("k: 4.5\n", encoding="utf-8")
    out = tmp_path / "r.md"
    rc = main([
        "--csv", str(rest_csv), "--k", "2", "--prereg", str(p),
        "--out", str(out),
    ])
    assert rc == 0
    payload = _load(out)
    assert payload["k"] == pytest.approx(2.0)
    assert payload["k_source"] == "cli"


# ------------------------------------------------------------------
# 4. 坏输入必须 fail loud（不给一个能用的数）
# ------------------------------------------------------------------
def test_missing_file_returns_error_code(tmp_path):
    assert main(["--csv", str(tmp_path / "nope.csv")]) == 2


def test_non_increasing_time_is_rejected(tmp_path):
    """时间列非递增 ⇒ 报错。插值会静默吃掉重复时间点。"""
    p = tmp_path / "bad.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "voltage_V"])
        for t in (0.0, 1.0, 1.0, 2.0) * 20:
            w.writerow([t, "0.3"])
    assert main(["--csv", str(p)]) == 2


def test_too_few_points_returns_error_code(tmp_path):
    p = tmp_path / "short.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "voltage_V"])
        for i in range(5):
            w.writerow([i, "0.3"])
    assert main(["--csv", str(p)]) == 3


def test_unknown_column_name_is_rejected(rest_csv, tmp_path):
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv), "--t-col", "nope"], out) == 2


def test_ambiguous_candidate_columns_are_not_guessed(tmp_path):
    """列名有两个候选时**不替你挑** —— 静默挑一列是这类脚本最常见的错。"""
    p = tmp_path / "amb.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "time", "voltage_V"])
        for i in range(50):
            w.writerow([i, i, "0.3"])
    assert main(["--csv", str(p)]) == 2


# ------------------------------------------------------------------
# 5. 单位不许猜
# ------------------------------------------------------------------
def test_mv_input_gives_the_same_sigma_as_v_input(tmp_path):
    """同一个序列写成 mV 或 V，标出来的 sigma 必须一致。"""
    p_v = _write_rest_csv(tmp_path / "v.csv")
    p_mv = tmp_path / "mv.csv"
    with open(p_v, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(p_mv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "voltage_mV"])
        for r in rows:
            w.writerow([r["time_s"], f"{float(r['voltage_V']) * 1000.0:.6f}"])

    out_a, out_b = tmp_path / "a.md", tmp_path / "b.md"
    assert main(["--csv", str(p_v), "--out", str(out_a)]) == 0
    assert main([
        "--csv", str(p_mv), "--v-col", "voltage_mV", "--v-unit", "mV",
        "--out", str(out_b),
    ]) == 0
    assert _load(out_a)["sigma_noise_mV"] == pytest.approx(
        _load(out_b)["sigma_noise_mV"], rel=1e-9
    )


# ------------------------------------------------------------------
# 6. 产物落在 outputs/noise_floor/ 且不碰别的地方（additive）
# ------------------------------------------------------------------
def test_artifacts_land_in_the_noise_floor_dir(rest_csv, tmp_path):
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv)], out) == 0
    assert out.is_file() and out.with_suffix(".json").is_file()


def test_script_does_not_write_outside_the_requested_output(rest_csv, tmp_path):
    """只在指定路径写两份产物 —— 没有隐藏的第三份。"""
    out = tmp_path / "r.md"
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert _run(["--csv", str(rest_csv)], out) == 0
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    added = {p.name for p in (after - before)}
    assert added == {"r.md", "r.json"}, f"多写了文件：{sorted(added)}"


def test_json_is_machine_readable_and_has_run_record_keys(rest_csv, tmp_path):
    """run_record 需要的字段必须都在，且能直接 json.loads。"""
    out = tmp_path / "r.md"
    assert _run(["--csv", str(rest_csv)], out) == 0
    payload = _load(out)
    for key in (
        "sigma_noise_mV", "n_points", "rest_window_s", "drift_mV_per_h",
        "estimator", "resolution_floor_mV", "resolution_limited",
    ):
        assert key in payload, f"run_record 需要的 {key} 不在 JSON 里"
