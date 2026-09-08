# ============================================================
# Scientific Analysis Phase A1 — Cross-dataset Residual Atlas
# Build step (Steps A2-A7): residual long table, run-level
# summary, residual decomposition, transient / current / state
# conditioned error tables.
#
# Platform v0.4 FROZEN: this module only READS platform outputs
# (outputs/platform/.../_time_aligned.csv) plus adapter canonical
# windows for the current trace.  It never imports or re-runs
# runner/evaluator logic and never modifies battery_sim/.
#
# Definitions (fixed here; repeated in
# docs/cross_dataset_residual_analysis_v01.md):
#   residual_mV      = 1000 * (V_sim - V_exp) at shared time grid
#   elapsed_fraction = time_s / max(time_s)            (NOT "SOC")
#   dI_dt_A_s        = (I_i - I_{i-1}) / (t_i - t_{i-1}): FORWARD
#                      finite difference on the strictly-monotone
#                      shared time grid (first value padded);
#                      |dI/dt| is the transient proxy.
#                      LOCKED anomaly rule (2026-09-08): any
#                      dt <= 1e-6 s or non-finite quotient is an
#                      AUDIT FAILURE (raise) -- never silently
#                      zeroed, clipped or dropped.
#   q_fraction       = cumulative capacity / total capacity
#                      (CC runs only; dynamic runs carry regen
#                      current so q_fraction is left NaN).
#   charge_fraction  = Q_charge / (Q_charge + Q_discharge),
#                      Q from trapezoid of I over the window.
#   dynamicity_index_1_per_s = mean(|dI/dt|)
#   dynamicity_index_norm    = mean(|dI/dt|) / current_rms
#   decomposition (EXACT identity, not an approximation):
#       sigma_e = sqrt(mean((e - mean(e))^2))  centered resid. RMS
#       RMSE^2  = Bias^2 + sigma_e^2
#       bias_fraction            = Bias^2 / RMSE^2
#       dynamic_residual_component = sigma_e^2 / RMSE^2
#       bias_fraction + dynamic_residual_component == 1  exactly
# ============================================================

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from battery_sim.paths import ROOT
from battery_sim.registry import get_dataset, list_dataset_configs

# ------------------------------------------------------------------
# Fixed scientific facts of the atlas (frozen platform manifest):
# parameter_match for datasets whose yaml carries no pm block, and
# the protocol label used for CC (no protocol_id metadata exists).
# ------------------------------------------------------------------
CC_PROTOCOL = "CC"

_PM_FALLBACK = {
    "chen2020": {"level": "exact", "grade": "A"},
}

_PROTOCOL_FROM_WINDOW = {
    "calce_20r": {
        "DST_50SOC": "DST", "DST_80SOC": "DST",
        "FUDS_50SOC": "FUDS", "FUDS_80SOC": "FUDS",
        "US06_50SOC": "US06", "US06_80SOC": "US06",
    },
}


def _pm(dataset_id: str) -> dict:
    cfg = next(c for c in list_dataset_configs()
               if c.dataset_id == dataset_id)
    pm = dict(cfg.extra.get("parameter_match") or {})
    if not pm:
        pm = dict(_PM_FALLBACK.get(dataset_id, {}))
    return {
        "level": pm.get("level", ""),
        "grade": pm.get("grade", ""),
        "parameter_set": cfg.parameter_set,
        "chemistry": cfg.chemistry,
    }


def protocol_of(dataset_id: str, rate_slug: str) -> str:
    # dynamic windows: the slug either IS the protocol (A123) or
    # embeds it as a prefix (20R: DST_50SOC, FUDS_80SOC, ...)
    up = rate_slug.upper()
    if up in ("DST", "FUDS", "US06"):
        return up
    if dataset_id in _PROTOCOL_FROM_WINDOW:
        return _PROTOCOL_FROM_WINDOW[dataset_id][rate_slug]
    for p in ("DST", "FUDS", "US06"):
        if up.startswith(p):
            return p
    return CC_PROTOCOL


# ------------------------------------------------------------------
# Registry: dataset -> (cells x windows) restricted to runs whose
# platform output actually exists (kept explicit, auditable).
# ------------------------------------------------------------------
def available_runs() -> list[dict]:
    runs = []
    for cfg in list_dataset_configs():
        if cfg.dataset_id == "chen2020":
            # atlas sample cell (platform golden cell 02)
            cells = ["02"]
        else:
            cells = list(cfg.cells)
        for cell in cells:
            ad = get_dataset(cfg.dataset_id)
            # per-cell bound rate (CS2: cell33->0p5C, cell35->1C) or
            # the full shared window set (20R / A123 / Chen2020)
            bound = getattr(ad, "rate_for_cell", lambda c: "")(cell)
            windows = [bound] if bound else list(ad.list_rates())
            for w in windows:
                info = ad.rate_info(w)
                slug = str(info["rate_slug"])
                protocol = protocol_of(cfg.dataset_id, slug)
                runs.append({
                    "dataset": cfg.dataset_id,
                    "cell": cell,
                    "window": w,
                    "rate_slug": slug,
                    "protocol": protocol,
                    "c_rate": info["c_rate"],
                    "time_aligned": (
                        ROOT / "outputs" / "platform" / cfg.dataset_id
                        / "baseline" / "SPME" / f"cell{cell}"
                        / f"{slug}_time_aligned.csv"
                    ),
                })
    return runs


def _read_run(run: dict) -> dict | None:
    ta = run["time_aligned"]
    if not ta.exists():
        return None
    df = pd.read_csv(ta)
    t = df["time_s"].to_numpy(dtype=float)
    V_exp = df["voltage_exp_V"].to_numpy(dtype=float)
    V_sim = df["voltage_sim_V"].to_numpy(dtype=float)
    res_mV = 1000.0 * (V_sim - V_exp)

    # canonical current on the shared time grid
    ad = get_dataset(run["dataset"])
    try:
        raw = ad.load_processed_discharge(run["cell"], run["window"])
    except Exception:
        raw = ad.load_processed_discharge(run["cell"], run["rate_slug"])
    t_raw = raw["time_s"].to_numpy(dtype=float)
    I_raw = raw["current_A"].to_numpy(dtype=float)
    I = np.interp(t, t_raw, I_raw)

    # transient proxy (LOCKED definition 2026-09-08):
    #   dI_dt_i = (I_i - I_{i-1}) / (t_i - t_{i-1}) forward
    #   difference on the strictly-monotone shared time grid,
    #   first value padded.  Degenerate steps (dt <= 1e-6 s) or
    #   non-finite quotients are AUDIT FAILURES (raise), never
    #   silently zeroed or dropped.
    dt = np.diff(t)
    dI = np.diff(I)
    if t.size > 1:
        if not np.all(dt > 0):
            raise ValueError(f"non-monotonic time grid in {ta}")
        if np.min(dt) <= 1e-6:
            raise ValueError(
                f"degenerate step dt={np.min(dt):.3e} s <= 1e-6 s "
                f"in {ta} (transient-indeterminate, locked rule)"
            )
    dI_dt = np.concatenate(
        ([dI[0] / dt[0]] if dI.size else [0.0], dI / dt)
    )
    if not np.all(np.isfinite(dI_dt)):
        raise ValueError(f"non-finite dI/dt in {ta} (audit failure)")

    elapsed_frac = t / t[-1] if t[-1] > 0 else np.zeros_like(t)

    # CC-only discharged-capacity fraction from the canonical
    # cumulative capacity (signed -> valid only if current >= 0)
    q_frac = None
    if "capacity_Ah" in raw.columns and np.all(I_raw >= -1e-9):
        cap = np.interp(t, t_raw, raw["capacity_Ah"].to_numpy(float))
        cap = cap - cap[0]
        if cap[-1] > 0:
            q_frac = np.clip(cap / cap[-1], 0.0, 1.0)

    # provenance facts
    prov = dict(raw.attrs.get("provenance", {}) or {})
    ist = dict(prov.get("initial_state", {}) or {})
    init_soc = ist.get("value")
    if init_soc is None:
        init_soc = raw.attrs.get("initial_soc")
    if init_soc is None:
        init_soc = prov.get("initial_soc", np.nan)

    return {
        "t": t, "V_exp": V_exp, "V_sim": V_sim, "res_mV": res_mV,
        "I": I, "dI_dt": dI_dt, "elapsed_frac": elapsed_frac,
        "q_frac": q_frac, "initial_state_value": init_soc,
    }


# ------------------------------------------------------------------
# Builders
# ------------------------------------------------------------------
def build_long(runs) -> pd.DataFrame:
    rows = []
    for run in runs:
        r = _read_run(run)
        if r is None:
            continue
        pm = _pm(run["dataset"])
        n = r["t"].size
        q = r["q_frac"]
        rows.append(pd.DataFrame({
            "dataset": run["dataset"],
            "cell": run["cell"],
            "window": f"{run['dataset']}/{run['cell']}/{run['rate_slug']}",
            "chemistry": pm["chemistry"],
            "model": "SPMe",
            "parameter_set": pm["parameter_set"],
            "parameter_match_grade": pm["grade"],
            "parameter_match_level": pm["level"],
            "protocol": run["protocol"],
            "c_rate": float(run["c_rate"]) if np.isfinite(run["c_rate"]) else np.nan,
            "initial_state_value": float(r["initial_state_value"]),
            "time_s": r["t"],
            "elapsed_fraction": r["elapsed_frac"],
            "q_fraction": q if q is not None else np.full(n, np.nan),
            "current_A": r["I"],
            "abs_current_A": np.abs(r["I"]),
            "dI_dt_A_s": r["dI_dt"],
            "abs_dI_dt_A_s": np.abs(r["dI_dt"]),
            "voltage_exp_V": r["V_exp"],
            "voltage_sim_V": r["V_sim"],
            "residual_mV": r["res_mV"],
            "abs_residual_mV": np.abs(r["res_mV"]),
        }))
    return pd.concat(rows, ignore_index=True) if rows else \
        pd.DataFrame()


def _charge_fraction(I: np.ndarray, t: np.ndarray) -> float:
    Q_pos = np.trapezoid(np.clip(I, 0, None), t)
    Q_neg = np.trapezoid(np.clip(-I, 0, None), t)
    denom = Q_pos + Q_neg
    return float(Q_neg / denom) if denom > 0 else np.nan


def build_summary(long: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (win,), g in long.groupby(["window"]):
        e = g["residual_mV"].to_numpy()
        I = g["current_A"].to_numpy()
        dI = g["dI_dt_A_s"].to_numpy()
        t = g["time_s"].to_numpy()
        rmse = float(np.sqrt(np.mean(e ** 2)))
        bias = float(np.mean(e))
        sigma = float(np.std(e))
        rec = {
            "dataset": g["dataset"].iloc[0],
            "cell": g["cell"].iloc[0],
            "window": win,
            "chemistry": g["chemistry"].iloc[0],
            "model": "SPMe",
            "parameter_set": g["parameter_set"].iloc[0],
            "parameter_match_grade": g["parameter_match_grade"].iloc[0],
            "parameter_match_level": g["parameter_match_level"].iloc[0],
            "protocol": g["protocol"].iloc[0],
            "c_rate": float(g["c_rate"].iloc[0]),
            "initial_state_value": float(g["initial_state_value"].iloc[0]),
            "n_points": int(len(g)),
            "duration_s": float(t[-1]),
            "RMSE_mV": rmse,
            "MAE_mV": float(np.mean(np.abs(e))),
            "Bias_mV": bias,
            "residual_std_mV": sigma,
            "max_abs_error_mV": float(np.max(np.abs(e))),
            "current_rms_A": float(np.sqrt(np.mean(I ** 2))),
            "peak_discharge_current_A": float(np.max(I)),
            "peak_charge_current_A": float(np.max(-I)),
            "charge_fraction": _charge_fraction(I, t),
            "current_std_A": float(np.std(I)),
            "dynamicity_index_1_per_s": float(np.mean(np.abs(dI))),
            "dynamicity_index_norm": (
                float(np.mean(np.abs(dI)) / np.sqrt(np.mean(I ** 2)))
                if np.sqrt(np.mean(I ** 2)) > 0 else np.nan
            ),
            # RMSE^2 = Bias^2 + sigma_e^2 (EXACT; sigma_e = std(e),
            # population std, so bias_fraction + sigma-term == 1)
            "bias_fraction": float(bias ** 2 / rmse ** 2) if rmse > 0 else np.nan,
            "dynamic_residual_component": (
                float(sigma ** 2 / rmse ** 2) if rmse > 0 else np.nan
            ),
        }
        out.append(rec)
    return pd.DataFrame(out)


def bin_table(long: pd.DataFrame, by: str, qs=(0.5, 0.9)) -> pd.DataFrame:
    """Condition residuals on quantile bins of `by` per window."""
    rows = []
    for win, g in long.groupby("window"):
        x = g[by].to_numpy(dtype=float)
        e = g["residual_mV"].to_numpy(dtype=float)
        ae = np.abs(e)
        q_lo, q_hi = np.quantile(x, qs[0]), np.quantile(x, qs[1])
        # half-open bins [lo, qlo) / [qlo, qhi) / [qhi, max+eps)
        eps = max(float(np.ptp(x)) * 1e-6, 1e-12)
        edges = [
            ("low", float(np.min(x)), float(q_lo)),
            ("medium", float(q_lo), float(q_hi)),
            ("high", float(q_hi), float(np.max(x)) + eps),
        ]
        for name, a, b in edges:
            m = (x >= a) & (x < b)
            if m.sum() < 5:
                continue
            rows.append({
                "window": win,
                "dataset": g["dataset"].iloc[0],
                "protocol": g["protocol"].iloc[0],
                "parameter_match_grade": g["parameter_match_grade"].iloc[0],
                "bin_by": by,
                "bin": name,
                "bin_edge_low": float(a),
                "bin_edge_high": float(b),
                "n_points": int(m.sum()),
                "RMSE_mV": float(np.sqrt(np.mean(e[m] ** 2))),
                "MAE_mV": float(np.mean(ae[m])),
                "Bias_mV": float(np.mean(e[m])),
            })
    return pd.DataFrame(rows)


def progress_table(long: pd.DataFrame) -> pd.DataFrame:
    """elapsed/protocol-progress bins (0-20..80-100 %), NOT called SOC."""
    rows = []
    edges = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    for win, g in long.groupby("window"):
        p = g["elapsed_fraction"].to_numpy()
        e = g["residual_mV"].to_numpy()
        ae = np.abs(e)
        for a, b in edges:
            m = (p >= a) & (p <= b)
            if m.sum() < 5:
                continue
            rows.append({
                "window": win,
                "dataset": g["dataset"].iloc[0],
                "protocol": g["protocol"].iloc[0],
                "parameter_match_grade": g["parameter_match_grade"].iloc[0],
                "progress_bin": f"{int(a*100)}-{int(b*100)}%",
                "n_points": int(m.sum()),
                "mean_residual_mV": float(np.mean(e[m])),
                "rmse_mV": float(np.sqrt(np.mean(e[m] ** 2))),
                "mean_abs_residual_mV": float(np.mean(ae[m])),
            })
    return pd.DataFrame(rows)


def main():
    out_dir = ROOT / "outputs" / "analysis" / "residual_atlas"
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = available_runs()
    missing = [r["time_aligned"] for r in runs if not r["time_aligned"].exists()]
    print(f"registered runs: {len(runs)} | missing outputs: {len(missing)}")
    for m in missing:
        print("  MISSING:", m)

    long = build_long(runs)
    long.to_csv(out_dir / "residual_long.csv", index=False)
    print("long rows:", len(long))

    summary = build_summary(long)
    summary.to_csv(out_dir / "run_summary.csv", index=False)
    print("summary runs:", len(summary))

    dec = pd.DataFrame(
        summary[["window", "dataset", "protocol", "RMSE_mV", "Bias_mV",
                 "residual_std_mV", "bias_fraction",
                 "dynamic_residual_component"]]
    )
    dec.to_csv(out_dir / "decomposition.csv", index=False)

    # Step A5: transient-conditioned bins on |dI/dt| (quantile
    # edges <50 / 50-90 / >90 within each run)
    tr = bin_table(long, "abs_dI_dt_A_s")
    tr.to_csv(out_dir / "transient_conditioned.csv", index=False)
    # Step A6: current-load-conditioned bins on |I| (terciles)
    cl = bin_table(long, "abs_current_A", qs=(1.0 / 3, 2.0 / 3))
    cl.to_csv(out_dir / "current_load_conditioned.csv", index=False)
    pr = progress_table(long)
    pr.to_csv(out_dir / "progress_error.csv", index=False)

    print("wrote:", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
