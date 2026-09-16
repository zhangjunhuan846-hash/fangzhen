"""D_s(x) 的有限维表示（G6.2a 的"接口"部分，不是辨识部分）。

三个形状，全部**按 RMS 归一化**：

    log10 D_s(x) = log10 D_ref(x) + amp * phi(x)

    phi_0(x) = 1                        constant：只动整体水平
    phi_1(x) = sqrt(3) (2x - 1)         linear：单调斜率
    phi_2(x) = (1, -2, 1) / sqrt(2)     three-region：两端 vs 中段（零均值）

x 是石墨的锂化分数（sto，0=脱锂，1=满锂）。三个 phi 都满足
``mean(phi) = 0``（phi_0 除外，它的 mean=±1）与 ``rms(phi) = 1``：

    · rms 归一化让 "amp" 在三者之间**可比** —— 都是"对数扩散系数的 RMS
      偏移（dex）"，所以形状之间的差异是**形状**差异，不是尺度差异。
      不做归一化的话，"linear 比 constant 弱"可以只是因为系数小。
    · phi_2 的零均值是必要的：带非零均值就与 phi_0 混在一起，
      两个方向的相关性会让"哪个形状更好"变成一句无法证伪的话。

**为什么 3-region 只用一个方向而不是三个自由系数**
    G6.1c 已经实测过这件事：476 个窗口里只有 3 个能在 1 mV 水平把
    *一个* 方向（phi_0）定到 0.30 dex 以内。每个新方向都有自己的带，
    交叉项只会更宽。所以 G6.2a 的目的**不是**辨识，而是回答一个接口问题：

        "shape 型参数能不能一路走通（override → 模型 → provenance → 报告）？"

    三个自由系数会让这个接口验证顺带产出一堆不可读的带宽。一个方向足够。

**phi_2 的物理读法**（只是读法，不是结论）
    (1, -2, 1)/sqrt(2) 是"中段比两端慢"的对比。石墨在 x≈0.5 附近的
    阶跃/相变区段常被认为扩散更慢；这个形状正好把那个假设写成一个可检验的
    方向。它在任何具体样品上都**没有被证实**，本模块只提供形状。
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Sequence, Tuple

import numpy as np

from battery_sim.models.pybamm_factory import load_parameter_values

#: 与 identification.replay_scan 同一个键
DS_KEY = "Positive particle diffusivity [m2.s-1]"

#: 三个形状的名字（报告与 provenance 里用它，不用下标）
SHAPE_CONSTANT = "constant"
SHAPE_LINEAR = "linear"
SHAPE_THREE_REGION = "three_region"

SHAPE_NAMES = (SHAPE_CONSTANT, SHAPE_LINEAR, SHAPE_THREE_REGION)

#: 边界区宽度（锂化分数的比例），仅用于绘图/描述；phi_2 的切点固定在 1/3、2/3
REGION_EDGES = (1.0 / 3.0, 2.0 / 3.0)


def _is_symbolic(x) -> bool:
    """pybamm 在参数替换阶段把**符号**传进函数型参数，不是浮点数。

    这是 G6.2a 实测到的一条接口事实（第一次跑就炸在这里）：
    实参可能是 ``Maximum(0.0, Minimum(1.0, ...))`` 这类 pybamm 表达式，
    对它做 ``np.asarray(x, dtype=float)`` 会 ``TypeError``。
    ⇒ 形状函数必须**符号与数值两边都支持**，否则"接口通了"这句话是假的。
    """
    try:
        import pybamm
    except Exception:                     # 没装 pybamm 时仍可用数值路径
        return False
    return isinstance(x, pybamm.Symbol)


def _numeric(x):
    """数值输入规整：**标量必须回 float，不能回 0 维 ndarray**。

    实测（G6.2a 的测试抓到的）：``pybamm_symbol * np.array(0.5)``（0 维）
    会变成 ``Array`` 子节点，随后在合并域时崩掉
    （``AttributeError: 'numpy.ndarray' object has no attribute 'domains'``）。
    Python float 不会 —— 参数集的参考函数本来就是这么被调用的。
    """
    arr = np.asarray(x, dtype=float)
    return float(arr) if arr.ndim == 0 else arr


def _clip01(x):
    """把锂化分数夹到 [0,1]：符号走 pybamm，数值走 numpy（标量回 float）。"""
    if _is_symbolic(x):
        import pybamm

        return pybamm.minimum(pybamm.maximum(x, 0), 1)
    return np.clip(_numeric(x), 0.0, 1.0)


def _step(x, threshold: float):
    """``H(x - threshold)``：x >= threshold 时取 1。

    pybamm 侧**没有** ``pybamm.Heaviside``（26.8 实测），只有
    ``EqualHeaviside`` / ``NotEqualHeaviside``，而且约定与直觉相反：
    实测 ``EqualHeaviside(left, right)`` 在 ``left <= right`` 时返回 1
    （``NotEqualHeaviside`` 在 ``left < right`` 时返回 1）。
    所以要的是 ``1 - NotEqualHeaviside(x, threshold)``，正好等价于
    数值侧的 ``x >= threshold``（相等处也取 1）。**两边必须一致**：
    符号侧与数值侧在同一个 x 给出不同的 φ，会让"接口通了"变成假话。
    """
    if _is_symbolic(x):
        import pybamm

        return 1.0 - pybamm.NotEqualHeaviside(x, threshold)
    value = _numeric(x)
    if isinstance(value, np.ndarray):
        return (value >= threshold).astype(float)
    return float(value >= threshold)


def phi_constant(x):
    """phi_0 = 1（mean=1, rms=1）：整体水平。"""
    return _clip01(x) * 0.0 + 1.0


def phi_linear(x):
    """phi_1 = sqrt(3)(2x-1)（mean=0, rms=1）：单调斜率，脱锂端为负。"""
    return math.sqrt(3.0) * (2.0 * _clip01(x) - 1.0)


def phi_three_region(x):
    """phi_2 = (1, -2, 1)/sqrt(2)（mean=0, rms=1）：两端快、中段慢。

    写成 ``(1 - 3*H(x-1/3) + 3*H(x-2/3)) / sqrt(2)`` —— 三段取值
    (+1, -2, +1)/sqrt(2) 都落在这个线性组合上，且**同一个式子**同时
    适用于 pybamm 符号与 numpy 数组（不用 np.where 分支）。
    """
    lo, hi = REGION_EDGES
    s1 = _step(x, lo)
    s2 = _step(x, hi)
    return (1.0 - 3.0 * s1 + 3.0 * s2) / math.sqrt(2.0)


SHAPES: Dict[str, Callable] = {
    SHAPE_CONSTANT: phi_constant,
    SHAPE_LINEAR: phi_linear,
    SHAPE_THREE_REGION: phi_three_region,
}


#: 数值复核 (mean, rms) 的容差。
#: 为什么不是 1e-9：`three_region` 有两个跳变，均匀网格上的求积误差就是
#: ~5e-4 量级（**测量**误差，不是形状误差；解析上 rms=1 是精确的）。
#: 2e-3 足以抓住真正的错误（例如漏掉 √3 会让 rms 变成 0.577），
#: 又不会把求积误差当成 bug。
SHAPE_RMS_TOL = 2e-3

#: numpy 2.0 把 trapz 改名 trapezoid；两个名字都兼容
_trapz = getattr(np, "trapezoid", None) or np.trapz


def shape_rms(name: str, n: int = 2001) -> Tuple[float, float]:
    """数值复核一个形状的 (mean, rms) —— 归一化是**声明**，也要能被测。

    用**梯形积分**而不是样本均值：均匀网格上的样本均值对 x² 有一阶偏差
    （n=2001 时 linear 的 rms 会读成 1.0005 —— 看起来像形状没归一化，
    其实是测量方式带进来的）。梯形法误差降到 O(h²)，对二次函数近乎精确。
    """
    phi = SHAPES[name]
    x = np.linspace(0.0, 1.0, n)
    v = np.asarray(phi(x), dtype=float)
    return float(_trapz(v, x)), float(np.sqrt(_trapz(v ** 2, x)))


def describe_shapes() -> str:
    rows = []
    for name in SHAPE_NAMES:
        mean, rms = shape_rms(name)
        rows.append(f"  {name:13s} mean {mean:+.4f}  rms {rms:.4f}")
    return "\n".join(rows)


def shape_override(
    parameter_set: str,
    shape: str,
    amplitude_dex: float,
    *,
    name: str = "",
) -> Callable:
    """``D_s(x,T) = D_ref(x,T) * 10**(amplitude_dex * phi_shape(x))``

    返回值是 **callable**，并且 ``*args`` **全转发**给参考函数 ——
    参数集的 D_s 签名是 ``f(sto, T)``，少传一个参数不会报错，
    只会静静地把温度依赖丢掉（G6.1a 已经踩过这条）。
    """
    if shape not in SHAPES:
        raise KeyError(
            f"未知形状 {shape!r}；允许 {list(SHAPE_NAMES)}"
        )
    pv = load_parameter_values(parameter_set)
    if DS_KEY not in pv:
        raise KeyError(f"{parameter_set}: no {DS_KEY!r}")
    ref = pv[DS_KEY]
    if not callable(ref):
        raise TypeError(
            f"{parameter_set}: {DS_KEY!r} 是 {type(ref).__name__} 而不是函数。"
            f"标量 vs 函数的区别正是 G6 要测的能力；标量在这里会静默改测另一件事。"
        )

    phi = SHAPES[shape]
    amp = float(amplitude_dex)

    def shaped(*args, _ref=ref, _phi=phi, _amp=amp):
        x = args[0] if args else 0.0
        return _ref(*args) * (10.0 ** (_amp * _phi(x)))

    shaped.__name__ = name or f"graphite_Ds_{shape}_{amp:+.3f}dex"
    shaped.__doc__ = (
        f"G6.2a shape override: {shape}, amplitude {amp:+.3f} dex "
        f"(RMS-normalised shape; see identification/representations.py)"
    )
    return shaped


def override_source(
    shape: str,
    amplitude_dex: float,
    *,
    note: str = "",
) -> Dict[str, object]:
    """写进 ``parameter_override_sources`` 的溯源条目。

    只放**可核对的量**：形状名、幅度、归一化方式、以及形状的取样点。
    不放 "the model uses this" 这类无法证伪的说法。
    """
    mean, rms = shape_rms(shape)
    return {
        "source": "G6.2a representation interface gate",
        "method": f"log10 D_s(x) = log10 D_ref(x) + amp * phi_{shape}(x)",
        "shape": shape,
        "amplitude_dex": float(amplitude_dex),
        "phi_mean": mean,
        "phi_rms": rms,
        "region_edges": list(REGION_EDGES),
        "note": note or (
            "RMS-normalised shape so amplitudes are comparable across "
            "representations; NOT a fit to any measurement"
        ),
    }


def cross_rmse_mV(va: np.ndarray, vb: np.ndarray) -> Dict[str, float]:
    """两条轨迹的逐点差（mV）。两个 scan 共用同一条参考时间轴才能这么用。"""
    a = np.asarray(va, dtype=float)
    b = np.asarray(vb, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"轨迹长度不同：{a.shape} vs {b.shape}")
    m = np.isfinite(a) & np.isfinite(b)
    d = (a[m] - b[m]) * 1e3
    if not d.size:
        return {"rmse_mV": float("nan"), "max_abs_mV": float("nan"),
                "n_points": 0}
    return {
        "rmse_mV": float(np.sqrt(np.mean(d ** 2))),
        "max_abs_mV": float(np.max(np.abs(d))),
        "n_points": int(d.size),
    }


__all__ = [
    "DS_KEY",
    "REGION_EDGES",
    "SHAPES",
    "SHAPE_CONSTANT",
    "SHAPE_LINEAR",
    "SHAPE_NAMES",
    "SHAPE_THREE_REGION",
    "cross_rmse_mV",
    "describe_shapes",
    "override_source",
    "phi_constant",
    "phi_linear",
    "phi_three_region",
    "shape_override",
    "shape_rms",
]


def _self_check() -> int:
    """``python -m identification.representations`` —— 归一化的数值复核。"""
    print("shape (RMS-normalised, x = lithiation fraction 0..1)")
    print(describe_shapes())
    print(f"容差 {SHAPE_RMS_TOL:g}（three_region 的跳变求积误差 ~5e-4）")
    bad = []
    for name in SHAPE_NAMES:
        mean, rms = shape_rms(name)
        if abs(rms - 1.0) > SHAPE_RMS_TOL:
            bad.append(f"{name}: rms {rms:.6f}")
        if name != SHAPE_CONSTANT and abs(mean) > SHAPE_RMS_TOL:
            bad.append(f"{name}: mean {mean:+.6f}（零均值是声明的一部分）")
    if bad:
        print(f"FAIL 归一化错误：{bad}")
        return 1
    print("OK 三个形状满足声明（rms=1；除 phi_0 外 mean=0）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_self_check())
