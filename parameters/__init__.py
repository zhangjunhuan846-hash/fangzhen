# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Top-level ``parameters`` package
#
# Geometry-aware parameter sets for the graphite half-cell line.
# NOT part of battery_sim/ (frozen): this package only READS
# dataset metadata and builds derived parameter dicts; it never
# touches the platform's scientific core.
# ============================================================

from parameters.sintef_graphite_capacity import (  # noqa: F401
    CAPACITY_MATCHED_IDS,
    FROZEN_PARAMETERS,
    build_capacity_matched_variant,
    capacity_payload,
    electrode_capacity_Ah,
    read_q_target,
    register_capacity_variants,
)
from parameters.sintef_graphite_ocp import (  # noqa: F401
    OCP_DELI_ID,
    OCP_LITH_ID,
    OCP_MEAN_ID,
    build_ocp_variant,
    load_ocp_tables,
    register_variants,
    variant_summary,
)
from parameters.sintef_graphite_geometry import (  # noqa: F401
    GEOMETRY_PARAMETER_SET_ID,
    KEPT_PARAMETERS,
    OVERRIDDEN_PARAMETERS,
    build_parameter_values,
    derive_geometry,
    geometry_override,
    read_structure,
    register,
)

__all__ = [
    "CAPACITY_MATCHED_IDS",
    "FROZEN_PARAMETERS",
    "build_capacity_matched_variant",
    "capacity_payload",
    "electrode_capacity_Ah",
    "read_q_target",
    "register_capacity_variants",
    "OCP_DELI_ID",
    "OCP_LITH_ID",
    "OCP_MEAN_ID",
    "build_ocp_variant",
    "load_ocp_tables",
    "register_variants",
    "variant_summary",
    "GEOMETRY_PARAMETER_SET_ID",
    "KEPT_PARAMETERS",
    "OVERRIDDEN_PARAMETERS",
    "build_parameter_values",
    "derive_geometry",
    "geometry_override",
    "read_structure",
    "register",
]
