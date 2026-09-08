# ============================================================
# Battery Dataset Simulation Platform v0.1
# Chen2020 LG M50 dataset adapter
#
# Data-parsing logic is reused from the already-validated
# reference implementation:
#   scripts/adapters/chen2020.py
#   scripts/runners/command_reproduction.py
#
# Preserved scientific definitions (do not change):
#   * Maccor CSV header on row 14            -> pd.read_csv(skiprows=13)
#   * Current sign:  D -> + (discharge)
#                    C -> - (charge)
#                    R -> 0 (rest)
#   * Validation rates keyed by Cycle C:
#        Cycle C=2 -> C10  0.5 A (discharge step 7)
#        Cycle C=3 -> C2   2.5 A (discharge step 12)
#        Cycle C=4 -> 1C   5.0 A (discharge step 17)
#        Cycle C=5 -> 1p5C 7.5 A (discharge step 22)
#   * Initial voltage: Cycle 1 / Step 1 / rest, median of last 5 min
#   * Ambient temperature: chamber median over pre-discharge rests
#     at steps {6, 11, 16, 21}
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.paths import ROOT
from battery_sim.schemas import DatasetConfig

# ------------------------------------------------------------------
# Nominal / rate map (identical to scripts/adapters/chen2020.py)
# ------------------------------------------------------------------

NOMINAL_CAPACITY_AH = 5.0

# Cycle C -> (rate name, nominal C-rate, nominal current A)
RATE_MAP = {
    2: ("C10", 0.1, 0.5),
    3: ("C2", 0.5, 2.5),
    4: ("1C", 1.0, 5.0),
    5: ("1p5C", 1.5, 7.5),
}

# Rate name -> discharge step index within that cycle
RATE_STEP = {
    "C10": 7,
    "C2": 12,
    "1C": 17,
    "1p5C": 22,
}

# Solution cycle index (0-based): conditioning=0, then C10..1p5C
RATE_CYCLE_INDEX = {
    "C10": 1,
    "C2": 2,
    "1C": 3,
    "1p5C": 4,
}

DEFAULT_RATES: Tuple[str, ...] = ("C10", "C2", "1C", "1p5C")


def load_raw_maccor(path: Path) -> pd.DataFrame:
    """
    Load a Chen2020 Maccor CSV (real header is line 14).
    """
    df = pd.read_csv(
        path,
        skiprows=13,
        low_memory=False,
    )

    required = [
        "Cycle C",
        "Step",
        "Test Time [s]",
        "Step Time [s]",
        "Capacity [Ah]",
        "Energy [Wh]",
        "Current [A]",
        "Voltage [V]",
        "Md",
        "Temperature Cell [degC]",
        "Temperature Chamber [degC]",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            f"{path.name}: missing columns: {missing}"
        )

    # --------------------------------------------------------------
    # Numeric coercion + clean time axis (reuses run_reproduction.py)
    # --------------------------------------------------------------
    numeric_cols = [
        "Cycle C",
        "Step",
        "Test Time [s]",
        "Step Time [s]",
        "Capacity [Ah]",
        "Current [A]",
        "Voltage [V]",
        "Temperature Cell [degC]",
        "Temperature Chamber [degC]",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "Test Time [s]",
            "Voltage [V]",
        ]
    ).copy()

    df = df.sort_values("Test Time [s]")

    # Rare Maccor sub-record can share a timestamp -> keep last.
    df = df.drop_duplicates(
        subset=["Test Time [s]"],
        keep="last",
    ).reset_index(drop=True)

    t0 = float(df["Test Time [s]"].iloc[0])

    df["time_s"] = df["Test Time [s]"] - t0

    # --------------------------------------------------------------
    # Maccor stores current magnitude. Convert to PyBaMM sign.
    # --------------------------------------------------------------
    mode = df["Md"].astype(str).str.strip()

    current_mag = (
        pd.to_numeric(
            df["Current [A]"],
            errors="coerce",
        )
        .fillna(0.0)
        .abs()
    )

    signed_current = np.zeros(len(df), dtype=float)

    signed_current[mode.eq("D").to_numpy()] = current_mag[
        mode.eq("D")
    ].to_numpy()

    signed_current[mode.eq("C").to_numpy()] = -current_mag[
        mode.eq("C")
    ].to_numpy()

    df["current_signed_A"] = signed_current

    return df


class Chen2020Adapter(BatteryDatasetAdapter):
    """
    Adapter for the Chen2020 LG M50 dataset (3 cells, 4 rates).
    """

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir
        self._processed_dir = (
            ROOT / config.processed_dir
            if config.processed_dir
            else None
        )

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
            # v0.2 schema: chemistry-parameter compatibility.
            # Chen2020 was parameterised from this exact cell.
            "parameter_match": {
                "level": "exact",
                "grade": "A",
                "parameter_set": cfg.parameter_set,
                "experimental_cell": (
                    "LG M50 (NMC532/graphite-SiOx, 5 Ah, 21700)"
                ),
                "fitted_to_dataset": True,
                "notes": (
                    "Chen2020 parameter set was fitted to this exact "
                    "cell geometry and chemistry."
                ),
            },
        }

    def list_cells(self):
        return list(self.config.cells)

    def list_rates(self):
        rates = list(self.config.rates)
        return rates if rates else list(DEFAULT_RATES)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def raw_path(self, cell: str) -> Path:
        path = (
            self._raw_dir
            / self.config.raw_file_template.format(cell=cell)
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Chen2020 raw file not found: {path}"
            )

        return path

    def processed_path(self, cell: str, rate: str) -> Optional[Path]:
        if self._processed_dir is None:
            return None

        path = (
            self._processed_dir
            / f"LGM50_cell{cell}_{rate}.csv"
        )

        return path if path.exists() else None

    # ------------------------------------------------------------------
    # Raw data
    # ------------------------------------------------------------------
    def load_raw(self, cell) -> pd.DataFrame:
        return load_raw_maccor(self.raw_path(cell))

    # ------------------------------------------------------------------
    # Discharge extraction
    # ------------------------------------------------------------------
    def load_discharge(self, cell, rate) -> pd.DataFrame:
        """
        One formal validation discharge as a clean DataFrame.

        Row selection is identical to command_reproduction.py's
        experimental_discharge(): Cycle C and exact discharge step
        from RATE_MAP / RATE_STEP.
        """
        if rate not in RATE_STEP:
            raise ValueError(
                f"Unknown Chen2020 rate '{rate}'. "
                f"Valid: {list(RATE_STEP.keys())}"
            )

        df = self.load_raw(cell)

        cycle_c = next(
            c for c, (r, _, _) in RATE_MAP.items() if r == rate
        )

        seg = df[
            (df["Cycle C"] == cycle_c)
            & (df["Step"] == RATE_STEP[rate])
            & (df["Md"] == "D")
        ].copy()

        if seg.empty:
            raise RuntimeError(
                f"cell{cell} {rate}: empty discharge segment "
                f"(Cycle C={cycle_c}, step={RATE_STEP[rate]})"
            )

        seg = seg.sort_values("Test Time [s]")

        q = pd.to_numeric(
            seg["Capacity [Ah]"],
            errors="coerce",
        ).to_numpy(dtype=float)

        q0 = q[0]
        q = q - q0

        V = pd.to_numeric(
            seg["Voltage [V]"],
            errors="coerce",
        ).to_numpy(dtype=float)

        t = pd.to_numeric(
            seg["Step Time [s]"],
            errors="coerce",
        ).to_numpy(dtype=float)

        t = t - t[0]

        return pd.DataFrame(
            {
                "time_s": t,
                "current_A": (
                    pd.to_numeric(
                        seg["Current [A]"],
                        errors="coerce",
                    ).to_numpy(dtype=float)
                ),
                "voltage_V": V,
                "capacity_Ah": q,
                "cell_temperature_C": (
                    pd.to_numeric(
                        seg["Temperature Cell [degC]"],
                        errors="coerce",
                    ).to_numpy(dtype=float)
                ),
            }
        )

    def discharge_info(self, cell: str, rate: str) -> dict:
        """
        Lightweight per-discharge metadata from the raw record.
        Mirrors the JSON produced by scripts/adapters/chen2020.py.
        """
        df = self.load_discharge(cell, rate)

        raw = self.load_raw(cell)

        cycle_c = next(
            c for c, (r, _, _) in RATE_MAP.items() if r == rate
        )

        ambient = float(
            raw[
                (raw["Cycle C"] == cycle_c)
                & (raw["Md"] == "D")
            ]["Temperature Chamber [degC]"]
            .median()
        )

        return {
            "dataset": self.config.name,
            "cell_id": f"LGM50_cell{cell}",
            "rate": rate,
            "n_points": int(len(df)),
            "duration_s": float(df["time_s"].iloc[-1]),
            "voltage_start_V": float(df["voltage_V"].iloc[0]),
            "voltage_end_V": float(df["voltage_V"].iloc[-1]),
            "capacity_end_Ah": float(df["capacity_Ah"].iloc[-1]),
            "ambient_temperature_C": float(ambient),
            "median_current_A": float(df["current_A"].median()),
        }

    # ------------------------------------------------------------------
    # Initial / environmental state (identical logic to command_repro.)
    # ------------------------------------------------------------------
    def get_initial_state(self, cell) -> float:
        """
        Open-circuit voltage [V] from the tail of the initial rest
        (Cycle 1 / Step 1 / rest, last 5 minutes median).
        """
        df = self.load_raw(cell)

        rest = df[
            (df["Cycle C"] == 1)
            & (df["Step"] == 1)
            & (df["Md"] == "R")
        ]

        if rest.empty:
            raise RuntimeError(
                f"cell{cell}: initial rest (Cycle 1/Step 1) not found"
            )

        tail = rest[
            rest["Step Time [s]"]
            >= rest["Step Time [s]"].max() - 300
        ]

        return float(tail["Voltage [V]"].median())

    def get_ambient_temperature(self, cell) -> float:
        """
        Chamber temperature [degC] median over the four 2-h
        pre-discharge rests (steps {6, 11, 16, 21}).
        """
        df = self.load_raw(cell)

        steps = [6, 11, 16, 21]

        x = df[
            (df["Step"].isin(steps))
            & (df["Md"] == "R")
        ]["Temperature Chamber [degC]"]

        return float(x.median())

    # ------------------------------------------------------------------
    # Processed data (baseline replay inputs)
    # ------------------------------------------------------------------
    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """
        Load a processed single-discharge CSV (from the reference
        data-preparation step) used by the ``baseline`` mode.
        """
        path = self.processed_path(cell, rate)

        if path is None:
            raise FileNotFoundError(
                f"cell{cell} {rate}: processed file missing under "
                f"{self._processed_dir}"
            )

        return pd.read_csv(path)
