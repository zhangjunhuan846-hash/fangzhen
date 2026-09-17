"""体系锚定的电压窗口（chemistry-anchored voltage windows）。

为什么需要它
============
``user_tools/validate.py`` 里的 ``VOLTAGE_RANGE`` 只做一件事：把**数据**与
**用户自己填的窗口**对账。用户把石墨半电池的窗口填成 ``[0.005, 15]`` V，
那项检查会报 PASS —— 声明与数据自洽，但**声明本身是错的**，而仿真层不会
因此报错，只会把整段曲线按一个不存在的窗口跑完。

本模块补的是另一件事：把**声明的窗口（以及实测极值）**与**该电化学体系的
参考窗口**对账。两边都不是从数据推出来的，所以规则必须显式、可审计、
宁可少也不要猜 —— 未收录的体系一律返回 ``None`` 并说明缺哪条声明。

两级判据（这是本模块唯一需要解释的设计）
========================================
每条规则带两组界：

``nominal``  该体系**通常**用的窗口。越界 = 警告。
             正当的例外太多（部分窗口、厂商窗口、老化后收窄），所以不判死。
``hard``     对**该体系而言物理上讲不通**的界。越界 = 错误。
             例如石墨半电池出现 20 V：那不是窗口选得宽，那是单位/通道/参比错了。

把两级分开是为了不让"正当的部分窗口"被误杀，同时仍然挡住真正的外行错误。

覆盖范围（刻意保守）
====================
只收录平台已经有一等公民支持的体系（石墨半电池、三类常见全电池）。
其余返回 ``None`` + 原因，由调用方写成 WARN —— **不猜**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------
# 体系 id（闭集）
# ------------------------------------------------------------------
SYS_GRAPHITE_HALFCELL_LI = "graphite_halfcell_li"
SYS_NMC_FULLCELL = "nmc_fullcell"
SYS_LCO_FULLCELL = "lco_fullcell"
SYS_LFP_FULLCELL = "lfp_fullcell"


@dataclass(frozen=True)
class VoltageWindow:
    """一个体系的参考窗口。

    ``nominal`` / ``hard`` 的含义见模块 docstring；两组都是**开区间判据**
    （``value < lo`` 或 ``value > hi`` 才算越界，端点算合法）。
    """

    system_id: str
    label: str
    nominal: Tuple[float, float]
    hard: Tuple[float, float]
    rationale: str
    source: str

    def describe(self) -> str:
        return (
            f"{self.label}：常用窗口 {self.nominal[0]:g}–{self.nominal[1]:g} V，"
            f"物理上讲不通的界 {self.hard[0]:g}–{self.hard[1]:g} V"
        )


#: 体系窗口表。改这里 = 改规则；每条都必须写 rationale 与 source。
WINDOWS: Dict[str, VoltageWindow] = {
    SYS_GRAPHITE_HALFCELL_LI: VoltageWindow(
        system_id=SYS_GRAPHITE_HALFCELL_LI,
        label="graphite || Li metal（半电池，工作电极 = 石墨）",
        nominal=(0.005, 1.5),
        hard=(0.0, 2.5),
        rationale=(
            "下限贴锂化端：石墨在 ~0.005 V vs Li/Li+ 附近才是高锂化平台；"
            "上限 1.5 V 覆盖脱锂全段。这是**功能性窗口**（平台自己的石墨热处理"
            "梯度设计用的就是它），不是热力学上界。"
            "上限到 2.5 V 仍可能是合法的深脱锂实验，所以只警告；"
            ">2.5 V 说明通道/参比/单位错了（单体锂离子体系到不了那里）。"
        ),
        source="docs/graphite_heat_treatment_test_plan.md（平台设计口径）",
    ),
    SYS_NMC_FULLCELL: VoltageWindow(
        system_id=SYS_NMC_FULLCELL,
        label="NMC/graphite 全电池",
        nominal=(2.5, 4.2),
        hard=(1.5, 5.0),
        rationale=(
            "与平台 configs/datasets.yaml 中 NMC 全电池数据集声明的窗口一致"
            "（2.5–4.2 V）。全电池的下限由负极/正极各自的截止决定，"
            "不同厂商会挪到 2.75 或 3.0 V，所以只警告不判死。"
        ),
        source="configs/datasets.yaml（NMC 全电池数据集的声明窗口）",
    ),
    SYS_LCO_FULLCELL: VoltageWindow(
        system_id=SYS_LCO_FULLCELL,
        label="LCO/graphite 全电池",
        nominal=(2.7, 4.2),
        hard=(1.5, 5.0),
        rationale=(
            "与平台 configs/datasets.yaml 中 LCO 全电池数据集声明的窗口一致"
            "（2.7–4.2 V）。"
        ),
        source="configs/datasets.yaml（LCO 全电池数据集的声明窗口）",
    ),
    SYS_LFP_FULLCELL: VoltageWindow(
        system_id=SYS_LFP_FULLCELL,
        label="LFP/graphite 全电池",
        nominal=(2.0, 3.65),
        hard=(1.0, 4.5),
        rationale=(
            "LFP 的平台电压 ~3.4 V；2.0–3.65 V 是常见做法。"
            "上限超过 4.0 V 对 LFP 体系意味着过充/电解液分解，越界只警告，"
            "因为有些测试故意走到 4.2 V 做边界实验。"
        ),
        source="平台内置参数集 Prada2013 / Chen2020 的化学体系常识（非本数据集实测）",
    ),
}

#: 石墨的显式别名（**闭集**：出现没列过的写法就报"无法锚定"，不猜）
_GRAPHITE_ALIASES = frozenset({
    "graphite",
    "graphite_negative",
    "graphite_anode",
    "graphite_halfcell",
    "artificial_graphite",
    "natural_graphite",
    "graphite_limetal",
    "graphite_li",
})

#: 锂金属对电极的显式别名
_LI_METAL_ALIASES = frozenset({
    "lithium_metal",
    "li",
    "li_metal",
    "limetal",
    "lithium",
    "li片",
})

# ------------------------------------------------------------------
# 声明词表（**唯一来源**）
#
# 这两张表被三个入口共用：自服务导入表（`user_tools/spec.py`）、
# 材料元数据（`battery_sim/datasets/material_metadata.py`）、以及材料侧
# 系列校验。放在这里而不是各写一份，是因为"两个入口两套标准"正是
# 规则表这种代码最容易长出来的病（加一条新体系时只改了一半）。
# ------------------------------------------------------------------
WORKING_ELECTRODE_MATERIALS = (
    "graphite",
    "nmc",
    "lfp",
    "lco",
    "lithium_metal",
    "silicon_c",
    "other",
)

COUNTER_ELECTRODE_TYPES = (
    "lithium_metal",
    "graphite",
    "other",
)

_NMC_TOKENS = ("nmc", "ncm", "nicomn", "ncm_li", "nmc_graphite", "ncm_graphite")
_LCO_TOKENS = ("lco", "licoo2", "lco_graphite")
_LFP_TOKENS = ("lfp", "lifepo4", "lfp_graphite")


def _norm(value) -> str:
    """规整成一个可比较的 token：小写、去空格、连字符转下划线。"""
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _is_graphite_working_electrode(
    working_electrode_material: str,
    physical_working_electrode: str,
) -> bool:
    """工作电极是不是石墨。两个字段任一命中即可（都是显式声明）。"""
    for raw in (working_electrode_material, physical_working_electrode):
        t = _norm(raw)
        if not t:
            continue
        if t in _GRAPHITE_ALIASES:
            return True
        # 含糊但明确指向石墨的复合写法：graphite_xxx / xxx_graphite
        if t.startswith("graphite_") or t.endswith("_graphite"):
            return True
    return False


def resolve_system(
    *,
    chemistry: str = "",
    cell_configuration: str = "",
    working_electrode: str = "",
    counter_electrode: str = "",
    working_electrode_material: str = "",
    physical_working_electrode: str = "",
) -> Tuple[Optional[VoltageWindow], str]:
    """把声明的事实映射到一个体系窗口。

    返回 ``(window, reason)``：

    * 命中 -> ``(VoltageWindow, "")``
    * 没命中 -> ``(None, reason)``，``reason`` 说明**缺哪条声明**或哪种组合
      不在表内。调用方应当把它写成 WARN（检查被跳过），而不是 PASS。

    禁止推断的部分：本函数不会因为 ``cell_configuration=half_cell`` 就假定
    工作电极是石墨，也不会从 ``chemistry`` 反推负极材料。

    ``cell_configuration`` 可以留空：**「工作电极 = 石墨 且 对电极 = 锂金属」
    这一对声明本身就唯一确定了半电池**（全电池不存在锂金属对电极）。
    这不是推断，是读两条显式声明；正因如此，如果两者同时给出却互相矛盾
    （写成 full_cell 却有锂金属对电极），本函数会返回 ``None`` 并说明矛盾，
    而不是挑一个信。
    """
    cfg = _norm(cell_configuration)
    chem = _norm(chemistry)
    counter = _norm(counter_electrode)
    graphite = _is_graphite_working_electrode(
        working_electrode_material, physical_working_electrode
    )
    li_counter = counter in _LI_METAL_ALIASES

    is_half = cfg in ("half_cell", "halfcell") or (not cfg and graphite
                                                   and li_counter)
    is_full = cfg in ("full_cell", "fullcell")

    if is_full and li_counter:
        return None, (
            "声明自相矛盾：cell_configuration=full_cell 但对电极写作 "
            f"'{counter_electrode}'。全电池没有锂金属对电极 —— "
            "先确认构型，再谈窗口"
        )

    if not cfg and not (graphite and li_counter):
        return None, (
            "未声明 cell_configuration，且工作电极/对电极这一对也不足以"
            "确定构型（需要 working_electrode_material=graphite 且 "
            "counter_electrode=lithium_metal）。无法判断该用哪个体系的电压窗口"
        )

    if is_half:
        if graphite and li_counter:
            return WINDOWS[SYS_GRAPHITE_HALFCELL_LI], ""
        missing: List[str] = []
        if not graphite:
            missing.append(
                "工作电极材料不是石墨（working_electrode_material / "
                "physical_working_electrode 未写或不在别名表内）"
            )
        if not li_counter:
            missing.append(
                f"对电极不是锂金属（counter_electrode='{counter_electrode}'）"
            )
        return None, (
            "半电池但这套声明没有对应的参考窗口：" + "；".join(missing)
            + "。当前表内只有 graphite || Li metal 一条半电池规则"
        )

    if is_full:
        if any(tok in chem for tok in _LFP_TOKENS):
            return WINDOWS[SYS_LFP_FULLCELL], ""
        if any(tok in chem for tok in _LCO_TOKENS):
            return WINDOWS[SYS_LCO_FULLCELL], ""
        if any(tok in chem for tok in _NMC_TOKENS):
            return WINDOWS[SYS_NMC_FULLCELL], ""
        return None, (
            f"全电池但 chemistry='{chemistry}' 不在表内"
            f"（写法需要含 {'/'.join(_NMC_TOKENS[:2])} / lco / lfp 之一）"
        )

    return None, f"cell_configuration='{cell_configuration}' 无法识别"


def check_declared_window(
    window: VoltageWindow,
    lower,
    upper,
) -> Tuple[List[str], List[str]]:
    """核对**用户声明的窗口**。返回 ``(errors, warnings)``。"""
    errors: List[str] = []
    warnings: List[str] = []
    try:
        lo = float(lower)
        hi = float(upper)
    except (TypeError, ValueError):
        return (
            [f"声明窗口不是数字：lower={lower!r}, upper={upper!r}"],
            [],
        )

    if not lo < hi:
        errors.append(
            f"声明窗口上下限颠倒或相等：[{lo:g}, {hi:g}] V"
        )
        return errors, warnings

    hard_lo, hard_hi = window.hard
    if lo < hard_lo or hi > hard_hi:
        errors.append(
            f"声明窗口 [{lo:g}, {hi:g}] V 超出 {window.label} 的物理界 "
            f"[{hard_lo:g}, {hard_hi:g}] V —— 这不是窗口选得宽，"
            f"而是体系/单位/参比有一处不对（依据：{window.source}）"
        )
    else:
        nom_lo, nom_hi = window.nominal
        if lo < nom_lo or hi > nom_hi:
            warnings.append(
                f"声明窗口 [{lo:g}, {hi:g}] V 超出该体系的常用窗口 "
                f"[{nom_lo:g}, {nom_hi:g}] V（{window.rationale}）。"
                f"如果是刻意的部分窗口/厂商窗口，记进 provenance 即可"
            )
    return errors, warnings


def check_measured_window(
    window: VoltageWindow,
    v_min: float,
    v_max: float,
) -> Tuple[List[str], List[str]]:
    """核对**实测电压极值**。返回 ``(errors, warnings)``。"""
    errors: List[str] = []
    warnings: List[str] = []
    if v_min != v_min or v_max != v_max:      # NaN 自我保护
        return errors, [
            "实测电压极值不是有限数，跳过体系窗口核对"
        ]

    hard_lo, hard_hi = window.hard
    if v_min < hard_lo or v_max > hard_hi:
        errors.append(
            f"实测电压 [{v_min:.4g}, {v_max:.4g}] V 超出 {window.label} 的物理界 "
            f"[{hard_lo:g}, {hard_hi:g}] V —— 典型原因是单位（mV 当 V）、"
            f"错把全电池数据当半电池、或通道/参比接错"
        )
    else:
        nom_lo, nom_hi = window.nominal
        if v_min < nom_lo or v_max > nom_hi:
            warnings.append(
                f"实测电压 [{v_min:.4g}, {v_max:.4g}] V 超出该体系的常用窗口 "
                f"[{nom_lo:g}, {nom_hi:g}] V —— 可能是刻意的宽窗/边界实验，"
                f"请在报告里说明"
            )
    return errors, warnings


def describe_all() -> Sequence[VoltageWindow]:
    """按 system_id 排序列出全部规则（审计用）。"""
    return [WINDOWS[k] for k in sorted(WINDOWS)]


__all__ = [
    "SYS_GRAPHITE_HALFCELL_LI",
    "SYS_LCO_FULLCELL",
    "SYS_LFP_FULLCELL",
    "SYS_NMC_FULLCELL",
    "VoltageWindow",
    "WINDOWS",
    "check_declared_window",
    "check_measured_window",
    "describe_all",
    "resolve_system",
]
