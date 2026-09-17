"""生成**合成**回收石墨夹具（examples/synthetic_recycled_graphite/）。

⚠️ 这是**接口夹具**，不是实验数据。
   三个样品的「差异」是一个写下来的 D_s 倍率 + 噪声，由平台自己的回放路径生成。
   唯一用途：在真实数据到来前把
       metadata → adapter → canonical → PyBaMM → report
   这条链跑通。**任何结论都不许引用它**（报告里会带 benchmark 标记）。

   它同时是一份「格式契约的可执行说明」：adapter 只认下面这个 CSV 格式。

CSV 格式（本仓库约定；真实仪器导出请按 docs/adding_a_dataset.md §2 改解析器）
    time_s,current_A,voltage_V,temperature_C,phase,window
      · current_A：**放电为正**（平台约定；Basytec 那类「负=放电」必须先翻）
      · phase    ：rest | discharge | charge | pulse（相当于仪器的 Command 列）
      · window   ：GITT 的窗口编号 1..N；GCD 留空

生成方式
    用平台自己的 ``_run_one_replay`` + ``identification.representations.shape_override``
    跑 SPM(Ecker2015_graphite_halfcell)。**与平台的回放路径同源**：
    夹具与平台若不一致，那就是真的不一致（这一条正是夹具的价值）。

用法
    python scripts/dev/make_synthetic_recycled_graphite.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.models.pybamm_factory import build_model_options  # noqa: E402
from battery_sim.simulation.baseline import _run_one_replay  # noqa: E402
from identification.representations import (  # noqa: E402
    DS_KEY,
    shape_override,
)

PARAMETER_SET = "Ecker2015_graphite_halfcell"


def _half_cell_options() -> dict:
    """与 configs 里 half_cell + working_electrode=positive 等价的模型选项。

    必须显式给：Ecker2015_graphite_halfcell 把**石墨放在正极槽位**，
    直接建全电池会在 'Negative electrode active material volume fraction' 上 KeyError
    （G6.1a 踩过同一个坑）。这里复用平台自己的 build_model_options，
    而不是另写一份翻译。
    """
    return build_model_options(
        cell_configuration="half_cell_positive",
        working_electrode="positive",
        extra_model_options={},
    )

#: 测量噪声（V）。写在这里，因为它是夹具的一部分，不是实验的一部分。
NOISE_SIGMA_V = 3.0e-4

#: 环境温度（°C）
AMBIENT_C = 25.0

#: GCD：600 s 静置 + C/5 放电 4 h（≈80 % DoD，避开电压悬崖）
GCD_REST_S = 600.0
GCD_DISCHARGE_S = 4 * 3600.0
GCD_C_RATE = 0.2

#: GITT：6 个 pulse-relax 窗口（这是平台最看重的激励）
GITT_WINDOWS = 6
GITT_INITIAL_REST_S = 1800.0
GITT_PULSE_S = 600.0
GITT_REST_S = 1800.0
GITT_C_RATE = 0.1
#: 每个窗口 = 脉冲前 600 s 静置 + 脉冲 + 脉冲后 600 s 静置
GITT_WINDOW_SIDE_S = 600.0

SAMPLE_DT_S = 10.0

#: 三个状态：fresh（基准）/ spent（损伤）/ regenerated（恢复）
SAMPLES: List[Dict] = [
    {
        "sample_id": "SYN-fresh",
        "material_class": "pristine",
        "ds_multiplier": 1.0,
        "recycling": None,
        "note": "商业石墨参照（夹具里的「真值」是 D_s ×1.0）",
    },
    {
        "sample_id": "SYN-spent",
        "material_class": "recycled",
        "ds_multiplier": 0.35,
        "recycling": {
            "source": {
                "battery_type": "18650 NMC/石墨 动力电池（退役）",
                "cathode_type": "NMC532",
                "graphite_origin": "人造石墨（原生）",
            },
            "treatment": {
                "method": "仅水洗去除电解液残留（无再生处理）",
                "temperature_C": 25.0,
                "duration_h": 1.0,
                "atmosphere": "air",
            },
        },
        "note": "拆解后未再生（夹具真值 D_s ×0.35）",
    },
    {
        "sample_id": "SYN-regenerated",
        "material_class": "regenerated",
        "ds_multiplier": 0.65,
        "recycling": {
            "source": {
                "battery_type": "18650 NMC/石墨 动力电池（退役）",
                "cathode_type": "NMC532",
                "graphite_origin": "人造石墨（原生）",
            },
            "treatment": {
                "method": "热处理（Ar/H2 还原）",
                "temperature_C": 800.0,
                "duration_h": 2.0,
                "atmosphere": "Ar/H2 5%",
            },
        },
        "note": "800 °C 热处理再生（夹具真值 D_s ×0.65）",
    },
]


def _current_profile(kind: str) -> tuple:
    """返回 (t 数组, 电流数组, phase 数组, window 数组)。"""
    if kind == "gcd":
        n_rest = int(GCD_REST_S / SAMPLE_DT_S)
        n_dis = int(GCD_DISCHARGE_S / SAMPLE_DT_S)
        t = np.arange(n_rest + n_dis + 1) * SAMPLE_DT_S
        i = np.concatenate([np.zeros(n_rest), np.full(n_dis + 1, GCD_C_RATE)])
        phase = np.array(["rest"] * n_rest + ["discharge"] * (n_dis + 1))
        window = np.array([""] * t.size)
        return t, i, phase, window

    # GITT 记录：initial rest(1800) + Σ[pulse(600) + rest(1800)]
    # **窗口定义 = rest→pulse→rest**（各 600 s）：平台的活动门/瞬态指标要
    # 用脉冲前的静置算 pre-pulse leakage，所以窗口必须含前静置。
    # 取"脉冲前后各 600 s"的切片，窗口之间不重叠。
    t, i, phase, window = [0.0], [0.0], ["rest"], [""]
    now = 0.0
    pulse_starts = []
    n_init_rest = int(GITT_INITIAL_REST_S / SAMPLE_DT_S)
    for _ in range(n_init_rest):
        now += SAMPLE_DT_S
        t.append(now)
        i.append(0.0)
        phase.append("rest")
        window.append("")
    for _ in range(GITT_WINDOWS):
        pulse_starts.append(now)
        for dur, cur, ph in ((GITT_PULSE_S, GITT_C_RATE, "pulse"),
                             (GITT_REST_S, 0.0, "rest")):
            n = int(dur / SAMPLE_DT_S)
            for _ in range(n):
                now += SAMPLE_DT_S
                t.append(now)
                i.append(cur)
                phase.append(ph)
                window.append("")
    t = np.array(t)
    i = np.array(i)
    phase = np.array(phase)
    window = np.array(window)

    n_side = int(GITT_WINDOW_SIDE_S / SAMPLE_DT_S)
    for k, start in enumerate(pulse_starts, start=1):
        lo = np.searchsorted(t, start - GITT_WINDOW_SIDE_S, side="left")
        hi = np.searchsorted(t, start + GITT_PULSE_S + GITT_WINDOW_SIDE_S,
                             side="right")
        window[lo:hi] = str(k)
    return t, i, phase, window


def _ocp_table() -> tuple:
    """(sto, OCP V) 表 —— 两处都要用：生成初值 + 写出 OCP 反演表。"""
    from battery_sim.models.pybamm_factory import load_parameter_values

    pv = load_parameter_values(PARAMETER_SET)
    ocp = pv["Positive electrode OCP [V]"]

    def _as_float(value) -> float:
        """pybamm 的函数对象对浮点入参也返回**符号**（实测 Scalar），必须取数。"""
        if hasattr(value, "evaluate"):
            return float(value.evaluate())
        return float(value)

    sto = np.linspace(0.005, 0.995, 400)
    ocp_v = np.array([_as_float(ocp(float(s))) for s in sto])
    return sto, ocp_v


def _simulate(t: np.ndarray, i: np.ndarray, ds_multiplier: float,
              *, x0: float = 0.01):
    """用平台自己的回放路径生成电压轨迹，返回 ``(t_sim, V_sim)``。

    必须声明 ``initialisation`` 块（平台契约）：半电池的 ``initial_soc`` 约定不适用，
    而默认初值会让 "Maximum voltage [V]" 事件在初值处就违反
    （实测 ``SolverError: Events ['Maximum voltage [V]'] are non-positive at
    initial conditions``）。夹具因此显式写死初值 x0（默认 0.01 = 装配态脱锂）
    并把它与对应 OCV 一起写进块里。

    ``x0`` 可传：倍率梯夹具要换到一个**平坦**的工作点（见
    ``scripts/dev/make_synthetic_rate_ladder.py``）。原因是反演的条件数 ——
    回放侧要靠"实测静置 OCV -> inverse_ocp -> x0"把初值找回来，
    而稀相端 dOCP/dx 极大（本参数集实测 x=0.01 处 ~0.78 V，x=0.1 处 ~0.22 V），
    网格分辨率上的一点点误差就会变成几十 mV 的起点差。
    """
    import pandas as pd

    from battery_sim.datasets.ocp_lookup import inverse_ocp

    conc_key = "Initial concentration in positive electrode [mol.m-3]"
    max_key = "Maximum concentration in positive electrode [mol.m-3]"
    sto, ocp_v = _ocp_table()
    order = np.argsort(ocp_v)
    x0 = float(x0)
    v0 = float(np.interp(x0, sto, ocp_v))
    # 用共享反演复核一遍（x0 -> OCP -> x0），反演与初值必须是同一个自洽关系
    x_check = inverse_ocp(sto[order], ocp_v[order], v0)
    if abs(x_check - x0) > 5e-3:
        raise RuntimeError(
            f"夹具初值不自洽：x0={x0} 但 inverse_ocp(OCP(x0))={x_check}"
        )

    # 生成用的 frame 也要满足 canonical 契约：平台自己的回放路径会读
    # capacity_Ah（Q_exp_reported）与温度列，缺了直接 KeyError。
    charge_Ah = np.concatenate(
        [[0.0], np.cumsum(0.5 * (i[1:] + i[:-1]) * np.diff(t))]
    ) / 3600.0
    frame = pd.DataFrame({
        "time_s": t,
        "current_A": i,
        "voltage_V": np.full(t.size, v0),       # 只用来定参考网格
        "capacity_Ah": charge_Ah,
        "temperature_ambient_C": np.full(t.size, AMBIENT_C),
    })
    frame.attrs["initialisation"] = {
        "method": "fixed_initial_concentration",
        "concentration_parameter": conc_key,
        "max_concentration_parameter": max_key,
        "stoichiometry_from_ocp": x0,
        "ocp_voltage_V": v0,
        "mapping_reason": (
            "SYNTHETIC FIXTURE: half cell assembled delithiated (x0 = 0.01); "
            "NOT inverted from a measurement"
        ),
    }
    res = _run_one_replay(
        frame,
        model_name="SPM",
        parameter_set=PARAMETER_SET,
        model_options=_half_cell_options(),
        parameter_overrides={
            DS_KEY: shape_override(
                PARAMETER_SET, "constant", float(np.log10(ds_multiplier)),
                name=f"fixture_Ds_x{ds_multiplier:g}"),
        },
        parameter_override_sources={
            DS_KEY: {
                "source": "SYNTHETIC FIXTURE (scripts/dev/make_synthetic_recycled_graphite.py)",
                "method": "log10 D_s(x) = log10 D_ref(x) + log10(multiplier)",
                "multiplier": float(ds_multiplier),
                "note": "夹具真值；不是从任何测量反演的",
            },
        },
    )
    return np.asarray(res["_t_common"], dtype=float), \
        np.asarray(res["_V_sim_common"], dtype=float)


def _write_csv(path: Path, t: np.ndarray, i: np.ndarray, v: np.ndarray,
               phase: np.ndarray, window: np.ndarray, seed: int) -> None:
    rng = np.random.default_rng(seed)
    noisy = v + rng.normal(0.0, NOISE_SIGMA_V, size=v.size)
    lines = ["time_s,current_A,voltage_V,temperature_C,phase,window"]
    for k in range(t.size):
        lines.append(
            f"{t[k]:.1f},{i[k]:.8g},{noisy[k]:.6f},{AMBIENT_C:.2f},"
            f"{phase[k]},{window[k]}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def _metadata(sample: Dict, out: Path, capacity_Ah: float) -> Dict:
    meta = {
        "sample_id": sample["sample_id"],
        "material_class": sample["material_class"],
        "source": f"SYNTHETIC FIXTURE —— {sample['note']}；不是实验样品",
        "electrode": {
            "mass_loading_mg_cm2": 1.8,
            "coating_thickness_um": 45.0,
            "area_cm2": 86.0,
            "binder": "夹具值（PVDF 5 %）",
        },
        "particle": {"d50_um": 12.0},
        "cell": {
            "format": "CR2032",
            "counter_electrode": "Li 片（夹具）",
            "electrolyte": "1 M LiPF6 EC:DEC（夹具）",
        },
        "measurements": [
            {"technique": "CC_charge_discharge",
             "file": f"examples/synthetic_recycled_graphite/raw/electrochemistry/{sample['sample_id']}_gcd.csv",
             "role": "identification",
             "notes": f"夹具：600 s 静置 + C/5 放电 4 h（≈80 % DoD），{capacity_Ah * 1e3:.2f} mAh"},
            {"technique": "GITT",
             "file": f"examples/synthetic_recycled_graphite/raw/electrochemistry/{sample['sample_id']}_gitt.csv",
             "role": "identification",
             "notes": f"夹具：{GITT_WINDOWS} × (pulse {GITT_PULSE_S:g} s @C/{1/GITT_C_RATE:g} + rest {GITT_REST_S:g} s)"},
        ],
        "structure": {
            "xrd": {"available": False,
                    "not_available_reason": "合成夹具：没有真实 XRD（真实样品必须填）"},
            "raman": {"available": False,
                      "not_available_reason": "合成夹具：没有真实 Raman"},
            "bet": {"available": False,
                    "not_available_reason": "合成夹具：没有真实 BET"},
        },
    }
    if sample["recycling"] is not None:
        meta["recycling"] = sample["recycling"]
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="examples/synthetic_recycled_graphite")
    args = parser.parse_args(argv)

    out = ROOT / args.out
    ec = out / "raw" / "electrochemistry"
    meta_dir = out / "metadata"
    proc = out / "processed"
    ec.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    st_dir = out / "raw" / "structure"
    st_dir.mkdir(parents=True, exist_ok=True)
    (st_dir / "README.md").write_text(
        "# raw/structure\n\n"
        "合成夹具**没有**结构表征数据：三个样品都是模型生成的，\n"
        "没有真实的 XRD / Raman / BET。布局留着是为了让目录契约完整；\n"
        "真实样品必须把这里填上（metadata 的 structure 块要求\n"
        "available=true 时必须给 file）。\n",
        encoding="utf-8", newline="")


    # OCP 反演表：半电池初值只能由实测静置 OCV 反演，反演需要这张表。
    # **不写表头** —— 平台的 load_ocp_curve 用 header=None 读两列。
    sto, ocp_v = _ocp_table()
    ocp_path = proc / "ocp_graphite.csv"
    ocp_path.write_text(
        "".join(f"{s:.6f},{v:.6f}\n" for s, v in zip(sto, ocp_v)),
        encoding="utf-8", newline="")
    print(f"  {ocp_path.name:28s} OCP 反演表 {sto.size} 行  "
          f"V∈[{ocp_v.min():.4f}, {ocp_v.max():.4f}]")

    print(f"生成合成夹具 → {out.relative_to(ROOT)}")
    print(f"注意 SYNTHETIC —— 不是实验数据；任何结论都不许引用它")
    first_capacity = None
    for k, sample in enumerate(SAMPLES):
        for kind in ("gcd", "gitt"):
            t, i, phase, window = _current_profile(kind)
            try:
                t_sim, v_sim = _simulate(t, i, sample["ds_multiplier"])
            except Exception as exc:
                print(f"  FAIL {sample['sample_id']} {kind}: "
                      f"{type(exc).__name__}: {str(exc)[:120]}")
                return 1
            # 仿真返回的时间轴是平台的参考网格：把电流/相位按它重采样
            i_sim = np.interp(t_sim, t, i)
            idx = np.searchsorted(t, t_sim, side="right") - 1
            idx = np.clip(idx, 0, t.size - 1)
            path = ec / f"{sample['sample_id']}_{kind}.csv"
            _write_csv(path, t_sim, i_sim, v_sim, phase[idx], window[idx],
                       seed=1000 * k + (0 if kind == "gcd" else 7))
            if kind == "gcd":
                charge = float(np.sum(0.5 * (i_sim[1:] + i_sim[:-1])
                                      * np.diff(t_sim))) / 3600.0
                if first_capacity is None:
                    first_capacity = charge
                print(f"  {path.name:28s} {t_sim.size:5d} 行  "
                      f"Q={charge * 1e3:7.3f} mAh  "
                      f"V∈[{v_sim.min():.4f}, {v_sim.max():.4f}]")
            else:
                print(f"  {path.name:28s} {t_sim.size:5d} 行  "
                      f"窗口数={len(set(window[idx])) - ('' in set(window[idx]))}")

        meta = _metadata(sample, out, first_capacity or 0.0)
        mpath = meta_dir / f"{sample['sample_id']}.yaml"
        mpath.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
                         encoding="utf-8", newline="")
        print(f"  {mpath.name:28s} 真值 D_s ×{sample['ds_multiplier']:g}")

    print("\n完成。注意：夹具的『真值』是 scripts/dev 里写死的 D_s 倍率，")
    print("不是从任何测量反演出来的 —— 所以它只能验链路，不能验方法。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
