# ============================================================
# Battery Dataset Simulation Platform -- v0.5 half-cell pilot (H0)
# Birmingham NCM920305 || Li dataset adapter (H6)
#
# Translates the Birmingham raw RateCapability CSVs into the
# platform canonical schema.  Half-cell is a FIRST-CLASS cell
# configuration declared in configs/datasets.yaml -- the adapter
# never guesses "half cell" from chemistry or file names.
#
# Audited raw-file facts (docs/halfcell_birmingham_audit.md):
#   * single header row, units embedded in column names
#     Time [s] / Current [mA] / Voltage [V] / Capacity [mAh] /
#     Temperature [K]
#   * sign convention: DISCHARGE = NEGATIVE [mA]
#     -> flipped to platform canonical (discharge = +, charge = -)
#   * every RateCapability file = 120 s rest at ~4.19-4.20 V
#     followed by ONE constant-current discharge that stops exactly
#     at the 2.5 V lower cutoff (no CV tail)
#   * chamber temperature constant 298.15 K
#   * time axis: absolute cumulative seconds across the file
#
# Slice (window) = [pre-discharge rest start .. discharge end].
# The pre-discharge rest OCV (V0) is measured from the data and
# mapped to an initial Li fraction x0 by inverting the author
# positive-OCP curve (ocp_discharge.csv, same data the PyBaMM OCP
# interpolant reads).  x0 lives in df.attrs; the model layer turns
# it into an initial concentration (x0 * c_max).  This mirrors the
# authors' own figure_5 pipeline and is NOT a fitted parameter.
#
# This module imports pandas/numpy only -- NEVER pybamm.
# ============================================================

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.paths import ROOT
from battery_sim.schemas import DatasetConfig

# ------------------------------------------------------------------
# Rate tokens -> canonical c_rate
#
# Raw file stems: RateCapability_Cover10_2mAhcm_2_NCM920305.csv ...
#   Cover10 = C/10, Cover5 = C/5, Cover2 = C/2, 1C, 2C
# ("Cover" = the JPS paper's C-over labelling; NOT to be confused
#  with the platform legacy slug C2 which means 0.5C.)
# ------------------------------------------------------------------
SOURCE_TO_CANONICAL: Dict[str, float] = {
    "Cover10": 0.1,
    "Cover5": 0.2,
    "Cover2": 0.5,
    # "1C" / "2C" resolve through the canonical registry natively
}

# Segment-identification tolerances (mirror the platform style)
ACTIVE_CURRENT_FRACTION = 0.02   # |I| >= 2 % of peak -> "on current"
# The rate files record only ONE in-file rest sample before the CC
# discharge starts (t=0, I=0; the ~120 s rest itself is not logged
# point-by-point -- see docs/halfcell_birmingham_audit.md).  At
# least one pre-discharge rest point is required so a discharge
# that starts at the very first row is still rejected.
MIN_REST_POINTS = 1
MIN_DISCHARGE_POINTS = 10
V_DROP_MIN_V = 1.0               # discharge must drop >= 1 V
V_CUTOFF_TOL_V = 0.10            # window end within 0.1 V of cutoff
TEMP_EXPECTED_K = 298.15
TEMP_TOL_K = 1.0


def _cumulative_capacity(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    dt = np.diff(t)
    cap = np.concatenate(
        ([0.0], np.cumsum(dt * (current[1:] + current[:-1]) / 2.0) / 3600.0)
    )
    return cap


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class BirminghamNcm920305Adapter(BatteryDatasetAdapter):
    """
    Adapter for the Birmingham NCM920305 || Li half-cell dataset
    (single electrode loading: 2 mAh/cm2).

    ``cell`` accepts the config cell id ("2mAhcm2").  ``rate``
    accepts the source file tokens ("Cover10" .. "2C") or any
    canonical alias that resolves to the same c_rate
    (0.1/0.2/0.5/1.0/2.0).
    """

    SOURCE_TO_CANONICAL = SOURCE_TO_CANONICAL

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir
        if not self._raw_dir.is_dir():
            raise FileNotFoundError(
                f"Birmingham raw dir not found: {self._raw_dir}"
            )

        extra = config.extra or {}

        self._cell_configuration = str(extra.get("cell_configuration", ""))
        if self._cell_configuration != "half_cell":
            raise ValueError(
                f"adapter {config.dataset_id}: cell_configuration must "
                f"be 'half_cell' (configs/datasets.yaml)"
            )
        self._working_electrode = str(extra.get("working_electrode", ""))
        if self._working_electrode != "positive":
            raise ValueError(
                f"adapter {config.dataset_id}: working_electrode must be "
                f"'positive' (configs/datasets.yaml)"
            )
        self._counter_electrode = str(extra.get("counter_electrode", ""))
        if self._counter_electrode != "lithium_metal":
            raise ValueError(
                f"adapter {config.dataset_id}: counter_electrode must be "
                f"'lithium_metal' (configs/datasets.yaml)"
            )

        # inverse-OCP file used to map the measured rest OCV -> x0
        ocp_rel = str(extra.get("initialisation_ocp_file_rel", ""))
        if not ocp_rel:
            raise ValueError(
                f"adapter {config.dataset_id}: missing "
                f"initialisation_ocp_file_rel (configs/datasets.yaml)"
            )
        self._ocp_file = ROOT / ocp_rel
        if not self._ocp_file.is_file():
            raise FileNotFoundError(f"OCP file not found: {self._ocp_file}")

        # ambient temperature block (value owned by the config)
        amb = extra.get("ambient_temperature")
        if isinstance(amb, dict) and "value_C" in amb:
            self._ambient_C = float(amb["value_C"])
            self._temperature_source = str(amb.get("source", ""))
            self._temperature_confidence = str(amb.get("confidence", ""))
            self._temperature_note = str(amb.get("note", ""))
        else:
            raise ValueError(
                f"dataset '{config.dataset_id}': no ambient_temperature "
                f"block with value_C in configs/datasets.yaml"
            )

        self._parameter_match = dict(extra.get("parameter_match", {}))
        self._param_source = dict(extra.get("parameter_source", {}) or {})

        self._ocp_curve = None  # lazy (Stoichiometry, Voltage)

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
            "cell_configuration": self._cell_configuration,
            "working_electrode": self._working_electrode,
            "counter_electrode": self._counter_electrode,
            "parameter_set": cfg.parameter_set,
            "nominal_capacity_Ah": cfg.nominal_capacity_Ah,
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
        return list(self.config.rates)

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------
    def _rate_token(self, rate) -> str:
        """File-stem token for a rate id (source_rate after resolve)."""
        info = self.rate_info(rate)
        token = str(info["source_rate"])
        known = {"Cover10", "Cover5", "Cover2", "1C", "2C"}
        if token not in known:
            raise ValueError(
                f"rate '{rate}' resolves to source token '{token}', "
                f"not one of {sorted(known)}"
            )
        return token

    def _raw_path(self, rate) -> Path:
        token = self._rate_token(rate)
        name = self.config.raw_file_template.format(token=token)
        path = self._raw_dir / name
        if not path.is_file():
            raise FileNotFoundError(
                f"Birmingham raw file not found for rate token "
                f"'{token}': {path}"
            )
        return path

    # ------------------------------------------------------------------
    # Raw parsing (canonical columns, sign flipped)
    # ------------------------------------------------------------------
    def _load_raw_file(self, path: Path) -> pd.DataFrame:
        """
        One RateCapability CSV as a canonical-trace DataFrame:
          time_s / current_A (discharge +) / voltage_V /
          capacity_mAh_raw / temperature_K
        Time stays in FILE-absolute seconds (relative to t=0 of file).
        """
        df = pd.read_csv(path)
        col = {c: c for c in df.columns}
        need = ["Time [s]", "Current [mA]", "Voltage [V]"]
        missing = [n for n in need if n not in col]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")

        t = pd.to_numeric(df["Time [s]"], errors="coerce").to_numpy(float)
        I_mA = pd.to_numeric(df["Current [mA]"], errors="coerce").to_numpy(float)
        V = pd.to_numeric(df["Voltage [V]"], errors="coerce").to_numpy(float)

        keep = np.isfinite(t) & np.isfinite(I_mA) & np.isfinite(V)
        t, I_mA, V = t[keep], I_mA[keep], V[keep]

        # canonical sign: discharge = +  (raw discharge is NEGATIVE mA)
        I = -I_mA / 1000.0

        # author style: drop duplicate timestamps keeping the first
        _, uniq = np.unique(t, return_index=True)
        t, I, V = t[uniq], I[uniq], V[uniq]
        order = np.argsort(t, kind="stable")
        t, I, V = t[order], I[order], V[order]

        out = pd.DataFrame(
            {
                "time_s": t,
                "current_A": I,
                "voltage_V": V,
            }
        )

        cap = None
        if "Capacity [mAh]" in col:
            cap = pd.to_numeric(
                df["Capacity [mAh]"], errors="coerce"
            ).to_numpy(float)[keep][uniq][order]
        out["capacity_mAh_raw"] = cap if cap is not None else np.nan

        temp = np.full(len(out), np.nan)
        if "Temperature [K]" in col:
            temp = pd.to_numeric(
                df["Temperature [K]"], errors="coerce"
            ).to_numpy(float)[keep][uniq][order]
        out["temperature_K"] = temp

        return out.reset_index(drop=True)

    def _find_window(self, raw: pd.DataFrame) -> Tuple[int, int]:
        """
        Indices [start, end] (inclusive) of the replay window:
        the contiguous rest immediately before the (single, longest)
        constant-current discharge run, through the discharge end.
        """
        I = raw["current_A"].to_numpy(float)
        peak = float(np.abs(I).max())
        if not np.isfinite(peak) or peak <= 0:
            raise ValueError("no non-zero current in raw file")

        active = np.abs(I) >= ACTIVE_CURRENT_FRACTION * peak

        # longest contiguous "active" run = the CC discharge
        best_run: List[int] = []
        cur: List[int] = []
        for i, a in enumerate(active):
            if a:
                cur.append(i)
            else:
                if len(cur) > len(best_run):
                    best_run = cur
                cur = []
        if len(cur) > len(best_run):
            best_run = cur
        if len(best_run) < MIN_DISCHARGE_POINTS:
            raise ValueError(
                f"no CC discharge run found (peak current {peak:.3e} A)"
            )

        d_start = int(best_run[0])

        # The cycler logs a current-decay artefact row as the channel
        # shuts off (|I| drops to ~95 % and V rebounds through the
        # cutoff), so the discharge end is taken as the row of the
        # MINIMUM voltage inside the run (= the lower-cutoff row),
        # not the last "active" row.
        V_run = raw["voltage_V"].to_numpy(float)[d_start : best_run[-1] + 1]
        d_end = d_start + int(np.argmin(V_run))

        # pre-discharge rest: contiguous inactive run ending at d_start
        rest_start = d_start
        while rest_start - 1 >= 0 and not active[rest_start - 1]:
            rest_start -= 1
        if d_start - rest_start < MIN_REST_POINTS:
            raise ValueError(
                f"pre-discharge rest too short "
                f"({d_start - rest_start} points)"
            )

        return rest_start, d_end

    # ------------------------------------------------------------------
    # OCV -> initial stoichiometry (pure data inversion)
    # ------------------------------------------------------------------
    def _load_ocp_curve(self):
        if self._ocp_curve is not None:
            return self._ocp_curve
        ocp = pd.read_csv(self._ocp_file)
        if "Stoichiometry" not in ocp.columns or "Voltage [V]" not in ocp.columns:
            raise ValueError(
                f"OCP file {self._ocp_file.name} must have columns "
                f"'Stoichiometry' and 'Voltage [V]'"
            )
        sto = ocp["Stoichiometry"].to_numpy(float)
        vv = ocp["Voltage [V]"].to_numpy(float)
        order = np.argsort(vv, kind="stable")
        self._ocp_curve = (sto[order], vv[order])
        return self._ocp_curve

    def inverse_ocp(self, voltage_V: float) -> float:
        """
        Stoichiometry x0 such that OCP(x0) = voltage_V.

        The OCP is the author's own ocp_discharge.csv curve, the
        same table PyBaMM's linear Interpolant reads.  PyBaMM's
        linear interpolant EXTRAPOLATES linearly beyond the
        tabulated voltage range, and the measured pre-discharge
        rest OCV (~4.1935 V) sits slightly ABOVE the tabulated top
        (4.18595 V): the authors' saved simulation starts at
        exactly 4.1935 V (H7 probe), so the inversion here mirrors
        that behaviour -- piecewise-linear inversion with linear
        extrapolation at both ends (never np.interp clipping, which
        would pin x0 to the table edge and under-state the charge).
        """
        sto, vv = self._load_ocp_curve()  # sorted ascending in V
        vmin, vmax = float(vv[0]), float(vv[-1])
        EXT_TOL_V = 0.10  # allow up to 0.1 V of linear extrapolation
        if voltage_V < vmin - EXT_TOL_V or voltage_V > vmax + EXT_TOL_V:
            raise ValueError(
                f"rest OCV {voltage_V:.4f} V more than {EXT_TOL_V} V "
                f"outside OCP data range [{vmin:.4f}, {vmax:.4f}] V"
            )
        if voltage_V < vmin:
            s = (sto[1] - sto[0]) / (vv[1] - vv[0])
            return float(sto[0] + s * (voltage_V - vv[0]))
        if voltage_V > vmax:
            s = (sto[-1] - sto[-2]) / (vv[-1] - vv[-2])
            return float(sto[-1] + s * (voltage_V - vv[-1]))
        return float(np.interp(voltage_V, vv, sto))

    # ------------------------------------------------------------------
    # Window extraction (canonical discharge interface)
    # ------------------------------------------------------------------
    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """
        Canonical replay df for the baseline runner:
          time_s (relative to rest start) / current_A [discharge +] /
          voltage_V / capacity_Ah / temperature_ambient_C
        plus attrs['provenance'] and attrs['initialisation'].
        """
        cell = str(cell)
        if cell not in [str(c) for c in self.config.cells]:
            raise ValueError(
                f"unknown cell '{cell}' for {self.config.dataset_id}; "
                f"expected one of {self.config.cells}"
            )

        info = self.rate_info(rate)
        c_rate = float(info["c_rate"])
        token = self._rate_token(rate)
        path = self._raw_path(rate)

        raw = self._load_raw_file(path)
        r0, r1 = self._find_window(raw)
        win = raw.iloc[r0 : r1 + 1].copy().reset_index(drop=True)

        t = win["time_s"].to_numpy(float)
        t_rel = t - float(t[0])
        I = win["current_A"].to_numpy(float)
        V = win["voltage_V"].to_numpy(float)

        # discharge run (rest removed) for median / direction checks
        active_mask = np.abs(I) >= ACTIVE_CURRENT_FRACTION * float(np.abs(I).max())
        I_dis = I[active_mask]
        V_dis = V[active_mask]

        if len(I_dis) == 0 or float(np.median(I_dis)) <= 0:
            raise ValueError(
                f"{path.name}: no positive (discharge) current run"
            )
        if float(V_dis[-1]) > float(V_dis[0]) - V_DROP_MIN_V:
            raise ValueError(
                f"{path.name}: discharge voltage does not drop >= "
                f"{V_DROP_MIN_V} V"
            )

        lower_cut = (
            self.config.lower_voltage_cutoff_V
            if self.config.lower_voltage_cutoff_V is not None
            else 2.5
        )
        if abs(float(V_dis[-1]) - lower_cut) > V_CUTOFF_TOL_V:
            raise ValueError(
                f"{path.name}: discharge does not end at the "
                f"{lower_cut} V cutoff (ends at {V_dis[-1]:.4f} V)"
            )

        # rest OCV = median of the LAST 60 s of the pre-discharge rest
        rest_mask = ~active_mask
        t_rest = t[rest_mask]
        if len(t_rest) == 0:
            raise ValueError(f"{path.name}: no rest segment found")
        t_rest_tail = t_rest >= float(t_rest[-1]) - 60.0
        V_rest_tail = V[rest_mask][t_rest_tail]
        v0 = float(np.median(V_rest_tail))

        x0 = self.inverse_ocp(v0)

        cap_Ah = _cumulative_capacity(t_rel, I)

        out = pd.DataFrame(
            {
                "time_s": t_rel,
                "current_A": I,
                "voltage_V": V,
                "capacity_Ah": cap_Ah,
                "temperature_ambient_C": float(self._ambient_C),
            }
        )

        # measured chamber temperature check (informational)
        temp_k = win["temperature_K"].to_numpy(float)
        temp_k = temp_k[np.isfinite(temp_k)]
        temp_ok = bool(
            len(temp_k) == 0
            or abs(float(np.median(temp_k)) - TEMP_EXPECTED_K) <= TEMP_TOL_K
        )

        provenance = {
            "source_file": path.name,
            "file_sha256": _sha256(path),
            "source_step": "RateCapability single CC discharge",
            "identification": (
                "rule-based: pre-discharge rest + single CC discharge "
                "to the lower voltage cutoff (negative raw current "
                "flipped to platform discharge+)"
            ),
            "c_rate": c_rate,
            "rate_label": str(info["rate_label"]),
            "rate_slug": str(info["rate_slug"]),
            "source_rate": token,
            "n_points": int(len(out)),
            "duration_s": float(t_rel[-1]),
            "rest_ocv_V": v0,
            "initial_stoichiometry_from_ocp": x0,
            "voltage_start_V": float(V_dis[0]),
            "voltage_end_V": float(V_dis[-1]),
            "median_current_A": float(np.median(I_dis)),
            "measured_temperature_median_K": (
                float(np.median(temp_k)) if len(temp_k) else float("nan")
            ),
            "temperature_matches_298.15K": temp_ok,
            "ambient_temperature_source": self._temperature_source,
            "parameter_match": dict(self._parameter_match),
            # v0.3/v0.4 explicit initial-state semantics:
            #  - this is a fixed-concentration initialisation derived
            #    from a MEASURED rest OCV through the model OCP curve
            #  - NOT a battery SOC, NOT fitted to the voltage
            "initial_state": {
                "type": "fixed_initial_concentration_from_inverse_ocp",
                "value": x0,
                "value_unit": "stoichiometry (Li fraction, x0)",
                "source": (
                    f"inverse-OCP(rest OCV {v0:.4f} V) on author "
                    f"ocp_discharge.csv"
                ),
                "history_replayed": False,
                "is_exact_electrochemical_state": False,
                "purpose": (
                    "reproduce author pipeline initialisation "
                    "(figure_5): measured pre-discharge OCV -> x0 -> "
                    "initial concentration x0*c_max; not a fitted "
                    "parameter"
                ),
                "fitted_to_voltage": False,
            },
            "initialisation_method": "inverse_ocp",
        }
        out.attrs["provenance"] = provenance
        out.attrs["initialisation"] = {
            "method": "fixed_initial_concentration",
            "ocp_voltage_V": v0,
            "stoichiometry_from_ocp": x0,
            "concentration_parameter": (
                "Initial concentration in positive electrode [mol.m-3]"
            ),
            "max_concentration_parameter": (
                "Maximum concentration in positive electrode [mol.m-3]"
            ),
            "published_default_value": (
                "authored default in Jackowska2025_2mAh_cm2 "
                "(5e3 mol/m3), read from the loaded parameter set "
                "before override"
            ),
            "mapping_reason": (
                "published default starts at Li fraction ~0.10 which "
                "contradicts the measured ~4.19-4.20 V rest OCV; the "
                "author pipeline (figure_5.py) initialises from "
                "inverse-OCP(rest V0).  The OCP inversion extends "
                "linearly ABOVE the ocp_discharge.csv top (4.186 V), "
                "matching PyBaMM's linear Interpolant: the authors' "
                "saved simulation opens at the measured 4.1935 V "
                "(H7 probe, docs/halfcell_birmingham_params_audit.md)"
            ),
        }
        return out

    # ------------------------------------------------------------------
    # Interface helpers
    # ------------------------------------------------------------------
    def discharge_info(self, cell: str, rate: str) -> dict:
        df = self.load_processed_discharge(str(cell), rate)
        prov = df.attrs["provenance"]
        return {
            "dataset": self.config.name,
            "cell_id": str(cell),
            "c_rate": prov["c_rate"],
            "rate_label": prov["rate_label"],
            "rate_slug": prov["rate_slug"],
            "source_rate": prov["source_rate"],
            "n_points": prov["n_points"],
            "duration_s": prov["duration_s"],
            "rest_ocv_V": prov["rest_ocv_V"],
            "initial_stoichiometry_x0": prov["initial_stoichiometry_from_ocp"],
            "voltage_start_V": prov["voltage_start_V"],
            "voltage_end_V": prov["voltage_end_V"],
            "capacity_end_Ah": float(df["capacity_Ah"].iloc[-1]),
            "median_current_A": prov["median_current_A"],
            "ambient_temperature_C": self.get_ambient_temperature(cell),
            "provenance": prov,
        }

    def get_initial_state(self, cell) -> float:
        """
        Measured open-circuit voltage [V]: the pre-discharge rest OCV
        of the C/10 file (lowest-rate, best OCV proxy).
        """
        df = self.load_processed_discharge(str(cell), "Cover10")
        return float(df.attrs["provenance"]["rest_ocv_V"])

    def get_ambient_temperature(self, cell) -> float:
        """Measured constant chamber temperature (config-owned)."""
        return self._ambient_C
