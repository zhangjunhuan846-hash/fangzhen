# ============================================================
# Phase A2 — figures A2-1 .. A2-4
#
#   A2-1  response-RMS heatmap        (how strongly can each
#         parameter move the model output on each run)
#   A2-2  residual-alignment heatmap  (cos theta, shape direction)
#   A2-3  projection-fraction heatmap (single-direction energy share)
#   A2-4  residual(t) vs top-3 parameter response vectors
#         (overlay of residual e(t) with the orthogonal projection
#          of e onto the top-|cos| parameter response directions;
#          amplitudes are the actual projection, not fitted)
#
# Interpretation rule (frozen): a large response alone never names
# a root cause; only high response + high alignment + high
# projection may become a "candidate explanatory direction".
# No fitting anywhere.
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import residual_atlas as atlas  # noqa: E402
from common import PARAMETERS, selected_runs  # noqa: E402
from build_tables import RUN_SHORT, _short, load_S  # noqa: E402
import simulate as sim  # noqa: E402

OUT = ROOT / "outputs" / "analysis" / "targeted_sensitivity"
OUT.mkdir(parents=True, exist_ok=True)

GROUP_ORDER = ["solid_transport", "electrolyte_transport",
               "kinetics", "microstructure"]

# re-order parameter rows for the heatmaps by group then by name
PARAM_ORDER = sorted(
    PARAMETERS,
    key=lambda p: (GROUP_ORDER.index(sim.load_parameter_specs()[p]["group"]),
                   p),
)

COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e"]


def _heatmap(data: pd.DataFrame, title, fname, cmap, vmin, vmax,
             fmt=".2f"):
    fig, ax = plt.subplots(figsize=(0.9 * len(data.columns) + 2.2,
                                    0.62 * len(data.index) + 2.0))
    im = ax.imshow(data.to_numpy(float), cmap=cmap, aspect="auto",
                   vmin=vmin, vmax=vmax)
    lo = vmin if vmin is not None else float(np.nanmin(data.to_numpy(float)))
    hi = vmax if vmax is not None else float(np.nanmax(data.to_numpy(float)))
    ax.set_xticks(range(data.shape[1]))
    ax.set_xticklabels(data.columns, rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(data.shape[0]))
    ax.set_yticklabels(data.index, fontsize=9)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data.to_numpy(float)[i, j]
            if np.isfinite(v):
                dark = cmap in ("viridis", "YlGnBu") and \
                    (v - lo) / max(hi - lo, 1e-12) > 0.55
                ax.text(j, i, f"{v:{fmt}}", ha="center", va="center",
                        fontsize=8,
                        color="white" if dark else "black")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=170)
    plt.close(fig)
    print("wrote", OUT / fname)


def fig_a2_1(summary: pd.DataFrame):
    data = summary.pivot(index="parameter", columns="run_short",
                         values="response_rms_mV").reindex(PARAM_ORDER)
    _heatmap(data,
             "Fig A2-1  response RMS  [mV per unit fractional change] "
             "(delta = 0.20 central difference)",
             "fig_a2_1_response_rms_heatmap.png",
             "viridis", 0.0, None, fmt=".1f")


def fig_a2_2(summary: pd.DataFrame):
    data = summary.pivot(index="parameter", columns="run_short",
                         values="cosine_alignment").reindex(PARAM_ORDER)
    _heatmap(data,
             "Fig A2-2  residual-sensitivity cosine alignment "
             "cos(e, S_p)   [+1 same shape / -1 inverted]",
             "fig_a2_2_cosine_alignment_heatmap.png",
             "RdBu_r", -1.0, 1.0, fmt=".2f")


def fig_a2_3(summary: pd.DataFrame):
    data = summary.pivot(index="parameter", columns="run_short",
                         values="projection_fraction").reindex(PARAM_ORDER)
    _heatmap(data,
             "Fig A2-3  projection fraction  ||Proj_S e||^2/||e||^2 "
             "(single-direction local linear diagnostic)",
             "fig_a2_3_projection_fraction_heatmap.png",
             "YlGnBu", 0.0, 1.0, fmt=".2f")


def fig_a2_4(summary: pd.DataFrame):
    runs = selected_runs()
    n = len(runs)
    ncol, nrow = 3, int(np.ceil(n / 3))
    fig, axes = plt.subplots(nrow, ncol,
                             figsize=(4.6 * ncol, 3.4 * nrow))
    axes = np.atleast_1d(axes).ravel()

    for ax, run in zip(axes, runs):
        rid = run["run_id"]
        rf = atlas._read_run(run)
        t = rf["t"] / 3600.0
        e = rf["res_mV"]
        pm = atlas._pm(run["dataset"])
        stats = {
            "rmse": float(np.sqrt(np.mean(e ** 2))),
            "bias": float(np.mean(e)),
        }

        # top-3 parameters by |cosine alignment|
        rows = summary[(summary["run_id"] == rid)]
        top = rows.reindex(rows["cosine_alignment"].abs().sort_values(
            ascending=False).index).head(3)

        ax.plot(t, e, color="black", lw=1.6,
                label=f"residual (RMSE {stats['rmse']:.0f} mV)")
        for k, (_, r) in enumerate(top.iterrows()):
            pid = r["parameter"]
            S = load_S(run, pid)
            valid = np.isfinite(S) & np.isfinite(e)
            if valid.sum() < 5:
                continue
            se = S[valid]
            ee = e[valid]
            alpha = float(np.dot(ee, se) / np.dot(se, se))
            # orthogonal projection of e onto span(S_p)
            proj = np.full_like(S, np.nan)
            proj[valid] = alpha * se
            ax.plot(t[valid], proj[valid], lw=1.2, alpha=0.9,
                    color=COLORS[k % len(COLORS)],
                    label=(f"{pid}  (cos={r['cosine_alignment']:+.2f}, "
                           f"fproj={r['projection_fraction']:.2f})"))
        ax.axhline(0, color="gray", lw=0.5)
        ax.set_title(f"{_short(rid)}  [{pm['grade']} / {run['protocol']}]",
                     fontsize=9)
        ax.set_xlabel("time [h]")
        ax.set_ylabel("mV")
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=6.5, frameon=False, loc="best")
    for ax in axes[n:]:
        ax.axis("off")

    fig.suptitle("Fig A2-4  residual(t) vs top-|cos| parameter response "
                 "vectors (curves = orthogonal projection of residual "
                 "onto each S_p; sign preserved)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(OUT / "fig_a2_4_residual_vs_top3_response.png", dpi=150)
    plt.close(fig)
    print("wrote", OUT / "fig_a2_4_residual_vs_top3_response.png")


def main():
    summary = pd.read_csv(
        OUT / "sensitivity_run_parameter_summary.csv")
    fig_a2_1(summary)
    fig_a2_2(summary)
    fig_a2_3(summary)
    fig_a2_4(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
