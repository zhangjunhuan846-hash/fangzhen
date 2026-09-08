# ============================================================
# Battery Dataset Simulation Platform v0.2
# Canonical rate normalization
#
# Datasets name their discharge rates differently (Chen2020 uses
# "C2" for 0.5C while CALCE writes "0p5C"; "C2" alone is also
# ambiguous -- C/2 vs 2C).  The platform therefore treats the
# NUMERIC C-rate as the true primary key:
#
#     c_rate       float   0.5                  <- machine key
#     rate_label   str     "C/2"                <- human readable
#     rate_slug    str     "C0p5"               <- filenames/paths
#     source_rate  str     "0p5C"               <- provenance
#     legacy_rate  str     "C2"                 <- compat column
#
# Cross-dataset groupby / comparison MUST key on c_rate (never on
# the `rate` string column).  The legacy_rate is kept only so
# existing Chen2020 outputs and golden regressions stay untouched.
# ============================================================

from __future__ import annotations

from typing import Dict, Optional

# Canonical registry, keyed by numeric C-rate.  Extend here when a
# new rate appears in a future dataset.
CANONICAL_RATES: Dict[float, Dict[str, str]] = {
    0.1: {"rate_label": "C/10", "rate_slug": "C0p1", "legacy_rate": "C10"},
    0.2: {"rate_label": "C/5", "rate_slug": "C0p2", "legacy_rate": "C5"},
    0.5: {"rate_label": "C/2", "rate_slug": "C0p5", "legacy_rate": "C2"},
    1.0: {"rate_label": "1C", "rate_slug": "C1", "legacy_rate": "1C"},
    1.5: {"rate_label": "1.5C", "rate_slug": "C1p5", "legacy_rate": "1p5C"},
    2.0: {"rate_label": "2C", "rate_slug": "C2", "legacy_rate": "2C"},
}


def resolve_rate(
    rate,
    source_to_canonical: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Resolve a dataset rate label to the canonical quintuple.

    ``rate`` may be:
      * a canonical slug            e.g. "C0p5"
      * a legacy rate id            e.g. "C2" (Chen2020 compat)
      * a dataset source label      e.g. "0p5C" (via the map)
      * a numeric C-rate string     e.g. "0.5"

    Returns {"c_rate": float, "rate_label": str, "rate_slug": str,
             "source_rate": str, "legacy_rate": str}.
    """
    src_map = dict(source_to_canonical or {})
    s = str(rate).strip()

    # numeric C-rate ("0.5", "1.0", ...)
    try:
        c = float(s)
    except ValueError:
        c = None
    if c is not None:
        for key in CANONICAL_RATES:
            if abs(key - c) < 1e-9:
                return _entry(key, source_rate=s, src_map=src_map)
        raise ValueError(
            f"Numeric rate {c} is not in the canonical registry "
            f"{sorted(CANONICAL_RATES)}"
        )

    # canonical slug / legacy id / human label
    for key, meta in CANONICAL_RATES.items():
        if s in (meta["rate_slug"], meta["legacy_rate"], meta["rate_label"]):
            return _entry(key, source_rate=s, src_map=src_map)

    # dataset source label
    for src, cval in src_map.items():
        if s == src:
            if cval not in CANONICAL_RATES:
                raise ValueError(
                    f"source rate '{s}' maps to c_rate={cval}, which is "
                    f"not in the canonical registry "
                    f"{sorted(CANONICAL_RATES)}"
                )
            return _entry(float(cval), source_rate=s, src_map=src_map)

    raise ValueError(
        f"Unknown rate '{rate}'. Canonical slugs: "
        f"{[m['rate_slug'] for m in CANONICAL_RATES.values()]}; "
        f"known source labels: {sorted(src_map)}"
    )


def _entry(
    c_rate: float,
    source_rate: str,
    src_map: Dict[str, float],
) -> Dict[str, object]:
    """Build the canonical quintuple for a numeric C-rate."""
    meta = CANONICAL_RATES[c_rate]
    # provenance: prefer the dataset's own label if it maps here
    provenance = source_rate
    for src, cval in src_map.items():
        if abs(cval - c_rate) < 1e-9:
            provenance = src
            break
    return {
        "c_rate": float(c_rate),
        "rate_label": meta["rate_label"],
        "rate_slug": meta["rate_slug"],
        "source_rate": provenance,
        "legacy_rate": meta["legacy_rate"],
    }
