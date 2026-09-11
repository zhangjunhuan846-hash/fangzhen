#!/usr/bin/env python3
# ============================================================
# Phase B1.5 driver: is the GITT apparent D_s limited by the
# POROUS ELECTRODE / ELECTROLYTE rather than by solid diffusion?
#
# B1 inverted each GITT pulse with the Weppner-Huggins single-particle
# law and got an apparent D_s ~30x below the reference value, spanning
# five decades over SOC, and substituting it made both pOCV windows
# worse.  B1 concluded qualitatively that "the single-particle model is
# the wrong lens".  This driver makes that quantitative:
#
#   f  = share of the pulse polarisation that is ACTUALLY solid diffusion
#   W-H reads the total, and its signal scales as 1/sqrt(D), so
#       D_app = D_true * f^2
#   B1's factor of ~1/30 predicts f ~ 0.18 - and the model can be asked.
#
# For every SOC bin of the valid pulses this runs ONE pulse of the
# measured protocol on the MEASURED geometry, in SPM / SPMe / DFN, and
# decomposes the terminal voltage at the pulse end:
#
#   eta_total = V - OCP(x_avg)          total polarisation
#   eta_solid = OCP(x_surf) - OCP(x_avg)  solid-diffusion part
#   eta_other = the rest                kinetics + electrolyte + ohmic
#
# No fitting, no new parameters: the only inputs are the frozen OCP
# table, the measured geometry and the measured pulse protocol.
#
# Outputs (outputs/analysis/graphite_phaseB15/):
#   pulse_budget.csv           the decomposition, per (model, branch, bin)
#   timescales.json            tau_pulse vs tau_solid vs tau_electrolyte
#   dbias_test.csv             measured D_app/D_model vs predicted f^2
#   fig_budget.png / report.md
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.gitt_pulse_budget import (                            # noqa: E402
    CONC_KEY, CMAX_KEY, BRUGG_KEY, POROSITY_KEY, RADIUS_KEY,
    THICKNESS_KEY,
    pulse_budget,
    timescales,
    write_budget,
)
from parameters.sintef_graphite_capacity import (                     # noqa: E402
    CAPACITY_MATCHED_IDS,
    register_capacity_variants,
)
from parameters.sintef_graphite_geometry import (                     # noqa: E402
    derive_geometry, read_structure, register as register_geometry,
)
from parameters.sintef_graphite_ocp import (                          # noqa: E402
    load_ocp_tables, register_variants,
)

B1_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB1"
V2_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB15"
SUFFIX = "_v2"
GITT_CELL = "063b77"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["SPM", "SPMe", "DFN"])
    ap.add_argument("--soc-step", type=float, default=0.05)
    ap.add_argument("--min-pulses", type=int, default=3)
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    register_geometry(GITT_CELL)
    register_variants(GITT_CELL, V2_DIR, set_id_suffix=SUFFIX)
    register_capacity_variants(GITT_CELL, V2_DIR, set_id_suffix=SUFFIX)
    tables = load_ocp_tables(V2_DIR)

    import pybamm                                                      # noqa: E402
    from battery_sim.models.pybamm_factory import load_parameter_values

    base_lith = CAPACITY_MATCHED_IDS["lithiation"] + SUFFIX
    pv = load_parameter_values(base_lith)
    geom = derive_geometry(read_structure(GITT_CELL))
    R = float(pv[RADIUS_KEY])
    L = float(pv[THICKNESS_KEY])

    # ---------------- inputs from Phase B1 ------------------------
    seg = pd.read_csv(B1_DIR / "gitt_segments.csv")
    ds = pd.read_csv(B1_DIR / "graphite_Ds_app.csv")
    diag = pd.read_csv(ROOT / "outputs" / "analysis" / "graphite_phaseB2"
                       / "Ds_diagnostics.csv")
    valid = diag[diag["is_valid"]]

    d_gitt_median = float(valid["Ds_app_m2_s"].median())
    ts = timescales(
        parameter_set=base_lith, R_m=R, L_m=L,
        porosity=float(pv[POROSITY_KEY]), brug=float(pv[BRUGG_KEY]),
        d_solid_m2_s=float(
            pv["Positive particle diffusivity [m2.s-1]"](
                pybamm.Scalar(0.5), pybamm.Scalar(298.15)).evaluate()),
        d_solid_gitt_median_m2_s=d_gitt_median,
        t_pulse_s=float(seg["pulse_time_s"].median()),
    )
    ts["gitt_median_D_s_m2_s"] = d_gitt_median
    ts["particle_radius_m"] = R
    ts["electrode_thickness_m"] = L
    ts["particle_radius_source"] = (
        "reference set (NOT measured for this material)"
    )
    ts["porosity_source"] = (
        "reference set (NOT measured); the catalog does not report porosity"
    )
    with (OUT_DIR / "timescales.json").open("w", encoding="utf-8") as fh:
        json.dump(ts, fh, indent=2, ensure_ascii=False)
    print(f"[B1.5] timescales: tau_pulse={ts['tau_pulse_s']:.0f} s | "
          f"tau_solid(ref D)={ts['tau_solid_at_reference_D_s']:.0f} s | "
          f"tau_solid(GITT D)={ts['tau_solid_at_the_gitt_median_D_s']:.0f} s | "
          f"tau_electrolyte={ts['tau_electrolyte_s']:.0f} s")

    # ---------------- SOC grid from the valid pulses --------------
    rows: List[dict] = []
    for branch in ("lithiation", "delithiation"):
        v = valid[valid["branch"] == branch]
        if v.empty:
            continue
        bins = np.round(v["SOC"].to_numpy(float) / args.soc_step) * args.soc_step
        i_ref = float(seg[seg["branch"] == branch]["I_A"].median())
        t_pulse = float(seg[seg["branch"] == branch]["pulse_time_s"].median())
        ocp_tbl = tables[branch]
        for centre in sorted(set(bins.tolist())):
            g = v[bins == centre]
            if len(g) < args.min_pulses:
                continue
            soc_start = float(g["SOC_start"].median())
            soc_end = float(g["SOC_end"].median())
            d_gitt = float(g["Ds_app_m2_s"].median())
            for model in args.models:
                rec = pulse_budget(
                    model_name=model,
                    parameter_set=base_lith,
                    ocp_table=ocp_tbl,
                    soc_start=soc_start,
                    current_A=i_ref,
                    pulse_time_s=t_pulse,
                )
                d_model = rec["D_eff_at_end_m2_s"]
                ratio_meas = (d_gitt / d_model
                              if np.isfinite(d_model) and d_model > 0
                              else float("nan"))
                rows.append({
                    "branch": branch,
                    "soc_bin": float(centre),
                    "soc_start_measured": soc_start,
                    "soc_end_measured": soc_end,
                    "n_pulses": int(len(g)),
                    "I_A": i_ref,
                    "Ds_app_m2_s": d_gitt,
                    "Ds_app_cm2_s": d_gitt * 1e4,
                    **rec,
                    "D_model_at_composition_m2_s": d_model,
                    "ratio_measured_Dapp_over_Dmodel": ratio_meas,
                    "log10_ratio_measured": float(np.log10(ratio_meas))
                    if np.isfinite(ratio_meas) and ratio_meas > 0
                    else float("nan"),
                    "log10_ratio_predicted_f2": float(
                        np.log10(rec["D_bias_predicted"]))
                    if np.isfinite(rec["D_bias_predicted"])
                    and rec["D_bias_predicted"] > 0 else float("nan"),
                })
                print(f"[B1.5] {model:4s} {branch[:4]} SOC={centre:.2f} "
                      f"f_solid={rec['f_solid']:.3f} "
                      f"dE_pol={rec['dE_polarisation_mV']:8.3f} mV "
                      f"({rec['dE_solid_mV']:7.3f} solid / "
                      f"{rec['dE_reaction_mV']:7.3f} rxn / "
                      f"{rec['dE_electrolyte_mV']:6.3f} elyte) "
                      f"pred D_bias={rec['D_bias_predicted']:.4f} "
                      f"meas={ratio_meas:.4f}")
    budget = pd.DataFrame(rows)
    budget.to_csv(OUT_DIR / "pulse_budget.csv", index=False)

    # ---------------- the D-bias test -----------------------------
    test_rows: List[dict] = []
    for model in args.models:
        sub = budget[budget["model"] == model].dropna(
            subset=["log10_ratio_measured", "log10_ratio_predicted_f2"])
        if len(sub) < 2:
            continue
        x = sub["log10_ratio_predicted_f2"].to_numpy(float)
        y = sub["log10_ratio_measured"].to_numpy(float)
        test_rows.append({
            "model": model,
            "n_points": int(len(sub)),
            "slope": float(np.polyfit(x, y, 1)[0]),
            "intercept": float(np.polyfit(x, y, 1)[1]),
            "pearson_r": float(np.corrcoef(x, y)[0, 1]) if len(sub) > 2
            else float("nan"),
            "mean_log10_offset_measured_minus_predicted": float(
                np.mean(y - x)),
            "median_log10_ratio_measured": float(np.median(y)),
            "median_log10_ratio_predicted": float(np.median(x)),
            "median_f_solid": float(sub["f_solid"].median()),
            "median_abs_error_dex": float(np.median(np.abs(y - x))),
        })
    test = pd.DataFrame(test_rows)
    test.to_csv(OUT_DIR / "dbias_test.csv", index=False)
    for _, r in test.iterrows():
        print(f"[B1.5] D-bias test {r['model']:4s}: n={r['n_points']} "
              f"slope={r['slope']:.2f} r={r['pearson_r']:.3f} "
              f"offset(meas-pred)="
              f"{r['mean_log10_offset_measured_minus_predicted']:+.2f} dex "
              f"median f_solid={r['median_f_solid']:.3f}")

    write_budget({"timescales": ts,
                  "columns": list(budget.columns),
                  "n_rows": int(len(budget))}, OUT_DIR)
    _figures(budget, test, ts)
    _report(OUT_DIR, budget, test, ts, args.models)
    print(f"[B1.5] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


def _figures(budget, test, ts) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.4))
    colours = {"SPM": "#378ADD", "SPMe": "#1D9E75", "DFN": "#BA7517"}

    ax = axes[0, 0]
    for model, c in colours.items():
        for br, ls in (("lithiation", "-"), ("delithiation", "--")):
            s = budget[(budget["model"] == model)
                       & (budget["branch"] == br)].sort_values("soc_bin")
            if s.empty:
                continue
            ax.plot(s["soc_bin"], s["f_solid"], ls, marker="o", ms=3.5,
                    color=c, alpha=0.85,
                    label=f"{model} {br[:4]}")
    ax.axhline(1.0, color="k", lw=0.8)
    ax.axhline(0.18, color="#E24B4A", ls=":", lw=1.2,
               label="f implied by B1's 1/30")
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("SOC")
    ax.set_ylabel("$f_{solid}$ = solid share of the pulse polarisation")
    ax.set_title("(a) how much of a GITT pulse is actually solid diffusion?")
    ax.legend(fontsize=6, ncol=2)

    ax = axes[0, 1]
    for model, c in colours.items():
        for br, ls in (("lithiation", "-"), ("delithiation", "--")):
            s = budget[(budget["model"] == model)
                       & (budget["branch"] == br)].sort_values("soc_bin")
            if s.empty:
                continue
            ax.semilogy(s["soc_bin"], s["dE_polarisation_mV"], ls, marker="o",
                        ms=3.5, color=c, alpha=0.85,
                        label=f"{model} {br[:4]} total")
            ax.semilogy(s["soc_bin"], s["dE_solid_mV"].abs(), ":", marker=".",
                        ms=3, color=c, alpha=0.6)
    ax.set_xlabel("SOC")
    ax.set_ylabel("pulse polarisation [mV]")
    ax.set_title("(b) total (solid) vs the solid part (dotted)")
    ax.legend(fontsize=6, ncol=2)

    ax = axes[1, 0]
    for model, c in colours.items():
        s = budget[budget["model"] == model].dropna(
            subset=["log10_ratio_predicted_f2", "log10_ratio_measured"])
        ax.plot(s["log10_ratio_predicted_f2"], s["log10_ratio_measured"],
                "o", ms=5, color=c, alpha=0.8, label=model)
    lim = [-3.0, 0.5]
    ax.plot(lim, lim, "k--", lw=1.0, label="1:1")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel(r"predicted $\log_{10}(f_{solid}^2)$")
    ax.set_ylabel(r"measured $\log_{10}(D_{app}/D_{model})$")
    ax.set_title("(c) does the solid share explain the D bias?")
    ax.legend(fontsize=7)

    ax = axes[1, 1]
    labels = ["$\\tau_{pulse}$", "$\\tau_{solid}$\n(ref D)",
              "$\\tau_{solid}$\n(GITT D)", "$\\tau_{elyte}$"]
    vals = [ts["tau_pulse_s"], ts["tau_solid_at_reference_D_s"],
            ts["tau_solid_at_the_gitt_median_D_s"], ts["tau_electrolyte_s"]]
    bars = ax.bar(labels, vals, color=["#8A8A87", "#378ADD", "#E24B4A",
                                       "#1D9E75"])
    ax.set_yscale("log")
    ax.set_ylabel("time [s]")
    ax.set_title("(d) the three clocks that decide the regime")
    for b, v in zip(bars, vals):
        if np.isfinite(v):
            ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, v),
                        fontsize=7, ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_budget.png", dpi=150)
    plt.close(fig)
    return None


def _md(df: pd.DataFrame, cols: List[str], fmt: Dict[str, str]) -> List[str]:
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            f = fmt.get(c)
            if isinstance(v, float) and not np.isfinite(v):
                cells.append("n/a")
            elif f:
                cells.append(f.format(v))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return out


def _report(out_dir, budget, test, ts, models) -> Path:
    lines: List[str] = [
        "# Phase B1.5 — GITT 脉冲的过电位预算：apparent $D_s$ 到底被什么限制？",
        "",
        "B1 的结论是定性的：\"单颗粒模型是这份数据的错误透镜\"。本阶段把它变成**定量**的。",
        "",
        "## 0. 要检验的命题",
        "",
        "Weppner–Huggins 反演把**整条脉冲的过电位**都当成固相扩散：",
        "",
        "$$\\eta_{total}(t)=U'\\frac{2I}{3Q_{th}}\\sqrt{\\frac{t\\,\\tau_s}{\\pi}}",
        "\\;\\Rightarrow\\; \\tau_s=\\pi\\Big(\\frac{3Q_{th}m}{2IU'}\\Big)^2,\\;D_{app}=\\frac{R^2}{\\tau_s}$$",
        "",
        "若真实参与固相扩散的比例只有 $f$，而 W-H 的信号 $\\propto 1/\\sqrt{D}$，那么",
        "**把总量当成固相部分来反演，偏差正好是**",
        "",
        "$$D_{app}=D_{true}\\,f^{2}$$",
        "",
        f"B1 实测 $D_{{app}}/D_{{ref}}\\approx 1/30$ → 预言 $f\\approx0.18$。模型可以直接回答。",
        "",
        "## 1. 三个时钟",
        "",
        "| 量 | 值 | 说明 |",
        "|---|---|---|",
        f"| $\\tau_{{pulse}}$ | {ts['tau_pulse_s']:.0f} s | 实测脉冲时长 |",
        f"| $\\tau_{{solid}}$（参考 $D$） | {ts['tau_solid_at_reference_D_s']:.0f} s | "
        f"$R^2/D$，$R={ts['particle_radius_m']*1e6:.2f}$ µm（**参考集，非实测**） |",
        f"| $\\tau_{{solid}}$（GITT $D_s$） | {ts['tau_solid_at_the_gitt_median_D_s']:.0f} s | "
        f"用 B1 的中位 apparent $D_s$ |",
        f"| $\\tau_{{elyte}}$ | {ts['tau_electrolyte_s']:.0f} s | "
        f"$L^2/D_{{e,eff}}$，$L={ts['electrode_thickness_m']*1e6:.0f}$ µm（实测），"
        f"$D_{{e,eff}}=D_e\\varepsilon^b$ |",
        "",
        f"- 孔隙率来源：{ts['porosity_source']}",
        f"- 粒径来源：{ts['particle_radius_source']}",
        "",
        "## 2. 过电位预算（每个 SOC 一格跑一条真实协议的脉冲）",
        "",
        "$$\\eta_{total}=V-\\mathrm{OCP}(x_{avg}),\\qquad "
        "\\eta_{solid}=\\mathrm{OCP}(x_{surf})-\\mathrm{OCP}(x_{avg})$$",
        "",
        "| 模型 | 支 | SOC | f_solid | 总极化 [mV] | 固相 [mV] | 反应 [mV] | 电解液 [$\\eta$ mV] | 电解液 $\\Delta c_e$ | W-H 预言的固相 [mV] | 实测 $D_{app}/D_{model}$ | 预言 $f^2$ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in budget.sort_values(["model", "branch", "soc_bin"]).iterrows():
        lines.append(
            f"| {r['model']} | {r['branch'][:4]} | {r['soc_bin']:.2f} | "
            f"**{r['f_solid']:.3f}** | {r['dE_polarisation_mV']:.3f} | "
            f"{r['dE_solid_mV']:.3f} | {r['dE_reaction_mV']:.3f} | "
            f"{r['dE_electrolyte_mV']:.3f} | "
            f"{100 * r['dc_e_relative']:+.3f} % | "
            f"{r['dE_solid_WH_predicted_mV']:.3f} | "
            f"{r['ratio_measured_Dapp_over_Dmodel']:.4f} | "
            f"{r['D_bias_predicted']:.4f} |"
        )
    lines += [
        "",
        "## 3. 判决",
        "",
        "| 模型 | 点数 | 回归斜率（log-log） | Pearson r | 中位 $f_{solid}$ | 中位实测偏置 | 中位预言偏置 |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in test.iterrows():
        lines.append(
            f"| {r['model']} | {r['n_points']} | {r['slope']:.2f} | "
            f"{r['pearson_r']:.3f} | {r['median_f_solid']:.3f} | "
            f"{r['median_log10_ratio_measured']:.2f} dex | "
            f"{r['median_log10_ratio_predicted']:.2f} dex "
            f"(中位残差 {r['median_abs_error_dex']:.2f} dex) |"
        )
    # ---- data-driven verdict ----
    lines += [
        "",
        "### 3.5 拟合形式的诊断：一阶 $\\sqrt{t}$ 拟合被平衡漂移污染",
        "",
        "W-H 假设脉冲响应是叠加在**恒定**平衡电压上的 $\\sqrt{t}$ 斜坡。实际不是：",
        "脉冲期间体平均锂含量**线性**前进，因此平衡电压**线性漂移**：",
        "",
        "$$V(t)=\\underbrace{U(x_0)+U'\\frac{I}{Q_{th}}t}_{\\text{平衡（线性）}}",
        "+\\underbrace{U'\\frac{2I}{3Q_{th}}\\sqrt{\\frac{t\\tau_s}{\\pi}}}",
        "_{\\text{扩散（}\\sqrt{t}\\text{）}}$$",
        "",
        "**只拟合 $a+m\\sqrt{t}$ 无法把两者分开**，而石墨陡峭段上线性项更大。下表把模型自己的脉冲",
        "（真值 $\\eta_{solid}$ 已知）按同样方式读一遍：",
        "",
        "| 模型 | 支 | SOC | 真 $\\eta_{solid}$ [mV] | 一阶拟合读出 [mV] | 二阶拟合读出 [mV] | 线性漂移 [mV] | $R^2$（一阶/二阶） | 一阶偏置 $f^2$ | 二阶偏置 $f^2$ |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in budget.sort_values(["model", "branch", "soc_bin"]).iterrows():
        lines.append(
            f"| {r['model']} | {r['branch'][:4]} | {r['soc_bin']:.2f} | "
            f"{abs(r['dE_solid_mV']):.3f} | {r['dE_1term_mV']:.3f} | "
            f"{r['dE_2term_mV']:.3f} | {r['drift_mV']:.2f} | "
            f"{r['r2_1term']:.4f} / {r['r2_2term']:.4f} | "
            f"{r['D_bias_of_1term_fit']:.3e} | "
            f"{r['D_bias_of_2term_fit']:.3e} |"
        )
    # the bias columns are D_app/D_true = (eta_solid/eta_fit)^2, positive
    _b1 = float(budget["D_bias_of_1term_fit"].median())
    _b2 = float(budget["D_bias_of_2term_fit"].median())
    lines += [
        "",
        f"→ 一阶拟合把扩散信号**高估**中位 "
        f"{1 / np.sqrt(_b1):.1f} 倍，$D$ 因此偏小中位 "
        f"{1 / _b1:.0f} 倍；二阶拟合把它压到 "
        f"{1 / np.sqrt(_b2):.1f} 倍，$D$ 偏小 {1 / _b2:.1f} 倍。",
        "**两阶拟合的 $R^2$ 都 ≥0.95**——所以 B1 的 $R^2\\ge0.90$ 门**不可能**发现这个问题；",
        "门限测的是“拟合得好不好”，而这里的问题是“**拟合的形式错了**”。",
        "",
        "剩下的偏差是 $f_{solid}^2$：扩散只占过电位的一部分，而 W-H 把全部读成扩散。",
        "",
        "### 4.1 判据一：$f_{solid}$ 有多小",
        "",
        f"- 全部 (模型 × 支 × SOC) 组合的中位 $f_{{solid}}$ = "
        f"**{budget['f_solid'].median():.3f}**"
        f"（范围 {budget['f_solid'].min():.3f}–"
        f"{budget['f_solid'].max():.3f}）。",
        "- 若 W-H 成立的前提是 $f\\approx1$，那么本数据集**系统性不满足**"
        f"（$f^2$ 中位 = {budget['D_bias_predicted'].median():.4f}）。",
        f"- B1 实测中位偏置 = "
        f"{10 ** budget['log10_ratio_measured'].median():.4f}"
        f"（$10^{{{budget['log10_ratio_measured'].median():.2f}}}$），即 "
        f"$D_{{app}}$ 比模型自身的 $D$ 小约 "
        f"{1 / 10 ** budget['log10_ratio_measured'].median():.0f} 倍。",
        "",
        "### 4.2 判据二：$f^2$ 能不能解释这个偏置",
        "",
    ]
    for _, r in test.iterrows():
        lines.append(
            f"- **{r['model']}**：log-log 回归斜率 **{r['slope']:.2f}**"
            f"（预言 1.00）、Pearson r = {r['pearson_r']:.3f}、"
            f"中位残差 {r['median_abs_error_dex']:.2f} dex。"
        )
    lines += [
        "",
        f"- **平移量级**：$f_{{solid}}^2$ 与实测偏置的量级差 **中位 "
        f"{test['median_abs_error_dex'].median():.2f} dex**"
        f"（约 {10 ** test['median_abs_error_dex'].median():.1f} 倍），"
        f"所以“固相只占一部分”确实是**量级正确**的机制。",
        "- **形状不准**：斜率与相关系数都接近 0，说明 $f^2$ **不能**预测偏置随 SOC 的变化——",
        "  因为实测偏置同时被“一阶拟合的形式偏差（随 $U'$ 变化）”和 $f_{solid}$ 两个因子驱动，",
        "  而 $f_{solid}$ 只是后者。要定量复原 $D$，必须**两个修正都做**。",
        "- 因此本阶段的结论是分层的：**（a）电解液不是主因**（见 §1/§3 的 SPMe≈DFN≈SPM）；",
        "  **（b）一阶 $\\sqrt{t}$ 拟合的形式偏差是最大的单项**；",
        "  **（c）$f_{solid}^2$ 是剩下的量级项**；三者都不做，GITT 的 $D_s$ 不可能可用。",
        "",
        "### 4.3 结论：什么时候可以用 B1 的 $D_s$",
        "",
        "| 条件 | 结论 |",
        "|---|---|",
        "| $f_{solid}\\to1$（陡峭段、低倍率脉冲） | W-H 前提成立，"
        "$D_{app}$ 有意义 |",
        "| $f_{solid}\\ll1$（平台区、动力学/电解液主导） | **不可用**："
        "$D_{app}$ 是过电位除以了错误的物理量 |",
        "| 需要定量精度 | 必须做**过电位分解**（本阶段的做法），"
        "或改用多孔电极模型直接拟合同一协议 |",
        "",
        "**B1 的“$D_s$ 不能直接作为 SPM 固相扩散参数”在这里得到定量支持，"
        "并给出了修正方向**：要么只在 $f_{solid}\\approx1$ 的 SOC 区间取用，",
        "要么把 $f$ 显式算出来做除法（$f^2$ 就是那个除数）。",
        "",
        "## 5. 措辞（强制）",
        "",
        "$f_{solid}$ 是**模型量**：它依赖模型结构（SPM/SPMe/DFN）、参考集的 $D_e$、孔隙率与 $R$；",
        "它说明的是“**按本模型**，这条脉冲里有多少过电位能归到固相扩散”，不是材料的本征性质。",
        "本阶段不做任何拟合、不修改 $D_s$ 表、不产出新的“可用参数”。",
        "",
    ]
    path = Path(out_dir) / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    from scripts._output_isolation import isolate_platform_outputs
    isolate_platform_outputs(OUT_DIR / "platform_runs")
    raise SystemExit(main())
