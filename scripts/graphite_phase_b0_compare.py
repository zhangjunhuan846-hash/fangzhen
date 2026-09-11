#!/usr/bin/env python3
# ============================================================
# Phase B0 driver: experiment-derived graphite OCP
#
#   SINTEF p-OCV (cycle 1, both branches)
#        -> extraction.ocp_extractor  -> graphite_ocp_{lithiation,
#                                        delithiation}.csv + provenance
#        -> parameters.sintef_graphite_ocp (Ecker2015 + A.5 geometry
#           + measured OCP; diffusivity/kinetics untouched)
#        -> unmodified public runner (battery_sim...run_baseline_cell)
#        -> comparison vs the published Ecker OCP
#
# Window / variant matrix (only physically MEANINGFUL combinations:
# a variant whose OCP table does not cover the window's SOC range is
# skipped and the reason is recorded):
#   pOCV-lith : reference, ocp_lith
#   pOCV-deli : reference, ocp_deli, ocp_mean
#
# Outputs (outputs/analysis/graphite_phaseB0/):
#   graphite_ocp_lithiation.csv / graphite_ocp_delithiation.csv
#   ocp_extraction_provenance.json / ocp_extraction_summary.json
#   ocp_parameter_variants.json
#   runs/<window>_<variant>/{time_aligned.csv, metrics.csv, ...}
#   residual_summary.json / comparison.md
#   fig_ocp_variants.png
#
# Claims verified (from Phase A.5):
#   H1 OCP RANGE  - the reference table tops out at 1.4325 V while the
#                   fresh cell sits at ~3 V.
#   H2 OCP SHAPE  - the reference curve needs x ~ 0.004 to reach 1.0 V.
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extraction.ocp_extractor import extract_ocp_branches, write_ocp_csvs  # noqa: E402
from parameters.sintef_graphite_geometry import (  # noqa: E402
    GEOMETRY_PARAMETER_SET_ID,
    REFERENCE_SET,
    register as register_geometry,
)
from parameters.sintef_graphite_ocp import (  # noqa: E402
    OCP_DELI_ID,
    OCP_LITH_ID,
    OCP_MEAN_ID,
    load_ocp_tables,
    register_variants,
    write_variant_summaries,
)

OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB0"
DATASET = "sintef_graphite"
CELL = "4ccc47"

# Comparison design: the OCP effect must be read off at FIXED geometry.
#   phaseA        published reference OCP + PUBLISHED reference geometry
#                 (= the Phase A baseline, for continuity)
#   A5_reference  Ecker OCP + MEASURED geometry (= Phase A.5)  <- control
#   lith/deli/mean measured OCP + MEASURED geometry (this phase)
BRANCH_ID = {
    "phaseA": REFERENCE_SET,
    "A5_reference": GEOMETRY_PARAMETER_SET_ID,
    "lithiation": OCP_LITH_ID,
    "delithiation": OCP_DELI_ID,
    "mean": OCP_MEAN_ID,
}

# window -> (rate id, branch name, variants in table order)
WINDOWS = {
    "lith": ("pOCV-lith", "lithiation",
             ["phaseA", "A5_reference", "lithiation"]),
    "deli": ("pOCV-deli", "delithiation",
             ["phaseA", "A5_reference", "delithiation", "mean"]),
}

REFERENCE_OCP_TABLE_TOP_V = 1.4325   # Ecker2015 graphite OCP table top

# The initial Li fraction is kept a hair inside the table edge because a
# zero (or full) concentration makes the surface kinetics degenerate at
# t = 0 (j0 ~ sqrt(c) -> 0) and the solver raises
# 'Events [Maximum voltage [V]] are non-positive at initial conditions'.
#
# Phase B0.7 quantified WHY that floor is load-bearing, and why it must
# not simply be made smaller: PyBaMM's initial-state initialisation solves
# for the surface state under the APPLIED current, so its overpotential
# grows without bound as c_s -> 0.  Measured on the p-OCV lithiation
# window (frozen v2 table):
#
#     x0 = 1e-3  -> V(0) = 1.077 V, initial overpotential  ~ -6 mV
#     x0 = 3e-4  -> V(0) = 1.524 V, initial overpotential +126 mV
#     x0 = 1e-4  -> V(0) = 2.186 V, initial overpotential +453 mV
#     x0 = 1e-5  -> initial terminal voltage overshoots the 3.2 V cut-off
#                   and the solve FAILS
#
# So 1e-3 is the smallest floor at which the initial state is clean; a
# smaller one buys a higher V(0) at the price of a spurious, slowly
# decaying initial overpotential.  The residual defect is therefore NOT
# fixed by moving x0 - it is fixed by declaring which part of the window
# the model can represent at all (see WINDOW_START_TOL_V below).
X0_MARGIN = 1e-3

# Phase B0.7 window-start rule: the model's terminal voltage at the
# declared initial state is OCP(x0); measured samples on the FAR side of
# that value (relative to the direction the window traverses) lie outside
# the model's admissible state space and must be reported, not compared.
# 1 mV is the tolerance for "at the start value".
#
# The rule matters because the frozen OCP table's endpoint entries carry
# the current-switch-on polarisation: the measured PRE-branch rest OCP is
# 3.0161 V while the lithiation table's top is 3.0003 V (+15.8 mV), and
# the delithiation window's rest OCP is 0.0824 V while that branch's
# bottom is 0.0967 V (-14.3 mV).  Both ends are outside the table by
# ~15 mV, and on the lithiation side the near-vertical dilute stage turns
# that into a 1.94 V initial-state error (V(0) = 1.077 V) that lands on a
# single comparison point and, by itself, accounted for ~43.6 mV of the
# 44.74 mV lith replay RMSE.
WINDOW_START_TOL_V = 1e-3

REGIONS = [
    ("V_exp<=0.15", 0.0, 0.15),
    ("0.15<V_exp<=0.60", 0.15, 0.60),
    ("0.60<V_exp<=1.43", 0.60, REFERENCE_OCP_TABLE_TOP_V),
    ("V_exp>1.43_outside_ref_table", REFERENCE_OCP_TABLE_TOP_V, np.inf),
]


# ------------------------------------------------------------------
# OCP-consistent initial state (analysis-level proxy; the runner and
# the adapter stay untouched)
# ------------------------------------------------------------------
class OCPConsistentAdapter:
    """
    Delegates to the real adapter but maps the initial Li fraction on
    the OCP TABLE OF THE VARIANT BEING RUN, so that the model starts at
    the measured pre-branch rest OCV as closely as that table allows.

    Only used for the derived variants; the reference run keeps the
    adapter's own (Ecker-inverted) x0.
    """

    def __init__(self, adapter, variant: str, ocp_tables: dict,
                 trim_unrepresentable_prefix: bool = True):
        self._adapter = adapter
        self._variant = variant
        self._tables = ocp_tables
        self._trim = bool(trim_unrepresentable_prefix)
        self.mapping_log: list = []
        self.window_trim_log: list = []

    def __getattr__(self, name):
        return getattr(self._adapter, name)

    def _curve(self):
        """
        (SOC, V) of the variant's own OCP table, unflipped.

        ``mean`` uses the grid both branches share, as in Phase B0.
        """
        if self._variant == "mean":
            lo = max(float(self._tables["lithiation"]["SOC"].min()),
                     float(self._tables["delithiation"]["SOC"].min()))
            hi = min(float(self._tables["lithiation"]["SOC"].max()),
                     float(self._tables["delithiation"]["SOC"].max()))
            grid = np.linspace(lo, hi, 400)
            v_l = np.interp(grid, *[self._tables["lithiation"].sort_values("SOC")[c].to_numpy(float)
                                    for c in ("SOC", "Voltage")])
            v_d = np.interp(grid, *[self._tables["delithiation"].sort_values("SOC")[c].to_numpy(float)
                                    for c in ("SOC", "Voltage")])
            return grid, 0.5 * (v_l + v_d)
        srt = self._tables[
            "lithiation" if self._variant == "lithiation" else "delithiation"
        ].sort_values("SOC")
        return (srt["SOC"].to_numpy(float), srt["Voltage"].to_numpy(float))

    def ocp_at(self, soc: float) -> float:
        """OCP of this variant's own table at a stoichiometry."""
        s, v = self._curve()
        return float(np.interp(float(soc), s, v))

    def _x0_for(self, rest_ocv_V: float):
        soc_tbl, v_tbl = self._curve()
        # tables are monotone decreasing in SOC -> flip to ascending
        order = np.argsort(v_tbl, kind="stable")
        v_asc, soc_asc = v_tbl[order], soc_tbl[order]
        clamped = False
        if rest_ocv_V < v_asc[0]:
            x0 = float(soc_asc[0])
            clamped = True
        elif rest_ocv_V > v_asc[-1]:
            x0 = float(soc_asc[-1])
            clamped = True
        else:
            x0 = float(np.interp(rest_ocv_V, v_asc, soc_asc))
        x0_raw = x0
        x0 = float(np.clip(x0, X0_MARGIN, 1.0 - X0_MARGIN))
        self.mapping_log.append(
            {
                "variant": self._variant,
                "rest_ocv_V": float(rest_ocv_V),
                "x0": x0,
                "x0_before_margin": float(x0_raw),
                "margin_applied": bool(abs(x0 - x0_raw) > 0),
                "clamped_to_table_edge": clamped,
                "table_soc_range": [float(soc_tbl.min()), float(soc_tbl.max())],
                "table_voltage_range": [float(v_tbl.min()), float(v_tbl.max())],
            }
        )
        return x0

    def _trim_prefix(self, df, x0: float):
        """
        Phase B0.7 window-start rule (see WINDOW_START_TOL_V).

        The model's terminal voltage at the declared initial state is
        OCP(x0).  Leading measured samples that lie on the FAR side of
        that value - relative to the direction the window traverses - are
        outside the model's admissible state space, so they are removed
        from the comparison window and reported.  Only a contiguous
        PREFIX is ever removed, and the remaining time/capacity columns
        are re-zeroed so the frame keeps its canonical semantics.
        """
        v_start = self.ocp_at(x0)
        V = df["voltage_V"].to_numpy(float)
        t = df["time_s"].to_numpy(float)
        ascending = float(V[-1]) > float(V[0])
        outside = (V < v_start - WINDOW_START_TOL_V) if ascending \
            else (V > v_start + WINDOW_START_TOL_V)
        k = 0
        while k < len(V) and bool(outside[k]):
            k += 1
        record = {
            "rule": (
                "Phase B0.7: leading samples whose measured terminal "
                "voltage lies on the far side of OCP(x0) (the model's "
                "voltage at the declared initial state), relative to the "
                "window's traversal direction, are outside the model's "
                "admissible state space"
            ),
            "applied": bool(k > 0),
            "variant": self._variant,
            "x0": float(x0),
            "model_start_voltage_V": v_start,
            "traversal_direction": "ascending" if ascending
            else "descending",
            "tolerance_V": WINDOW_START_TOL_V,
            "n_points_removed": int(k),
            "n_points_kept": int(len(V) - k),
            "duration_removed_s": float(t[k - 1] - t[0]) if k else 0.0,
            "duration_total_s": float(t[-1] - t[0]),
            "fraction_removed": float((t[k - 1] - t[0]) / (t[-1] - t[0]))
            if k and t[-1] > t[0] else 0.0,
            "voltage_range_removed_V": (
                [float(np.min(V[:k])), float(np.max(V[:k]))] if k
                else None
            ),
            "reason": (
                "the measured PRE-branch rest OCP lies outside the frozen "
                "OCP table at this end, so no admissible initial Li "
                "fraction reproduces it; the model starts at the table "
                "edge instead.  Recorded, not silently compared."
            ),
            "not_a_fit": (
                "the rule is parameter-based (OCP of the declared initial "
                "state) and pre-registered; nothing is tuned to the "
                "residual"
            ),
        }
        if k == 0:
            self.window_trim_log.append(record)
            return df, record
        out = df.iloc[k:].reset_index(drop=True).copy()
        out.attrs.update(df.attrs)
        t0 = float(out["time_s"].iloc[0])
        out["time_s"] = out["time_s"] - t0
        out["capacity_Ah"] = out["capacity_Ah"] - float(
            out["capacity_Ah"].iloc[0]
        )
        self.window_trim_log.append(record)
        return out, record

    def load_processed_discharge(self, cell, rate):
        df = self._adapter.load_processed_discharge(cell, rate)
        rest = float(df.attrs["provenance"]["rest_ocv_V"])
        x0 = self._x0_for(rest)
        df.attrs["initialisation"]["stoichiometry_from_ocp"] = x0
        df.attrs["provenance"]["initial_stoichiometry_from_ocp"] = x0
        df.attrs["provenance"]["initial_state_source"] = (
            "inverse_ocp_on_variant_table"
        )
        if self._trim:
            df, record = self._trim_prefix(df, x0)
            record["enabled"] = True
            df.attrs["provenance"]["window_start_rule"] = record
            df.attrs["initialisation"]["window_trim"] = record
        else:
            # the rule is still evaluated and recorded, merely not applied,
            # so a rule-off run is auditable on the same terms
            _trimmed, record = self._trim_prefix(df, x0)
            record["enabled"] = False
            record["applied"] = False
            record["note"] = (
                "rule DISABLED by flag: the unrepresentable prefix is "
                "still part of the comparison window"
            )
            df.attrs["provenance"]["window_start_rule"] = record
            df.attrs["initialisation"]["window_trim"] = record
        return df


# ------------------------------------------------------------------
# metrics
# ------------------------------------------------------------------
def _metrics(csv: Path) -> dict:
    df = pd.read_csv(csv)
    res = df["residual_V"].to_numpy(float)
    v_exp_span = float(
        (df["voltage_exp_V"].max() - df["voltage_exp_V"].min()) * 1000.0
    )
    v_sim_span = float(
        (df["voltage_sim_V"].max() - df["voltage_sim_V"].min()) * 1000.0
    )
    q = np.percentile(res * 1000.0, [5, 25, 50, 75, 95])
    return {
        "n_points": int(len(df)),
        "rmse_mV": float(np.sqrt(np.mean(res ** 2)) * 1000.0),
        "mae_mV": float(np.mean(np.abs(res)) * 1000.0),
        "bias_mV": float(np.mean(res) * 1000.0),
        "max_abs_mV": float(np.max(np.abs(res)) * 1000.0),
        "residual_std_mV": float(np.std(res) * 1000.0),
        "residual_skew": float(pd.Series(res).skew()),
        "residual_quantiles_mV": {
            "p05": float(q[0]), "p25": float(q[1]), "p50": float(q[2]),
            "p75": float(q[3]), "p95": float(q[4]),
        },
        "v_exp_start_V": float(df["voltage_exp_V"].iloc[0]),
        "v_exp_end_V": float(df["voltage_exp_V"].iloc[-1]),
        "v_sim_start_V": float(df["voltage_sim_V"].iloc[0]),
        "v_sim_end_V": float(df["voltage_sim_V"].iloc[-1]),
        "v_exp_span_mV": v_exp_span,
        "v_sim_span_mV": v_sim_span,
        "v_sim_span_ratio": float(v_sim_span / v_exp_span) if v_exp_span else float("nan"),
    }


def _region_mae(csv: Path) -> dict:
    df = pd.read_csv(csv)
    out = {}
    for label, lo, hi in REGIONS:
        sel = df[(df["voltage_exp_V"] > lo) & (df["voltage_exp_V"] <= hi)]
        out[label] = {
            "n_points": int(len(sel)),
            "mae_mV": float(np.mean(np.abs(sel["residual_V"])) * 1000.0)
            if len(sel)
            else float("nan"),
        }
    return out


def _run_case(adapter, model, rate, parameter_set, dest: Path):
    from battery_sim.simulation.baseline import run_baseline_cell

    result = run_baseline_cell(
        adapter, model_name=model, cell=CELL, rate=rate,
        parameter_set=parameter_set, plot=True, quiet=False,
    )
    run_dir = Path(result["output_dir"])
    slug = rate.replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    for name in (f"{slug}_time_aligned.csv", f"{slug}_Vt.png",
                 "metrics.csv", "run_metadata.json"):
        src = run_dir / name
        if not src.is_file():
            continue
        target = dest / (f"{slug}_metrics.csv" if name == "metrics.csv"
                        else f"{slug}_{name}" if name == "run_metadata.json"
                        else name)
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)
    csv = dest / f"{slug}_time_aligned.csv"
    # the runner's second rate would be copied too -> keep only ours
    other = [p for p in dest.glob("*_time_aligned.csv") if p.name != csv.name]
    for p in other:
        p.unlink()
    return csv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="SPM")
    ap.add_argument("--cell", default=CELL)
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from battery_sim.registry import get_dataset

    adapter = get_dataset(DATASET)

    # ---------------- 1. extract OCP ----------------
    raw = adapter.load_raw(args.cell)
    result = extract_ocp_branches(raw, cycle=1)
    paths = write_ocp_csvs(
        result, OUT_DIR,
        source_file=raw.attrs["provenance"]["source_file"],
        source_sha256=raw.attrs["provenance"]["source_file_sha256"],
        temperature_source=raw.attrs["provenance"][
            "ambient_temperature_source"
        ],
        extra_provenance={
            "dataset": DATASET,
            "cell": args.cell,
            "scope": "p-OCV cycle 1, both branches (canonical sign)",
            "boundary_conditions": {
                "lithiation_charge_Ah": result["provenance"][
                    "soc_reference_charge_Ah"
                ],
                "voltage_range_V": result["provenance"]["voltage_range_V"],
            },
            "wording": result["provenance"]["wording"],
        },
    )
    prov = result["provenance"]
    print(f"[B0] OCP extracted: lith {len(result['lithiation'])} pts, "
          f"deli {len(result['delithiation'])} pts")
    print(f"     Q_ref = {prov['soc_reference_charge_Ah']*1000:.3f} mAh | "
          f"hysteresis @SOC0.5 = "
          f"{prov['hysteresis_at_soc_mV'].get('SOC_0.50', float('nan')):.1f} mV")
    print(f"     files: {paths['lithiation'].name}, "
          f"{paths['delithiation'].name}, {paths['provenance'].name}")

    # ---------------- 2. derived parameter sets ----------------
    register_geometry(args.cell)            # A.5 geometry-only control set
    variant_ids = register_variants(args.cell)
    write_variant_summaries(OUT_DIR, args.cell)
    print(f"[B0] registered variants: {variant_ids}")

    tables = load_ocp_tables(OUT_DIR)

    # ---------------- 3. run matrix ----------------
    summary = {
        "dataset": DATASET,
        "cell": args.cell,
        "model": args.model,
        "ocp_extraction": {
            k: prov[k] for k in (
                "soc_definition", "soc_reference_charge_mAh", "branch_steps",
                "n_points", "voltage_range_V", "soc_range",
                "hysteresis_proxy_mV", "hysteresis_at_soc_mV",
                "handover_voltage_gap_mV", "rest_ocv_after_lithiation_V",
                "polarization_estimate_at_handover_mV",
            )
        },
        "equilibrium_warning": prov["equilibrium_warning"],
        "variants": {},
        "windows": {},
        "hypotheses": {
            "H1_ocp_range": (
                "Phase A.5 found the reference OCP table tops out at "
                f"{REFERENCE_OCP_TABLE_TOP_V} V while the fresh cell sits at "
                "~3 V; the region V_exp > 1.43 V should collapse when the "
                "measured OCP is used"
            ),
            "H2_ocp_shape": (
                "Phase A.5 found the reference curve needs x ~0.004 to reach "
                "1.0 V; with the measured OCP the delithiation end region "
                "should collapse"
            ),
        },
    }

    for win, (rate, branch, variants) in WINDOWS.items():
        win_block = {}
        curves = {}
        for variant in variants:
            set_id = BRANCH_ID[variant]
            tag = f"{win}_{variant}"
            proxy = (adapter if variant in ("phaseA", "A5_reference")
                     else OCPConsistentAdapter(adapter, variant, tables))
            csv = _run_case(proxy, args.model, rate, set_id,
                            OUT_DIR / "runs" / tag)
            m = _metrics(csv)
            h1 = _region_mae(csv)
            win_block[variant] = {
                "parameter_set": set_id,
                "metrics": m,
                "region_mae_mV": h1,
                "x0_mapping": (proxy.mapping_log
                               if variant not in ("phaseA", "A5_reference")
                               else "adapter default (inverse-OCP on the "
                                    "reference table)"),
            }
            curves[variant] = (csv, m)
        summary["windows"][win] = win_block

        # hypothesis verdicts for this window
        ref = win_block["A5_reference"]["metrics"]
        derived = [v for v in win_block
                   if v not in ("phaseA", "A5_reference")]
        best = min(
            derived,
            key=lambda v: win_block[v]["metrics"]["rmse_mV"],
            default=None,
        )
        verdicts = {}
        if best is not None:
            b = win_block[best]["metrics"]
            verdicts = {
                "best_variant": best,
                "control": "A5_reference (Ecker OCP + measured geometry)",
                "rmse_delta_mV": b["rmse_mV"] - ref["rmse_mV"],
                "rmse_ratio": b["rmse_mV"] / ref["rmse_mV"],
                "rmse_phaseA_mV": win_block["phaseA"]["metrics"]["rmse_mV"],
                "span_ratio_before": ref["v_sim_span_ratio"],
                "span_ratio_after": b["v_sim_span_ratio"],
            }
            for label, _lo, _hi in REGIONS:
                verdicts.setdefault("region_mae_delta_mV", {})[label] = (
                    win_block[best]["region_mae_mV"][label]["mae_mV"]
                    - win_block["A5_reference"]["region_mae_mV"][label]["mae_mV"]
                )
        summary["windows"][win]["verdict"] = verdicts

    with (OUT_DIR / "residual_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ---------------- 4. figure ----------------
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(WINDOWS)
    fig, axes = plt.subplots(n, 3, figsize=(15, 3.6 * n))
    if n == 1:
        axes = axes.reshape(1, 3)
    for i, (win, (rate, branch, variants)) in enumerate(WINDOWS.items()):
        blk = summary["windows"][win]
        # (a) voltage curves
        ax = axes[i, 0]
        any_csv = Path(list(blk.values())[0].get("csv", "")) if False else None
        ref_csv = OUT_DIR / "runs" / f"{win}_A5_reference" / \
            f"{rate.replace('-', '')}_time_aligned.csv"
        df0 = pd.read_csv(ref_csv)
        ax.plot(df0["time_s"] / 3600.0, df0["voltage_exp_V"], "k-", lw=1.6,
                label="experiment")
        colors = {"phaseA": "#888780", "A5_reference": "#E24B4A",
                  "lithiation": "#378ADD", "delithiation": "#1D9E75",
                  "mean": "#BA7517"}
        for variant in variants:
            csv = OUT_DIR / "runs" / f"{win}_{variant}" / \
                f"{rate.replace('-', '')}_time_aligned.csv"
            d = pd.read_csv(csv)
            m = blk[variant]["metrics"]
            ax.plot(d["time_s"] / 3600.0, d["voltage_sim_V"],
                    color=colors[variant], lw=1.1,
                    label=f"{variant}: {m['rmse_mV']:.1f} mV")
        ax.set_ylabel("voltage [V]")
        ax.set_title(f"{win} ({branch}) — OCP variants")
        ax.legend(fontsize=7)
        # (b) residual
        ax2 = axes[i, 1]
        for variant in variants:
            csv = OUT_DIR / "runs" / f"{win}_{variant}" / \
                f"{rate.replace('-', '')}_time_aligned.csv"
            d = pd.read_csv(csv)
            ax2.plot(d["time_s"] / 3600.0, d["residual_V"] * 1000.0,
                     color=colors[variant], lw=1.0, label=variant)
        ax2.axhline(0.0, color="k", lw=0.6)
        ax2.set_title("residual [mV]")
        ax2.legend(fontsize=7)
        # (c) residual distribution
        ax3 = axes[i, 2]
        data = []
        labels = []
        for variant in variants:
            csv = OUT_DIR / "runs" / f"{win}_{variant}" / \
                f"{rate.replace('-', '')}_time_aligned.csv"
            d = pd.read_csv(csv)
            data.append(d["residual_V"].to_numpy(float) * 1000.0)
            labels.append(variant)
        try:  # matplotlib >= 3.9 renamed `labels` -> `tick_labels`
            bp = ax3.boxplot(data, tick_labels=labels, showfliers=False,
                             patch_artist=True)
        except TypeError:
            bp = ax3.boxplot(data, labels=labels, showfliers=False,
                             patch_artist=True)
        for patch, variant in zip(bp["boxes"], variants):
            patch.set_facecolor(colors[variant])
            patch.set_alpha(0.5)
        ax3.axhline(0.0, color="k", lw=0.6)
        ax3.tick_params(axis="x", labelrotation=20, labelsize=8)
        ax3.set_title("residual distribution [mV]")
        for j in range(3):
            axes[i, j].set_xlabel("time [h]" if j < 2 else "")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "fig_ocp_variants.png", dpi=150)
    plt.close(fig)

    # ---------------- 5. comparison.md ----------------
    lines = [
        "# Phase B0 — experiment-derived graphite OCP (Ecker2015 + SINTEF p-OCV)",
        "",
        f"- dataset `{DATASET}` / cell `{args.cell}` / model {args.model}",
        "- geometry: Phase A.5 measured geometry (unchanged)",
        "- diffusivity / kinetics: **unchanged** (no GITT in this phase)",
        f"- OCP extraction: cycle 1, both branches, Q_ref = "
        f"{prov['soc_reference_charge_mAh']:.3f} mAh",
        "",
        "## What the extracted OCP is",
        "",
        f"> {prov['equilibrium_warning']}",
        "",
        f"- hysteresis at fixed SOC: "
        f"{', '.join(f'{k} → {v:.1f} mV' for k, v in prov['hysteresis_at_soc_mV'].items())}",
        f"- hand-over gap (NOT hysteresis): "
        f"{prov['handover_voltage_gap_mV']:.1f} mV",
        f"- C/50 polarisation estimate at the hand-over: "
        f"{prov['polarization_estimate_at_handover_mV']:.1f} mV (recorded only)",
        "",
        "## Results (zero-fit; nothing fitted to any voltage)",
        "",
        "| window | OCP variant | RMSE [mV] | MAE [mV] | bias [mV] | V_sim span [mV] | span ratio |",
        "|---|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for variant, entry in blk.items():
            if variant == "verdict":
                continue
            m = entry["metrics"]
            lines.append(
                f"| {win} | {variant} | **{m['rmse_mV']:.2f}** | "
                f"{m['mae_mV']:.2f} | {m['bias_mV']:.2f} | "
                f"{m['v_sim_span_mV']:.1f} | {m['v_sim_span_ratio']:.3f} |"
            )
    lines += [
        "",
        "## Residual distribution (mV)",
        "",
        "| window | variant | std | p05 | p50 | p95 | max abs |",
        "|---|---|---|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        for variant, entry in blk.items():
            if variant == "verdict":
                continue
            m = entry["metrics"]
            q = m["residual_quantiles_mV"]
            lines.append(
                f"| {win} | {variant} | {m['residual_std_mV']:.2f} | "
                f"{q['p05']:.2f} | {q['p50']:.2f} | {q['p95']:.2f} | "
                f"{m['max_abs_mV']:.2f} |"
            )
    lines += [
        "",
        "## Residual by experimental-voltage region (MAE, mV)",
        "",
        "The `V_exp>1.43` region is exactly where the published reference OCP",
        "table has no data (H1).",
        "",
        "| window | region | A5 control (Ecker OCP) | best derived OCP |",
        "|---|---|---|---|",
    ]
    for win, blk in summary["windows"].items():
        verdict = blk.get("verdict") or {}
        best = verdict.get("best_variant")
        for label, _lo, _hi in REGIONS:
            lines.append(
                f"| {win} | {label} | "
                f"{blk['A5_reference']['region_mae_mV'][label]['mae_mV']:.2f} | "
                + (f"{blk[best]['region_mae_mV'][label]['mae_mV']:.2f} |"
                   if best else "— |")
            )
    lines += ["", "## Hypothesis check (Phase A.5 findings)", ""]
    for win, blk in summary["windows"].items():
        verdict = blk.get("verdict") or {}
        if not verdict:
            continue
        lines += [
            f"**{win}**: best derived variant `{verdict['best_variant']}`",
            f"- control (Ecker OCP, measured geometry) RMSE "
            f"{blk['A5_reference']['metrics']['rmse_mV']:.2f} → "
            f"{blk[verdict['best_variant']]['metrics']['rmse_mV']:.2f} mV "
            f"(×{verdict['rmse_ratio']:.2f})",
            f"- V_sim span ratio {verdict['span_ratio_before']:.3f} → "
            f"{verdict['span_ratio_after']:.3f}",
            "- region MAE change [mV]: "
            + ", ".join(f"{k} {v:+.2f}"
                        for k, v in verdict.get("region_mae_delta_mV",
                                                {}).items()),
            "",
        ]
    lines += [
        "## Wording (mandatory)",
        "",
        "The derived OCP is an **experiment-derived pseudo-OCP** for this",
        "electrode at the declared room temperature. It is not a material",
        "constant and not validation. Diffusivity and kinetics are still the",
        "published reference values, so any residual left in the low-voltage",
        "region is a hypothesis for Phase B1 (GITT), not a conclusion.",
        "",
    ]
    (OUT_DIR / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    for win, blk in summary["windows"].items():
        verdict = blk.get("verdict") or {}
        if verdict:
            print(f"[B0] {win}: control {blk['A5_reference']['metrics']['rmse_mV']:.2f} "
                  f"-> {verdict['best_variant']} "
                  f"{blk[verdict['best_variant']]['metrics']['rmse_mV']:.2f} mV "
                  f"(x{verdict['rmse_ratio']:.2f})")
    print(f"[B0] outputs: {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    from scripts._output_isolation import isolate_platform_outputs
    isolate_platform_outputs(OUT_DIR / "platform_runs")
    raise SystemExit(main())
