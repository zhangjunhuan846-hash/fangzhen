# ============================================================
# Battery Dataset Simulation Platform v0.1
# Dataset configuration schema
#
# Validates one entry of configs/datasets.yaml and provides
# typed access to the fields the platform consumes.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_REQUIRED = [
    "name",
    "chemistry",
    "raw_dir",
    "adapter",
    "protocol",
    "parameter_set",
    "cells",
    "rates",
    "supported_models",
]


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    name: str
    ion: str = "Li"
    chemistry: str = ""
    raw_dir: str = ""
    processed_dir: str = ""
    adapter: str = ""
    protocol: str = ""
    parameter_set: str = ""
    cells: List[str] = field(default_factory=list)
    rates: List[str] = field(default_factory=list)
    supported_models: List[str] = field(default_factory=list)
    nominal_capacity_Ah: Optional[float] = None
    lower_voltage_cutoff_V: Optional[float] = None
    upper_voltage_cutoff_V: Optional[float] = None
    raw_file_template: str = "LGM50_cell{cell}.csv"
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, dataset_id: str, raw: Dict[str, Any]) -> "DatasetConfig":
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise ValueError(
                f"datasets.yaml entry '{dataset_id}' missing required "
                f"keys: {missing}"
            )

        extra_keys = set(raw.keys()) - {
            "name",
            "ion",
            "chemistry",
            "raw_dir",
            "processed_dir",
            "adapter",
            "protocol",
            "parameter_set",
            "cells",
            "rates",
            "supported_models",
            "nominal_capacity_Ah",
            "lower_voltage_cutoff_V",
            "upper_voltage_cutoff_V",
            "raw_file_template",
        }

        return cls(
            dataset_id=dataset_id,
            name=str(raw["name"]),
            ion=str(raw.get("ion", "Li")),
            chemistry=str(raw["chemistry"]),
            raw_dir=str(raw["raw_dir"]),
            processed_dir=str(raw.get("processed_dir", "")),
            adapter=str(raw["adapter"]),
            protocol=str(raw["protocol"]),
            parameter_set=str(raw["parameter_set"]),
            cells=[str(c) for c in raw["cells"]],
            rates=[str(r) for r in raw["rates"]],
            supported_models=[str(m) for m in raw["supported_models"]],
            nominal_capacity_Ah=(
                float(raw["nominal_capacity_Ah"])
                if raw.get("nominal_capacity_Ah") is not None
                else None
            ),
            lower_voltage_cutoff_V=(
                float(raw["lower_voltage_cutoff_V"])
                if raw.get("lower_voltage_cutoff_V") is not None
                else None
            ),
            upper_voltage_cutoff_V=(
                float(raw["upper_voltage_cutoff_V"])
                if raw.get("upper_voltage_cutoff_V") is not None
                else None
            ),
            raw_file_template=str(
                raw.get("raw_file_template", "LGM50_cell{cell}.csv")
            ),
            extra={k: raw[k] for k in extra_keys},
        )

    def cell_ids(self) -> List[str]:
        return list(self.cells)

    def rate_ids(self) -> List[str]:
        return list(self.rates)
