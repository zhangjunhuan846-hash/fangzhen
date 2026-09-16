# ============================================================
# 尺度对齐门（Scale alignment gate）
#
# 为什么它是一级概念，而不是某个脚本里的一段
#   G5 与 G6 各踩过一次同一个坑，两次**表现完全一样**：
#       "模型对这个参数没有反应" —— 读起来就是**参数惰性**。
#   根因却不是参数，而是 **Q_model != Q_measured**：
#
#     G5  p-OCV 分支：模型 202 mAh 的电芯几何被拿来回放另一颗电芯的电流，
#         4.33e-5 A 实际是 C/4670 —— 得出"准平衡不激发固相扩散"的错误结论。
#     G6  DLR GITT ：标称 C/10 的 150 s 脉冲实际落在 C/309，
#         仿真瞬态比实测小 43 倍（0.394 mV vs 17.165 mV）。
#
#   两次都不是"协议不激发"，而是**模型不在电芯的尺度上**。
#   两者在输出里长得一模一样，靠人眼看是分不开的 —— 所以必须由代码拦。
#
# 顺序（这个顺序本身就是结论）
#
#     Dataset
#       |
#       v
#     Geometry audit          <- 参数集自己说自己描述的是多大一颗电芯
#       |
#       v
#     Capacity alignment      <- Q_model == Q_measured，本模块
#       |
#       v
#     Protocol excitation     <- 只有对齐之后，"协议是否激发"才是一个问题
#       |
#       v
#     Parameter inference     <- 最后才轮到辨识
#
#   石墨、LFP 回收、硬碳钠电都会踩同一个坑，因为**参数集描述的电芯
#   与手上的电芯永远不是同一颗**。跳过前三步直接做第四步，
#   得到的"参数不可辨识"里混着尺度失配，无法归因。
#
# 本模块**不碰**冻结内核（runner / evaluator / factory / registry / rates /
# paths）。它只提供"查 + 断言 + 给出对齐配方"三件事，调用方自己决定在哪一步用。
# 真正的入口级强制在 `battery_sim/simulation/protocol_replay.py`
# （那里是新增的 additive 入口，可以严；`run_baseline_cell` 是冻结的，不改）。
#
# 与 `governance/dataset_roles.py` 的分工
#   dataset_roles  回答"这份数据**允许**被用来做什么"（用途）
#   scale_alignment 回答"这次回放**是否在同一个物理尺度上**"（前置条件）
#   两者都是"先声明、再检查"，都不做科学计算本身。
# ============================================================

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

#: 全流程的规范顺序。写成元组的目的是让"我们跳过了哪一步"可以被机器读出来，
#: 而不是只存在于文档的示意图里。
PIPELINE_STAGES = (
    "dataset",
    "geometry_audit",
    "capacity_alignment",
    "protocol_excitation",
    "parameter_inference",
)

#: 本模块负责的阶段。
STAGE = "capacity_alignment"
UPSTREAM_STAGE = "geometry_audit"
NEXT_STAGE = "protocol_excitation"

#: 容量一致化的旋钮：电极 footprint 的两个线性尺寸。
#: 不选 ε_am / 厚度，因为要达到 31 倍的容量比，那两个旋钮会给出物理上荒谬的值
#: （ε_am 会掉到 0.012、厚度掉到 2.4 µm）。缩放面积则保持一个可接受的几何。
DEFAULT_KNOBS = ("Electrode height [m]", "Electrode width [m]")

#: 判定"同尺度"的容差：|log10(Q_model / Q_measured)| <= 该值。
#: ±0.05 dex ≈ ±12 %。**这是声明出来的容差，不是推导出来的**：
#: 它的任务是拦住 31×（DLR）与 3×（SINTEF p-OCV）这一量级的失配，
#: 不是拦住 5 % 的批次差异。
ALIGNMENT_TOLERANCE_DEX = 0.05

#: 法拉第常数，与 PyBaMM 默认值一致。
FARADAY = 96485.33212


class ScaleMisalignment(RuntimeError):
    """模型不在电芯的尺度上，而调用方要求继续往下走。

    刻意用独立异常类型而不是 ``ValueError``：调用方需要能把
    "尺度没对齐"与"参数写错了"分开处理 —— 前者是可以修的（给出配方即可），
    后者不行。宽泛的 ``except`` 会把这两种情形混在一起，
    这正是本仓库已经吃过一次亏的地方。
    """


# ------------------------------------------------------------------
# 阶段 1：几何自审
# ------------------------------------------------------------------
def geometry_audit(
    parameter_set: str,
    knobs: Sequence[str] = DEFAULT_KNOBS,
) -> Dict[str, object]:
    """从参数集自己算出它描述的是多大一颗电芯。

    这是流水线的第一步，也是唯一一步不接触实验数据的一步：
    先弄清模型的"尺子"有多长，再拿实验去比。

    只读 ``Positive electrode ...`` 一族键 —— 半电池把工作电极映射到
    positive 槽位是本仓库的既定约定（见 `configs/datasets.yaml` 的
    ``working_electrode``；``Negative electrode OCP [V] = 0.0`` 是锂金属对电极）。
    按全电池命名去找这些键会全部落空，所以这里显式写死槽位而不是猜。
    """
    from battery_sim.models.pybamm_factory import load_parameter_values

    pv = load_parameter_values(parameter_set)
    need = {
        "active_volume_fraction": (
            "Positive electrode active material volume fraction"
        ),
        "thickness_m": "Positive electrode thickness [m]",
        "c_max_mol_m3": (
            "Maximum concentration in positive electrode [mol.m-3]"
        ),
    }
    missing = [k for k in (list(need.values()) + list(knobs)) if k not in pv]
    if missing:
        raise KeyError(
            f"scale alignment: geometry key(s) absent from parameter set "
            f"'{parameter_set}': {missing}"
        )

    eps = float(pv[need["active_volume_fraction"]])
    thick = float(pv[need["thickness_m"]])
    cmax = float(pv[need["c_max_mol_m3"]])
    dims = {str(k): float(pv[k]) for k in knobs}

    area = 1.0
    for k in knobs:
        area *= dims[str(k)]
    capacity_Ah = eps * area * thick * cmax * FARADAY / 3600.0
    if capacity_Ah <= 0:
        raise ValueError(
            f"scale alignment: '{parameter_set}' yields a non-positive "
            f"capacity ({capacity_Ah} Ah); the geometry cannot be used"
        )
    return {
        "parameter_set": str(parameter_set),
        "active_volume_fraction": eps,
        "thickness_m": thick,
        "c_max_mol_m3": cmax,
        "footprint_dimensions_m": dims,
        "area_m2": area,
        "capacity_Ah": capacity_Ah,
        "capacity_formula": (
            "eps_am * (height * width) * thickness * c_max * F / 3600"
        ),
        "electrode_slot": "positive",
        "electrode_slot_note": (
            "a half cell puts its WORKING electrode in the positive slot on "
            "this platform; reading these keys by full-cell name returns "
            "nothing"
        ),
    }


# ------------------------------------------------------------------
# 阶段 2：容量对齐
# ------------------------------------------------------------------
def _resolve_cell(adapter, cell: Optional[str]) -> str:
    if cell is not None:
        return str(cell)
    cells = list(adapter.list_cells())
    if not cells:
        raise ValueError(
            f"scale alignment: dataset '{adapter.config.dataset_id}' "
            f"declares no cells"
        )
    return str(cells[0])


def _load_window(adapter, cell: str, protocol_id: str):
    """Whether ``protocol_id`` is a recorded protocol or a rate is a
    capability question, not a name convention.

    ``hasattr(adapter, "load_processed_protocol")`` is ALWAYS true because
    the base class DEFINES it (raising ``NotImplementedError``) so the
    capability is declared rather than accidental.  The test has to be
    whether the subclass actually overrides it.
    """
    from battery_sim.datasets.base import BatteryDatasetAdapter

    has_protocols = (
        type(adapter).load_processed_protocol
        is not BatteryDatasetAdapter.load_processed_protocol
    )
    if has_protocols:
        return adapter.load_processed_protocol(cell, protocol_id)
    return adapter.load_processed_discharge(cell, protocol_id)


def measure_window_charge_Ah(adapter, cell: str, protocol_id: str) -> float:
    """Net charge the record actually passed over one window, in Ah.

    A measurement, not a datasheet claim: trapezoidal integral of the
    canonical current.  This is the number ``Q_measured`` refers to.
    """
    import numpy as np

    df = _load_window(adapter, cell, str(protocol_id))
    t = df["time_s"].to_numpy(float)
    I = df["current_A"].to_numpy(float)
    if t.size < 2:
        raise ValueError(
            f"scale alignment: window '{protocol_id}' has {t.size} point(s); "
            f"a charge cannot be integrated"
        )
    ah = abs(float(np.sum(0.5 * (I[1:] + I[:-1]) * np.diff(t))) / 3600.0)
    if ah <= 0:
        raise ValueError(
            f"scale alignment: window '{protocol_id}' passed no net charge; "
            f"capacity alignment is undefined for it"
        )
    return ah


def _charge_reference(adapter, protocol_id: str, charge_reference: Optional[str]) -> str:
    """WHICH charge is "the cell's capacity" is a dataset-level fact.

    A single pulse-rest triplet passes only its own pulse (0.027 mAh here),
    and treating that as the cell capacity scales the model down by ~7400x,
    which drives it straight into the voltage cut-off and produces NaN
    transients -- which reads exactly like "the parameter is inert".  A
    dataset therefore DECLARES a reference protocol whose recorded charge
    is the accessible capacity; failing that declaration the window itself
    is used, which is right when the window is a full sweep.
    """
    if charge_reference is not None:
        return str(charge_reference)
    getter = getattr(adapter, "capacity_reference_protocol", None)
    if callable(getter):
        declared = getter()
        if declared:
            return str(declared)
    return str(protocol_id)


def alignment_overrides(
    adapter,
    protocol_id: str,
    cell: Optional[str] = None,
    *,
    parameter_set: Optional[str] = None,
    charge_reference: Optional[str] = None,
    knobs: Sequence[str] = DEFAULT_KNOBS,
) -> Dict[str, object]:
    """The footprint recipe that puts the model on the cell's scale.

    Always computes the scaling; it does NOT short-circuit on tolerance.
    A caller that wants the tolerance judgement wants :func:`audit`.

    Returns ``{"overrides", "source", "footprint_scale_area",
    "footprint_scale_linear", "charge_reference", "measured_charge_Ah",
    "model_capacity_Ah", "geometry"}``.  ``overrides`` plugs straight into
    a replay's ``parameter_overrides`` and ``source`` into
    ``parameter_override_sources``, so the scaling is as auditable as any
    other override.
    """
    import numpy as np

    cell = _resolve_cell(adapter, cell)
    if parameter_set is None:
        parameter_set = adapter.config.parameter_set

    ref_id = _charge_reference(adapter, protocol_id, charge_reference)
    measured_Ah = measure_window_charge_Ah(adapter, cell, ref_id)
    geom = geometry_audit(parameter_set, knobs=knobs)
    model_Ah = float(geom["capacity_Ah"])

    scale = measured_Ah / model_Ah
    root = float(math.sqrt(scale))
    overrides = {
        str(k): float(geom["footprint_dimensions_m"][str(k)]) * root
        for k in knobs
    }
    reason = (
        f"the recorded charge over '{ref_id}' is {measured_Ah * 1e3:.4f} mAh; "
        f"parameter set '{parameter_set}' describes a {model_Ah * 1e3:.3f} mAh "
        f"cell; the footprint is scaled by {root:.6f} (area x{scale:.6f}) so "
        f"the two agree"
    )
    source = {
        str(k): {
            "source": "CAPACITY ALIGNMENT (Q_model == Q_measured)",
            "method": "governance/scale_alignment.py",
            "stage": STAGE,
            "basis": reason,
            "charge_reference": str(ref_id),
            "params_scaled": [str(k) for k in knobs],
            "scale_factor_area": scale,
            "scale_factor_linear": root,
        }
        for k in knobs
    }
    return {
        "overrides": overrides,
        "source": source,
        "footprint_scale_area": scale,
        "footprint_scale_linear": root,
        "charge_reference": str(ref_id),
        "measured_charge_Ah": measured_Ah,
        "model_capacity_Ah": model_Ah,
        "geometry": geom,
        "reason": reason,
        "cell": cell,
        "dataset_id": str(adapter.config.dataset_id),
        "parameter_set": str(parameter_set),
        "protocol_id": str(protocol_id),
    }


def audit(
    adapter,
    protocol_id: str,
    cell: Optional[str] = None,
    *,
    parameter_set: Optional[str] = None,
    charge_reference: Optional[str] = None,
    knobs: Sequence[str] = DEFAULT_KNOBS,
    tolerance_dex: float = ALIGNMENT_TOLERANCE_DEX,
) -> Dict[str, object]:
    """Full alignment record, including the C-rate the model is ACTUALLY at.

    The two C-rate numbers are the whole point of the gate, in one place:

      ``c_rate_on_cell``          what the readout says (e.g. 0.10)
      ``c_rate_on_model_unscaled`` what the model actually does (e.g. 0.0032)

    They differ by exactly the capacity ratio, and only the second one
    determines whether solid diffusion is excited.  Reporting only the
    first is how "C/10" became "C/309" without anyone noticing.
    """
    import numpy as np

    cell = _resolve_cell(adapter, cell)
    rec = alignment_overrides(
        adapter, protocol_id, cell,
        parameter_set=parameter_set,
        charge_reference=charge_reference,
        knobs=knobs,
    )

    df = _load_window(adapter, cell, str(protocol_id))
    I_peak = float(np.nanmax(np.abs(df["current_A"].to_numpy(float)))) if len(df) else 0.0

    measured_Ah = float(rec["measured_charge_Ah"])
    model_Ah = float(rec["model_capacity_Ah"])
    log10_ratio = float(math.log10(model_Ah / measured_Ah))

    aligned = abs(log10_ratio) <= float(tolerance_dex)
    return {
        **rec,
        "stage": STAGE,
        "upstream_stage": UPSTREAM_STAGE,
        "next_stage": NEXT_STAGE,
        "pipeline_stages": list(PIPELINE_STAGES),
        "tolerance_dex": float(tolerance_dex),
        "log10_model_over_measured": log10_ratio,
        "capacity_ratio_model_over_measured": model_Ah / measured_Ah,
        "verdict": "aligned" if aligned else "misaligned",
        "window_peak_current_A": I_peak,
        "c_rate_on_cell": (I_peak / measured_Ah) if measured_Ah else None,
        "c_rate_on_model_unscaled": (I_peak / model_Ah) if model_Ah else None,
        "c_rate_deficit_factor": (
            (model_Ah / measured_Ah) if measured_Ah else None
        ),
        "what_to_do": (
            "same scale: the parameter set describes this cell's size"
            if aligned else
            "apply rec['overrides'] via parameter_overrides; without it the "
            "model runs at 1/{:.1f} of the intended C-rate and a "
            "diffusion-limited protocol becomes inert".format(
                model_Ah / measured_Ah
            )
        ),
    }


def assert_aligned(
    adapter,
    protocol_id: str,
    cell: Optional[str] = None,
    *,
    tolerance_dex: float = ALIGNMENT_TOLERANCE_DEX,
    **kwargs,
) -> Dict[str, object]:
    """Refuse to continue when the model is not on the cell's scale."""
    rec = audit(
        adapter, protocol_id, cell,
        tolerance_dex=tolerance_dex, **kwargs,
    )
    if rec["verdict"] != "aligned":
        raise ScaleMisalignment(
            f"{rec['dataset_id']} / {rec['protocol_id']}: the model is a "
            f"{rec['model_capacity_Ah'] * 1e3:.3f} mAh cell while the record "
            f"passed {rec['measured_charge_Ah'] * 1e3:.4f} mAh "
            f"(ratio {rec['capacity_ratio_model_over_measured']:.1f}x, "
            f"{rec['log10_model_over_measured']:+.3f} dex, tolerance "
            f"±{tolerance_dex} dex). A window read as C/10 would run at "
            f"C/{1.0 / (rec['c_rate_on_model_unscaled'] or float('nan')):.0f} "
            f"on this model. Apply "
            f"governance.scale_alignment.alignment_overrides(...)['overrides'] "
            f"as parameter_overrides, or declare scale_alignment explicitly."
        )
    return rec


__all__ = [
    "ALIGNMENT_TOLERANCE_DEX",
    "DEFAULT_KNOBS",
    "FARADAY",
    "NEXT_STAGE",
    "PIPELINE_STAGES",
    "STAGE",
    "ScaleMisalignment",
    "UPSTREAM_STAGE",
    "alignment_overrides",
    "assert_aligned",
    "audit",
    "geometry_audit",
    "measure_window_charge_Ah",
]
