"""G6.1c -- GITT excitation map: which window can actually resolve D_s?

WHERE THIS SITS
    G6.1a asked "does the trajectory respond to D_s(x) at all?" (activity).
    G6.1b-1 asked "does the inverse problem have a minimum of finite
    width?" and answered: not really -- on the two windows tested, the 1 mV
    band is 0.14 to 1.01 dex wide, and one-sided.

    G6.1c turns that single measurement into a MAP over the whole record.
    The 239 discharge pulse-rest windows of the DLR GITT each get one
    number:

        B_i = width, in dex of the D_s multiplier, of the set
              { RMSE_model-to-model <= 1 mV } around a0 = 0

    That is the resolution at which window i can speak about the parameter
    at all.  A window whose B is 1 dex cannot distinguish D_s from 10x D_s;
    a window whose B is 0.1 dex can.

WHY A MAP AND NOT A BIGGER PARAMETER VECTOR
    Nothing here adds a parameter.  The global multiplier is one direction
    in function space, and every window measures THE SAME direction -- so
    the map buys precision, not dimension.  What it does buy is the answer
    to a question that decides the next step:

        does this dataset CONTAIN an excitation that identifies D_s,
        or is the limitation in the physics of the cell?

    If no window gets below the G6.1b-1 limit, then enlarging the
    parameter vector is provably pointless: adding coefficients adds
    directions, not information, and a direction with no information has
    an infinitely wide band.  If some window does get below it, G6.1b-2
    has a home and we know which window to build it on.

WHAT IS HELD FIXED (so the map varies ONE thing)
    * capacity scale -- one alignment recipe, computed once from the sweep
      reference charge and applied to every window (Q_model == Q_measured)
    * model -- SPM, one parameter set, one temperature channel
    * only the window (i.e. the state and the local OCP slope) changes

PRE-REGISTERED CRITERIA (fixed before the run):
    M1 existence      at least one window with B <= 0.30 dex, not truncated
    M2 screening      the top-10 windows by MEASURED |dV_pulse| and the
                      top-10 by B share at least 5 members.  This is what
                      decides whether window selection needs the model at
                      all, or can be read off the recorded transient.
    M3 one-sidedness  the median of the cost-curve asymmetry over windows
                      is NEGATIVE (raising D_s is cheaper than lowering it)
    M4 resolution     the median band resolution <= 0.10 dex, i.e. the
                      printed widths are read off a grid fine enough to
                      mean something
    N1 negative       zero-excitation windows: the cost surface is EXACTLY
                      flat and the band is truncated on both sides

Usage:
    python scripts/graphite/g6_1c_excitation_map.py [--sweep discharge|charge|both]
                                                    [--out outputs/fitting/g6.1c]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import battery_sim.paths as paths  # noqa: E402

from battery_sim.models.pybamm_factory import resolve_model_options  # noqa: E402
from battery_sim.registry import get_dataset  # noqa: E402
from governance.scale_alignment import (  # noqa: E402
    PIPELINE_STAGES,
    alignment_overrides,
    audit,
)
from identification.recovery_stats import (  # noqa: E402
    band_width,
    curvature_stats,
    probe_grid,
)
from identification.replay_scan import (  # noqa: E402
    DS_KEY,
    MIN_COVERAGE,
    MultiplierScan,
)

#: The identifiability level, in mV of model-to-model RMSE.  Deliberately
#: the SAME number G6.1b-1 used for its I1 criterion: a map measured at a
#: different level would not be comparable with the gate that motivated it.
BAND_LEVEL_MV = 1.0
BAND_MAX_DEX = 0.30
TOP_K = 10
MIN_SCREEN_OVERLAP = int(TOP_K * 0.5)
MIN_SOC_GAP = 0.05
MAX_SUBSET = 8
ASYMMETRY_H_DEX = 0.02
NEGATIVE_WINDOWS = 3
SPREAD_LEVELS_DEX = (-0.5, 0.0, 0.5)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def summarise_window(scan: MultiplierScan, grid: np.ndarray) -> Dict[str, Any]:
    """One row of the map: the band, its resolution, and its one-sidedness."""
    recs = [scan.evaluate(float(a)) for a in grid]
    reach = np.array([scan.reachable(r) for r in recs], dtype=bool)
    used = grid[reach]
    row: Dict[str, Any] = {
        "protocol_id": scan.protocol_id,
        "n_reference_points": int(scan.n_ref),
        "n_grid_points": int(grid.size),
        "n_unreachable": int((~reach).sum()),
        "unreachable_dex": [float(x) for x in grid[~reach]],
        "coverage_min": float(min(r["coverage_fraction"] for r in recs)),
    }

    if used.size < 3 or not (used.min() <= 0.0 <= used.max()):
        row["band"] = band_width(used, np.zeros(used.size), 0.0,
                                 BAND_LEVEL_MV ** 2)
        row["applicable"] = False
        return row

    # Two reference points, at ZERO extra simulation cost: V(-0.5) is one
    # of the probe points, so the second cost curve comes out of the same
    # cache.  Both are reported because the band depends on where in the
    # valley it is measured -- the same window that needs 0.35 dex at
    # a0 = 0 needs 0.14 dex at a0 = -0.5 (G6.1b-1), and a map with only
    # one column would hide that.
    for tag, truth in (("", 0.0), ("_alt", -0.5)):
        if not (used.min() <= truth <= used.max()):
            row[f"band{tag}"] = {
                "width_dex": float("nan"), "left_dex": float("nan"),
                "right_dex": float("nan"), "truncated_left": True,
                "truncated_right": True, "truncated": True,
                "resolution_dex": float("nan"), "n_points": 0,
            }
            row[f"cost_at_truth{tag}_mV2"] = float("nan")
            row[f"J_max{tag}_mV2"] = float("nan")
            row[f"peak_model_to_model_rmse{tag}_mV"] = float("nan")
            continue
        Jt = np.array([scan.cost(float(a), truth) for a in used])
        jmax = float(np.nanmax(Jt[np.isfinite(Jt)]))
        row[f"band{tag}"] = band_width(used, Jt, truth, BAND_LEVEL_MV ** 2)
        row[f"cost_at_truth{tag}_mV2"] = float(scan.cost(truth, truth))
        row[f"J_max{tag}_mV2"] = jmax
        row[f"peak_model_to_model_rmse{tag}_mV"] = float(
            math.sqrt(max(jmax, 0.0))
        )
    row["curvature"] = curvature_stats(
        lambda a: scan.cost(float(a), 0.0), 0.0, ASYMMETRY_H_DEX
    )
    # the same observable G6.1a reported: the dV_pulse spread over the
    # +/-0.5 dex stencil.  Reported so the two stages stay comparable.
    dv = {}
    for a in SPREAD_LEVELS_DEX:
        dv[float(a)] = scan.evaluate(float(a))["dv_pulse_mV"]
    finite = [v for v in dv.values() if v is not None and np.isfinite(v)]
    row["dv_pulse_vs_a_mV"] = dv
    row["dv_pulse_spread_mV"] = (
        float(max(finite) - min(finite)) if len(finite) >= 2 else float("nan")
    )
    row["applicable"] = True
    return row


def pick_subset(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """SOC-diverse windows that are individually identifiable.

    RULE (stated so the choice is reviewable, not hand-picked): take the
    windows with B <= BAND_MAX_DEX and not truncated, in order of
    increasing B, and keep a window only if its pre-pulse lithiation
    fraction is at least MIN_SOC_GAP away from every window already kept.
    """
    cand = [
        r for r in rows
        if r.get("applicable")
        and np.isfinite(r["band"]["width_dex"])
        and r["band"]["width_dex"] <= BAND_MAX_DEX
        and not r["band"]["truncated"]
        and np.isfinite(r.get("soc_lithiation_fraction", float("nan")))
    ]
    cand.sort(key=lambda r: r["band"]["width_dex"])
    kept: List[Dict[str, Any]] = []
    for r in cand:
        x = float(r["soc_lithiation_fraction"])
        if all(abs(x - float(k["soc_lithiation_fraction"])) >= MIN_SOC_GAP
               for k in kept):
            kept.append(r)
            if len(kept) >= MAX_SUBSET:
                break
    return kept


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation without scipy, so the number is reproducible here."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size < 3:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    den = math.sqrt(float((rx ** 2).sum()) * float((ry ** 2).sum()))
    return float((rx * ry).sum() / den) if den > 0 else float("nan")


def make_figure(df: pd.DataFrame, subset: List[Dict[str, Any]], out_png: Path,
                sweep: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    ok = df[df["applicable"] == True]  # noqa: E712
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 9))
    fig.suptitle(
        f"G6.1c  excitation map -- DLR GITT {sweep} sweep, "
        f"{len(ok)} pulse-rest windows",
        fontsize=13,
    )

    ax = axes[0][0]
    sc = ax.scatter(ok["soc_lithiation_fraction"], ok["band_width_dex"],
                    c=ok["measured_abs_dv_pulse_mV"], cmap="viridis",
                    norm=LogNorm(), s=26, edgecolor="none")
    ax.set_yscale("log")
    ax.axhline(BAND_MAX_DEX, color="crimson", ls="--", lw=1)
    ax.text(0.012, BAND_MAX_DEX * 1.06, "0.30 dex limit (G6.1b-1 I1)",
            color="crimson", fontsize=8)
    ax.set_xlabel("pre-pulse lithiation fraction x0")
    ax.set_ylabel("1 mV band width  B  (dex)")
    ax.set_title("(a) resolution vs state", fontsize=10)
    fig.colorbar(sc, ax=ax, label="measured |dV_pulse| (mV)", fraction=0.046)

    ax = axes[0][1]
    m = np.isfinite(ok["measured_abs_dv_pulse_mV"]) & \
        np.isfinite(ok["band_width_dex"])
    ax.scatter(ok["measured_abs_dv_pulse_mV"][m], ok["band_width_dex"][m],
               s=22, color="#0F6E56", edgecolor="none")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.axhline(BAND_MAX_DEX, color="crimson", ls="--", lw=1)
    rho = spearman(ok["measured_abs_dv_pulse_mV"].to_numpy(float),
                   ok["band_width_dex"].to_numpy(float))
    ax.set_xlabel("measured |dV_pulse| (mV)")
    ax.set_ylabel("1 mV band width  B  (dex)")
    ax.set_title(f"(b) can the record screen windows?  rho = {rho:+.3f}",
                 fontsize=10)

    ax = axes[1][0]
    ax.scatter(ok["soc_lithiation_fraction"], ok["asymmetry"],
               s=22, color="#7F77DD", edgecolor="none")
    ax.axhline(0.0, color="gray", lw=0.8)
    ax.set_xlabel("pre-pulse lithiation fraction x0")
    ax.set_ylabel("(J(+h) - J(-h)) / (J(+h) + J(-h))")
    ax.set_title("(c) one-sidedness (negative = raising D_s is cheaper)",
                 fontsize=10)

    ax = axes[1][1]
    ax.hist(ok["band_width_dex"], bins=32, color="#D85A30", edgecolor="white")
    ax.axvline(BAND_MAX_DEX, color="crimson", ls="--", lw=1)
    ax.set_xlabel("1 mV band width  B  (dex)")
    ax.set_ylabel("windows")
    ax.set_title(f"(d) distribution; {int((ok['band_width_dex'] <= BAND_MAX_DEX).sum())}"
                 f" below the limit, "
                 f"{int(((ok['band_width_dex'] <= BAND_MAX_DEX) & (ok['band_truncated'] == False)).sum())} of them closed"  # noqa: E712
                 f" of {len(ok)}", fontsize=10)

    if subset:
        ax = axes[0][0]
        ax.scatter([r["soc_lithiation_fraction"] for r in subset],
                   [r["band"]["width_dex"] for r in subset],
                   facecolor="none", edgecolor="crimson", s=110, lw=1.4,
                   label="recommended subset")
        ax.legend(fontsize=8, loc="upper right")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="discharge",
                    choices=("discharge", "charge", "both"))
    ap.add_argument("--out", default="outputs/fitting/g6.1c")
    ap.add_argument("--limit", type=int, default=0,
                    help="debug: only the first N windows per sweep")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    paths.PLATFORM_OUTPUT_ROOT = out / "platform_runs"

    sweeps = (["discharge", "charge"] if args.sweep == "both"
              else [args.sweep])

    tic = time.perf_counter()
    report: Dict[str, Any] = {
        "gate": "G6.1c",
        "claim": (
            "which recorded excitation can resolve D_s at all?  the map "
            "decides whether enlarging the parameter vector could ever help"
        ),
        "representation": "log10 D_s(x) = log10 D_ref(x) + a0,  phi_0(x) = 1",
        "ds_key": DS_KEY,
        "band_level_mV": BAND_LEVEL_MV,
        "band_max_dex": BAND_MAX_DEX,
        "probe_grid_dex": [float(x) for x in probe_grid()],
        "asymmetry_h_dex": ASYMMETRY_H_DEX,
        "criteria": {
            "M1_existence": f"at least one window with B <= {BAND_MAX_DEX} dex",
            "M1b_existence_at_minus_half": (
                "same, at the reference point a0 = -0.5 -- ADDED after the "
                "3-window smoke test showed the a0 = 0 band is the wider "
                "one; reported as secondary, it does not replace M1"
            ),
            "M2_screening": (
                f"top-{TOP_K} by measured |dV_pulse| and top-{TOP_K} by B "
                f"share >= {MIN_SCREEN_OVERLAP}"
            ),
            "M3_one_sidedness": "median cost-curve asymmetry < 0",
            "M4_resolution": "median band resolution <= 0.10 dex",
            "N1_negative": "zero-excitation windows are exactly flat",
        },
        "pipeline_stages": list(PIPELINE_STAGES),
        "sweeps": {},
        "negative_control": {},
    }

    log("=" * 92)
    log("G6.1c  GITT excitation map -- which window can resolve D_s?")
    log("=" * 92)
    log(f"  pipeline: {' -> '.join(PIPELINE_STAGES)}")

    adapter = get_dataset("dlr_gitt")
    ps = adapter.config.parameter_set
    model_options = resolve_model_options(adapter)
    cell = "Hydra.0b_A"

    # ---- stages 1-2: ONE alignment recipe for the whole map ---------
    log("")
    log("-" * 92)
    log("stage 1-2  geometry audit + capacity alignment (held FIXED)")
    log("-" * 92)
    al_rec = audit(adapter, "GITT-discharge", cell)
    align = alignment_overrides(adapter, "GITT-discharge", cell)
    log(f"  model capacity    : {al_rec['model_capacity_Ah'] * 1e3:.3f} mAh")
    log(f"  measured charge   : {al_rec['measured_charge_Ah'] * 1e3:.4f} mAh "
        f"over '{al_rec['charge_reference']}'")
    log(f"  verdict           : {al_rec['verdict'].upper()} "
        f"(x{al_rec['capacity_ratio_model_over_measured']:.1f})")
    log(f"  C-rate as read    : C/{1.0 / al_rec['c_rate_on_cell']:.1f}   "
        f"on model: C/{1.0 / al_rec['c_rate_on_model_unscaled']:.0f}")
    log(f"  footprint         : area x{align['footprint_scale_area']:.6f} "
        f"(one recipe, every window)")
    report["scale_alignment"] = al_rec

    grid = probe_grid()
    table = adapter.triplets()
    rows_all: List[Dict[str, Any]] = []

    for sweep in sweeps:
        idx = sorted(int(k) for k in table[table["sweep"] == sweep]["triplet"])
        if args.limit:
            idx = idx[:args.limit]
        log("")
        log("-" * 92)
        log(f"[{sweep}] {len(idx)} pulse-rest windows, "
            f"{len(grid)} probe points each")
        log("-" * 92)

        sweep_tic = time.perf_counter()
        for n, k in enumerate(idx, start=1):
            pid = f"GITT-{sweep}#t{k}"
            meta = table[table["triplet"] == k].iloc[0]
            try:
                df = adapter.load_processed_protocol(cell, pid)
                protocol = adapter.load_protocol(pid)
                scan = MultiplierScan(adapter, cell, pid, df, protocol, ps,
                                      model_options, align)
                row = summarise_window(scan, grid)
                init = df.attrs.get("initialisation", {}) or {}
                row.update({
                    "sweep": sweep,
                    "triplet": int(k),
                    "n_simulations": scan.n_sim,
                    "soc_lithiation_fraction": float(
                        init.get("stoichiometry_from_ocp", float("nan"))
                    ),
                    "ocp_voltage_V": float(init.get("ocp_voltage_V", float("nan"))),
                    "edge_fallback": bool(init.get("ocp_table_edge_fallback", False)),
                    "v_pre_V": float(meta["v_pre_V"]),
                    "measured_dv_pulse_mV": float(meta["dv_pulse_mV"]),
                    "measured_dv_relax_mV": float(meta["dv_relax_mV"]),
                    "measured_abs_dv_pulse_mV": abs(float(meta["dv_pulse_mV"])),
                    "pulse_s": float(meta["pulse_s"]),
                    "rest_before_s": float(meta["rest_before_s"]),
                    "rest_after_s": float(meta["rest_after_s"]),
                    "pulse_current_A": float(meta["current_A"]),
                    "pulse_c_rate": float(
                        abs(meta["current_A"]) / al_rec["measured_charge_Ah"]
                    ),
                })
            except Exception as exc:                    # noqa: BLE001
                log(f"    t{k}: FAILED {type(exc).__name__}: {exc}")
                row = {
                    "sweep": sweep, "triplet": int(k), "protocol_id": pid,
                    "applicable": False, "error": f"{type(exc).__name__}: {exc}",
                }
            rows_all.append(row)
            if n % 20 == 0 or n == len(idx):
                okb = [r for r in rows_all if r.get("applicable")
                       and np.isfinite(r.get("band", {}).get("width_dex",
                                                              float("nan")))]
                best = min((r["band"]["width_dex"] for r in okb), default=float("nan"))
                log(f"    {n:4d}/{len(idx)}  elapsed {time.perf_counter() - sweep_tic:6.1f} s"
                    f"  applicable {len(okb):4d}  best B {best:.4f} dex")
                # checkpoint: this sweep takes tens of minutes, and a crash
                # on the last window must not lose the map.  The derived
                # columns are materialised here too, so the partial file is
                # readable (and plottable) on its own.
                part = pd.DataFrame(
                    [r for r in rows_all if r["sweep"] == sweep]
                )
                for col, key, pick in (
                    ("band_width_dex", "band", "width_dex"),
                    ("band_truncated", "band", "truncated"),
                    ("band_alt_width_dex", "band_alt", "width_dex"),
                    ("band_alt_truncated", "band_alt", "truncated"),
                ):
                    part[col] = part[key].map(
                        lambda b, k=pick: (b.get(k, float("nan"))
                                           if isinstance(b, dict)
                                           else float("nan"))
                    )
                part.drop(columns=["band", "band_alt", "curvature",
                                   "dv_pulse_vs_a_mV"],
                          errors="ignore").to_csv(
                    out / f"g6_1c_window_map_{sweep}.partial.csv", index=False)

        # ---- negative control inside the same sweep ------------------
        neg_rows = []
        for k in idx[:NEGATIVE_WINDOWS]:
            pid = f"GITT-{sweep}#t{k}"
            df = adapter.load_processed_protocol(cell, pid)
            protocol = adapter.load_protocol(pid)
            scan = MultiplierScan(adapter, cell, pid, df, protocol, ps,
                                  model_options, align, zero_current=True)
            r = summarise_window(scan, grid)
            recs = [scan.evaluate(float(a)) for a in grid]
            ref = recs[0]["V_ref"]
            dev = 0.0
            for rr in recs[1:]:
                m = np.isfinite(ref) & np.isfinite(rr["V_ref"])
                if m.any():
                    dev = max(dev, float(np.max(np.abs(ref[m] - rr["V_ref"][m]))) * 1e3)
            neg_rows.append({
                "protocol_id": pid,
                "triplet": int(k),
                "max_abs_dV_across_a_mV": dev,
                "band_width_dex": r["band"]["width_dex"],
                "truncated_left": r["band"]["truncated_left"],
                "truncated_right": r["band"]["truncated_right"],
                "flat": bool(dev == 0.0),
                "n_simulations": int(scan.n_sim),
            })
            log(f"    negative {pid}: max|dV| {dev:.3e} mV, "
                f"band {r['band']['width_dex']}, "
                f"trunc L/R {r['band']['truncated_left']}/{r['band']['truncated_right']}")
        report["negative_control"][sweep] = {
            "windows": neg_rows,
            "all_flat": bool(all(x["flat"] for x in neg_rows)),
            "all_both_sides_truncated": bool(all(
                x["truncated_left"] and x["truncated_right"] for x in neg_rows
            )),
            "n_simulations": int(sum(x["n_simulations"] for x in neg_rows)),
        }

        df_map = pd.DataFrame(rows_all)
        sweep_df = df_map[df_map["sweep"] == sweep].copy()
        # derived columns go on the WHOLE per-sweep frame, not on the
        # applicable subset: a window that failed must still be visible in
        # the CSV and the figure rather than dropped silently
        for col, pick in (
            ("band_width_dex", "width_dex"),
            ("band_left_dex", "left_dex"),
            ("band_right_dex", "right_dex"),
            ("band_truncated", "truncated"),
            ("band_truncated_right", "truncated_right"),
            ("band_resolution_dex", "resolution_dex"),
        ):
            sweep_df[col] = sweep_df["band"].map(
                lambda b, k=pick: (b.get(k, float("nan"))
                                   if isinstance(b, dict) else float("nan"))
            )
        for col, pick in (
            ("asymmetry", "curvature_asymmetry"),
            ("Jpp", "curvature_Jpp_mV2_per_dex2"),
        ):
            sweep_df[col] = sweep_df["curvature"].map(
                lambda c, k=pick: (c.get(k, float("nan"))
                                   if isinstance(c, dict) else float("nan"))
            )
        # the second reference point (see summarise_window): free, and it
        # is the column that says whether ANY window resolves D_s well
        for col, pick in (
            ("band_alt_width_dex", "width_dex"),
            ("band_alt_truncated", "truncated"),
            ("band_alt_resolution_dex", "resolution_dex"),
        ):
            sweep_df[col] = sweep_df["band_alt"].map(
                lambda b, k=pick: (b.get(k, float("nan"))
                                   if isinstance(b, dict) else float("nan"))
            )
        ok = sweep_df[sweep_df["applicable"] == True]  # noqa: E712

        finite_band = ok[np.isfinite(ok["band_width_dex"])]
        ranked = finite_band.sort_values("band_width_dex")
        by_signal = ok.sort_values("measured_abs_dv_pulse_mV", ascending=False)
        top_band = set(ranked.head(TOP_K)["triplet"].tolist())
        top_signal = set(by_signal.head(TOP_K)["triplet"].tolist())
        overlap = sorted(top_band & top_signal)

        subset = pick_subset(ranked.to_dict("records"))
        rho_meas = spearman(ok["measured_abs_dv_pulse_mV"].to_numpy(float),
                            ok["band_width_dex"].to_numpy(float))
        rho_model = spearman(ok["dv_pulse_spread_mV"].to_numpy(float),
                             ok["band_width_dex"].to_numpy(float))
        asym_med = float(np.nanmedian(ok["asymmetry"].to_numpy(float)))
        res_med = float(np.nanmedian(ok["band_resolution_dex"].to_numpy(float)))
        n_below = int((finite_band["band_width_dex"] <= BAND_MAX_DEX).sum())
        # NOTE: ``~`` on a boolean column that also holds NaN is not a
        # negation (it goes through Python bools and returns -2/-1, which
        # are truthy).  Compare to False explicitly.
        n_below_nt = int(((finite_band["band_width_dex"] <= BAND_MAX_DEX)
                          & (finite_band["band_truncated"] == False)).sum())  # noqa: E712
        alt = ok[np.isfinite(ok["band_alt_width_dex"])]
        n_below_alt = int((alt["band_alt_width_dex"] <= BAND_MAX_DEX).sum())
        n_below_alt_nt = int(((alt["band_alt_width_dex"] <= BAND_MAX_DEX)
                              & (alt["band_alt_truncated"] == False)).sum())  # noqa: E712
        rho_alt = spearman(ok["measured_abs_dv_pulse_mV"].to_numpy(float),
                           ok["band_alt_width_dex"].to_numpy(float))
        # POST-HOC, added after seeing that M2 failed: is there a RECORDED
        # quantity that screens windows better than the raw amplitude?  It
        # does not enter any criterion, and it is named posthoc_* so that a
        # reader can see it was not part of the pre-registration.
        dvp = ok["measured_abs_dv_pulse_mV"].to_numpy(float)
        dvr = np.abs(ok["measured_dv_relax_mV"].to_numpy(float))
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(dvp > 0, dvr / dvp, np.nan)
        rho_relax_ratio = spearman(ratio, ok["band_width_dex"].to_numpy(float))
        rho_relax_abs = spearman(dvr, ok["band_width_dex"].to_numpy(float))

        report["sweeps"][sweep] = {
            "n_windows": int(len(idx)),
            "n_applicable": int(len(ok)),
            "n_errors": int(sum(1 for r in rows_all
                                if r["sweep"] == sweep and "error" in r)),
            "band_min_dex": (float(finite_band["band_width_dex"].min())
                             if len(finite_band) else float("nan")),
            "band_median_dex": (float(finite_band["band_width_dex"].median())
                                if len(finite_band) else float("nan")),
            "band_max_dex": (float(finite_band["band_width_dex"].max())
                             if len(finite_band) else float("nan")),
            "n_below_limit": n_below,
            "n_below_limit_untruncated": n_below_nt,
            "band_alt_min_dex": (float(alt["band_alt_width_dex"].min())
                                 if len(alt) else float("nan")),
            "band_alt_median_dex": (float(alt["band_alt_width_dex"].median())
                                    if len(alt) else float("nan")),
            "n_below_limit_alt": n_below_alt,
            "n_below_limit_alt_untruncated": n_below_alt_nt,
            "spearman_band_alt_vs_measured_dv": rho_alt,
            "posthoc_spearman_band_vs_relax_ratio": rho_relax_ratio,
            "posthoc_spearman_band_vs_relax_abs": rho_relax_abs,
            "posthoc_note": (
                "the two posthoc_* numbers were added AFTER M2 failed, to "
                "test whether some other RECORDED quantity screens windows "
                "better than the raw pulse amplitude.  They feed no "
                "criterion."
            ),
            "n_truncated_any": int(ok["band"].map(
                lambda b: bool(b["truncated"])).sum()),
            "n_truncated_right": int(ok["band"].map(
                lambda b: bool(b["truncated_right"])).sum()),
            "n_never_crossed_1mV": int(sum(
                1 for r in rows_all
                if r["sweep"] == sweep and r.get("applicable") is False
                and "error" not in r
            )),
            "spearman_band_vs_measured_dv": rho_meas,
            "spearman_band_vs_model_spread": rho_model,
            "median_asymmetry": asym_med,
            "median_band_resolution_dex": res_med,
            "top_k": TOP_K,
            "top_by_band": [
                {"protocol_id": r["protocol_id"], "triplet": int(r["triplet"]),
                 "band_dex": float(r["band_width_dex"]),
                 "resolution_dex": float(r["band_resolution_dex"]),
                 "truncated": bool(r["band_truncated"]),
                 "soc_lithiation_fraction": float(r["soc_lithiation_fraction"]),
                 "v_pre_V": float(r["v_pre_V"]),
                 "measured_abs_dv_pulse_mV": float(r["measured_abs_dv_pulse_mV"]),
                 "measured_dv_relax_mV": float(r["measured_dv_relax_mV"]),
                 "pulse_c_rate": float(r["pulse_c_rate"])}
                for r in ranked.head(TOP_K).to_dict("records")
            ],
            "top_by_measured_signal": [
                {"protocol_id": r["protocol_id"], "triplet": int(r["triplet"]),
                 "measured_abs_dv_pulse_mV": float(r["measured_abs_dv_pulse_mV"]),
                 "band_dex": float(r["band_width_dex"])}
                for r in by_signal.head(TOP_K).to_dict("records")
            ],
            "screen_overlap": [int(x) for x in overlap],
            "screen_overlap_n": int(len(overlap)),
            "recommended_subset": [
                {"protocol_id": r["protocol_id"], "triplet": int(r["triplet"]),
                 "band_dex": float(r["band_width_dex"]),
                 "soc_lithiation_fraction": float(r["soc_lithiation_fraction"]),
                 "v_pre_V": float(r["v_pre_V"]),
                 "measured_abs_dv_pulse_mV": float(r["measured_abs_dv_pulse_mV"])}
                for r in subset
            ],
            "subset_rule": (
                f"B <= {BAND_MAX_DEX} dex and not truncated, sorted by B "
                f"ascending, keeping a window only if its pre-pulse "
                f"lithiation fraction is >= {MIN_SOC_GAP} away from every "
                f"window already kept (max {MAX_SUBSET})"
            ),
            "runtime_s": time.perf_counter() - sweep_tic,
        }

        csv_cols = [
            "sweep", "triplet", "protocol_id", "applicable", "error",
            "soc_lithiation_fraction", "v_pre_V", "ocp_voltage_V",
            "edge_fallback", "measured_dv_pulse_mV", "measured_abs_dv_pulse_mV",
            "measured_dv_relax_mV", "pulse_s", "rest_before_s", "rest_after_s",
            "pulse_current_A", "pulse_c_rate", "n_unreachable", "coverage_min",
            "cost_at_truth_mV2", "peak_model_to_model_rmse_mV",
            "band_width_dex", "band_left_dex", "band_right_dex",
            "band_truncated", "band_resolution_dex", "asymmetry", "Jpp",
            "band_alt_width_dex", "band_alt_truncated",
            "band_alt_resolution_dex", "dv_pulse_spread_mV", "n_simulations",
        ]
        path = out / f"g6_1c_window_map_{sweep}.csv"
        sweep_df.reindex(columns=csv_cols).to_csv(path, index=False)
        log(f"  wrote {path}")

        png = out / f"g6_1c_excitation_map_{sweep}.png"
        make_figure(sweep_df, subset, png, sweep)
        log(f"  wrote {png}")

        log("")
        log(f"  [{sweep}] applicable {len(ok)}/{len(idx)}  "
            f"B min {report['sweeps'][sweep]['band_min_dex']:.4f} / "
            f"median {report['sweeps'][sweep]['band_median_dex']:.4f} dex")
        log(f"  [{sweep}] below {BAND_MAX_DEX} dex: {n_below} "
            f"({n_below_nt} untruncated)")
        log(f"  [{sweep}] alt (a0=-0.5) min "
            f"{report['sweeps'][sweep]['band_alt_min_dex']:.4f} / "
            f"median {report['sweeps'][sweep]['band_alt_median_dex']:.4f} dex"
            f"  below limit {n_below_alt} ({n_below_alt_nt} untruncated)")
        log(f"  [{sweep}] rho(B, measured |dV_pulse|) = {rho_meas:+.3f}   "
            f"screen overlap {len(overlap)}/{TOP_K}")
        log(f"  [{sweep}] median asymmetry {asym_med:+.4f}   "
            f"median resolution {res_med:.4f} dex")
        log(f"  [{sweep}] recommended subset: "
            + ", ".join(r["protocol_id"] for r in subset))
        log(f"  [{sweep}] runtime {report['sweeps'][sweep]['runtime_s']:.1f} s")

    # ---- pre-registered verdict ------------------------------------
    crit: Dict[str, Any] = {}
    neg_sims = 0
    for sweep, s in report["sweeps"].items():
        crit[f"M1_existence[{sweep}]"] = bool(s["n_below_limit_untruncated"] >= 1)
        crit[f"M1b_existence_at_minus_half[{sweep}]"] = bool(
            s["n_below_limit_alt_untruncated"] >= 1
        )
        crit[f"M2_screening[{sweep}]"] = bool(s["screen_overlap_n"] >= MIN_SCREEN_OVERLAP)
        crit[f"M3_one_sidedness[{sweep}]"] = bool(
            np.isfinite(s["median_asymmetry"]) and s["median_asymmetry"] < 0
        )
        crit[f"M4_resolution[{sweep}]"] = bool(
            np.isfinite(s["median_band_resolution_dex"])
            and s["median_band_resolution_dex"] <= 0.10
        )
        n = report["negative_control"][sweep]
        crit[f"N1_negative[{sweep}]"] = bool(
            n["all_flat"] and n["all_both_sides_truncated"]
        )
        neg_sims += int(n.get("n_simulations", 0))
    report["verdict"] = {
        "criteria": crit,
        "passed": bool(all(crit.values())),
        "n_simulations_total": int(
            sum(r.get("n_simulations", 0) for r in rows_all) + neg_sims
        ),
        "runtime_s": time.perf_counter() - tic,
        "interpretation_rule": (
            "M1 decides the next step: if some window reaches B <= 0.30 dex "
            "at the reference point the dataset contains an identifying "
            "excitation and G6.1b-2 has a home.  M1b asks the same question "
            "one probe away (a0 = -0.5), added AFTER the 3-window smoke test "
            "and reported as secondary: it bounds how much of the failure is "
            "the reference point rather than the excitation."
        ),
    }

    log("")
    log("=" * 92)
    for k, v in crit.items():
        log(f"  {'PASS' if v else 'FAIL'}  {k}")
    log(f"  GATE PASSED  : {report['verdict']['passed']}")
    log(f"  simulations  : {report['verdict']['n_simulations_total']}")
    log(f"  runtime      : {report['verdict']['runtime_s']:.1f} s")
    log("=" * 92)

    (out / "g6_1c_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log(f"\nwrote {out / 'g6_1c_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
