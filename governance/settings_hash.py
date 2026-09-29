# ============================================================
# 数值设置指纹 settings_hash（缺口 3）
#
# 为什么三层模型比对需要它
#
#   M0 / M1 / M2 都是**零自由参数**（纯递进参数化，不拟合）。这意味着
#   三层之间的任何差异都会被原封不动归给"参数化的增益"。而三层里
#   唯一允许变的就是参数 —— **网格、时间步、求解器容差、模型选项**
#   必须逐位相同。
#
#   如果 M1 和 M2 之间还改了网格，"M2 比 M1 好"这句话就读不出来：
#   差异里混着离散化误差。而这类差异**在电压曲线上一眼看不出**，
#   所以必须由指纹拦，不能靠人自觉。这与 scale_alignment 的教训同源：
#   两次"参数惰性"的真因都不在参数上。
#
# 指纹覆盖什么（三组，缺一组都拦不住）
#
#   1. **求解器**：class / rtol / atol（来自 configs/models.yaml 的 solver 段）
#   2. **模型选项**：PyBaMM options dict（如 "contact resistance"）
#   3. **时间栅格**：t_eval 的点数与起止 —— 平台**不传** npts/mesh，
#      用的是 PyBaMM 默认网格，所以网格无法从参数读出；能读的是
#      "这次喂进去的时间点"。这一点必须**明说**（见 KNOWN_LIMITS）。
#
# 三个刻意的设计决定
#
#   · **哈希只答"同不同"，不答"该不该同"。** 所以返回里同时给
#     逐字段的分组明细，冲突时能直接指出哪一项变了 —— 只给一个
#     十六进制串是没有可操作性的。
#   · **不引入新输入。** 指纹的所有输入都能从**已经写进现有产物的字段**
#     取到（run_metadata.json 的 solver 块、model_options 键、
#     time_aligned CSV 的时间列）。所以它可以对**新跑的 run** 事后复算，
#     不需要重跑。
#     ⚠️ **但对更早的 run 不行**：`solver` / `model_options` 是 2026-09-28
#     才写进产物的。实测 2026-09-28 之前的 21 份 run_metadata.json
#     **没有一份**带 `solver` 块。若对它们复算时套用默认值，会得到描述
#     "默认值"而非"那次 run"的指纹 → 三层比对给出**虚假的相同**
#     （13 份不同数据集/电芯的 run 共用同一指纹 `f4ddab...`，即是此故）。
#     ⇒ :func:`payload_from_run_metadata` **默认抛错**（见
#     :class:`MissingSettingsError`），缺字段时不会静默补默认值。
#   · **浮点格式化到固定位数**，否则 1.0e-6 与 1e-06 会算出不同指纹
#     （同一个设置被报成不同 —— 这是最坏的一类假阳性）。
#
# 已知边界（必须与结论一起引用）
#
#   · PyBaMM 默认网格（npts / 空间离散）**没有**进指纹，因为平台不显式
#     设置它。若将来有人给它显式传值，必须同时更新本模块 ——
#     测试 `test_settings_hash.py::test_known_limits_are_declared` 钉住这条。
#   · 指纹不覆盖 PyBaMM 版本。版本已在 run_metadata.json 的
#     `pybamm_version` 里，两者要一起看（版本变了，同一指纹也可能行为不同）。
# ============================================================

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Sequence

#: 指纹版本。改了覆盖范围/规范化规则就 +1 —— 否则旧指纹与新指纹
#: 看起来可比，实际不可比（这是最坏的一种静默失效）。
SCHEMA = 1

#: 浮点规范化的有效位数。**声明出来**：它决定"多大的差异算差异"。
FLOAT_SIG_DIGITS = 12

KNOWN_LIMITS = (
    "PyBaMM 默认空间网格（npts / 离散方式）未包含：平台不显式设置它。",
    "PyBaMM 版本未包含：见 run_metadata.json 的 pybamm_version，须一起引用。",
    "数据集/电芯身份未包含：指纹只描述**怎么算**，不描述**算哪颗电芯**。",
)


def _canon_float(value: float) -> str:
    """把浮点规范化成稳定的字符串。

    两个坑：① 1.0e-6 与 1e-06 是同一个数但 str() 不同；
    ② 0.1 + 0.2 类误差在 repr 里会露出来。
    用 ``%.{FLOAT_SIG_DIGITS}g`` 同时解决：固定有效位数、固定指数写法。
    """
    f = float(value)
    if f != f:  # NaN
        return "nan"
    if f in (float("inf"), float("-inf")):
        return "inf" if f > 0 else "-inf"
    return f"%.{FLOAT_SIG_DIGITS}g" % f


#: 规范化后给每个标量加的类型前缀。**必须有** —— 否则数值 1e-6 与字符串
#: "1e-6" 规范化成同一个 token，指纹就对"输入类型变了"完全失明。
#: PyBaMM 里这不是假想：`contact resistance` 必须是字符串 "true"，
#: 传布尔 True 会被 OptionError 拒绝，两者绝不能算同一支。
#:
#: 三条相关的纪律（都不在注释里，在测试里）：
#:   · ``solver_fingerprint`` / ``model_options_fingerprint`` 返回的是**原值**，
#:     不打标签 —— 标签只在 :func:`_canon` 这一处打，否则会打在已字符串化的
#:     值上，类型信息就丢了。
#:   · int 与 float 分开：``1`` 与 ``1.0`` 在 Python 里相等，但作为容差
#:     传进去语义不同。
#:   · bool 与 str 分开：见上。
def _canon(value: Any) -> Any:
    """递归规范化：数字取有效位，标量带类型标签，键稳定排序。

    类型标签是这一步最容易被省掉、也最不能省的东西：JSON 的
    ``1e-6`` 与 ``"1e-6"`` 看着一样，在 PyBaMM 里行为不同。
    """
    if isinstance(value, bool):
        return "b:true" if value else "b:false"
    if isinstance(value, int):
        # int 与 float 分开：1 与 1.0 在 Python 里相等，但作为设置
        # 传进去的语义不同（一个是整数计数，一个是容差）。合并它们
        # 会让"把 rtol 从 1e-6 改成 1"这类改动看不出来。
        return f"i:{value}"
    if isinstance(value, float):
        return f"f:{_canon_float(value)}"
    if isinstance(value, str):
        return f"s:{value}"
    if value is None:
        return "z:null"
    if isinstance(value, Mapping):
        return {
            str(k): _canon(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    # 其它类型：用类型名 + repr，避免静默丢掉一个未预期的输入
    return f"<{type(value).__name__}:{value!r}>"


# ------------------------------------------------------------------
# 三组输入的抽取（都从既有产物读，不新增字段）
# ------------------------------------------------------------------
def solver_fingerprint(solver_cfg: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """求解器设置。输入 = configs/models.yaml 的 solver 段（或 run_metadata 的 solver 块）。

    值**原样保留类型**交给 :func:`_canon` —— 这里若先自己 ``_canon_float``
    一把，类型标签就会打在已经变成字符串的值上，于是 ``1e-6`` 与 ``"1e-6"``
    又撞回同一个 token（这正是本模块最容易踩的坑，测试
    ``test_string_vs_float_are_different`` 钉住它）。
    """
    cfg = dict(solver_cfg or {})
    return {
        "class": cfg.get("class", "IDAKLUSolver"),
        "rtol": cfg.get("rtol", 1.0e-6),
        "atol": cfg.get("atol", 1.0e-6),
    }


def model_options_fingerprint(options: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """PyBaMM 模型选项。None 与空 dict 归一化到同一支（都表示"用默认选项"）。

    注意：PyBaMM 对 ``contact resistance`` 的值要求**字符串** "true"，
    布尔 True 会被 OptionError 拒绝 —— 所以这里**不**做任何类型转换，
    让两种写法算出不同指纹（它们确实是不同的输入）。
    """
    return {str(k): v for k, v in (options or {}).items()}


def grid_fingerprint(
    t_eval: Optional[Sequence[float]],
    *,
    include_endpoints_only: bool = False,
) -> Dict[str, Any]:
    """时间栅格指纹。

    ``include_endpoints_only=False``（默认）时**不哈希全部时间点**：
    时间点由数据决定，两个不同的协议本来就有不同时间列 —— 那样算出来的
    差异是"协议不同"，不是"数值设置不同"，会把指纹变得毫无用处。
    默认只取 **点数 + 起止 + 单调性**，这三样足以发现"网格被换了"。
    """
    if t_eval is None:
        return {"n_points": None, "t_start_s": None, "t_end_s": None}
    # numpy 只在这一支里需要 —— 而这一支只在调用方真的给了时间列时才走到。
    # 放成局部 import 的理由：本模块要能对**已有的 run_metadata.json**
    # 复算指纹（见 payload_from_run_metadata），那在纯分析环境里也要能跑，
    # 不该因为"没装 numpy"就整个 import 失败。
    import numpy as np

    t = np.asarray(list(t_eval), dtype=float)
    if t.size == 0:
        return {"n_points": 0, "t_start_s": None, "t_end_s": None}
    if include_endpoints_only:
        return {
            "n_points": int(t.size),
            "t_start_s": _canon_float(float(t[0])),
            "t_end_s": _canon_float(float(t[-1])),
        }
    d = np.diff(t)
    return {
        "n_points": int(t.size),
        "t_start_s": _canon_float(float(t[0])),
        "t_end_s": _canon_float(float(t[-1])),
        "dt_min_s": _canon_float(float(np.min(d))) if d.size else None,
        "dt_max_s": _canon_float(float(np.max(d))) if d.size else None,
        "monotonic": bool(np.all(d > 0)),
    }


def settings_payload(
    *,
    solver_cfg: Optional[Mapping[str, Any]] = None,
    model_options: Optional[Mapping[str, Any]] = None,
    t_eval: Optional[Sequence[float]] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """三组输入合成一个可哈希的载荷（也给人类看）。"""
    return {
        "schema": SCHEMA,
        "float_sig_digits": FLOAT_SIG_DIGITS,
        "model": None if model_name is None else str(model_name),
        "solver": solver_fingerprint(solver_cfg),
        "model_options": model_options_fingerprint(model_options),
        "grid": grid_fingerprint(t_eval),
    }


def settings_hash(
    *,
    solver_cfg: Optional[Mapping[str, Any]] = None,
    model_options: Optional[Mapping[str, Any]] = None,
    t_eval: Optional[Sequence[float]] = None,
    model_name: Optional[str] = None,
) -> str:
    """数值设置指纹（sha256 前 16 位十六进制）。"""
    payload = settings_payload(
        solver_cfg=solver_cfg,
        model_options=model_options,
        t_eval=t_eval,
        model_name=model_name,
    )
    blob = json.dumps(_canon(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------
# 比对：三层模型能不能下结论，就看这个
# ------------------------------------------------------------------
def diff_settings(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
) -> Dict[str, Any]:
    """逐字段比较两个 settings_payload。返回差异明细。"""
    diffs: Dict[str, Any] = {}

    def walk(pa: str, x: Any, y: Any) -> None:
        if isinstance(x, Mapping) and isinstance(y, Mapping):
            for k in sorted(set(x) | set(y)):
                # 路径拼接不带前导点：``solver.rtol`` 而不是 ``.solver.rtol``。
                # 前导点看着无害，但它会让"按前缀筛选差异"的调用方漏掉根层键。
                child = f"{pa}.{k}" if pa else str(k)
                if k not in x:
                    diffs[child] = {"a": "<absent>", "b": _canon(y[k])}
                elif k not in y:
                    diffs[child] = {"a": _canon(x[k]), "b": "<absent>"}
                else:
                    walk(child, x[k], y[k])
            return
        if _canon(x) != _canon(y):
            diffs[pa] = {"a": _canon(x), "b": _canon(y)}

    walk("", dict(a), dict(b))
    return diffs


def assert_same_settings(
    runs: Mapping[str, Any],
    *,
    require_pairwise_identical: bool = True,
) -> Dict[str, Any]:
    """断言一组 run 的数值设置相同（三层比对的前置门）。

    参数
    ----
    runs
        ``{层级名: settings_payload}``，例 ``{"M0": p0, "M1": p1, "M2": p2}``。
    require_pairwise_identical
        ``True``（默认）时任意两个不同即抛 —— 这是 M0/M1/M2 应当的用法
        （零自由参数、只该差参数）。

    返回
    ----
    ``{"hashes": {...}, "identical": bool, "reference": str, "differences": {...}}``

    抛
    --
    ``ValueError``（当 ``require_pairwise_identical`` 且确有差异）。
    **错误信息里逐字段列出差异** —— 只报"不一致"是无法修的。
    """
    if not runs:
        raise ValueError("runs 为空：至少要有两层才能比对")

    hashes = {name: _hash_payload(p) for name, p in runs.items()}
    names = list(runs)
    reference = names[0]
    all_diffs: Dict[str, Dict[str, Any]] = {}
    for other in names[1:]:
        d = diff_settings(runs[reference], runs[other])
        if d:
            all_diffs[f"{reference} vs {other}"] = d

    identical = not all_diffs
    if require_pairwise_identical and not identical:
        lines = []
        for pair, d in all_diffs.items():
            lines.append(f"  [{pair}]")
            for key, v in d.items():
                lines.append(f"    {key}: a={v['a']!r} b={v['b']!r}")
        raise ValueError(
            "数值设置不一致 —— 三层模型比对**不能下结论**：\n"
            "零自由参数的三层之间只允许差**参数**。网格/求解器/模型选项的"
            "差异会原封不动归给'参数化增益'，而这类差异在电压曲线上看不出来。\n"
            + "\n".join(lines)
        )

    return {
        "hashes": hashes,
        "identical": identical,
        "reference": reference,
        "differences": all_diffs,
    }


def _hash_payload(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(_canon(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


#: ``run_metadata.json`` 里指纹所依赖的字段。
#: 缺任何一个 ⇒ 该 run 的指纹**不可复算**（不是"用了默认值"）。
REQUIRED_METADATA_FIELDS = ("solver", "model_options", "model")


def missing_fingerprint_fields(meta: Mapping[str, Any]) -> list:
    """列出这份 ``run_metadata.json`` 里**缺失**、导致指纹不可复算的字段。

    为什么要这个函数：``run_metadata.json`` 的字段是**逐步加上的**——
    2026-09-28 之前产生的 21 份产物**没有一份**带 ``solver`` 块。
    若此时静默套用模块默认值（IDAKLUSolver / rtol=atol=1e-6），
    就会给出一串"看起来合法"的指纹，而它其实描述的是**默认值**、
    不是那次 run 真正的设置 —— 于是三层比对会得到**虚假的"相同"**。
    这正是本项目最不能接受的一类失败（静默失效）。

    >>> missing_fingerprint_fields({"model": "SPM"})
    ['solver', 'model_options']
    """
    missing = []
    for key in REQUIRED_METADATA_FIELDS:
        value = meta.get(key)
        if value is None:
            missing.append(key)
        elif isinstance(value, Mapping) and not value:
            # 空 dict 与缺失等价：都没有告诉我们任何设置信息。
            missing.append(key)
    return missing


def payload_from_run_metadata(
    meta: Mapping[str, Any],
    *,
    t_eval: Optional[Sequence[float]] = None,
    on_missing: str = "raise",
) -> Dict[str, Any]:
    """从已有的 ``run_metadata.json`` 复算指纹（**不需要重跑**）。

    与 :func:`settings_payload` 的关键区别：**缺失字段不套默认值**。
    缺字段时按 ``on_missing`` 处理：

    * ``"raise"``（默认）—— 抛 :class:`MissingSettingsError`。这是默认行为，
      因为"指纹看起来有值其实来自默认"比"没有指纹"危险得多。
    * ``"mark"`` —— 返回 ``{"__unfingerprintable__": {...}}``，
      调用方可以显式地把它排除在比对之外，而不是误当成一个指纹。
    * ``"default"`` —— 旧行为（套默认值）。**已弃用**，只为兼容旧调用方；
      返回的 payload 里会带 ``"used_defaults": [...]`` 让误用可见。

    ``t_eval`` 不在 run_metadata 里；调用方若手上有 ``<rate>_time_aligned.csv``，
    可读出时间列传进来，否则 grid 会记成 ``n_points=None``（这是**已知**
    而非**缺失**——所以它不触发 ``on_missing``）。
    """
    if on_missing not in ("raise", "mark", "default"):
        raise ValueError(
            f"on_missing 只能是 'raise' / 'mark' / 'default'，收到 {on_missing!r}"
        )

    missing = missing_fingerprint_fields(meta)

    if missing and on_missing == "raise":
        raise MissingSettingsError(
            "这份 run_metadata.json 缺少指纹所需的字段，**不能复算指纹**：\n"
            f"  缺失：{missing}\n"
            f"  文件里有的键：{sorted(meta.keys())}\n"
            "原因：solver / model_options 是 2026-09-28 才写进产物的；\n"
            "更早的 run 没有记录它们，所以它们当时的设置**不可知**。\n"
            "⇒ 若在此处套用默认值，会得到一个描述『默认值』而非『那次 run』\n"
            "   的指纹，使三层比对给出**虚假的相同**。\n"
            "处理：只对**新跑**的 run 用指纹；或显式传 on_missing='mark' "
            "把它排除在比对之外。"
        )

    if missing and on_missing == "mark":
        return {
            "__unfingerprintable__": {
                "reason": "run_metadata.json 缺少指纹所需字段",
                "missing": missing,
                "schema": SCHEMA,
            }
        }

    payload = settings_payload(
        solver_cfg=meta.get("solver"),
        model_options=meta.get("model_options"),
        t_eval=t_eval,
        model_name=meta.get("model"),
    )
    if missing:
        # on_missing == "default"：保留旧行为，但**让误用可见**。
        payload = dict(payload)
        payload["used_defaults"] = list(missing)
    return payload


class MissingSettingsError(RuntimeError):
    """``run_metadata.json`` 缺少指纹所需字段，指纹不可复算。"""


__all__ = [
    "FLOAT_SIG_DIGITS",
    "KNOWN_LIMITS",
    "REQUIRED_METADATA_FIELDS",
    "SCHEMA",
    "MissingSettingsError",
    "assert_same_settings",
    "diff_settings",
    "grid_fingerprint",
    "missing_fingerprint_fields",
    "model_options_fingerprint",
    "payload_from_run_metadata",
    "settings_hash",
    "settings_payload",
    "solver_fingerprint",
]
