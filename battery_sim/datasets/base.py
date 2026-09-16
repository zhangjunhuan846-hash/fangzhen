# ============================================================
# Battery Dataset Simulation Platform v0.1
# Dataset adapter interface
#
# A dataset adapter knows how to read one experimental dataset
# (raw + processed files) and expose the pieces the simulation
# platform needs. Adapters must NOT import pybamm: they stay
# pure data I/O so new datasets can be added without touching
# the pybamm-facing layers.
# ============================================================

from __future__ import annotations

from typing import Dict

import pandas as pd

from battery_sim.rates import resolve_rate


class BatteryDatasetAdapter:
    """
    Interface for a battery experimental dataset.

    Subclasses receive their DatasetConfig at construction and
    resolve paths relative to the project root.
    """

    # Dataset source rate labels that differ from the canonical
    # C-rate (see battery_sim/rates.py).  Maps source label ->
    # numeric c_rate, e.g. {"0p5C": 0.5}.  Subclasses override;
    # empty by default.
    SOURCE_TO_CANONICAL: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def get_metadata(self) -> dict:
        """Dataset-level metadata (name, chemistry, ion, ...)."""
        raise NotImplementedError

    def list_cells(self):
        """List of cell ids, e.g. ['02', '03', '04']."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Raw data access
    # ------------------------------------------------------------------
    def load_raw(self, cell) -> pd.DataFrame:
        """
        Load the full raw record for a cell as a DataFrame with
        columns already normalised (signed current etc.).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Discharge extraction
    # ------------------------------------------------------------------
    def load_discharge(self, cell, rate) -> pd.DataFrame:
        """
        One formal validation discharge as a DataFrame.

        Required columns: time_s, current_A, voltage_V, capacity_Ah.
        Times are relative to the discharge start.
        """
        raise NotImplementedError

    def list_rates(self):
        """Available rate ids for this dataset."""
        raise NotImplementedError

    def rate_info(self, rate) -> Dict[str, object]:
        """
        Canonical rate quintuple for ``rate`` (slug, legacy id,
        source label or numeric string): {"c_rate", "rate_label",
        "rate_slug", "source_rate", "legacy_rate"}.
        """
        return resolve_rate(rate, self.SOURCE_TO_CANONICAL)

    def list_rate_slugs(self):
        """Canonical rate_slugs for this dataset (file naming)."""
        return [str(self.rate_info(r)["rate_slug"]) for r in self.list_rates()]

    # ------------------------------------------------------------------
    # Initial / environmental state used by simulations
    # ------------------------------------------------------------------
    def get_initial_state(self, cell):
        """
        Initial state for the simulation. Convention: return the
        measured open-circuit voltage in volts (float).
        """
        raise NotImplementedError

    def get_ambient_temperature(self, cell) -> float:
        """Ambient temperature in degrees Celsius."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Recorded-protocol capability (OPTIONAL, additive)
    #
    # A dataset whose source is a RECORDED open-loop excitation -- a
    # pulse-relax GITT, a quasi-equilibrium p-OCV sweep, a cycling log --
    # can describe it with the schema in ``battery_sim.excitation``
    # instead of flattening it into canonical columns immediately.  The
    # reason to bother is that the DIFFERENCES that matter scientifically
    # (does this protocol excite solid diffusion at all?) then survive as
    # data rather than being lost in file-parsing details.
    #
    # Nothing in the core calls these, and the defaults below keep every
    # existing adapter working untouched.  A dataset that has no such
    # source simply leaves them alone.
    # ------------------------------------------------------------------
    def list_protocols(self):
        """Protocol ids this dataset can replay ([] when unsupported)."""
        return []

    def load_protocol(self, protocol_id):
        """Resolve ``protocol_id`` to a ``battery_sim.excitation.Protocol``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose recorded protocols"
        )

    def load_processed_protocol(self, cell, protocol_id):
        """Canonical columns for one recorded-protocol window."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose recorded protocols"
        )
