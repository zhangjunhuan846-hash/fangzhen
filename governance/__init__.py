# ============================================================
# governance —— 数据用途治理层
#
# 只放"规则与门"：一个数据集/一条倍率可以被用来做什么
# （identification / validation / prediction），以及"把验证数据
# 用于标定"必须报错。
#
# 不含科学计算，不改动 battery_sim 冻结内核。
# ============================================================

from governance.dataset_roles import (  # noqa: F401
    ALLOWED_DECLARED_ROLES,
    ALLOWED_USES,
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

__all__ = [
    "ALLOWED_DECLARED_ROLES",
    "ALLOWED_USES",
    "ROLE_BENCHMARK",
    "ROLE_IDENTIFICATION",
    "ROLE_PREDICTION",
    "ROLE_UNSPECIFIED",
    "ROLE_VALIDATION",
    "USE_CALIBRATE",
    "USE_EVALUATE",
    "RoleViolation",
    "assert_calibration_allowed",
    "audit_config",
    "check",
    "may",
    "normalise",
    "resolve_role",
    "role_notes_from_config",
    "roles_from_config",
]
