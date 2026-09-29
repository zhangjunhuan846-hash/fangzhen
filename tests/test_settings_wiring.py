# -*- coding: utf-8 -*-
"""settings_hash 接线器（user_tools/settings_wiring.py）的契约测试。

这个文件存在的理由：缺口 3 的真正形态不是"模块没有"（模块早就有、也有测试），
而是**"模板里挖了四个槽位，没有任何代码去填"** ——
实测 `grep -rn "settings_hash_per_level" --include=*.py . | grep -v tests/` = 0 命中。

所以这里测的不是"算得对不对"（那是 test_settings_hash.py 的职责），
而是 **"填得进去、且不许说假话"**：

  * 四个槽位名必须与 run_record.yaml 一字不差（名字错 = 手抄会错位）
  * 不可复算的层必须被显式排除，**不许静默套默认值**
  * 只要有一层不可复算，总判定必须是 'unknown'，**不许是 True**
  * 设置真不一致时退出码 2（结论级红线）
  * 三层真的相同时才给 True

纯标准库 + yaml，不 import pybamm、不需要网络。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
RUN_RECORD = ROOT / "templates" / "commercial_graphite_ht" / "run_record.yaml"

from user_tools.settings_wiring import (  # noqa: E402
    SLOT_DIFF_DETAIL,
    SLOT_IDENTICAL,
    SLOT_KNOWN_LIMITS,
    SLOT_PER_LEVEL,
    UNKNOWN,
    collect,
)

#: 一份**真实的** scheduler 设置，用于构造"新式 run"。
_SOLVER = {"class": "CasadiSolver", "rtol": 1e-6, "atol": 1e-6}
#: ⚠️ 必须**非空**：settings_hash.missing_fingerprint_fields() 明确把空 dict
#: 视同缺失（"空 dict 没有告诉我们任何设置信息"）。这是那个模块的设计，
#: 测试必须照着它的语义来，不能自作主张用 {} 然后抱怨。
_OPTIONS = {"contact resistance": "true"}


def _write_meta(tmp_path: Path, name: str, *, solver=None, options=None) -> Path:
    """造一份 run_metadata.json。solver/options 为 None 时**不写**这两个键，
    模拟 2026-09-28 之前的旧产物。"""
    meta = {"model": "SPM", "parameter_set": "Chen2020"}
    if solver is not None:
        meta["solver"] = solver
    if options is not None:
        meta["model_options"] = options
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return p


# ------------------------------------------------------------------
# 槽位名必须与模板一字不差
# ------------------------------------------------------------------
def test_slot_names_match_the_template_exactly():
    """工具写出的槽位名 = 模板里的槽位名。差一个字就是手抄错位。"""
    doc = yaml.safe_load(RUN_RECORD.read_text(encoding="utf-8"))
    for slot in (SLOT_PER_LEVEL, SLOT_IDENTICAL, SLOT_DIFF_DETAIL, SLOT_KNOWN_LIMITS):
        assert slot in doc, (
            f"run_record.yaml 里没有槽位 {slot} —— 工具填的名字与模板对不上"
        )


def test_slots_are_actually_empty_in_the_shipped_template():
    """四个槽位在模板里应是**空**的：有默认值会被误读成'已填'。"""
    doc = yaml.safe_load(RUN_RECORD.read_text(encoding="utf-8"))
    assert doc[SLOT_PER_LEVEL] == {}
    assert doc[SLOT_IDENTICAL] == ""
    assert doc[SLOT_DIFF_DETAIL] == ""
    assert doc[SLOT_KNOWN_LIMITS] == []


# ------------------------------------------------------------------
# 核心：不可复算的层不许被静默套默认值
# ------------------------------------------------------------------
def test_unfingerprintable_level_is_excluded_not_defaulted(tmp_path):
    """旧 run（缺 solver/model_options）⇒ 指纹为 None，判定为 unknown。

    这是整个接线的**关键防呆**：套默认值会造出"看起来合法其实描述默认值"
    的指纹，使三层比对给出**虚假的相同**。
    """
    m0 = _write_meta(tmp_path, "M0")  # 旧式：两个键都没有
    m1 = _write_meta(tmp_path, "M1")
    res = collect(["M0", "M1"], {"M0": m0, "M1": m1})

    assert res[SLOT_PER_LEVEL]["M0"] is None, "不可复算的层不许有指纹"
    assert res[SLOT_PER_LEVEL]["M1"] is None
    assert res[SLOT_IDENTICAL] == UNKNOWN, (
        "至少一层不可复算时，总判定必须是 'unknown' —— "
        "给 True 就是说假话"
    )
    assert set(res["_unfingerprintable"]) == {"M0", "M1"}
    assert res["_missing_fields"]["M0"], "必须报出缺了哪些字段"


def test_empty_dict_options_count_as_missing(tmp_path):
    """空 dict 视同缺失 —— 与 settings_hash 的既有语义一致。"""
    m0 = _write_meta(tmp_path, "M0", solver=_SOLVER, options={})
    res = collect(["M0"], {"M0": m0})
    assert res[SLOT_PER_LEVEL]["M0"] is None
    assert "model_options" in res["_missing_fields"]["M0"]


def test_partial_availability_still_gives_unknown(tmp_path):
    """一层可复算 + 一层不可复算 ⇒ 仍然 unknown（不许因为"能算的那层相同"就说 True）。"""
    m0 = _write_meta(tmp_path, "M0", solver=_SOLVER, options=_OPTIONS)
    m1 = _write_meta(tmp_path, "M1")  # 旧式
    res = collect(["M0", "M1"], {"M0": m0, "M1": m1})
    assert res[SLOT_PER_LEVEL]["M0"] is not None
    assert res[SLOT_PER_LEVEL]["M1"] is None
    assert res[SLOT_IDENTICAL] == UNKNOWN, (
        "只有全部层都可复算时才敢写 True"
    )


# ------------------------------------------------------------------
# 正向：三层真的相同
# ------------------------------------------------------------------
def test_identical_new_style_runs_give_true(tmp_path):
    paths, names = {}, []
    for n in ("M0", "M1", "M2"):
        paths[n] = _write_meta(tmp_path, n, solver=_SOLVER, options=_OPTIONS)
        names.append(n)
    res = collect(names, paths)

    assert all(res[SLOT_PER_LEVEL][n] for n in names), "三层都该有指纹"
    assert len(set(res[SLOT_PER_LEVEL].values())) == 1, "相同设置应得同一指纹"
    assert res[SLOT_IDENTICAL] is True
    assert res[SLOT_DIFF_DETAIL] == ""


def test_different_solver_is_flagged_not_silently_passed(tmp_path):
    """求解器容差不同 ⇒ 判定 False，且 detail 要**逐字段**指出差在哪。

    为什么逐字段：只报"不一致"是无法修的。
    """
    m0 = _write_meta(tmp_path, "M0", solver=_SOLVER, options=_OPTIONS)
    m2 = _write_meta(tmp_path, "M2",
                     solver={"class": "CasadiSolver", "rtol": 1e-4, "atol": 1e-4},
                     options=_OPTIONS)
    res = collect(["M0", "M2"], {"M0": m0, "M2": m2})

    assert res[SLOT_IDENTICAL] is False
    assert "rtol" in res[SLOT_DIFF_DETAIL] and "atol" in res[SLOT_DIFF_DETAIL], (
        "差异明细必须逐字段列出，否则拿到结果也不知道改什么"
    )
    assert res.get("_inconsistent") is True


def test_known_limits_come_from_the_module(tmp_path):
    """已知边界必须从模块抄来，随结果一起引用。"""
    from governance.settings_hash import KNOWN_LIMITS

    m0 = _write_meta(tmp_path, "M0", solver=_SOLVER, options=_OPTIONS)
    res = collect(["M0"], {"M0": m0})
    assert res[SLOT_KNOWN_LIMITS] == list(KNOWN_LIMITS)
    assert len(res[SLOT_KNOWN_LIMITS]) > 0


# ------------------------------------------------------------------
# 端到端：退出码（四种状态必须区分开）
# ------------------------------------------------------------------
def _run(tmp_path, levels, extra=()):
    cmd = [sys.executable, "-m", "user_tools.settings_wiring"]
    for n, p in levels:
        cmd += ["--level", f"{n}={p}"]
    cmd += list(extra)
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180)


def test_exit_code_0_when_identical(tmp_path):
    paths = []
    for n in ("M0", "M1"):
        paths.append((n, _write_meta(tmp_path, n, solver=_SOLVER, options=_OPTIONS)))
    r = _run(tmp_path, paths)
    assert r.returncode == 0, r.stderr
    assert "True" in r.stdout


def test_exit_code_2_when_inconsistent(tmp_path):
    """设置不一致 = 结论级红线 ⇒ rc=2，与"输入错"(1) 区分开。"""
    p0 = _write_meta(tmp_path, "M0", solver=_SOLVER, options=_OPTIONS)
    p2 = _write_meta(tmp_path, "M2",
                     solver={"class": "CasadiSolver", "rtol": 1e-3, "atol": 1e-3},
                     options=_OPTIONS)
    r = _run(tmp_path, [("M0", p0), ("M2", p2)])
    assert r.returncode == 2, f"期望 2，得到 {r.returncode}\n{r.stdout}\n{r.stderr}"


def test_exit_code_0_when_unfingerprintable(tmp_path):
    """不可复算是**事实**，不是错误 —— 退出码应为 0。"""
    r = _run(tmp_path, [("M0", _write_meta(tmp_path, "M0"))])
    assert r.returncode == 0, r.stderr
    assert UNKNOWN in r.stdout


def test_exit_code_1_on_missing_input(tmp_path):
    r = _run(tmp_path, [("M0", tmp_path / "nope.json")])
    assert r.returncode == 1


def test_duplicate_level_names_are_refused(tmp_path):
    """层级名重复 ⇒ 直接拒绝（名字是比对表主键，重复会互相覆盖）。"""
    p = _write_meta(tmp_path, "M0", solver=_SOLVER, options=_OPTIONS)
    r = _run(tmp_path, [("M0", p), ("M0", p)])
    assert r.returncode != 0
    assert "重复" in (r.stdout + r.stderr)


def test_check_mode_answers_fingerprintability(tmp_path):
    """--check 只回答"能不能复算"，不比对。"""
    p = _write_meta(tmp_path, "M0")
    r = _run(tmp_path, [("M0", p)], extra=["--check"])
    assert r.returncode == 0
    assert "不可复算" in r.stdout


def test_real_outputs_currently_have_no_fingerprintable_run():
    """把实测事实钉住：现有 61 份 run_metadata **没有一份**能复算指纹。

    这不是"期望如此"的断言，是**记录一个必须被知道的事实**。
    若将来有新 run 带上了 solver 块，这条会红 —— 那时应当更新它，
    并把该 run 当作三层比对的起点。
    """
    import json as _json

    metas = sorted((ROOT / "outputs").rglob("run_metadata.json"))
    if not metas:
        pytest.skip("outputs/ 下没有 run_metadata.json（干净检出）")

    from governance.settings_hash import missing_fingerprint_fields

    n_ok = 0
    for p in metas:
        try:
            meta = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not missing_fingerprint_fields(meta):
            n_ok += 1
    assert n_ok == 0, (
        f"现在有 {n_ok} 份 run 可以复算指纹了（此前为 0）。"
        "这是好消息 —— 请把该 run 用作三层比对的起点，并更新本测试的期望值。"
    )
