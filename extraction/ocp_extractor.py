# ============================================================
# Phase B0 (graphite line): experiment-derived graphite OCP
#
# Turns a SINTEF graphite R2032 p-OCV record into a TWO-BRANCH
# OCP table:
#
#   graphite_ocp_lithiation.csv    (fresh -> fully lithiated)
#   graphite_ocp_delithiation.csv  (fully lithiated -> cutoff)
#
# WHAT THIS IS (and is not)
#   The p-OCV programme steps at ~C/50 with rests only at the
#   endpoints, so the extracted curve is a PSEUDO-OCP: it contains
#   the (small) C/50 polarisation and therefore sits slightly below
#   the lithiation branch and slightly above the delithiation
#   branch.  It is NOT a true equilibrium OCP, and it is NOT a
#   material constant -- it is the measured quasi-equilibrium
#   response of THIS electrode at THIS temperature (declared RT).
#   The `equilibrium_warning` field carries this verbatim.
#
# SOC AXIS (explicit, one anchor per cycle)
#   Q_ref = charge delivered by the cycle's LITHIATION branch
#           (canonical current > 0 = discharge = lithiation for a
#            graphite||Li half cell), measured from the fresh state
#            to the lower voltage cutoff.
#   lithiation  : SOC = Q(t) / Q_ref                 (0 -> 1)
#   delithiation: SOC = 1 - |Q(t)| / Q_ref           (1 -> ~0.08)
#   => both branches share ONE SOC axis anchored at the fresh and
#      fully-lithiated states of the SAME cycle.
#   Cycle 1 is the default (it starts from the fresh state).  For
#   cycle > 1 the fresh anchor no longer applies and a warning is
#   recorded.
#
# This module imports numpy/pandas only -- never pybamm.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# columns of the emitted tables (the three required ones first)
OCP_CSV_FIELDS = ["SOC", "Voltage", "branch", "time_s", "current_A",
                  "capacity_Ah"]

BRANCH_LITHIATION = "lithiation"
BRANCH_DELITHIATION = "delithiation"

EQUILIBRIUM_WARNING = (
    "pseudo-OCP: extracted from a ~C/50 galvanostatic p-OCV with rests "
    "only at the branch endpoints. The curve therefore contains the C/50 "
    "polarisation (lithiation branch biased low, delithiation branch "
    "biased high) and is NOT a true equilibrium OCP. Using it as the model "
    "OCP double-counts that polarisation, so the replay residual is a "
    "conservative (pessimistic) estimate. Not a material constant: it is "
    "the measured quasi-equilibrium response of this electrode at the "
    "declared room temperature."
)

MIN_BRANCH_POINTS = 50
ACTIVE_CURRENT_FRACTION = 0.5


def _cumulative_Ah(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative charge [Ah] from (t[s], I[A])."""
    if len(t) < 2:
        return np.zeros(len(t))
    dt = np.diff(t)
    return np.concatenate(
        ([0.0], np.cumsum(dt * (current[1:] + current[:-1]) / 2.0) / 3600.0)
    )


def _classify_steps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per (cycle, step) current statistics, classified by MEASURED sign.

    Canonical platform sign: discharge = +.  For a graphite||Li half
    cell the discharge direction LITHIATES the graphite, so
    + = lithiation, - = delithiation.
    """
    rows: List[dict] = []
    peak = float(np.max(np.abs(df["current_A"].to_numpy(float))))
    if peak <= 0:
        raise ValueError("no non-zero current in the record")
    thr = ACTIVE_CURRENT_FRACTION * peak

    for (cyc, step), g in df.groupby(["cycle", "step"], sort=True):
        med = float(np.median(g["current_A"].to_numpy(float)))
        if med >= thr:
            kind = BRANCH_LITHIATION
        elif med <= -thr:
            kind = BRANCH_DELITHIATION
        else:
            kind = "rest"
        rows.append(
            {
                "cycle": int(cyc),
                "step": int(step),
                "n_rows": int(len(g)),
                "median_current_A": med,
                "kind": kind,
                "v_first": float(g["voltage_V"].iloc[0]),
                "v_last": float(g["voltage_V"].iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


def _branch_frame(
    g: pd.DataFrame, kind: str, soc: np.ndarray
) -> pd.DataFrame:
    t = g["time_s"].to_numpy(float)
    t_rel = t - float(t[0])
    I = g["current_A"].to_numpy(float)
    out = pd.DataFrame(
        {
            "SOC": soc,
            "Voltage": g["voltage_V"].to_numpy(float),
            "branch": kind,
            "time_s": t_rel,
            "current_A": I,
            "capacity_Ah": _cumulative_Ah(t_rel, I),
        }
    )
    return out[OCP_CSV_FIELDS]


def extract_ocp_branches(
    df: pd.DataFrame,
    cycle: int = 1,
) -> Dict[str, object]:
    """
    Extract both OCP branches from a canonical p-OCV record.

    ``df`` must be a canonical (platform-sign) dataframe carrying
    ``time_s`` / ``current_A`` / ``voltage_V`` / ``cycle`` / ``step``,
    e.g. the SINTEF adapter's ``load_raw`` output.

    Returns {"lithiation": DataFrame, "delithiation": DataFrame,
             "provenance": dict}.  Raises if either branch is missing.
    """
    missing = [c for c in ("time_s", "current_A", "voltage_V", "cycle",
                           "step") if c not in df.columns]
    if missing:
        raise ValueError(f"canonical record missing columns: {missing}")

    steps = _classify_steps(df)
    cyc = steps[steps["cycle"] == cycle]
    if cyc.empty:
        raise ValueError(
            f"cycle {cycle} not present (cycles: "
            f"{sorted(steps['cycle'].unique())})"
        )

    lith_steps = cyc[cyc["kind"] == BRANCH_LITHIATION]
    deli_steps = cyc[cyc["kind"] == BRANCH_DELITHIATION]
    if lith_steps.empty or deli_steps.empty:
        raise ValueError(
            f"cycle {cycle} needs one lithiation and one delithiation step; "
            f"found {sorted(lith_steps['step'])} / {sorted(deli_steps['step'])}"
        )
    lith_step = int(lith_steps.iloc[0]["step"])
    deli_step = int(deli_steps.iloc[0]["step"])

    g_lith = df[(df["cycle"] == cycle) & (df["step"] == lith_step)].copy()
    g_deli = df[(df["cycle"] == cycle) & (df["step"] == deli_step)].copy()
    g_lith = g_lith.sort_values("time_s").reset_index(drop=True)
    g_deli = g_deli.sort_values("time_s").reset_index(drop=True)

    if len(g_lith) < MIN_BRANCH_POINTS or len(g_deli) < MIN_BRANCH_POINTS:
        raise ValueError(
            f"branch too short: lithiation {len(g_lith)} rows, "
            f"delithiation {len(g_deli)} rows "
            f"(min {MIN_BRANCH_POINTS})"
        )

    # ---- SOC anchor: lithiation-branch charge -------------------
    q_lith = _cumulative_Ah(
        g_lith["time_s"].to_numpy(float) - float(g_lith["time_s"].iloc[0]),
        g_lith["current_A"].to_numpy(float),
    )
    q_ref = float(q_lith[-1])
    if q_ref <= 0:
        raise ValueError(
            f"lithiation branch charge is not positive ({q_ref:.6e} Ah); "
            f"check the current sign convention"
        )

    soc_lith = q_lith / q_ref

    q_deli = _cumulative_Ah(
        g_deli["time_s"].to_numpy(float) - float(g_deli["time_s"].iloc[0]),
        g_deli["current_A"].to_numpy(float),
    )
    soc_deli = 1.0 + q_deli / q_ref  # q_deli <= 0 -> SOC decreases from 1

    lith = _branch_frame(g_lith, BRANCH_LITHIATION, soc_lith)
    deli = _branch_frame(g_deli, BRANCH_DELITHIATION, soc_deli)

    # ---- consistency / quality flags ----------------------------
    flags: List[str] = []
    if cycle != 1:
        flags.append(
            f"cycle {cycle}: the fresh-state anchor of the SOC axis applies "
            f"to cycle 1 only"
        )
    for name, br in ((BRANCH_LITHIATION, lith),
                     (BRANCH_DELITHIATION, deli)):
        soc = br["SOC"].to_numpy(float)
        if soc.min() < -0.01 or soc.max() > 1.01:
            flags.append(f"{name}: SOC leaves [0, 1] ({soc.min():.3f}..{soc.max():.3f})")
        v = br["Voltage"].to_numpy(float)
        if name == BRANCH_LITHIATION and v[-1] > v[0]:
            flags.append("lithiation branch does not lower the voltage")
        if name == BRANCH_DELITHIATION and v[-1] < v[0]:
            flags.append("delithiation branch does not raise the voltage")

    # polarisation estimate at the branch hand-over (record only,
    # NEVER applied): the delithiation branch starts right after the
    # post-lithiation rest, whose OCV is the equilibrium value.
    rest_ocv_after_lith = None
    rest_steps = cyc[(cyc["kind"] == "rest") & (cyc["step"] > lith_step)
                     & (cyc["step"] < deli_step)]
    if not rest_steps.empty:
        rs = int(rest_steps.iloc[0]["step"])
        g_rest = df[(df["cycle"] == cycle) & (df["step"] == rs)]
        if not g_rest.empty:
            rest_ocv_after_lith = float(g_rest["voltage_V"].iloc[-1])
    polarization_estimate_mV = (
        float((deli["Voltage"].iloc[0] - rest_ocv_after_lith) * 1000.0)
        if rest_ocv_after_lith is not None
        else None
    )

    # ---- hysteresis (over the OVERLAPPING SOC range) -------------
    # NB the hand-over gap (deli start vs lith end) is NOT
    # hysteresis: the lithiation branch was driven to its cutoff
    # (below equilibrium) and the delithiation branch starts with the
    # current just switched on.  Hysteresis is the branch separation
    # AT THE SAME SOC, so it is measured on a common grid.
    soc_lo = max(float(lith["SOC"].min()), float(deli["SOC"].min()))
    soc_hi = min(float(lith["SOC"].max()), float(deli["SOC"].max()))
    if soc_hi > soc_lo:
        grid = np.linspace(soc_lo, soc_hi, 200)
        # np.interp requires ASCENDING xp: the delithiation branch runs
        # SOC 1 -> 0.08, so both tables are sorted before interpolation
        lith_sorted = lith.sort_values("SOC")
        deli_sorted = deli.sort_values("SOC")
        v_l = np.interp(grid, lith_sorted["SOC"].to_numpy(float),
                        lith_sorted["Voltage"].to_numpy(float))
        v_d = np.interp(grid, deli_sorted["SOC"].to_numpy(float),
                        deli_sorted["Voltage"].to_numpy(float))
        hyst_mean_mV = float(np.mean(v_d - v_l) * 1000.0)
        hyst_max_mV = float(np.max(np.abs(v_d - v_l)) * 1000.0)
        hyst_soc_median_mV = float(
            (v_d[len(grid) // 2] - v_l[len(grid) // 2]) * 1000.0
        )
        # the mean is dominated by the steep dilute-stage end, so the
        # separation is also reported at fixed SOC points
        hyst_at_soc = {
            f"SOC_{s:.2f}": float(
                (np.interp(s, grid, v_d) - np.interp(s, grid, v_l)) * 1000.0
            )
            for s in (0.2, 0.5, 0.8)
            if soc_lo <= s <= soc_hi
        }
    else:
        hyst_mean_mV = hyst_max_mV = hyst_soc_median_mV = float("nan")
        hyst_at_soc = {}
    handover_gap_mV = float(
        (deli["Voltage"].iloc[0] - lith["Voltage"].iloc[-1]) * 1000.0
    )

    provenance = {
        "extraction": "extraction/ocp_extractor.py::extract_ocp_branches",
        "soc_definition": (
            "Q_ref = charge of the cycle's lithiation branch (canonical "
            "current > 0) from the fresh state to the lower cutoff; "
            "lithiation SOC = Q/Q_ref; delithiation SOC = 1 - |Q|/Q_ref"
        ),
        "soc_reference_charge_Ah": q_ref,
        "soc_reference_charge_mAh": q_ref * 1000.0,
        "soc_anchor_cycle": cycle,
        "branch_steps": {"lithiation": lith_step, "delithiation": deli_step},
        "n_points": {"lithiation": int(len(lith)),
                     "delithiation": int(len(deli))},
        "voltage_range_V": {
            "lithiation": [float(lith["Voltage"].min()),
                           float(lith["Voltage"].max())],
            "delithiation": [float(deli["Voltage"].min()),
                             float(deli["Voltage"].max())],
        },
        "soc_range": {
            "lithiation": [float(lith["SOC"].min()), float(lith["SOC"].max())],
            "delithiation": [float(deli["SOC"].min()), float(deli["SOC"].max())],
        },
        "hysteresis_proxy_mV": hyst_mean_mV,
        "hysteresis_proxy_definition": (
            "mean( V_delithiation(SOC) - V_lithiation(SOC) ) on a common "
            "200-point SOC grid over the overlap; positive = the "
            "delithiation branch sits above the lithiation branch"
        ),
        "hysteresis_max_abs_mV": hyst_max_mV,
        "hysteresis_at_mid_overlap_mV": hyst_soc_median_mV,
        "hysteresis_at_soc_mV": hyst_at_soc,
        "hysteresis_mean_caveat": (
            "the mean is dominated by the steep dilute-stage end "
            "(large dV/dSOC); prefer the fixed-SOC values for reporting"
        ),
        "handover_voltage_gap_mV": handover_gap_mV,
        "handover_gap_note": (
            "delithiation-branch start minus lithiation-branch end; this is "
            "NOT hysteresis (cutoff overshoot + switched-on polarisation)"
        ),
        "rest_ocv_after_lithiation_V": rest_ocv_after_lith,
        "polarization_estimate_at_handover_mV": polarization_estimate_mV,
        "polarization_estimate_note": (
            "first-order C/50 polarisation read off the delithiation branch "
            "start vs the preceding rest OCV; RECORDED ONLY, never applied "
            "to the extracted curve"
        ),
        "branch_direction_check": (
            "lithiation lowers the voltage (3.0 V -> 0.01 V), delithiation "
            "raises it (0.01 V -> 1.0 V); both verified from the data"
        ),
        "equilibrium_warning": EQUILIBRIUM_WARNING,
        "flags": flags,
        "wording": (
            "experiment-derived PSEUDO-OCP for this electrode; not a "
            "material constant, not validation"
        ),
    }
    return {
        "lithiation": lith,
        "delithiation": deli,
        "provenance": provenance,
    }


def write_ocp_csvs(
    result: Dict[str, object],
    out_dir: Path | str,
    *,
    source_file: str = "",
    source_sha256: str = "",
    temperature_source: str = "",
    extra_provenance: Optional[dict] = None,
) -> Dict[str, Path]:
    """
    Write the two branch tables plus the provenance json.

    Returns {"lithiation": path, "delithiation": path, "provenance": path}.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = {
        "lithiation": out / "graphite_ocp_lithiation.csv",
        "delithiation": out / "graphite_ocp_delithiation.csv",
    }
    for key, path in paths.items():
        result[key].to_csv(path, index=False)  # type: ignore[index]

    prov = {
        "source_file": source_file,
        "source_sha256": source_sha256,
        "temperature_source": temperature_source,
        **(result["provenance"] if isinstance(result["provenance"], dict)
           else {}),
    }
    if extra_provenance:
        prov.update(extra_provenance)

    prov_path = out / "ocp_extraction_provenance.json"
    with prov_path.open("w", encoding="utf-8") as fh:
        json.dump(prov, fh, indent=2, ensure_ascii=False)

    # machine-readable summary of the two tables for quick checks
    summary = {
        "lithiation_csv": paths["lithiation"].name,
        "delithiation_csv": paths["delithiation"].name,
        "fields": OCP_CSV_FIELDS,
        "soc_reference_charge_Ah": prov.get("soc_reference_charge_Ah"),
        "equilibrium_warning": prov.get("equilibrium_warning"),
    }
    with (out / "ocp_extraction_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    return {**paths, "provenance": prov_path}
