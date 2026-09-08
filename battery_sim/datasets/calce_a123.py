# ============================================================
# Battery Dataset Simulation Platform v0.4
# CALCE A123 (LFP/Graphite) dynamic-protocol adapter (Steps 31-34)
#
# Chemistry generalization: NMC/LCO -> LFP with ZERO changes to
# the scientific computing logic of battery_sim/simulation/*.py
# and battery_sim/evaluation/*.py.
#
# Validated facts (docs/v04_step28_a123_audit.md):
#   * A123 Systems APR18650M1A: 1.1 Ah, LFP/graphite, 18650,
#     2.0-3.6 V (window verified in the data)
#   * TWO cells in the dynamic dataset: A1-007 and A1-008
#     (OCV files are a separate archive and are NOT replayed)
#   * ONE file per cell containing ALL THREE dynamic protocols
#     (each preceded by a full CC-CV charge + rest):
#       full charge -> rest -> dynamic profile to 2.0 V -> rest
#   * Arbin sign convention: charge = +, discharge = -
#     -> platform canonical flips sign (discharge = +)
#   * HAS a measured temperature column ("Temperature (C)_1",
#     26.5-28.4 C) -- unlike the 20R dataset, no temperature
#     assumption is needed; the measured cell temperature is the
#     isothermal-replay ambient (documented proxy).
#
# Protocol identification is RULE-BASED on the measured current
# signature (no hard-coded step numbers):
#   * candidate dynamic steps: mixed-sign current, peak |I| >= 1 A,
#     >= 500 points
#   * exactly 3 candidates are expected; the US06 profile is
#     uniquely identified by the SMALLEST regen (charge) peak, of
#     the remaining two FUDS has the LARGER charge peak, DST the
#     smaller.  The CALCE archive order (DST-US06-FUDS) must
#     agree with the chronological order of the mapped steps.
#   * the same signature ordering held in the v0.3 20R dataset
#     (US06 lowest, DST < FUDS), giving a cross-dataset check.
#
# Initial-state semantics (v0.3 freeze spec, Step 34): each
# dynamic segment starts from the protocol's own full charge
# (nominal SOC 1.0, history NOT replayed, NOT an exact
# electrochemical state under the surrogate parameterization).
# ============================================================

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.paths import ROOT
from battery_sim.schemas import DatasetConfig

# ------------------------------------------------------------------
# Dataset constants (audit-verified)
# ------------------------------------------------------------------

NOMINAL_CAPACITY_AH = 1.1

PROTOCOLS: Tuple[str, ...] = ("DST", "FUDS", "US06")

_FILENAME_RE = re.compile(
    r"A1-(?P<cell>\d+)-DST-US06-FUDS-25-(?P<date>\d{8})\.xlsx"
)

# Dynamic-step identification thresholds (same spirit as v0.3)
MIN_DYNAMIC_POINTS = 500
PEAK_CURRENT_ABS_A = 1.0
MIXED_SIGN_MIN_COUNT = 10

# Pre-profile rest-end temperature (v0.4 final temperature semantics)
REST_CURRENT_ABS_A = 0.05     # |I| below this counts as rest
REST_TEMP_WINDOW_S = 120.0    # median over the last 120 s of the rest


def _cumulative_capacity(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    return np.concatenate(
        ([0.0],
         np.cumsum((current[1:] + current[:-1]) / 2.0 * np.diff(t)) / 3600.0)
    )


def _parse_filename(path: Path) -> dict:
    m = _FILENAME_RE.search(path.name)
    if m is None:
        raise ValueError(f"cannot parse CALCE A123 filename: {path.name}")
    return {"cell": m.group("cell"), "date": m.group("date")}


def load_calce_a123_file(path: Path, data_sheet: Optional[str] = None) -> pd.DataFrame:
    """
    Load one CALCE A123 Arbin xlsx into a canonical-trace DataFrame
    (file-local trace, canonical sign, Arbin cumulative columns
    renamed with an explicit suffix).
    """
    xl = pd.ExcelFile(path)
    if data_sheet is None:
        data_sheet = next(
            s for s in xl.sheet_names if "Channel" in s
        )
    df = xl.parse(data_sheet)

    required = [
        "Test_Time(s)", "Step_Index", "Cycle_Index",
        "Current(A)", "Voltage(V)",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    t = pd.to_numeric(df["Test_Time(s)"], errors="coerce")
    V = pd.to_numeric(df["Voltage(V)"], errors="coerce")
    keep = (t.notna() & V.notna()).to_numpy()

    out = pd.DataFrame(
        {
            "time_s": t.to_numpy(dtype=float)[keep],
            "current_A": (
                # Arbin charge=+ / discharge=- -> canonical flip
                -pd.to_numeric(df["Current(A)"], errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype=float)
            )[keep],
            "voltage_V": V.to_numpy(dtype=float)[keep],
            "cycle_index": pd.to_numeric(
                df["Cycle_Index"], errors="coerce"
            ).to_numpy(dtype=float)[keep],
            "step_index": pd.to_numeric(
                df["Step_Index"], errors="coerce"
            ).to_numpy(dtype=float)[keep],
        }
    )

    # measured cell temperature (A123 HAS a temperature column)
    temp_col = next(
        (c for c in df.columns
         if "temperature" in str(c).lower()),
        None,
    )
    if temp_col is not None:
        out["temperature_cell_C"] = (
            pd.to_numeric(df[temp_col], errors="coerce")
            .to_numpy(dtype=float)[keep]
        )

    if "Date_Time" in df.columns:
        out["date_time"] = df.loc[keep, "Date_Time"].to_numpy()
    else:
        out["date_time"] = pd.NaT

    for col, name in [
        ("Discharge_Capacity(Ah)", "capacity_discharge_arbin_cumulative_Ah"),
        ("Charge_Capacity(Ah)", "capacity_charge_arbin_cumulative_Ah"),
    ]:
        if col in df.columns:
            out[name] = (
                pd.to_numeric(df[col], errors="coerce")
                .to_numpy(dtype=float)[keep]
            )

    out = out.sort_values("time_s").drop_duplicates(
        subset=["time_s"], keep="last"
    ).reset_index(drop=True)
    out["time_s"] = out["time_s"] - float(out["time_s"].iloc[0])

    return out


def _candidate_dynamic_steps(df: pd.DataFrame) -> List[Tuple[int, int, dict]]:
    """
    Rule-based dynamic-step candidates (no hard-coded step numbers):
    mixed-sign current, peak |I| >= threshold, enough points.
    Returns [(cycle, step, stats), ...] ordered by start time.
    """
    cands = []
    for (cyc, step), seg in df.groupby(["cycle_index", "step_index"]):
        if len(seg) < MIN_DYNAMIC_POINTS:
            continue
        I = seg["current_A"].to_numpy(dtype=float)
        n_pos = int((I > 0).sum())
        n_neg = int((I < 0).sum())
        if n_pos < MIXED_SIGN_MIN_COUNT or n_neg < MIXED_SIGN_MIN_COUNT:
            continue
        if float(np.max(np.abs(I))) < PEAK_CURRENT_ABS_A:
            continue
        t = seg["time_s"].to_numpy(dtype=float)
        cands.append(
            (int(cyc), int(step), {
                "n": int(len(seg)),
                "start_s": float(t[0]),
                "duration_s": float(t[-1] - t[0]),
                "peak_discharge_A": float(I.max()),   # canonical +
                "peak_charge_A": float(-I.min()),     # magnitude
            })
        )
    cands.sort(key=lambda x: x[2]["start_s"])
    return cands


def _map_protocols(
    cands: List[Tuple[int, int, dict]]
) -> Dict[str, Tuple[int, int, dict]]:
    """
    Map the (exactly 3) dynamic-step candidates to protocols by the
    measured charge-peak signature (US06 smallest regen; of the rest,
    FUDS larger than DST), cross-checked against the CALCE archive
    order DST -> US06 -> FUDS.  Raises on ambiguity.
    """
    if len(cands) != 3:
        raise RuntimeError(
            f"expected exactly 3 dynamic steps (DST/US06/FUDS), "
            f"found {len(cands)}"
        )

    by_charge_peak = sorted(cands, key=lambda x: x[2]["peak_charge_A"])
    us06 = by_charge_peak[0]
    fuds, dst = sorted(by_charge_peak[1:], key=lambda x: -x[2]["peak_charge_A"])

    mapping = {"US06": us06, "FUDS": fuds, "DST": dst}

    # cross-check: chronological order must be DST, US06, FUDS
    chrono = sorted(cands, key=lambda x: x[2]["start_s"])
    expected = [mapping[p] for p in ("DST", "US06", "FUDS")]
    if [id(c) for c in chrono] != [id(c) for c in expected]:
        raise RuntimeError(
            "protocol signature mapping disagrees with the CALCE "
            "archive order DST->US06->FUDS; refusing to guess"
        )

    return mapping


def _preprofile_rest_temperature(df: pd.DataFrame, seg_start_time: float) -> float:
    """
    v0.4 final temperature semantics: the isothermal replay
    environment is the MEASURED cell temperature at the end of the
    rest immediately preceding the dynamic profile (the cell has
    relaxed there; it is the closest available proxy for the
    chamber temperature, which this archive does not record).

    Rule-based: walk backwards from the dynamic-step start over the
    contiguous rest segment (|I| < REST_CURRENT_ABS_A), take the
    median measured cell temperature over its last
    REST_TEMP_WINDOW_S seconds.  Raises if no such rest exists.
    """
    pre = df[df["time_s"] < seg_start_time - 1e-9]
    if pre.empty:
        raise ValueError(
            "no data before the dynamic step; cannot determine "
            "the pre-profile rest temperature"
        )
    I = pre["current_A"].to_numpy(dtype=float)
    T = pre["temperature_cell_C"].to_numpy(dtype=float)
    t = pre["time_s"].to_numpy(dtype=float)

    is_rest = np.abs(I) < REST_CURRENT_ABS_A
    end = len(pre) - 1
    # tolerate one boundary sample (e.g. a settling point at the
    # step switch) but the segment must END in rest
    if not is_rest[end]:
        end -= 1
        if end < 0 or not is_rest[end]:
            raise ValueError(
                "the step preceding the dynamic profile is not a "
                "rest; refusing to invent an ambient temperature"
            )
    start = end
    while start > 0 and is_rest[start - 1]:
        start -= 1

    rest_end_t = t[end]
    mask = (t >= rest_end_t - REST_TEMP_WINDOW_S) & (t <= rest_end_t)
    temp = T[mask & np.isfinite(T)]
    if temp.size == 0:
        raise ValueError(
            "no finite temperature samples in the pre-profile rest"
        )
    return float(np.median(temp))


def _canonical_window(seg: pd.DataFrame, provenance: dict,
                      ambient_T: float) -> pd.DataFrame:
    """
    Canonical replay window: strictly increasing time, relative to
    window start, canonical columns + measured cell temperature.
    Enriches ``provenance`` in place.
    """
    seg = seg.sort_values("time_s").reset_index(drop=True)

    t = seg["time_s"].to_numpy(dtype=float)
    I = seg["current_A"].to_numpy(dtype=float)
    V = seg["voltage_V"].to_numpy(dtype=float)

    keep = np.concatenate(([True], np.diff(t) > 0))
    n_dropped = int((~keep).sum())
    t, I, V = t[keep], I[keep], V[keep]

    T_cell = (
        seg["temperature_cell_C"].to_numpy(dtype=float)[keep]
        if "temperature_cell_C" in seg.columns
        else np.full_like(t, np.nan)
    )

    t_rel = t - t[0]

    out = pd.DataFrame(
        {
            "time_s": t_rel,
            "current_A": I,
            "voltage_V": V,
            "capacity_Ah": _cumulative_capacity(t_rel, I),
            # measured cell temperature: VALIDATION TARGET ONLY
            # (a response quantity; must never drive the model)
            "temperature_cell_C": T_cell,
            # isothermal replay environment: FIXED at the
            # pre-profile rest-end measured cell temperature
            "temperature_ambient_C": np.full(t_rel.shape, float(ambient_T)),
        }
    )

    assert np.all(np.diff(out["time_s"].to_numpy()) > 0)

    provenance.update({
        "n_points": int(len(out)),
        "n_points_dropped_nonincreasing_time": n_dropped,
        "duration_s": float(t_rel[-1]),
        "voltage_start_V": float(V[0]),
        "voltage_end_V": float(V[-1]),
        "current_peak_discharge_A": float(I.max()),
        "current_peak_charge_A": float(-I.min()),
        "current_rms_A": float(np.sqrt(np.mean(I ** 2))),
        "integrated_charge_Ah": float(out["capacity_Ah"].iloc[-1]),
        # --- temperature semantics (v0.4 final freeze) ---
        "initial_temperature_C": float(ambient_T),
        "ambient_temperature_C": float(ambient_T),
        "ambient_temperature_source": (
            "assumed_from_preprofile_rest_cell_temperature"
        ),
        "measured_cell_temperature_role": "validation_target_only",
        # diagnostics over the measured trace (not model inputs)
        "temperature_median_C": float(np.nanmedian(T_cell)),
        "temperature_range_C": [float(np.nanmin(T_cell)),
                                float(np.nanmax(T_cell))],
        "time_axis_checks": {
            "sorted": True,
            "duplicates_removed_at_load": True,
            "strictly_increasing": True,
            "nan_current_or_voltage": 0,
        },
    })

    out.attrs["provenance"] = provenance
    out.attrs["initial_soc"] = provenance["initial_soc"]
    return out


class CalceA123Adapter(BatteryDatasetAdapter):
    """
    Adapter for the CALCE A123 (LFP/graphite) dynamic dataset.

    Window ids ("rates" channel -- the replay runner only knows
    ids -> windows): DST, FUDS, US06 per cell (007 / 008).
    """

    SOURCE_TO_CANONICAL: Dict[str, float] = {}

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir

        extra = config.extra or {}

        # A123 has a MEASURED temperature column, so unlike 20R the
        # adapter needs no assumed value.  The config may still
        # carry the chamber-nominal note; if it carries a value_C
        # block it is informational only (audit text), not used
        # numerically here.
        amb = extra.get("ambient_temperature")
        self._temperature_note = (
            str(amb.get("note", "")) if isinstance(amb, dict) else ""
        )
        self._temperature_source = (
            str(amb.get("source", "measured_cell_temperature_column"))
            if isinstance(amb, dict)
            else "measured_cell_temperature_column"
        )

        self._parameter_match = dict(extra.get("parameter_match", {}))
        dyn = extra.get("dynamic_protocol", {})
        self._profile_kind = str(dyn.get("profile_kind", "dynamic"))
        self._initial_soc_source = str(
            dyn.get(
                "initial_soc_source",
                "protocol full charge (CC-CV to 3.6 V) immediately before each dynamic segment",
            )
        )
        # Step 34 / freeze spec: the initial SOC is OWNED BY THE
        # CONFIG (no Python-side default).  Under Prada2013 the
        # model OCV at nominal SOC 1.0 sits AT its own upper-cutoff
        # event boundary (surrogate stoichiometry mismatch), so the
        # config pins the highest audited SOC that starts cleanly;
        # replay RMSE is insensitive over 0.98-0.995 (LFP plateau).
        if "initial_soc_value" not in dyn:
            raise ValueError(
                f"dataset '{config.dataset_id}': dynamic_protocol."
                f"initial_soc_value missing in configs/datasets.yaml "
                f"(the adapter does not invent initial states)"
            )
        self._initial_soc_value = float(dyn["initial_soc_value"])

        self._cell_files: Dict[str, Path] = {}
        for path in sorted((self._raw_dir).glob("*.xlsx")):
            meta = _parse_filename(path)
            self._cell_files[meta["cell"]] = path

    # ------------------------------------------------------------------
    # Metadata / cells / protocol listing
    # ------------------------------------------------------------------
    def get_metadata(self) -> dict:
        cfg = self.config
        return {
            "dataset_id": cfg.dataset_id,
            "name": cfg.name,
            "ion": cfg.ion,
            "chemistry": cfg.chemistry,
            "parameter_set": cfg.parameter_set,
            "nominal_capacity_Ah": (
                cfg.nominal_capacity_Ah or NOMINAL_CAPACITY_AH
            ),
            "cells": cfg.cells,
            "rates": cfg.rates,
            "protocols": list(PROTOCOLS),
            "profile_kind": self._profile_kind,
            "temperature_source": self._temperature_source,
            "temperature_note": self._temperature_note,
            "initial_soc_source": self._initial_soc_source,
            "initial_soc_confidence": "medium",
            "parameter_match": self._parameter_match,
        }

    def list_cells(self):
        return list(self.config.cells)

    def list_protocols(self) -> List[str]:
        return list(PROTOCOLS)

    def list_rates(self):
        """Window ids: the three protocols (identical for both cells)."""
        return list(PROTOCOLS)

    def expand_protocol(self, protocol: str) -> List[str]:
        p = str(protocol).upper()
        if p in PROTOCOLS:
            return [p]
        raise KeyError(f"unknown protocol '{protocol}'")

    # ------------------------------------------------------------------
    # Canonical window resolution
    # ------------------------------------------------------------------
    def rate_info(self, rate) -> Dict[str, object]:
        pid = str(rate).strip().upper()
        if pid not in PROTOCOLS:
            raise KeyError(
                f"unknown window id '{rate}'; available: {self.list_rates()}"
            )
        return {
            "c_rate": float("nan"),
            "rate_label": pid,
            "rate_slug": pid,
            "source_rate": pid,
            "legacy_rate": pid,
            "protocol_id": pid,
        }

    def rate_for_cell(self, cell: str) -> str:
        return ""

    def canonical_rate_slug_for_cell(self, cell: str) -> str:
        return ""

    # ------------------------------------------------------------------
    # File access
    # ------------------------------------------------------------------
    def cell_file(self, cell: str) -> Path:
        cell = str(cell)
        if cell not in self._cell_files:
            raise KeyError(
                f"cell '{cell}' not found; available: "
                f"{sorted(self._cell_files)}"
            )
        return self._cell_files[cell]

    def load_raw(self, cell) -> pd.DataFrame:
        return load_calce_a123_file(self.cell_file(str(cell)))

    # ------------------------------------------------------------------
    # Dynamic window extraction (canonical, rule-based)
    # ------------------------------------------------------------------
    def _load_window(self, cell: str, protocol: str) -> Tuple[pd.DataFrame, dict]:
        pid = str(protocol).strip().upper()
        if pid not in PROTOCOLS:
            raise KeyError(f"unknown protocol '{protocol}'")

        path = self.cell_file(str(cell))
        df = load_calce_a123_file(path)

        cands = _candidate_dynamic_steps(df)
        mapping = _map_protocols(cands)
        cyc, step, stats = mapping[pid]

        seg = df[
            (df["cycle_index"] == cyc) & (df["step_index"] == step)
        ].copy()

        # v0.4 final temperature semantics: isothermal environment
        # anchored at the pre-profile rest-end measured cell
        # temperature (NOT the in-profile T_cell(t), which is a
        # response quantity kept only as a validation target)
        ambient_T = _preprofile_rest_temperature(
            df, float(seg["time_s"].iloc[0])
        )

        provenance = {
            "protocol_id": pid,
            "profile_kind": self._profile_kind,
            "source_file": path.name,
            "source_cycle": int(cyc),
            "source_step": int(step),
            "initial_soc": self._initial_soc_value,
            "initial_soc_source": self._initial_soc_source,
            "initial_soc_confidence": "medium",
            # v0.3 freeze spec + v0.4 wording freeze: explicit
            # initial-state semantics.  The SOC value is a stable
            # surrogate initialization, NOT a measured cell SOC and
            # NOT fitted to the measured voltage.
            "initial_state": {
                "type": "surrogate_ocv_mapped_soc",
                "value": self._initial_soc_value,
                "purpose": "stable surrogate initialization",
                "fitted_to_voltage": False,
                "source": (
                    "protocol full charge; SOC is the highest audited "
                    "value that does not place the Prada2013 model at "
                    "its own upper-cutoff event boundary (model rest V "
                    "3.484 V vs measured 3.554 V; replay RMSE "
                    "insensitive over SOC 0.98-0.995, LFP plateau). "
                    "Do NOT report this as 'the cell is at 99.5% SOC'."
                ),
                "history_replayed": False,
                "is_exact_electrochemical_state": False,
            },
            "protocol_identification": {
                "rule": (
                    "mixed-sign current, peak |I| >= "
                    f"{PEAK_CURRENT_ABS_A} A, >= {MIN_DYNAMIC_POINTS} "
                    "points; US06 = smallest charge peak, FUDS = "
                    "larger of the rest, DST = smaller; cross-checked "
                    "against CALCE archive order DST-US06-FUDS"
                ),
                "candidate_steps": [
                    {"cycle": c, "step": s, **st}
                    for c, s, st in cands
                ],
            },
            "parameter_set": self.config.parameter_set,
            "parameter_match": self._parameter_match,
        }

        window_df = _canonical_window(seg, provenance, ambient_T)
        return window_df, dict(window_df.attrs["provenance"])

    def load_profile(self, cell, protocol) -> pd.DataFrame:
        df, _ = self._load_window(str(cell), str(protocol))
        return df

    def profile_info(self, cell: str, protocol: str) -> dict:
        df, provenance = self._load_window(str(cell), str(protocol))
        info = self.rate_info(protocol)
        return {
            "dataset": self.config.name,
            "cell_id": f"A1-{cell}",
            "protocol_id": str(info["protocol_id"]),
            "profile_kind": self._profile_kind,
            "rate_slug": str(info["rate_slug"]),
            "n_points": int(len(df)),
            "duration_s": float(df["time_s"].iloc[-1]),
            "voltage_start_V": float(df["voltage_V"].iloc[0]),
            "voltage_end_V": float(df["voltage_V"].iloc[-1]),
            "integrated_charge_Ah": float(df["capacity_Ah"].iloc[-1]),
            "temperature_median_C": provenance["temperature_median_C"],
            "initial_soc": float(df.attrs["initial_soc"]),
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Baseline-replay input (same schema as chen2020/calce_cs2/calce_20r)
    # ------------------------------------------------------------------
    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        df, provenance = self._load_window(str(cell), str(rate))
        df = df.copy()
        df.attrs["provenance"] = provenance
        df.attrs["initial_soc"] = provenance["initial_soc"]
        return df

    # ------------------------------------------------------------------
    # Initial / environmental state
    # ------------------------------------------------------------------
    def get_initial_state(self, cell) -> float:
        """Measured cell voltage at the start of the DST window."""
        df, _ = self._load_window(str(cell), "DST")
        return float(df["voltage_V"].iloc[0])

    def get_ambient_temperature(self, cell) -> float:
        """
        Isothermal replay environment: the pre-profile rest-end
        measured cell temperature (DST window, per the v0.4 final
        temperature semantics).
        """
        df, prov = self._load_window(str(cell), "DST")
        return float(prov["ambient_temperature_C"])


# Registry compatibility: adapter id 'calce_a123' resolves to
# class 'CalceA123Adapter' directly (PascalCase join).
