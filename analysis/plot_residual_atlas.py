# ============================================================
# Scientific Analysis Phase A1 — Fig A1..A5 (Step A8)
# Reads outputs/analysis/residual_atlas/*.csv (read-only).
# Scientific-diagnostic plots only; deliberately plain, no
# dashboards.  Colors = dataset, line styles = protocol.
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = _ROOT / "outputs" / "analysis" / "residual_atlas"
OUT.mkdir(parents=True, exist_ok=True)

DATASET_COLORS = {
    "chen2020": "#1f77b4",
    "calce_cs2": "#ff7f0e",
    "calce_20r": "#2ca02c",
    "calce_a123": "#d62728",
}
PROTOCOL_MARKERS = {"CC": ("--", "o"), "DST": ("-", "o"),
                    "FUDS": ("-", "s"), "US06": ("-", "^")}

DATASET_SHORT = {
    "chen2020": "Chen2020\n(NMC, A/exact, CC)",
    "calce_cs2": "CS2\n(LCO, B/surr, CC)",
    "calce_20r": "20R\n(NMC, B/surr, dyn)",
    "calce_a123": "A123\n(LFP, B/surr, dyn)",
}


def short_window(w: str) -> str:
    # 'calce_20r/2/DST_50SOC' -> 'DST50' ; 'calce_a123/007/DST' -> '007 DST'
    parts = w.split("/")
    slug = parts[-1]
    if slug.startswith(("DST", "FUDS", "US06")) and "_" in slug:
        p, soc = slug.split("_", 1)
        return f"{p} {soc.replace('SOC','')}"
    return f"{parts[1]} {slug}"


def _facet_axes():
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.2), sharey=False)
    fig.subplots_adjust(wspace=0.42, bottom=0.16, left=0.07, right=0.99)
    return fig, axes


def fig_a1(summary: pd.DataFrame):
    """Run-level RMSE / Bias / residual_std per dataset."""
    fig, axes = _facet_axes()
    for ax, (ds, g) in zip(axes, summary.groupby("dataset", sort=False)):
        x = np.arange(len(g))
        labels = [short_window(w) for w in g["window"]]
        ax.bar(x - 0.25, g["RMSE_mV"], 0.25, label="RMSE", color="#4c72b0")
        ax.bar(x, g["Bias_mV"], 0.25, label="Bias", color="#dd8452")
        ax.bar(x + 0.25, g["residual_std_mV"], 0.25,
               label="resid. std", color="#55a868")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=7.5)
        ax.set_title(DATASET_SHORT[ds], fontsize=9)
        ax.set_ylabel("mV")
        ax.axhline(0, color="k", lw=0.6)
        ax.tick_params(axis="y", labelsize=8)
    axes[0].legend(fontsize=7, loc="upper left", frameon=False)
    fig.suptitle("Fig A1 — run-level RMSE / bias / residual std "
                 "(SPMe baseline replay, time-aligned)", fontsize=11, y=1.0)
    fig.savefig(OUT / "fig_a1_run_level_error.png", dpi=160)
    plt.close(fig)


def fig_a2(summary: pd.DataFrame):
    """bias_fraction across datasets (RMSE^2 = Bias^2 + sigma_e^2 exact)."""
    fig, axes = _facet_axes()
    for ax, (ds, g) in zip(axes, summary.groupby("dataset", sort=False)):
        x = np.arange(len(g))
        fracs = g["bias_fraction"]
        ax.bar(x, fracs, 0.6, color=DATASET_COLORS[ds])
        ax.axhline(0.5, color="gray", ls=":", lw=1)
        ax.text(len(g) - 0.5, 0.52, "bias = centered", fontsize=7,
                color="gray", ha="right")
        ax.set_ylim(0, 1.02)
        ax.set_xticks(x)
        ax.set_xticklabels([short_window(w) for w in g["window"]],
                           rotation=55, ha="right", fontsize=7.5)
        ax.set_title(DATASET_SHORT[ds], fontsize=9)
        ax.set_ylabel("bias_fraction = Bias²/RMSE²")
        ax.tick_params(axis="y", labelsize=8)
    fig.suptitle("Fig A2 — systematic vs centered residual share "
                 "(high = steady offset dominates; low = dynamic error)", fontsize=11)
    fig.savefig(OUT / "fig_a2_bias_fraction.png", dpi=160)
    plt.close(fig)


def _per_run_binned(long: pd.DataFrame, xcol: str, n_bins=8) -> pd.DataFrame:
    """Per-run median |residual| over equal-width bins of xcol."""
    rows = []
    for win, g in long.groupby("window"):
        x = g[xcol].to_numpy(dtype=float)
        ae = g["abs_residual_mV"].to_numpy(dtype=float)
        if x.max() <= x.min():
            continue
        edges = np.linspace(x.min(), x.max(), n_bins + 1)
        for a, b in zip(edges[:-1], edges[1:]):
            m = (x >= a) & (x <= b)
            if m.sum() < 10:
                continue
            rows.append({
                "window": win,
                "dataset": g["dataset"].iloc[0],
                "protocol": g["protocol"].iloc[0],
                "x": float((a + b) / 2),
                "median_abs_residual_mV": float(np.median(ae[m])),
            })
    return pd.DataFrame(rows)


def fig_a3(cond: pd.DataFrame, long: pd.DataFrame):
    """|residual| vs |current| (tercile bins; CC = single point)."""
    fig, axes = _facet_axes()
    for ax, (ds, g) in zip(axes, cond.groupby("dataset", sort=False)):
        for win, run in g.groupby("window"):
            prot = run["protocol"].iloc[0]
            if prot == "CC":
                continue  # drawn as a single point below
            ls, mk = PROTOCOL_MARKERS[prot]
            ax.plot(run["bin_edge_low"] + 0.5
                    * (run["bin_edge_high"] - run["bin_edge_low"]),
                    run["RMSE_mV"], ls, marker=mk, ms=4, lw=1.2,
                    color=DATASET_COLORS[ds], alpha=0.9)
        # CC runs: constant current -> a single representative point
        for win, run in long[long["dataset"] == ds].groupby("window"):
            if run["protocol"].iloc[0] != "CC":
                continue
            ax.plot([run["abs_current_A"].median()],
                    [run["abs_residual_mV"].median()],
                    "o", ms=7, mfc="none",
                    color=DATASET_COLORS[ds])
        ax.set_xlabel("|I|  [A]")
        ax.set_ylabel("RMSE in bin [mV]")
        ax.set_title(DATASET_SHORT[ds], fontsize=9)
        ax.tick_params(labelsize=8)
    fig.suptitle("Fig A3 — |residual| vs current load "
                 "(tercile bins per run; open circle = CC run median)",
                 fontsize=11)
    fig.savefig(OUT / "fig_a3_abs_residual_vs_current.png", dpi=160)
    plt.close(fig)


def fig_a4(cond: pd.DataFrame):
    """|residual| vs |dI/dt| (transient-conditioned, quantile bins)."""
    fig, axes = _facet_axes()
    for ax, (ds, g) in zip(axes, cond.groupby("dataset", sort=False)):
        drew = False
        for win, run in g.groupby("window"):
            prot = run["protocol"].iloc[0]
            # CC has no meaningful transients: single low bin only
            if prot == "CC" and len(run) == 1:
                ax.plot(run["bin_edge_high"], run["RMSE_mV"],
                        "o", ms=7, mfc="none", color=DATASET_COLORS[ds])
                drew = True
                continue
            if len(run) < 2:
                continue
            ls, mk = PROTOCOL_MARKERS[prot]
            ax.plot(0.5 * (run["bin_edge_low"] + run["bin_edge_high"]),
                    run["RMSE_mV"], ls, marker=mk, ms=4, lw=1.2,
                    color=DATASET_COLORS[ds], alpha=0.9)
            drew = True
        ax.set_xscale("log")
        ax.set_xlabel("|dI/dt|  [A/s]  (bin mid / run max for CC)")
        ax.set_ylabel("RMSE in bin [mV]")
        ax.set_title(DATASET_SHORT[ds], fontsize=9)
        ax.tick_params(labelsize=8)
        _ = drew
    fig.suptitle("Fig A4 — |residual| vs current-transition rate "
                 "(quantile bins per run)", fontsize=11)
    fig.savefig(OUT / "fig_a4_abs_residual_vs_dIdt.png", dpi=160)
    plt.close(fig)


def fig_a5(progress: pd.DataFrame):
    """residual (bias) vs protocol progress (NOT called SOC)."""
    order = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
    fig, axes = _facet_axes()
    for ax, (ds, g) in zip(axes, progress.groupby("dataset", sort=False)):
        for win, run in g.groupby("window"):
            prot = run["protocol"].iloc[0]
            ls, mk = PROTOCOL_MARKERS[prot]
            run = run.set_index("progress_bin").reindex(order).dropna()
            ax.plot(range(len(run)), run["mean_residual_mV"],
                    ls, marker=mk, ms=3.5, lw=1.2,
                    color=DATASET_COLORS[ds], alpha=0.9)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(range(5))
        ax.set_xticklabels(order, fontsize=7.5)
        ax.set_xlabel("elapsed / protocol progress")
        ax.set_ylabel("mean residual [mV]")
        ax.set_title(DATASET_SHORT[ds], fontsize=9)
        ax.tick_params(labelsize=8)
    fig.suptitle("Fig A5 — residual drift over protocol progress "
                 "(state-dependent drift?)", fontsize=11)
    fig.savefig(OUT / "fig_a5_residual_vs_progress.png", dpi=160)
    plt.close(fig)


def main():
    summary = pd.read_csv(OUT / "run_summary.csv")
    long = pd.read_csv(OUT / "residual_long.csv")
    progress = pd.read_csv(OUT / "progress_error.csv")
    cond_tr = pd.read_csv(OUT / "transient_conditioned.csv")
    cond_cl = pd.read_csv(OUT / "current_load_conditioned.csv")
    fig_a1(summary)
    fig_a2(summary)
    fig_a3(cond_cl, long)
    fig_a4(cond_tr)
    fig_a5(progress)
    print("figures written to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
