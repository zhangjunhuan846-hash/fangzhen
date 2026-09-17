"""生成**合成倍率梯**夹具（examples/synthetic_rate_ladder/）。

⚠️ 与 examples/synthetic_recycled_graphite 同一性质：**接口夹具，不是实验数据**。
   两个目录里的电压曲线由平台自己的回放路径生成，真值是这里写死的 D_s 倍率。
   唯一用途：在真实石墨数据到来之前，把
       L4 预测链（辨识侧参数 -> 留出倍率 -> 与记录比）
   跑通，并让"角色门 / 尺度门 / 覆盖率门"都有东西可拦。

为什么要两个目录而不是一个
--------------------------
因为平台的 dataset_role 是**数据集级**的（没有 cell 维度），而 L4 要的正是
「辨识集」与「留出集」分开声明。所以夹具也照这个形状做：

    examples/synthetic_rate_ladder/
        ident/      C/5 放电  -> 声明为 identification（参数从这里来）
        holdout/    1C 放电   -> 声明为 validation（只用来评分）
        overrides_truth.json  夹具真值参数（当"辨识结果"用）
        datasets_roles.yaml   给 --roles-config 用的最小角色声明

两个目录描述的是**同一颗**（模拟的）电芯与同一个初始态，只有倍率不同 ——
所以它检验的是「倍率外推」，不是「跨样品泛化」。报告里这两件事必须分开写。

用法
    python scripts/dev/make_synthetic_rate_ladder.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# 生成路径必须**与回收石墨夹具同源**（同一个 _simulate / 同一套半电池选项），
# 否则两个夹具会各自漂移，夹具之间的一致性就没人保证了。
sys.path.insert(0, str(ROOT / "scripts" / "dev"))

import make_synthetic_recycled_graphite as gen  # noqa: E402

PARAMETER_SET = gen.PARAMETER_SET
SAMPLE_ID = "SYN-LADDER"

#: 夹具真值：D_s 相对参数集的倍率。刻意不是 1.0 ——
#: 若等于 1.0，"辨识出来的参数"就等于参数集默认值，这条链什么也没验证。
DS_TRUTH_MULTIPLIER = 0.35

#: 两个倍率（数值 C-rate）与目标 DoD
FIT_C_RATE = 0.2
TARGET_C_RATE = 1.0
#: 0.30 而不是 0.6：0.6 会让 1C 那一档先撞到电压下限（实测 V_end = 0.011 V），
#: 于是两档记录的 DoD 不一样，"同一 DoD、不同倍率"的对照就掺进了截断效应。
TARGET_DOD = 0.30
REST_S = 600.0
DT_S = 10.0

#: 初值化学计量（放电从这里出发）。
#: **刻意不用 0.01**：回放侧要靠「实测静置 OCV -> inverse_ocp -> x0」把初值
#: 找回来，而稀相端 dOCP/dx 极大（本参数集实测 OCP(0.01)=0.780 V、
#: OCP(0.10)=0.218 V）。400 点表在 x≈0.01 处的分辨率就能造出**90 mV** 的
#: 起点差 —— 那条链会把"反演病态"读成"模型误差"。
#: 0.40 落在平台上（OCP≈0.133 V，斜率 ~1.2 mV 每 0.01 x），反演误差 ~0.3 mV。
INITIAL_STOICH = 0.40


def _nominal_capacity_Ah() -> float:
    from battery_sim.models.pybamm_factory import load_parameter_values

    pv = load_parameter_values(PARAMETER_SET)
    return float(pv["Nominal cell capacity [A.h]"])


def _gcd_profile(c_rate: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """静置 + 定流放电到指定 DoD（电流按**标称容量的倍数**取，不是按安培数取）。

    按安培数取会让 "C/5" 与 "1C" 变成同一个电流（回收石墨夹具里
    ``GCD_C_RATE = 0.2`` 就是那个写法：0.2 **安培**）。倍率梯必须真的差倍率，
    所以这里先用参数集标称容量换出电流，再按同一个 DoD 定放电时长。
    """
    nominal = _nominal_capacity_Ah()
    i_dis = c_rate * nominal
    dod_time_s = TARGET_DOD * nominal / i_dis * 3600.0
    n_rest = int(REST_S / DT_S)
    n_dis = int(round(dod_time_s / DT_S))
    t = np.arange(n_rest + n_dis + 1) * DT_S
    i = np.concatenate([np.zeros(n_rest), np.full(n_dis + 1, i_dis)])
    phase = np.array(["rest"] * n_rest + ["discharge"] * (n_dis + 1))
    return t, i, phase


def _write_dataset(root: Path, *, c_rate: float, label: str) -> Dict:
    """写一个倍率目录（metadata + raw csv + processed OCP 表）。"""
    ec = root / "raw" / "electrochemistry"
    meta_dir = root / "metadata"
    proc = root / "processed"
    st_dir = root / "raw" / "structure"
    for d in (ec, meta_dir, proc, st_dir):
        d.mkdir(parents=True, exist_ok=True)

    sto, ocp_v = gen._ocp_table()
    (proc / "ocp_graphite.csv").write_text(
        "".join(f"{s:.6f},{v:.6f}\n" for s, v in zip(sto, ocp_v)),
        encoding="utf-8", newline="",
    )

    t, i, phase = _gcd_profile(c_rate)
    t_sim, v_sim = gen._simulate(t, i, DS_TRUTH_MULTIPLIER, x0=INITIAL_STOICH)
    i_sim = np.interp(t_sim, t, i)
    idx = np.clip(np.searchsorted(t, t_sim, side="right") - 1, 0, t.size - 1)
    window = np.array([""] * t_sim.size)

    csv_rel = f"{root.relative_to(ROOT)}/raw/electrochemistry/{SAMPLE_ID}_gcd.csv"
    gen._write_csv(ec / f"{SAMPLE_ID}_gcd.csv", t_sim, i_sim, v_sim,
                   phase[idx], window, seed=4242)

    charge_Ah = float(np.sum(0.5 * (i_sim[1:] + i_sim[:-1])
                             * np.diff(t_sim))) / 3600.0
    meta = {
        "sample_id": SAMPLE_ID,
        "material_class": "pristine",
        "source": (
            f"SYNTHETIC RATE-LADDER FIXTURE ({label}, {c_rate:g}C) —— "
            f"不是实验样品；曲线由平台自己的回放路径生成"
        ),
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
            {
                "technique": "CC_charge_discharge",
                "file": csv_rel,
                "role": "identification" if label == "ident" else "validation",
                "notes": (
                    f"夹具：{REST_S:g} s 静置 + {c_rate:g}C 放电到 "
                    f"~{TARGET_DOD:.0%} DoD；真值 D_s ×{DS_TRUTH_MULTIPLIER:g}；"
                    f"初值 x0={INITIAL_STOICH:g}（平台工作点，反演良态）"
                ),
            }
        ],
        "structure": {
            "xrd": {"available": False,
                    "not_available_reason": "合成夹具：没有真实 XRD"},
            "raman": {"available": False,
                      "not_available_reason": "合成夹具：没有真实 Raman"},
            "bet": {"available": False,
                    "not_available_reason": "合成夹具：没有真实 BET"},
        },
    }
    (meta_dir / f"{SAMPLE_ID}.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="",
    )
    (st_dir / "README.md").write_text(
        "# raw/structure\n\n合成夹具没有结构表征数据。\n",
        encoding="utf-8", newline="",
    )
    return {
        "root": str(root.relative_to(ROOT)),
        "c_rate": c_rate,
        "rows": int(t_sim.size),
        "charge_mAh": charge_Ah * 1e3,
        "v_min": float(v_sim.min()),
        "v_max": float(v_sim.max()),
        "duration_s": float(t_sim[-1]),
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="examples/synthetic_rate_ladder")
    args = ap.parse_args(argv)

    out = ROOT / args.out
    nominal = _nominal_capacity_Ah()
    print(f"parameter_set        : {PARAMETER_SET}")
    print(f"model nominal cap    : {nominal * 1e3:.3f} mAh")
    print(f"fixture D_s truth    : ×{DS_TRUTH_MULTIPLIER:g}")
    print("注意：SYNTHETIC —— 不是实验数据\n")

    rows = []
    rows.append(_write_dataset(out / "ident", c_rate=FIT_C_RATE, label="ident"))
    rows.append(_write_dataset(out / "holdout", c_rate=TARGET_C_RATE,
                               label="holdout"))
    for r in rows:
        print(f"  {r['root']:34s} {r['c_rate']:>5g}C  {r['rows']:5d} 行  "
              f"Q={r['charge_mAh']:7.3f} mAh  "
              f"V∈[{r['v_min']:.4f}, {r['v_max']:.4f}]  "
              f"{r['duration_s']:8.1f} s")

    overrides = {
        "provenance": (
            "SYNTHETIC FIXTURE 真值（不是从任何测量反演的）："
            f"D_s = D_ref × {DS_TRUTH_MULTIPLIER:g}"
        ),
        "overrides": {
            "Ds": {"shape": "constant",
                   "amplitude_dex": float(np.log10(DS_TRUTH_MULTIPLIER)),
                   "source": "synthetic_fixture_truth",
                   "note": "夹具写死的 D_s 倍率；真实工作里这里应填 GITT 反演值"},
        },
        "sources": {
            "Ds": {"source": "synthetic_fixture_truth",
                   "note": "仅用于验证 L4 链路可跑，不构成任何参数结论"},
        },
    }
    (out / "overrides_truth.json").write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="",
    )

    # 零拟合对照：同样的链，但"辨识出来的参数"就是参数集默认值（D_s 不变）
    zero_fit = {
        "provenance": "SYNTHETIC FIXTURE 负对照：不做任何覆盖（等于零拟合回放）",
        "overrides": {
            "Ds": {"shape": "constant", "amplitude_dex": 0.0,
                   "source": "zero_fit_control",
                   "note": "负对照：期望它在留出倍率上明显更差"},
        },
        "sources": {"Ds": {"source": "zero_fit_control", "note": "负对照"}},
    }
    (out / "overrides_zero_fit_control.json").write_text(
        json.dumps(zero_fit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="",
    )

    roles = {
        "synth_ladder_ident": {
            "dataset_role": "identification",
            "dataset_role_note": "夹具：C/5 放电，参数从这里辨识",
        },
        "synth_ladder_holdout": {
            "dataset_role": "validation",
            "dataset_role_note": "夹具：1C 放电，只用于预测评分，禁止进入拟合",
        },
    }
    (out / "datasets_roles.yaml").write_text(
        yaml.safe_dump(roles, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="",
    )

    (out / "README.md").write_text(
        "# 合成倍率梯夹具（SYNTHETIC）\n\n"
        "**不是实验数据。** 两个目录的曲线由平台自己的回放路径用写死的 "
        f"D_s 倍率（×{DS_TRUTH_MULTIPLIER:g}）生成，唯一用途是把 L4 预测链"
        "（辨识侧参数 → 留出倍率 → 与记录比）跑通，并让角色门/尺度门/"
        "覆盖率门都有东西可拦。\n\n"
        "两点必须知道的事实（否则会被读成 bug）：\n\n"
        "1. **1C 那一档会先撞到参数集的电压下限**（`Lower voltage cut-off`），"
        "所以它只走了更小的 DoD、比较区间也更短。这正是倍率能力的物理来源，"
        "不是夹具生成出错。\n"
        "2. 初值取的是平台上 x0 = "
        f"{INITIAL_STOICH:g}（**不是** 0.01）：稀相端 OCP 太陡，"
        "反演误差会被放大成几十 mV 的起点差，见生成器里的注释。\n\n"
        "```bash\n"
        "python -m identification.rate_prediction \\\n"
        "  --fit-dataset synth_ladder_ident --fit-rate C0p2 "
        "--fit-root examples/synthetic_rate_ladder/ident \\\n"
        "  --target-dataset synth_ladder_holdout --target-rate C1 "
        "--target-root examples/synthetic_rate_ladder/holdout \\\n"
        "  --overrides examples/synthetic_rate_ladder/overrides_truth.json \\\n"
        "  --roles-config examples/synthetic_rate_ladder/datasets_roles.yaml \\\n"
        "  --target-nominal-capacity-Ah 0.15625 "
        "--fit-nominal-capacity-Ah 0.15625\n"
        "```\n",
        encoding="utf-8", newline="",
    )

    print("\n完成。真值是脚本里写死的 D_s 倍率 —— 只能验链路，不能验方法。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
