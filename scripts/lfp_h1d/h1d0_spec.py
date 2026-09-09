"""H1-D0 shared spec: frozen zero-fit composite definitions + value factories.

Single source of truth shared by build_parameter_lock.py and
run_forward_baseline.py so the lock and the run cannot drift.
No pybamm import at module import time (factories import lazily).

Scientific frame (per H1-D0 launch):
  - D0-A: external-prior forward baseline. SINTEF A0/A1 facts + pre-locked
          B2/C literature priors (incl. external Afshar2017 LFP OCP).
          ZERO tuning against any SINTEF voltage curve.
  - D0-B: branch-aware DIAGNOSTIC baseline (DFN only). Replaces the external
          single-curve OCP with measured charge/discharge branch OCP read from
          the H1-B replay. Data-informed model-structure test, NOT an
          independent prediction.
  - No value below was chosen to reproduce 3.2878 mAh or any SINTEF voltage.
    eps_s x dx stays degenerate (H1-C Tightening 1); eps_s=0.50 is a central
    prior, not a capacity fit (H1-C Tightening 2).
"""
from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "analysis" / "lfp_h1" / "forward_baseline"
DATA_REPLAY_DIR = ROOT / "outputs" / "analysis" / "lfp_h1" / "data_replay"
AUDIT_DIR = ROOT / "outputs" / "analysis" / "lfp_h1" / "parameter_audit"

PARQUET_PATH = DATA_REPLAY_DIR / "processed_pocv.parquet"
FACTS_PATH = AUDIT_DIR / "experimental_facts.json"
PRIOR_BANK_PATH = AUDIT_DIR / "literature_prior_bank.csv"

TEMPLATE_SET = "Jackowska2025_2mAh_cm2"
TEMPLATE_SOURCE = (
    "Jackowska2025_2mAh_cm2 (H0-grade-A exact matched Birmingham NCM920305||Li "
    "half-cell set); used here ONLY as unmatched structural defaults "
    "(separator / electrolyte / Li counter / double-layer / Bruggeman / "
    "inert thermal-chemistry scalars)."
)

# --- model geometry / options -------------------------------------------------
A_M2 = 1.53938e-4          # SINTEF A1 derived disc area (d = 14 mm)
SQRT_A = math.sqrt(A_M2)
THICKNESS_M = 78e-6        # SINTEF A0
C_SMAX = 22820.0           # ae94f3 Table I (~theoretical; 3.60 g/cc, 157.76 g/mol)
NOMINAL_CAP_AH = 3.07876e-3  # SINTEF A0 nominal label (NOT used for closure)

MODEL_OPTIONS = {
    "working electrode": "positive",
    "surface form": "differential",
    "contact resistance": "true",
}
SOLVER = {"rtol": 1e-6, "atol": 1e-6}

# --- D0-A frozen scalar overrides ----------------------------------------------
# each: key, value, role, source_class, source_reference, selection_reason
SCALAR_OVERRIDES = [
    dict(key="Electrode height [m]", value=SQRT_A, role="geometry_A0_A1",
         source_class="A1", source_reference="SINTEF A1 derived (sqrt(A) square footprint)",
         selection_reason="pybamm square-equivalent footprint of the 14 mm disc (H1-B frozen)"),
    dict(key="Electrode width [m]", value=SQRT_A, role="geometry_A0_A1",
         source_class="A1", source_reference="SINTEF A1 derived (sqrt(A) square footprint)",
         selection_reason="pybamm square-equivalent footprint of the 14 mm disc (H1-B frozen)"),
    dict(key="Positive electrode thickness [m]", value=THICKNESS_M, role="geometry_A0",
         source_class="A0", source_reference="SINTEF R2032 LFP-NMP-1 metadata",
         selection_reason="cell geometry fact; no tuning possible/needed"),
    dict(key="Maximum concentration in positive electrode [mol.m-3]",
         value=C_SMAX, role="capacity_axis",
         source_class="B2", source_reference="ae94f3 Table I (equals theoretical rho/M ceiling)",
         selection_reason="prior c_smax; NOT selected to close 3.2878 mAh (H1-C Tightening 1)"),
    dict(key="Positive electrode active material volume fraction", value=0.50,
         role="capacity_axis",
         source_class="C", source_reference="central of band 0.40-0.70 (acfc66/ae94f3/generic)",
         selection_reason="central prior of unresolved (U) active fraction band; "
                          "NOT capacity-tuned; eps_s x dx stays degenerate (H1-C Tightening 1)"),
    dict(key="Positive electrode porosity", value=0.35, role="transport_electrolyte",
         source_class="B2", source_reference="mean(acfc66 0.254, ae94f3 0.45)",
         selection_reason="prior mean of two matched-LFP published porosities"),
    dict(key="Positive particle radius [m]", value=1e-6, role="transport_solid_kinetics",
         source_class="B2", source_reference="acfc66 Table 1 / Sec.2 (FESEM mean, 1 um primary)",
         selection_reason="published matched-LFP FESEM primary particle radius"),
    dict(key="Positive electrode conductivity [S.m-1]", value=1.0,
         role="transport_electronic",
         source_class="C", source_reference="generic carbon-coated LFP composite",
         selection_reason="generic prior; electronic ohmic loss negligible at C/50"),
    dict(key="Initial concentration in electrolyte [mol.m-3]", value=1000.0,
         role="electrolyte_state", source_class="C",
         source_reference="generic 1 M LiPF6 carbonate (prior bank row)",
         selection_reason="SINTEF electrolyte not disclosed -> generic 1 M"),
    dict(key="Contact resistance [Ohm]", value=0.0, role="ohmic_wiring",
         source_class="C", source_reference="H0 wiring default (feature on, value 0)",
         selection_reason="feature enabled as in H0 half-cell wire; value 0: no contact "
                          "loss assumed; at 61.6 uA even tens of Ohm are sub-mV"),
    dict(key="Lower voltage cut-off [V]", value=2.5, role="protocol_A0",
         source_class="A0", source_reference="SINTEF p-OCV programme",
         selection_reason="experimental window fact"),
    dict(key="Upper voltage cut-off [V]", value=3.65, role="protocol_A0",
         source_class="A0", source_reference="SINTEF p-OCV programme",
         selection_reason="experimental window fact"),
    dict(key="Nominal cell capacity [A.h]", value=NOMINAL_CAP_AH, role="inert_label_A0",
         source_class="A0", source_reference="SINTEF metadata",
         selection_reason="manufacturer label; carried for provenance, not used for closure"),
    dict(key="Open-circuit voltage at 0% SOC [V]", value=2.5, role="inert_label",
         source_class="A0", source_reference="SINTEF window",
         selection_reason="label only (unused by half-cell build); kept for provenance"),
    dict(key="Open-circuit voltage at 100% SOC [V]", value=3.65, role="inert_label",
         source_class="A0", source_reference="SINTEF window",
         selection_reason="label only (unused by half-cell build); kept for provenance"),
]

# --- D0-A frozen functional overrides -------------------------------------------
# spec dicts are authoritative: the runner instantiates the pybamm callable from
# these numbers, so the lock fully determines the run.
OCP_SPEC = {
    "key": "Positive electrode OCP [V]",
    "kind": "ocp_afshar_interp",
    "grid_points": 4001,
    "domain": [0.0, 1.0],
    "interpolator": "linear",
    "analytic_source": "LFP_ocp_Afshar2017 from pybamm registered Prada2013 set "
                       "(3.4077 - 0.020269*sto + 0.5*exp(-150*sto) - 0.9*exp(-30*(1-sto)))",
    "role": "ocp_thermodynamics",
    "source_class": "C",
    "source_reference": "Afshar2017 external LFP OCP via pybamm Prada2013 (full-cell "
                        "surrogate chemistry prior; NOT a SINTEF half-cell reference)",
    "selection_reason": "external single-curve OCP required by D0-A (no SINTEF curve "
                        "used); SINTEF two-branch hysteresis (~37.5 mV proxy) NOT represented",
}
J0_SPEC = {
    "key": "Positive electrode exchange-current density [A.m-2]",
    "kind": "j0_const", "value": 50.0,
    "role": "kinetics", "source_class": "B2",
    "source_reference": "ae94f3 Table I (assumed, NOT measured; P2D table value)",
    "selection_reason": "prior j0; high uncertainty flagged; no tuning from SINTEF curve",
}
DS_SPEC = {
    "key": "Positive particle diffusivity [m2.s-1]",
    "kind": "ds_const", "value": 3.7e-16,
    "role": "transport_solid", "source_class": "B2",
    "source_reference": "acfc66 Table 1 (constant D_s from EIS)",
    "selection_reason": "prior constant solid diffusivity; SOC-dependence (ae94f3 GITT) "
                        "flagged but not used in D0",
}
FUNCTION_OVERRIDES = [OCP_SPEC, J0_SPEC, DS_SPEC]

# --- per-leg (run-time) variables ----------------------------------------------
PER_LEG = {
    "Current function [A]": {
        "role": "drive", "source_class": "A1",
        "source_reference": "H1-B replay measured driven-leg median |I| = 61.6 uA",
        "method": "constant current per driven leg; sign = +I for discharge (lithiation, "
                  "V down) and -I for charge (delithiation, V up), H0 half-cell convention "
                  "= flip of cycler sign (cycler discharge negative)",
        "selected_before_forward_run": True,
    },
    "Initial concentration in positive electrode [mol.m-3]": {
        "role": "initial_state", "source_class": "A1+external OCP",
        "source_reference": "measured preceding-rest-end voltage V0 inverted through the "
                            "locked external Afshar OCP",
        "method": "x0 = brentq(U_afshar(x) - V0) on [1e-4, 0.9994]; initial concentration "
                  "= x0*c_smax set before build; conditioning (dU/dx at x0) recorded in "
                  "initialisation_audit.json; plateau dU/dx~0 regions -> "
                  "weakly_determined_from_voltage flag (never a unique-x0 claim)",
        "selected_before_forward_run": True,
    },
}

# D0-B branch-aware reference legs (define measured branch OCP on the frozen
# model capacity axis); reference legs are excluded from independent D0-B metrics.
D0B_REFERENCE_LEGS = {"charge": "c2_charge", "discharge": "c1_discharge"}

LEG_KEYS_ALLOWED = {"Current function [A]", "Initial concentration in positive electrode [mol.m-3]"}

# deterministic json helpers ----------------------------------------------------
def canonical_json_bytes(obj) -> bytes:
    import json
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return s.encode("utf-8")


def sha256_of(obj) -> str:
    import hashlib
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def json_default(o):
    """JSON-encode template values that may be numpy scalars or callables."""
    import numpy as np
    if isinstance(o, bool):
        return o
    if isinstance(o, (int, float, str)) or o is None:
        return o
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if callable(o):
        return {"<function>": getattr(o, "__name__", "anonymous")}
    return {"<type>": type(o).__name__, "repr": str(o)}
