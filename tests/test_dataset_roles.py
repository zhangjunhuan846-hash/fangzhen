# ============================================================
# 测试：数据用途治理（governance/dataset_roles.py）
#
# 这一层的价值全在"把验证数据用于标定必须报错"这一条上，
# 所以测试围绕**边界与负例**写，而不是围绕 happy path。
#
# 其中 test_no_dataset_is_undeclared 是常驻守卫：将来有人往
# configs/datasets.yaml 里加数据集却忘了写 dataset_role，
# 测试会直接失败——声明缺口不可能悄悄溜进仓库。
# ============================================================

from pathlib import Path

import pytest
import yaml

from governance.dataset_roles import (
    ALLOWED_DECLARED_ROLES,
    ROLE_BENCHMARK,
    ROLE_IDENTIFICATION,
    ROLE_PREDICTION,
    ROLE_UNSPECIFIED,
    ROLE_VALIDATION,
    USE_CALIBRATE,
    USE_EVALUATE,
    RoleViolation,
    assert_calibration_allowed,
    audit_config,
    check,
    may,
    normalise,
    resolve_role,
    role_notes_from_config,
    roles_from_config,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / "configs" / "datasets.yaml"

CALIBRATION_FORBIDDEN = (ROLE_VALIDATION, ROLE_BENCHMARK, ROLE_PREDICTION)


# ------------------------------------------------------------------
# 词表
# ------------------------------------------------------------------
def test_role_vocabulary_includes_the_three_named_roles_plus_benchmark():
    assert ROLE_IDENTIFICATION in ALLOWED_DECLARED_ROLES
    assert ROLE_VALIDATION in ALLOWED_DECLARED_ROLES
    assert ROLE_PREDICTION in ALLOWED_DECLARED_ROLES
    # benchmark 是刻意加的第四个：CALCE 这类 surrogate 比较
    # 既不是识别集，也不许被叫做 validation
    assert ROLE_BENCHMARK in ALLOWED_DECLARED_ROLES
    assert ROLE_UNSPECIFIED not in ALLOWED_DECLARED_ROLES


def test_normalise_accepts_blank_as_unspecified_and_rejects_junk():
    assert normalise(None) == ROLE_UNSPECIFIED
    assert normalise("") == ROLE_UNSPECIFIED
    assert normalise("  Validation ") == ROLE_VALIDATION
    assert normalise("BENCHMARK") == ROLE_BENCHMARK
    with pytest.raises(ValueError, match="dataset_role 非法"):
        normalise("training")


def test_declared_unspecified_is_not_a_declarable_value():
    # 写 "unspecified" 等于没写：normalise 接受它，但它不在可声明集合里
    assert normalise("unspecified") == ROLE_UNSPECIFIED


# ------------------------------------------------------------------
# 门：负例才是重点
# ------------------------------------------------------------------
def test_calibration_is_forbidden_for_every_non_identification_role():
    for role in CALIBRATION_FORBIDDEN:
        assert may(role, USE_EVALUATE) is True
        assert may(role, USE_CALIBRATE) is False
        with pytest.raises(RoleViolation, match="不允许用于 'calibrate'"):
            check(role, USE_CALIBRATE, dataset="d", rate="r")


def test_identification_may_be_used_for_both():
    assert may(ROLE_IDENTIFICATION, USE_CALIBRATE) is True
    assert may(ROLE_IDENTIFICATION, USE_EVALUATE) is True
    assert check(ROLE_IDENTIFICATION, USE_CALIBRATE,
                 dataset="d", rate="r") == []


def test_unspecified_is_allowed_but_must_be_reported():
    """不拦，但绝不静默：调用方必须拿到警告并写进 provenance。"""
    warns = check(ROLE_UNSPECIFIED, USE_CALIBRATE, dataset="d", rate="r")
    assert len(warns) == 1
    assert "未声明" in warns[0]
    assert "d/r" in warns[0]


def test_unknown_use_is_an_error_not_a_pass():
    with pytest.raises(ValueError, match="未知用途"):
        may(ROLE_IDENTIFICATION, "fit_everything")
    with pytest.raises(ValueError):
        check(ROLE_IDENTIFICATION, "train")


def test_violation_message_names_the_way_out():
    with pytest.raises(RoleViolation) as ei:
        check(ROLE_VALIDATION, USE_CALIBRATE, dataset="x", rate="1C")
    msg = str(ei.value)
    assert "x/1C" in msg
    assert ROLE_IDENTIFICATION in msg      # 告诉人怎么合法地继续


# ------------------------------------------------------------------
# 从 configs 读声明
# ------------------------------------------------------------------
def test_real_config_declares_every_dataset():
    """常驻守卫：新数据集没写 dataset_role 就失败。"""
    report = audit_config(REAL_CONFIG)
    missing = [it["dataset"] for it in report["unspecified"]]
    assert missing == [], (
        f"这些数据集没有声明 dataset_role：{missing}。"
        f"请在 configs/datasets.yaml 里补一行（见 governance/dataset_roles.py）"
    )
    assert len(report["declared"]) >= 6


def test_real_config_roles_match_how_the_data_is_actually_used():
    roles = roles_from_config(REAL_CONFIG)
    # SINTEF 石墨：OCP 与 D_s 的参数来源
    assert roles[("sintef_graphite", "*")] == ROLE_IDENTIFICATION
    # CALCE 三套：surrogate，只能 benchmark，不许叫 validation
    for ds in ("calce_cs2", "calce_20r", "calce_a123"):
        assert roles[(ds, "*")] == ROLE_BENCHMARK
    assert ("calce_cs2", "*") in roles


def test_real_config_notes_exist_for_the_subtle_ones():
    notes = role_notes_from_config(REAL_CONFIG)
    # 跨电芯这条不写下来，后人会把 GITT→p-OCV 的回放当成 validation
    assert "跨电芯" in notes[("sintef_graphite", "*")]
    # surrogate 这条不写下来，CALCE 的比较会被叫成 validation
    assert "不构成验证" in notes[("calce_cs2", "*")]


def test_assert_calibration_allowed_blocks_a_benchmark_dataset():
    with pytest.raises(RoleViolation):
        assert_calibration_allowed("calce_cs2", "0p5C", config=REAL_CONFIG)
    assert assert_calibration_allowed(
        "sintef_graphite", "gitt", config=REAL_CONFIG
    ) == []


def test_rate_level_declaration_overrides_the_dataset_level(tmp_path):
    cfg = tmp_path / "datasets.yaml"
    cfg.write_text(yaml.safe_dump({
        "demo": {
            "chemistry": "NMC_Graphite",
            "dataset_role": ROLE_IDENTIFICATION,
            "rates_meta": {
                "0p5C": {"dataset_role": ROLE_IDENTIFICATION},
                "2C": {"dataset_role": ROLE_VALIDATION,
                       "dataset_role_note": "hold-out rate"},
            },
        }
    }, allow_unicode=True), encoding="utf-8")

    roles = roles_from_config(cfg)
    assert roles[("demo", "0p5C")] == ROLE_IDENTIFICATION
    assert roles[("demo", "2C")] == ROLE_VALIDATION
    assert resolve_role("demo", "2C", roles=roles) == ROLE_VALIDATION
    # 未逐个声明的倍率回落数据集级
    assert resolve_role("demo", "1C", roles=roles) == ROLE_IDENTIFICATION
    # 未知数据集 → 未声明
    assert resolve_role("nope", "1C", roles=roles) == ROLE_UNSPECIFIED


def test_rate_level_holdout_is_enforced(tmp_path):
    """倍率级 hold-out 必须真的拦住标定——这是这套机制的核心用途。"""
    cfg = tmp_path / "datasets.yaml"
    cfg.write_text(yaml.safe_dump({
        "demo": {"chemistry": "NMC_Graphite",
                 "dataset_role": ROLE_IDENTIFICATION,
                 "rates_meta": {"2C": {"dataset_role": ROLE_VALIDATION}}},
    }, allow_unicode=True), encoding="utf-8")
    assert assert_calibration_allowed("demo", "0p5C", config=cfg) == []
    with pytest.raises(RoleViolation):
        assert_calibration_allowed("demo", "2C", config=cfg)


def test_missing_config_raises_rather_than_silently_allowing(tmp_path):
    with pytest.raises(FileNotFoundError):
        roles_from_config(tmp_path / "absent.yaml")
