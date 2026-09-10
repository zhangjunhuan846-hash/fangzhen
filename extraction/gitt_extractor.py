# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B1.0: SINTEF GITT segmentation (full resolution)
#
# THE FILE IS A MULTI-RATE LOG, NOT A FLAT TABLE
#   The SINTEF "intelligent cell" writes several channels with
#   DIFFERENT logging rates, interleaved in time and distinguished
#   only by (Cycle Count, Step Index).  For programme "gitt"
#   (cell 063b77), measured:
#
#     step 4   lithiation PULSE train    I = -44.1545 uA, 1 s logging
#     step 10  delithiation PULSE train  I = +44.155  uA, 1 s logging
#     step 2   rest  100 Hz burst        I = 0,  dt = 0.01 s
#     step 3   rest  10 s logging        I = 0,  dt = 10 s
#     steps 8/9  the same for the delithiation half
#     103 lithiation pulses and 95-96 delithiation pulses per cycle
#
#   Two consequences that MUST be handled or the charge is wrong:
#
#   1. a step's rows do NOT cover the whole interval [t_min, t_max].
#      Step 4 spans 309 h but only ~52 h of it carries current; the
#      9000 s rests between pulses are logged by OTHER channels.  A
#      trapezoid over step 4 alone therefore charges the rests as if a
#      current were flowing: measured 9.8 mAh, 4.5x the cell capacity.
#      The pulse/rest split must come from the LOGGING GAPS.
#   2. the relaxation is only on the rest channels, so each pulse has
#      to be PAIRED with the rest burst that follows it.
#
# WHAT THIS MODULE DOES
#   Pass 1: per (cycle, step) census -> pulse vs rest channels, each
#           channel's own sampling interval and gap threshold.
#   Pass 2: vectorised run-length encoding of every channel into
#           bursts on dt > max(5 x channel dt, 1.5 s):
#             * pulse bursts -> one GITT pulse each, keeping the
#               sufficient statistics of TWO regressions of the pulse:
#               the Weppner-Huggins V = a + m*sqrt(t) (Phase B1) and the
#               drift-corrected V = a + b*t + m*sqrt(t) (Phase B1.6);
#             * rest bursts  -> start/end voltage of one relaxation.
#           Each pulse is paired with the longest rest burst that
#           starts at its end.
#
#   Full resolution throughout: no decimation of pulses or of the rest
#   endpoints.  No pybamm import.
# ============================================================

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]

COL_TIME = "Test Time / s"
COL_CURRENT = "Current / A"
COL_VOLTAGE = "Voltage / V"
COL_CYCLE = "Cycle Count / 1"
COL_STEP = "Step Index / 1"

BATCH_SIZE = 1 << 18

ACTIVE_CURRENT_FRACTION = 0.5   # channel is a pulse channel above this
MIN_BURST_S = 600.0             # drop logging artefacts shorter than this
DEFAULT_IR_SKIP_S = 60.0        # skip the IR/initial transient in the fit
REST_MATCH_WINDOW_S = 600.0     # a rest must start within this of the pulse

BASE_FIELDS = [
    "cycle", "pulse_id", "branch", "step",
    "SOC_start", "SOC_end",
    "I_A", "pulse_time_s", "relax_time_s",
    "delta_V_pulse_V", "delta_V_relax_V",
    "capacity_increment_mAh",
]


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def resolve_gitt_file(adapter, cell: str,
                      programme: str = "gitt") -> Tuple[Path, str]:
    """
    Raw GITT file from the dataset config (never adapter internals).

    The programme is taken as an explicit argument rather than from the
    adapter's ``rates_meta``: GITT is a PARAMETER-EXTRACTION source, not
    a replay rate, so it is deliberately not added to the dataset's
    rate table (which the baseline runner would then try to replay).
    """
    cfg = adapter.config
    raw_dir = Path(cfg.raw_dir)
    if not raw_dir.is_absolute():
        raw_dir = ROOT / raw_dir
    pattern = str(cfg.raw_file_template).format(cell=str(cell),
                                                programme=programme)
    matches = sorted(raw_dir.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one GITT file for cell '{cell}' in {raw_dir} "
            f"(pattern '{pattern}'), found {[m.name for m in matches]}"
        )
    return matches[0], programme


# ------------------------------------------------------------------
# pass 1: channel census
# ------------------------------------------------------------------
def _census(path: Path) -> Tuple[pd.DataFrame, Dict[int, float], float]:
    acc: Dict[int, dict] = {}
    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=BATCH_SIZE,
        columns=[COL_TIME, COL_CURRENT, COL_STEP],
    ):
        d = batch.to_pandas()
        d = d.assign(_a=d[COL_CURRENT].abs())
        gb = d.groupby(COL_STEP, sort=False)
        cnt = gb[COL_CURRENT].count()
        ssum = gb[COL_CURRENT].sum()
        amax = gb["_a"].max()
        t0 = gb[COL_TIME].min()
        t1 = gb[COL_TIME].max()
        for step in cnt.index:
            s = int(step)
            a = acc.get(s)
            if a is None:
                acc[s] = a = {"n": 0, "sum": 0.0, "amax": 0.0,
                              "t0": np.inf, "t1": -np.inf}
            a["n"] += int(cnt.loc[step])
            a["sum"] += float(ssum.loc[step])
            a["amax"] = max(a["amax"], float(amax.loc[step]))
            a["t0"] = min(a["t0"], float(t0.loc[step]))
            a["t1"] = max(a["t1"], float(t1.loc[step]))

    peak = max((a["amax"] for a in acc.values()), default=0.0)
    if peak <= 0:
        raise ValueError(f"{path.name}: no non-zero current found")
    thr = ACTIVE_CURRENT_FRACTION * peak

    rows, gap_thr = [], {}
    for s, a in sorted(acc.items()):
        med = a["sum"] / a["n"] if a["n"] else float("nan")
        mean_dt = (a["t1"] - a["t0"]) / max(a["n"] - 1, 1)
        gt = max(5.0 * mean_dt, 1.5)
        gap_thr[s] = gt
        rows.append({
            "step": s, "n_rows": int(a["n"]),
            "median_current_A": med,
            "kind": "pulse" if abs(med) >= thr else "rest",
            "t_min_s": float(a["t0"]), "t_max_s": float(a["t1"]),
            "span_h": float((a["t1"] - a["t0"]) / 3600.0),
            "mean_dt_s": float(mean_dt), "gap_threshold_s": float(gt),
        })
    return pd.DataFrame(rows), gap_thr, peak


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _fit_sqrt_t(t_rel: np.ndarray, v: np.ndarray, ir_skip: float) -> dict:
    """
    Least squares fit of V = a + m*sqrt(t) over t >= ir_skip.

    Exactly the PyBOP Weppner-Huggins form
    V = U + U' (2I/(3 Q_th)) sqrt(t tau_d/pi), so `slope` carries
    U' * (2I/(3Q_th)) * sqrt(tau_d/pi).
    """
    sel = t_rel >= ir_skip
    if sel.sum() < 10:
        sel = np.ones(len(t_rel), dtype=bool)
    x = np.sqrt(t_rel[sel])
    y = v[sel]
    n = int(len(x))
    nan = float("nan")
    if n < 3:
        return {"slope": nan, "stderr": nan, "intercept": nan,
                "r2": nan, "n_fit": n}
    xm, ym = float(x.mean()), float(y.mean())
    sxx = float(np.sum((x - xm) ** 2))
    if sxx <= 0:
        return {"slope": nan, "stderr": nan, "intercept": nan,
                "r2": nan, "n_fit": n}
    sxy = float(np.sum((x - xm) * (y - ym)))
    m = sxy / sxx
    a = ym - m * xm
    resid = y - (a + m * x)
    sse = float(np.sum(resid ** 2))
    stderr = float(np.sqrt(sse / max(n - 2, 1) / sxx))
    sst = float(np.sum((y - ym) ** 2))
    return {"slope": m, "stderr": stderr, "intercept": a,
            "r2": (1.0 - sse / sst) if sst > 0 else nan, "n_fit": n}


def _fit_quadratic_sqrt_t(t_rel: np.ndarray, v: np.ndarray,
                          ir_skip: float) -> dict:
    """
    Least squares fit of V = a + b*t + m*sqrt(t) over t >= ir_skip.

    WHY THIS EXISTS (Phase B1.5)
      The Weppner-Huggins pulse law assumes the EQUILIBRIUM voltage is
      constant across the pulse, so the whole measured rise is
      diffusional.  It is not constant: the bulk-average lithium content
      advances roughly linearly with time, so the equilibrium voltage
      drifts linearly and the fitted sqrt(t) slope absorbs part of that
      drift.  On model-generated pulses of this very protocol the
      first-order fit inflated the diffusion slope by a median 2.9x
      (Phase B1.5, `extraction/gitt_pulse_budget.py`).  Adding the
      linear term lets the drift be carried by `b` and the diffusion
      signal by `m`.

      Numerically the fit is done with t centred and divided by the
      pulse duration: the column space of {1, t, sqrt(t)} is unchanged
      by shifting t, so the returned sqrt(t) coefficient `m` is exactly
      the coefficient of the raw sqrt(t) column, while the conditioning
      improves by orders of magnitude (t ~ 1.8e3 against t ~ 9e2 offsets).

    Returns the sqrt(t) coefficient and its standard error, the linear
    drift coefficient in V/s, the intercept, R^2 and the sample count --
    the same shape as :func:`_fit_sqrt_t`.
    """
    sel = t_rel >= ir_skip
    if sel.sum() < 10:
        sel = np.ones(len(t_rel), dtype=bool)
    t = np.asarray(t_rel[sel], dtype=float)
    y = np.asarray(v[sel], dtype=float)
    n = int(len(t))
    nan = float("nan")
    empty = {"sqrt_slope": nan, "sqrt_stderr": nan, "t_slope": nan,
             "intercept": nan, "r2": nan, "n_fit": n}
    # 3 coefficients + at least 2 residual degrees of freedom
    if n < 5:
        return empty
    tau = float(np.ptp(t))
    if tau <= 0:
        return empty
    x_t = (t - float(np.mean(t))) / tau
    x_s = np.sqrt(t)
    X = np.column_stack((np.ones(n), x_t, x_s))
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return empty
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    sse = float(resid @ resid)
    dof = n - 3
    s2 = sse / dof if dof > 0 else nan
    diag = np.diag(XtX_inv)
    se_sqrt = float(np.sqrt(s2 * diag[2])) if np.isfinite(s2) \
        and diag[2] > 0 else nan
    sst = float(np.sum((y - np.mean(y)) ** 2))
    # the intercept is reported as V at t = 0 (i.e. a, the value the
    # first-order fit also reports) rather than as the coefficient of
    # the centred regressor, so the two fits stay comparable
    t_mean = float(np.mean(t))
    return {
        "sqrt_slope": float(beta[2]),
        "sqrt_stderr": se_sqrt,
        "t_slope": float(beta[1]) / tau,      # back to V/s
        "intercept": float(beta[0] - beta[1] * t_mean / tau),
        "r2": (1.0 - sse / sst) if sst > 0 else nan,
        "n_fit": n,
    }


def _runs_with_gaps(t: np.ndarray, gt: float) -> List[Tuple[int, int]]:
    """Index ranges of contiguous logging runs (gaps larger than gt split)."""
    if len(t) == 0:
        return []
    brk = np.flatnonzero(np.diff(t) > gt) + 1
    bounds = np.concatenate(([0], brk, [len(t)]))
    return [(int(bounds[k]), int(bounds[k + 1]))
            for k in range(len(bounds) - 1)]


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------
def extract_gitt_segments(
    adapter,
    cell: str,
    programme: str = "gitt",
    *,
    ir_skip_s: float = DEFAULT_IR_SKIP_S,
    min_burst_s: float = MIN_BURST_S,
    rest_match_window_s: float = REST_MATCH_WINDOW_S,
    verbose: bool = True,
) -> Dict[str, object]:
    """Full-resolution GITT segmentation -> one row per pulse."""
    path, programme = resolve_gitt_file(adapter, cell, programme)
    pf = pq.ParquetFile(path)
    channels, gap_thr, peak = _census(path)
    if verbose:
        print(f"  channel census ({path.name}, "
              f"{pf.metadata.num_rows:,} rows):")
        print(channels.to_string(index=False))

    pulse_steps = set(channels.loc[channels["kind"] == "pulse", "step"].astype(int))
    rest_steps = set(channels.loc[channels["kind"] == "rest", "step"].astype(int))
    thr_abs = ACTIVE_CURRENT_FRACTION * peak

    pulse_chunks: Dict[Tuple[int, int], List[np.ndarray]] = {}
    rest_bursts: List[dict] = []
    open_bursts: Dict[int, dict] = {}

    for batch in pf.iter_batches(
        batch_size=BATCH_SIZE,
        columns=[COL_TIME, COL_CURRENT, COL_VOLTAGE, COL_CYCLE, COL_STEP],
    ):
        d = batch.to_pandas()
        for (cyc, step), g in d.groupby([COL_CYCLE, COL_STEP], sort=False):
            cyc, step = int(cyc), int(step)
            if step in pulse_steps:
                pulse_chunks.setdefault((cyc, step), []).append(
                    np.column_stack((g[COL_TIME].to_numpy(float),
                                     g[COL_CURRENT].to_numpy(float),
                                     g[COL_VOLTAGE].to_numpy(float)))
                )
                continue
            if step not in rest_steps:
                continue
            t = g[COL_TIME].to_numpy(float)
            v = g[COL_VOLTAGE].to_numpy(float)
            gt = gap_thr[step]
            for a, b in _runs_with_gaps(t, gt):
                st = open_bursts.get(step)
                if st is not None and (t[a] - st["t1"]) <= gt:
                    st["t1"] = float(t[b - 1])
                    st["v1"] = float(v[b - 1])
                    st["n"] += b - a
                else:
                    if st is not None and st["t1"] - st["t0"] >= min_burst_s:
                        rest_bursts.append(st)
                    open_bursts[step] = {
                        "step": step, "t0": float(t[a]), "t1": float(t[b - 1]),
                        "v0": float(v[a]), "v1": float(v[b - 1]),
                        "n": int(b - a), "cycle": cyc,
                    }
    for st in open_bursts.values():
        if st["t1"] - st["t0"] >= min_burst_s:
            rest_bursts.append(st)
    if verbose:
        print(f"  pulse channels {sorted(pulse_steps)} | "
              f"rest channels {sorted(rest_steps)} | "
              f"rest bursts kept {len(rest_bursts)}")

    # ---- pulse trains -> segments --------------------------------
    seg_rows: List[dict] = []
    for (cyc, step), chunks in sorted(pulse_chunks.items()):
        arr = np.concatenate(chunks, axis=0)
        arr = arr[np.argsort(arr[:, 0], kind="stable")]
        t, i, v = arr[:, 0], arr[:, 1], arr[:, 2]
        for a, b in _runs_with_gaps(t, gap_thr[step]):
            if b - a < 10 or (t[b - 1] - t[a]) < min_burst_s:
                continue
            # RAW sign is the cycler convention (negative = discharge);
            # for a graphite||Li cell the discharge LITHIATES the
            # graphite, so the canonical platform sign (+ = discharge)
            # requires a flip, exactly as in the p-OCV adapter.
            i_med = -float(np.median(i[a:b]))
            if abs(i_med) < thr_abs:
                continue
            fit = _fit_sqrt_t(t[a:b] - t[a], v[a:b], ir_skip_s)
            # the same pulse is ALSO fitted with the equilibrium-drift
            # term, V = a + b*t + m*sqrt(t); both live side by side so
            # the two diffusivity routes can be compared pulse by pulse
            fit2 = _fit_quadratic_sqrt_t(t[a:b] - t[a], v[a:b], ir_skip_s)
            seg_rows.append({
                "cycle": cyc, "step": step,
                "branch": "lithiation" if i_med > 0 else "delithiation",
                "t_pulse_start_s": float(t[a]),
                "t_pulse_end_s": float(t[b - 1]),
                "pulse_time_s": float(t[b - 1] - t[a]),
                "I_A": i_med,
                "V_pulse_start_V": float(v[a]),
                "V_pulse_end_V": float(v[b - 1]),
                "delta_V_pulse_V": float(v[b - 1] - v[a]),
                "n_pulse_samples": int(b - a),
                "n_relax_samples": 0,
                "relax_step": -1,
                "relax_time_s": float("nan"),
                "relax_coverage_s": float("nan"),
                "V_relax_end_V": float("nan"),
                "delta_V_relax_V": float("nan"),
                # ---- first order: V = a + m*sqrt(t) ------------------
                "sqrt_t_slope_V_per_sqrt_s": fit["slope"],
                "sqrt_t_slope_stderr": fit["stderr"],
                "sqrt_t_intercept_V": fit["intercept"],
                "sqrt_t_r2": fit["r2"],
                "n_fit_samples": fit["n_fit"],
                # ---- second order: V = a + b*t + m*sqrt(t) -----------
                "quad_sqrt_t_slope_V_per_sqrt_s": fit2["sqrt_slope"],
                "quad_sqrt_t_slope_stderr": fit2["sqrt_stderr"],
                "quad_t_slope_V_per_s": fit2["t_slope"],
                "quad_intercept_V": fit2["intercept"],
                "quad_r2": fit2["r2"],
                "quad_n_fit_samples": fit2["n_fit"],
                # how much of the first-order slope was really drift
                "sqrt_t_slope_excess_over_quad": fit["slope"] - fit2["sqrt_slope"],
                "ir_skip_s": float(ir_skip_s),
            })
        if verbose:
            n = sum(1 for r in seg_rows
                    if r["cycle"] == cyc and r["step"] == step)
            print(f"  cycle {cyc} step {step}: {n} pulses")

    if not seg_rows:
        raise ValueError(f"{path.name}: no GITT pulses found")
    seg = pd.DataFrame(seg_rows)

    # ---- relaxation: the repose window between consecutive pulses --
    # The rest is logged by OTHER channels, so it is assembled from the
    # rest bursts that fall inside the repose window that follows each
    # pulse (start of the next pulse of the same train, else the match
    # window).  The reported V_end is the LATEST rest sample, and the
    # coverage records how much of the window the rest channels cover.
    by_cycle: Dict[int, List[dict]] = {}
    for r in rest_bursts:
        by_cycle.setdefault(r["cycle"], []).append(r)
    for cyc, lst in by_cycle.items():
        lst.sort(key=lambda r: r["t0"])

    # the repose window ends when the NEXT current pulse starts, on ANY
    # channel: a rest is a physical interval between pulses, not a
    # property of one logging step.  (Bounding it by the same train only
    # would let the last pulse of a train swallow the next train's
    # rests, which is how a "negative relaxation" appears.)
    next_pulse_after: Dict[int, List[float]] = {}
    for cyc in {r["cycle"] for r in seg_rows}:
        starts = sorted(r["t_pulse_start_s"] for r in seg_rows
                        if r["cycle"] == cyc)
        next_pulse_after[cyc] = starts

    def _window_end(cyc: int, end: float) -> float:
        for t0 in next_pulse_after.get(cyc, []):
            if t0 > end + 1.0:
                return float(t0)
        return float(end + rest_match_window_s * 10.0)

    trains: Dict[Tuple[int, int], List[int]] = {}
    for idx, row in enumerate(seg_rows):
        trains.setdefault((row["cycle"], row["step"]), []).append(idx)
    for key, idxs in trains.items():
        idxs.sort(key=lambda k: seg_rows[k]["t_pulse_start_s"])
        for j, k in enumerate(idxs):
            row = seg_rows[k]
            end = row["t_pulse_end_s"]
            window_end = _window_end(key[0], end)
            cands = [r for r in by_cycle.get(key[0], [])
                     if r["t0"] >= end - 1.0 and r["t0"] <= window_end + 1.0]
            if not cands:
                continue
            coverage = float(sum(min(r["t1"], window_end) - max(r["t0"], end)
                                 for r in cands))
            latest = max(cands, key=lambda r: r["t1"])
            row["relax_step"] = int(latest["step"])
            row["relax_coverage_s"] = coverage
            row["relax_time_s"] = float(latest["t1"] - end)
            row["V_relax_end_V"] = float(latest["v1"])
            row["delta_V_relax_V"] = float(latest["v1"] - row["V_pulse_end_V"])
            row["n_relax_samples"] = int(sum(r["n"] for r in cands))

    seg = pd.DataFrame(seg_rows)

    # ---- SOC axis (same DEFINITION as the p-OCV OCP extraction) ---
    q_ref_by_cycle: Dict[int, float] = {}
    for cyc, g in seg.groupby("cycle", sort=True):
        lith = g[g["branch"] == "lithiation"]
        q_ref_by_cycle[int(cyc)] = float(
            (lith["I_A"].abs() * lith["pulse_time_s"]).sum() / 3.6
        )   # mAh
    soc0 = pd.Series(np.nan, index=seg.index, dtype=float)
    soc1 = pd.Series(np.nan, index=seg.index, dtype=float)
    for _, g in seg.groupby("cycle", sort=True):
        q_ref = q_ref_by_cycle[int(g["cycle"].iloc[0])] / 1e3      # Ah
        for branch, sub in g.groupby("branch", sort=False):
            sub = sub.sort_values("t_pulse_start_s")
            inc = (sub["I_A"].abs() * sub["pulse_time_s"] / 3600.0).to_numpy()
            cum = np.cumsum(inc)
            prev = cum - inc
            if branch == "lithiation":
                a, b = prev / q_ref, cum / q_ref
            else:
                a, b = 1.0 - prev / q_ref, 1.0 - cum / q_ref
            soc0.loc[sub.index] = a
            soc1.loc[sub.index] = b
    seg["SOC_start"] = soc0
    seg["SOC_end"] = soc1

    seg["capacity_increment_mAh"] = (
        seg["I_A"].abs() * seg["pulse_time_s"] / 3.6
    )
    seg = seg.sort_values(["cycle", "t_pulse_start_s"]).reset_index(drop=True)
    seg["pulse_id"] = seg.groupby("cycle").cumcount() + 1
    seg = seg.drop(columns=["t_pulse_end_s"], errors="ignore")

    provenance = {
        "segmentation": "extraction/gitt_extractor.py::extract_gitt_segments",
        "source_file": path.name,
        "source_sha256": _sha256(path),
        "row_groups": int(pf.metadata.num_row_groups),
        "total_rows": int(pf.metadata.num_rows),
        "programme": programme,
        "decimation": "NONE - full resolution on pulses and rest endpoints",
        "file_structure": (
            "multi-rate log: several (cycle, step) channels are "
            "interleaved in time and a step's rows do NOT cover "
            "[t_min, t_max]"
        ),
        "channels": channels.to_dict(orient="records"),
        "pulse_protocol": {
            "pulse_time_s_median": float(seg["pulse_time_s"].median()),
            "relax_time_s_median": float(seg["relax_time_s"].median()),
            "pulses_per_cycle": {
                str(int(k)): int(v)
                for k, v in seg.groupby("cycle").size().items()
            },
            "pulses_per_branch": {
                str(k): int(v) for k, v in seg.groupby("branch").size().items()
            },
            "n_pulses_total": int(len(seg)),
            "current_levels_A": sorted(
                {float(np.round(x, 9)) for x in seg["I_A"].unique()}
            ),
            "pulse_steps": sorted(int(s) for s in pulse_steps),
            "rest_steps": sorted(int(s) for s in rest_steps),
        },
        "soc_definition": (
            "Q_ref = total charge of the cycle's LITHIATION pulse train "
            "(canonical current > 0) from the fresh state to the fully "
            "lithiated state; lithiation SOC = Q/Q_ref, delithiation "
            "SOC = 1 - Q/Q_ref.  Deliberately the SAME definition as the "
            "p-OCV OCP extraction so that D_s(SOC) and the frozen OCP "
            "share one axis."
        ),
        "soc_reference_charge_mAh": {
            str(k): float(v) for k, v in q_ref_by_cycle.items()
        },
        "segmentation_rules": {
            "gap_rule": "burst break where dt > max(5 x channel mean dt, 1.5 s)",
            "gap_threshold_s": {str(k): float(v) for k, v in gap_thr.items()},
            "min_burst_s": float(min_burst_s),
            "ir_skip_s": float(ir_skip_s),
            "rest_pairing": (
                "rest bursts inside the repose window [pulse end, next "
                "pulse start on ANY channel]; V_end is the latest rest "
                "sample, coverage records the channels' span"
            ),
            "why_the_gaps_matter": (
                "the 9000 s rests between pulses are logged by other "
                "channels, so integrating the pulse channel alone would "
                "charge them as well: that mis-integration gives 9.8 mAh, "
                "4.5x the cell capacity, instead of the correct 2.29 mAh"
            ),
        },
        "fits": {
            "first_order": (
                "V = a + m*sqrt(t) -- the PyBOP Weppner-Huggins form; "
                "the Phase B1 apparent D_s is built from this slope"
            ),
            "second_order": (
                "V = a + b*t + m*sqrt(t) -- the same pulse law PLUS the "
                "linear equilibrium drift caused by the bulk composition "
                "advancing during the pulse.  Phase B1.5 measured that "
                "the first-order slope inflates the diffusion term by a "
                "median 2.9x on model-generated pulses of this protocol, "
                "which biases the first-order D_s low by about 9x"
            ),
            "columns": (
                "both fits are stored per pulse: sqrt_t_* (first order, "
                "unchanged from Phase B1) and quad_* (second order); "
                "sqrt_t_slope_excess_over_quad is their difference"
            ),
            "why_one_pass": (
                "the two regressions are computed from the SAME pulse "
                "samples in the same pass, so the comparison cannot be "
                "affected by decimation or by a differing segmentation"
            ),
        },
        "sign_convention": {
            "raw": "negative current = discharge (cycler convention)",
            "platform_canonical": "discharge = +, charge = -",
            "action": "raw sign FLIPPED (same as the p-OCV adapter)",
            "physics": (
                "for a graphite||Li half cell the spontaneous discharge "
                "LITHIATES the graphite, so canonical + = lithiation and "
                "the sign of I_A is directly usable in the PyBOP "
                "Weppner-Huggins form where current is positive on "
                "discharge"
            ),
        },
        "temperature_source": "declared_room_temperature_not_measured",
        "wording": (
            "GITT segmentation only: pulse/rest identification and charge "
            "accounting.  No diffusivity is computed in this step."
        ),
    }
    return {"segments": seg, "channels": channels, "provenance": provenance}


def write_gitt_segments(
    result: Dict[str, object],
    out_dir: Path | str,
    *,
    extra_provenance: Optional[dict] = None,
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seg: pd.DataFrame = result["segments"]  # type: ignore[assignment]
    fields = BASE_FIELDS + [c for c in seg.columns if c not in BASE_FIELDS]
    csv = out / "gitt_segments.csv"
    seg[fields].to_csv(csv, index=False)
    prov = dict(result["provenance"])  # type: ignore[arg-type]
    if extra_provenance:
        prov.update(extra_provenance)
    ppath = out / "gitt_segmentation_provenance.json"
    with ppath.open("w", encoding="utf-8") as fh:
        json.dump(prov, fh, indent=2, ensure_ascii=False)
    return {"segments": csv, "provenance": ppath}
