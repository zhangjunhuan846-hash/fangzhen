"""回收石墨链路端到端（**合成夹具**）：metadata → adapter → canonical → PyBaMM → report。

注意：数据是合成的（``examples/synthetic_recycled_graphite/``）。
这一步证明的是**链路**，不是方法 —— 所有判定都按 benchmark 模式解释，
不许引用为实验结论。真实数据到手后换 ``--root`` 即可复用同一条链。

五步：
  1 契约自检（``--require-data``）：结构 + metadata + 文件都在
  2 GCD 回放（三个状态）→ 与记录对照的 RMSE + provenance 落盘
  3 GITT 窗口扫描 → 每个窗口的 1 mV 带宽
  4 参数报告（benchmark 模式，自动带合成数据的边界说明）
  5 汇总：fresh / spent / regenerated

用法：
    python scripts/dev/recycled_graphite_e2e.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from battery_sim.datasets.recycled_graphite import (  # noqa: E402
    RecycledGraphiteAdapter,
    render_check,
)
from battery_sim.models.pybamm_factory import resolve_model_options  # noqa: E402
from battery_sim.simulation.baseline import run_baseline_cell  # noqa: E402
from governance.analysis_mode import (  # noqa: E402
    MODE_BENCHMARK,
    classify_band,
)
from identification.parameter_report import (  # noqa: E402
    ParameterProbe,
    render_report,
    unmeasured_probes,
)
from identification.recovery_stats import band_width  # noqa: E402
from identification.replay_scan import MultiplierScan  # noqa: E402

FIXTURE = "examples/synthetic_recycled_graphite"
SCAN = np.round(np.arange(-1.0, 1.0001, 0.1), 6)
LEVEL_MV = 1.0
LIMIT_DEX = 0.30
WINDOWS_TO_SCAN = ("GITT#w2", "GITT#w4", "GITT#w6")

#: 夹具不做 footprint 缩放：模型**就是**生成数据的那个电芯。
#: 真实半电池请用 scale_alignment="check"（默认），让它先判尺度。
ASSUME_ALIGNMENT = {"overrides": {}, "source": {}}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=FIXTURE)
    parser.add_argument("--out", default="outputs/reports/synthetic_recycled_graphite_identifiability.md")
    args = parser.parse_args(argv)

    failures: List[str] = []
    adapter = RecycledGraphiteAdapter(root=args.root)
    ps = adapter.config.parameter_set
    model_options = resolve_model_options(adapter)

    print("=" * 72)
    print("回收石墨端到端（合成夹具）")
    print("=" * 72)
    print(f"root          : {args.root}")
    print(f"parameter_set : {ps}")
    print(f"model_options : {model_options}")
    print("注意：这是 SYNTHETIC 夹具，不是实验数据\n")

    # ---------------- 1 契约自检 ----------------
    print("--- 1 契约自检（--require-data）---")
    check = adapter.validate(require_data=True)
    print(render_check(check))
    if not check["ok"]:
        failures.append("契约自检未通过")
    cells = [str(c) for c in adapter.list_cells()]
    print(f"cells: {cells}")
    if not cells:
        failures.append("没有发现任何样品（metadata/*.yaml）")
        cells = []

    # ---------------- 2 GCD 回放 ----------------
    print("\n--- 2 GCD 回放（每个状态）---")
    gcd_rows: List[Dict[str, Any]] = []
    for cell in cells:
        try:
            res = run_baseline_cell(adapter, "SPM", cell, rate="C0p2",
                                    parameter_set=ps, plot=False, quiet=True)
        except Exception as exc:
            failures.append(f"{cell} GCD 回放失败：{type(exc).__name__}: {exc}")
            print(f"  {cell}: FAIL {type(exc).__name__}: {str(exc)[:90]}")
            continue
        row = res["metrics"].iloc[0].to_dict()
        gcd_rows.append({
            "cell": cell,
            "rmse_mV": float(row.get("rmse_time_aligned_mV", float("nan"))),
            "n_points": int(row.get("n_points_time_aligned", 0) or 0),
            "output_dir": str(res["output_dir"].relative_to(ROOT)).replace("\\", "/"),
            "runtime_s": float(res["runtime_s"]),
        })
        meta_path = Path(res["output_dir"]) / "run_metadata.json"
        has_meta = meta_path.is_file()
        print(f"  {cell}: RMSE {gcd_rows[-1]['rmse_mV']:.3f} mV  "
              f"({gcd_rows[-1]['n_points']} 点, {gcd_rows[-1]['runtime_s']:.1f} s)  "
              f"run_metadata={'有' if has_meta else '缺'}")
        if not has_meta:
            failures.append(f"{cell}: 没写出 run_metadata.json（provenance 断裂）")

    # ---------------- 3 GITT 窗口扫描 ----------------
    print("\n--- 3 GITT 窗口扫描（1 mV 带宽）---")
    protocol_ids = [p for p in adapter.list_protocols()
                    if p in WINDOWS_TO_SCAN] or adapter.list_protocols()[:1]
    print(f"  窗口 id（list_protocols 广告的）：{adapter.list_protocols()}")
    scan_cell = cells[0] if cells else ""
    probe_rows: List[Dict[str, Any]] = []
    probes: List[ParameterProbe] = []
    for pid in protocol_ids:
        try:
            df = adapter.load_processed_protocol(scan_cell, pid)
            protocol = adapter.load_protocol(pid)
            scan = MultiplierScan(adapter, scan_cell, pid, df, protocol, ps,
                                  model_options, ASSUME_ALIGNMENT)
            J = np.array([scan.cost(float(a), 0.0) for a in SCAN])
            band = band_width(SCAN, J, 0.0, LEVEL_MV ** 2)
            verdict = classify_band(band, level_mV=LEVEL_MV, limit_dex=LIMIT_DEX,
                                    scan_range_dex=2.0)
        except Exception as exc:
            failures.append(f"{pid} 扫描失败：{type(exc).__name__}: {exc}")
            print(f"  {pid}: FAIL {type(exc).__name__}: {str(exc)[:90]}")
            continue
        finite = np.isfinite(J)
        peak = float(np.sqrt(np.max(J[finite]))) if finite.any() else float("nan")
        probe_rows.append({
            "protocol_id": pid,
            "segments": len(protocol.segments),
            "peak_model_to_model_rmse_mV": peak,
            "band_width_dex": band["width_dex"],
            "band_truncated": band["truncated"],
            "n_unreachable_amps": int(np.sum(~finite)),
            "verdict": verdict["verdict"],
        })
        probes.append(ParameterProbe(
            parameter=f"Ds[{pid}]",
            verdict=verdict["verdict"],
            protocol_id=f"{scan_cell}/{pid}",
            band=band,
            rationale=verdict["reason"],
            evidence=("GITT",),
            source="gitt_fitting",
            note=f"峰值 {peak:.3f} mV；{len(protocol.segments)} 段",
        ))
        print(f"  {pid}: 峰值 {peak:7.3f} mV | 带 {band['width_dex']:.4f} dex "
              f"| {verdict['verdict']} | 段数 {len(protocol.segments)}")

    # ---------------- 4 参数报告 ----------------
    print("\n--- 4 参数报告（benchmark 模式）---")
    probes.extend(unmeasured_probes(("k0", "Rct"), available_techniques=("GITT",)))
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = render_report(
            probes, dataset="synthetic_recycled_graphite", cell=scan_cell,
            analysis_mode=MODE_BENCHMARK, level_mV=LEVEL_MV, limit_dex=LIMIT_DEX,
            scan_half_dex=1.0,
            windows_path=f"{args.root}（合成夹具）",
            extra_caveats=[
                "**数据是合成夹具，不是实验样品**：三个状态的差异是一个写下来的 "
                "D_s 倍率 + 高斯噪声，由平台自己的回放路径生成。",
                "本步只证明链路（metadata → adapter → canonical → PyBaMM → report）通了，"
                "不构成任何关于回收石墨的结论。",
                "夹具未做 footprint 缩放（模型就是生成数据的那颗电芯）；真实半电池请用 "
                "scale_alignment='check' 让尺度对齐门先判一次。",
            ],
        )
        out_path.write_text(report, encoding="utf-8", newline="")
        print(f"  wrote {out_path.relative_to(ROOT)}")
    except Exception as exc:
        failures.append(f"报告生成失败：{type(exc).__name__}: {exc}")
        print(f"  FAIL {type(exc).__name__}: {exc}")

    # ---------------- 5 汇总 ----------------
    print("\n--- 5 汇总 ---")
    summary = pd.DataFrame(gcd_rows)
    if not summary.empty:
        print(summary.to_string(index=False))
    if probe_rows:
        print(pd.DataFrame(probe_rows).to_string(index=False))
    out_dir = ROOT / "outputs" / "fitting" / "synthetic_recycled_graphite"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "e2e_summary.json").write_text(
        json.dumps({"root": args.root, "parameter_set": ps,
                    "cells": cells, "gcd": gcd_rows, "gitt": probe_rows,
                    "failures": failures,
                    "note": "SYNTHETIC FIXTURE — plumbing only"},
                   indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8", newline="")

    print()
    if failures:
        for item in failures:
            print(f"  FAIL {item}")
        print(f"=== FAIL（{len(failures)} 项）===")
        return 1
    print("=== PASS：metadata → adapter → canonical → PyBaMM → report 全链路通 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
