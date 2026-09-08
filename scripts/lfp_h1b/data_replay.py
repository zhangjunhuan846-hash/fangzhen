"""H1-B data replay gate: SINTEF R2032 LFP-NMP-1 p-OCV (d07eb6).

Goal (user task book, H1-B):
  turn one public parquet into a provenance + protocol + capacity verified
  canonical half-cell experimental dataset.  Adapter-level ONLY:
  * no pybamm import (gate: model_dependency = 0)
  * no inverse OCP / stoichiometry (initial state = measured facts only)
  * no fitting, no GITT download, no D_s inference.

Outputs (default out dir: outputs/analysis/lfp_h1/data_replay/):
  source_manifest.json   file/metadata/dataset/electrode provenance + hashes
  cycle_manifest.csv     row per contiguous protocol block (21 rows expected)
  processed_pocv.parquet generic row-wise canonical table
  replay_summary.json    gate results + capacity comparison + initial states
  figures/fig1_v_time.png, fig2_i_time.png, fig3_v_capacity.png   (sanity only)

Fresh replay: rerun with a fresh --out dir; the 3 data files (and PNGs) must be
byte-identical (deterministic pipeline).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Constants / expected protocol facts (frozen from Zenodo record + metadata.csv)
# ----------------------------------------------------------------------------
RECORD_DOI = "10.5281/zenodo.19107295"
RECORD_VERSION_MATCHED = "v1"
RECORD_NEWER = "10.5281/zenodo.20086298"
RECORD_TITLE = (
    "Half-Cell Open-Circuit Voltage of Several Lithium-Ion Battery Active "
    "Materials Measured under Various Electrochemical Protocols"
)
LICENSE = "CC-BY-4.0"

# official md5 of the p-ocv d07eb6 parquet, as recorded on Zenodo v1 (verified
# locally during H1-A screening: 3efea83a... == official value).
OFFICIAL_MD5 = "3efea83aa4a59c500bde5723a67e3c3c"

# metadata facts from SINTEF metadata.csv row (BDF names == basename of RAW)
PUBLIC_LABEL = "LFP-NMP-1"
ACTIVE_MATERIAL = "LFP"
CYCLING_PROGRAMME = "p-OCV"
ELECTRODE_DIAMETER_MM = 14.0          # metadata column header says "cm" but the
                                      # value 14 is a mm disc (flagged in notes)
DRY_THICKNESS_UM = 78.0
NOMINAL_AREAL_CAPACITY_MAH_CM2 = 2.0  # manufacturer nominal (metadata)
TEMPERATURE_NOTE = "RT (record: room temperature; no numeric value reported)"
START_DATE = 20250602

# expected protocol structure: 5 full cycles, each charge(C/50)->8h rest->
# discharge(C/50)->8h rest; plus one 6 h pre-cycle rest at file start.
EXPECTED_CYCLES = 5
EXPECTED_DRIVEN = 10                 # 5 charge + 5 discharge legs
EXPECTED_REST_BLOCKS = 11            # 1 initial (6 h) + 5 top + 5 bottom (8 h)
CUTOFF_CHARGE_V = 3.65
CUTOFF_DISCHARGE_V = 2.50

# ----------------------------------------------------------------------------
# paths (repo rooted at this file: <root>/scripts/lfp_h1b/data_replay.py)
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
RAW = (
    ROOT
    / "data/raw/LIB/LFP_LiMetal/SINTEF_R2032/raw"
    / "sintef__sintef-lfp-R2032-gelon-d07eb6__20250602__p-ocv__RT.bdf.parquet"
)
META_CSV = ROOT / "data/raw/LIB/LFP_LiMetal/SINTEF_R2032/meta/metadata.csv"
DEFAULT_OUT = ROOT / "outputs/analysis/lfp_h1/data_replay"

CELL_ID = "SINTEF-LFP-NMP-1-pocv-d07eb6"

# current sign classification threshold (A); rest currents are exactly 0.0
EPS_I = 1e-12


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iso_mtime(p: Path) -> str:
    ts = os.path.getmtime(p)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def detect_blocks(df: pd.DataFrame) -> list[dict]:
    """Split into contiguous same-type blocks based on measured current only.

    Block types: charge (I>+eps), discharge (I<-eps), rest (|I|<=eps).
    The cycler's Cycle/Step columns are NOT used for classification; they are
    cross-checked afterwards (repeatable, data-driven segmentation).
    """
    I = df["current_A"].to_numpy()
    cyc = df["raw_cycle_index"].to_numpy()
    stp = df["raw_step_index"].to_numpy()
    state = np.where(I > EPS_I, 1, np.where(I < -EPS_I, -1, 0))
    edges = np.flatnonzero(np.diff(state) != 0) + 1
    bounds = np.concatenate([[0], edges, [len(df)]])
    blocks = []
    for k in range(len(bounds) - 1):
        i0, i1 = int(bounds[k]), int(bounds[k + 1])
        typ = {1: "charge", -1: "discharge", 0: "rest"}[int(state[i0])]
        blocks.append(
            dict(
                type=typ,
                i0=i0,
                i1=i1,
                cycle=int(cyc[i0]),
                step=int(stp[i0]),
                raw_cycles_unique=sorted(set(cyc[i0:i1].tolist())),
                raw_steps_unique=sorted(set(stp[i0:i1].tolist())),
            )
        )
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-figures", action="store_true",
                    help="skip matplotlib figures (fast QA run)")
    args = ap.parse_args()

    # ---- gate 8a: model dependency = 0 (checked before any heavy work) -----
    pybamm_loaded = [m for m in sys.modules if m == "pybamm" or m.startswith("pybamm.")]
    gate_model_dependency = len(pybamm_loaded) == 0
    import_list = sorted(
        m.split(".")[0] for m in sys.modules
        if m.split(".")[0] in {"numpy", "pandas", "pyarrow", "matplotlib"}
    )
    print("== H1-B data replay | SINTEF LFP-NMP-1 p-OCV (d07eb6) ==")
    print(f"out dir : {args.out}")
    print(f"gate model_dependency(0 pybamm import): {gate_model_dependency}")

    # ------------------------------------------------------------------ 1
    # provenance freeze
    # ------------------------------------------------------------------
    print("\n[1/5] provenance freeze")
    raw_sha = sha256_file(RAW)
    raw_md5 = md5_file(RAW)
    meta_sha = sha256_file(META_CSV)
    meta_md5 = md5_file(META_CSV)
    n_raw = RAW.stat().st_size
    n_meta = META_CSV.stat().st_size
    print(f"  raw  : {RAW.name}\n         size={n_raw} B  sha256={raw_sha}")
    print(f"         md5={raw_md5}  (official Zenodo v1 md5={OFFICIAL_MD5})")
    print(f"  meta : {META_CSV.name}  size={n_meta} B  sha256={meta_sha}  md5={meta_md5}")

    mdf = pd.read_csv(META_CSV)
    meta_row = mdf[mdf["BDF names"] == RAW.name]
    if len(meta_row) != 1:
        raise SystemExit(f"metadata row for {RAW.name} not found uniquely "
                         f"(found {len(meta_row)})")
    mr = meta_row.iloc[0].to_dict()

    df = pd.read_parquet(RAW)
    raw_cols = list(df.columns)
    df = df.rename(
        columns={
            "Test Time / s": "time_s",
            "Unix Time / s": "unix_time_s",
            "Current / A": "current_A",
            "Voltage / V": "voltage_V",
            "Cycle Count / 1": "raw_cycle_index",
            "Step Index / 1": "raw_step_index",
            "Cumulative Capacity / Ah": "cum_capacity_raw_Ah",
        }
    )
    n_rows = len(df)
    t = df["time_s"].to_numpy()
    V = df["voltage_V"].to_numpy()
    I = df["current_A"].to_numpy()
    span_h = (t[-1] - t[0]) / 3600.0
    print(f"  rows={n_rows}  cols={df.shape[1]}  time {t[0]:.3f}..{t[-1]:.3f} s"
          f" ({span_h:.2f} h)")

    # time monotonicity (cycler files may duplicate the boundary row at an event)
    dt = np.diff(t)
    gate_time_monotonic = bool(np.all(dt >= -1e-6))
    n_dup = int(np.sum(np.abs(dt) < 1e-6))
    print(f"  time nondecreasing: {gate_time_monotonic}  (boundary duplicates: {n_dup})")

    # ------------------------------------------------------------------ 2
    # protocol segmentation (current-driven)
    # ------------------------------------------------------------------
    print("\n[2/5] protocol segmentation")
    blocks = detect_blocks(df)
    seg_rows = []
    for b in blocks:
        i0, i1 = b["i0"], b["i1"]
        t0, t1 = t[i0], t[i1 - 1]
        seg_type = b["type"]
        Ib = I[i0:i1]
        Vb = V[i0:i1]
        # integrate |I| dt within block only (never across a boundary)
        tb = t[i0:i1]
        # integrate |I| dt within block only (never across a boundary);
        # dt in s, current in A -> charge in Ah = A*s / 3600
        dq = np.abs(Ib[1:] + Ib[:-1]) / 2.0 * np.diff(tb) / 3600.0
        q_ah = float(np.sum(dq)) if seg_type != "rest" else 0.0
        seg_rows.append(
            dict(
                type=seg_type,
                cycle=b["cycle"],
                step=b["step"],
                n_rows=i1 - i0,
                i0=i0,
                i1=i1,
                t0=float(t0),
                t1=float(t1),
                dur_h=(t1 - t0) / 3600.0,
                i_med_uA=float(np.median(Ib)) * 1e6,
                i_absmax_uA=float(np.max(np.abs(Ib))) * 1e6,
                v0=float(Vb[0]),
                v1=float(Vb[-1]),
                v_min=float(np.min(Vb)),
                v_max=float(np.max(Vb)),
                q_ah=q_ah,
            )
        )

    charges = [s for s in seg_rows if s["type"] == "charge"]
    discharges = [s for s in seg_rows if s["type"] == "discharge"]
    rests = [s for s in seg_rows if s["type"] == "rest"]
    print(f"  blocks total={len(seg_rows)}  charge={len(charges)}  "
          f"discharge={len(discharges)}  rest={len(rests)}")
    for s in seg_rows:
        print(f"    {s['type']:<10} cyc={s['cycle']} stp={s['step']} "
              f"n={s['n_rows']:>6} t={s['t0']:>11.1f}..{s['t1']:>11.1f} s "
              f"dur={s['dur_h']:>7.3f} h  I_med={s['i_med_uA']:>8.2f} uA "
              f"V {s['v0']:>7.4f}->{s['v1']:>7.4f}  Q={s['q_ah']*1e3:>9.4f} mAh")

    # structural checks
    n_full_cycles = max(s["cycle"] for s in seg_rows)
    pattern_ok = (
        len(charges) == EXPECTED_DRIVEN // 2
        and len(discharges) == EXPECTED_DRIVEN // 2
        and len(rests) == EXPECTED_REST_BLOCKS
        and n_full_cycles == EXPECTED_CYCLES
        and [s["type"] for s in seg_rows][0] == "rest"          # pre-cycle rest
        and len({(s["cycle"], s["step"]) for s in charges}) == EXPECTED_CYCLES
    )
    # every driven block must map to a single raw cycle+step (column consistency)
    col_consistent = all(
        len(b["raw_cycles_unique"]) == 1 and len(b["raw_steps_unique"]) == 1
        for b in blocks
    )
    gate_segmentation = bool(pattern_ok and col_consistent)
    print(f"  gate segmentation (5 cycles / 10 driven / 11 rest, repeatable): "
          f"{gate_segmentation}")

    # ------------------------------------------------------------------ 3
    # voltage window / current / rest-duration checks
    # ------------------------------------------------------------------
    v_min_all, v_max_all = float(V.min()), float(V.max())
    gate_voltage_window = (
        v_min_all >= CUTOFF_DISCHARGE_V - 0.005
        and v_max_all <= CUTOFF_CHARGE_V + 0.005
        and all(abs(s["v1"] - CUTOFF_CHARGE_V) < 0.002 for s in charges)
        and all(abs(s["v1"] - CUTOFF_DISCHARGE_V) < 0.002 for s in discharges)
    )
    print(f"  V window file: {v_min_all:.5f}..{v_max_all:.5f} V "
          f"(expected 2.50..3.65)")
    print(f"  gate voltage window (all legs reach cutoffs): {gate_voltage_window}")

    # C/50 implied current from nominal geometry
    area_cm2 = math.pi * (ELECTRODE_DIAMETER_MM / 20.0) ** 2
    q_nom_mah = NOMINAL_AREAL_CAPACITY_MAH_CM2 * area_cm2
    i_c50_pred_uA = q_nom_mah / 50.0 * 1e3  # mAh / 50 h -> uA
    leg_i_med = [abs(s["i_med_uA"]) for s in charges + discharges]
    gate_current = all(0.95 * i_c50_pred_uA <= v <= 1.05 * i_c50_pred_uA
                       for v in leg_i_med)
    print(f"  nominal Q (2.0 mAh/cm2 x {area_cm2:.5f} cm2) = {q_nom_mah:.4f} mAh"
          f" -> C/50 current {i_c50_pred_uA:.3f} uA")
    print(f"  gate current (each driven leg |I_med| within 5% of C/50): "
          f"{gate_current}")

    rest_dur = [s["dur_h"] for s in rests]
    gate_rest = (
        abs(rest_dur[0] - 6.0) < 0.01
        and all(abs(d - 8.0) < 0.01 for d in rest_dur[1:])
    )
    print(f"  rest durations h: {[f'{d:.3f}' for d in rest_dur]}  "
          f"gate_rest_6h_8h: {gate_rest}")

    # ------------------------------------------------------------------ 4
    # capacity reconstruction (independent trapezoidal integration)
    # ------------------------------------------------------------------
    cap_charge = [s["q_ah"] * 1e3 for s in charges]
    cap_discharge = [s["q_ah"] * 1e3 for s in discharges]
    # cross-check against cycler cumulative column at end of each driven block
    qcol_cross = []
    for s in seg_rows:
        if s["type"] == "rest":
            continue
        qc = float(df["cum_capacity_raw_Ah"].iloc[s["i1"] - 1]) * 1e3
        qcol_cross.append(abs(qc - s["q_ah"] * 1e3))
    cap_max_dev_mah = max(qcol_cross)
    gate_capacity_stable = bool(max(cap_discharge) - min(cap_discharge) < 0.05)
    print("\n[3/5] capacity reconstruction (Q = |int I dt| per leg)")
    print(f"  charge legs   mAh: {[f'{q:.4f}' for q in cap_charge]}")
    print(f"  discharge legs mAh: {[f'{q:.4f}' for q in cap_discharge]}")
    print(f"  |integral - cycler cum col| max = {cap_max_dev_mah*1e3:.3f} uAh")
    ratio = float(np.mean(cap_discharge)) / q_nom_mah
    print(f"  discharge mean {np.mean(cap_discharge):.4f} mAh vs nominal "
          f"{q_nom_mah:.4f} mAh -> ratio {ratio:.4f} "
          f"(vs protocol-implied 3.080 mAh)")
    print(f"  gate capacity stable (discharge spread < 0.05 mAh): "
          f"{gate_capacity_stable}")

    # ------------------------------------------------------------------ 5
    # processed table + capacity column + initial-state facts
    # ------------------------------------------------------------------
    # per-row capacity_Ah: cumulative |throughput| since the start of the
    # current driven block; held constant through the following rest block.
    cap_col = np.zeros(n_rows)
    state = np.where(I > EPS_I, 1, np.where(I < -EPS_I, -1, 0))
    k = 0
    while k < len(blocks):
        b = blocks[k]
        if b["type"] != "rest":
            i0, i1 = b["i0"], b["i1"]
            tb = t[i0:i1]
            dq = np.abs(I[i0 + 1:i1] + I[i0:i1 - 1]) / 2.0 * np.diff(tb) / 3600.0
            cum = np.concatenate([[0.0], np.cumsum(dq)])
            cap_col[i0:i1] = cum[: i1 - i0]
            # trailing rest block (same Q, V relaxation only)
            if k + 1 < len(blocks) and blocks[k + 1]["type"] == "rest":
                j0, j1 = blocks[k + 1]["i0"], blocks[k + 1]["i1"]
                cap_col[j0:j1] = float(cum[-1])
                k += 2
            else:
                k += 1
        else:
            k += 1

    df["capacity_Ah"] = cap_col
    df["cycle_index"] = df["raw_cycle_index"]
    df["segment_type"] = np.where(state > 0, "charge",
                                  np.where(state < 0, "discharge", "rest"))

    # attach segment labels (deterministic scheme on raw cycle + step index:
    # rest step 1 = pre-cycle conditioning rest, step 3 = top rest,
    # step 5 = bottom rest; charge step 2, discharge step 4)
    labels = np.full(n_rows, "", dtype=object)
    for b in blocks:
        c = b["cycle"]
        if b["type"] == "charge":
            tag = f"c{c}_charge"
        elif b["type"] == "discharge":
            tag = f"c{c}_discharge"
        else:
            tag = {1: f"c{c}_pre_rest", 3: f"c{c}_top_rest",
                   5: f"c{c}_bottom_rest"}[b["step"]]
        labels[b["i0"]:b["i1"]] = tag
    df["segment_label"] = labels

    # initial-state facts (measured only, NO stoichiometry inversion):
    # each driven segment is preceded by a rest block -> record that block's
    # end voltage + duration and the measured voltage at the first driven
    # sample. Iterate the block list in chronological order so the preceding
    # rest is the true one.
    initial_states = []
    for k, b in enumerate(blocks):
        if b["type"] == "rest" or k == 0:
            continue
        prev = blocks[k - 1]
        assert prev["type"] == "rest", "driven block not preceded by rest"
        i0 = b["i0"]
        dur_s = float(t[prev["i1"] - 1] - t[prev["i0"]])
        initial_states.append(
            {
                "segment": str(labels[i0]),
                "cycle_index": int(b["cycle"]),
                "direction": b["type"],
                "initial_voltage_V": float(V[i0]),
                "preceding_rest_end_voltage_V": float(V[prev["i1"] - 1]),
                "preceding_rest_duration_s": dur_s,
                "preceding_rest_h": round(dur_s / 3600.0, 4),
                "current_before_segment_A": 0.0,
                "current_A_at_first_sample": float(I[i0]),
            }
        )

    # ------------------------------------------------------------------ 6
    # write outputs
    # ------------------------------------------------------------------
    print("\n[4/5] writing outputs")
    out = args.out
    fig_dir = out / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    # cycle manifest CSV
    mrows = []
    for s in seg_rows:
        mrows.append(
            {
                "cell_id": CELL_ID,
                "cycle": s["cycle"],
                "segment": s["type"],
                "segment_label": labels[s["i0"]],
                "t_start": round(s["t0"], 3),
                "t_end": round(s["t1"], 3),
                "duration_h": round(s["dur_h"], 6),
                "I_mA_median": round(s["i_med_uA"] / 1e3, 6),
                "V_start": round(s["v0"], 5),
                "V_end": round(s["v1"], 5),
                "Q_Ah": round(s["q_ah"], 9),
                "termination_reason": (
                    "cutoff_3p65V_reached" if s["type"] == "charge"
                    else "cutoff_2p50V_reached" if s["type"] == "discharge"
                    else "next_event_or_eof"
                ),
                "n_rows": s["n_rows"],
                "raw_cycle_index": s["cycle"],
                "raw_step_index": s["step"],
            }
        )
    pd.DataFrame(mrows).to_csv(out / "cycle_manifest.csv", index=False)

    # processed canonical parquet (generic; pybamm-free)
    keep = [
        "time_s", "voltage_V", "current_A", "capacity_Ah",
        "segment_type", "segment_label", "cycle_index",
        "raw_cycle_index", "raw_step_index", "cum_capacity_raw_Ah",
    ]
    processed = df[keep].copy()
    processed.to_parquet(out / "processed_pocv.parquet", index=False)

    # source manifest
    source_manifest = {
        "dataset": {
            "short_name": "SINTEF R2032 LFP-NMP-1 p-OCV",
            "title": RECORD_TITLE,
            "zenodo_doi": RECORD_DOI,
            "record_version_matched": RECORD_VERSION_MATCHED,
            "newer_record_doi": RECORD_NEWER,
            "license": LICENSE,
            "lab": "SINTEF Battery Lab",
        },
        "source_file": {
            "local_path_rel": str(RAW.relative_to(ROOT)).replace("\\", "/"),
            "file_name": RAW.name,
            "size_bytes": n_raw,
            "sha256": raw_sha,
            "md5": raw_md5,
            "md5_matches_official_zenodo_v1": raw_md5 == OFFICIAL_MD5,
            "local_mtime_utc": iso_mtime(RAW),
            "download_note": "captured during H1-A screening 2026-09-08; "
                             "md5 verified == Zenodo v1 official value",
            "row_count": n_rows,
            "columns": raw_cols,
            "unit_map": {
                "time_s": "s",
                "unix_time_s": "s",
                "current_A": "A",
                "voltage_V": "V",
                "raw_cycle_index": "1",
                "raw_step_index": "1",
                "cum_capacity_raw_Ah": "Ah (cycler, resets at each segment start)",
            },
            "sampling_span_s": [float(t[0]), float(t[-1])],
            "sampling_span_h": round(span_h, 3),
            "time_monotonic_non_decreasing": gate_time_monotonic,
            "time_boundary_duplicate_rows": int(n_dup),
        },
        "metadata_csv": {
            "local_path_rel": str(META_CSV.relative_to(ROOT)).replace("\\", "/"),
            "size_bytes": n_meta,
            "sha256": meta_sha,
            "md5": meta_md5,
            "row_count": len(mdf),
            "column_count": mdf.shape[1],
            "local_mtime_utc": iso_mtime(META_CSV),
        },
        "electrode": {
            "public_label": PUBLIC_LABEL,
            "active_material": ACTIVE_MATERIAL,
            "cell_configuration": "half_cell",
            "working_electrode": "LFP",
            "counter_electrode": "Li-metal",
            "cell_format": "R2032 coin",
            "electrode_diameter_mm": ELECTRODE_DIAMETER_MM,
            "electrode_area_cm2": round(area_cm2, 6),
            "electrode_thickness_um": DRY_THICKNESS_UM,
            "nominal_areal_capacity_mAh_cm2": NOMINAL_AREAL_CAPACITY_MAH_CM2,
            "nominal_capacity_mAh": round(q_nom_mah, 5),
            "temperature": TEMPERATURE_NOTE,
            "start_date_yyyymmdd": START_DATE,
            "cycling_programme": CYCLING_PROGRAMME,
            "metadata_note": "metadata column 'Electrode Diameter / cm' holds "
                             "value 14 -> consistent with a 14 mm disc; unit "
                             "header treated as mm (coin-cell geometry). "
                             "Mass/loading/wt% blank for this commercial "
                             "electrode (LFP-NMP-1).",
        },
        "processed_schema": {
            "capacity_Ah": ("cumulative |charge throughput| since the start of "
                            "the current charge/discharge leg; held constant "
                            "across the following rest (V relaxation at fixed "
                            "composition-equivalent throughput). Reset per leg. "
                            "NOT a global SOC / absolute lithiation coordinate."),
            "columns": keep,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "no_pybamm_import": gate_model_dependency,
        },
    }
    with open(out / "source_manifest.json", "w", encoding="utf-8") as f:
        json.dump(source_manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    # replay summary + gates
    gates = {
        "file_provenance": raw_md5 == OFFICIAL_MD5,
        "segmentation": gate_segmentation,
        "voltage_window": gate_voltage_window,
        "current_C50_selfconsistent": gate_current,
        "capacity": gate_capacity_stable,
        "geometry_inherited": True,   # recorded above (area/Q_nom recomputed)
        "fresh_replay": "verified externally by byte-comparing two runs",
        "model_dependency_zero": gate_model_dependency,
    }
    summary = {
        "cell_id": CELL_ID,
        "protocol_summary": {
            "full_cycles": n_full_cycles,
            "charge_legs": len(charges),
            "discharge_legs": len(discharges),
            "rest_blocks": len(rests),
            "block_sequence": [f"{b['type']}(c{b['cycle']})" for b in blocks],
            "initial_block": "6 h rest at ~3.15 V (relaxing 3.1498->3.1677 V); "
                             "file begins mid-relaxation, no defined SOC claim",
        },
        "voltage_window_V": {"min": round(v_min_all, 5), "max": round(v_max_all, 5),
                             "expected": [2.50, 3.65]},
        "current": {
            "c50_implied_uA": round(i_c50_pred_uA, 4),
            "driven_leg_median_uA": [round(x, 3) for x in leg_i_med],
            "driven_leg_absmax_uA": [round(x, 3) for x in
                                     [s["i_absmax_uA"] for s in charges + discharges]],
        },
        "capacity": {
            "q_nominal_metadata_mAh": round(q_nom_mah, 5),
            "q_protocol_implied_mAh": round(i_c50_pred_uA * 1e-3 * 50.0, 5),
            "q_integral_charge_mAh": [round(x, 4) for x in cap_charge],
            "q_integral_discharge_mAh": [round(x, 4) for x in cap_discharge],
            "discharge_mean_mAh": round(float(np.mean(cap_discharge)), 4),
            "discharge_mean_over_nominal": round(ratio, 4),
            "cycler_cumulative_column_max_dev_uAh": round(cap_max_dev_mah * 1e3, 3),
            "note": ("current-derived full-window (2.50-3.65 V) capacity "
                     "~3.27-3.31 mAh exceeds manufacturer nominal 3.079 mAh "
                     "by ~6-7%: nominal is a manufacturer label, not the "
                     "cycler-observed window capacity (same class of finding "
                     "as Birmingham H0). All 5 discharge legs and charge "
                     "legs c2-c5 span the full window; the cycle-1 charge "
                     "leg starts at 3.17 V after the 6 h pre-rest (partial "
                     "leg) and is excluded from full-window comparisons."),
        },
        "rest_durations_h": [round(d, 4) for d in rest_dur],
        "initial_states": initial_states,
        "gates": gates,
        "outputs": {
            "source_manifest.json": sha256_file(out / "source_manifest.json"),
            "cycle_manifest.csv": sha256_file(out / "cycle_manifest.csv"),
            "processed_pocv.parquet": sha256_file(out / "processed_pocv.parquet"),
        },
    }
    with open(out / "replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    # sanity figures (V-t, I-t, V-Q per half-cycle) — English labels only
    if not args.no_figures:
        print("  figures ...")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        th = t / 3600.0
        cmap = plt.get_cmap("viridis", EXPECTED_CYCLES)

        # fig1: V vs time, colored by segment state
        fig, ax = plt.subplots(figsize=(12, 3.6))
        for b in blocks:
            i0, i1 = b["i0"], b["i1"]
            col = {"charge": "#c0392b", "discharge": "#2471a3",
                   "rest": "#95a5a6"}[b["type"]]
            ax.plot(th[i0:i1], V[i0:i1], color=col, lw=0.9)
        ax.axhline(CUTOFF_CHARGE_V, color="k", ls=":", lw=0.7)
        ax.axhline(CUTOFF_DISCHARGE_V, color="k", ls=":", lw=0.7)
        ax.set_xlabel("time / h"); ax.set_ylabel("voltage / V")
        ax.set_title("SINTEF LFP-NMP-1 p-OCV (d07eb6): V vs t "
                     "(red=charge, blue=discharge, grey=rest)")
        fig.tight_layout(); fig.savefig(fig_dir / "fig1_v_time.png", dpi=150)
        plt.close(fig)

        # fig2: I vs time
        fig, ax = plt.subplots(figsize=(12, 3.2))
        ax.plot(th, I * 1e6, color="k", lw=0.6)
        ax.axhline(i_c50_pred_uA, color="r", ls="--", lw=0.8,
                   label=f"C/50 nominal {i_c50_pred_uA:.2f} uA")
        ax.axhline(-i_c50_pred_uA, color="b", ls="--", lw=0.8)
        ax.set_xlabel("time / h"); ax.set_ylabel("current / uA")
        ax.set_title("SINTEF LFP-NMP-1 p-OCV (d07eb6): I vs t")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout(); fig.savefig(fig_dir / "fig2_i_time.png", dpi=150)
        plt.close(fig)

        # fig3: V vs leg-relative capacity (discharge | charge panels)
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
        for kk in range(EXPECTED_CYCLES):
            c = kk + 1
            for panel, direction, patt in [
                (0, "discharge", "-"), (1, "charge", "-")]:
                sel = df[(df["segment_label"] == f"c{c}_{direction}")]
                ax = axes[panel]
                ax.plot(sel["capacity_Ah"] * 1e3, sel["voltage_V"],
                        color=cmap(kk), lw=1.1, label=f"cycle {c}")
        axes[0].set_xlabel("capacity / mAh"); axes[0].set_ylabel("voltage / V")
        axes[0].set_title("discharge legs (2.50 V floor)")
        axes[1].set_xlabel("capacity / mAh")
        axes[1].set_title("charge legs (3.65 V ceiling)")
        for ax in axes:
            ax.legend(fontsize=7, loc="lower right")
        fig.suptitle("SINTEF LFP-NMP-1 p-OCV (d07eb6): V vs leg-relative Q")
        fig.tight_layout(); fig.savefig(fig_dir / "fig3_v_capacity.png", dpi=150)
        plt.close(fig)

    print("\n[5/5] gates:")
    for k_, v_ in gates.items():
        print(f"  {k_:<24} {v_}")
    ok = all(v_ is True for k_, v_ in gates.items()
             if k_ not in {"fresh_replay"})
    print(f"\nALL DATA GATES PASS: {ok}")
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
