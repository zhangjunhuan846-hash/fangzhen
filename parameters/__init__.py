# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Top-level ``parameters`` package
#
# Geometry-aware parameter sets for the graphite half-cell line.
# NOT part of battery_sim/ (frozen): this package only READS
# dataset metadata and builds derived parameter dicts; it never
# touches the platform's scientific core.
# ============================================================

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
    "GEOMETRY_PARAMETER_SET_ID",
    "KEPT_PARAMETERS",
    "OVERRIDDEN_PARAMETERS",
    "build_parameter_values",
    "derive_geometry",
    "geometry_override",
    "read_structure",
    "register",
]
