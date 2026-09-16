# ============================================================
# Battery Dataset Simulation Platform
# Recorded excitation protocols -- pybamm-free schema
#
# TWO different things in this platform are called a "protocol", and
# confusing them is a real hazard:
#
#   battery_sim/protocols/       command-level ``pybamm.Experiment``
#                                builders: a drive cycle the SIMULATION
#                                is told to follow, closed loop.
#   battery_sim/excitation/      a RECORDED, open-loop excitation: what
#                                the experiment actually applied, as a
#                                sequence of segments (this module).
#
# This module therefore imports NO pybamm.  Dataset adapters are required
# to stay pure data I/O, so the schema an adapter produces has to be
# importable without the simulation stack.
#
# Why the abstraction exists at all
#   The platform now carries three structurally different excitations:
#   a quasi-equilibrium p-OCV sweep, a pulse-relax GITT, and continuous
#   current cycling.  Without a shared description every adapter turns
#   its source format straight into canonical columns, and the
#   differences that MATTER scientifically -- does this protocol excite
#   solid diffusion at all? -- get lost in file-parsing details.  The
#   segment list keeps that question answerable.
#
# Scope: description and selection.  This module says WHAT the excitation
# was and WHICH window is being replayed.  It does not simulate anything.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------
# Segment kinds
#
# Deliberately small.  A segment is a period over which the applied
# current is CONSTANT, which is all the replayed current profile needs
# to know; the ``label`` keeps the source's own wording (e.g. Basytec's
# "Pause" / "Charge" / "Discharge") so nothing is lost.
# ------------------------------------------------------------------
KIND_PULSE = "pulse"                 # current-carrying, short
KIND_REST = "rest"                   # no current
KIND_CONSTANT_CURRENT = "constant_current"
KIND_CONSTANT_VOLTAGE = "constant_voltage"

ALLOWED_KINDS = (
    KIND_PULSE,
    KIND_REST,
    KIND_CONSTANT_CURRENT,
    KIND_CONSTANT_VOLTAGE,
)

#: Kinds that carry current.  A rest must carry exactly zero.
_CURRENT_CARRYING = (KIND_PULSE, KIND_CONSTANT_CURRENT, KIND_CONSTANT_VOLTAGE)


@dataclass(frozen=True)
class Segment:
    """One period of constant applied current inside a recorded protocol.

    Times are relative to the START of the protocol, and the current is
    in the platform canonical convention (DISCHARGE = +), so a segment
    can be written straight into the canonical ``current_A`` column.

    ``row_start`` / ``row_stop`` are half-open indices into the source
    sample table the protocol was built from.  They are carried here
    rather than looked up later so that "which samples belong to this
    segment" is one fact in one place instead of a recomputed guess.
    """

    kind: str
    t_start_s: float
    t_stop_s: float
    current_A: float
    label: str = ""
    voltage_start_V: float = float("nan")
    voltage_end_V: float = float("nan")
    row_start: int = -1
    row_stop: int = -1

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_KINDS:
            raise ValueError(
                f"unknown segment kind {self.kind!r}; "
                f"allowed: {list(ALLOWED_KINDS)}"
            )
        if not self.t_stop_s > self.t_start_s:
            raise ValueError(
                f"segment '{self.label}' has non-positive duration "
                f"({self.t_stop_s - self.t_start_s} s)"
            )
        if self.kind == KIND_REST and float(self.current_A) != 0.0:
            # A rest that carries current is a contradiction, and it is
            # exactly the kind of labelling error that makes an
            # excitation statistic meaningless.  Fail loudly.
            raise ValueError(
                f"segment '{self.label}' is a rest but carries "
                f"{self.current_A} A"
            )
        if self.kind in _CURRENT_CARRYING and float(self.current_A) == 0.0:
            raise ValueError(
                f"segment '{self.label}' is {self.kind!r} but carries "
                f"zero current"
            )

    @property
    def duration_s(self) -> float:
        return self.t_stop_s - self.t_start_s

    @property
    def is_current_carrying(self) -> bool:
        return self.kind in _CURRENT_CARRYING

    @property
    def n_rows(self) -> int:
        if self.row_start < 0 or self.row_stop < 0:
            return 0
        return self.row_stop - self.row_start

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "t_start_s": self.t_start_s,
            "t_stop_s": self.t_stop_s,
            "duration_s": self.duration_s,
            "current_A": self.current_A,
            "voltage_start_V": self.voltage_start_V,
            "voltage_end_V": self.voltage_end_V,
            "row_start": self.row_start,
            "row_stop": self.row_stop,
        }


@dataclass(frozen=True)
class Protocol:
    """A recorded open-loop excitation as a sequence of segments.

    The base class is usable on its own (a plain segment list); the
    subclasses below differ only in the invariants they promise, which
    is what lets a caller say "replay a pulse-relax protocol" and get an
    error if the object is really a cycling log.
    """

    protocol_id: str
    kind: str = "protocol"
    segments: Tuple[Segment, ...] = ()
    temperature_C: float = float("nan")
    source: Dict[str, Any] = field(default_factory=dict)

    # ---- structure -------------------------------------------------
    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.segments)

    @property
    def current_carrying(self) -> Tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.is_current_carrying)

    @property
    def rests(self) -> Tuple[Segment, ...]:
        return tuple(s for s in self.segments if not s.is_current_carrying)

    @property
    def duty_cycle(self) -> float:
        """Fraction of the protocol on current.

        The single most useful excitation statistic for the
        identifiability question: a protocol whose duty cycle is ~0
        cannot excite a transport limitation no matter how long it runs.
        """
        total = self.duration_s
        if total <= 0:
            return float("nan")
        return sum(s.duration_s for s in self.current_carrying) / total

    def describe(self) -> str:
        parts = [
            f"{self.protocol_id} [{self.kind}]",
            f"{len(self.segments)} segments",
            f"{self.duration_s:.1f} s",
            f"duty {self.duty_cycle * 100:.3f} %",
        ]
        if self.temperature_C == self.temperature_C:  # not NaN
            parts.append(f"{self.temperature_C:.2f} C")
        return " | ".join(parts)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "kind": self.kind,
            "n_segments": len(self.segments),
            "duration_s": self.duration_s,
            "duty_cycle": self.duty_cycle,
            "temperature_C": self.temperature_C,
            "segments": [s.as_dict() for s in self.segments],
            "source": dict(self.source),
        }


# ------------------------------------------------------------------
# The four kinds the platform currently needs
# ------------------------------------------------------------------
@dataclass(frozen=True)
class ConstantCurrentProtocol(Protocol):
    """One uninterrupted constant-current period (e.g. a rated discharge)."""

    kind: str = KIND_CONSTANT_CURRENT

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("a constant-current protocol needs >= 1 segment")
        if not all(s.kind == KIND_CONSTANT_CURRENT for s in self.segments):
            raise ValueError(
                "ConstantCurrentProtocol segments must all be "
                f"{KIND_CONSTANT_CURRENT!r}"
            )


@dataclass(frozen=True)
class OCVProtocol(Protocol):
    """A quasi-equilibrium sweep: the current is (near) zero throughout.

    This is the p-OCV case, and its defining property is the one that
    made it useless as a diffusivity probe: almost no duty cycle, so no
    transport limitation is ever established.
    """

    kind: str = "ocv"

    def __post_init__(self) -> None:
        if self.current_carrying:
            raise ValueError(
                "an OCV protocol must not contain current-carrying "
                f"segments (found {len(self.current_carrying)})"
            )


@dataclass(frozen=True)
class CyclingProtocol(Protocol):
    """Continuous-current cycling: long current segments, few rests."""

    kind: str = "cycling"

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("a cycling protocol needs >= 1 segment")


@dataclass(frozen=True)
class PulseRelaxProtocol(Protocol):
    """Alternating short current pulses and long rests (GITT).

    Adds the one operation the activity gate needs: cutting the record
    down to a single ``rest -> pulse -> rest`` triplet, without
    re-deriving anything from the source format.
    """

    kind: str = KIND_PULSE

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("a pulse-relax protocol needs >= 1 segment")
        bad = [s.label for s in self.segments
               if s.kind not in (KIND_PULSE, KIND_REST)]
        if bad:
            raise ValueError(
                "PulseRelaxProtocol segments must be pulse or rest; "
                f"found {bad[:3]}"
            )

    # ---- window selection ------------------------------------------
    def triplets(self) -> Tuple[Tuple[int, int, int], ...]:
        """Indices of every ``(rest, pulse, rest)`` run in the record.

        A triplet is a run, not a fixed stride, so a protocol that
        occasionally logs two rests back to back still yields its
        pulses instead of silently skipping them.
        """
        segs = self.segments
        out: List[Tuple[int, int, int]] = []
        for i, s in enumerate(segs):
            if s.kind != KIND_PULSE:
                continue
            if i == 0 or i + 1 >= len(segs):
                continue
            if segs[i - 1].kind == KIND_REST and segs[i + 1].kind == KIND_REST:
                out.append((i - 1, i, i + 1))
        return tuple(out)

    @property
    def pulse_indices(self) -> Tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.segments)
                     if s.kind == KIND_PULSE)

    def triplet(self, k: int) -> "PulseRelaxProtocol":
        """The k-th ``(rest, pulse, rest)`` triplet as its own protocol.

        Times are REBASED to zero so that the result can be replayed on
        its own; the segment labels and sample row ranges are carried
        through untouched.
        """
        trips = self.triplets()
        if not (0 <= k < len(trips)):
            raise IndexError(
                f"triplet {k} out of range ({len(trips)} available)"
            )
        a, b, c = trips[k]
        chosen = self.segments[a:c + 1]
        t0 = chosen[0].t_start_s
        rebased = tuple(
            Segment(
                kind=s.kind,
                t_start_s=s.t_start_s - t0,
                t_stop_s=s.t_stop_s - t0,
                current_A=s.current_A,
                label=s.label,
                voltage_start_V=s.voltage_start_V,
                voltage_end_V=s.voltage_end_V,
                row_start=s.row_start,
                row_stop=s.row_stop,
            )
            for s in chosen
        )
        return PulseRelaxProtocol(
            protocol_id=f"{self.protocol_id}#t{k}",
            segments=rebased,
            temperature_C=self.temperature_C,
            source=dict(self.source, parent_protocol=self.protocol_id,
                        triplet_index=k),
        )

    def transient_summary(self, k: int) -> Dict[str, float]:
        """Pulse and relaxation amplitudes of triplet ``k``, in mV.

        Reported because they are the pre-registered observable of the
        activity gate: if the model's diffusivity has leverage on the
        window at all, these move.
        """
        trips = self.triplets()
        a, b, c = trips[k]
        pre, pulse, post = (self.segments[a], self.segments[b],
                            self.segments[c])
        return {
            "pulse_duration_s": pulse.duration_s,
            "rest_before_s": pre.duration_s,
            "rest_after_s": post.duration_s,
            "current_A": pulse.current_A,
            "v_pre_V": pre.voltage_end_V,
            "v_pulse_end_V": pulse.voltage_end_V,
            "v_relax_end_V": post.voltage_end_V,
            "dv_pulse_mV": (pulse.voltage_end_V - pre.voltage_end_V) * 1e3,
            "dv_relax_mV": (post.voltage_end_V - pulse.voltage_end_V) * 1e3,
            "v_min_V": pulse.voltage_start_V,
        }


# ------------------------------------------------------------------
# Construction helpers
# ------------------------------------------------------------------
def segments_from_phase_table(
    phases: Sequence[Dict[str, Any]],
    *,
    rest_labels: Sequence[str] = ("Pause",),
    pulse_labels: Sequence[str] = (),
) -> Tuple[Segment, ...]:
    """Build segments from a phase summary produced by a source parser.

    ``phases`` is a list of ``{label, t_start_s, t_stop_s, mean_current_A,
    v_start_V, v_end_V, row_start, row_stop}`` mappings.  The mapping from
    a source's own phase name to a segment kind is DECLARED by the caller
    and recorded in the segment label, so a source that names things
    unusually cannot quietly change the physics.
    """
    segs: List[Segment] = []
    for ph in phases:
        label = str(ph["label"])
        dur = float(ph["t_stop_s"]) - float(ph["t_start_s"])
        if dur <= 0:
            continue
        if label in rest_labels:
            kind = KIND_REST
        elif label in pulse_labels:
            kind = KIND_PULSE
        else:
            kind = KIND_CONSTANT_CURRENT
        segs.append(
            Segment(
                kind=kind,
                t_start_s=float(ph["t_start_s"]),
                t_stop_s=float(ph["t_stop_s"]),
                current_A=float(ph["mean_current_A"]),
                label=label,
                voltage_start_V=float(ph.get("v_start_V", float("nan"))),
                voltage_end_V=float(ph.get("v_end_V", float("nan"))),
                row_start=int(ph.get("row_start", -1)),
                row_stop=int(ph.get("row_stop", -1)),
            )
        )
    return tuple(segs)


__all__ = [
    "ALLOWED_KINDS",
    "ConstantCurrentProtocol",
    "CyclingProtocol",
    "KIND_CONSTANT_CURRENT",
    "KIND_CONSTANT_VOLTAGE",
    "KIND_PULSE",
    "KIND_REST",
    "OCVProtocol",
    "Protocol",
    "PulseRelaxProtocol",
    "Segment",
    "segments_from_phase_table",
]
