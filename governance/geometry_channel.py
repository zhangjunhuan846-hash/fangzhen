# ============================================================
# 几何 → 模型 参数通路（geometry channel）
#
# 为什么必须有这个模块（缺口 1，见 preregistration_annex_A §4.1）
#
#   实测值（载量 / 涂层厚度 / 面积 / D50）在仓库里**只出现在
#   material_metadata.py 的校验与摘要打印**里，**没有任何代码把它们
#   变成 parameter_overrides**。而 geometry_audit() 是从**参数集自己**
#   反推几何与容量的（eps·A·L·c_max·F/3600），**不读实验值**。
#
#   后果不是"不够规范"，是**结论不可归因**：
#     模型默认沿用 Ecker2015_graphite_halfcell 的 R_p = 13.70 µm。
#     实测 D50/2 = 6.875 µm 时两者差 1.99× ⇒ D_s 读数差 3.97×（D ∝ R²）。
#     也就是**粒径变化会被读成"扩散变化"** —— 而这正是本课题要说的事。
#
# 这个模块只做一件事：把 metadata 里的四个实测量翻译成 PyBaMM 键，
# 并逐键给出 source_record。它**不碰冻结内核**（run_pipeline / runner /
# evaluator / factory / registry / rates / paths）。
#
# 三条设计规则（每一条都对应一处已经踩过的坑）
#
#   1. **缺任一项就整块不给**（all-or-nothing），不部分覆盖。
#      理由：R_p 与 L 同时进 tau = D·t/R²；只换 R_p 不换 L 会得到一个
#      既不是"参数集几何"也不是"实测几何"的混合态，事后无人能复算。
#
#   2. **每一键都必须有 source**（值 / 来自哪个 metadata 文件 / 公式）。
#      与 parameter_override_sources 的既有契约一致：没有来源的覆盖
#      在本平台不可引用。
#
#   3. **报告必须打印本轮用的是哪个 R**（returned as "radius_used_m"）。
#      不打印就等于把粒径变化读成扩散变化。
#
#   4. **与尺度对齐门冲突时硬失败**，不静默挑一个。
#      scale_alignment='align' 会写 "Electrode height/width [m]"，
#      本模块写的是**别的键**，两者同时生效会得到双重缩放：
#      Q_model 被面积缩放一次、再被 eps/厚度改一次。这类"两个都对但
#      合起来错"的组合，必须在入口就拦。
#
# 用法
#   from governance.geometry_channel import (
#       geometry_override_channel, geometry_channel_conflicts,
#   )
#   ch = geometry_override_channel("templates/commercial_graphite_ht/metadata/CG-AR.yaml")
#   if ch["incomplete"]:
#       print(ch["reason"])          # 报缺哪几项，不猜
#   else:
#       overrides = ch["parameter_overrides"]
#       sources   = ch["parameter_override_sources"]
# ============================================================

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

# 注意：**不在文件顶部 import battery_sim**。
#
# 治理层依赖内核这件事本身是设计（见文件头："不碰冻结内核"指的是不写内核，
# 读是允许的）；但**模块级** import 会让 `import governance.geometry_channel`
# 立刻拉起 6 个 battery_sim 模块 —— 于是"分层单向"在导入期就破产了，
# 内核与治理层被焊死在一起，任何只想要其中一半的人都得付另一半的代价。
#
# 改成函数体内 lazy import（与同目录 scale_alignment.py 一致）：
# 依赖关系不变、行为不变，但**导入期不再牵连**。
# 由 tests/test_module_graph.py 与 scripts/check_module_graph.py 钉住。

#: 本通路负责的四个人填实测量（点路径）。
REQUIRED_MEASUREMENTS = (
    "electrode.mass_loading_mg_cm2",
    "electrode.coating_thickness_um",
    "electrode.area_cm2",
    "particle.d50_um",
)

#: 只有这些量能从实测值直接翻译。其余几何键（孔隙率等）**不由本通路覆盖** ——
#: 它们要么需要真密度（annex A §3.1 的派生公式），要么需要配方，本轮不猜。
CHANNEL_KEYS = (
    "Positive particle radius [m]",
    "Positive electrode thickness [m]",
)

#: 尺度对齐门使用的旋钮键。本模块与它们互斥（见文件头第 4 条）。
SCALE_ALIGNMENT_KNOBS = ("Electrode height [m]", "Electrode width [m]")

#: 石墨真密度（g/cm³）。D50 换算不需要它；eps_am 才需要，而 eps_am 不在本通路。
#: 留在这里只为把"什么没有做"写在代码里，避免读者以为它被算过。
GRAPHITE_TRUE_DENSITY_G_CM3 = 2.26


def _dig(metadata: Mapping[str, Any], path: str) -> Any:
    node: Any = metadata
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def geometry_channel_conflicts(
    *,
    scale_alignment_mode: Optional[str],
    parameter_overrides: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """本通路与调用方已声明的覆盖/尺度模式是否冲突。

    返回冲突说明列表（空 = 无冲突）。**只报告，不抛** —— 抛错留给调用方，
    因为"冲突"与"怎么修"是两个决定（改参数、还是关掉通路）。
    """
    problems: List[str] = []
    mode = "check" if scale_alignment_mode is None else str(scale_alignment_mode)

    if mode == "align":
        problems.append(
            "scale_alignment='align' 会写 "
            f"{list(SCALE_ALIGNMENT_KNOBS)}（缩放 footprint 面积），"
            "而几何通路会改写 "
            f"{list(CHANNEL_KEYS)}（改活性体积与厚度）。"
            "两者同时生效 = 容量被缩放两次，得到既不是参数集尺度、"
            "也不是实测尺度的第三种几何。二者只能取一。"
        )

    supplied = set(parameter_overrides or {})
    clash = sorted(supplied & set(CHANNEL_KEYS))
    if clash:
        problems.append(
            f"调用方已在 parameter_overrides 里提供了 {clash}，"
            "几何通路会覆盖它们。要么去掉通路，要么把这些键从参数里拿掉 "
            "（并说明是谁在提供几何）。"
        )
    return problems


def geometry_override_channel(
    metadata_path: str | Path,
    *,
    require_complete: bool = False,
) -> Dict[str, Any]:
    """把一份材料元数据翻译成几何参数覆盖（含逐键来源）。

    参数
    ----
    metadata_path
        材料元数据 yaml（例 `templates/commercial_graphite_ht/metadata/CG-AR.yaml`）。
    require_complete
        ``True`` 时四个实测量缺任一项即抛 ``KeyError``；
        ``False``（默认）时返回 ``incomplete=True`` 的记录，由调用方决定。
        **默认不抛**，因为"数据还没到"与"填错了"是两件事 ——
        前者是 pending，后者才该失败。

    返回
    ----
    dict，始终含这些键：
        sample_id / metadata_path / measured / missing / complete / incomplete
    ``complete=True`` 时**另有**：
        parameter_overrides / parameter_override_sources / radius_used_m /
        thickness_used_m / formula_notes
    ``incomplete=True`` 时**另有**：
        reason（人类可读，说明缺什么、以及"不部分覆盖"的原因）
    """
    path = Path(metadata_path)
    from battery_sim.datasets.material_metadata import load_metadata

    meta = load_metadata(path)

    measured: Dict[str, float] = {}
    missing: List[str] = []
    for field in REQUIRED_MEASUREMENTS:
        value = _dig(meta, field)
        if _is_number(value):
            measured[field] = float(value)
        else:
            missing.append(field)

    record: Dict[str, Any] = {
        "sample_id": str(meta.get("sample_id") or ""),
        "metadata_path": str(path),
        "measured": measured,
        "missing": missing,
        "complete": not missing,
        "incomplete": bool(missing),
    }

    if missing:
        reason = (
            f"几何通路不完整：缺 {missing}。**不部分覆盖** —— "
            "R_p 与涂层厚度同时进 tau = D·t/R²，只换一部分会得到一个"
            "既不是参数集几何、也不是实测几何的混合态，事后无法复算。"
            "补齐这四项后重跑（材料元数据的模板与自检见 "
            "templates/commercial_graphite_ht/metadata/）。"
        )
        record["reason"] = reason
        if require_complete:
            raise KeyError(reason)
        return record

    if len(measured) != len(REQUIRED_MEASUREMENTS):  # pragma: no cover
        raise ValueError(
            "几何通路内部不一致：missing 为空但 measured 条目数不符。"
            "不允许继续（宁可失败也不给一个说不清来源的几何）。"
        )

    d50_um = measured["particle.d50_um"]
    thickness_um = measured["electrode.coating_thickness_um"]
    radius_m = d50_um * 1e-6 / 2.0
    thickness_m = thickness_um * 1e-6

    if radius_m <= 0 or thickness_m <= 0:
        raise ValueError(
            f"{path}: 几何实测值必须为正（D50={d50_um} µm, "
            f"厚度={thickness_um} µm）"
        )

    rel = str(path)
    sources = {
        "Positive particle radius [m]": {
            "value": radius_m,
            "source": "measured",
            "origin": f"{rel} : particle.d50_um = {d50_um} µm",
            "formula": "R_p = D50 / 2（球等效半径）",
            "note": (
                "D50 必须是**本样品实测**（每样品重测），不能用规格书值："
                "规格书是处理前的粉，热处理的失重与破碎会改粒径。"
            ),
        },
        "Positive electrode thickness [m]": {
            "value": thickness_m,
            "source": "measured",
            "origin": (
                f"{rel} : electrode.coating_thickness_um = {thickness_um} µm"
            ),
            "formula": "L = 涂层厚度（千分尺实测，不是标称）",
            "note": "直接进模型容量与 tau。",
        },
    }

    record.update(
        {
            "parameter_overrides": {
                "Positive particle radius [m]": radius_m,
                "Positive electrode thickness [m]": thickness_m,
            },
            "parameter_override_sources": sources,
            "radius_used_m": radius_m,
            "thickness_used_m": thickness_m,
            "mass_loading_mg_cm2": measured["electrode.mass_loading_mg_cm2"],
            "area_cm2": measured["electrode.area_cm2"],
            "d50_um": d50_um,
            "coating_thickness_um": thickness_um,
            "formula_notes": (
                "R_p = D50/2 ; L = 实测涂层厚度。"
                "**没有**改 eps_am / porosity：那两者要把载量与真密度、"
                "配方按 annex A §3.1 的固定公式算出来，本通路不猜。"
                "因此覆盖后模型的 Q_model 只随 R_p 之外的几何变化，"
                "尺度一致性仍由尺度对齐门单独判（每轮都要报）。"
            ),
            "not_covered": (
                "Positive electrode active material volume fraction",
                "Positive electrode porosity",
                "Nominal cell capacity [A.h]",
            ),
        }
    )
    return record


def radius_report_line(record: Mapping[str, Any]) -> str:
    """一行"本轮用的是哪个 R"——必须出现在报告里（不打印 = 无法归因）。"""
    if not record.get("complete"):
        return (
            "R 口径：**参数集默认值**（几何通路不完整，缺 "
            f"{record.get('missing')}）—— 跨样品不能据此解释 D_s 差异。"
        )
    r_um = float(record["radius_used_m"]) * 1e6
    d50 = float(record["d50_um"])
    return (
        f"R 口径：**本样品实测 D50 = {d50:g} µm** ⇒ R_p = {r_um:.3f} µm"
        f"（来自 {record['metadata_path']}）。"
        "跨样品比较 D_s 时必须用同一 R 口径。"
    )


# ------------------------------------------------------------------
# 与尺度对齐门的联动检查（供调用方在入口使用）
# ------------------------------------------------------------------
def assert_geometry_channel_consistent(
    *,
    scale_alignment_mode: Optional[str],
    parameter_overrides: Optional[Mapping[str, Any]] = None,
    context: str = "",
) -> None:
    """冲突即抛 ``ValueError``。与 ``geometry_channel_conflicts`` 配成一对：

    前者是查询（先看清再决定），后者是入口守卫（决定之后不许反悔）。
    """
    problems = geometry_channel_conflicts(
        scale_alignment_mode=scale_alignment_mode,
        parameter_overrides=parameter_overrides,
    )
    if problems:
        where = f"{context}: " if context else ""
        raise ValueError(
            where + "几何通路与已有覆盖冲突 ——\n  - "
            + "\n  - ".join(problems)
        )


__all__ = [
    "CHANNEL_KEYS",
    "GRAPHITE_TRUE_DENSITY_G_CM3",
    "REQUIRED_MEASUREMENTS",
    "SCALE_ALIGNMENT_KNOBS",
    "assert_geometry_channel_consistent",
    "geometry_channel_conflicts",
    "geometry_override_channel",
    "radius_report_line",
]
