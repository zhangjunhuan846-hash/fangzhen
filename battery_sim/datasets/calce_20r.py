# ============================================================
# Battery Dataset Simulation Platform v0.3
# CALCE INR18650-20R dynamic-protocol adapter (Steps 19-22)
#
# Translates the CALCE INR18650-20R Arbin .xls dynamic tests
# (DST / FUDS / US06, at 50 % / 80 % starting SOC) into the
# platform canonical schema.  Works through the SAME runner /
# evaluator / output schema as chen2020 and calce_cs2 with ZERO
# changes to the scientific computing logic of
# battery_sim/simulation/*.py and battery_sim/evaluation/*.py.
#
# Validated scientific facts (docs/v03_step18_calce20r_audit.md):
#   * Samsung SDI INR 18650-20R: 2.0 Ah, NMC/graphite,
#     cylindrical 18650, 2.5-4.2 V
#   * One cell in the dynamic dataset: SP20-2
#     (OCV files belong to SP20-1 and are NOT replayed)
#   * One file per (protocol, SOC level); each file is a single
#     continuous test: CC-CV charge -> rest -> trim discharge to
#     target SOC -> rest -> dynamic profile repeated to 2.5 V
#     cutoff -> short final rest
#   * Arbin sign convention: charge = +, discharge = -
#     -> platform canonical flips sign (discharge = +)
#   * No temperature column -> ambient temperature is a platform
#     modeling assumption owned by configs/datasets.yaml
#     (source: CALCE archive naming "SP2_25C_*")
#
# Dynamic-step identification is RULE-BASED (mixed-sign current,
# peak |I| threshold, maximum point count) -- the step number 7
# is nowhere hard-coded; the rules hit Step 7 in all 6 files.
#
# Dynamic canonical schema (Step 19): the runner only ever sees
#   t, I(t), Vexp(t)   (+ ambient temperature from config)
# Protocol metadata lives in the DataFrame attrs / provenance:
#   protocol_id, profile_kind, source_file, source_soc_percent,
#   source_cycle, source_step -- there are NO DST-specific or
#   US06-specific current fields anywhere in this adapter.
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

NOMINAL_CAPACITY_AH = 2.0

PROTOCOLS: Tuple[str, ...] = ("DST", "FUDS", "US06")
SOC_LEVELS: Tuple[int, ...] = (50, 80)

# Filename pattern: '11_05_2015_SP20-2_DST_50SOC.xls'
_FILENAME_RE = re.compile(
    r"(?P<mo>\d+)_(?P<day>\d+)_(?P<year>\d{4})_"
    r"SP20-(?P<cell>\d+)_(?P<protocol>DST|FUDS|US06)_(?P<soc>\d+)SOC\.xls"
)

# Canonical window ids: DST50 / DST80 / FUDS50 / ... and their
# file-naming slugs (DST_50SOC).  rate_slug names output files.
PROTOCOL_SOC_SLUGS: Dict[str, str] = {
    f"{p}{s}": f"{p}_{s}SOC" for p in PROTOCOLS for s in SOC_LEVELS
}

# ------------------------------------------------------------------
# Dynamic-step identification rules (Step 18 / audit section 4)
# ------------------------------------------------------------------

MIN_DYNAMIC_POINTS = 500   # prep steps are <= ~720 rest pts; profile >> this
PEAK_CURRENT_ABS_A = 1.0   # profile peaks at 2C (4 A); CC prep at 1 A is
                           # single-sign, so a mixed-sign requirement is
                           # what actually separates the profile step
MIXED_SIGN_MIN_COUNT = 10  # need >=10 samples of EACH sign


def _cumulative_capacity(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    return np.concatenate(
        ([0.0],
         np.cumsum((current[1:] + current[:-1]) / 2.0 * np.diff(t)) / 3600.0)
    )


def _parse_filename(path: Path) -> dict:
    m = _FILENAME_RE.search(path.name)
    if m is None:
        raise ValueError(f"cannot parse CALCE 20R filename: {path.name}")
    return {
        "month": int(m.group("mo")),
        "day": int(m.group("day")),
        "year": int(m.group("year")),
        "cell": m.group("cell"),
        "protocol": m.group("protocol"),
        "soc_percent": int(m.group("soc")),
    }


def load_calce_20r_file(path: Path) -> pd.DataFrame:
    """
    Load one CALCE INR18650-20R Arbin .xls into a canonical-trace
    DataFrame.

    Columns produced:
        time_s     file-local test time (file starts at t=0)
        current_A  CANONICAL sign (discharge +, charge -)
        voltage_V
        cycle_index / step_index as recorded in this file
        date_time  original Arbin timestamp

    Arbin cumulative capacity columns are renamed with an explicit
    ``_arbin_cumulative`` suffix (CS2 trap T2) so no downstream code
    mistakes them for per-segment capacity.
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
    keep = (t.notna() & V.notna()).to_numpy()

    out = pd.DataFrame(
        {
            "time_s": t.to_numpy(dtype=float)[keep],
            "current_A": (
                # CALCE/Arbin charge=+ / discharge=- -> canonical flip
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

    # Time-axis hygiene (Step 20): sort, de-duplicate exact repeats,
    # re-zero.  Near-zero-dt event records (dt ~ 1e-4 s) are kept;
    # the strictly-increasing guarantee is enforced per window in
    # _canonical_window before the data leaves the adapter.
    out = out.sort_values("time_s").drop_duplicates(
        subset=["time_s"], keep="last"
    ).reset_index(drop=True)

    out["time_s"] = out["time_s"] - float(out["time_s"].iloc[0])

    return out


def _find_dynamic_step(df: pd.DataFrame) -> Tuple[int, int]:
    """
    Rule-based identification of the dynamic-profile step in one
    file's canonical trace.  Returns (cycle_index, step_index).

    Rules (no hard-coded step number anywhere):
      * group by (cycle, step)
      * candidate must have >= MIN_DYNAMIC_POINTS samples
      * candidate current must contain BOTH signs
        (>= MIXED_SIGN_MIN_COUNT samples of each)
      * candidate peak |I| >= PEAK_CURRENT_ABS_A
      * among candidates, take the one with the most samples
        (the profile is repeated to the cutoff -> longest step)
    """
    best: Optional[Tuple[int, int, int]] = None

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

        n = int(len(seg))
        if best is None or n > best[2]:
            best = (int(cyc), int(step), n)

    if best is None:
        raise RuntimeError(
            "no dynamic-profile step found (mixed-sign current, "
            f"peak |I| >= {PEAK_CURRENT_ABS_A} A, "
            f">= {MIN_DYNAMIC_POINTS} points)"
        )

    return best[0], best[1]


def _canonical_window(
    seg: pd.DataFrame, provenance: dict
) -> pd.DataFrame:
    """
    Build the canonical replay window for one dynamic segment:
    strictly increasing time (Step 20), times relative to the
    window start, canonical columns only.  Enriches ``provenance``
    in place with the measured window statistics.
    """
    seg = seg.sort_values("time_s").reset_index(drop=True)

    t = seg["time_s"].to_numpy(dtype=float)
    I = seg["current_A"].to_numpy(dtype=float)
    V = seg["voltage_V"].to_numpy(dtype=float)

    # strictly increasing time: drop duplicate / non-increasing stamps
    keep = np.concatenate(([True], np.diff(t) > 0))
    n_dropped = int((~keep).sum())
    t, I, V = t[keep], I[keep], V[keep]

    t_rel = t - t[0]

    out = pd.DataFrame(
        {
            "time_s": t_rel,
            "current_A": I,
            "voltage_V": V,
            "capacity_Ah": _cumulative_capacity(t_rel, I),
        }
    )

    assert np.all(np.diff(out["time_s"].to_numpy()) > 0), (
        "canonical window time must be strictly increasing"
    )

    provenance = dict(provenance)
    provenance["n_points_strictly_increasing"] = int(len(out))
    provenance["n_points_dropped_nonincreasing_time"] = n_dropped
    provenance["n_points"] = int(len(out))
    provenance["duration_s"] = float(t_rel[-1])
    provenance["voltage_start_V"] = float(V[0])
    provenance["voltage_end_V"] = float(V[-1])
    provenance["current_peak_discharge_A"] = float(I.max())
    provenance["current_peak_charge_A"] = float(-I.min())
    provenance["current_rms_A"] = float(
        np.sqrt(np.mean(I ** 2))
    )
    provenance["integrated_charge_Ah"] = float(out["capacity_Ah"].iloc[-1])

    provenance["time_axis_checks"] = {
        "sorted": True,
        "duplicates_removed_at_load": True,
        "strictly_increasing": True,
        "nan_current_or_voltage": 0,
    }

    out.attrs["provenance"] = provenance
    # initial SOC for the replay (Step 19 metadata; assumption
    # documented in the parameter audit + datasets.yaml)
    out.attrs["initial_soc"] = provenance["initial_soc"]
    return out


class Calce20RAdapter(BatteryDatasetAdapter):
    """
    Adapter for the CALCE INR18650-20R dynamic dataset (v0.3).

    Window ids ("rates" channel -- the replay runner only knows
    ids -> windows, it does not know what DST is):
        DST50, DST80, FUDS50, FUDS80, US0650, US0680

    Accepted window arguments: canonical id ("DST50"), file slug
    ("DST_50SOC"), or bare protocol ("DST" -> every SOC level of
    that protocol, usable wherever a window list is expected).
    """

    # the dynamic dataset has no CC-rate semantics; resolve_rate is
    # not applicable, rate_info is overridden below
    SOURCE_TO_CANONICAL: Dict[str, float] = {}

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir

        extra = config.extra or {}

        # Ambient temperature: OWNED BY THE CONFIG, never a Python
        # default (v0.2 convention B).
        amb = extra.get("ambient_temperature")
        if isinstance(amb, dict) and "value_C" in amb:
            self._ambient_C = float(amb["value_C"])
            self._temperature_source = str(amb.get("source", "assumed"))
            self._temperature_confidence = str(
                amb.get("confidence", "unspecified")
            )
            self._temperature_note = str(amb.get("note", ""))
        else:
            raise ValueError(
                f"dataset '{config.dataset_id}': no ambient temperature "
                f"assumption in configs/datasets.yaml (add an "
                f"'ambient_temperature: {{value_C, source, confidence}}' "
                f"block).  The adapter does not invent assumptions."
            )

        self._parameter_match = dict(extra.get("parameter_match", {}))

        dyn = extra.get("dynamic_protocol", {})
        self._profile_kind = str(dyn.get("profile_kind", "dynamic"))
        self._initial_soc_source = str(
            dyn.get(
                "initial_soc_source",
                "calce_filename_SOC_label",
            )
        )
        self._initial_soc_confidence = str(
            dyn.get("initial_soc_confidence", "low")
        )

        self._file_index: Dict[Tuple[str, int], Path] = {}
        for path in sorted(self._raw_dir.glob("*.xls")):
            meta = _parse_filename(path)
            if meta["cell"] != "2":
                continue  # dynamic replay uses the SP20-2 test cell only
            key = (meta["protocol"], meta["soc_percent"])
            if key in self._file_index:
                raise ValueError(
                    f"duplicate dynamic file for {key}: "
                    f"{path.name} vs {self._file_index[key].name}"
                )
            self._file_index[key] = path

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
            "ambient_temperature_C": self._ambient_C,
            "temperature_source": self._temperature_source,
            "temperature_confidence": self._temperature_confidence,
            "initial_soc_source": self._initial_soc_source,
            "initial_soc_confidence": self._initial_soc_confidence,
            "parameter_match": self._parameter_match,
        }

    def list_cells(self):
        return list(self.config.cells)

    def list_protocols(self) -> List[str]:
        """Protocols with at least one experimental window."""
        have = {p for (p, _s) in self._file_index}
        return [p for p in PROTOCOLS if p in have]

    def list_rates(self):
        """Canonical window ids (protocol+SOC) with files present."""
        out = []
        for pid in PROTOCOLS:
            for soc in SOC_LEVELS:
                if (pid, soc) in self._file_index:
                    out.append(f"{pid}{soc}")
        return out

    def expand_protocol(self, protocol: str) -> List[str]:
        """
        'DST' -> ['DST50', 'DST80']; 'DST50' -> ['DST50'].
        Used by the CLI (--protocol) BEFORE the runner is called.
        """
        p = str(protocol).upper()
        if p in PROTOCOLS:
            windows = [
                f"{p}{s}" for s in SOC_LEVELS
                if (p, s) in self._file_index
            ]
            if not windows:
                raise KeyError(
                    f"no experimental windows for protocol '{protocol}'"
                )
            return windows
        # otherwise treat as a window id (validation in rate_info)
        return [p]

    # ------------------------------------------------------------------
    # Canonical window resolution
    # ------------------------------------------------------------------
    def _resolve_window(self, window: str) -> Tuple[str, int]:
        """'DST50' / 'DST_50SOC' -> ('DST', 50)."""
        w = str(window).strip()
        slug = w.replace("-", "_").upper()

        # file-slug form, e.g. 'DST_50SOC'
        for wid, file_slug in PROTOCOL_SOC_SLUGS.items():
            if slug == file_slug.upper():
                pid = "".join(c for c in wid if c.isalpha())
                soc = int("".join(c for c in wid if c.isdigit()))
                if (pid, soc) not in self._file_index:
                    raise KeyError(
                        f"no experimental file for window '{window}'"
                    )
                return pid, soc

        # canonical-id form, e.g. 'US0650' (protocol prefix may
        # itself contain digits, so match known protocol names)
        for pid in PROTOCOLS:
            if w.upper().startswith(pid):
                tail = w.upper()[len(pid):]
                if tail.isdigit():
                    soc = int(tail)
                    if (pid, soc) not in self._file_index:
                        raise KeyError(
                            f"no experimental file for window '{window}'"
                        )
                    return pid, soc

        raise KeyError(
            f"unknown window id '{window}'; "
            f"available: {self.list_rates()}"
        )

    def rate_info(self, rate) -> Dict[str, object]:
        """
        Canonical window descriptor.  The dynamic dataset has no
        single C-rate, so ``c_rate`` is NaN by construction.
        """
        pid, soc = self._resolve_window(rate)
        return {
            "c_rate": float("nan"),
            "rate_label": f"{pid} @ {soc}% SOC",
            "rate_slug": PROTOCOL_SOC_SLUGS[f"{pid}{soc}"],
            "source_rate": f"{soc}SOC",
            "legacy_rate": pid,
            "protocol_id": pid,
            "soc_percent": soc,
        }

    def rate_for_cell(self, cell: str) -> str:
        return ""  # dynamic windows are not per-cell

    def canonical_rate_slug_for_cell(self, cell: str) -> str:
        return ""

    # ------------------------------------------------------------------
    # File access
    # ------------------------------------------------------------------
    def protocol_files(self, cell: str) -> Dict[Tuple[str, int], Path]:
        return dict(self._file_index)

    def load_raw(self, cell) -> pd.DataFrame:
        """All dynamic windows concatenated (audit convenience)."""
        frames = []
        for (pid, soc), path in sorted(self._file_index.items()):
            df = load_calce_20r_file(path)
            df["protocol_id"] = pid
            df["soc_percent"] = soc
            df["source_file"] = path.name
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------------------
    # Dynamic window extraction (canonical, rule-based)
    # ------------------------------------------------------------------
    def _load_window(self, window: str) -> Tuple[pd.DataFrame, dict]:
        pid, soc = self._resolve_window(window)
        path = self._file_index[(pid, soc)]

        df = load_calce_20r_file(path)

        cyc, step = _find_dynamic_step(df)
        seg = df[
            (df["cycle_index"] == cyc) & (df["step_index"] == step)
        ].copy()

        provenance = {
            "protocol_id": pid,
            "profile_kind": self._profile_kind,
            "source_file": path.name,
            "source_soc_percent": soc,
            "source_cycle": int(cyc),
            "source_step": int(step),
            "initial_soc": float(soc) / 100.0,
            "initial_soc_source": self._initial_soc_source,
            "initial_soc_confidence": self._initial_soc_confidence,
            # v0.3 freeze item: explicit initial-state semantics.
            # The replay starts at the dynamic segment with a
            # NOMINAL SOC from the CALCE protocol target; the
            # charge/rest/trim history before it is NOT replayed,
            # and under a surrogate parameterization the SOC ->
            # electrode-stoichiometry mapping is NOT the 20R's own.
            # Do NOT read RMSE differences between SOC levels as
            # model SOC-generalization quality.
            "initial_state": {
                "type": "nominal_soc",
                "value": float(soc) / 100.0,
                "source": "CALCE protocol target (filename SOC label)",
                "history_replayed": False,
                "is_exact_electrochemical_state": False,
            },
            "identification": (
                "rule-based: mixed-sign current, peak |I| >= "
                f"{PEAK_CURRENT_ABS_A} A, >= {MIN_DYNAMIC_POINTS} "
                "points, largest step"
            ),
            "parameter_set": self.config.parameter_set,
            "parameter_match": self._parameter_match,
        }

        window_df = _canonical_window(seg, provenance)

        # return the ENRICHED provenance (window statistics added
        # inside _canonical_window via attrs)
        return window_df, dict(window_df.attrs["provenance"])

    def load_profile(self, cell, protocol) -> pd.DataFrame:
        """
        One dynamic window as a canonical DataFrame
        (time_s, current_A [discharge +], voltage_V, capacity_Ah).
        Times are relative to the window start.
        """
        df, _ = self._load_window(str(protocol))
        return df

    def profile_info(self, cell: str, protocol: str) -> dict:
        """Per-window metadata incl. full provenance."""
        df, provenance = self._load_window(str(protocol))
        info = self.rate_info(protocol)
        return {
            "dataset": self.config.name,
            "cell_id": f"SP20-{cell}" if str(cell).isdigit() else str(cell),
            "protocol_id": str(info["protocol_id"]),
            "soc_percent": int(info["soc_percent"]),
            "profile_kind": self._profile_kind,
            "rate_slug": str(info["rate_slug"]),
            "n_points": int(len(df)),
            "duration_s": float(df["time_s"].iloc[-1]),
            "voltage_start_V": float(df["voltage_V"].iloc[0]),
            "voltage_end_V": float(df["voltage_V"].iloc[-1]),
            "integrated_charge_Ah": float(df["capacity_Ah"].iloc[-1]),
            "ambient_temperature_C": self.get_ambient_temperature(cell),
            "temperature_source": self._temperature_source,
            "initial_soc": float(df.attrs["initial_soc"]),
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Baseline-replay input (same schema as chen2020 / calce_cs2)
    # ------------------------------------------------------------------
    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """
        Canonical window df for the baseline runner.  Generated on
        the fly from the raw .xls; ambient temperature is the
        platform modeling assumption owned by the config.
        """
        df, provenance = self._load_window(str(rate))
        df = df.copy()
        df["temperature_ambient_C"] = self._ambient_C
        df.attrs["provenance"] = provenance
        df.attrs["initial_soc"] = provenance["initial_soc"]
        return df

    # ------------------------------------------------------------------
    # Initial / environmental state
    # ------------------------------------------------------------------
    def get_initial_state(self, cell) -> float:
        """
        Measured cell voltage at the start of the (first) dynamic
        window -- informational; the replay uses initial_soc.
        """
        df, _ = self._load_window(self.list_rates()[0])
        return float(df["voltage_V"].iloc[0])

    def get_ambient_temperature(self, cell) -> float:
        """Platform modeling assumption (config-owned, v0.2 rule B)."""
        return self._ambient_C


# Registry compatibility: battery_sim.registry resolves the adapter
# id 'calce_20r' -> class name 'Calce20rAdapter' via PascalCase
# joining; expose the same class under that name as well so the
# human-facing name above stays Calce20RAdapter.
Calce20rAdapter = Calce20RAdapter
