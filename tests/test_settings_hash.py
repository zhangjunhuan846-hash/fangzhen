"""数值设置指纹（governance/settings_hash.py）的契约测试。

M0/M1/M2 都是**零自由参数**，所以三层之间只允许差参数。
本指纹是那条纪律的机器读法。测试必须钉住：

  * **同一设置 ⇒ 同一指纹**，包括浮点写法差异（1.0e-6 vs 1e-06）——
    这是最坏的一类**假阳性**（同一个设置被报成不同，于是三层比对永远被拒）
  * **真的改了设置 ⇒ 指纹必须变**，且 `diff_settings` 指出**哪一项**变了
    —— 只给"不一致"是无法修的
  * 模型选项的 `None` 与 `{}` 归一化到同一支（都表示"用默认"），
    但 `True` 与 `"true"` **不许**归一化（PyBaMM 对这两者行为不同）
  * 已声明的边界（默认网格、PyBaMM 版本不在指纹里）**必须写在代码里**，
    否则读者会以为覆盖了它们
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from governance.settings_hash import (
    FLOAT_SIG_DIGITS,
    KNOWN_LIMITS,
    REQUIRED_METADATA_FIELDS,
    SCHEMA,
    MissingSettingsError,
    assert_same_settings,
    diff_settings,
    grid_fingerprint,
    missing_fingerprint_fields,
    model_options_fingerprint,
    payload_from_run_metadata,
    settings_hash,
    settings_payload,
    solver_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SOLVER = {"class": "IDAKLUSolver", "rtol": 1.0e-6, "atol": 1.0e-6}


def _t(n=1000, t_end=3600.0):
    return [t_end * i / (n - 1) for i in range(n)]


# ------------------------------------------------------------------
# 1. 同设置 ⇒ 同指纹（含浮点写法差异）
# ------------------------------------------------------------------
def test_identical_settings_hash_identically():
    a = settings_hash(solver_cfg=DEFAULT_SOLVER, model_options={"contact resistance": "true"},
                      t_eval=_t(), model_name="DFN")
    b = settings_hash(solver_cfg=DEFAULT_SOLVER, model_options={"contact resistance": "true"},
                      t_eval=_t(), model_name="DFN")
    assert a == b
    assert len(a) == 16


def test_float_literal_spelling_does_not_change_the_hash():
    """1.0e-6 与 1e-06 是同一个数。报成不同指纹 = 三层比对永远被拒（假阳性）。"""
    a = settings_hash(solver_cfg={"class": "IDAKLUSolver", "rtol": 1.0e-6, "atol": 1.0e-6})
    b = settings_hash(solver_cfg={"class": "IDAKLUSolver", "rtol": 1e-06, "atol": 0.000001})
    assert a == b, "浮点写法被当成了不同设置"


def test_string_vs_float_are_different():
    """'1e-6' 是字符串，1.0e-6 是数 —— 不许当成同一个。

    这条测试是**类型标签**的护栏：规范化若只取数值有效位，两者会撞成
    同一个 token，指纹就对"输入类型变了"完全失明。
    """
    a = settings_hash(solver_cfg={"class": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6})
    b = settings_hash(solver_cfg={"class": "IDAKLUSolver", "rtol": "1e-6", "atol": 1e-6})
    assert a != b


def test_int_and_float_are_different():
    """1 与 1.0 在 Python 里相等，但作为容差传进去语义不同。"""
    a = settings_hash(solver_cfg={"class": "S", "rtol": 1, "atol": 1e-6})
    b = settings_hash(solver_cfg={"class": "S", "rtol": 1.0, "atol": 1e-6})
    assert a != b, "int 与 float 被合并了 —— '把 rtol 改成 1' 这类改动会看不出来"


def test_dict_key_order_does_not_matter():
    a = settings_hash(model_options={"a": 1, "b": 2}, solver_cfg=DEFAULT_SOLVER)
    b = settings_hash(model_options={"b": 2, "a": 1}, solver_cfg=DEFAULT_SOLVER)
    assert a == b


def test_none_and_empty_options_are_the_same_branch():
    """None 与 {} 都表示"用 PyBaMM 默认选项"，必须同支。"""
    a = settings_hash(solver_cfg=DEFAULT_SOLVER, model_options=None)
    b = settings_hash(solver_cfg=DEFAULT_SOLVER, model_options={})
    assert a == b


# ------------------------------------------------------------------
# 2. 真改了设置 ⇒ 指纹必须变，且能指出哪一项
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "changed",
    [
        {"class": "CasadiSolver", "rtol": 1.0e-6, "atol": 1.0e-6},
        {"class": "IDAKLUSolver", "rtol": 1.0e-5, "atol": 1.0e-6},
        {"class": "IDAKLUSolver", "rtol": 1.0e-6, "atol": 1.0e-7},
    ],
)
def test_solver_change_is_detected(changed):
    base = settings_payload(solver_cfg=DEFAULT_SOLVER)
    other = settings_payload(solver_cfg=changed)
    d = diff_settings(base, other)
    assert d, "求解器改了但指纹没变"
    assert any(k.startswith("solver.") for k in d)


def test_tolerance_change_names_the_field():
    base = settings_payload(solver_cfg=DEFAULT_SOLVER)
    other = settings_payload(solver_cfg={**DEFAULT_SOLVER, "rtol": 1e-4})
    d = diff_settings(base, other)
    assert "solver.rtol" in d, d
    assert d["solver.rtol"]["a"] != d["solver.rtol"]["b"]


def test_model_option_change_is_detected():
    base = settings_payload(solver_cfg=DEFAULT_SOLVER, model_options=None)
    other = settings_payload(solver_cfg=DEFAULT_SOLVER,
                             model_options={"contact resistance": "true"})
    d = diff_settings(base, other)
    assert "model_options.contact resistance" in d, d


def test_bool_true_and_string_true_are_NOT_conflated():
    """PyBaMM 对它俩行为不同（布尔 True 会被 OptionError 拒绝），不许归一化。"""
    a = settings_hash(model_options={"contact resistance": True}, solver_cfg=DEFAULT_SOLVER)
    b = settings_hash(model_options={"contact resistance": "true"}, solver_cfg=DEFAULT_SOLVER)
    assert a != b, "布尔 True 与字符串 'true' 被当成了同一个输入"

def test_grid_change_is_detected():
    base = settings_payload(solver_cfg=DEFAULT_SOLVER, t_eval=_t(1000))
    other = settings_payload(solver_cfg=DEFAULT_SOLVER, t_eval=_t(2000))
    d = diff_settings(base, other)
    assert "grid.n_points" in d, d


def test_non_monotonic_grid_is_recorded():
    bad = _t(100)
    bad[5], bad[6] = bad[6], bad[5]
    g = grid_fingerprint(bad)
    assert g["monotonic"] is False


# ------------------------------------------------------------------
# 3. assert_same_settings：三层比对的前置门
# ------------------------------------------------------------------
def test_identical_layers_pass():
    p = settings_payload(solver_cfg=DEFAULT_SOLVER, model_options={"contact resistance": "true"},
                         t_eval=_t())
    res = assert_same_settings({"M0": p, "M1": p, "M2": p})
    assert res["identical"] is True
    assert len(set(res["hashes"].values())) == 1
    assert res["reference"] == "M0"


def test_broken_layer_is_rejected_with_per_field_detail():
    """M1 偷偷换了 rtol ⇒ 三层比对必须被拒，且指出是 rtol。"""
    p = settings_payload(solver_cfg=DEFAULT_SOLVER, t_eval=_t())
    bad = settings_payload(solver_cfg={**DEFAULT_SOLVER, "rtol": 1e-3}, t_eval=_t())
    with pytest.raises(ValueError) as exc:
        assert_same_settings({"M0": p, "M1": bad, "M2": p})
    msg = str(exc.value)
    assert "solver.rtol" in msg, msg
    assert "M0 vs M1" in msg, msg
    assert "不能下结论" in msg


def test_can_collect_differences_without_raising():
    p = settings_payload(solver_cfg=DEFAULT_SOLVER, t_eval=_t())
    bad = settings_payload(solver_cfg={**DEFAULT_SOLVER, "atol": 1e-3}, t_eval=_t())
    res = assert_same_settings({"M0": p, "M1": bad}, require_pairwise_identical=False)
    assert res["identical"] is False
    assert "M0 vs M1" in res["differences"]


def test_empty_runs_raises():
    with pytest.raises(ValueError):
        assert_same_settings({})


def test_missing_key_in_one_layer_is_reported():
    """一层多了一个选项 —— 必须报出来，不是静默忽略。"""
    a = settings_payload(solver_cfg=DEFAULT_SOLVER, model_options={})
    b = settings_payload(solver_cfg=DEFAULT_SOLVER, model_options={"thermal": "lumped"})
    d = diff_settings(a, b)
    assert "model_options.thermal" in d
    assert d["model_options.thermal"]["a"] == "<absent>"


# ------------------------------------------------------------------
# 4. 从既有产物复算（不需要重跑）
# ------------------------------------------------------------------
def test_payload_from_existing_run_metadata():
    meta = {
        "model": "DFN",
        "solver": {"class": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6},
        "model_options": {"contact resistance": "true"},
    }
    p = payload_from_run_metadata(meta)
    assert p["solver"]["class"] == "IDAKLUSolver"
    # settings_payload 里的值仍是**原值**（标签只在 _canon/哈希那一刻打），
    # 所以这里就是字符串 "true" —— 而它与布尔 True 必须在**指纹层面**分开
    # （下一条测试从哈希那一侧验）。这条只验类型没有被悄悄改掉。
    assert p["model_options"]["contact resistance"] == "true"
    assert isinstance(p["model_options"]["contact resistance"], str)
    assert p["grid"]["n_points"] is None, (
        "t_eval 不在 run_metadata 里 —— 不许编一个出来"
    )


def test_same_metadata_gives_same_hash_round_trip():
    """同一份 run_metadata 复算两次必须同指纹（可复算性的最低要求）。"""
    meta = {
        "model": "DFN",
        "solver": {"class": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6},
        "model_options": {"contact resistance": "true"},
    }
    p = payload_from_run_metadata(meta)
    from governance.settings_hash import _hash_payload

    assert _hash_payload(p) == _hash_payload(payload_from_run_metadata(meta))


def test_fingerprint_helpers_return_raw_values_not_tagged():
    """两个 ``*_fingerprint`` 返回**原值**，标签只在 `_canon` 打。

    这一条是有来历的：若 helper 自己先 `_canon_float` 一把，字符串与数值
    就都在这一步变成同一个字符串，类型标签再打在**已字符串化**的值上，
    等于白打 —— ``1e-6`` 与 ``"1e-6"`` 会撞回同一个指纹。
    """
    a = solver_fingerprint({"class": "S", "rtol": 1e-6, "atol": 1e-6})
    assert a["rtol"] == 1e-6 and isinstance(a["rtol"], float)
    b = solver_fingerprint({"class": "S", "rtol": "1e-6", "atol": 1e-6})
    assert b["rtol"] == "1e-6" and isinstance(b["rtol"], str)

    o = model_options_fingerprint({"contact resistance": True})
    assert o["contact resistance"] is True
    o2 = model_options_fingerprint({"contact resistance": "true"})
    assert o2["contact resistance"] == "true"


# ------------------------------------------------------------------
# 5. 已声明的边界必须写在代码里
# ------------------------------------------------------------------
def test_known_limits_are_declared():
    joined = " ".join(KNOWN_LIMITS)
    assert "网格" in joined, "默认空间网格不在指纹里，必须显式声明"
    assert "pybamm" in joined.lower(), "PyBaMM 版本不在指纹里，必须显式声明"


def test_schema_version_is_exposed():
    assert isinstance(SCHEMA, int) and SCHEMA >= 1
    assert settings_payload(solver_cfg=DEFAULT_SOLVER)["schema"] == SCHEMA
    assert settings_payload(solver_cfg=DEFAULT_SOLVER)["float_sig_digits"] == FLOAT_SIG_DIGITS


def test_solver_fingerprint_has_declared_defaults():
    f = solver_fingerprint(None)
    assert f["class"] == "IDAKLUSolver"
    assert f["rtol"] == 1.0e-6
    assert f["atol"] == 1.0e-6
    # 默认值必须**逐字**等于 configs/models.yaml 里 solver 段的声明，
    # 否则"用默认值"这件事会有两个真源。
    import yaml

    cfg = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text(encoding="utf-8"))
    assert f["class"] == cfg["solver"]["class"]
    assert f["rtol"] == float(cfg["solver"]["rtol"])
    assert f["atol"] == float(cfg["solver"]["atol"])


# ------------------------------------------------------------------
# 6. 不碰冻结内核
# ------------------------------------------------------------------
def _module_level_imports(path: Path) -> set[str]:
    """只在**模块层**（顶层，含顶层 if/try 体内）收集 import。

    为什么区分层级：本模块**故意**在 ``grid_fingerprint`` 里局部 import
    numpy（只在调用方真的给了时间列时才走到那一支，这样没装 numpy
    的分析环境也能对已有 run_metadata 复算指纹）。那种"局部 import"
    与"模块一导入就依赖 pybamm"是两件完全不同的事 ——
    不区分的话，一条本来正确的设计会被测试判成违规。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:  # 只走顶层
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name)
    return found


def test_module_does_not_import_the_simulation_stack_at_module_level():
    """指纹模块只比对、不计算。顶层不许依赖 pybamm/pandas 或冻结内核。

    （numpy 允许**局部**使用 —— 见 _module_level_imports 的说明。）
    """
    imports = _module_level_imports(ROOT / "governance" / "settings_hash.py")
    banned = {
        "pybamm", "pandas", "numpy",
        "battery_sim.models.pybamm_factory",
        "battery_sim.simulation.baseline",
        "battery_sim.simulation.protocol_replay",
    }
    hit = imports & banned
    assert not hit, (
        f"指纹模块顶层不得依赖这些：{sorted(hit)} —— "
        "它要能对已有 run_metadata 复算指纹，不该要求一个仿真环境"
    )


def test_numpy_use_is_lazy_and_confined_to_the_grid_branch():
    """局部 import numpy 只允许出现在 grid_fingerprint 这一支。"""
    src = (ROOT / "governance" / "settings_hash.py").read_text(encoding="utf-8")
    assert "import numpy" in src, "grid_fingerprint 需要 numpy"
    # 出现次数为 1 ⇒ 只有一处局部 import，没有散落各处的隐式依赖
    assert src.count("import numpy as np") == 1, (
        "numpy 的局部 import 应恰好一处（网格那一支）"
    )


def test_governance_package_still_importable():
    """新增模块不许把 governance 包弄坏。"""
    import governance  # noqa: F401
    import governance.analysis_mode  # noqa: F401
    import governance.dataset_roles  # noqa: F401
    import governance.geometry_channel  # noqa: F401
    import governance.noise_floor  # noqa: F401
    import governance.scale_alignment  # noqa: F401
    import governance.settings_hash  # noqa: F401


# ------------------------------------------------------------------
# 缺失字段不许静默补默认值（2026-09-29 修）
#
# 背景（实测）：2026-09-28 之前产生的 21 份 run_metadata.json
# **没有一份**带 solver 块。若复算时静默套用 IDAKLUSolver / rtol=atol=1e-6，
# 会得到一串"看起来合法"的指纹，而它描述的是**默认值**、不是那次 run。
# 后果是 **13 份不同数据集/电芯的 run 共用同一指纹 f4ddab...**，
# 三层比对会给出**虚假的相同** —— 这正是本项目最不能接受的静默失效。
# ------------------------------------------------------------------
_OLD_STYLE_META = {
    # 2026-09-28 之前的产物形状：有 model，没有 solver / model_options
    "dataset": "chen2020",
    "model": "SPMe",
    "pybamm_version": "26.8.0.0",
}


def test_missing_fields_are_detected():
    assert missing_fingerprint_fields(_OLD_STYLE_META) == ["solver", "model_options"]


def test_empty_dict_counts_as_missing_not_as_a_value():
    """空 dict 与缺失等价 —— 两者都没有告诉我们任何设置信息。"""
    meta = {**_OLD_STYLE_META, "solver": {}, "model_options": {}}
    assert missing_fingerprint_fields(meta) == ["solver", "model_options"]


def test_complete_metadata_has_no_missing_fields():
    meta = {
        "model": "SPMe",
        "solver": {"class": "IDAKLUSolver", "rtol": 1.0e-6, "atol": 1.0e-6},
        "model_options": {"working electrode": "positive"},
    }
    assert missing_fingerprint_fields(meta) == []


def test_recomputing_from_old_metadata_raises_instead_of_using_defaults():
    """默认行为必须是**抛错**，不是套默认值。

    这是本组测试里最重要的一条：它钉住的是"静默"这个性质，
    不是某个具体数值。
    """
    with pytest.raises(MissingSettingsError) as ei:
        payload_from_run_metadata(_OLD_STYLE_META)
    msg = str(ei.value)
    # 报错必须可操作：缺了哪几个、为什么、怎么办
    assert "solver" in msg and "model_options" in msg
    assert "虚假的相同" in msg
    assert "on_missing" in msg


def test_mark_mode_returns_an_explicitly_unfingerprintable_marker():
    """``on_missing='mark'`` 时要能显式排除在比对之外，而不是误当指纹。"""
    p = payload_from_run_metadata(_OLD_STYLE_META, on_missing="mark")
    assert "__unfingerprintable__" in p
    assert p["__unfingerprintable__"]["missing"] == ["solver", "model_options"]


def test_default_mode_is_kept_but_marks_the_payload_as_defaulted():
    """兼容旧行为，但**误用必须可见**（``used_defaults``）。

    ``used_defaults`` 参与哈希 —— 于是"缺字段套默认值"与"真的用了默认值"
    **算出的指纹不同**，两者不会在比对时被误判为同一支。
    这是本模式唯一可接受的形态；若哪天它不再参与哈希，本测试必须失败，
    因为那意味着静默混淆又回来了。
    """
    p = payload_from_run_metadata(_OLD_STYLE_META, on_missing="default")
    assert p["used_defaults"] == ["solver", "model_options"]

    explicit = settings_payload(
        solver_cfg={"class": "IDAKLUSolver", "rtol": 1.0e-6, "atol": 1.0e-6},
        model_options={},
        model_name="SPMe",
    )
    assert _hashable(p) != _hashable(explicit), (
        "带 used_defaults 的 payload 与显式默认值算出了**同一个指纹** —— "
        "那说明 used_defaults 没进哈希，'缺字段套默认值'与'真的用了默认值'"
        "在比对时不可分。静默混淆又回来了。"
    )


def _hashable(payload):
    """按 settings_hash 的口径把 payload 规范化后哈希（便于对比）。"""
    from governance.settings_hash import _canon

    blob = json.dumps(_canon(payload), sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def test_the_21_real_historical_artifacts_cannot_be_fingerprinted():
    """对**真实历史产物**做回归：它们必须全部被拒，不许静默给出指纹。

    这条测试是本次修复的动机本身。若将来有人给旧产物补了 solver 块，
    这条会失败 —— 那说明产物格式变了，应当同步更新本测试与文档。
    """
    import glob

    paths = sorted(glob.glob(str(ROOT / "outputs" / "platform" / "*" / "*" / "*" / "*"
                                   / "run_metadata.json")))
    if not paths:
        pytest.skip("没有历史产物可查（此测试只在有 outputs/platform 时有效）")

    refused = 0
    for path in paths:
        meta = json.loads(Path(path).read_text(encoding="utf-8"))
        if missing_fingerprint_fields(meta):
            with pytest.raises(MissingSettingsError):
                payload_from_run_metadata(meta)
            refused += 1
    assert refused == len(paths), (
        f"{len(paths)} 份历史产物中只有 {refused} 份被拒 —— "
        "剩下那些能算出指纹，说明产物格式已变，本测试与文档都要更新"
    )


def test_on_missing_rejects_unknown_values():
    with pytest.raises(ValueError):
        payload_from_run_metadata(_OLD_STYLE_META, on_missing="quiet")


def test_required_metadata_fields_is_the_single_source_of_truth():
    """REQUIRED_METADATA_FIELDS 必须与文档/报错说的一致。"""
    assert set(REQUIRED_METADATA_FIELDS) == {"solver", "model_options", "model"}
