# ============================================================
# Battery Dataset Simulation Platform v0.2
# CALCE CS2 dataset adapter (Step 14)
#
# Translates the CALCE CS2 Arbin/MITS xlsx logs into the platform
# canonical schema.  This is the first second-dataset adapter: it
# must work through the SAME runner / evaluator / output schema as
# chen2020 with ZERO changes to the scientific computing logic of
# battery_sim/simulation/*.py and battery_sim/evaluation/*.py.
#
# Validated scientific facts (CALCE official page + file audit):
#   * CS2: LiCoO2 cathode / graphite, 1.1 Ah prismatic,
#     5.4 x 33.6 x 50.6 mm, weight 21.1 g
#   * Charge (all CS2): CC-CV, 0.5C -> 4.2 V, CV until I < 0.05 A
#   * Discharge cutoff 2.7 V
#       CS2_33 (Type 1): constant-current 0.5C  (0.55 A)
#       CS2_35 (Type 2): constant-current 1C    (1.1 A)
#   * Arbin sign convention: charge = +, discharge = -
#     -> platform canonical flips sign (discharge = +)
#
# Audit traps handled (docs/v02_step12_13_calce_audit_and_mapping.md):
#   T1 sign flip            T2 capacity column is cumulative
#                           (never used; capacity integrated from I)
#   T3 filename order !=    T4 Cycle/Step reset per file
#      chronological order
#   T5 single-point pseudo  T6 CV step is not CC
#      steps
#   T7 no temperature data  -> platform modeling assumption
#      (config: assumed, confidence low)
#
# Discharge segments are identified by RULES (current sign, CC
# amplitude, minimum points, voltage direction, 2.7 V cutoff) --
# never by a hard-coded (cycle, step) locator.
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
# Nominal / per-cell rates (CALCE official description)
# ------------------------------------------------------------------

NOMINAL_CAPACITY_AH = 1.1

CELL_RATES: Dict[str, str] = {
    "33": "0p5C",
    "35": "1C",
}

RATE_C_RATE: Dict[str, float] = {
    "0p5C": 0.5,
    "1C": 1.0,
}

# Canonical rate normalization (platform-wide): CALCE's "0p5C" is
# the same numeric C-rate as Chen2020's legacy "C2".  Cross-dataset
# comparisons must key on c_rate, never on source/legacy strings.
SOURCE_TO_CANONICAL: Dict[str, float] = {
    "0p5C": 0.5,
    # "1C" resolves canonically without a mapping
}

DEFAULT_RATES: Tuple[str, ...] = ("0p5C", "1C")

# Segment identification tolerances
CURRENT_RTOL = 0.10        # |median I - expected| <= 10% of expected
MIN_DISCHARGE_POINTS = 10  # excludes pseudo steps (T5)
V_DROP_MIN_V = 0.20        # discharge must actually go down
V_CUTOFF_TOL_V = 0.15      # end near 2.7 V / start near 4.2 V
REST_CURRENT_ABS_A = 0.01

_FILENAME_DATE_RE = re.compile(
    r"CS2_(?P<cell>\d+)_(?P<mo>\d+)_(?P<day>\d+)_(?P<yy>\d+)"
)


def _file_sort_key(path: Path) -> Tuple:
    """Chronological key from 'CS2_33_9_7_10.xlsx' (M_D_YY). (T3)"""
    m = _FILENAME_DATE_RE.search(path.name)
    if m is None:
        return (0, 0, 0, path.name)
    yy = int(m.group("yy"))
    year = 2000 + yy if yy < 50 else 1900 + yy
    return (year, int(m.group("mo")), int(m.group("day")), path.name)


def _cumulative_capacity(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    try:
        return np.concatenate(
            ([0.0], np.cumsum((current[1:] + current[:-1]) / 2.0 * np.diff(t)) / 3600.0)
        )
    except Exception:  # pragma: no cover - numpy always has these
        return np.concatenate(([0.0], np.cumsum(np.diff(t) * (current[1:] + current[:-1]) / 2.0) / 3600.0))


def load_calce_file(path: Path) -> pd.DataFrame:
    """
    Load one CALCE CS2 xlsx into a canonical-trace DataFrame.

    Columns produced:
        time_s            file-local test time (file starts at t=0)
        current_A         CANONICAL sign (discharge +, charge -)  (T1)
        voltage_V
        cycle_index / step_index   as recorded in this file (T4:
                          caller adds the file offset if needed)
        date_time         original Arbin timestamp

    The cumulative Discharge/Charge_Capacity columns are read but
    renamed with an explicit ``_arbin_cumulative`` suffix so that no
    downstream code mistakes them for per-segment capacity.  (T2)
    """
    xl = pd.ExcelFile(path)

    sheet = next(s for s in xl.sheet_names if "Channel" in s)
    df = xl.parse(sheet)

    required = [
        "Test_Time(s)",
        "Step_Index",
        "Cycle_Index",
        "Current(A)",
        "Voltage(V)",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    t = pd.to_numeric(df["Test_Time(s)"], errors="coerce")
    V = pd.to_numeric(df["Voltage(V)"], errors="coerce")
    keep = t.notna() & V.notna()

    out = pd.DataFrame(
        {
            "time_s": t[keep].to_numpy(dtype=float),
            "current_A": (
                # T1: CALCE charge=+ / discharge=- -> flip to canonical
                -pd.to_numeric(df["Current(A)"], errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype=float)
            )[keep.to_numpy()],
            "voltage_V": V[keep].to_numpy(dtype=float),
            "cycle_index": (
                pd.to_numeric(df["Cycle_Index"], errors="coerce")
                .to_numpy(dtype=float)[keep.to_numpy()]
            ),
            "step_index": (
                pd.to_numeric(df["Step_Index"], errors="coerce")
                .to_numpy(dtype=float)[keep.to_numpy()]
            ),
        }
    )

    if "Date_Time" in df.columns:
        out["date_time"] = df.loc[keep, "Date_Time"].to_numpy()
    else:
        out["date_time"] = pd.NaT

    # T2: keep Arbin cumulative capacity, clearly renamed
    for col, name in [
        ("Discharge_Capacity(Ah)", "capacity_discharge_arbin_cumulative_Ah"),
        ("Charge_Capacity(Ah)", "capacity_charge_arbin_cumulative_Ah"),
    ]:
        if col in df.columns:
            out[name] = (
                pd.to_numeric(df[col], errors="coerce")
                .to_numpy(dtype=float)[keep.to_numpy()]
            )

    out = out.sort_values("time_s").drop_duplicates(
        subset=["time_s"], keep="last"
    ).reset_index(drop=True)

    out["time_s"] = out["time_s"] - float(out["time_s"].iloc[0])

    return out


class CalceCs2Adapter(BatteryDatasetAdapter):
    """
    Adapter for the CALCE CS2 dataset (cells 33 and 35 in v0.2).

    Rate semantics per cell (CALCE official):
        cell 33 -> 0.5C CC discharge (0.55 A)  canonical: C/2 (C0p5)
        cell 35 -> 1C   CC discharge (1.1 A)   canonical: 1C  (C1)

    ``rate`` arguments accept the canonical slug ("C0p5", "C1"),
    the legacy id ("C2", "1C"), the CALCE source label ("0p5C",
    "1C") or a numeric string ("0.5").
    """

    SOURCE_TO_CANONICAL = SOURCE_TO_CANONICAL

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir

        extra = config.extra or {}

        # B: the missing-temperature assumption is OWNED BY THE
        # CONFIG, not by this adapter.  No Python-side default.
        amb = extra.get("ambient_temperature")
        if isinstance(amb, dict) and "value_C" in amb:
            self._ambient_C = float(amb["value_C"])
            self._temperature_source = str(amb.get("source", "assumed"))
            self._temperature_confidence = str(
                amb.get("confidence", "unspecified")
            )
            self._temperature_note = str(amb.get("note", ""))
        elif "ambient_temperature_C" in extra:
            # legacy flat layout (v0.2 Step 14)
            self._ambient_C = float(extra["ambient_temperature_C"])
            self._temperature_source = str(
                extra.get("temperature_source", "assumed")
            )
            self._temperature_confidence = str(
                extra.get("temperature_confidence", "low")
            )
            self._temperature_note = str(extra.get("temperature_note", ""))
        else:
            raise ValueError(
                f"dataset '{config.dataset_id}': no ambient temperature "
                f"assumption in configs/datasets.yaml (add an "
                f"'ambient_temperature: {{value_C, source, confidence}}' "
                f"block).  The adapter does not invent assumptions."
            )

        self._parameter_match = dict(extra.get("parameter_match", {}))

    # ------------------------------------------------------------------
    # Metadata / cells / rates
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
            "ambient_temperature_C": self._ambient_C,
            "temperature_source": self._temperature_source,
            "temperature_confidence": self._temperature_confidence,
            "parameter_match": self._parameter_match,
        }

    def list_cells(self):
        return list(self.config.cells)

    def list_rates(self):
        rates = list(self.config.rates)
        return rates if rates else list(DEFAULT_RATES)

    def rate_for_cell(self, cell: str) -> str:
        """The (single) CC discharge rate CALCE used for this cell."""
        return CELL_RATES.get(str(cell), "")

    def canonical_rate_slug_for_cell(self, cell: str) -> str:
        """Canonical rate_slug of the cell's CC discharge rate."""
        src = self.rate_for_cell(str(cell))
        if not src:
            return ""
        return str(self.rate_info(src)["rate_slug"])

    # ------------------------------------------------------------------
    # File discovery (chronological, T3)
    # ------------------------------------------------------------------
    def cell_files(self, cell: str) -> List[Path]:
        cell_dir = self._raw_dir / f"CS2_{cell}"
        if not cell_dir.is_dir():
            raise FileNotFoundError(f"CS2 cell dir not found: {cell_dir}")
        files = sorted(cell_dir.glob("*.xlsx"), key=_file_sort_key)
        if not files:
            raise FileNotFoundError(f"no xlsx files under {cell_dir}")
        return files

    # ------------------------------------------------------------------
    # Raw data
    # ------------------------------------------------------------------
    def load_raw(self, cell) -> pd.DataFrame:
        """
        Full canonical trace for a cell: all files concatenated in
        chronological order with a global file index and cycle
        offset (T4).  Heavy: parses every xlsx of the cell.
        """
        frames = []
        cycle_offset = 0.0
        for i, path in enumerate(self.cell_files(str(cell))):
            df = load_calce_file(path)
            df["file_index"] = i
            df["source_file"] = path.name
            df["global_cycle_index"] = df["cycle_index"] + cycle_offset
            cycle_offset = float(df["global_cycle_index"].iloc[-1])
            frames.append(df)

        out = pd.concat(frames, ignore_index=True)
        # strictly increasing global time
        out = out.drop_duplicates(subset=["time_s"], keep="last")
        return out

    # ------------------------------------------------------------------
    # Rule-based discharge segment identification
    # ------------------------------------------------------------------
    def _qualifying_segments_in_file(
        self,
        df: pd.DataFrame,
        expected_current: float,
    ) -> List[Tuple[int, int]]:
        """
        (cycle_index, step_index) of discharge segments in one file
        that satisfy the CC-discharge rules.  No (cycle, step) is
        hard-coded anywhere.
        """
        hits: List[Tuple[int, int]] = []

        if df.empty:
            return hits

        lower_cut = (
            self.config.lower_voltage_cutoff_V
            if self.config.lower_voltage_cutoff_V is not None
            else 2.7
        )
        upper_cut = (
            self.config.upper_voltage_cutoff_V
            if self.config.upper_voltage_cutoff_V is not None
            else 4.2
        )

        for (cyc, step), seg in df.groupby(["cycle_index", "step_index"]):
            if len(seg) < MIN_DISCHARGE_POINTS:       # T5
                continue

            I = seg["current_A"].to_numpy(dtype=float)
            V = seg["voltage_V"].to_numpy(dtype=float)

            median_I = float(np.median(I))

            # CC amplitude at the expected rate
            if abs(median_I - expected_current) > CURRENT_RTOL * expected_current:
                continue

            # current direction: canonical discharge is positive
            if median_I <= 0:
                continue

            # voltage must actually decrease
            if float(V[-1]) > float(V[0]) - V_DROP_MIN_V:
                continue

            # full discharge: starts near full charge, ends at cutoff
            if float(V[0]) < upper_cut - V_CUTOFF_TOL_V:
                continue
            if float(V[-1]) > lower_cut + V_CUTOFF_TOL_V:
                continue

            hits.append((int(cyc), int(step)))

        return hits

    def _find_first_full_discharge(
        self, cell: str, rate: str
    ) -> Tuple[pd.DataFrame, dict]:
        """
        First (BOL) full CC discharge at ``rate`` for ``cell``,
        scanning files in chronological order and stopping at the
        first hit.  Returns (canonical segment df, provenance dict).
        """
        info = self.rate_info(rate)
        c_rate = float(info["c_rate"])
        source_rate = str(info["source_rate"])

        expected_slug = self.canonical_rate_slug_for_cell(str(cell))
        if expected_slug and str(info["rate_slug"]) != expected_slug:
            raise ValueError(
                f"cell {cell} was cycled at {self.rate_for_cell(str(cell))} "
                f"(CALCE official; canonical {expected_slug}); "
                f"rate '{rate}' not available for this cell"
            )

        nominal = self.config.nominal_capacity_Ah or NOMINAL_CAPACITY_AH
        expected_current = c_rate * nominal

        for i, path in enumerate(self.cell_files(str(cell))):
            df = load_calce_file(path)

            for cyc, step in self._qualifying_segments_in_file(
                df, expected_current
            ):
                seg = df[
                    (df["cycle_index"] == cyc)
                    & (df["step_index"] == step)
                ].copy()

                seg = seg.sort_values("time_s").reset_index(drop=True)

                t = seg["time_s"].to_numpy(dtype=float)
                I = seg["current_A"].to_numpy(dtype=float)
                V = seg["voltage_V"].to_numpy(dtype=float)

                t_rel = t - t[0]

                out = pd.DataFrame(
                    {
                        "time_s": t_rel,
                        "current_A": I,
                        "voltage_V": V,
                        "capacity_Ah": _cumulative_capacity(t_rel, I),
                    }
                )

                provenance = {
                    "source_file": path.name,
                    "file_index": i,
                    "cycle_index": int(cyc),
                    "step_index": int(step),
                    "c_rate": c_rate,
                    "rate_label": str(info["rate_label"]),
                    "rate_slug": str(info["rate_slug"]),
                    "source_rate": source_rate,
                    "n_points": int(len(out)),
                    "duration_s": float(t_rel[-1]),
                    "voltage_start_V": float(V[0]),
                    "voltage_end_V": float(V[-1]),
                    "median_current_A": float(np.median(I)),
                    "expected_current_A": expected_current,
                    "identification": (
                        "rule-based: CC amplitude, min points, "
                        "voltage direction, cutoff voltages"
                    ),
                }

                return out, provenance

        raise RuntimeError(
            f"cell {cell}: no full CC discharge at {rate} found in "
            f"{len(self.cell_files(str(cell)))} files"
        )

    # ------------------------------------------------------------------
    # Discharge extraction (canonical)
    # ------------------------------------------------------------------
    def load_discharge(self, cell, rate) -> pd.DataFrame:
        """
        One full CC discharge at ``rate`` as a canonical DataFrame
        (time_s, current_A [discharge +], voltage_V, capacity_Ah).
        Times are relative to the discharge start.
        """
        df, _ = self._find_first_full_discharge(str(cell), rate)
        return df

    def discharge_info(self, cell: str, rate: str) -> dict:
        """Per-discharge metadata incl. segment provenance."""
        df, provenance = self._find_first_full_discharge(str(cell), rate)
        rate_info = self.rate_info(rate)
        return {
            "dataset": self.config.name,
            "cell_id": f"CS2_{cell}",
            "c_rate": float(rate_info["c_rate"]),
            "rate_label": str(rate_info["rate_label"]),
            "rate_slug": str(rate_info["rate_slug"]),
            "source_rate": str(rate_info["source_rate"]),
            "n_points": int(len(df)),
            "duration_s": float(df["time_s"].iloc[-1]),
            "voltage_start_V": float(df["voltage_V"].iloc[0]),
            "voltage_end_V": float(df["voltage_V"].iloc[-1]),
            "capacity_end_Ah": float(df["capacity_Ah"].iloc[-1]),
            "ambient_temperature_C": self.get_ambient_temperature(cell),
            "temperature_source": self._temperature_source,
            "median_current_A": float(df["current_A"].median()),
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Baseline-replay input (same schema as chen2020 processed CSVs)
    # ------------------------------------------------------------------
    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """
        Canonical discharge df for the baseline runner.  Generated
        on the fly from the raw xlsx (CALCE has no processed layer);
        ambient temperature is the platform modeling assumption.
        """
        df, provenance = self._find_first_full_discharge(str(cell), rate)
        df = df.copy()
        df["temperature_ambient_C"] = self._ambient_C
        df.attrs["provenance"] = provenance
        return df

    # ------------------------------------------------------------------
    # Initial / environmental state
    # ------------------------------------------------------------------
    def get_initial_state(self, cell) -> float:
        """
        OCV [V] from the rest immediately before the first full
        discharge (last 5 min median, or the whole rest if it is
        shorter than 5 min).
        """
        cell = str(cell)

        # first file only: the BOL discharge lives there
        path = self.cell_files(cell)[0]
        df = load_calce_file(path)

        expected_rate = self.rate_for_cell(cell)
        nominal = self.config.nominal_capacity_Ah or NOMINAL_CAPACITY_AH
        expected_current = RATE_C_RATE[expected_rate] * nominal

        cyc, step = self._qualifying_segments_in_file(
            df, expected_current
        )[0]

        seg_start_time = float(
            df[(df["cycle_index"] == cyc) & (df["step_index"] == step)][
                "time_s"
            ].iloc[0]
        )

        rest = df[
            (df["time_s"] < seg_start_time)
            & (df["current_A"].abs() < REST_CURRENT_ABS_A)
        ]

        if rest.empty:
            raise RuntimeError(
                f"cell {cell}: no rest found before the first full "
                f"discharge"
            )

        t_rest = rest["time_s"].to_numpy(dtype=float)
        tail = rest[
            t_rest >= t_rest.max() - 300
        ]

        return float(tail["voltage_V"].median())

    def get_ambient_temperature(self, cell) -> float:
        """
        Platform modeling assumption (T7): CALCE does not report
        the test temperature for CS2.  Value + confidence come from
        configs/datasets.yaml.
        """
        return self._ambient_C
