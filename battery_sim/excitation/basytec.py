# ============================================================
# Battery Dataset Simulation Platform
# Basytec text-export reader -- pybamm-free
#
# Reads the phase-log export used by DLR's battery test systems and
# turns it into the recorded-protocol schema in
# ``battery_sim.excitation.protocol``.
#
# Three things about this format are not obvious and all three have
# already caused trouble:
#
#   1. THE FILE IS LATIN-1, not UTF-8.  The header carries a degree sign
#      in "T1[degC]" and a UTF-8 decoder stops at byte 0xb0.
#
#   2. THE PHASE COMES FROM THE ``Command`` COLUMN, not from step
#      numbering.  Every row states whether the cell was on Charge,
#      Discharge or Pause, so the segmentation is DECLARED BY THE DATA
#      and nothing has to be inferred.  (This is exactly what the SINTEF
#      bdf export does not give you -- see docs/g6.1a_gitt_protocol_audit.md,
#      where grouping by (cycle, step) produced physically impossible
#      segments because the file interleaves channels.)
#
#   3. THE SIGN IS BASYTEC'S: negative current is discharge.  The
#      platform canonical convention is DISCHARGE = POSITIVE, so every
#      current is flipped here, once, at the boundary.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from battery_sim.excitation.protocol import (
    ConstantCurrentProtocol,
    CyclingProtocol,
    KIND_PULSE,
    KIND_REST,
    Protocol,
    PulseRelaxProtocol,
    Segment,
    segments_from_phase_table,
)

#: Column names, in order, of the Basytec "Resultfile" export.
BASYTEC_COLUMNS = (
    "Time_h",
    "DataSet",
    "t_Set_h",
    "Line",
    "Command",
    "U_V",
    "I_A",
    "Ah_per_kg",
    "Ah_Charge",
    "Ah_Discharge",
    "Ah_Step",
    "Ah_Step_per_kg",
    "Ah_Set",
    "Ah_Set_per_kg",
    "T1_C",
    "Cyc_Count",
    "State",
)

#: The source's own phase names, mapped to what they mean physically.
#: Kept explicit because a source that renames a phase must not be able
#: to silently change the segmentation.
REST_COMMANDS = ("Pause",)
CHARGE_COMMANDS = ("Charge",)
DISCHARGE_COMMANDS = ("Discharge",)

#: A pulse-relax protocol is recognised when pulses are at most this
#: long AND the median rest is at least this many times longer.  The
#: thresholds are declared rather than tuned: a continuous-current
#: sweep must NOT be filed as pulse-relax, because the activity gate
#: then reports a capability that the excitation never had.
PULSE_MAX_S = 3600.0
REST_OVER_PULSE_MIN = 3.0


@dataclass
class BasytecLog:
    """One Basytec export, parsed and normalised."""

    path: Path
    header: Dict[str, str]
    frame: pd.DataFrame          # canonical columns, t from record start
    phases: pd.DataFrame         # one row per phase
    protocol: Protocol

    @property
    def n_rows(self) -> int:
        return int(len(self.frame))

    def window_frame(self, protocol: Protocol) -> pd.DataFrame:
        """Materialise a (sub)protocol as canonical columns, t from 0.

        Slices by the segment row ranges recorded when the protocol was
        built, so a window cannot drift away from the segmentation it
        came from.
        """
        segs = [s for s in protocol.segments if s.row_start >= 0]
        if not segs:
            raise ValueError(
                f"protocol '{protocol.protocol_id}' carries no row ranges"
            )
        i0 = min(s.row_start for s in segs)
        i1 = max(s.row_stop for s in segs)
        sub = self.frame.iloc[i0:i1].copy()

        # The measured current is the model input, so it is taken from
        # the SOURCE samples rather than from the segment's mean: a
        # segment mean would flatten the very transient the protocol
        # exists to provide.  Any residual disagreement is surfaced as a
        # provenance field instead of being hidden.
        t = sub["time_s"].to_numpy(float)
        t = t - t[0]

        out = pd.DataFrame(
            {
                "time_s": t,
                "current_A": sub["current_A"].to_numpy(float),
                "voltage_V": sub["voltage_V"].to_numpy(float),
                "capacity_Ah": _cumulative_charge_Ah(
                    t, sub["current_A"].to_numpy(float)
                ),
                "temperature_ambient_C": sub["temperature_C"].to_numpy(float),
            }
        )
        out.attrs["protocol"] = protocol.as_dict()
        out.attrs["initial_soc"] = float("nan")
        return out


def _cumulative_charge_Ah(t_s: np.ndarray, current_A: np.ndarray) -> np.ndarray:
    """Trapezoidal integral of the canonical current, in Ah.

    Signed by the canonical current, i.e. positive while discharging --
    the platform-wide convention.  An offset is appended so the array
    matches the sample count exactly even when time repeats.
    """
    if len(t_s) < 2:
        return np.zeros(len(t_s), dtype=float)
    dt = np.diff(t_s)
    im = 0.5 * (current_A[1:] + current_A[:-1])
    inc = im * dt
    return np.concatenate(([0.0], np.cumsum(inc))) / 3600.0


def _read_header(path: Path, max_lines: int = 40) -> Dict[str, str]:
    """The ``~Name: value`` comment block at the top of the export."""
    header: Dict[str, str] = {}
    with path.open("r", encoding="latin-1") as fh:
        for _ in range(max_lines):
            line = fh.readline()
            if not line:
                break
            line = line.strip()
            if not line.startswith("~"):
                break
            body = line.lstrip("~").strip()
            if ":" in body:
                k, v = body.split(":", 1)
                header[k.strip()] = v.strip()
    return header


def read_basytec(path: Path, *, protocol_id: Optional[str] = None) -> BasytecLog:
    """Parse a Basytec export into canonical samples + a Protocol."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such Basytec export: {path}")

    df = pd.read_csv(
        path,
        comment="~",
        sep=r"\s+",
        names=list(BASYTEC_COLUMNS),
        header=None,
        engine="python",
        encoding="latin-1",
    )
    missing = [c for c in BASYTEC_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    t_s = df["Time_h"].astype(float).to_numpy() * 3600.0
    label = df["Command"].astype(str).to_numpy()
    u_v = df["U_V"].astype(float).to_numpy()
    i_raw = df["I_A"].astype(float).to_numpy()
    t_c = df["T1_C"].astype(float).to_numpy()

    # CONVENTION FIX, once, at the boundary.  Basytec: negative = discharge.
    # Platform canonical: discharge = +.  Verified in-data by the contract
    # test that requires current > 0 to coincide with falling voltage.
    current_A = -i_raw

    frame = pd.DataFrame(
        {
            "time_s": t_s - float(t_s[0]) if len(t_s) else t_s,
            "label": label,
            "current_A": current_A,
            "voltage_V": u_v,
            "temperature_C": t_c,
        }
    )

    phases = _phase_table(frame)
    protocol = _build_protocol(
        phases, frame, protocol_id=protocol_id or path.stem
    )

    header = _read_header(path)
    header["_file"] = path.name
    header["_n_rows"] = str(len(frame))
    header["_sign_convention"] = (
        "Basytec raw current negated once: raw negative = discharge -> "
        "platform canonical discharge = +"
    )

    return BasytecLog(path=path, header=header, frame=frame,
                      phases=phases, protocol=protocol)


def _phase_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per contiguous run of the same ``Command``.

    Runs are detected on the label sequence, so a repeated phase name
    that appears twice yields two phases rather than being merged.
    """
    lab = frame["label"].to_numpy()
    n = len(frame)
    if n == 0:
        return pd.DataFrame()

    brk = np.r_[0, np.flatnonzero(lab[1:] != lab[:-1]) + 1, n]
    rows: List[Dict[str, Any]] = []
    for i in range(len(brk) - 1):
        a, b = int(brk[i]), int(brk[i + 1])
        sub = frame.iloc[a:b]
        tt = sub["time_s"].to_numpy(float)
        rows.append(
            {
                "label": str(sub["label"].iloc[0]),
                "row_start": a,
                "row_stop": b,
                "n_rows": b - a,
                "t_start_s": float(tt[0]),
                "t_stop_s": float(tt[-1]),
                "duration_s": float(tt[-1] - tt[0]),
                "mean_current_A": float(
                    sub["current_A"].to_numpy(float).mean()
                ),
                "v_start_V": float(sub["voltage_V"].iloc[0]),
                "v_end_V": float(sub["voltage_V"].iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


def _build_protocol(
    phases: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    protocol_id: str,
) -> Protocol:
    """Classify the record and build the matching Protocol subclass.

    The classification is deliberately conservative: anything that is
    not measurably pulse-relax is reported as continuous current or
    cycling, because mis-filing a slow sweep as pulse-relax would let
    the activity gate claim an excitation the data does not provide.
    """
    if phases.empty:
        raise ValueError(f"{protocol_id}: no phases found")

    temp_median = float(np.nanmedian(frame["temperature_C"].to_numpy(float)))
    source = {
        "protocol_id": protocol_id,
        "n_phases": int(len(phases)),
        "phase_labels": sorted(set(phases["label"].astype(str))),
        "duty_cycle": _duty_cycle(phases),
    }

    segs = segments_from_phase_table(
        phases.to_dict("records"),
        rest_labels=REST_COMMANDS,
        pulse_labels=(),
    )

    # a pulse-relax record must actually alternate
    pulses = [s for s in segs if s.kind != KIND_REST]
    rests = [s for s in segs if s.kind == KIND_REST]
    if not pulses:
        return CyclingProtocol(
            protocol_id=protocol_id,
            segments=segs,
            temperature_C=temp_median,
            source=dict(source, classified_as="no_current_phases"),
        )

    durations = np.array([s.duration_s for s in pulses], dtype=float)
    rest_med = float(np.median([s.duration_s for s in rests])) if rests else 0.0
    pulse_med = float(np.median(durations))
    alternates = _alternates(segs)

    is_pulse_relax = (
        alternates
        and pulse_med <= PULSE_MAX_S
        and rest_med >= REST_OVER_PULSE_MIN * pulse_med
    )

    if is_pulse_relax:
        # the current-carrying phases are short relative to the rests, so
        # they are pulses rather than a continuous sweep
        relabelled = tuple(
            Segment(
                kind=KIND_PULSE if s.kind != KIND_REST else KIND_REST,
                t_start_s=s.t_start_s,
                t_stop_s=s.t_stop_s,
                current_A=s.current_A,
                label=s.label,
                voltage_start_V=s.voltage_start_V,
                voltage_end_V=s.voltage_end_V,
                row_start=s.row_start,
                row_stop=s.row_stop,
            )
            for s in segs
        )
        source = dict(
            source,
            classified_as="pulse_relax",
            pulse_duration_median_s=pulse_med,
            rest_duration_median_s=rest_med,
        )
        return PulseRelaxProtocol(
            protocol_id=protocol_id,
            segments=relabelled,
            temperature_C=temp_median,
            source=source,
        )

    if len(pulses) == 1:
        return ConstantCurrentProtocol(
            protocol_id=protocol_id,
            segments=tuple(
                Segment(
                    kind="constant_current",
                    t_start_s=s.t_start_s,
                    t_stop_s=s.t_stop_s,
                    current_A=s.current_A,
                    label=s.label,
                    voltage_start_V=s.voltage_start_V,
                    voltage_end_V=s.voltage_end_V,
                    row_start=s.row_start,
                    row_stop=s.row_stop,
                )
                for s in segs
            ),
            temperature_C=temp_median,
            source=dict(source, classified_as="constant_current"),
        )

    return CyclingProtocol(
        protocol_id=protocol_id,
        segments=segs,
        temperature_C=temp_median,
        source=dict(
            source,
            classified_as="cycling",
            pulse_duration_median_s=pulse_med,
            rest_duration_median_s=rest_med,
            alternates=alternates,
        ),
    )


def _duty_cycle(phases: pd.DataFrame) -> float:
    total = float(phases["duration_s"].sum())
    if total <= 0:
        return float("nan")
    on = phases[phases["label"].isin(
        list(CHARGE_COMMANDS) + list(DISCHARGE_COMMANDS)
    )]
    return float(on["duration_s"].sum()) / total


def _alternates(segs: tuple) -> bool:
    """True when current and rest phases genuinely alternate.

    A single long charge followed by a single long rest is NOT
    alternation, and must not be read as a pulse train.
    """
    kinds = [s.kind == KIND_REST for s in segs]
    switches = sum(1 for a, b in zip(kinds, kinds[1:]) if a != b)
    return switches >= max(3, len(kinds) // 4)


__all__ = [
    "BASYTEC_COLUMNS",
    "BasytecLog",
    "CHARGE_COMMANDS",
    "DISCHARGE_COMMANDS",
    "PULSE_MAX_S",
    "REST_COMMANDS",
    "REST_OVER_PULSE_MIN",
    "read_basytec",
]
