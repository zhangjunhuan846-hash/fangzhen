# ============================================================
# 用途治理层（dataset_role）
#
# 一个数据集/一条倍率可以被用来做什么，是**声明**出来的，不是推断出来的。
# 本包只放"规则 + 门"，不含任何科学计算。
#
# 为什么需要它
#   平台的红线是 zero-fit：参数只能来自**识别用**的实验数据。
#   一旦拿来做验证的倍率/长循环数据回头去调参数，"验证"就变成了
#   对训练集的拟合，结论立刻失去意义——这是审稿人最先查的一条，
#   而它靠人自觉是守不住的，必须由代码拦。
#
# 三种用途
#   identification  可用于标定/提取（calibrate）与评估（evaluate）
#   validation      只可用于评估；进入标定即报错
#   benchmark       只可用于评估；进入标定即报错。
#                   **与 validation 的区别**：参数集不是为该数据集标定的
#                   （surrogate 等级），所以这个比较**不构成验证**。
#                   留下这个独立的角色，就是为了不把 CALCE 这类
#                   surrogate 比较在措辞上偷换成 "validation"。
#   prediction      只可用于评估；进入标定即报错
#   未声明         按 identification 处理，但每次都会返回警告，
#                  调用方必须把它写进 provenance（不静默）
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

ROLE_IDENTIFICATION = "identification"
ROLE_VALIDATION = "validation"
ROLE_BENCHMARK = "benchmark"
ROLE_PREDICTION = "prediction"
ROLE_UNSPECIFIED = "unspecified"

# 允许**声明**的取值（unspecified 是"没声明"，不是可声明的选项）
ALLOWED_DECLARED_ROLES = (
    ROLE_IDENTIFICATION,
    ROLE_VALIDATION,
    ROLE_BENCHMARK,
    ROLE_PREDICTION,
)

USE_CALIBRATE = "calibrate"
USE_EVALUATE = "evaluate"
ALLOWED_USES = (USE_CALIBRATE, USE_EVALUATE)

_RULES: Dict[str, frozenset] = {
    ROLE_IDENTIFICATION: frozenset({USE_CALIBRATE, USE_EVALUATE}),
    ROLE_VALIDATION: frozenset({USE_EVALUATE}),
    ROLE_BENCHMARK: frozenset({USE_EVALUATE}),
    ROLE_PREDICTION: frozenset({USE_EVALUATE}),
    # 未声明：不拦（否则所有既有数据集都要先补声明），但要求调用方记录
    ROLE_UNSPECIFIED: frozenset({USE_CALIBRATE, USE_EVALUATE}),
}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "datasets.yaml"


class RoleViolation(RuntimeError):
    """把 validation/prediction 数据用于标定（或使用未知用途）时抛出。"""


def normalise(role) -> str:
    """把声明值规整成四选一；非法值直接报错（禁止猜）。"""
    if role is None:
        return ROLE_UNSPECIFIED
    r = str(role).strip().lower()
    if r == "" or r == ROLE_UNSPECIFIED:
        return ROLE_UNSPECIFIED
    if r not in ALLOWED_DECLARED_ROLES:
        raise ValueError(
            f"dataset_role 非法：{role!r}；"
            f"允许 {list(ALLOWED_DECLARED_ROLES)}（留空表示未声明）"
        )
    return r


def may(role, use: str) -> bool:
    """该用途是否被该角色允许。未知 use 报错，而不是默默放行。"""
    r = normalise(role)
    u = str(use).strip().lower()
    if u not in ALLOWED_USES:
        raise ValueError(f"未知用途 {use!r}；允许 {list(ALLOWED_USES)}")
    return u in _RULES[r]


def check(
    role,
    use: str,
    *,
    dataset: Optional[str] = None,
    rate: Optional[str] = None,
    what: Optional[str] = None,
) -> list:
    """
    门。允许则返回**警告列表**（调用方必须写进 provenance），
    不允许则抛 :class:`RoleViolation`。
    """
    r = normalise(role)
    if not may(r, use):
        where = "/".join(x for x in (dataset, rate) if x) or "?"
        raise RoleViolation(
            f"dataset_role='{r}' 的数据集 {where} 不允许用于 '{use}'"
            f"{('（' + what + '）') if what else ''}。"
            f"允许的用途：{sorted(_RULES[r])}。"
            f"把验证/预测数据用于标定会让'验证'变成对训练集的拟合；"
            f"如果确实要标定，请先把它的 dataset_role 改声明为 "
            f"'{ROLE_IDENTIFICATION}' 并说明理由。"
        )
    warnings = []
    if r == ROLE_UNSPECIFIED:
        where = "/".join(x for x in (dataset, rate) if x) or "?"
        warnings.append(
            f"dataset_role 未声明（{where}）：已按 '{ROLE_IDENTIFICATION}' "
            f"处理用于 '{use}'。请在 configs/datasets.yaml 里显式声明。"
        )
    return warnings


# ------------------------------------------------------------------
# 从 configs/datasets.yaml 读取声明
# ------------------------------------------------------------------
def _entry_role(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ROLE_UNSPECIFIED
    return normalise(entry.get("dataset_role"))


def roles_from_config(path: Optional[Path | str] = None) -> Dict[tuple, str]:
    """
    {(dataset, rate) 与 (dataset, '*')} -> role。

    倍率级声明覆盖数据集级声明；都没写就是 'unspecified'。
    """
    import yaml

    p = Path(path) if path is not None else DEFAULT_CONFIG
    if not p.is_file():
        raise FileNotFoundError(f"数据集配置不存在：{p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    out: Dict[tuple, str] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        ds_role = _entry_role(entry)
        out[(str(name), "*")] = ds_role
        meta = entry.get("rates_meta") or {}
        if isinstance(meta, dict):
            for rate, r_entry in meta.items():
                if isinstance(r_entry, dict) and "dataset_role" in r_entry:
                    out[(str(name), str(rate))] = normalise(
                        r_entry["dataset_role"]
                    )
    return out


def resolve_role(
    dataset: str,
    rate: Optional[str] = None,
    *,
    roles: Optional[Dict[tuple, str]] = None,
    config: Optional[Path | str] = None,
) -> str:
    """倍率级 > 数据集级 > 未声明。"""
    table = roles if roles is not None else roles_from_config(config)
    key = (str(dataset), str(rate) if rate is not None else "*")
    if key in table:
        return table[key]
    return table.get((str(dataset), "*"), ROLE_UNSPECIFIED)


def assert_calibration_allowed(
    dataset: str,
    rate: Optional[str] = None,
    *,
    what: Optional[str] = None,
    roles: Optional[Dict[tuple, str]] = None,
    config: Optional[Path | str] = None,
) -> list:
    """
    参数提取/标定路径的入口守卫。

    >>> assert_calibration_allowed("sintef_graphite", "gitt")
    [...]
    """
    role = resolve_role(dataset, rate, roles=roles, config=config)
    return check(role, USE_CALIBRATE, dataset=dataset, rate=rate, what=what)


def role_notes_from_config(path: Optional[Path | str] = None) -> Dict[tuple, str]:
    """
    {(dataset, rate) 与 (dataset, '*')} -> dataset_role_note（可选）。

    角色只有一个词，装不下"这条数据为什么是识别集"这类说明；
    说明写进同一份 config 才不会和角色脱节。
    """
    import yaml

    p = Path(path) if path is not None else DEFAULT_CONFIG
    if not p.is_file():
        raise FileNotFoundError(f"数据集配置不存在：{p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    out: Dict[tuple, str] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("dataset_role_note"):
            out[(str(name), "*")] = str(entry["dataset_role_note"]).strip()
        meta = entry.get("rates_meta") or {}
        if isinstance(meta, dict):
            for rate, r_entry in meta.items():
                if isinstance(r_entry, dict) and r_entry.get("dataset_role_note"):
                    out[(str(name), str(rate))] = str(
                        r_entry["dataset_role_note"]
                    ).strip()
    return out


def audit_config(path: Optional[Path | str] = None) -> Dict[str, list]:
    """
    只读审计：列出每个数据集的声明情况。
    返回 {"declared": [...], "unspecified": [...]}。
    """
    table = roles_from_config(path)
    notes = role_notes_from_config(path)
    declared, unspecified = [], []
    for (ds, rate), role in sorted(table.items()):
        item = {"dataset": ds, "rate": rate, "role": role,
                "note": notes.get((ds, rate), "")}
        (unspecified if role == ROLE_UNSPECIFIED else declared).append(item)
    return {"declared": declared, "unspecified": unspecified}


def iter_roles(roles: Dict[tuple, str]) -> Iterable[tuple]:
    return sorted(roles.items())
