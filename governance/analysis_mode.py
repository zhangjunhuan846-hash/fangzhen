# ============================================================
# 分析模式（analysis mode）与判定词汇
#
# 为什么需要这一层
#   G5/G6 的 benchmark 分析里大量使用了 **synthetic truth**：同一次扫描在真值
#   点的输出当作"观测"，于是 J(a)=0 精确成立、恢复误差逐位为 0。这对**接线
#   检查**是有意义的（能证明 override 真的到达了模型），对**科学结论**毫无意义
#   —— 因为观测是同一个模型生成的（inverse crime）。
#
#   接上真实回收石墨数据以后，truth 根本不存在。此时若沿用 benchmark 的报告
#   模板，就会自然写出"恢复误差 0.000"这种把模拟当实验的句子。这件事靠人自觉
#   是守不住的，所以由代码拦：
#
#     · material 模式下，truth_recovery / synthetic_truth 一类字段**直接报错**
#     · 判定词汇限定为四个词（+ 显式的 not_measured），各有严格定义
#     · 只有 identifiable 允许写"数值"；bounded 只允许写"界"；
#       unconstrained / not identifiable 不许写数值
#
# 判定规则（判据是**声明的阈值**，不是隐藏常数）
#   给定 1 mV 之类的水平 level、带宽上限 limit_dex、扫描半宽 scan_range_dex：
#     n_points == 0                       -> not_measured
#     两侧都被截断（带跑到扫描边界）      -> unconstrained
#     恰好一侧被截断                      -> bounded（另一侧才是真界）
#     未截断 且 width <= limit_dex        -> identifiable
#     未截断 且 width >  limit_dex        -> not identifiable
#
#   注意 bounded 的语义落在**被约束的那一侧**：G6.1c 实测里缺的那一半统一在
#   D_s 偏大侧，也就是只给出 D_s 的下界（τ_d 的上界）。
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Optional

MODE_BENCHMARK = "benchmark"
MODE_MATERIAL = "material"
ALLOWED_MODES = (MODE_BENCHMARK, MODE_MATERIAL)

MODE_NOTES = {
    MODE_BENCHMARK: (
        "合成/受控分析：允许 synthetic truth 与 truth recovery，"
        "结论**不构成**对真实材料或实验可辨识性的陈述"
    ),
    MODE_MATERIAL: (
        "真实材料分析：不允许 synthetic truth / truth recovery；"
        "只输出判定词汇与实测界"
    ),
}

VERDICT_IDENTIFIABLE = "identifiable"
VERDICT_NOT_IDENTIFIABLE = "not identifiable"
VERDICT_BOUNDED = "bounded"
VERDICT_UNCONSTRAINED = "unconstrained"
VERDICT_NOT_MEASURED = "not_measured"

#: 允许出现在报告里的判定词。多一个都算越界。
ALLOWED_VERDICTS = (
    VERDICT_IDENTIFIABLE,
    VERDICT_NOT_IDENTIFIABLE,
    VERDICT_BOUNDED,
    VERDICT_UNCONSTRAINED,
    VERDICT_NOT_MEASURED,
)

VERDICT_GLOSS = {
    VERDICT_IDENTIFIABLE: "在本水平上被约束到声明带宽以内，可以引用一个数值",
    VERDICT_BOUNDED: "只有一个方向被约束：只能报界，不能报点估计",
    VERDICT_UNCONSTRAINED: "全区间内观测不动：本协议对它没有信息，不许报数",
    VERDICT_NOT_IDENTIFIABLE: "有影响但带宽超过判据，不许报数",
    VERDICT_NOT_MEASURED: "这份数据里没有对应激励，不许给判定",
}

#: material 模式下禁止出现的数据/报告字段（子串匹配，大小写无关）。
#: 最后一条 "truth" 是兜底：真实材料分析里**任何**带 truth 的键都不该出现
#: （`cost_at_truth_mV2` 这种名字在 benchmark 表里很常见，正好要被拦下）。
BENCHMARK_ONLY_FEATURES = (
    "synthetic_truth",
    "truth_recovery",
    "recovery_error",
    "injected_truth",
    "a_truth",
    "truth",
)


class ModeViolation(RuntimeError):
    """在 material 模式下试图做只有 benchmark 才成立的事。"""


def normalise_mode(mode) -> str:
    """规整模式声明；未知值报错（禁止猜）。"""
    raw = str(mode or "").strip().lower()
    if raw not in ALLOWED_MODES:
        raise ValueError(
            f"未知分析模式 {mode!r}；允许 {list(ALLOWED_MODES)}"
        )
    return raw


def assert_benchmark_only(mode, feature: str, *, context: str = "") -> None:
    """在 material 模式下拒绝 benchmark 专属活动。

    刻意抛 :class:`ModeViolation`（不是 ``ValueError``）：模式用错**可修**
    （换成 benchmark 模式、或改跑真实数据的判据），参数名写错不可修。
    """
    if normalise_mode(mode) == MODE_MATERIAL:
        where = f"（{context}）" if context else ""
        raise ModeViolation(
            f"分析模式 'material'{where} 下不允许 '{feature}'。"
            f"{MODE_NOTES[MODE_MATERIAL]}。"
            f"如果这一步确实要用合成真值做接线检查，请显式声明 "
            f"analysis_mode='{MODE_BENCHMARK}'，并在报告里写明该结论"
            f"**不构成**实验可辨识性陈述。"
        )


def check_payload(mode, payload: Any, *, where: str = "payload") -> list:
    """扫一遍报告载荷的键名，material 模式下命中禁用字段即报错。

    递归扫 dict 的键（不扫值：值里出现 "truth" 可能只是引用了 benchmark 的
    结论），返回命中的键路径列表供调用方记录。
    """
    hits: list = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                low = str(key).lower()
                for feat in BENCHMARK_ONLY_FEATURES:
                    if feat in low:
                        hits.append(child)
                        break
                walk(value, child)
        elif isinstance(node, (list, tuple)):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(payload, "")
    if hits and normalise_mode(mode) == MODE_MATERIAL:
        raise ModeViolation(
            f"{where} 里出现了 benchmark 专属字段 {hits}，"
            f"但分析模式是 'material'。真实材料分析里这些量没有定义。"
        )
    return hits


def classify_band(
    band: Optional[Dict[str, Any]],
    *,
    level_mV: float,
    limit_dex: float,
    scan_range_dex: float,
    tolerance_dex: float = 1e-9,
) -> Dict[str, Any]:
    """把一条 1 mV（或指定水平）带宽测量翻成判定词。

    返回值里同时带上水平、上限、扫描范围与**实测分辨率** —— 带宽离开这三样
    是没法读的（G6.1b-1 的红线：报带宽必须带上分辨率）。
    """
    common = {
        "level_mV": float(level_mV),
        "limit_dex": float(limit_dex),
        "scan_range_dex": float(scan_range_dex),
    }
    if not band:
        return {
            "verdict": VERDICT_NOT_MEASURED,
            "reportable_value_kind": "none",
            "reason": "没有带宽测量（这个参数在本数据集里没有激励）",
            **common,
        }

    width = band.get("width_dex")
    left = band.get("left_dex")
    right = band.get("right_dex")
    trunc_l = bool(band.get("truncated_left",
                            band.get("truncated", False)))
    trunc_r = bool(band.get("truncated_right",
                            band.get("truncated", False)))
    # ``n_points`` 缺省与 0 不是一回事：0 表示"最小点根本不可达"（没测到），
    # 缺省只表示这份表是汇总出来的、没带点数。所以只在明确给了 0 时才判未测。
    n_points = band.get("n_points", None)
    resolution = band.get("resolution_dex")

    if (n_points is not None and int(n_points) <= 0) \
            or width is None or width != width:  # None or NaN
        return {
            "verdict": VERDICT_NOT_MEASURED,
            "reportable_value_kind": "none",
            "reason": "带宽未定义（无有限代价点 / 最小点本身不可达）",
            **common,
        }

    width = float(width)
    common["width_dex"] = width
    common["resolution_dex"] = resolution
    res_note = (
        f"分辨率 {resolution:.4f} dex"
        if isinstance(resolution, float) and resolution == resolution
        else "分辨率未知"
    )

    if trunc_l and trunc_r:
        return {
            "verdict": VERDICT_UNCONSTRAINED,
            "reportable_value_kind": "none",
            "reason": (
                f"两侧都被截断：在 ±{scan_range_dex / 2:.3f} dex 的扫描范围内"
                f"观测移动不足 {level_mV:g} mV，带宽只是扫描范围"
                f"（{width:.3f} dex，{res_note}）。本协议对它没有信息。"
            ),
            **common,
        }

    if trunc_l or trunc_r:
        # ``bounded_side`` 命名的是**被约束、因而可报**的那一侧：
        #   左侧截断 → a 没有下界，可报的是**上界** → "upper"
        #   右侧截断 → a 没有上界，可报的是**下界** → "lower"
        # G6.1c 实测里缺的那一半在 $D_s$ 偏大侧 ⇒ 典型情形是 "lower"，
        # 也就是"只给 $D_s$ 的下界（$\tau_d$ 的上界）"。
        bounded_side = "upper" if trunc_l else "lower"
        return {
            "verdict": VERDICT_BOUNDED,
            "reportable_value_kind": f"one_sided_{bounded_side}_bound",
            "bounded_side": bounded_side,
            "reason": (
                f"单侧截断（{'左侧' if trunc_l else '右侧'}撞到扫描边界）："
                f"可报的是{'上界' if bounded_side == 'upper' else '下界'}"
                f"（另一侧在 {level_mV:g} mV 水平上仍无界），"
                f"带宽 {width:.3f} dex（{res_note}），不要报点估计。"
            ),
            **common,
        }

    if width <= limit_dex + tolerance_dex:
        return {
            "verdict": VERDICT_IDENTIFIABLE,
            "reportable_value_kind": "value",
            "reason": (
                f"未截断且 {width:.3f} dex <= 判据 {limit_dex:.3f} dex"
                f"（水平 {level_mV:g} mV），可以引用数值（{res_note}）"
            ),
            **common,
        }

    return {
        "verdict": VERDICT_NOT_IDENTIFIABLE,
        "reportable_value_kind": "none",
        "reason": (
            f"未截断但 {width:.3f} dex > 判据 {limit_dex:.3f} dex："
            f"该参数对观测确有影响，但在 {level_mV:g} mV 水平上约束不够"
            f"（{res_note}）"
        ),
        **common,
    }


def render_verdict(verdict: str, *, parameter: str = "") -> str:
    """一行人类可读的判定（不写数值）。"""
    name = f"{parameter}: " if parameter else ""
    gloss = VERDICT_GLOSS.get(verdict, "(未知判定词)")
    return f"{name}{verdict} — {gloss}"


def party_role_caution(mode, dataset_role: Optional[str]) -> Optional[str]:
    """mode/role 组合的风险提示（只提示，不拦）。

    material 模式 + benchmark 角色意味着：这份数据可以做真实材料的
    **一致性检查**，但参数集不是为它标定的 ⇒ 比较结果不构成验证。
    """
    if normalise_mode(mode) != MODE_MATERIAL:
        return None
    role = str(dataset_role or "").strip().lower()
    if role == "benchmark":
        return (
            f"分析模式 'material' 但 dataset_role='benchmark'："
            f"可以做真实材料的一致性检查，"
            f"**不构成对该材料参数集的验证**（参数集非为它标定）"
        )
    if role in ("validation", "prediction"):
        return (
            f"dataset_role='{role}' 的数据只可用于评估；"
            f"任何回写参数的步骤都会被 governance.dataset_roles 拦下"
        )
    return None


__all__ = [
    "ALLOWED_MODES",
    "ALLOWED_VERDICTS",
    "BENCHMARK_ONLY_FEATURES",
    "MODE_BENCHMARK",
    "MODE_MATERIAL",
    "MODE_NOTES",
    "ModeViolation",
    "VERDICT_BOUNDED",
    "VERDICT_GLOSS",
    "VERDICT_IDENTIFIABLE",
    "VERDICT_NOT_IDENTIFIABLE",
    "VERDICT_NOT_MEASURED",
    "VERDICT_UNCONSTRAINED",
    "assert_benchmark_only",
    "check_payload",
    "classify_band",
    "normalise_mode",
    "party_role_caution",
    "render_verdict",
]
