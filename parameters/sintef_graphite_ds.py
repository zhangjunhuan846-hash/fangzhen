# ============================================================
# Battery Dataset Simulation Platform -- graphite line
# Phase B1.1 (integration): derived parameter set
#
#     Ecker2015 reference (diffusivity REPLACED)
#   + SINTEF measured geometry            (Phase A.5)
#   + SINTEF measured OCP, v2 tables      (Phase B0.6, frozen)
#   + SINTEF capacity-matched eps_am      (Phase B0.5)
#   + SINTEF GITT apparent D_s(SOC)       (Phase B1.1, this phase)
#
# Everything except the diffusivity comes from the already-frozen
# phases; this module adds exactly one physical parameter and records
# where its value came from.
#
# WHAT THE DIFFUSIVITY IS
#   An APPARENT / EFFECTIVE solid-state diffusivity extracted from a
#   GITT pulse train under the Weppner-Huggins single-particle model.
#   It is NOT a material constant: it is R^2 divided by a fitted
#   diffusion time constant, so it inherits (a) the reference-set
#   particle radius, (b) the one-particle-size idealisation, (c) the
#   GITT pulse duration and the fitting window, and (d) the OCP slope
#   the model happens to use.  It is registered as an
#   `apparent_ds`-grade parameter and must be reported that way.
#
# INTERPOLATION
#   D spans orders of magnitude, so the function is built as
#   10 ** Interpolant(SOC, log10 D) on the SOC-resolved medians of the
#   ACCEPTED pulses, with the end values held constant outside the
#   tabulated range (a linear extrapolation of log D would be
#   meaningless).
#
# This module imports pybamm lazily; it stays importable for
# provenance work without a solver environment.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from parameters.sintef_graphite_capacity import (
    CAPACITY_MATCHED_IDS,
    build_capacity_matched_pair,
    electrode_capacity_Ah,
)
from parameters.sintef_graphite_geometry import DEFAULT_CELL
from parameters.sintef_graphite_ocp import DEFAULT_OCP_DIR

ROOT = Path(__file__).resolve().parents[1]

KEY_DIFFUSIVITY = "Positive particle diffusivity [m2.s-1]"

DS_PARAMETER_SET_IDS: Dict[str, str] = {
    "lithiation": "sintef_graphite_dsapp_lith_v1",
    "delithiation": "sintef_graphite_dsapp_deli_v1",
}

DEFAULT_DS_DIR = "outputs/analysis/graphite_phaseB1"
DS_GRADE = "apparent_ds_from_GITT_weppner_huggins"


def load_ds_table(
    ds_dir: Path | str = DEFAULT_DS_DIR,
    branch: str = "lithiation",
) -> pd.DataFrame:
    """SOC-resolved apparent D_s(SOC) for one branch."""
    d = Path(ds_dir)
    if not d.is_absolute():
        d = ROOT / d
    path = d / "graphite_Ds_app.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"apparent-D table not found: {path} "
            f"(run the B1.1 extraction first)"
        )
    tab = pd.read_csv(path)
    sub = tab[tab["branch"] == branch].sort_values("SOC")
    if sub.empty:
        raise ValueError(f"{path.name}: no rows for branch '{branch}'")
    sub = sub[np.isfinite(sub["Ds_app_m2_s"]) & (sub["Ds_app_m2_s"] > 0)]
    if len(sub) < 2:
        raise ValueError(
            f"{path.name}: fewer than 2 valid D_s points for '{branch}'"
        )
    return sub.reset_index(drop=True)


def build_diffusivity_function(
    ds_table: pd.DataFrame,
    *,
    hold_ends: bool = True,
):
    """
    Callable D(sto) for PyBaMM, log-interpolated.

    PyBaMM evaluates this at the particle stoichiometry, so the abscissa
    is the SOC axis of the frozen OCP (same definition).
    """
    import pybamm

    soc = ds_table["SOC"].to_numpy(float)
    d = ds_table["Ds_app_m2_s"].to_numpy(float)
    order = np.argsort(soc)
    soc, d = soc[order], d[order]
    keep = np.concatenate(([True], np.diff(soc) > 0))
    soc, d = soc[keep], d[keep]
    if hold_ends:
        if soc[0] > 0.0:
            soc = np.concatenate(([0.0], soc))
            d = np.concatenate(([d[0]], d))
        if soc[-1] < 1.0:
            soc = np.concatenate((soc, [1.0]))
            d = np.concatenate((d, [d[-1]]))
    log_d = np.log10(d)

    def diffusivity(sto, T=None):
        """
        PyBaMM calls the diffusivity with (stoichiometry, temperature)
        when the key it replaces temperature-dependent.  The GITT was
        run at the declared room temperature only, so D(T) is NOT
        characterised here: the temperature argument is accepted and
        IGNORED, and that is recorded in the provenance.
        """
        return 10.0 ** pybamm.Interpolant(soc, log_d, sto)

    diffusivity.__doc__ = (diffusivity.__doc__ or "") + (
        "\nNOTE: no temperature dependence - a single declared RT."
    )
    return diffusivity, soc, d


def build_ds_variant(
    branch: str = "delithiation",
    cell: str = DEFAULT_CELL,
    *,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    ds_dir: Path | str = DEFAULT_DS_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
):
    """
    pybamm.ParameterValues for the graphite line with the GITT-derived
    apparent D_s, everything else taken from the frozen phases.
    """
    import pybamm

    if branch not in DS_PARAMETER_SET_IDS:
        raise ValueError(f"unknown branch '{branch}'")

    base, pv = build_capacity_matched_pair(
        branch, cell, ocp_dir, metadata_csv,
        set_id_suffix=set_id_suffix,
    )
    table = load_ds_table(ds_dir, branch)
    fn, soc, d = build_diffusivity_function(table)
    if KEY_DIFFUSIVITY not in pv:
        raise KeyError(
            f"parameter set has no '{KEY_DIFFUSIVITY}' key; refusing to add "
            f"a parameter the model does not expect"
        )
    pv[KEY_DIFFUSIVITY] = fn
    return base, pv, {"soc": soc, "ds": d, "table": table}


def variant_summary(
    branch: str = "delithiation",
    cell: str = DEFAULT_CELL,
    *,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    ds_dir: Path | str = DEFAULT_DS_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
) -> Dict[str, object]:
    d = Path(ds_dir)
    if not d.is_absolute():
        d = ROOT / d
    prov_path = d / "gitt_ds_app_provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8")) \
        if prov_path.is_file() else {}
    table = load_ds_table(ds_dir, branch)
    return {
        "parameter_set_id": DS_PARAMETER_SET_IDS[branch] + set_id_suffix,
        "branch": branch,
        "base_parameter_set": CAPACITY_MATCHED_IDS[branch] + set_id_suffix,
        "grade": DS_GRADE,
        "quantity": (
            "APPARENT/effective solid-state diffusivity from GITT under "
            "the Weppner-Huggins single-particle model - NOT an intrinsic "
            "material coefficient"
        ),
        "equation_reference": prov.get("equation_reference"),
        "particle_radius_source": prov.get("particle_radius_source"),
        "particle_radius_m": prov.get("particle_radius_m"),
        "Q_th_source": prov.get("Q_th_source"),
        "active_mass_source": prov.get("active_mass_source"),
        "U_prime_source": prov.get("U_prime_source"),
        "ds_soc_points": int(len(table)),
        "ds_cm2_s_range": [
            float(table["Ds_app_cm2_s"].min()),
            float(table["Ds_app_cm2_s"].max()),
        ],
        "ds_cm2_s_median": float(table["Ds_app_cm2_s"].median()),
        "n_accepted_pulses": prov.get("n_accepted"),
        "uncertainty_definition": prov.get("uncertainty_definition"),
        "soc_definition": (
            "same charge-based SOC axis as the frozen OCP, so the "
            "diffusivity and the OCP share one coordinate"
        ),
        "temperature_dependence": (
            "NONE - the GITT was measured at the declared room "
            "temperature, so the function accepts PyBaMM's temperature "
            "argument and ignores it.  Using this set at another "
            "temperature would be an extrapolation."
        ),
        "wording": (
            "apparent D_s from GITT; the calibration is model- and "
            "radius-dependent and the estimate carries a large method "
            "uncertainty - not a material constant, not validation"
        ),
    }


def register_ds_variants(
    cell: str = DEFAULT_CELL,
    *,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    ds_dir: Path | str = DEFAULT_DS_DIR,
    metadata_csv: Optional[Path | str] = None,
    set_id_suffix: str = "",
    branches: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Register the D_s-bearing sets for name lookup in THIS process."""
    import pybamm

    from parameters.sintef_graphite_geometry import _ParameterSetsWithExtra

    branches = branches or ["lithiation", "delithiation"]
    extra: Dict[str, dict] = {}
    for branch in branches:
        _base, pv, _info = build_ds_variant(
            branch, cell, ocp_dir=ocp_dir, ds_dir=ds_dir,
            metadata_csv=metadata_csv, set_id_suffix=set_id_suffix,
        )
        extra[DS_PARAMETER_SET_IDS[branch] + set_id_suffix] = dict(pv)

    current = pybamm.parameter_sets
    if isinstance(current, _ParameterSetsWithExtra):
        current._extra.update(extra)
    else:
        pybamm.parameter_sets = _ParameterSetsWithExtra(current, extra)
    return {b: DS_PARAMETER_SET_IDS[b] + set_id_suffix for b in branches}


def write_variant_summaries(
    out_dir: Path | str = DEFAULT_DS_DIR,
    cell: str = DEFAULT_CELL,
    *,
    ocp_dir: Path | str = DEFAULT_OCP_DIR,
    ds_dir: Path | str = DEFAULT_DS_DIR,
    metadata_csv: Optional[Path | str] = None,
) -> Path:
    d = Path(out_dir)
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "cell": cell,
        "variants": [
            variant_summary(b, cell, ocp_dir=ocp_dir, ds_dir=ds_dir,
                            metadata_csv=metadata_csv)
            for b in ("lithiation", "delithiation")
        ],
        "ecker_ds_function": (
            "Positive particle diffusivity [m2.s-1] of "
            "Ecker2015_graphite_halfcell - the CONTROL for the replay "
            "comparison"
        ),
    }
    path = d / "ds_parameter_variants.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


def ecker_diffusivity_summary() -> Dict[str, object]:
    """The reference (control) diffusivity, evaluated at fixed SOC."""
    import pybamm

    pv = pybamm.ParameterValues("Ecker2015_graphite_halfcell")
    fn = pv[KEY_DIFFUSIVITY]
    socs = [0.05, 0.2, 0.5, 0.8, 0.95]
    vals = {}

    def _eval(node) -> float:
        if hasattr(node, "evaluate"):
            return float(np.asarray(node.evaluate(), dtype=float).reshape(-1)[0])
        return float(node)

    for s in socs:
        try:
            vals[f"{s:.2f}"] = _eval(fn(pybamm.Scalar(s)))
        except TypeError:
            vals[f"{s:.2f}"] = _eval(
                fn(pybamm.Scalar(s), pybamm.Scalar(298.15))
            )
    finite = [v for v in vals.values() if np.isfinite(v) and v > 0]
    return {"values_m2_s": vals, "median_m2_s": float(np.median(finite))
            if finite else float("nan")}
