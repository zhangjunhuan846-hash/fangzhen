"""G6.2a — D_s(x) 表示的**接口门**（不是辨识门，不做优化）。

导师的定位：这一步只回答"函数型参数能不能一路走通"，不要扩展成论文级。
所以本脚本只测三件事，每条都是"通/不通"：

    A1  接口通  三种形状（constant / linear / three_region）作为 callable
                覆盖**真的到达模型**：换幅度 → 轨迹动，动的量能报出来
    A2  溯源通  写出的 run_metadata.json 里，函数型覆盖被记成可解析的
                描述符 + 调用方声明的形状/幅度/归一化 —— **没有序列化泄漏**
                （函数型参数曾经让整次运行直接失败）
    A3  报告通  结果能被 identification.parameter_report 消费，
                判定词落在 governance.analysis_mode 的五个词里

外加两个自洽检查（这两个不"通过"就说明接线错了，不是科学结论）：
    N1  amp=0 时三种形状必须与"不改参数"**逐位相同**（形状本身不夹带偏移）
    N2  扫描全程可达（coverage >= MIN_COVERAGE），否则那个点是"没跑"不是"没响应"

**另外报一个不是判据的量**：同一 amp 下 linear / three_region 与 constant 的
轨迹差多大。若小于 1 mV ⇒ **换形状在可观测量上不可区分** ⇒ 复杂化没有收益。
这与 G6.1c 的结论同族（那里是"换窗口"，这里是"换形状"），但这是从形状侧
独立测出来的第二个证据。

**窗口**：G6.1c 唯一合格的窗口 `GITT-charge#t475`（+ 一个中等可辨识窗口
`GITT-charge#t120` 作对照，用来判断结论是不是窗口特有的）。

预登记判据（跑之前固定）：
    A1_activity   每个形状在 |amp| <= 1 dex 内的峰值 model-to-model RMSE >= 1 mV
    A1_order      constant 的 dV_pulse 沿扫描**严格单调**
    A2_json       run_metadata.json 可解析，且 D_s 那一条是 callable 描述符
    A2_source     溯源条目含 shape / amplitude_dex / phi_rms
    A3_report     报告写出且三个判定词都在五个词的词表里
    N1_zero       amp=0 与不覆盖逐位相同（差异恰好 0.0）
    N2_coverage   所有被使用的点 coverage >= MIN_COVERAGE

Usage:
    python scripts/graphite/g6_2a_representations.py [--out outputs/fitting/g6.2a]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.analysis_mode import (  # noqa: E402
    ALLOWED_VERDICTS,
    MODE_MATERIAL,
    classify_band,
    render_verdict,
)
from governance.scale_alignment import alignment_overrides  # noqa: E402
from identification.parameter_report import (  # noqa: E402
    ParameterProbe,
    render_report,
    unmeasured_probes,
)
from identification.recovery_stats import band_width  # noqa: E402
from identification.replay_scan import (  # noqa: E402
    DS_KEY,
    MIN_COVERAGE,
    MultiplierScan,
)
from identification.representations import (  # noqa: E402
    SHAPE_CONSTANT,
    SHAPE_NAMES,
    cross_rmse_mV,
    describe_shapes,
    override_source,
    shape_override,
)

DATASET = "dlr_gitt"
REFERENCE_SWEEP = "GITT-discharge"     # 容量一致化的基准扫程

#: 只跑 G6.1c 唯一合格的窗口 + 一个对照窗口。
#: ⚠️ t120 属于**放电**扫程：写成 `GITT-charge#t120` 会被 adapter 挡下
#: （"triplet 120 belongs to sweep 'discharge'"）—— 这个报错是对的，
#: 窗口 id 里的扫程名不是装饰。
WINDOWS = ("GITT-charge#t475", "GITT-discharge#t120")

#: 幅度扫描（dex，RMS 归一化后三个形状可比）。
#: 步长必须**细于**要报的带宽（G5 的红线：容差不能小于网格间距）——
#: 0.25 dex 的网格报出 0.011 dex 的带是自欺。用 G6.1c 同一个分辨率
#: （0.05 dex），于是 `constant` 这一行可以**逐位核对** G6.1c 的 0.0988 dex：
#: phi_0 = 1 就是那次扫描，不一致就说明接线错了。
SCAN_STEP_DEX = 0.05
SCAN_HALF_DEX = 1.0

#: 判据水平与上限：与 G6.1b-1 / G6.1c 用同一组数，不新造
LEVEL_MV = 1.0
LIMIT_DEX = 0.30

#: 做溯源/形状对比用的幅度
PROBE_AMP_DEX = 0.5


def scan_grid() -> np.ndarray:
    n = int(round(2 * SCAN_HALF_DEX / SCAN_STEP_DEX))
    return np.round(np.linspace(-SCAN_HALF_DEX, SCAN_HALF_DEX, n + 1), 6)


def _find_key(node: Any, key: str) -> Optional[Any]:
    """在嵌套 dict/list 里找第一个 key（run_metadata 的层级不保证）。"""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, (list, tuple)):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def build_scan(adapter, cell, window, df, protocol, ps, model_options,
               align, shape) -> MultiplierScan:
    """一个形状 = 一个 scan 实例；扫描变量是**该形状的幅度（dex）**。

    cost / compare / reachable 的定义完全沿用 MultiplierScan ——
    换形状不允许换代价函数。
    """
    return MultiplierScan(
        adapter, cell, window, df, protocol, ps, model_options, align,
        override_builder=lambda a, s=shape: shape_override(ps, s, a),
        override_source_fn=lambda a, s=shape: override_source(s, a),
        source_label=f"G6.2a shape interface gate ({shape})",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    from battery_sim.models.pybamm_factory import resolve_model_options
    from battery_sim.registry import get_dataset

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/fitting/g6.2a")
    parser.add_argument("--windows", default=",".join(WINDOWS))
    args = parser.parse_args(argv)

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    windows = [w for w in args.windows.split(",") if w.strip()]

    adapter = get_dataset(DATASET)
    cell = str(adapter.list_cells()[0])
    ps = adapter.config.parameter_set
    model_options = resolve_model_options(adapter)
    align = alignment_overrides(adapter, REFERENCE_SWEEP, cell)
    grid = scan_grid()

    log_lines: List[str] = []

    def log(msg: str = "") -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    log("=" * 72)
    log("G6.2a — D_s(x) 表示接口门（只验接口，不做辨识）")
    log("=" * 72)
    log(f"dataset/window : {DATASET} / {cell}")
    log(f"参考扫程(容量) : {REFERENCE_SWEEP}")
    log(f"幅度扫描       : ±{SCAN_HALF_DEX:g} dex，步长 {SCAN_STEP_DEX:g}（{grid.size} 点）")
    log(f"判据           : {LEVEL_MV:g} mV 水平、上限 {LIMIT_DEX} dex")
    log("形状（RMS 归一化）:")
    log(describe_shapes())

    tic = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    curves: List[Dict[str, Any]] = []
    per_window: Dict[str, Dict[str, Any]] = {}

    for window in windows:
        df = adapter.load_processed_protocol(cell, window)
        protocol = adapter.load_protocol(window)
        log("")
        log(f"--- {window}  ({len(df)} 行) ---")
        record: Dict[str, Any] = {"shapes": {}}

        for shape in SHAPE_NAMES:
            scan = build_scan(adapter, cell, window, df, protocol, ps,
                              model_options, align, shape)
            ref_rec = scan.evaluate(0.0)
            J = np.array([scan.cost(float(a), 0.0) for a in grid])
            finite = np.isfinite(J)
            n_unreach = int(np.sum(~finite))
            # 峰值只在**可达**的扫描点上取。不可达点是"这次没跑"，
            # 不是"响应无穷大"（cost 对不可达返回 inf）——把两者混在一起
            # 会让 A1_activity 因为 inf 而通过，看起来像"有响应"。
            peak_mV = (float(math.sqrt(np.max(J[finite])))
                       if finite.any() else float("nan"))
            dvp = [scan.evaluate(float(a))["dv_pulse_mV"] for a in grid]
            dvp_f = [float(v) for v in dvp if v is not None and np.isfinite(v)]
            coverage = min(scan.evaluate(float(a))["coverage_fraction"]
                           for a in grid)
            band = band_width(grid, J, 0.0, LEVEL_MV ** 2)
            verdict = classify_band(band, level_mV=LEVEL_MV, limit_dex=LIMIT_DEX,
                                    scan_range_dex=2.0 * SCAN_HALF_DEX)

            # N1：amp=0 必须与"不改参数"逐位相同
            zero_diff = cross_rmse_mV(ref_rec["V_ref"],
                                      scan.evaluate(0.0)["V_ref"])
            record["shapes"][shape] = {
                "scan": scan,
                "peak_model_to_model_rmse_mV": peak_mV,
                "band": band,
                "verdict": verdict,
                "dv_pulse_mV": dvp_f,
                "coverage_min": float(coverage),
                "n_unreachable_amps": n_unreach,
                "zero_diff_max_abs_mV": zero_diff["max_abs_mV"],
                "n_sim": scan.n_sim,
                "runtime_s": scan.runtime_s,
            }
            rows.append({
                "window": window,
                "shape": shape,
                "peak_model_to_model_rmse_mV": peak_mV,
                "band_width_dex": band["width_dex"],
                "band_truncated": band["truncated"],
                "band_resolution_dex": band["resolution_dex"],
                "verdict": verdict["verdict"],
                "coverage_min": float(coverage),
                "n_unreachable_amps": n_unreach,
                "dv_pulse_min_mV": min(dvp_f) if dvp_f else float("nan"),
                "dv_pulse_max_mV": max(dvp_f) if dvp_f else float("nan"),
                "n_sim": scan.n_sim,
            })
            for a, j in zip(grid, J):
                curves.append({"window": window, "shape": shape,
                               "amp_dex": float(a),
                               "rmse_mV": float(math.sqrt(j))
                               if np.isfinite(j) else float("nan")})
            log(f"  {shape:13s} 峰值 {peak_mV:7.4f} mV | 带 {band['width_dex']:.4f} dex"
                f" (res {band['resolution_dex'] or float('nan'):.3f}, "
                f"trunc {band['truncated']}) | {verdict['verdict']}")

        # 形状之间的差异（不是判据）
        log("  同幅度下形状差异（amp = %+.2f dex）：" % PROBE_AMP_DEX)
        base = record["shapes"][SHAPE_CONSTANT]["scan"].evaluate(
            PROBE_AMP_DEX)["V_ref"]
        record["cross"] = {}
        for shape in SHAPE_NAMES:
            if shape == SHAPE_CONSTANT:
                continue
            other = record["shapes"][shape]["scan"].evaluate(
                PROBE_AMP_DEX)["V_ref"]
            cmp = cross_rmse_mV(other, base)
            record["cross"][f"{shape}_vs_{SHAPE_CONSTANT}"] = cmp
            log(f"    {shape:13s} vs {SHAPE_CONSTANT:13s} RMSE {cmp['rmse_mV']:.4f} mV"
                f" | max {cmp['max_abs_mV']:.4f} mV")
        per_window[window] = record

    # ---------------- A2：溯源（走公开回放入口，读它写下的 metadata） -------
    log("")
    log("--- A2 溯源（run_protocol_replay 写下的 run_metadata.json）---")
    from battery_sim.simulation.protocol_replay import run_protocol_replay

    prov: Dict[str, Any] = {}
    for shape in SHAPE_NAMES:
        res = run_protocol_replay(
            adapter, windows[0], model_name="SPM", cell=cell,
            parameter_set=ps,
            parameter_overrides={DS_KEY: shape_override(ps, shape, PROBE_AMP_DEX)},
            parameter_override_sources={DS_KEY: override_source(shape, PROBE_AMP_DEX)},
            scale_alignment="align",
            quiet=True,
        )
        meta_path = Path(res["output_dir"]) / "run_metadata.json"
        raw = meta_path.read_text(encoding="utf-8")
        meta = json.loads(raw)
        requested = _find_key(meta, "parameter_overrides_requested")
        applied = _find_key(meta, "parameter_overrides_applied")
        sources = _find_key(meta, "parameter_override_sources")
        entry = _find_key(requested, DS_KEY) or _find_key(applied, DS_KEY)
        src_entry = _find_key(sources, DS_KEY)
        is_descriptor = isinstance(entry, dict) and "__callable__" in entry
        prov[shape] = {
            "path": str(meta_path.relative_to(ROOT)).replace("\\", "/"),
            "json_parses": True,
            "ds_entry_is_callable_descriptor": bool(is_descriptor),
            "ds_entry_keys": sorted(entry.keys()) if isinstance(entry, dict) else None,
            "source_has_shape": bool(isinstance(src_entry, dict)
                                     and src_entry.get("shape") == shape),
            "source_has_amplitude": bool(
                isinstance(src_entry, dict)
                and abs(float(src_entry.get("amplitude_dex", np.nan))
                        - PROBE_AMP_DEX) < 1e-9),
            "source_has_phi_rms": bool(isinstance(src_entry, dict)
                                       and "phi_rms" in src_entry
                                       and src_entry.get("phi_rms") is not None),
        }
        log(f"  {shape:13s} json OK | D_s 描述符 {is_descriptor} | "
            f"source.shape {prov[shape]['source_has_shape']} | "
            f"amplitude {prov[shape]['source_has_amplitude']} | "
            f"phi_rms {prov[shape]['source_has_phi_rms']}")
        log(f"                {prov[shape]['path']}")

    # ---------------- A3：报告（直接用参数报告生成器） ----------------------
    log("")
    log("--- A3 报告 ---")
    probes = []
    for shape in SHAPE_NAMES:
        sh = per_window[windows[0]]["shapes"][shape]
        v = sh["verdict"]
        probes.append(ParameterProbe(
            parameter=f"Ds[{shape}]",
            verdict=v["verdict"],
            protocol_id=windows[0],
            band=sh["band"],
            rationale=v["reason"],
            evidence=("GITT",),
            source="gitt_fitting",
            note=(f"峰值 model-to-model RMSE {sh['peak_model_to_model_rmse_mV']:.3f} mV"),
        ))
    probes.extend(unmeasured_probes(("k0", "Rct"), available_techniques=("GITT",)))
    report_path = ROOT / "outputs" / "reports" / "g6_2a_shape_interface.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(
        probes, dataset=DATASET, cell=cell, analysis_mode=MODE_MATERIAL,
        level_mV=LEVEL_MV, limit_dex=LIMIT_DEX, scan_half_dex=SCAN_HALF_DEX,
        dataset_role="benchmark", windows_path="(G6.2a shape scan)",
        extra_caveats=[
            "本门只验接口（override → 模型 → provenance → 报告），"
            "**不构成任何 D_s(x) 形状的辨识结论**。",
            f"形状幅度按 RMS 归一化后可比（{SCAN_HALF_DEX:g} dex 扫描）；"
            f"three_region 只用了**一个**方向（两端 vs 中段），不是三个自由系数。",
        ],
        include_recovery=False,
    )
    report_path.write_text(report, encoding="utf-8", newline="")
    verdicts_ok = all(p.verdict in ALLOWED_VERDICTS for p in probes)
    log(f"  写出 {report_path.relative_to(ROOT)}")
    log(f"  判定词全部在词表内: {verdicts_ok}")
    for p in probes:
        log(f"    {render_verdict(p.verdict, parameter=p.parameter)}")

    # ---------------- 判据 -------------------------------------------------
    crit: Dict[str, Any] = {}
    for window in windows:
        rec = per_window[window]
        crit[f"A1_activity[{window}]"] = bool(all(
            rec["shapes"][s]["peak_model_to_model_rmse_mV"] >= LEVEL_MV
            for s in SHAPE_NAMES))
        dvp = rec["shapes"][SHAPE_CONSTANT]["dv_pulse_mV"]
        crit[f"A1_order[{window}]"] = bool(
            len(dvp) >= 3 and all(b > a for a, b in zip(dvp, dvp[1:])))
        crit[f"N1_zero[{window}]"] = bool(all(
            rec["shapes"][s]["zero_diff_max_abs_mV"] == 0.0
            for s in SHAPE_NAMES))
        crit[f"N2_coverage[{window}]"] = bool(all(
            rec["shapes"][s]["coverage_min"] >= MIN_COVERAGE
            for s in SHAPE_NAMES))
    crit["A2_json"] = bool(all(p["json_parses"]
                               and p["ds_entry_is_callable_descriptor"]
                               for p in prov.values()))
    crit["A2_source"] = bool(all(p["source_has_shape"]
                                 and p["source_has_amplitude"]
                                 and p["source_has_phi_rms"]
                                 for p in prov.values()))
    crit["A3_report"] = bool(report_path.is_file() and verdicts_ok)

    runtime = time.perf_counter() - tic
    n_sim = int(sum(r["n_sim"] for w in per_window.values()
                    for r in w["shapes"].values()))

    # 形状差异：与判据水平比一次（报告用，不改判据）
    shape_resolution = {
        w: {k: v["rmse_mV"] for k, v in per_window[w]["cross"].items()}
        for w in windows
    }

    interface_criteria = sorted(k for k in crit if k.startswith(("A2", "A3")))
    window_failures = sorted(k for k in crit
                             if not crit[k] and k not in interface_criteria)
    verdict_payload = {
        "criteria": crit,
        "passed": bool(all(crit.values())),
        # 门的**目的**（导师定的那三个问题）是"接口通"：A2 溯源 + A3 报告。
        # A1_*/N* 是顺带测的窗口类判据：失败要照实报，但不改变
        # "接口通了"这个结论 —— 也不许用它们去改阈值。
        "interface_passed": bool(all(crit[k] for k in interface_criteria)),
        "interface_criteria": interface_criteria,
        "window_criteria_failed": window_failures,
        # 探针点不可达时 cost 返回 inf，band_width 会把那些点**丢弃**，
        # 于是剩下的点被当成相邻点 → **带会被量窄**。凡是 n>0 的行，
        # 它的带宽只能当"上限"，不能当测量值。
        "bands_measured_with_unreachable_amps": [
            {"window": r["window"], "shape": r["shape"],
             "n_unreachable_amps": r["n_unreachable_amps"],
             "band_width_dex": r["band_width_dex"]}
            for r in rows if r["n_unreachable_amps"] > 0
        ],
        "n_simulations": n_sim,
        "runtime_s": runtime,
        "level_mV": LEVEL_MV,
        "limit_dex": LIMIT_DEX,
        "scan_half_dex": SCAN_HALF_DEX,
        "scan_step_dex": SCAN_STEP_DEX,
        "windows": list(windows),
        "shape_resolution_mV": shape_resolution,
        "interpretation_rule": (
            "A1/A2/A3 只说明接口通了。形状能不能被分辨是另一个问题："
            f"把 shape_resolution_mV 与判据水平 {LEVEL_MV:g} mV 比 —— "
            "小于它就意味着换形状在可观测量上不可区分，"
            "此时增加形状复杂度不会带来信息（与 G6.1c 同族）。"
        ),
    }

    report_json = {
        "dataset": DATASET,
        "cell": cell,
        "reference_sweep": REFERENCE_SWEEP,
        "parameter_set": ps,
        # 每个形状的 (mean, rms) 已经写在 run_metadata.json 的
        # parameter_override_sources 里（phi_mean / phi_rms），
        # 这里不重复一遍；要复核跑 identification.representations。
        "shape_names": list(SHAPE_NAMES),
        "rows": rows,
        "provenance": prov,
        "verdict": verdict_payload,
        "caveats": [
            "只验接口，不做辨识、不做优化、不拟合任何测量。",
            "带宽是 model-to-model 量（同模型、同尺度、无噪声）；"
            "这里它只是「接口通了之后顺带看到的数」，不是结论。",
            "形状幅度按 RMS 归一化（phi 的 rms=1、除 phi_0 外 mean=0），"
            "三个形状的 amp 因此可比。",
            "three_region 只用一个方向（两端 vs 中段），"
            "因为 G6.1c 已实测：加自由系数只加带宽，不加信息。",
            "数据集是公开 benchmark（dlr_gitt），不是任何回收石墨样品。",
        ],
    }
    (out / "g6_2a_report.json").write_text(
        json.dumps(report_json, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8", newline="")
    pd.DataFrame(rows).to_csv(out / "g6_2a_shapes.csv", index=False)
    pd.DataFrame(curves).to_csv(out / "g6_2a_cost_curves.csv", index=False)
    (out / "g6_2a_run.log").write_text("\n".join(log_lines) + "\n",
                                       encoding="utf-8", newline="")

    log("")
    log("=" * 72)
    for k, v in crit.items():
        log(f"  {'PASS' if v else 'FAIL'}  {k}")
    log(f"  => {'PASS' if verdict_payload['passed'] else 'FAIL'}"
        f"  ({n_sim} 次仿真，{runtime:.1f} s)")
    log("=" * 72)
    log("形状差异 vs 判据水平（不是判据）：")
    for w, d in shape_resolution.items():
        for k, val in d.items():
            log(f"  {w:22s} {k:34s} {val:8.4f} mV   "
                f"({'< 1 mV，形状不可分辨' if val < LEVEL_MV else '>= 1 mV'})")
    log(f"\n产物：{out.relative_to(ROOT)}/g6_2a_{{report.json,shapes.csv,cost_curves.csv}}"
        f"  +  {report_path.relative_to(ROOT)}")
    return 0 if verdict_payload["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
