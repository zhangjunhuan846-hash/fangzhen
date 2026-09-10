# ============================================================
# Battery Dataset Simulation Platform -- Phase A (graphite line)
# SINTEF graphite R2032 || Li half-cell adapter
#
# Dataset: SINTEF "Battery Datasets for Testing Data Pipelines
# and Workflow Automation" catalog (Zenodo 10.5281/zenodo.18214281),
# R2032 coin cells, 2025-05 campaigns.  One .parquet file per
# (cell, programme); the file stem carries the cell's BDF id.
#
# AUDITED RAW FACTS (docs/graphite_dataset_triage.md):
#   * columns: Test Time [s] / Unix Time [s] / Current [A] /
#     Voltage [V] / Cycle Count / Step Index /
#     Cumulative Capacity [Ah]
#   * the capacity column is PER-STEP cumulative (resets to 0 at
#     each step; agrees with the trapezoidal current integral to
#     <0.5 % on the delithiation branch)
#   * sign convention: NEGATIVE current = DISCHARGE (standard cycler
#     convention, same as the Birmingham raw files).  For a
#     graphite||Li cell the spontaneous discharge LITHIATES the
#     graphite (Li dissolves from the Li metal and intercalates),
#     driving V from ~3 V (fresh) down to 0.01 V.  Verified in-data:
#     the negative-current step runs 3.0 V -> 0.01 V.
#     The platform canonical convention is DISCHARGE = +, so the raw
#     sign is FLIPPED (as in the Birmingham adapter).  Checked
#     against PyBaMM: with graphite in the positive slot a POSITIVE
#     current inserts Li (x: 0.964 -> 0.987, V -> 0 V) while a
#     NEGATIVE current extracts it (x -> 0.930, V rises), so after
#     the flip the canonical discharge direction and the model agree.
#   * p-OCV programme per cycle:
#       step 2 = lithiation  (-43.3 uA, 44-46 h, 3.0 -> 0.01 V)  = canonical +
#       step 3 = rest        (8 h)
#       step 4 = delithiation (+43.3 uA, 41-46 h, 0.01 -> 1.0 V) = canonical -
#       step 5 = rest        (8 h)
#     BOTH branches are exposed as rates (user decision 2026-09-10
#     selects the delithiation branch as the primary window):
#       pOCV-lith  lithiation    = the cell's own DISCHARGE direction
#       pOCV-deli  delithiation  = the user-selected window; under the
#                                  platform convention this is a
#                                  CHARGE-direction window, so the
#                                  runner's discharge-oriented columns
#                                  (current_peak_discharge_A, Q_sim,
#                                  capacity_error_pct) are NOT
#                                  meaningful for it -- the
#                                  time-aligned V(t) metrics are.
#     Branch selection is RULE-BASED on the measured current sign,
#     never guessed from the step index.
#   * no temperature channel -> ambient temperature is the
#     dataset-declared room temperature (see datasets.yaml);
#     provenance records
#     temperature_source = declared_room_temperature_not_measured
#
# PyBaMM slot convention (CRITICAL, audited 2026-09-10):
#   The built-in parameter set `Ecker2015_graphite_halfcell` stores
#   the GRAPHITE in the POSITIVE electrode slots (positive OCP =
#   graphite_ocp_Ecker2015, positive diffusivity = graphite_*,
#   negative OCP = 0 V + lithium-metal exchange-current density).
#   The platform therefore declares working_electrode = "positive"
#   (the PyBaMM SLOT) while the PHYSICAL working electrode is the
#   graphite negative electrode -- `physical_working_electrode` in
#   datasets.yaml records the physical meaning.
#
# Initial state: measured pre-delithiation rest OCV is inverted on
# the SAME graphite OCP table PyBaMM interpolates (vendored under
# external/pybamm-input-data/) -> initial Li fraction x0 -> initial
# concentration x0 * c_max.  This mirrors the Birmingham H6
# inverse-OCP method: it is a fixed initialisation derived from a
# measurement, NOT a battery SOC and NOT a fitted parameter.
#
# SCALE CAVEAT (recorded in datasets.yaml parameter_match.notes):
# the reference set describes an 85.85 cm2 / ~202 mAh graphite
# electrode, the SINTEF coin cell is 1.54 cm2 / ~2.16 mAh nominal.
# Per-area capacity differs by ~1.9x and the absolute current
# density by ~56x, so the zero-fit replay RMSE is dominated by
# this scale mismatch until a geometry-matched parameter set
# exists (Phase C).  Nothing here silently rescales anything.
#
# This module imports numpy/pandas/pyarrow only -- NEVER pybamm.
# ============================================================

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.paths import ROOT
from battery_sim.schemas import DatasetConfig

# ------------------------------------------------------------------
# Raw file layout
# ------------------------------------------------------------------
FILE_TEMPLATE = (
    "sintef__sintef-graphite-R2032-intelligent-{cell}__*__"
    "{programme}__RT.bdf.parquet"
)

COL_TIME = "Test Time / s"
COL_UNIX = "Unix Time / s"
COL_CURRENT = "Current / A"
COL_VOLTAGE = "Voltage / V"
COL_CYCLE = "Cycle Count / 1"
COL_STEP = "Step Index / 1"
COL_CAPACITY = "Cumulative Capacity / Ah"

TRACE_COLUMNS = [
    COL_TIME,
    COL_UNIX,
    COL_CURRENT,
    COL_VOLTAGE,
    COL_CYCLE,
    COL_STEP,
    COL_CAPACITY,
]

# ------------------------------------------------------------------
# Window / identification tolerances
# ------------------------------------------------------------------
ACTIVE_CURRENT_FRACTION = 0.5     # |mean I| >= 50 % of peak -> "on current"
REST_TAIL_S = 60.0                # last 60 s of the pre-branch rest are kept
MIN_REST_TAIL_S = 30.0            # the rest must be at least this long
BRANCH_V_RISE_MIN_V = 0.5         # delithiation must raise V by >= 0.5 V
BRANCH_CUTOFF_TOL_V = 0.05        # branch end must sit near the upper cutoff
OCP_EXTRAPOLATION_TOL_V = 0.05    # linear extrapolation allowed both ends
DISCHARGE_SIGN_MIN_MEDIAN_A = 0.0

DEFAULT_MAX_POINTS = 20000        # adapter-level memory guard (baseline
                                  # re-decimates to its own 2000 points)
BATCH_SIZE = 1 << 18

# ------------------------------------------------------------------
# metadata.csv (SINTEF catalog) -- electrode properties per cell
# ------------------------------------------------------------------
META_BDF = "BDF names"
META_AM_TYPE = "Active Material type"
META_DATE = "Start Date YYYYMMDD"
META_LABEL = "Public Labels"
META_PROGRAMME = "Cycling Programme name"
META_MASS_MG = "Mass of Active Material / mg"
META_COATING_G = "Electrode Coating Mass / g"
META_WT_PCT = "Weight percentage of Active Material / %"
META_THEO_CAP = "Theoretical Capacity /  mAh g-1"
META_DIAMETER_CM = "Electrode Diameter / cm"
META_THICKNESS_UM = "Dry Thickness / um"
META_AREAL_CAP = "Nominal Areal Capacity / mAh cm-2"
META_LOADING = "Electrode Loading / g cm-2"

_STRUCTURE_FIELDS = [
    (META_AM_TYPE, "active_material_type", None),
    (META_DATE, "campaign_date", None),
    (META_LABEL, "public_label", None),
    (META_PROGRAMME, "cycling_programme", None),
    (META_MASS_MG, "mass_active_material_mg", float),
    (META_COATING_G, "electrode_coating_mass_g", float),
    (META_WT_PCT, "active_material_wt_pct", float),
    (META_THEO_CAP, "theoretical_capacity_mAh_g", float),
    (META_DIAMETER_CM, "electrode_diameter_mm", float),
    (META_THICKNESS_UM, "dry_thickness_um", float),
    (META_AREAL_CAP, "nominal_areal_capacity_mAh_cm2", float),
    (META_LOADING, "electrode_loading_g_cm2", float),
]


def _sha256(path: Path) -> str:
    """Full-file SHA256 (user decision 2026-09-10: full digest)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cumulative_capacity(t: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Trapezoidal cumulative capacity [Ah] from (t[s], I[A])."""
    dt = np.diff(t)
    return np.concatenate(
        ([0.0], np.cumsum(dt * (current[1:] + current[:-1]) / 2.0) / 3600.0)
    )


def _decimate_index(n: int, max_points: int) -> np.ndarray:
    """Uniform index selection keeping the first and last sample."""
    if n <= max_points:
        return np.arange(n)
    idx = np.linspace(0, n - 1, max_points).round().astype(int)
    return np.unique(idx)


class SintefGraphiteAdapter(BatteryDatasetAdapter):
    """
    Adapter for the SINTEF graphite R2032 || Li half-cell dataset
    (room-temperature p-OCV programme; delithiation branch).

    ``cell`` accepts the BDF id embedded in the file name
    (e.g. "4ccc47").  ``rate`` accepts an id/slug/label from the
    dataset-declared rate table (Phase A: "pOCV").
    """

    def __init__(self, config: DatasetConfig):
        self.config = config
        self._raw_dir = ROOT / config.raw_dir
        if not self._raw_dir.is_dir():
            raise FileNotFoundError(
                f"SINTEF graphite raw dir not found: {self._raw_dir}"
            )

        extra = config.extra or {}

        # ---- first-class half-cell declaration (never guessed) ----
        self._cell_configuration = str(extra.get("cell_configuration", ""))
        if self._cell_configuration != "half_cell":
            raise ValueError(
                f"adapter {config.dataset_id}: cell_configuration must be "
                f"'half_cell' (configs/datasets.yaml)"
            )
        # PyBaMM SLOT: this is where the parameter set stores graphite.
        self._working_electrode = str(extra.get("working_electrode", ""))
        if self._working_electrode != "positive":
            raise ValueError(
                f"adapter {config.dataset_id}: working_electrode must be "
                f"'positive' (the PyBaMM slot in which "
                f"Ecker2015_graphite_halfcell stores the graphite "
                f"electrode); got {self._working_electrode!r}"
            )
        self._physical_working_electrode = str(
            extra.get("physical_working_electrode", "")
        )
        if self._physical_working_electrode != "graphite_negative":
            raise ValueError(
                f"adapter {config.dataset_id}: physical_working_electrode "
                f"must be 'graphite_negative' (configs/datasets.yaml)"
            )
        self._counter_electrode = str(extra.get("counter_electrode", ""))
        if self._counter_electrode != "lithium_metal":
            raise ValueError(
                f"adapter {config.dataset_id}: counter_electrode must be "
                f"'lithium_metal' (configs/datasets.yaml)"
            )

        # ---- ambient temperature block (declared, not measured) ----
        amb = extra.get("ambient_temperature")
        if not isinstance(amb, dict) or "value_C" not in amb:
            raise ValueError(
                f"dataset '{config.dataset_id}': no ambient_temperature "
                f"block with value_C in configs/datasets.yaml"
            )
        self._temperature_source = str(amb.get("source", "")).strip()
        if not self._temperature_source:
            # a temperature without a declared source is not auditable
            raise ValueError(
                f"dataset '{config.dataset_id}': ambient_temperature "
                f"block must declare 'source' (expected "
                f"'declared_room_temperature_not_measured' for this "
                f"dataset)"
            )
        self._ambient_C = float(amb["value_C"])
        self._temperature_confidence = str(amb.get("confidence", ""))
        self._temperature_note = str(amb.get("note", ""))

        # ---- rate table (dataset-declared; NOT the canonical registry) ----
        rates_meta = extra.get("rates_meta")
        if not isinstance(rates_meta, dict) or not rates_meta:
            raise ValueError(
                f"dataset '{config.dataset_id}': missing rates_meta block "
                f"in configs/datasets.yaml"
            )
        self._rate_table: Dict[str, dict] = {
            str(k): dict(v) for k, v in rates_meta.items()
        }
        for rid, meta in self._rate_table.items():
            for key in ("programme", "c_rate", "rate_label", "rate_slug",
                        "legacy_rate", "branch"):
                if key not in meta:
                    raise ValueError(
                        f"rates_meta['{rid}'] missing key '{key}'"
                    )
            if str(meta["branch"]) not in ("lithiation", "delithiation"):
                raise ValueError(
                    f"rates_meta['{rid}']: branch must be 'lithiation' or "
                    f"'delithiation' (got {meta['branch']!r})"
                )

        # ---- initialisation OCP table (vendored, pybamm-free) ----
        ocp_rel = str(extra.get("initialisation_ocp_file_rel", ""))
        if not ocp_rel:
            raise ValueError(
                f"adapter {config.dataset_id}: missing "
                f"initialisation_ocp_file_rel (configs/datasets.yaml)"
            )
        self._ocp_file = ROOT / ocp_rel
        if not self._ocp_file.is_file():
            raise FileNotFoundError(f"OCP file not found: {self._ocp_file}")

        # ---- catalog metadata.csv ----
        meta_rel = str(extra.get("metadata_csv_rel", ""))
        if not meta_rel:
            raise ValueError(
                f"adapter {config.dataset_id}: missing metadata_csv_rel "
                f"(configs/datasets.yaml)"
            )
        self._metadata_csv = ROOT / meta_rel
        if not self._metadata_csv.is_file():
            raise FileNotFoundError(
                f"metadata csv not found: {self._metadata_csv}"
            )

        self._max_points = int(
            extra.get("max_points", DEFAULT_MAX_POINTS)
        )
        self._target_cycle = int(extra.get("window_cycle", 1))
        self._parameter_match = dict(extra.get("parameter_match", {}))

        self._ocp_curve: Optional[Tuple[np.ndarray, np.ndarray]] = None

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
            # PyBaMM slot + physical meaning are BOTH reported
            "working_electrode": self._working_electrode,
            "physical_working_electrode": self._physical_working_electrode,
            "counter_electrode": self._counter_electrode,
            "parameter_set": cfg.parameter_set,
            "nominal_capacity_Ah": cfg.nominal_capacity_Ah,
            "cells": cfg.cells,
            "rates": cfg.rates,
            "ambient_temperature_C": self._ambient_C,
            "temperature_source": self._temperature_source,
            "temperature_confidence": self._temperature_confidence,
            "parameter_match": self._parameter_match,
            "window_cycle": self._target_cycle,
        }

    def list_cells(self) -> List[str]:
        return list(self.config.cells)

    def list_rates(self) -> List[str]:
        return list(self.config.rates)

    # ------------------------------------------------------------------
    # Rate resolution (dataset-declared table; canonical registry
    # deliberately NOT touched -- its c_rate set does not contain
    # C/50, and battery_sim/rates.py is frozen)
    # ------------------------------------------------------------------
    def rate_info(self, rate) -> Dict[str, object]:
        s = str(rate).strip()
        for rid, meta in self._rate_table.items():
            if s in (rid, str(meta["rate_slug"]), str(meta["rate_label"]),
                     str(meta["legacy_rate"])):
                return self._quintuple(rid, meta)
        # numeric C-rate string
        try:
            c = float(s)
        except ValueError:
            c = None
        if c is not None:
            for rid, meta in self._rate_table.items():
                if abs(float(meta["c_rate"]) - c) < 1e-9:
                    return self._quintuple(rid, meta)
        raise ValueError(
            f"Unknown rate '{rate}' for dataset "
            f"'{self.config.dataset_id}'. Known: {sorted(self._rate_table)}"
        )

    @staticmethod
    def _quintuple(rid: str, meta: dict) -> Dict[str, object]:
        return {
            "c_rate": float(meta["c_rate"]),
            "rate_label": str(meta["rate_label"]),
            "rate_slug": str(meta["rate_slug"]),
            "source_rate": str(meta.get("programme", rid)),
            "legacy_rate": str(meta["legacy_rate"]),
        }

    def list_rate_slugs(self) -> List[str]:
        return [str(self.rate_info(r)["rate_slug"]) for r in self.list_rates()]

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------
    def _raw_path(self, cell: str, rate: str) -> Path:
        if rate not in self._rate_table:
            raise ValueError(
                f"rate '{rate}' is not declared for dataset "
                f"'{self.config.dataset_id}' ({sorted(self._rate_table)})"
            )
        programme = str(self._rate_table[rate]["programme"])
        pattern = FILE_TEMPLATE.format(cell=cell, programme=programme)
        matches = sorted(self._raw_dir.glob(pattern))
        if not matches:
            raise FileNotFoundError(
                f"no raw file for cell '{cell}' / rate '{rate}' in "
                f"{self._raw_dir} (pattern '{pattern}')"
            )
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous raw files for cell '{cell}' / rate '{rate}': "
                f"{[m.name for m in matches]}"
            )
        return matches[0]

    def _structural_metadata(self, cell: str) -> dict:
        """Electrode properties for one cell from the catalog metadata."""
        meta = pd.read_csv(self._metadata_csv)
        if META_BDF not in meta.columns:
            raise ValueError(
                f"{self._metadata_csv.name}: missing column '{META_BDF}'"
            )
        hit = meta[
            meta[META_BDF].astype(str).str.contains(str(cell), regex=False)
        ]
        if hit.empty:
            raise ValueError(
                f"{self._metadata_csv.name}: no row for cell '{cell}'"
            )
        if len(hit) > 1:
            raise ValueError(
                f"{self._metadata_csv.name}: {len(hit)} rows match cell "
                f"'{cell}'; expected exactly one"
            )
        row = hit.iloc[0]
        out: Dict[str, object] = {}
        for col, key, caster in _STRUCTURE_FIELDS:
            if col not in meta.columns:
                continue
            val = row[col]
            if caster is not None:
                try:
                    out[key] = float(val)
                except (TypeError, ValueError):
                    out[key] = None
            else:
                out[key] = None if pd.isna(val) else str(val)
        # derived quantities
        # UNIT TRAP (audited): the catalog header says "Electrode
        # Diameter / cm" but the values are MILLIMETRES (14 -> a 14 mm
        # coin-cell disc, the standard R2032 punching).  Reading it as
        # cm inflates the area by 100x, so the value is taken as mm and
        # the inconsistency with the "g cm-2" loading column (which
        # implies ~1.69 cm2 rather than 1.539 cm2) is recorded.
        d_mm = out.get("electrode_diameter_mm")
        if isinstance(d_mm, float):
            area_cm2 = float(np.pi * (d_mm / 20.0) ** 2)
            out["electrode_area_cm2"] = area_cm2
            out["electrode_area_source"] = (
                f"pi*(d/2)^2 with d = {d_mm:g} mm read from the catalog "
                f"column labelled 'Electrode Diameter / cm' (values are mm)"
            )
            areal = out.get("nominal_areal_capacity_mAh_cm2")
            if isinstance(areal, float):
                out["nominal_cell_capacity_mAh"] = areal * area_cm2
            loading = out.get("electrode_loading_g_cm2")
            coating = out.get("electrode_coating_mass_g")
            if isinstance(loading, float) and loading > 0 and isinstance(
                coating, float
            ):
                out["area_implied_by_mass_over_loading_cm2"] = coating / loading
                out["area_inconsistency_note"] = (
                    "the catalog's own (coating mass / loading) implies "
                    f"{coating / loading:.4f} cm2 vs {area_cm2:.4f} cm2 from "
                    "the punched-disc diameter; ~10 % internal "
                    "inconsistency in the catalog, recorded not corrected"
                )
        return out

    # ------------------------------------------------------------------
    # Streaming readers (bounded memory; audit: the GITT file holds
    # 9.1e7 rows, so nothing may be read whole)
    # ------------------------------------------------------------------
    def _iter_batches(self, path: Path, columns: List[str]):
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=columns):
            yield batch.to_pandas()

    def _scan_steps(self, path: Path) -> pd.DataFrame:
        """
        Pass 1: per (cycle, step) row count + current statistics, read
        with bounded memory.  Used to classify steps as
        lithiation / rest / delithiation by the MEASURED current.
        """
        rows: List[dict] = []
        acc: Dict[Tuple[int, int], dict] = {}
        peak = 0.0
        for df in self._iter_batches(
            path, [COL_CYCLE, COL_STEP, COL_CURRENT]
        ):
            cur = df[COL_CURRENT].to_numpy(float)
            if len(cur):
                peak = max(peak, float(np.max(np.abs(cur))))
            df = df.assign(_abs=df[COL_CURRENT].abs())
            gb = df.groupby([COL_CYCLE, COL_STEP], sort=False)
            stats = gb[COL_CURRENT].agg(["count", "sum", "last"])
            amax = gb["_abs"].max()
            for (c, s), r in stats.iterrows():
                key = (int(c), int(s))
                d = acc.get(key)
                if d is None:
                    acc[key] = d = {"n": 0, "sum": 0.0, "absmax": 0.0,
                                    "last": 0.0}
                d["n"] += int(r["count"])
                d["sum"] += float(r["sum"])
                d["last"] = float(r["last"])
                d["absmax"] = max(d["absmax"], float(amax.loc[(c, s)]))
        for (c, s), d in sorted(acc.items()):
            rows.append(
                {
                    "cycle": c,
                    "step": s,
                    "n_rows": int(d["n"]),
                    "mean_current_A": d["sum"] / d["n"] if d["n"] else np.nan,
                    "abs_max_current_A": float(d["absmax"]),
                }
            )
        out = pd.DataFrame(rows)
        out.attrs["peak_abs_current_A"] = peak
        return out

    def _read_window(
        self,
        path: Path,
        want: List[Tuple[int, int]],
        expected_rows: int,
    ) -> pd.DataFrame:
        """
        Pass 2: materialise the (cycle, step) pairs in ``want``.

        Decimation is PER GROUP with a row-count-proportional budget,
        and each group keeps its FIRST and LAST sample: a global
        stride with an offset would silently drop branch endpoints
        (audited: it lost the 3.0 V first sample of the fresh-cell
        lithiation branch, which is the SOC = 0 anchor).
        """
        want_set = {(int(c), int(s)) for c, s in want}
        chunks: List[pd.DataFrame] = []
        seen = 0
        max_stride = 1
        for df in self._iter_batches(path, TRACE_COLUMNS):
            cyc = df[COL_CYCLE].to_numpy(np.int64)
            stp = df[COL_STEP].to_numpy(np.int64)
            mask = np.array(
                [(int(c), int(s)) in want_set for c, s in zip(cyc, stp)],
                dtype=bool,
            )
            if not mask.any():
                continue
            sub = df.loc[mask]
            seen += len(sub)
            out_parts = []
            for _key, g in sub.groupby([COL_CYCLE, COL_STEP], sort=False):
                budget = max(
                    2,
                    int(round(self._max_points * len(g) / max(expected_rows, 1))),
                )
                idx = _decimate_index(len(g), budget)
                max_stride = max(max_stride, int(np.ceil(len(g) / budget)))
                out_parts.append(g.iloc[idx])
            chunks.append(pd.concat(out_parts))
        if not chunks:
            raise ValueError(
                f"{path.name}: no rows matched cycle/step {sorted(want_set)}"
            )
        out = pd.concat(chunks, ignore_index=True)
        out = out.sort_values(COL_TIME, kind="stable").reset_index(drop=True)
        out.attrs["decimation_stride"] = int(max_stride)
        out.attrs["rows_matched_before_decimation"] = int(seen)
        out.attrs["decimation"] = (
            "per-(cycle,step) budget proportional to row count; the first "
            "and last sample of every group are always retained"
        )
        return out

    # ------------------------------------------------------------------
    # OCP inversion (pure data; vendored table)
    # ------------------------------------------------------------------
    def _load_ocp_curve(self) -> Tuple[np.ndarray, np.ndarray]:
        if self._ocp_curve is not None:
            return self._ocp_curve
        ocp = pd.read_csv(
            self._ocp_file, header=None, names=["stoichiometry", "voltage_V"]
        )
        sto = ocp["stoichiometry"].to_numpy(float)
        vv = ocp["voltage_V"].to_numpy(float)
        order = np.argsort(vv, kind="stable")
        self._ocp_curve = (sto[order], vv[order])
        return self._ocp_curve

    def inverse_ocp(self, voltage_V: float) -> float:
        """
        Stoichiometry x0 with OCP(x0) = voltage_V on the vendored
        graphite OCP table (the same table PyBaMM interpolates).

        Piecewise-linear inversion, with the SAME linear extrapolation
        at both ends that PyBaMM's linear Interpolant performs (never
        np.interp clipping, which would pin x0 to a table edge).
        """
        sto, vv = self._load_ocp_curve()  # ascending in V
        vmin, vmax = float(vv[0]), float(vv[-1])
        if (
            voltage_V < vmin - OCP_EXTRAPOLATION_TOL_V
            or voltage_V > vmax + OCP_EXTRAPOLATION_TOL_V
        ):
            raise ValueError(
                f"rest OCV {voltage_V:.4f} V more than "
                f"{OCP_EXTRAPOLATION_TOL_V} V outside the graphite OCP "
                f"table [{vmin:.4f}, {vmax:.4f}] V"
            )
        if voltage_V < vmin:
            s = (sto[1] - sto[0]) / (vv[1] - vv[0])
            return float(sto[0] + s * (voltage_V - vv[0]))
        if voltage_V > vmax:
            s = (sto[-1] - sto[-2]) / (vv[-1] - vv[-2])
            return float(sto[-1] + s * (voltage_V - vv[-1]))
        return float(np.interp(voltage_V, vv, sto))

    # ------------------------------------------------------------------
    # Window identification (rule-based, fail-loud)
    # ------------------------------------------------------------------
    def _identify_branches(
        self, steps: pd.DataFrame, path: Path, branch: str
    ) -> Tuple[int, int, int, int]:
        """
        For the configured cycle and requested branch return
        (n_branch_rows, rest_step, branch_step, n_rest_rows).

        Classification is by MEASURED mean current relative to the
        file's peak |I|; nothing is inferred from step numbering.
        """
        peak = float(steps.attrs.get("peak_abs_current_A", 0.0))
        if peak <= 0:
            raise ValueError(f"{path.name}: no non-zero current in file")
        thr = ACTIVE_CURRENT_FRACTION * peak

        cand = steps[steps["cycle"] == self._target_cycle].sort_values("step")
        if cand.empty:
            raise ValueError(
                f"{path.name}: cycle {self._target_cycle} not found "
                f"(cycles: {sorted(steps['cycle'].unique())})"
            )

        if branch == "lithiation":
            # raw negative current = discharge = lithiation
            sel = cand[cand["mean_current_A"] <= -thr]
        elif branch == "delithiation":
            sel = cand[cand["mean_current_A"] >= thr]
        else:
            raise ValueError(f"unknown branch '{branch}'")

        if sel.empty:
            raise ValueError(
                f"{path.name}: no {branch} step in cycle "
                f"{self._target_cycle} (mean currents: "
                f"{[round(v * 1e6, 2) for v in cand['mean_current_A']]})"
            )
        if len(sel) > 1:
            raise ValueError(
                f"{path.name}: {len(sel)} {branch} steps in cycle "
                f"{self._target_cycle}: {sorted(sel['step'].tolist())}; "
                f"expected exactly one"
            )
        br_step = int(sel.iloc[0]["step"])

        rest = cand[
            (cand["step"] < br_step) & (cand["mean_current_A"].abs() < thr)
        ]
        if rest.empty:
            raise ValueError(
                f"{path.name}: no rest step before the {branch} step "
                f"{br_step} in cycle {self._target_cycle}"
            )
        rest_step = int(rest["step"].max())

        br_n = int(sel.iloc[0]["n_rows"])
        rest_n = int(rest[rest["step"] == rest_step].iloc[0]["n_rows"])
        return br_n, rest_step, br_step, rest_n

    # ------------------------------------------------------------------
    # Public data interface
    # ------------------------------------------------------------------
    def load_raw(self, cell) -> pd.DataFrame:
        """
        Whole file as a canonical (decimated) trace, for audits and
        for the OCP extractor.

        Columns: time_s / current_A / voltage_V / capacity_Ah /
        cycle / step (+ temperature_ambient_C).

        Canonical sign is applied here as well (raw cycler negative =
        discharge -> flipped), so branch classification downstream can
        rely on: current > 0 = discharge = lithiation of graphite.
        """
        rate = self.list_rates()[0]
        path = self._raw_path(str(cell), rate)
        steps = self._scan_steps(path)
        n_total = int(steps["n_rows"].sum())
        df = self._read_window(
            path,
            [(int(r["cycle"]), int(r["step"])) for _, r in steps.iterrows()],
            n_total,
        )
        t = df[COL_TIME].to_numpy(float)
        I = -df[COL_CURRENT].to_numpy(float)  # -> canonical (discharge +)
        out = pd.DataFrame(
            {
                "time_s": t,
                "current_A": I,
                "voltage_V": df[COL_VOLTAGE].to_numpy(float),
                "capacity_Ah": _cumulative_capacity(t, I),
                "cycle": df[COL_CYCLE].to_numpy(np.int64),
                "step": df[COL_STEP].to_numpy(np.int64),
            }
        )
        t0 = float(out["time_s"].iloc[0])
        out["time_s"] = out["time_s"] - t0
        out["temperature_ambient_C"] = float(self._ambient_C)
        out.attrs["decimation_stride"] = int(
            df.attrs.get("decimation_stride", 1)
        )
        out.attrs["rows_before_decimation"] = int(
            df.attrs.get("rows_matched_before_decimation", len(out))
        )
        out.attrs["sign_convention"] = (
            "canonical (discharge = +) applied: raw cycler negative = "
            "discharge flipped; for a graphite||Li half cell the discharge "
            "direction lithiates the graphite"
        )
        out.attrs["provenance"] = {
            "source_file": path.name,
            "source_file_sha256": _sha256(path),
            "scope": "whole file (all cycles/steps), decimated",
            "ambient_temperature_C": float(self._ambient_C),
            "ambient_temperature_source": self._temperature_source,
        }
        return out

    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """
        Canonical replay window: the pre-branch rest tail (60 s)
        followed by the requested p-OCV branch.

        Columns: time_s (relative to the window start) / current_A
        [platform canonical: DISCHARGE = +; the raw cycler sign
        (negative = discharge) is FLIPPED here] / voltage_V /
        capacity_Ah [signed by the canonical current] /
        temperature_ambient_C.
        """
        cell = str(cell)
        if cell not in [str(c) for c in self.config.cells]:
            raise ValueError(
                f"unknown cell '{cell}' for {self.config.dataset_id}; "
                f"expected one of {self.config.cells}"
            )

        info = self.rate_info(rate)
        branch = str(self._rate_table[str(rate)]["branch"])
        path = self._raw_path(cell, str(rate))
        structure = self._structural_metadata(cell)

        steps = self._scan_steps(path)
        br_n, rest_step, br_step, rest_n = self._identify_branches(
            steps, path, branch
        )

        win = self._read_window(
            path,
            [
                (self._target_cycle, rest_step),
                (self._target_cycle, br_step),
            ],
            br_n + rest_n,
        )

        is_rest = win[COL_STEP].to_numpy(np.int64) == rest_step
        t = win[COL_TIME].to_numpy(float)
        I_raw = win[COL_CURRENT].to_numpy(float)
        V = win[COL_VOLTAGE].to_numpy(float)
        Ah_raw = win[COL_CAPACITY].to_numpy(float)

        # canonical sign: platform discharge = +, raw cycler negative =
        # discharge -> FLIP (verified in-data and against PyBaMM)
        I = -I_raw

        # ---- rest tail ----
        if not is_rest.any():
            raise ValueError(f"{path.name}: rest step {rest_step} empty")
        t_rest = t[is_rest]
        rest_len_s = float(t_rest[-1] - t_rest[0])
        if rest_len_s + 0.0 < MIN_REST_TAIL_S:
            raise ValueError(
                f"{path.name}: pre-branch rest only {rest_len_s:.1f} s "
                f"(< {MIN_REST_TAIL_S} s)"
            )
        tail_mask = is_rest & (t >= t_rest[-1] - REST_TAIL_S)

        # ---- branch ----
        br_mask = ~is_rest
        if not br_mask.any():
            raise ValueError(
                f"{path.name}: {branch} step {br_step} empty"
            )
        I_br = I[br_mask]
        V_br = V[br_mask]
        Ah_br = Ah_raw[br_mask]

        med_I = float(np.median(I_br))
        if branch == "lithiation":
            # canonical discharge = positive current
            if med_I <= 0:
                raise ValueError(
                    f"{path.name}: lithiation branch median canonical "
                    f"current {med_I:.3e} A is not a discharge (+)"
                )
            if V_br[-1] > V_br[0] - BRANCH_V_RISE_MIN_V:
                raise ValueError(
                    f"{path.name}: lithiation branch lowers V by only "
                    f"{V_br[0] - V_br[-1]:.3f} V "
                    f"(< {BRANCH_V_RISE_MIN_V} V)"
                )
            end_cut = (
                self.config.lower_voltage_cutoff_V
                if self.config.lower_voltage_cutoff_V is not None
                else 0.01
            )
            if abs(float(V_br[-1]) - end_cut) > BRANCH_CUTOFF_TOL_V:
                raise ValueError(
                    f"{path.name}: lithiation ends at {V_br[-1]:.4f} V, "
                    f"not at the {end_cut} V cutoff "
                    f"(+/-{BRANCH_CUTOFF_TOL_V} V)"
                )
        else:
            # delithiation = canonical charge = negative current
            if med_I >= DISCHARGE_SIGN_MIN_MEDIAN_A:
                raise ValueError(
                    f"{path.name}: delithiation branch median canonical "
                    f"current {med_I:.3e} A is not a charge (-)"
                )
            if V_br[-1] - V_br[0] < BRANCH_V_RISE_MIN_V:
                raise ValueError(
                    f"{path.name}: delithiation branch raises V by only "
                    f"{V_br[-1] - V_br[0]:.3f} V "
                    f"(< {BRANCH_V_RISE_MIN_V} V)"
                )
            end_cut = (
                self.config.upper_voltage_cutoff_V
                if self.config.upper_voltage_cutoff_V is not None
                else 1.0
            )
            if abs(float(V_br[-1]) - end_cut) > BRANCH_CUTOFF_TOL_V:
                raise ValueError(
                    f"{path.name}: delithiation ends at {V_br[-1]:.4f} V, "
                    f"not at the {end_cut} V cutoff "
                    f"(+/-{BRANCH_CUTOFF_TOL_V} V)"
                )

        # ---- assemble ----
        sel = tail_mask | br_mask
        t_sel = t[sel]
        t_rel = t_sel - float(t_sel[0])
        I_sel = I[sel]
        V_sel = V[sel]

        # capacity: 0 over the rest, cumulative canonical charge over
        # the branch (negative for a charge-direction window)
        cap = np.zeros(len(t_sel), dtype=float)
        br_sel = br_mask[sel]
        if br_sel.any():
            cap[br_sel] = _cumulative_capacity(t_sel[br_sel], I_sel[br_sel])

        out = pd.DataFrame(
            {
                "time_s": t_rel,
                "current_A": I_sel,
                "voltage_V": V_sel,
                "capacity_Ah": cap,
                "temperature_ambient_C": float(self._ambient_C),
            }
        )

        # ---- initial state from the measured rest OCV (inverse OCP) ----
        t_tail = t[tail_mask]
        V_tail = V[tail_mask]
        v0 = float(np.median(V_tail))
        init_edge_fallback = False
        try:
            x0 = self.inverse_ocp(v0)
        except ValueError:
            # fresh cell: the rest OCV lies ABOVE the reference OCP
            # table (2.97 V vs the table top 1.4325 V) -> start at the
            # table's delithiated edge and flag it
            sto, _vv = self._load_ocp_curve()
            x0 = float(np.min(sto))
            init_edge_fallback = True

        cap_integral_Ah = float(
            np.trapezoid(I_sel, t_sel - float(t_sel[0])) / 3600.0
        )
        cap_column_raw_Ah = float(Ah_br[-1] - Ah_br[0])

        # measured rate check (declared rate comes from the config)
        nominal_mAh = structure.get("nominal_cell_capacity_mAh")
        c_rate_measured = (
            float(abs(med_I) * 1000.0 / nominal_mAh)
            if isinstance(nominal_mAh, float) and nominal_mAh > 0
            else float("nan")
        )

        provenance = {
            "source_file": path.name,
            "source_file_sha256": _sha256(path),
            "source_dataset": (
                "SINTEF battery dataset catalog (Zenodo "
                "10.5281/zenodo.18214281) - graphite R2032 half cell"
            ),
            "identification": (
                "rule-based: pre-branch rest (60 s tail) + the unique "
                f"{branch} step of the configured p-OCV cycle; "
                "classification by measured current, never by step "
                "numbering"
            ),
            "window_cycle": self._target_cycle,
            "rest_step": rest_step,
            "branch_step": br_step,
            "branch": branch,
            "branch_physics": {
                "lithiation": (
                    "the cell's own DISCHARGE direction (Li dissolves "
                    "from the Li metal and intercalates into graphite)"
                ),
                "delithiation": (
                    "Li extraction from graphite; under the platform "
                    "canonical convention this is a CHARGE-direction "
                    "window"
                ),
            }[branch],
            "sign_convention": {
                "raw": (
                    "negative current = DISCHARGE (standard cycler "
                    "convention; same as the Birmingham raw files)"
                ),
                "verified_from_data": (
                    "the negative-current step drives 3.0 V -> 0.01 V, "
                    "i.e. lithiation of graphite, which is the "
                    "spontaneous (discharge) direction for a "
                    "graphite||Li cell"
                ),
                "platform_canonical": "discharge = +, charge = -",
                "action": "raw sign FLIPPED to canonical",
                "model_check": (
                    "with graphite in the PyBaMM POSITIVE slot a "
                    "positive current inserts Li (x 0.964 -> 0.987, "
                    "V -> 0 V) and a negative current extracts it "
                    "(x -> 0.930, V rises)"
                ),
            },
            "unit_conversion": {
                "time_s": "raw 'Test Time / s' used as-is (seconds)",
                "current_A": (
                    "raw 'Current / A' negated (cycler sign -> platform "
                    "canonical discharge = +)"
                ),
                "voltage_V": "raw 'Voltage / V' used as-is (volts)",
                "capacity_Ah": (
                    "trapezoidal integral of the CANONICAL current; the "
                    "file's own per-step cumulative column is carried in "
                    "branch_charge_raw_column_Ah for cross-check"
                ),
                "temperature": (
                    "no temperature channel in the file; the dataset-"
                    "declared room temperature is written into "
                    "temperature_ambient_C"
                ),
            },
            "c_rate": float(info["c_rate"]),
            "c_rate_basis": (
                "declared in configs/datasets.yaml from the catalog's "
                "nominal areal capacity x electrode area"
            ),
            "c_rate_measured_from_data": c_rate_measured,
            "rate_label": str(info["rate_label"]),
            "rate_slug": str(info["rate_slug"]),
            "source_rate": str(info["source_rate"]),
            "n_points": int(len(out)),
            "n_raw_rows_in_window": int(
                win.attrs.get("rows_matched_before_decimation", len(win))
            ),
            "decimation_stride": int(win.attrs.get("decimation_stride", 1)),
            "duration_s": float(t_rel[-1]),
            "rest_tail_s": float(t_tail[-1] - t_tail[0]),
            "rest_ocv_V": v0,
            "initial_stoichiometry_from_ocp": x0,
            "initial_state_source": (
                "ocp_table_edge_fallback"
                if init_edge_fallback
                else "inverse_ocp_of_measured_rest_ocv"
            ),
            "voltage_start_V": float(V_br[0]),
            "voltage_end_V": float(V_br[-1]),
            "median_current_A": med_I,
            "branch_charge_raw_column_Ah": cap_column_raw_Ah,
            "branch_charge_canonical_Ah": cap_integral_Ah,
            "measured_structure": structure,
            "ambient_temperature_C": float(self._ambient_C),
            "ambient_temperature_source": self._temperature_source,
            "ambient_temperature_confidence": self._temperature_confidence,
            "ambient_temperature_note": self._temperature_note,
            "parameter_match": dict(self._parameter_match),
            "initial_state": {
                "type": "fixed_initial_concentration_from_inverse_ocp",
                "value": x0,
                "value_unit": "stoichiometry (Li fraction, x0, positive "
                              "electrode slot = graphite)",
                "source": (
                    f"inverse-OCP(rest OCV {v0:.4f} V) on the vendored "
                    f"graphite OCP table"
                    if not init_edge_fallback
                    else (
                        f"rest OCV {v0:.4f} V lies above the reference "
                        f"graphite OCP table top; initial Li fraction set "
                        f"to the table's delithiated edge"
                    )
                ),
                "history_replayed": False,
                "is_exact_electrochemical_state": False,
                "purpose": (
                    "initialise the branch replay at the measured "
                    "pre-branch equilibrium state; not a fitted parameter "
                    "and not a battery SOC"
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
            # NOTE: this parameter set stores graphite in the POSITIVE
            # electrode slots, so the initial concentration to override
            # is the positive-electrode one.
            "concentration_parameter": (
                "Initial concentration in positive electrode [mol.m-3]"
            ),
            "max_concentration_parameter": (
                "Maximum concentration in positive electrode [mol.m-3]"
            ),
            "mapping_reason": (
                "graphite occupies the positive electrode slot of "
                "Ecker2015_graphite_halfcell (audited); initial Li "
                f"fraction x0 = {x0:.4f} from the pre-branch rest OCV "
                f"{v0:.4f} V"
            ),
        }
        return out

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
            "initial_stoichiometry_x0": prov[
                "initial_stoichiometry_from_ocp"
            ],
            "voltage_start_V": prov["voltage_start_V"],
            "voltage_end_V": prov["voltage_end_V"],
            "capacity_end_Ah": float(df["capacity_Ah"].iloc[-1]),
            "median_current_A": prov["median_current_A"],
            "ambient_temperature_C": self.get_ambient_temperature(cell),
            "provenance": prov,
        }

    def get_initial_state(self, cell) -> float:
        """Measured pre-delithiation rest OCV [V] (p-OCV cycle 1)."""
        df = self.load_processed_discharge(
            str(cell), self.list_rates()[0]
        )
        return float(df.attrs["provenance"]["rest_ocv_V"])

    def get_ambient_temperature(self, cell) -> float:
        """
        Dataset-declared room temperature (not measured).

        ``provenance.ambient_temperature_source`` records
        'declared_room_temperature_not_measured'.
        """
        return self._ambient_C
