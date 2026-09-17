"""L4 倍率预测验收：用低倍率辨识出的参数，去预测**另一个倍率**。

这个模块存在的理由
==================
平台到 v0.1 为止能证明的是「回放」：把实测电流喂进去，模型能走出接近的电压。
那**不构成预测能力** —— 回放用的是同一段数据，参数也可以是从它里面调出来的。
第一篇应用论文的看点是下面这条链：

    低倍率（辨识集）-> 参数（D_s 等）-> 高倍率（**留出集**）-> 与实测比

所以这里只做一件事：把「辨识」与「被预测的倍率」当成两份独立的数据集，
在**角色治理**与**尺度对齐**两道门后面跑一次回放，把误差如实报出来。

三条必须写在报告里的口径（写在代码里，是因为它们最容易被忘）
------------------------------------------------------------
1. **倍率外推 ≠ 独立样品验证。** 同一颗电芯的 0.1C 与 1C 是同一次实验的两个
   倍率；用它检验的是「倍率外推」，不是「跨样品泛化」。跨样品泛化要靠
   平行样品（平台设计里是每组 ≥3 颗）。报告里两者分开写。
2. **留出集必须是声明出来的，不是推断出来的。** ``governance.dataset_roles``
   里 ``identification`` 角色的数据**禁止**当留出集（那等于对自己评分）；
   ``benchmark`` 角色的数据可以评，但**参数集不是为它标定的**，所以那个比较
   不构成验证。未声明角色 = 无法证明它不是辨识集 -> 只出报告，不出结论。
3. **覆盖不足记失败，不在残片上打分。** 模型若晚到截止电压，比较区间会变短；
   把那段短残差拿来算 RMSE 会让一个明显错的参数看起来很好
   （``identification/forward.py`` 里是同一条规矩）。

用法
----
    python -m identification.rate_prediction \
        --fit-dataset graphite_ht_cg_800 --fit-rate C0p2 \
        --target-dataset graphite_ht_cg_800_holdout --target-rate C1 \
        --overrides overrides.json \
        --out outputs/analysis/l4/cg800_0p2_to_1C.md

``--overrides`` 是**唯一**的参数入口（JSON）：

.. code-block:: json

    {
      "provenance": "从 CG-800 的 0.1C + GITT 辨识（<命令/日期>）",
      "overrides": {
        "Ds": {"shape": "constant", "amplitude_dex": -0.42},
        "Contact resistance [Ohm]": 12.5
      },
      "sources": {
        "Ds": {"source": "gitt_fitting", "note": "apparent D_s；R 用的是 D50/2"}
      }
    }

``Ds`` 是平台石墨半电池扩散系数的简写（会在内部展开成真正的 pybamm 键）；
其余键必须是参数集里真实存在的名字 —— 写错会 ``KeyError``，不静默。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from battery_sim.simulation.baseline import run_baseline_cell  # noqa: E402
from governance.dataset_roles import (  # noqa: E402
    ROLE_BENCHMARK,
    ROLE_IDENTIFICATION,
    ROLE_PREDICTION,
    ROLE_UNSPECIFIED,
    ROLE_VALIDATION,
    resolve_role,
)
from governance.scale_alignment import ScaleMisalignment  # noqa: E402
from identification.representations import (  # noqa: E402
    DS_KEY,
    SHAPE_NAMES,
    shape_override,
)

#: 目标倍率的比较区间至少要覆盖这么多（否则记失败，不给 RMSE 结论）
COVERAGE_MIN = 0.80

#: 与 governance.scale_alignment.ALIGNMENT_TOLERANCE_DEX 同口径（容量比对数容差）
ALIGNMENT_TOLERANCE_DEX = 0.05

#: 允许被拿来当留出集的角色；identification 明确排除
_ALLOWED_TARGET_ROLES = (ROLE_VALIDATION, ROLE_PREDICTION)

#: 从 metrics 行里挑出来的标量字段（不搬数组，报告只放能引用的数）
_SCALAR_METRICS = (
    "rmse_time_aligned_mV",
    "mae_time_aligned_mV",
    "bias_time_aligned_mV",
    "max_abs_error_mV",
    "coverage_fraction",
    "n_comparison_points",
    "median_current_A",
    "c_rate_measured",
    "Q_exp_integrated_Ah",
    "Q_exp_reported_Ah",
    "simulated_forced_window_charge_Ah",
    "capacity_error_pct",
    "ambient_temperature_C",
    "protocol_id",
    "initial_state_type",
    "initial_state_source",
)


class PredictionProtocolError(RuntimeError):
    """预测链路的**协议**错误（角色/参数来源/覆盖），不是数值错误。"""


# ------------------------------------------------------------------
# 参数覆盖：JSON -> platform overrides
# ------------------------------------------------------------------
@dataclass
class OverrideBundle:
    """一次预测所用的参数覆盖 + 来源。"""

    overrides: Dict[str, Any] = field(default_factory=dict)
    sources: Dict[str, Any] = field(default_factory=dict)
    provenance: str = ""
    warnings: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.overrides


def load_overrides(path: Path | str, parameter_set: str) -> OverrideBundle:
    """读 ``--overrides`` 文件。

    支持的取值形态：

    * 数字 -> 直接做标量覆盖
    * ``{"shape": ..., "amplitude_dex": ...}`` -> 走
      :func:`identification.representations.shape_override`（函数型参数，
      例如 D_s(x)）。**只有这一条路能覆盖函数型参数**，因为 JSON 里放不下
      callable，而"看起来像数字"的覆盖会被 pybamm 当成另一个量。
    * ``Ds`` 作为简写键 -> 展开成参数集里真正的扩散系数键

    来源（``sources`` / ``provenance``）缺失只给警告，不阻断 —— 但报告会把
    "来源缺失"写在结论旁边，因为平台红线是「参数来源必须留」。
    """
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_file():
        raise PredictionProtocolError(f"找不到 overrides 文件：{p}")
    raw = json.loads(p.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise PredictionProtocolError(
            "overrides 文件必须是 JSON 对象；"
            "要么直接是 {参数名: 值}，要么是 {overrides: {...}, sources: {...}}"
        )

    nested = "overrides" in raw
    spec = raw.get("overrides") if nested else raw
    if not isinstance(spec, dict) or not spec:
        raise PredictionProtocolError("overrides 是空的：没有要应用的参数")

    bundle = OverrideBundle(
        sources=dict(raw.get("sources") or {}) if nested else {},
        provenance=str(raw.get("provenance") or ""),
    )

    for key, value in spec.items():
        real_key = DS_KEY if str(key).strip() in ("Ds", "D_s", "DS") else str(key)
        if isinstance(value, dict) and "shape" in value:
            shape = str(value["shape"])
            if shape not in SHAPE_NAMES:
                raise PredictionProtocolError(
                    f"{key}: 未知形状 {shape!r}；允许 {list(SHAPE_NAMES)}"
                )
            amplitude = value.get("amplitude_dex", value.get("amplitude"))
            if amplitude is None:
                raise PredictionProtocolError(
                    f"{key}: 函数型覆盖必须给 amplitude_dex（就是那个 a0）"
                )
            bundle.overrides[real_key] = shape_override(
                parameter_set, shape, float(amplitude),
                name=str(value.get("name") or f"L4_{shape}"),
            )
            bundle.sources.setdefault(real_key, {
                "source": str(value.get("source") or "unspecified"),
                "method": (
                    f"D_s(x,T) = D_ref(x,T) * 10**({float(amplitude):+.4f} * "
                    f"phi_{shape}(x))"
                ),
                "note": str(value.get("note") or ""),
            })
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            bundle.overrides[real_key] = float(value)
            bundle.sources.setdefault(real_key, {
                "source": "unspecified", "note": "标量覆盖",
            })
        else:
            raise PredictionProtocolError(
                f"{key}: 不认识的覆盖形态 {value!r}；"
                "只支持数字与 {shape, amplitude_dex} 两种"
            )

    if not bundle.provenance:
        bundle.warnings.append(
            "overrides 文件没写 provenance：报告里无法说明这套参数是从哪来的"
        )
    for key, src in bundle.sources.items():
        if str((src or {}).get("source", "")).strip() in ("", "unspecified"):
            bundle.warnings.append(
                f"{key}: 来源未写（平台红线要求实验参数留来源）"
            )
    return bundle


# ------------------------------------------------------------------
# 角色门 + 尺度门
# ------------------------------------------------------------------
def role_gate(
    dataset: str,
    rate: Optional[str],
    *,
    roles_config: Optional[Path | str] = None,
    allow_identification_target: bool = False,
    reason: str = "",
) -> Tuple[str, List[str]]:
    """目标数据集能不能当留出集。

    返回 ``(role, warnings)``；不允许就抛 :class:`PredictionProtocolError`。

    * ``identification`` -> 拒绝（拿辨识集当留出集 = 对自己评分）。确实要这样
      做（例如只想知道链路通不通）必须显式 ``allow_identification_target``
      并给理由，那个理由会进报告。
    * ``benchmark`` -> 允许，但记录「参数集非为它标定 ⇒ 不构成验证」。
    * 未声明 -> 允许，但记录「无法证明它不是辨识集」。
    """
    role = resolve_role(dataset, rate, config=roles_config)
    warnings: List[str] = []
    if role == ROLE_IDENTIFICATION:
        if not allow_identification_target:
            raise PredictionProtocolError(
                f"目标数据集 {dataset}/{rate} 的 dataset_role="
                f"'{ROLE_IDENTIFICATION}'：辨识集不能当留出集，"
                f"否则报出来的误差是对自己评分的结果。"
                f"请把留出倍率单独放一个条目并声明为 "
                f"'{ROLE_VALIDATION}' 或 '{ROLE_PREDICTION}'；"
                f"确实只想验链路时显式加 --allow-identification-target 并给理由。"
            )
        warnings.append(
            "目标是辨识集，已由调用方显式豁免："
            + (reason or "（未给理由）")
            + "。这份报告只能说明链路，不能说明预测能力。"
        )
    elif role == ROLE_BENCHMARK:
        warnings.append(
            "目标数据集角色是 benchmark：参数集不是为它标定的，"
            "这个比较不构成验证（surrogate ≠ validation）"
        )
    elif role == ROLE_UNSPECIFIED:
        warnings.append(
            "目标数据集未在 datasets.yaml 里声明 dataset_role："
            "无法证明它不是辨识集，本报告不构成验证"
        )
    elif role not in _ALLOWED_TARGET_ROLES:
        warnings.append(f"目标数据集角色是 '{role}'，按评估处理并记录")
    return role, warnings


def _model_nominal_capacity_Ah(metrics: Dict[str, Any]) -> Optional[float]:
    """从 metrics 反推**模型**的标称容量。

    ``c_rate_measured`` 是平台按参数集标称容量算出来的
    （``median_current / Nominal cell capacity``），所以标称容量可以反解。
    反解而不是另读一次参数集：这样报告的 C-rate 与运行记录用的是同一个数。
    """
    i_med = metrics.get("median_current_A")
    c_rate = metrics.get("c_rate_measured")
    try:
        i_v = float(i_med)
        c_v = float(c_rate)
    except (TypeError, ValueError):
        return None
    if c_v == 0 or not np.isfinite(i_v) or not np.isfinite(c_v):
        return None
    return i_v / c_v


def scale_record(metrics: Dict[str, Any],
                 cell_nominal_Ah: Optional[float] = None) -> Dict[str, Any]:
    """两个 C-rate 并列 + 尺度判定 —— 平台一级概念，任何报告都必须带。

    判据是 **模型标称容量 vs 电芯标称容量**，不是 vs 窗口电荷。
    这个区别是必须写下来的（2026-09-17 在合成倍率梯夹具上踩到）：
    一份只跑 60 % DoD 的 GCD，其窗口电荷**本来就**只有容量的 0.6 倍，
    拿它当分母会把"正常的部分窗口"误判成尺度失配。
    平台真正要挡的是"模型是 202 mAh 的电芯、记录来自 2.16 mAh 的硬币电池"
    （G6 的 31×、G5 的 113×）——那是**电芯容量**层面的错配。

    ``cell_nominal_Ah`` 来自数据集声明（``config.nominal_capacity_Ah``）。
    没声明 -> 尺度**未知**，报告里不许写成 aligned，也不许据此下结论。
    """
    q_exp = float(metrics.get("Q_exp_integrated_Ah") or float("nan"))
    i_med = float(metrics.get("median_current_A") or float("nan"))
    nominal = _model_nominal_capacity_Ah(metrics)
    rec: Dict[str, Any] = {
        "Q_exp_integrated_Ah": q_exp,
        "model_nominal_capacity_Ah": nominal,
        "cell_nominal_capacity_Ah": (
            float(cell_nominal_Ah) if cell_nominal_Ah else None
        ),
        "median_current_A": i_med,
        "c_rate_on_cell": (i_med / q_exp) if q_exp else None,
        "c_rate_on_model_unscaled": (
            float(metrics.get("c_rate_measured"))
            if metrics.get("c_rate_measured") not in (None, "") else None
        ),
        # 窗口只覆盖了模型容量的多少：GCD 的部分窗口是正常的，
        # 但这个数必须报出来，否则"回放只走了 1 % 容量"那种事故看不出来
        "window_charge_fraction_of_model": (
            q_exp / nominal if (nominal and q_exp) else None
        ),
    }
    if nominal and cell_nominal_Ah:
        ratio = nominal / float(cell_nominal_Ah)
        rec["capacity_ratio_model_over_measured"] = ratio
        rec["log10_ratio"] = math.log10(ratio)
        rec["verdict"] = (
            "aligned"
            if abs(math.log10(ratio)) <= ALIGNMENT_TOLERANCE_DEX
            else "misaligned"
        )
        rec["basis"] = "model nominal capacity vs declared cell nominal capacity"
    else:
        rec["capacity_ratio_model_over_measured"] = None
        rec["log10_ratio"] = None
        rec["verdict"] = "unknown"
        rec["basis"] = (
            "数据集未声明标称容量 -> 尺度未判定"
            "（窗口电荷不能代替电芯容量：部分窗口的 GCD 天然小于容量）"
        )
    return rec


# ------------------------------------------------------------------
# 单次回放 + 编排
# ------------------------------------------------------------------
def _initial_offset_mV(output_dir: Path, rate: str) -> Optional[float]:
    """回放起点与记录起点差多少（mV）。

    这是一条**接线**检查，不是模型检查。半电池回放必须从实测静置 OCV
    反演出的初值出发（``df.attrs['initialisation']``）；一旦那个块没带上，
    仿真会从参数集默认初值启动，整个 RMSE 被初值差吃掉 ——
    看上去像"模型差 60 mV"，其实是初值没接上（2026-09-17 在本平台的
    合成倍率梯夹具上实测到：记录 0.745 V vs 仿真 1.453 V）。
    """
    files = sorted(Path(output_dir).glob("*_time_aligned.csv"))
    if not files:
        return None
    df = pd.read_csv(files[0])
    for exp_col, sim_col in (("voltage_exp_V", "voltage_sim_V"),
                             ("V_exp", "V_sim")):
        if exp_col in df.columns and sim_col in df.columns:
            if len(df) == 0:
                return None
            off = (float(df[sim_col].iloc[0]) - float(df[exp_col].iloc[0]))
            return off * 1000.0
    return None


def _run_one(
    adapter,
    *,
    cell: str,
    rate: str,
    model_name: str,
    parameter_set: Optional[str],
    overrides: Optional[Dict[str, Any]],
    sources: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    res = run_baseline_cell(
        adapter,
        model_name,
        cell,
        rate=rate,
        parameter_set=parameter_set,
        plot=False,
        quiet=True,
        parameter_overrides=overrides or None,
        parameter_override_sources=sources or None,
    )
    row = res["metrics"].iloc[0].to_dict()
    out_dir = Path(res["output_dir"])
    return {
        "metrics": {k: row.get(k) for k in _SCALAR_METRICS},
        "output_dir": str(out_dir),
        "runtime_s": float(res.get("runtime_s") or float("nan")),
        "applied_overrides": res.get("parameter_overrides_applied"),
        "initial_offset_mV": _initial_offset_mV(out_dir, rate),
    }


def rate_prediction(
    fit_adapter,
    target_adapter,
    *,
    cell: str,
    fit_rate: str,
    target_rate: str,
    model_name: str = "SPM",
    parameter_set: Optional[str] = None,
    bundle: Optional[OverrideBundle] = None,
    alignment: str = "check",
    roles_config: Optional[Path | str] = None,
    allow_identification_target: bool = False,
    reason: str = "",
    coverage_min: float = COVERAGE_MIN,
    fit_dataset: Optional[str] = None,
    target_dataset: Optional[str] = None,
) -> Dict[str, Any]:
    """跑一次 L4 倍率预测验收，返回可 JSON 化的记录。

    ``alignment``：``check``（默认，尺度不对齐就抛 ``ScaleMisalignment``，
    与 ``run_protocol_replay`` 的默认语义一致）/ ``assume``（继续，但把豁免
    写进记录）。这里没有 ``align``：GCD 回放路径不吃 footprint 配方，
    真正的修法是换一个几何/容量匹配的参数集，不能在这里偷偷缩放。
    """
    if alignment not in ("check", "assume"):
        raise PredictionProtocolError(
            f"alignment 只能是 check / assume；收到 {alignment!r}"
            "（align 不在此路径：见模块 docstring）"
        )
    fit_ds = fit_dataset or str(fit_adapter.config.dataset_id)
    tgt_ds = target_dataset or str(target_adapter.config.dataset_id)
    ps = parameter_set or str(target_adapter.config.parameter_set)

    warnings: List[str] = []
    failures: List[str] = []

    role, role_warnings = role_gate(
        tgt_ds, target_rate, roles_config=roles_config,
        allow_identification_target=allow_identification_target, reason=reason,
    )
    warnings.extend(role_warnings)

    bundle = bundle or OverrideBundle()
    if bundle.is_empty():
        raise PredictionProtocolError(
            "没有参数覆盖：L4 的前提是「用辨识出来的参数去预测」。"
            "空覆盖等于零拟合回放，那是 baseline 的活，不是这个脚本的活"
        )
    warnings.extend(bundle.warnings)

    # 辨识侧：跑一遍同参数的同倍率（in-sample），只作为对照
    fit_run = _run_one(
        fit_adapter, cell=cell, rate=fit_rate, model_name=model_name,
        parameter_set=ps, overrides=bundle.overrides, sources=bundle.sources,
    )
    # 目标侧：**留出倍率**，同一套参数，不回改
    target_run = _run_one(
        target_adapter, cell=cell, rate=target_rate, model_name=model_name,
        parameter_set=ps, overrides=bundle.overrides, sources=bundle.sources,
    )

    scale = scale_record(
        target_run["metrics"],
        cell_nominal_Ah=getattr(
            target_adapter.config, "nominal_capacity_Ah", None
        ),
    )
    if scale["verdict"] == "unknown":
        warnings.append(
            "尺度**未判定**：数据集没有声明标称容量（"
            "`config.nominal_capacity_Ah`），因此无法比较模型容量与电芯容量。"
            "窗口电荷不能代替电芯容量 —— 部分窗口的 GCD 天然小于满容量。"
            "在这个数补齐之前，报告里的 C-rate 只有 `c_rate_on_model_unscaled` "
            "可用，且不能声称尺度已对齐"
        )
    elif scale["verdict"] == "misaligned":
        msg = (
            f"模型与记录不在同一尺度：模型标称容量 "
            f"{scale['model_nominal_capacity_Ah']:.6g} Ah vs 电芯声明容量 "
            f"{scale['cell_nominal_capacity_Ah']:.6g} Ah（比 "
            f"{scale['capacity_ratio_model_over_measured']:.1f}×，"
            f"{scale['log10_ratio']:+.3f} dex，容差 ±"
            f"{ALIGNMENT_TOLERANCE_DEX} dex）。此时名义 C/"
            f"{1.0 / (scale['c_rate_on_cell'] or float('nan')):.0f} 的协议在模型上"
            f"实际是 C/"
            f"{1.0 / (scale['c_rate_on_model_unscaled'] or float('nan')):.0f} 量级，"
            f"固相扩散可能根本没被激发 —— 这个 RMSE 主要反映尺度失配。"
            f"修法是几何/容量匹配的参数集，不是在回放里缩电流。"
        )
        warnings.append(msg)
        if alignment == "check":
            failures.append("scale_misaligned")

    cov = target_run["metrics"].get("coverage_fraction")
    try:
        cov_v = float(cov)
    except (TypeError, ValueError):
        cov_v = float("nan")
    if not np.isfinite(cov_v) or cov_v < coverage_min:
        failures.append("insufficient_coverage")
        warnings.append(
            f"目标倍率的比较区间只覆盖了 {cov_v:.1%}（要求 ≥"
            f"{coverage_min:.0%}）：仿真在记录结束前就到了截止电压。"
            f"按要求这记失败，不给 RMSE 结论（在残片上打分会让错参数看起来很好）"
        )

    # 初值接线检查（不是模型检查）：半电池回放必须从实测静置 OCV 反演出的
    # 初值出发。缺了那个块，仿真从参数集默认初值启动，RMSE 里混进一个
    # 纯几何的电压偏移 —— 那是最容易被误读成"模型误差"的一类接线故障。
    initial_tol_mV = 30.0
    init_off = target_run.get("initial_offset_mV")
    if init_off is None:
        warnings.append(
            "读不到 time_aligned 比较表，无法核对回放起点与记录起点"
            "（初值是否带上就没法证明）"
        )
    elif abs(float(init_off)) > initial_tol_mV:
        failures.append("initial_state_wiring")
        warnings.append(
            f"回放起点与记录起点差 {float(init_off):+.1f} mV"
            f"（容差 ±{initial_tol_mV:g} mV）：这不是模型误差，是初值没带上。"
            f"半电池的初值只能由实测静置 OCV 反演（attrs['initialisation']）；"
            f"请检查 adapter 的 load_processed_discharge 是否挂了那个块 —— "
            f"挂上之前，这个 RMSE 不能引用"
        )

    record = {
        "kind": "L4_rate_prediction",
        "fit": {
            "dataset": fit_ds, "rate": fit_rate, "cell": cell,
            "role": resolve_role(fit_ds, fit_rate, config=roles_config),
            "metrics": fit_run["metrics"], "output_dir": fit_run["output_dir"],
            "initial_offset_mV": fit_run.get("initial_offset_mV"),
            "note": "in-sample：这套参数就是从这一侧来的，其 RMSE 不是预测误差",
        },
        "target": {
            "dataset": tgt_ds, "rate": target_rate, "cell": cell,
            "role": role, "metrics": target_run["metrics"],
            "output_dir": target_run["output_dir"],
            "applied_overrides": target_run["applied_overrides"],
            "initial_offset_mV": target_run.get("initial_offset_mV"),
        },
        "overrides": {
            "provenance": bundle.provenance,
            "sources": bundle.sources,
            "keys": sorted(bundle.overrides),
        },
        "scale": scale,
        "alignment_mode": alignment,
        "coverage_min": coverage_min,
        "model_name": model_name,
        "parameter_set": ps,
        "warnings": warnings,
        "failures": failures,
        "link_ok": not failures,
    }
    return record


# ------------------------------------------------------------------
# 报告
# ------------------------------------------------------------------
def _f(value, fmt="{:.2f}", dash="n/a") -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return dash
    if not np.isfinite(v):
        return dash
    return fmt.format(v)


def render_report(record: Dict[str, Any]) -> str:
    """把记录排成人能读、能直接贴进论文草稿的 markdown。

    措辞按平台红线写死在模板里：**倍率外推 ≠ 独立样品验证**、
    **拟合好 ≠ 参数对**、**surrogate ≠ validation**。
    """
    fit, tgt = record["fit"], record["target"]
    scale = record["scale"]
    fm, tm = fit["metrics"], tgt["metrics"]
    lines: List[str] = []

    verdict = "PASS" if record["link_ok"] else "FAIL"
    lines.append(f"# L4 倍率预测验收 — {tgt['dataset']}")
    lines.append("")
    lines.append(
        f"**链路判定：{verdict}**"
        f"（{tgt['dataset']}/{tgt['rate']} 用 "
        f"{fit['dataset']}/{fit['rate']} 辨识的参数预测）"
    )
    lines.append("")
    lines.append("## 一句话结论")
    lines.append("")
    if record["link_ok"]:
        lines.append(
            f"模型在**未参与辨识的倍率** {tgt['rate']} 上，与实测电压的 "
            f"RMSE = **{_f(tm.get('rmse_time_aligned_mV'))} mV**"
            f"（覆盖 {_f(tm.get('coverage_fraction'), '{:.1%}')}，"
            f"{int(tm.get('n_comparison_points') or 0)} 个比较点）。"
            f"这只说明链路可跑、参数可迁移到该倍率，"
            f"**不等于**这套参数是物理正确的（见下面「口径」）。"
        )
    else:
        for f in record["failures"]:
            lines.append(f"- 失败项 `{f}`")
    lines.append("")
    lines.append("## 输入")
    lines.append("")
    lines.append(f"- 辨识侧：`{fit['dataset']}` / 倍率 `{fit['rate']}`"
                 f"（role = `{fit['role']}`）—— in-sample 对照")
    lines.append(f"- 目标侧：`{tgt['dataset']}` / 倍率 `{tgt['rate']}`"
                 f"（role = `{tgt['role']}`）—— 留出集")
    lines.append(f"- 模型：`{record['model_name']}`，参数集 `{record['parameter_set']}`")
    lines.append(f"- 参数覆盖：{', '.join(record['overrides']['keys']) or '（空）'}")
    if record["overrides"]["provenance"]:
        lines.append(f"- 参数来源：{record['overrides']['provenance']}")
    lines.append("")
    lines.append("## 结果")
    lines.append("")
    lines.append("| 量 | 辨识倍率（in-sample） | 留出倍率（预测） |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| 倍率 | `{fit['rate']}` | `{tgt['rate']}` |")
    lines.append(
        "| RMSE / mV | {a} | **{b}** |".format(
            a=_f(fm.get("rmse_time_aligned_mV")), b=_f(tm.get("rmse_time_aligned_mV"))
        )
    )
    lines.append(
        "| MAE / mV | {a} | {b} |".format(
            a=_f(fm.get("mae_time_aligned_mV")), b=_f(tm.get("mae_time_aligned_mV"))
        )
    )
    lines.append(
        "| bias / mV | {a} | {b} |".format(
            a=_f(fm.get("bias_time_aligned_mV")), b=_f(tm.get("bias_time_aligned_mV"))
        )
    )
    lines.append(
        "| 最大偏差 / mV | {a} | {b} |".format(
            a=_f(fm.get("max_abs_error_mV")), b=_f(tm.get("max_abs_error_mV"))
        )
    )
    lines.append(
        "| 覆盖 | {a} | {b} |".format(
            a=_f(fm.get("coverage_fraction"), "{:.1%}"),
            b=_f(tm.get("coverage_fraction"), "{:.1%}"),
        )
    )
    lines.append(
        "| 回放起点偏移 / mV | {a} | {b} |".format(
            a=_f(fit.get("initial_offset_mV"), "{:+.1f}"),
            b=_f(tgt.get("initial_offset_mV"), "{:+.1f}"),
        )
    )
    lines.append("")
    lines.append(
        "「回放起点偏移」是**接线**检查：半电池回放必须从实测静置 OCV 反演"
        "出的初值出发。若这个数很大，先修初值再接结论 —— "
        "否则量到的是初值差，不是模型误差。"
    )
    lines.append("")
    lines.append("### 两个 C-rate 必须并列")
    lines.append("")
    lines.append(
        f"- `c_rate_on_cell` = **{_f(scale['c_rate_on_cell'], '{:.4f}')}**"
        f"（由记录的 max/median 电流与实测扫程电荷算出）"
    )
    lines.append(
        f"- `c_rate_on_model_unscaled` = "
        f"**{_f(scale['c_rate_on_model_unscaled'], '{:.4f}')}**"
        f"（按参数集标称容量算出）"
    )
    lines.append(
        f"- 模型标称容量 {_f(scale['model_nominal_capacity_Ah'] * 1e3 if scale['model_nominal_capacity_Ah'] else None, '{:.3f}')} mAh"
        f" vs 电芯声明容量 "
        f"{_f(scale['cell_nominal_capacity_Ah'] * 1e3 if scale['cell_nominal_capacity_Ah'] else None, '{:.3f}')} mAh"
        f" ⇒ 比值 "
        f"{_f(scale['capacity_ratio_model_over_measured'], '{:.2f}')}×，"
        f"判定 `{scale['verdict']}`（容差 ±{ALIGNMENT_TOLERANCE_DEX} dex）"
    )
    lines.append(
        f"- 本次窗口只走了模型容量的 "
        f"{_f(scale['window_charge_fraction_of_model'], '{:.1%}')}"
        f"（部分窗口的 GCD 天然小于满容量，这个数是**信息**不是判据）"
    )
    lines.append(
        "- **只有第二个数决定固相扩散是否被激发。**只报第一个数是"
        "「C/10 变成 C/309」那次事故的写法。"
    )
    lines.append("")
    if record["warnings"]:
        lines.append("## 必须一起引用的警告")
        lines.append("")
        for w in record["warnings"]:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("## 口径（写死在渲染器里，避免被略过）")
    lines.append("")
    lines.append(
        "1. **这是倍率外推，不是独立样品验证。** 同一样品的两个倍率是同一次"
        "实验的两段；跨样品泛化要靠平行样品（设计里每组 ≥3 颗）另行检验。"
    )
    lines.append(
        "2. **拟合好 ≠ 参数对 ≠ 物理可迁移。** G5.2 已实测：在错误的模型"
        "假设下，真值**不是**最优解（偏 −25 % 的参数拟合反而好 3.4×）。"
        "所以「预测误差小」只说明这套参数在这个倍率上自洽。"
    )
    lines.append(
        "3. **被判定的角色是声明出来的，不是证明出来的。** 本报告只证明"
        "「没有把目标倍率用于辨识」这件事被代码拦过（governance.dataset_roles）。"
    )
    if tgt["role"] == ROLE_BENCHMARK:
        lines.append(
            "4. 目标数据集角色是 `benchmark`：参数集**不是**为它标定的，"
            "所以这个比较**不构成验证**（surrogate ≠ validation）。"
        )
    elif tgt["role"] == ROLE_UNSPECIFIED:
        lines.append(
            "4. 目标数据集**未声明角色**：无法证明它不是辨识集，"
            "本报告不构成验证。"
        )
    lines.append("")
    lines.append("## 运行产物")
    lines.append("")
    lines.append(f"- 辨识侧：`{fit['output_dir']}`")
    lines.append(f"- 目标侧：`{tgt['output_dir']}`")
    lines.append(
        "- 两者的 `run_metadata.json` 里 `parameter_overrides_applied` 是"
        "**实际生效**的覆盖（与请求分开记录，见 baseline 的 v0.7 契约）。"
    )
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def _build_adapter(dataset: str, root: Optional[str], rate: str):
    """取 adapter：``--fit-root/--target-root`` 优先（未注册的数据/夹具），
    否则按 ``configs/datasets.yaml`` 里的 dataset_id 走注册表。"""
    if root:
        from types import SimpleNamespace

        from battery_sim.datasets.recycled_graphite import (
            RecycledGraphiteAdapter,
        )

        cfg = SimpleNamespace(
            dataset_id=dataset,
            name=dataset,
            chemistry="graphite",
            ion="Li",
            raw_dir=root,
            processed_dir=f"{root}/processed",
            parameter_set="Ecker2015_graphite_halfcell",
            extra={
                "source": f"UNREGISTERED ROOT: {root}",
                "cell_configuration": "half_cell",
                "working_electrode": "positive",
                "physical_working_electrode": "graphite_negative",
                "counter_electrode": "lithium_metal",
                "model_options": {},
            },
            cells=[],
            rates=[rate],
            nominal_capacity_Ah=None,
            lower_voltage_cutoff_V=None,
            upper_voltage_cutoff_V=None,
        )
        return RecycledGraphiteAdapter(config=cfg)

    from battery_sim.registry import get_dataset

    return get_dataset(dataset)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="L4 倍率预测验收")
    ap.add_argument("--fit-dataset", required=True)
    ap.add_argument("--fit-rate", required=True)
    ap.add_argument("--target-dataset", required=True)
    ap.add_argument("--target-rate", required=True)
    ap.add_argument("--cell", default="", help="样品/电芯 id（默认取第一个）")
    ap.add_argument("--overrides", required=True, help="参数覆盖 JSON")
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--parameter-set", default=None)
    ap.add_argument("--alignment", default="check", choices=("check", "assume"))
    ap.add_argument("--roles-config", default=None,
                    help="角色声明用的 datasets.yaml（默认 configs/datasets.yaml）")
    ap.add_argument("--allow-identification-target", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--coverage-min", type=float, default=COVERAGE_MIN)
    ap.add_argument("--fit-root", default=None,
                    help="未注册数据的根目录（夹具/临时数据）")
    ap.add_argument("--target-root", default=None)
    ap.add_argument("--fit-nominal-capacity-Ah", type=float, default=None,
                    help="电芯标称容量（未注册数据用；没有它就判不了尺度）")
    ap.add_argument("--target-nominal-capacity-Ah", type=float, default=None)
    ap.add_argument("--out", default=None, help="报告 markdown 路径")
    ap.add_argument("--json", default=None, help="记录 JSON 路径")
    args = ap.parse_args(argv)

    fit_adapter = _build_adapter(args.fit_dataset, args.fit_root, args.fit_rate)
    tgt_adapter = _build_adapter(
        args.target_dataset, args.target_root, args.target_rate
    )
    # 尺度判定要的是**电芯**容量。注册数据集从 configs 里读；未注册的
    # （夹具/临时数据）只能由调用方显式给 —— 给不出就判"未知"，不许猜。
    if args.fit_nominal_capacity_Ah is not None:
        fit_adapter.config.nominal_capacity_Ah = float(
            args.fit_nominal_capacity_Ah
        )
    if args.target_nominal_capacity_Ah is not None:
        tgt_adapter.config.nominal_capacity_Ah = float(
            args.target_nominal_capacity_Ah
        )
    cell = args.cell or (
        str((fit_adapter.list_cells() or ["cell0"])[0])
    )
    ps = args.parameter_set or str(tgt_adapter.config.parameter_set)
    bundle = load_overrides(args.overrides, ps)

    try:
        record = rate_prediction(
            fit_adapter, tgt_adapter, cell=cell,
            fit_rate=args.fit_rate, target_rate=args.target_rate,
            model_name=args.model, parameter_set=ps, bundle=bundle,
            alignment=args.alignment, roles_config=args.roles_config,
            allow_identification_target=args.allow_identification_target,
            reason=args.reason, coverage_min=args.coverage_min,
        )
    except ScaleMisalignment as exc:
        print(f"[FAIL 尺度对齐] {exc}", file=sys.stderr)
        return 3

    report = render_report(record)
    out_path = (ROOT / args.out) if args.out else (
        ROOT / "outputs" / "analysis" / "l4" /
        f"{args.target_dataset}_{args.fit_rate}_to_{args.target_rate}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8", newline="")
    print(f"报告：{out_path.relative_to(ROOT)}")

    if args.json:
        jp = ROOT / args.json
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8", newline="",
        )
        print(f"记录：{jp.relative_to(ROOT)}")

    tm = record["target"]["metrics"]
    print(
        f"目标倍率 {args.target_rate}: RMSE "
        f"{_f(tm.get('rmse_time_aligned_mV'))} mV, "
        f"覆盖 {_f(tm.get('coverage_fraction'), '{:.1%}')}"
    )
    print(f"链路判定：{'PASS' if record['link_ok'] else 'FAIL'}")
    return 0 if record["link_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
