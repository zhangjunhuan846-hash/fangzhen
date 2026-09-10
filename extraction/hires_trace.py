# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B0.6: FULL-RESOLUTION canonical trace loader
#
# WHY THIS EXISTS
#   `adapter.load_raw()` decimates the whole file to
#   DEFAULT_MAX_POINTS = 20 000 samples before handing anything to
#   the OCP extraction.  For the SINTEF p-OCV file (189 340 rows at
#   10 s) that is a GLOBAL stride of 10 -> one sample every 100 s,
#   which wipes out the steep start of a branch:
#
#       lithiation branch, first 300 s
#         raw samples          31   (V: 3.000 -> 1.786 -> 1.621 -> ...
#                                     -> 0.885 V)
#         survive decimation    4   (t = 0, 90, 190, 280 s)
#
#   The extracted OCP table therefore jumped 3.0003 V -> 1.2349 V
#   between its first two rows, and any replay residual above 1.43 V
#   was an interpolation artefact of that gap (measured in Phase B0.5:
#   ~1937 mV).  Parameter extraction must not use a global stride.
#
# WHAT THIS MODULE DOES
#   Reads the SAME raw file the adapter reads (resolved from the
#   dataset config, and cross-checked against the adapter's own
#   provenance by name + SHA256) at FULL resolution, applies the same
#   canonical sign convention, and returns a record with the same
#   column contract as `load_raw` -- so `extract_ocp_branches` can be
#   reused unchanged (the SOC definition stays exactly the same).
#
#   Decimation: NONE.  The sample spacing of the output is the raw
#   sample spacing, and that fact is recorded in provenance.  Memory
#   stays bounded per batch; the whole trace is materialised only for
#   files that fit the caller's budget (the p-OCV file is 1.9e5 rows).
#
# This module imports numpy/pandas/pyarrow only -- never pybamm.
# ============================================================

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]

# raw parquet column names (same vocabulary as the SINTEF adapter)
COL_TIME = "Test Time / s"
COL_UNIX = "Unix Time / s"
COL_CURRENT = "Current / A"
COL_VOLTAGE = "Voltage / V"
COL_CYCLE = "Cycle Count / 1"
COL_STEP = "Step Index / 1"
COL_CAPACITY = "Cumulative Capacity / Ah"

TRACE_COLUMNS = [
    COL_TIME, COL_CURRENT, COL_VOLTAGE, COL_CYCLE, COL_STEP, COL_CAPACITY,
]

BATCH_SIZE = 1 << 18

# canonical platform convention: discharge = +, charge = -
SIGN_ACTION = "raw sign FLIPPED to platform canonical (discharge = +)"


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def resolve_raw_file(adapter, cell: str, rate: str) -> Tuple[Path, str]:
    """
    Locate the raw file for (cell, rate) from the DATASET CONFIG
    (``raw_dir`` + ``raw_file_template`` + the declared programme),
    without touching adapter internals.

    Returns (path, programme).
    """
    cfg = adapter.config
    rates_meta = dict((cfg.extra or {}).get("rates_meta") or {})
    if str(rate) not in rates_meta:
        raise ValueError(
            f"rate '{rate}' has no rates_meta entry for dataset "
            f"'{cfg.dataset_id}' ({sorted(rates_meta)})"
        )
    programme = str(rates_meta[str(rate)]["programme"])

    raw_dir = Path(cfg.raw_dir)
    if not raw_dir.is_absolute():
        raw_dir = ROOT / raw_dir
    template = str(getattr(cfg, "raw_file_template", ""))
    if not template:
        raise ValueError(
            f"dataset '{cfg.dataset_id}': raw_file_template is empty; the "
            f"high-fidelity loader cannot resolve the raw file"
        )
    pattern = template.format(cell=str(cell), programme=programme)
    matches = sorted(raw_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"no raw file for cell '{cell}' / rate '{rate}' in {raw_dir} "
            f"(pattern '{pattern}')"
        )
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous raw files for cell '{cell}' / rate '{rate}': "
            f"{[m.name for m in matches]}"
        )
    return matches[0], programme


def load_hires_trace(
    adapter,
    cell: str,
    rate: str,
    *,
    columns: Optional[List[str]] = None,
    verify_against_adapter: bool = True,
) -> pd.DataFrame:
    """
    FULL-RESOLUTION canonical trace for one (cell, rate) of a dataset.

    Output columns (same contract as ``adapter.load_raw``):
        time_s / current_A / voltage_V / capacity_Ah / cycle / step
        (+ temperature_ambient_C copied from the dataset declaration)

    ``time_s`` is relative to the first sample of the file.
    ``attrs["provenance"]`` records the file, its SHA256, the raw
    sample spacing and the explicit statement that NO decimation was
    applied.

    With ``verify_against_adapter`` the resolved file is checked
    against the adapter's own provenance (file name + SHA256), so the
    two paths can never silently drift apart.
    """
    path, programme = resolve_raw_file(adapter, cell, rate)
    cols = list(columns or TRACE_COLUMNS)
    missing = [c for c in TRACE_COLUMNS if c not in cols]
    if missing:
        raise ValueError(f"columns must include {missing}")

    pf = pq.ParquetFile(path)
    frames: List[pd.DataFrame] = []
    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=cols):
        frames.append(batch.to_pandas())
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    order = np.argsort(raw[COL_TIME].to_numpy(float), kind="stable")
    raw = raw.iloc[order].reset_index(drop=True)

    t = raw[COL_TIME].to_numpy(float)
    t_rel = t - float(t[0])
    I_raw = raw[COL_CURRENT].to_numpy(float)

    out = pd.DataFrame(
        {
            "time_s": t_rel,
            "current_A": -I_raw,          # flip to canonical
            "voltage_V": raw[COL_VOLTAGE].to_numpy(float),
            "capacity_Ah": raw[COL_CAPACITY].to_numpy(float),
            "cycle": raw[COL_CYCLE].to_numpy(np.int64),
            "step": raw[COL_STEP].to_numpy(np.int64),
            "raw_current_A": I_raw,
        }
    )
    try:
        temp = float(adapter.get_ambient_temperature(cell))
    except Exception:  # noqa: BLE001 - best effort, recorded below
        temp = float("nan")
    out["temperature_ambient_C"] = temp

    dt = np.diff(t)
    dt = dt[dt > 0]
    provenance: Dict[str, object] = {
        "loader": "extraction/hires_trace.py::load_hires_trace",
        "purpose": (
            "Phase B0.6 full-resolution trace for OCP extraction; the "
            "decimating load_raw path is deliberately NOT used"
        ),
        "source_file": path.name,
        "source_sha256": _sha256(path),
        "source_path": str(path.relative_to(ROOT))
        if path.is_relative_to(ROOT)
        else str(path),
        "programme": programme,
        "n_rows": int(len(out)),
        "row_groups": int(pf.metadata.num_row_groups),
        "sampling_median_s": float(np.median(dt)) if len(dt) else float("nan"),
        "sampling_min_s": float(dt.min()) if len(dt) else float("nan"),
        "sampling_max_s": float(dt.max()) if len(dt) else float("nan"),
        "decimation": "NONE - every raw sample is kept",
        "sign_convention": {
            "raw": "negative current = discharge (cycler convention)",
            "platform_canonical": "discharge = +, charge = -",
            "action": SIGN_ACTION,
            "raw_current_kept_as": "raw_current_A column",
        },
        "unit_conversion": {
            "time_s": "raw 'Test Time / s' made relative to its first sample",
            "current_A": "raw 'Current / A' negated (canonical)",
            "voltage_V": "raw 'Voltage / V' used as-is",
            "capacity_Ah": "raw per-step cumulative column, used as-is",
        },
        "ambient_temperature_C": out["temperature_ambient_C"].iloc[0]
        if len(out) else float("nan"),
    }

    if verify_against_adapter:
        probe = adapter.load_processed_discharge(cell, rate)
        ref = dict(probe.attrs.get("provenance") or {})
        checks = {
            "adapter_source_file": ref.get("source_file"),
            "adapter_source_sha256": ref.get("source_file_sha256"),
            "same_file": ref.get("source_file") == path.name,
            "same_sha256": ref.get("source_file_sha256")
            == provenance["source_sha256"],
            "adapter_rows_in_window": ref.get("n_raw_rows_in_window"),
            "adapter_stride": ref.get("decimation_stride"),
        }
        provenance["verification_vs_adapter"] = checks
        if not checks["same_file"] or not checks["same_sha256"]:
            raise ValueError(
                f"high-fidelity loader resolved a different file than the "
                f"adapter: {checks}"
            )

    out.attrs["provenance"] = provenance
    return out
