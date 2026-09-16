# ============================================================
# Battery Dataset Simulation Platform
# DLR Hydra.0b Li||graphite GITT adapter (Basytec text export)
#
# WHY THIS DATASET EXISTS IN THE PLATFORM
#   The SINTEF graphite line has NO diffusion-limited protocol: its
#   p-OCV is C/50 quasi-equilibrium, and its "gitt"/"gitthold" files
#   turned out to be C/44 CC-CV with three interleaved logging channels
#   rather than a pulse train (docs/g6.1a_gitt_protocol_audit.md).  So
#   the activity gate for a function-valued diffusivity had no positive
#   control.  This file is the one real GITT on disk: 240 discharge and
#   238 charge pulses of ~150 s against rests of thousands of seconds.
#
# WHAT THIS ADAPTER IS FOR
#   Replaying a pulse-relax window, so that "does the model respond to
#   D_s(x) at all?" can be asked.  It is NOT a validation of any
#   parameter set: the cell is a different cell, from a different
#   laboratory, with a different electrode and OCP.
#
#   dataset_role: benchmark  -- evaluation only, must never be used to
#   calibrate a parameter set.  Calling anything here "validation"
#   would be wrong (see governance/dataset_roles.py).
#
# PURE DATA I/O: this module imports no pybamm.  The recorded-protocol
# schema and the parsing live in battery_sim.excitation.
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.datasets.ocp_lookup import inverse_ocp, load_ocp_curve
from battery_sim.excitation import (
    PulseRelaxProtocol,
    Protocol,
    read_basytec,
)
from battery_sim.paths import ROOT

#: The canonical column set every adapter must return.
CANONICAL_COLUMNS = (
    "time_s",
    "current_A",
    "voltage_V",
    "capacity_Ah",
    "temperature_ambient_C",
)

#: Tail of the pre-pulse rest whose median is taken as the rest OCV the
#: replay is initialised from.  Long enough to be past relaxation, short
#: enough not to drag in the previous pulse's recovery.
REST_TAIL_S = 60.0

SWEEP_DISCHARGE = "discharge"
SWEEP_CHARGE = "charge"


class DlrGittAdapter(BatteryDatasetAdapter):
    """Basytec GITT log -> canonical replay windows."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        extra = dict(config.extra or {})
        self._extra = extra

        raw_dir = ROOT / str(config.raw_dir)
        file_name = str(extra.get("raw_file") or "").strip()
        if not file_name:
            raise ValueError(
                f"dataset '{config.dataset_id}': extra.raw_file is required "
                f"(the Basytec export file name inside {config.raw_dir})"
            )
        self._raw_file = raw_dir / file_name
        if not self._raw_file.exists():
            raise FileNotFoundError(
                f"dataset '{config.dataset_id}': no such raw file "
                f"{self._raw_file}"
            )

        ocp_rel = str(extra.get("initialisation_ocp_file_rel") or "").strip()
        if not ocp_rel:
            raise ValueError(
                f"dataset '{config.dataset_id}': "
                f"extra.initialisation_ocp_file_rel is required"
            )
        self._ocp_file = ROOT / ocp_rel
        if not self._ocp_file.exists():
            raise FileNotFoundError(
                f"dataset '{config.dataset_id}': no OCP table {self._ocp_file}"
            )

        self._log = None                 # lazy: ~315k rows
        self._ocp_curve = None
        self._triplets: Optional[pd.DataFrame] = None

        # declared window, resolved against the loaded record
        self._default_sweep = str(
            extra.get("default_sweep") or SWEEP_DISCHARGE
        ).strip()
        self._default_triplet = extra.get("default_triplet")
        self._default_v_target = extra.get("default_v_target_V")

        rates_meta = extra.get("rates_meta")
        if not isinstance(rates_meta, dict) or not rates_meta:
            raise ValueError(
                f"dataset '{config.dataset_id}': missing rates_meta block"
            )
        self._rate_table: Dict[str, dict] = {
            str(k): dict(v) for k, v in rates_meta.items()
        }

    # ------------------------------------------------------------------
    # Lazy source access
    # ------------------------------------------------------------------
    @property
    def log(self):
        if self._log is None:
            self._log = read_basytec(self._raw_file,
                                     protocol_id=self.config.dataset_id)
        return self._log

    def _load_ocp(self):
        if self._ocp_curve is None:
            self._ocp_curve = load_ocp_curve(self._ocp_file)
        return self._ocp_curve

    # ------------------------------------------------------------------
    # Metadata / cells / rates
    # ------------------------------------------------------------------
    def get_metadata(self) -> dict:
        cfg = self.config
        log = self.log
        return {
            "dataset_id": cfg.dataset_id,
            "name": cfg.name,
            "ion": cfg.ion,
            "chemistry": cfg.chemistry,
            "dataset_role": (cfg.extra or {}).get("dataset_role"),
            "cells": list(self.list_cells()),
            "rates": list(self.list_rates()),
            "config_protocol": cfg.protocol,
            "source_file": self._raw_file.name,
            "source_header": dict(log.header),
            "protocol_class": log.protocol.kind,
        }

    def list_cells(self) -> List[str]:
        declared = self.config.extra.get("cell_ids")
        if declared:
            return [str(c) for c in declared]
        return ["Hydra.0b_A"]

    def list_rates(self) -> List[str]:
        return [str(r) for r in self.config.rates]

    def rate_info(self, rate) -> Dict[str, object]:
        s = str(rate).strip()
        if s not in self._rate_table:
            # numeric c-rate lookup, as the other adapter does
            try:
                c = float(s)
            except ValueError:
                c = None
            if c is not None:
                for rid, meta in self._rate_table.items():
                    if abs(float(meta["c_rate"]) - c) < 1e-9:
                        s = rid
                        break
            if s not in self._rate_table:
                raise ValueError(
                    f"Unknown rate '{rate}' for dataset "
                    f"'{self.config.dataset_id}'. Known: "
                    f"{sorted(self._rate_table)}"
                )
        meta = self._rate_table[s]
        return {
            "c_rate": float(meta["c_rate"]),
            "rate_label": str(meta["rate_label"]),
            "rate_slug": str(meta["rate_slug"]),
            "source_rate": str(meta.get("source_rate", s)),
            "legacy_rate": str(meta.get("legacy_rate", s)),
        }

    def list_rate_slugs(self) -> List[str]:
        return [str(self.rate_info(r)["rate_slug"]) for r in self.list_rates()]

    # ------------------------------------------------------------------
    # Triplet index (the unit the activity gate works in)
    # ------------------------------------------------------------------
    def triplets(self) -> pd.DataFrame:
        """One row per (rest, pulse, rest) triplet in the record."""
        if self._triplets is not None:
            return self._triplets
        proto = self.log.protocol
        if not isinstance(proto, PulseRelaxProtocol):
            raise TypeError(
                f"dataset '{self.config.dataset_id}': the source was "
                f"classified as {proto.kind!r}, not pulse-relax; there "
                f"are no triplets to index"
            )
        rows = []
        trips = proto.triplets()
        for k in range(len(trips)):
            s = proto.transient_summary(k)
            rows.append(
                {
                    "triplet": k,
                    "sweep": (SWEEP_DISCHARGE if s["current_A"] > 0
                              else SWEEP_CHARGE),
                    "t_pulse_start_s": float(
                        proto.segments[trips[k][1]].t_start_s
                    ),
                    "pulse_s": float(s["pulse_duration_s"]),
                    "rest_before_s": float(s["rest_before_s"]),
                    "rest_after_s": float(s["rest_after_s"]),
                    "current_A": float(s["current_A"]),
                    "v_pre_V": float(s["v_pre_V"]),
                    "dv_pulse_mV": float(s["dv_pulse_mV"]),
                    "dv_relax_mV": float(s["dv_relax_mV"]),
                }
            )
        df = pd.DataFrame(rows)
        self._triplets = df
        return df

    def list_protocols(self) -> List[str]:
        """Sweep-level protocol ids available on this dataset."""
        return [f"GITT-{SWEEP_DISCHARGE}", f"GITT-{SWEEP_CHARGE}"]

    def list_triplets(self, sweep: str = SWEEP_DISCHARGE) -> List[str]:
        t = self.triplets()
        sel = t[t["sweep"] == str(sweep)]
        return [f"GITT-{sweep}#t{int(k)}" for k in sel["triplet"]]

    def find_triplet(self, sweep: str, v_target_V: float) -> str:
        """The triplet of ``sweep`` whose pre-pulse voltage is closest.

        Selecting by a stated voltage rather than by triplet index keeps
        the choice reviewable: it names the STATE the window probes, not
        a position in a file.
        """
        t = self.triplets()
        sel = t[t["sweep"] == str(sweep)]
        if sel.empty:
            raise ValueError(
                f"dataset '{self.config.dataset_id}': no {sweep} triplets"
            )
        k = int((sel["v_pre_V"] - float(v_target_V)).abs().idxmin())
        return f"GITT-{sweep}#t{int(t.loc[k, 'triplet'])}"

    def default_protocol_id(self) -> str:
        """The dataset's declared canonical window."""
        if self._default_triplet is not None:
            return f"GITT-{self._default_sweep}#t{int(self._default_triplet)}"
        if self._default_v_target is not None:
            return self.find_triplet(self._default_sweep,
                                     float(self._default_v_target))
        t = self.triplets()
        sel = t[t["sweep"] == self._default_sweep]
        if sel.empty:
            raise ValueError(
                f"dataset '{self.config.dataset_id}': no "
                f"{self._default_sweep} triplets; declare "
                f"extra.default_sweep / default_triplet / default_v_target_V"
            )
        return f"GITT-{self._default_sweep}#t{int(sel['triplet'].iloc[0])}"

    def capacity_reference_protocol(self) -> Optional[str]:
        """Which protocol's recorded charge represents the CELL's capacity.

        A single pulse-rest triplet passes only its own pulse, so its
        charge is NOT the cell capacity.  The sweep is.  Declared in
        configs/datasets.yaml rather than assumed, because using the
        triplet would scale the model down by ~7400x and drive it into the
        voltage cut-off -- which looks like "the parameter is inert".
        """
        v = (self.config.extra or {}).get("capacity_reference_protocol")
        return str(v) if v else None

    # ------------------------------------------------------------------
    # Protocol resolution
    # ------------------------------------------------------------------
    def load_protocol(self, protocol_id: str) -> Protocol:
        """Resolve a protocol id to a Protocol object.

        Accepted forms
          ``GITT-discharge`` / ``GITT-charge``   the whole sweep
          ``GITT-discharge#t120``                one pulse-rest triplet
        """
        pid = str(protocol_id).strip()
        if "#t" in pid:
            head, _, k_str = pid.partition("#t")
            sweep = head[len("GITT-"):] if head.startswith("GITT-") else head
            try:
                k = int(k_str)
            except ValueError:
                raise ValueError(
                    f"protocol id '{protocol_id}': '#t' must be followed "
                    f"by a triplet index"
                ) from None
            proto = self.log.protocol
            if not isinstance(proto, PulseRelaxProtocol):
                raise TypeError(
                    f"dataset '{self.config.dataset_id}': source is "
                    f"{proto.kind!r}, not pulse-relax"
                )
            t = self.triplets()
            row = t[t["triplet"] == k]
            if row.empty:
                raise ValueError(
                    f"dataset '{self.config.dataset_id}': no triplet {k} "
                    f"({len(t)} available)"
                )
            actual = str(row["sweep"].iloc[0])
            if sweep and sweep != actual:
                raise ValueError(
                    f"triplet {k} belongs to sweep '{actual}', "
                    f"not '{sweep}'"
                )
            return proto.triplet(k)

        if pid.startswith("GITT-"):
            sweep = pid[len("GITT-"):]
            return self._sweep_protocol(sweep)
        raise ValueError(
            f"unrecognised protocol id '{protocol_id}' for dataset "
            f"'{self.config.dataset_id}'"
        )

    def _sweep_protocol(self, sweep: str) -> PulseRelaxProtocol:
        """The whole sweep as its own pulse-relax protocol.

        Note this can be very large (12.7 days of record), and the
        platform's replay path decimates to 2000 points, which would
        smear the pulses.  Replaying a sweep verbatim is therefore NOT
        the recommended path -- it is offered so the object exists and
        can be inspected, and the gate uses triplets.
        """
        proto = self.log.protocol
        if not isinstance(proto, PulseRelaxProtocol):
            raise TypeError(
                f"dataset '{self.config.dataset_id}': source is "
                f"{proto.kind!r}, not pulse-relax"
            )
        trips = proto.triplets()
        table = self.triplets()
        keep = sorted(int(k) for k in
                      table[table["sweep"] == str(sweep)]["triplet"])
        if not keep:
            raise ValueError(f"no {sweep} triplets on this dataset")

        # A sweep is a contiguous run of triplets in this record, so the
        # segment ranges of its first and last triplet bound it exactly.
        # Verified rather than assumed: a non-contiguous sweep would mean
        # the sign interleaves, and slicing would then silently include
        # the opposite direction.
        idx: List[int] = []
        for k in keep:
            idx.extend(trips[k])
        lo, hi = min(idx), max(idx)
        if sorted(set(idx)) != list(range(lo, hi + 1)):
            raise ValueError(
                f"sweep '{sweep}' is not contiguous in the record; "
                f"refusing to slice it"
            )
        chosen = proto.segments[lo:hi + 1]
        current_signs = {s.current_A > 0 for s in chosen if s.current_A}
        if len(current_signs) > 1:
            raise ValueError(
                f"sweep '{sweep}' slice mixes current directions"
            )
        return PulseRelaxProtocol(
            protocol_id=f"GITT-{sweep}",
            segments=chosen,
            temperature_C=proto.temperature_C,
            source=dict(proto.source, sweep=sweep, n_segments=len(chosen),
                        n_triplets=len(keep)),
        )

    # ------------------------------------------------------------------
    # Canonical windows
    # ------------------------------------------------------------------
    def load_processed_protocol(self, cell: str, protocol_id: str) -> pd.DataFrame:
        """Canonical columns for one protocol window, plus provenance."""
        cell = str(cell)
        if cell not in [str(c) for c in self.list_cells()]:
            raise ValueError(
                f"unknown cell '{cell}' for {self.config.dataset_id}; "
                f"expected one of {self.list_cells()}"
            )
        protocol = self.load_protocol(protocol_id)
        frame = self.log.window_frame(protocol)
        out = frame[list(CANONICAL_COLUMNS)].reset_index(drop=True)

        out.attrs["provenance"] = self._provenance(cell, protocol, out)
        out.attrs["initialisation"] = self._initialisation(protocol, out)
        out.attrs["protocol"] = protocol.as_dict()
        return out

    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        """The dataset's declared canonical window for ``rate``.

        A ``rate`` here is a replay WINDOW, not a C-rate: the pulse level
        happens to be constant across the record, so what distinguishes
        one window from another is which part of the sweep it probes.
        """
        info = self.rate_info(rate)
        pid = self._rate_table[str(rate)].get("protocol_id")
        if pid is None:
            pid = self.default_protocol_id()
        out = self.load_processed_protocol(cell, str(pid))
        prov = out.attrs["provenance"]
        prov["rate_selection"] = {
            "rate": str(rate),
            "rate_label": info["rate_label"],
            "protocol_id": str(pid),
            "note": (
                "a 'rate' on this dataset selects a REPLAY WINDOW "
                "(a pulse-relax triplet); the pulse current is constant "
                "across the record, so the c_rate is a property of the "
                "pulse, not of the window choice"
            ),
        }
        return out

    def load_raw(self, cell: str) -> pd.DataFrame:
        cell = str(cell)
        if cell not in [str(c) for c in self.list_cells()]:
            raise ValueError(f"unknown cell '{cell}'")
        return self.log.frame.copy()

    # ------------------------------------------------------------------
    # Initial / environmental state
    # ------------------------------------------------------------------
    def _rest_ocv(self, protocol: Protocol, out: pd.DataFrame) -> float:
        """Median of the pre-pulse rest tail, in volts."""
        if not protocol.segments:
            raise ValueError("protocol has no segments")
        pre = protocol.segments[0]
        # rows of the FIRST segment (the pre-pulse rest), relative to
        # the window frame that was just materialised
        t = out["time_s"].to_numpy(float)
        tail = t <= (pre.duration_s - REST_TAIL_S)
        sel = ~tail if tail.all() else tail
        if not sel.any():
            sel = np.ones_like(t, dtype=bool)
        return float(np.median(out["voltage_V"].to_numpy(float)[sel]))

    def _initialisation(self, protocol: Protocol, out: pd.DataFrame) -> dict:
        sto, vv = self._load_ocp()
        v0 = self._rest_ocv(protocol, out)
        edge_fallback = False
        try:
            x0 = inverse_ocp(sto, vv, v0)
        except ValueError:
            # a cell far outside the reference table: start at the
            # nearest edge and FLAG it rather than pretending
            x0 = float(np.min(sto)) if v0 > float(np.max(vv)) else \
                float(np.max(sto))
            edge_fallback = True
        return {
            "method": "fixed_initial_concentration",
            "ocp_voltage_V": v0,
            "stoichiometry_from_ocp": x0,
            "concentration_parameter": (
                "Initial concentration in positive electrode [mol.m-3]"
            ),
            "max_concentration_parameter": (
                "Maximum concentration in positive electrode [mol.m-3]"
            ),
            "mapping_reason": (
                "graphite occupies the positive electrode slot of "
                "Ecker2015_graphite_halfcell (audited); initial Li "
                f"fraction x0 = {x0:.4f} from the measured pre-pulse "
                f"rest OCV {v0:.4f} V"
            ),
            "ocp_table_edge_fallback": edge_fallback,
        }

    def get_initial_state(self, cell) -> float:
        pid = self.default_protocol_id()
        out = self.load_processed_protocol(str(cell), pid)
        return float(np.median(out["voltage_V"].to_numpy(float)))

    def get_ambient_temperature(self, cell) -> float:
        t = self.log.frame["temperature_C"].to_numpy(float)
        return float(np.nanmedian(t))

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------
    def _provenance(self, cell: str, protocol: Protocol,
                    out: pd.DataFrame) -> dict:
        h = self.log.header
        t = out["time_s"].to_numpy(float)
        I = out["current_A"].to_numpy(float)
        V = out["voltage_V"].to_numpy(float)
        on = np.abs(I) > 0.0
        return {
            "source_file": self._raw_file.name,
            "source_dataset": (
                "DLR (German Aerospace Center) Hydra.0b Li||graphite, "
                "GITT-OCV testplan; Basytec result-file export"
            ),
            "source_header": dict(h),
            "protocol_id": protocol.protocol_id,
            "protocol_kind": protocol.kind,
            "classification": protocol.source.get("classified_as"),
            "identification": (
                "rule-based, from the file's own Command column "
                "(Pause/Charge/Discharge); nothing inferred from step "
                "numbering or from a step index"
            ),
            "segmentation": [s.as_dict() for s in protocol.segments],
            "duty_cycle": protocol.duty_cycle,
            "sign_convention": {
                "raw": "Basytec: negative current = discharge",
                "platform_canonical": "discharge = +, charge = -",
                "action": "raw current NEGATED once, at parse time",
                "verified_from_data": (
                    "canonical positive current coincides with FALLING "
                    "voltage, which for graphite is lithiation and is "
                    "the spontaneous (discharge) direction of a "
                    "graphite||Li cell"
                ),
                "model_check": (
                    "with graphite in the PyBaMM POSITIVE slot a "
                    "positive current inserts Li and drives V down"
                ),
            },
            "unit_conversion": {
                "time_s": "raw 'Time[h]' x 3600; rebased to the window start",
                "current_A": "raw 'I[A]' negated to the canonical sign",
                "voltage_V": "raw 'U[V]' used as-is",
                "capacity_Ah": (
                    "trapezoidal integral of the CANONICAL current"
                ),
                "temperature_ambient_C": (
                    "raw 'T1[degC]' MEASURED channel -- this dataset has "
                    "one, unlike the SINTEF half-cell export"
                ),
            },
            "measured_temperature_C": {
                "min": float(np.nanmin(out["temperature_ambient_C"])),
                "max": float(np.nanmax(out["temperature_ambient_C"])),
                "median": float(np.nanmedian(out["temperature_ambient_C"])),
            },
            "c_rate": float(self.rate_info(self.list_rates()[0])["c_rate"]),
            "c_rate_basis": (
                "declared in configs/datasets.yaml; derived from the "
                "MEASURED charge passed in the sweep's pulses, not from a "
                "datasheet capacity (no datasheet was available)"
            ),
            "n_points": int(len(out)),
            "duration_s": float(t[-1] - t[0]) if len(t) else 0.0,
            "rows_on_current": int(on.sum()),
            "current_A": {
                "min": float(I.min()) if len(I) else None,
                "max": float(I.max()) if len(I) else None,
            },
            "voltage_V": {
                "start": float(V[0]) if len(V) else None,
                "end": float(V[-1]) if len(V) else None,
                "min": float(V.min()) if len(V) else None,
                "max": float(V.max()) if len(V) else None,
            },
            "cell_id": cell,
            "known_difference_from_sintef_line": (
                "different cell, different laboratory, different "
                "electrode preparation and OCP; replaying an "
                "Ecker2015-parameterised model against this record is a "
                "CAPABILITY demonstration, not a validation of that "
                "parameter set"
            ),
        }


__all__ = [
    "CANONICAL_COLUMNS",
    "DlrGittAdapter",
    "REST_TAIL_S",
    "SWEEP_CHARGE",
    "SWEEP_DISCHARGE",
]
