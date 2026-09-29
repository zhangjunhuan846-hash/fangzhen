# ============================================================
# 静置电压噪声底 sigma_noise —— 标定 + 判据接线（缺口 2）
#
# 为什么它是缺口而不是"一个数字"（annex B §A3）
#
#   预注册的负对照 **N1** 是"零激励窗口代价面**精确平坦**"。
#   "精确"这个词必须有量纲：没有 sigma_noise，N1 是**空的判据** ——
#   平坦到多少算平坦？同一句还决定"静置是否够长"（静置判据
#   dV/dt < 1 mV/h 是不是已经落到噪声里了，看不出来）。
#
#   它必须用**空跑**测（Step 0：不装样、或装一颗不工作的电芯，
#   静置 30 min，记电压序列）。这一步**不依赖任何样品、任何设备到货**。
#
# 三个容易做错的地方（都已在实现里处理）
#
#   1. **不能对原始序列直接取 std。**  静置时电压有残余漂移，
#      std 会把漂移算成噪声，系统性高估。做法：先把序列**去线性趋势**
#      （最小二乘），对残差取稳健尺度估计。
#   2. **要用稳健估计，不用 std。**  偶发跳点（接触不良、采样毛刺）
#      会让 std 膨胀。默认中位绝对偏差 MAD：sigma = 1.4826 * median(|r - median(r)|)。
#      1.4826 是正态下的相合常数 —— **这个常数写在代码里，不是隐藏的**。
#   3. **分辨率下限。**  sigma_noise 不会小于仪器分辨率/√12（均匀量化误差）。
#      若估出的值低于它，报出来的是分辨率而不是噪声 —— 必须显式标出来，
#      否则 N1 会被一个"看起来很小"的分辨率满足掉。
#
# 与既有机制的关系
#   · 产出写进 run_record.yaml 的 `sigma_noise_mV`（本模块不写文件，只算）。
#   · 判据用 `calibrated_threshold_mV(k)` 取 max|dV| 的上限，
#     并与 sign convention 一起交给调用方（本模块不做物理模拟）。
#   · **不改冻结内核**：这是一个独立的测量与判据工具。
# ============================================================

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np

#: 正态下 MAD → sigma 的相合常数。声明出来，因为它进了所有下游判据。
MAD_TO_SIGMA = 1.4826

#: 预注册 annex B §A3 要求的空跑时长（秒）。30 min。
DEFAULT_REST_WINDOW_S = 1800.0

#: 最少点数。少于这个数无法把漂移与噪声分开（拟合 2 个参数至少要 3 点，
#: 但 3 点的残差几乎没有自由度 —— 取 30 作为"能给出一位小数"的下限）。
MIN_POINTS = 30

#: 平台默认电压量程下限（V）。用于把"分辨率未知"时的均匀量化误差
#: 与电压水平挂钩；显式声明，不藏在公式里。
DEFAULT_VOLTAGE_RANGE_V = 5.0

#: ⚠️ ``k`` **不是**本模块的默认值，它是**预注册量**（annex B §A3 要求"判据写成
#: max|ΔV| ≤ k·σ_noise 并给出 k"）。这里只放一个**示例值**，
#: 且任何用到它的渲染/阈值函数都必须在输出里标注"这是示例、尚未预注册"。
#: 理由与 ``settings_hash`` 的缺失字段同源：**一个看起来像决定的默认值，
#: 比没有默认值更危险** —— 报告读起来像"我们定了 k=3"，而其实没人定过。
EXAMPLE_K = 3.0

#: 预注册 ``k`` 的存放位置约定（相对项目根）。空白跑标定与 ``k`` 分两个文件，
#: 因为两者的**时间顺序**是固定的：先定 k（预注册），再拿空跑数据算 sigma。
K_PREREGISTRATION_RELPATH = "configs/noise_floor_prereg.yaml"


class NoiseFloorUnavailable(RuntimeError):
    """空跑记录不足以标定噪声底。"""


class KNotPreregistered(RuntimeError):
    """在需要**已预注册**的 ``k`` 的场合，拿到的是示例值或空值。

    判据在预注册体系里必须**先定 k、后看数据**；用示例值冒充后果是
    判据阈值随示例值漂移，而报告上看不出来。
    """


@dataclass(frozen=True)
class NoiseFloor:
    """一次空跑标定的结果。所有字段都进 run_record。"""

    sigma_mV: float
    n_points: int
    window_s: float
    drift_mV_per_h: float
    residual_max_abs_mV: float
    estimator: str
    resolution_floor_mV: Optional[float]
    resolution_limited: bool
    notes: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sigma_noise_mV": self.sigma_mV,
            "n_points": self.n_points,
            "rest_window_s": self.window_s,
            "drift_mV_per_h": self.drift_mV_per_h,
            "residual_max_abs_mV": self.residual_max_abs_mV,
            "estimator": self.estimator,
            "resolution_floor_mV": self.resolution_floor_mV,
            "resolution_limited": self.resolution_limited,
            "notes": self.notes,
        }

    def calibrated_threshold_mV(self, k: Optional[float]) -> Dict[str, Any]:
        """判据阈值 max|ΔV| <= k * sigma_noise。

        返回口径说明 —— 判据离开 k 与 sigma 是没法读的，所以三者一起给。

        ``k`` 语义（**不要**让调用方省掉它）：
          * ``float`` —— 已预注册的 k。只有当它确实来自预注册文件时才传具体值。
          * ``None``  —— 尚未预注册。**不抛错**，但返回里带
            ``is_preregistered=False`` + ``example_k``，且 ``statement`` 明写
            "这是示例、判据尚未成立"。调用方必须把这个标记一路带到报告里。

        ⚠️ 与 ``settings_hash`` 的修复同源：缺一个决定时**不许静默套默认值**，
        要么抛错、要么显式标记。这里选"标记"，因为标定 σ 与预注册 k 是
        两件独立的事，不该因为 k 还没定就挡住 σ 的产出。
        """
        if k is None:
            example = float(EXAMPLE_K)
            return {
                "threshold_mV": example * self.sigma_mV,
                "k": None,
                "example_k": example,
                "is_preregistered": False,
                "sigma_mV": self.sigma_mV,
                "statement": (
                    f"⚠️ **k 尚未预注册** —— 下表按示例 k={example:g} 计算，"
                    f"**判据尚未成立**："
                    f"max|ΔV| <= {example:g} x sigma_noise = "
                    f"{example * self.sigma_mV:.3f} mV"
                    f"（sigma_noise = {self.sigma_mV:.3f} mV，"
                    f"由 {self.n_points} 点 / {self.window_s:.0f} s 空跑标定，"
                    f"估计量 {self.estimator}）。"
                    f"预注册写入 {K_PREREGISTRATION_RELPATH} 后方可引用此阈值。"
                ),
                "resolution_limited": self.resolution_limited,
            }
        if k <= 0:
            raise ValueError(f"k 必须为正，得到 {k}")
        return {
            "threshold_mV": k * self.sigma_mV,
            "k": float(k),
            "example_k": float(EXAMPLE_K),
            "is_preregistered": True,
            "sigma_mV": self.sigma_mV,
            "statement": (
                f"max|ΔV| <= {k:g} x sigma_noise = {k * self.sigma_mV:.3f} mV"
                f"（sigma_noise = {self.sigma_mV:.3f} mV，"
                f"由 {self.n_points} 点 / {self.window_s:.0f} s 空跑标定，"
                f"估计量 {self.estimator}）"
            ),
            "resolution_limited": self.resolution_limited,
        }


def calibrate_noise_floor(
    t_s: Sequence[float],
    v_V: Sequence[float],
    *,
    rest_window_s: float = DEFAULT_REST_WINDOW_S,
    voltage_range_V: Optional[float] = DEFAULT_VOLTAGE_RANGE_V,
    estimator: str = "mad",
    detrend: bool = True,
) -> NoiseFloor:
    """从一段静置记录标定 sigma_noise（单位 mV）。

    参数
    ----
    t_s, v_V
        空跑静置段的原始时间（s）与电压（V）。**必须是原始采样**，
        不要在调用前自行平滑 —— 平滑会把噪声一起抹掉。
    rest_window_s
        只保留**最后**这段时间窗（默认 1800 s = 30 min）。
        取最后一段的理由：静置初期还有松弛，那不是"噪声"。
    voltage_range_V
        仪器量程，用于算分辨率下限（均匀量化误差 = range / 2^n，
        未知 n 时用 range/1e6 作为常见 24-bit 的保守代理）；
        给 ``None`` 则跳过分辨率检查。
    estimator
        ``"mad"``（默认，稳健）或 ``"std"``。**std 只用于对照**：
        两个都算出来并列报，是判断"有没有跳点"的最快方式。
    detrend
        是否去线性趋势（默认 True）。**不要关掉**，除非你确认
        这段静置的漂移确实可忽略 —— 关掉它 std 会把漂移算成噪声。
    """
    t = np.asarray(t_s, dtype=float)
    v = np.asarray(v_V, dtype=float)
    if t.size != v.size:
        raise ValueError(
            f"时间与电压长度不一致：{t.size} vs {v.size}"
        )
    if t.size < 2:
        raise NoiseFloorUnavailable(
            f"空跑记录只有 {t.size} 点，无法标定（至少 {MIN_POINTS} 点）"
        )

    order = np.argsort(t)
    t, v = t[order], v[order]

    # ---- 取最后 rest_window_s ----
    t_end = float(t[-1])
    window_s = min(float(rest_window_s), t_end - float(t[0]))
    if window_s <= 0:
        raise NoiseFloorUnavailable(
            f"可用时间跨度 {t_end - float(t[0]):.3g} s 非正（时间列不是递增？）"
        )
    mask = t >= (t_end - window_s)
    t_w, v_w = t[mask], v[mask]
    if t_w.size < MIN_POINTS:
        raise NoiseFloorUnavailable(
            f"最后 {window_s:.0f} s 内只有 {t_w.size} 点，少于下限 "
            f"{MIN_POINTS}；空跑要么更长，要么采样更密"
        )

    v_mV = v_w * 1000.0

    # ---- 去线性趋势（漂移与噪声必须分开） ----
    if detrend:
        x = t_w - t_w.mean()
        slope, intercept = np.polyfit(x, v_mV, 1)
        resid = v_mV - (slope * x + intercept)
        drift_mV_per_h = float(slope) * 3600.0
    else:
        resid = v_mV - v_mV.mean()
        drift_mV_per_h = float("nan")

    # ---- 稳健尺度 ----
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med)))
    sigma_mad = MAD_TO_SIGMA * mad
    sigma_std = float(np.std(resid, ddof=1))

    key = str(estimator).strip().lower()
    if key == "mad":
        sigma = sigma_mad
        used = f"MAD x {MAD_TO_SIGMA}（稳健）；std 对照 = {sigma_std:.4f} mV"
    elif key == "std":
        sigma = sigma_std
        used = f"std(ddof=1)（仅对照用）；MAD 估计 = {sigma_mad:.4f} mV"
    else:
        raise ValueError(f"estimator 只能是 'mad' 或 'std'，得到 {estimator!r}")

    # ---- 分辨率下限（均匀量化误差 = q/sqrt(12)） ----
    resolution_floor_mV: Optional[float] = None
    resolution_limited = False
    if voltage_range_V is not None and voltage_range_V > 0:
        # 常见 24-bit ADC 的 LSB；这是一个**声明出来的保守代理**，
        # 有实测分辨率时调用方应自行覆盖 voltage_range_V。
        lsb_V = float(voltage_range_V) / (2 ** 24)
        resolution_floor_mV = lsb_V / math.sqrt(12.0) * 1000.0
        resolution_limited = sigma < resolution_floor_mV
    elif voltage_range_V is not None:
        raise ValueError(f"voltage_range_V 必须为正，得到 {voltage_range_V}")

    notes_parts = [
        f"估计量：{used}",
        "去线性趋势：%s" % ("是" if detrend else "否（漂移会被算进噪声）"),
    ]
    if detrend and abs(drift_mV_per_h) > 0.5 * sigma:
        notes_parts.append(
            f"漂移 {drift_mV_per_h:+.3f} mV/h 与噪声同量级 —— "
            f"检查静置是否足够长（预注册的 dV/dt < 1 mV/h 判据在这里兑现）"
        )
    if resolution_limited:
        notes_parts.append(
            f"**受分辨率限制**：估出的 {sigma:.4f} mV 低于分辨率下限 "
            f"{resolution_floor_mV:.4f} mV ⇒ 报出的是**仪器分辨率**，不是噪声。"
            f"N1 判据会被这个值满足掉，必须显式声明。"
        )

    return NoiseFloor(
        sigma_mV=float(sigma),
        n_points=int(t_w.size),
        window_s=float(window_s),
        drift_mV_per_h=drift_mV_per_h,
        residual_max_abs_mV=float(np.max(np.abs(resid - med))),
        estimator=f"mad(detrended)" if (key == "mad" and detrend)
        else (key + ("(detrended)" if detrend else "")),
        resolution_floor_mV=resolution_floor_mV,
        resolution_limited=bool(resolution_limited),
        notes="；".join(notes_parts) + "。",
    )


def render_noise_floor_report(
    floor: NoiseFloor, *, k: Optional[float] = None
) -> str:
    """写进方案 / run_record 的那几行（N1 判据的输入）。

    ``k=None``（默认）表示**尚未预注册** —— 报告里会出现显式警示，
    不会静默按示例值渲染成一个像已定的判据。
    """
    thr = floor.calibrated_threshold_mV(k)
    lines = [
        "## sigma_noise 标定（空跑静置）",
        "",
        f"- sigma_noise = **{floor.sigma_mV:.4f} mV**",
        f"- 记录：{floor.n_points} 点 / {floor.window_s:.0f} s，"
        f"去趋势后残差 max|r - med| = {floor.residual_max_abs_mV:.4f} mV",
        f"- 残余漂移：{floor.drift_mV_per_h:+.4f} mV/h",
    ]
    if not thr["is_preregistered"]:
        lines.append(
            f"- ⚠️ **k 未预注册**（示例 k={thr['example_k']:g}）—— "
            f"下方阈值**不是判据**，只是占位。先写 `{K_PREREGISTRATION_RELPATH}`。"
        )
    lines.append(f"- N1 判据：{thr['statement']}")
    if floor.resolution_limited:
        lines.append(
            f"- ⚠️ **受分辨率限制**（下限 {floor.resolution_floor_mV:.4f} mV）"
            "—— 这个 sigma 反映的是仪器分辨率，N1 的结论必须一起引用这条。"
        )
    lines.append(f"- 注：{floor.notes}")
    return "\n".join(lines)


def load_preregistered_k(path: Any = None) -> Optional[float]:
    """读预注册的 ``k``。没有文件或字段缺失 ⇒ 返回 ``None``（**不猜**）。

    刻意不设默认值：``k`` 是预注册量，本模块无权替使用者决定。
    """
    from pathlib import Path as _Path

    import yaml

    p = _Path(path) if path is not None else _Path(K_PREREGISTRATION_RELPATH)
    if not p.is_file():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    value = data.get("k")
    if value is None:
        return None
    value = float(value)
    if value <= 0:
        raise ValueError(f"{p} 里的 k 必须为正，得到 {value}")
    return value


def render_preregistration_template(k: Optional[float] = None) -> str:
    """生成 ``configs/noise_floor_prereg.yaml`` 的模板（含填写说明）。"""
    k_line = "k: null" if k is None else f"k: {k}"
    return "\n".join(
        [
            "# σ_noise 判据的预注册量（annex B §A3）",
            "#",
            "# 为什么单独一个文件：判据必须先定 k、后用空跑数据算 sigma。",
            "# 顺序颠倒（先看 sigma 再挑 k）会让判据退化成'事后拟合'。",
            "#",
            "# k 怎么选（写下来，不要只填数字）：",
            "#   k 是'多少倍噪声算不显著'。k=3 是常见起点（正态下约 99.7%），",
            "#   但对 n 点极值统计，max|ΔV| 的期望本身随 n 增长，",
            "#   所以 k 应随窗口内点数说明，不能跨点数复用同一个 k。",
            k_line,
            "rationale: ''",
            "preregistered_on: ''",
            "preregistered_by: ''",
            "",
        ]
    )


__all__ = [
    "DEFAULT_REST_WINDOW_S",
    "DEFAULT_VOLTAGE_RANGE_V",
    "EXAMPLE_K",
    "KNotPreregistered",
    "K_PREREGISTRATION_RELPATH",
    "MAD_TO_SIGMA",
    "MIN_POINTS",
    "NoiseFloor",
    "NoiseFloorUnavailable",
    "calibrate_noise_floor",
    "load_preregistered_k",
    "render_noise_floor_report",
    "render_preregistration_template",
]
