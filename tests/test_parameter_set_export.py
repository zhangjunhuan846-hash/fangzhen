# ============================================================
# 测试：参数集导出 / 加载 / 校验
#
# 这一层的价值是"让运行时状态变成可归档的文件"，所以测试围绕三件事：
#   1. 该进文件的进了（标量、输入指纹），不该进的被**明确标出**（函数）；
#   2. 输入变了必须被指纹抓住（否则归档记录就是假证据）；
#   3. 标量漂移必须被 diff 抓住（改参数忘了重导出 = 静默不一致）。
#
# 用普通 dict 代替 ParameterValues：本模块只要求 .keys() 与 []，
# 于是这些测试不需要求解器环境。
# ============================================================

import json

import pytest

from parameters.export_parameter_set import (
    EXPORT_VERSION,
    ParameterSetMismatch,
    apply_scalars,
    collect_non_scalars,
    collect_scalars,
    export_parameter_set,
    load_parameter_set,
    scalar_diff,
    sha256,
    summarise,
    verify_inputs,
)


def _fake_pv():
    return {
        "Positive particle radius [m]": 13.7e-6,
        "Positive electrode thickness [m]": 6.4e-5,
        "Lower voltage cut-off [V]": 0.005,
        "Upper voltage cut-off [V]": 3.2,
        "Nominal cell capacity [A.h]": 2.2464e-3,
        "Positive electrode diffusivity [m2.s-1]": lambda sto: sto,
        "Positive electrode OCP [V]": lambda sto: sto,
        "A list that is not a scalar": [1, 2, 3],
        "flag": True,
    }


def test_outputdir_export_roundtrip(tmp_path):
    src = tmp_path / "ocp.csv"
    src.write_text("SOC,Voltage\n0,3.0\n1,0.01\n", encoding="utf-8")

    out = export_parameter_set(
        _fake_pv(), tmp_path / "sets" / "demo.json",
        set_id="demo_v1",
        provenance={"grade": "apparent_ds"},
        inputs=[(src, "OCP table")],
        recipe={"module": "m", "function": "f", "kwargs": {"a": 1}},
        metadata={"cell": "X"},
    )
    assert out.is_file()
    data = load_parameter_set(out)
    assert data["export_version"] == EXPORT_VERSION
    assert data["set_id"] == "demo_v1"
    assert data["recipe"]["function"] == "f"
    assert data["provenance"]["grade"] == "apparent_ds"


def test_scalars_are_snapshotted_and_functions_are_declared_not_saved(tmp_path):
    out = export_parameter_set(_fake_pv(), tmp_path / "s.json", set_id="s")
    data = load_parameter_set(out)

    scal = data["scalars"]
    assert scal["Positive particle radius [m]"] == 13.7e-6
    assert scal["flag"] is True
    # 非标量绝不混进 scalars
    assert "Positive electrode diffusivity [m2.s-1]" not in scal
    assert "A list that is not a scalar" not in scal

    non = data["non_scalars"]
    assert set(non) == {
        "Positive electrode diffusivity [m2.s-1]",
        "Positive electrode OCP [V]",
        "A list that is not a scalar",
    }
    # 函数条目必须**明说**不可序列化，而不是假装存下来了
    assert non["Positive electrode OCP [V]"]["serialisable"] is False
    assert "函数体不入文件" in non["Positive electrode OCP [V]"]["note"]


def test_repr_of_callables_is_stripped_of_memory_addresses():
    pv = {"f": lambda x: x}
    assert "0x..." in collect_non_scalars(pv)["f"]["repr"]
    assert "0x0" not in collect_non_scalars(pv)["f"]["repr"]


def test_inputs_get_a_real_sha256(tmp_path):
    src = tmp_path / "d.csv"
    src.write_text("SOC,D\n0.5,1e-14\n", encoding="utf-8")
    out = export_parameter_set(_fake_pv(), tmp_path / "s.json", set_id="s",
                               inputs=[(src, "D_s table")])
    data = load_parameter_set(out)
    rec = data["inputs"][0]
    assert rec["role"] == "D_s table"
    assert rec["sha256"] == sha256(src)
    assert rec["size_bytes"] == src.stat().st_size


def test_changing_an_input_breaks_verification(tmp_path):
    """归档记录必须真的能证明"输入没变"，否则它只是装饰。"""
    src = tmp_path / "d.csv"
    src.write_text("a\n1\n", encoding="utf-8")
    out = export_parameter_set(_fake_pv(), tmp_path / "s.json", set_id="s",
                               inputs=[(src, "D_s table")])
    data = load_parameter_set(out)
    assert verify_inputs(data) == {}

    src.write_text("a\n2\n", encoding="utf-8")
    problems = verify_inputs(data, strict=False)
    assert "sha256 不符" in list(problems.values())[0]
    with pytest.raises(ParameterSetMismatch, match="指纹校验失败"):
        verify_inputs(data, strict=True)


def test_missing_input_is_recorded_and_detected(tmp_path):
    out = export_parameter_set(
        _fake_pv(), tmp_path / "s.json", set_id="s",
        inputs=[(tmp_path / "nope.csv", "absent")],
    )
    data = load_parameter_set(out)
    rec = data["inputs"][0]
    assert rec["missing"] is True
    assert rec["sha256"] is None
    # verify_inputs 以记录下来的那个路径为键（仓库外的路径是绝对路径）
    assert verify_inputs(data, strict=False)[rec["path"]] == "文件不存在"


def test_scalar_diff_is_empty_when_nothing_drifted(tmp_path):
    pv = _fake_pv()
    out = export_parameter_set(pv, tmp_path / "s.json", set_id="s")
    assert scalar_diff(pv, load_parameter_set(out)) == {}


def test_scalar_diff_catches_a_changed_parameter(tmp_path):
    pv = _fake_pv()
    out = export_parameter_set(pv, tmp_path / "s.json", set_id="s")
    pv = dict(pv)
    pv["Positive electrode thickness [m]"] = 7.0e-5
    diff = scalar_diff(pv, load_parameter_set(out))
    assert list(diff) == ["Positive electrode thickness [m]"]
    assert diff["Positive electrode thickness [m]"] == (7.0e-5, 6.4e-5)


def test_scalar_diff_reports_keys_that_only_exist_on_one_side(tmp_path):
    out = export_parameter_set(_fake_pv(), tmp_path / "s.json", set_id="s")
    loaded = load_parameter_set(out)
    loaded["scalars"]["brand new key"] = 1.0
    diff = scalar_diff(_fake_pv(), loaded)
    assert diff["brand new key"] == ("<absent>", 1.0)


def test_apply_scalars_overlays_and_refuses_unknown_keys(tmp_path):
    pv = _fake_pv()
    out = export_parameter_set(pv, tmp_path / "s.json", set_id="s")
    loaded = load_parameter_set(out)
    loaded["scalars"]["Positive particle radius [m]"] = 5.0e-6

    merged = apply_scalars(pv, loaded)
    assert merged["Positive particle radius [m]"] == 5.0e-6
    assert pv["Positive particle radius [m]"] == 13.7e-6     # 原集不被改

    loaded["scalars"]["a key the model does not know"] = 1.0
    with pytest.raises(KeyError, match="拒绝默默忽略"):
        apply_scalars(pv, loaded)


def test_load_rejects_a_foreign_json(tmp_path):
    p = tmp_path / "foreign.json"
    p.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(ValueError, match="不像本模块导出"):
        load_parameter_set(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_parameter_set(tmp_path / "absent.json")


def test_summarise_reports_the_shape_of_the_export(tmp_path):
    src = tmp_path / "x.csv"
    src.write_text("a\n1\n", encoding="utf-8")
    out = export_parameter_set(_fake_pv(), tmp_path / "s.json", set_id="s",
                               inputs=[(src, "x")],
                               recipe={"module": "m", "function": "f"})
    s = summarise(load_parameter_set(out))
    assert s["set_id"] == "s"
    assert s["n_scalars"] == len(collect_scalars(_fake_pv()))
    assert s["n_non_scalars"] == 3
    assert s["n_inputs"] == 1
    assert s["recipe"]["function"] == "f"


# ------------------------------------------------------------------
# 真实产物：存在、可加载、指纹仍然对得上
# ------------------------------------------------------------------
def test_exported_graphite_sets_are_present_and_verify():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    idx = (root / "outputs" / "analysis" / "graphite_phaseB16"
           / "parameter_sets" / "parameter_sets_index.json")
    if not idx.is_file():
        pytest.skip("参数集尚未导出（运行 scripts/export_graphite_parameter_sets.py）")
    sets = json.loads(idx.read_text(encoding="utf-8"))["sets"]
    assert len(sets) == 4
    for item in sets:
        loaded = load_parameter_set(
            idx.parent / item["file"]
        )
        assert loaded["set_id"] == item["set_id"]
        # 输入指纹必须仍然成立：这些表自导出以来没有被改过
        assert verify_inputs(loaded, strict=False) == {}
        assert "apparent" in loaded["provenance"]["quantity"].lower()
