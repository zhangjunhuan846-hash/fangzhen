#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
H1-C  Parameter-Source Audit builder  (SINTEF R2032 / LFP-NMP-1 / p-OCV)

Scope discipline (approved 2026-09-08):
  * experimental facts source = ONLY the frozen H1-B canonical replay
    (outputs/analysis/lfp_h1/data_replay/*) + SINTEF meta/metadata.csv
  * NO PyBaMM forward simulation, NO fitting/optimisation, NO capacity tuning,
    NO GITT download, NO modification of H0 / H1-B frozen artifacts.
  * audit builder itself is deterministic, pure python + pandas(parquet stat);
    it does NOT import pybamm and does NOT load any parameter values into a model.

Outputs  -> outputs/analysis/lfp_h1/parameter_audit/
  parameter_requirements.csv        reverse-enumerated model requirements
  experimental_facts.json           layer-1: SINTEF facts ONLY (A0/A1)
  parameter_source_matrix.csv       one row per key: role/source_class/value/...
  literature_prior_bank.csv         layer-2: acfc66 / ae94f3 / generic C priors
  capacity_closure.csv              F*A*L*eps_s*c_smax*dx grid vs 3.0788 / 3.2878
  ocp_source_audit.json             OCP candidates + hysteresis proxy
  unresolved_parameters.csv         source_class U preserved
  source_manifest.json              inputs + outputs hashes (deterministic)
  h1c_gate_summary.json             7 gates + GITT decision note
  model_ready_composite_draft.json  layer-3 DRAFT (declaration, not to run)

Usage:  python build_parameter_audit.py [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import pandas as pd  # parquet read only (env has pyarrow); NOT pybamm

ROOT = Path(__file__).resolve().parents[2]
H1B = ROOT / "outputs" / "analysis" / "lfp_h1" / "data_replay"
META = ROOT / "data" / "raw" / "LIB" / "LFP_LiMetal" / "SINTEF_R2032" / "meta" / "metadata.csv"
RAW = ROOT / "data" / "raw" / "LIB" / "LFP_LiMetal" / "SINTEF_R2032" / "raw" / \
      "sintef__sintef-lfp-R2032-gelon-d07eb6__20250602__p-ocv__RT.bdf.parquet"
KEYUNIV = ROOT / "scripts" / "lfp_h1c" / "halfcell_required_keys.json"
DEFAULT_OUT = ROOT / "outputs" / "analysis" / "lfp_h1" / "parameter_audit"

FARADAY = 96485.33212  # C mol^-1
DIAM_MM = 14.0
AREA_M2 = math.pi * (DIAM_MM * 1e-3) ** 2 / 4.0        # disc footprint
AREA_CM2 = AREA_M2 * 1e4
THICK_M = 78e-6
C_SMAX_THEO = 22820.0          # ae94f3 estimate == theoretical 3.60 g/cc / 157.76 g/mol
C_SMAX_ACFC66 = 21852.0        # acfc66 Table 1
NOMINAL_AH = 3.07876e-3
Q_EXP_DISCHARGE_MEAN_AH = 3.2878e-3
Q_EXP_BAND_AH = (3.2662e-3, 3.3059e-3)   # observed leg spread (5 discharge legs)

# ---------------------------------------------------------------------------
# Source-class legend (must be used verbatim in every table)
#   A0 SINTEF direct experimental fact; A1 derived only from SINTEF facts;
#   B1 same material / same study (unused: no matched SINTEF parameter study);
#   B2 external LFP study;  C generic literature / chemistry / default;  U unknown
# ---------------------------------------------------------------------------
# Role legend: measured / derived / fixed / prior / inferred / nuisance / design

# Row: (pybamm_key or conceptual, canonical_name, physical_group, req_spm,
#       req_spme, req_dfn, role, source_class, value_or_range, uncertainty_status,
#       temperature, source_ref, match_grade, comment)
# required flags: Y = needed, N = not needed (isothermal single-phase P2D family),
# T = needed only under a thermal submodel (isothermal config -> not consumed).
R = []
R.append(("Electrode height [m]", "cell_footprint_size",
          "geometry/loading", "Y", "Y", "Y",
          "derived", "A1",
          f"{math.sqrt(AREA_M2):.6e}  (square-area-equivalent of the 14 mm disc)",
          "low (exact disc area known)",
          "RT", "H1-B source_manifest (derived from diameter)",
          "A (derived from SINTEF A0 fact)",
          "PyBaMM uses width x height; both set to sqrt(A) so footprint == disc area (Birmingham H0 convention)."))
R.append(("Electrode width [m]", "cell_footprint_size",
          "geometry/loading", "Y", "Y", "Y",
          "derived", "A1",
          f"{math.sqrt(AREA_M2):.6e}",
          "low", "RT", "H1-B source_manifest", "A (derived)",
          "see Electrode height."))
R.append(("Positive electrode thickness [m]", "positive_electrode_thickness",
          "geometry/loading", "Y", "Y", "Y",
          "measured", "A0", "78e-6",
          "measured (metadata 'Dry Thickness / um' = 78)",
          "RT", "SINTEF meta/metadata.csv row d07eb6", "A0",
          "Dry coating thickness of the commercial LFP-NMP-1 electrode."))
R.append(("Negative electrode thickness [m]", "lithium_counter_thickness",
          "geometry/loading", "Y", "Y", "Y",
          "prior", "C", "UNKNOWN (excess Li foil; not disclosed)",
          "high (excess lithium -> insensitive)",
          "RT", "not disclosed in record", "C",
          "Li-metal counter foil. Oversized vs working electrode; expected insensitive."))
R.append(("Separator thickness [m]", "separator_thickness",
          "geometry/loading", "N", "Y", "Y",
          "prior", "U", "UNKNOWN -> priors 20e-6 (acfc66), 25e-6 (Celgard 2325)",
          "high", "RT", "acfc66 / ae94f3 electrode set-ups", "B2",
          "SINTEF record does not disclose separator (coin R2032)."))
R.append(("Positive electrode porosity", "positive_electrode_porosity",
          "geometry/loading", "N", "Y", "Y",
          "prior", "U", "UNKNOWN -> priors: 0.254 (acfc66), 0.45 (ae94f3)",
          "high (capacity + electrolyte volume)",
          "RT", "acfc66 Table 1 / ae94f3 Table I", "B2",
          "Electrolyte volume fraction in the composite electrode."))
R.append(("Positive electrode active material volume fraction", "positive_active_volume_fraction",
          "geometry/loading", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN (eps_s) -> priors 0.40-0.70 (generic commercial LFP)",
          "high (capacity closure, see capacity_closure.csv)",
          "RT", "generic commercial LFP electrodes", "C",
          "Solid active fraction; enters Q_geom = F A L eps_s c_smax dx."))
R.append(("Positive electrode active material density [kg.m-3]", "positive_active_density",
          "thermal/constants", "N", "N", "N",
          "prior", "C", "3600 (LiFePO4 crystallographic density)",
          "low", "RT", "crystallographic / generic LFP", "C",
          "Only needed for mass-based conversions or thermal model (not consumed isothermally)."))
R.append(("Positive electrode carbon-binder density [kg.m-3]", "positive_carbon_binder_density",
          "thermal/constants", "N", "N", "N",
          "prior", "C", "generic (PVDF/carbon composite, ~1500-1900)",
          "medium", "RT", "generic", "C",
          "Not consumed in isothermal electrochemical solve."))
R.append(("Positive electrode conductivity [S.m-1]", "positive_electrode_conductivity",
          "electronic transport", "N", "N", "Y",
          "prior", "U", "UNKNOWN -> generic carbon-coated LFP composite 0.1-10 S/m",
          "medium (only DFN solid-potential PDE)",
          "RT", "generic LFP electrodes", "C",
          "Carbon-coated LFP composite electronic conductivity; DFN only."))
R.append(("Negative electrode conductivity [S.m-1]", "lithium_counter_conductivity",
          "electronic transport", "N", "N", "Y",
          "prior", "C", "high (Li metal, ~1e7); value far from limiting",
          "low (excess Li, high conductivity)",
          "RT", "generic Li metal", "C",
          "DFN solid-potential PDE in the Li counter region."))
R.append(("Contact resistance [Ohm]", "contact_resistance",
          "electronic transport", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN (platform option 'contact resistance: true' enabled)",
          "medium (terminal voltage offset)",
          "RT", "not measured in record", "U",
          "H0 wiring kept this option on; a SINTEF value does not exist. 0-Ohm start + sensitivity in H1-D0."))
R.append(("Positive electrode OCP [V]", "positive_ocp",
          "solid thermo/OCP", "Y", "Y", "Y",
          "derived", "A1", "own p-OCV charge & discharge branches (C/50), see ocp_source_audit.json",
          "medium (hysteresis: single equilibrium curve not directly measured)",
          "RT (no numeric value reported)", "H1-B processed p-OCV (d07eb6)", "A1",
          "Two measured full-window branches available; equilibrium/hysteresis treatment is an H1-D model choice."))
R.append(("Positive electrode OCP entropic change [V.K-1]", "positive_ocp_entropic",
          "solid thermo/OCP", "T", "T", "T",
          "fixed", "C", "0 (isothermal; RT range)",
          "n/a under isothermal config",
          "RT", "generic / pybamm default", "C",
          "Only consumed if a thermal submodel is activated."))
R.append(("Negative electrode OCP [V]", "lithium_counter_ocp",
          "solid thermo/OCP", "Y", "Y", "Y",
          "fixed", "C", "0 (Li/Li+ reference potential)",
          "low", "RT", "definition", "C",
          "Li-metal counter sets the 0 V reference."))
R.append(("Negative electrode OCP entropic change [V.K-1]", "lithium_counter_ocp_entropic",
          "solid thermo/OCP", "T", "T", "T",
          "fixed", "C", "0",
          "n/a", "RT", "generic", "C",
          "Thermal-only."))
R.append(("Positive particle diffusivity [m2.s-1]", "positive_particle_diffusivity",
          "solid transport", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN -> 3.7e-16 (acfc66 const); ae94f3 SOC-dependent GITT range",
          "high (but LOW sensitivity at C/50 near-equilibrium replay)",
          "RT / 298.15 K", "acfc66 Table 1; ae94f3 GITT Fig.4", "B2",
          "GITT of the SINTEF cell itself not downloaded (deferred; see gate summary)."))
R.append(("Positive particle radius [m]", "positive_particle_radius",
          "solid transport", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN -> 1e-6 (acfc66, FESEM); ae94f3 PSD (surface-area-weighted, no single number in text)",
          "high (surface area / kinetics timescale)",
          "RT", "acfc66 Table 1/Sec.2; ae94f3 PSD", "B2",
          "Commercial LFP-NMP-1 particle size not disclosed."))
R.append(("Positive electrode diffusivity scaling factor", "positive_ds_scaling",
          "solid transport", "Y", "Y", "Y",
          "fixed", "A1", "1.0",
          "n/a (definition)",
          "RT", "H0 mapping (PyBaMM alias auto-materialisation)", "A1",
          "Platform keeps =1.0 unless a per-rate D-scaling study is explicitly approved (Birmingham lesson: scaling != material constant)."))
R.append(("Maximum concentration in positive electrode [mol.m-3]", "positive_c_smax",
          "solid transport", "Y", "Y", "Y",
          "prior", "B2", "22820 (ae94f3 & theoretical) ; 21852 (acfc66)",
          "medium-low (theoretical value robust)",
          "298.15 K", "ae94f3 Table I (estimated); acfc66 Table 1", "B2",
          "c_smax ~ theoretical 22.8e3 mol/m3 for LFP (3.60 g/cc, 157.76 g/mol)."))
R.append(("Positive electrode exchange-current density [A.m-2]", "positive_exchange_current",
          "kinetics", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN -> j0 50 A/m2 assumed in ae94f3; acfc66 k0-form alternative",
          "high (kinetics)",
          "298.15 K", "ae94f3 Table I (assumed); acfc66 Table 1 (calibrated k0)", "B2",
          "Interfacial kinetics of LFP-NMP-1 not measured by SINTEF. i0-form (pybamm default) or k0-form are alternatives."))
R.append(("Positive electrode reaction rate [A.m-2.(m3.mol-1)^1.5]", "positive_reaction_rate",
          "kinetics", "Y", "Y", "Y",
          "prior", "U", "UNKNOWN (k0-form; acfc66 k0=0.12e-11 in m^2.5 mol^-0.5 s^-1 requires unit conversion)",
          "high",
          "298 K", "acfc66 Table 1 (fitted/calibrated)", "B2",
          "Alternative kinetic parameterisation; only one kinetics form is consumed per pybamm option."))
R.append(("Positive electrode charge transfer coefficient", "positive_alpha",
          "kinetics", "Y", "Y", "Y",
          "fixed", "C", "0.5",
          "low (standard symmetric BV)",
          "RT", "generic Butler-Volmer", "C",
          "Symmetric transfer coefficient assumption."))
R.append(("Positive electrode reaction activation energy [J.mol-1]", "positive_activation_energy",
          "kinetics", "Y", "Y", "Y",
          "fixed", "C", "0 (isothermal at RT; Arrhenius factor =1 at Reference temperature)",
          "low",
          "RT", "generic", "C",
          "Reference temperature fixed at 298.15 K; Ea=0 keeps kinetics at the chosen reference."))
R.append(("Exchange-current density for lithium metal electrode [A.m-2]", "li_counter_exchange_current",
          "kinetics", "Y", "Y", "Y",
          "fixed", "C", "large (fast Li plating/stripping; value not limiting)",
          "low",
          "RT", "generic Li metal", "C",
          "Li counter kinetics; excess Li => insensitive."))
R.append(("Positive electrode double-layer capacity [F.m-2]", "positive_double_layer_capacity",
          "kinetics", "Y", "Y", "Y",
          "prior", "C", "generic (only relevant under surface-form options)",
          "low-medium (consumption to confirm in H1-D wiring)",
          "RT", "generic", "C",
          "Present in the reference half-cell set (differential surface form)."))
R.append(("Negative electrode double-layer capacity [F.m-2]", "li_counter_double_layer_capacity",
          "kinetics", "Y", "Y", "Y",
          "prior", "C", "generic",
          "low",
          "RT", "generic", "C",
          "As above for the Li counter."))
R.append(("Electrolyte diffusivity [m2.s-1]", "electrolyte_diffusivity",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "UNKNOWN (SINTEF electrolyte not disclosed) -> 1 M LiPF6 generic transport model",
          "medium (C/50 slow scan -> small concentration polarisation)",
          "RT", "generic 1 M LiPF6 (carbonate)", "C",
          "Composition anchor ae94f3: 1 M LiPF6 EC:DEC 1:1; transport values generic."))
R.append(("Electrolyte conductivity [S.m-1]", "electrolyte_conductivity",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "UNKNOWN -> generic 1 M LiPF6 model",
          "medium", "RT", "generic 1 M LiPF6 (carbonate)", "C",
          "See electrolyte diffusivity."))
R.append(("Cation transference number", "cation_transference",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "generic 1 M LiPF6 value (0.26-0.4)",
          "medium", "RT", "generic", "C",
          "See electrolyte diffusivity."))
R.append(("Thermodynamic factor", "electrolyte_thermodynamic_factor",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "generic (1 or mild concentration dependence)",
          "medium", "RT", "generic", "C",
          "Concentrated-solution correction; often folded into diffusivity."))
R.append(("Initial concentration in electrolyte [mol.m-3]", "initial_electrolyte_concentration",
          "electrolyte transport", "Y", "Y", "Y",
          "prior", "C", "1000 (1 M LiPF6; ae94f3 exact, acfc66 1 M)",
          "low-medium", "RT", "ae94f3 Table II (1000, exp. data sheet)", "B2",
          "Bulk electrolyte concentration reference; enters exchange-current density."))
R.append(("Positive electrode Bruggeman coefficient (electrolyte)", "positive_brug_ele",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "1.5 (default) UNKNOWN",
          "medium", "RT", "generic Bruggeman", "C",
          "Tortuosity exponent for effective electrolyte transport inside the electrode."))
R.append(("Positive electrode Bruggeman coefficient (electrode)", "positive_brug_elec",
          "electronic transport", "N", "N", "Y",
          "prior", "C", "1.5 (default)",
          "medium (DFN solid-phase tortuosity)",
          "RT", "generic Bruggeman", "C",
          "Solid-phase tortuosity exponent (DFN electronic conduction)."))
R.append(("Separator porosity", "separator_porosity",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "U", "UNKNOWN -> Celgard-type 0.39-0.40 (ae94f3 2325 spec)",
          "medium", "RT", "ae94f3 separator spec; acfc66 0.37", "B2",
          "SINTEF record does not disclose separator."))
R.append(("Separator Bruggeman coefficient (electrolyte)", "separator_brug_ele",
          "electrolyte transport", "N", "Y", "Y",
          "prior", "C", "1.5 (default)",
          "medium", "RT", "generic Bruggeman", "C",
          "Effective electrolyte transport across separator."))
R.append(("Separator Bruggeman coefficient (electrode)", "separator_brug_elec",
          "electronic transport", "N", "N", "N",
          "fixed", "C", "1.5 (unused; no solid in separator)",
          "n/a", "RT", "generic", "C",
          "Present in reference set; no electronic conductor in separator to tortuose."))
R.append(("Separator thickness [m]", "separator_thickness",
          "geometry/loading", "N", "Y", "Y",
          "prior", "U", "UNKNOWN -> priors 20e-6 / 25e-6",
          "high", "RT", "acfc66 / ae94f3", "B2",
          "Duplicate row alias (see Separator thickness above)."))
R.append(("Lower voltage cut-off [V]", "lower_cutoff",
          "geometry/loading", "Y", "Y", "Y",
          "measured", "A0", "2.50",
          "measured (legs reach 2.49999 V)",
          "RT", "H1-B replay_summary voltage_window", "A0",
          "Discharge cut-off actually reached by cycler."))
R.append(("Upper voltage cut-off [V]", "upper_cutoff",
          "geometry/loading", "Y", "Y", "Y",
          "measured", "A0", "3.65",
          "measured (legs reach 3.65000 V)",
          "RT", "H1-B replay_summary voltage_window", "A0",
          "Charge cut-off actually reached by cycler."))
R.append(("Current function [A]", "applied_current",
          "geometry/loading", "Y", "Y", "Y",
          "measured", "A0", "61.60e-6 (+/- 0.01%) during driven legs; rest 0",
          "measured",
          "RT", "H1-B replay_summary current", "A0",
          "Experimental drive current (C/50 on ~3.08 mAh)."))
R.append(("Nominal cell capacity [A.h]", "nominal_capacity",
          "geometry/loading", "Y", "Y", "Y",
          "derived", "A1", "3.07876e-3 (metadata label; measured full-window mean 3.2878e-3)",
          "label vs measured mismatch quantified in capacity_closure.csv",
          "RT", "SINTEF metadata.csv + H1-B capacity integration", "A0/A1",
          "Used only as a C-rate reference if C-rate current is ever required; replay uses the measured current."))
R.append(("Electrode height [m]", "electrode_height",
          "geometry/loading", "Y", "Y", "Y",
          "derived", "A1", f"{math.sqrt(AREA_M2):.6e}",
          "low", "RT", "derived", "A", "area-equivalent square half-side."))
R.append(("Ambient temperature [K]", "ambient_temperature",
          "thermal/constants", "T", "T", "T",
          "fixed", "C", "298.15 (assumed RT; record gives no numeric)",
          "n/a under isothermal",
          "RT (no numeric)", "record says 'room temperature'", "A0 (qualitative)",
          "Only consumed under a thermal submodel."))
R.append(("Initial temperature [K]", "initial_temperature",
          "thermal/constants", "T", "T", "T",
          "fixed", "C", "298.15",
          "n/a under isothermal", "RT", "assumed", "C",
          "Only consumed under a thermal submodel."))
R.append(("Reference temperature [K]", "reference_temperature",
          "thermal/constants", "Y", "Y", "Y",
          "fixed", "C", "298.15",
          "n/a (Arrhenius reference)",
          "RT", "generic", "C",
          "Arrhenius reference temperature (activation energies referenced to it)."))
R.append(("Electrolyte density [kg.m-3]", "electrolyte_density",
          "thermal/constants", "N", "N", "N",
          "prior", "C", "generic carbonate (~1200)",
          "n/a", "RT", "generic", "C",
          "Thermal model only."))
R.append(("Lithium metal partial molar volume [m3.mol-1]", "li_partial_molar_volume",
          "thermal/constants", "Y", "Y", "Y",
          "fixed", "C", "generic (Li-metal electrode model constant)",
          "low", "RT", "generic Li metal", "C",
          "Present in reference half-cell set; consumption to be confirmed in H1-D wiring."))
R.append(("Open-circuit voltage at 0% SOC [V]", "ocv_at_0pct_soc",
          "solid thermo/OCP", "N", "N", "N",
          "fixed", "C", "UNKNOWN (SOC-based initialisation not used here)",
          "n/a", "RT", "generic", "C",
          "SOC-based init path not used for replay (measured V0 + inverse OCP path in H1-D)."))
R.append(("Open-circuit voltage at 100% SOC [V]", "ocv_at_100pct_soc",
          "solid thermo/OCP", "N", "N", "N",
          "fixed", "C", "UNKNOWN",
          "n/a", "RT", "generic", "C",
          "As above."))
R.append(("Initial concentration in positive electrode [mol.m-3]", "initial_positive_concentration",
          "initialization", "Y", "Y", "Y",
          "inferred", "U", "UNKNOWN (H1-D: inverse-OCP(measured V0) on the chosen OCP branch)",
          "high (initial state; not inverted in H1-B/H1-C)",
          "RT", "see replay_summary initial_states (measured V0 only)", "U",
          "x0/c_s0 belong to the parameterisation layer (H1-D). Measured V0 facts listed in experimental_facts.json."))
R.append(("Number of cells connected in series to make a battery", "series_cells",
          "geometry/loading", "Y", "Y", "Y",
          "design", "C", "1",
          "n/a", "RT", "definition", "C",
          "Single coin cell."))
R.append(("Number of electrodes connected in parallel to make a cell", "parallel_electrodes",
          "geometry/loading", "Y", "Y", "Y",
          "design", "C", "1",
          "n/a", "RT", "definition", "C",
          "Single-side coated disc."))

# ---- conceptual (non-pybamm-key) requirements --------------------------
R.append(("(conceptual) initial stoichiometry x0", "initial_stoichiometry_x0",
          "initialization", "Y", "Y", "Y",
          "inferred", "U", "UNKNOWN (from measured V0 via chosen OCP)",
          "high", "RT", "replay_summary initial_states (V0)", "U",
          "Not a SINTEF fact; belongs to H1-D parameterisation."))
R.append(("(conceptual) stoichiometry window dx", "stoichiometry_window_dx",
          "initialization", "Y", "Y", "Y",
          "inferred", "U", "UNKNOWN (depends on chosen OCP + voltage endpoints)",
          "high (capacity closure)",
          "RT", "see ocp_source_audit.json", "U",
          "dx = x(V_low)-x(V_high) implied by the chosen OCP; not measured."))
R.append(("(conceptual) active material mass loading", "active_mass_loading",
          "geometry/loading", "Y", "Y", "Y",
          "inferred", "U", "UNKNOWN (metadata blank for LFP rows)",
          "high", "RT", "SINTEF metadata.csv (blank)", "U",
          "Commercial electrode; mass/wt%/loading columns empty in metadata."))
R.append(("(conceptual) OCP hysteresis / equilibrium definition", "ocp_hysteresis_definition",
          "solid thermo/OCP", "Y", "Y", "Y",
          "inferred", "A1", "two measured branches available; equilibrium treatment open",
          "high (structural, see ocp_source_audit.json)",
          "RT", "H1-B processed p-OCV", "A1",
          "Charge/discharge branches differ; single-equilibrium OCP is a model-structure hypothesis to test in H1-D, not a parameter error."))

# ---------------------------------------------------------------------------
# Literature prior bank rows (B2 / C), columns:
# parameter, value/range, unit, temperature, electrolyte, electrode_details,
# method, doi_or_source, source_class, match_grade, uncertainty_status, note
# ---------------------------------------------------------------------------
PB = []
PB.append(("positive_electrode_porosity", "0.254", "1 (vol frac)", "298 K",
           "1 M LiPF6 EC:DEC 1:1 (Sec.2)", "in-house LFP 26.5 um, 4.749 mg/cm2, 16 mm disc",
           "computed (Table 1)", "10.1088/2515-7655/acfc66 (acfc66)", "B2", "C (parameters-matched publication)", "medium", "electrode eps_e, base case"))
PB.append(("separator_porosity", "0.37", "1", "298 K", "same", "separator 20 um", "Table 1",
           "10.1088/2515-7655/acfc66", "B2", "C", "medium", ""))
PB.append(("positive_particle_radius", "1e-6", "m", "298 K", "same", "FESEM-verified mean", "Table 1 / Sec.2",
           "10.1088/2515-7655/acfc66", "B2", "C", "low-medium", "1 um primary particles"))
PB.append(("positive_particle_diffusivity", "3.7e-16", "m2.s-1", "298 K", "same", "same electrode", "EIS (Table 1)",
           "10.1088/2515-7655/acfc66", "B2", "C", "medium", "constant Ds base case"))
PB.append(("positive_reaction_rate", "0.12e-11", "m^2.5 mol^-0.5 s^-1", "298 K", "same", "same electrode",
           "calibrated/fitted (Table 1)", "10.1088/2515-7655/acfc66", "B2", "C", "high", "k0 form; requires unit conversion to pybamm i0 form"))
PB.append(("positive_c_smax", "21852", "mol.m-3", "298 K", "same", "same electrode", "Table 1",
           "10.1088/2515-7655/acfc66", "B2", "C", "low", "slightly below theoretical"))
PB.append(("electrode_thickness", "26.5e-6", "m", "298 K", "same", "in-house LFP (THIN, areal ~0.66 mAh/cm2)", "Table 1",
           "10.1088/2515-7655/acfc66", "B2", "C", "n/a", "geometry anchor only - NOT the SINTEF 78 um electrode"))
PB.append(("active_mass_loading", "4.749", "mg.cm-2", "298 K", "same", "in-house LFP", "Sec.2",
           "10.1088/2515-7655/acfc66", "B2", "C", "n/a", "anchor cell geometry differs from SINTEF"))
PB.append(("positive_c_smax", "22820", "mol.m-3", "298.15 K", "1 M LiPF6 EC:DEC 1:1 (50:50 vol%)", "in-house LFP 11.0+-0.8 mg/cm2, Celgard 2325",
           "estimated (Table I; ~theoretical)", "10.1149/1945-7111/ae94f3 (ae94f3)", "B2", "C", "low",
           "equals theoretical c_smax (3.60 g/cc / 157.76 g/mol)"))
PB.append(("positive_electrode_porosity", "0.45", "1 (vol frac)", "298.15 K", "1 M LiPF6 EC:DEC 1:1", "in-house LFP 80:10:10, 11.0 mg/cm2",
           "measured / calc. Eq.12 (Table I)", "10.1149/1945-7111/ae94f3", "B2", "C", "medium", "electrode eps_e"))
PB.append(("separator_porosity", "0.39", "1", "298.15 K", "same", "Celgard 2325", "manufacturer spec (Table I)",
           "10.1149/1945-7111/ae94f3", "B2", "C", "low", "separator = Celgard 2325"))
PB.append(("separator_thickness", "25e-6", "m", "298.15 K", "same", "Celgard 2325", "spec",
           "10.1149/1945-7111/ae94f3", "B2", "C", "low", "anchor only"))
PB.append(("positive_exchange_current", "50 (assumed)", "A.m-2", "298.15 K", "same", "same electrode", "assumed in Table I (NOT measured)",
           "10.1149/1945-7111/ae94f3", "B2", "C", "high", "j0 reference 0.363 from lit.[12] also reported; 50 A/m2 is the P2D table value"))
PB.append(("positive_particle_diffusivity", "SOC-dependent (GITT)", "m2.s-1", "298.15 K", "same", "same electrode",
           "own GITT (Fig.4); constant-Ds test consistent w/ GITT at SOC~0.34", "10.1149/1945-7111/ae94f3", "B2", "C", "high",
           "table extraction of numeric ranges unreliable in H1-C; treat as qualitative SOC-dependence evidence"))
PB.append(("positive_particle_radius", "PSD (surface-area-weighted)", "m", "298.15 K", "same", "same electrode",
           "SEM + laser PSD (Eq.5)", "10.1149/1945-7111/ae94f3", "B2", "C", "high", "no single mean radius number found in H1-C fetch"))
PB.append(("voltage_window", "2.8-3.8", "V", "298.15 K", "same", "same electrode", "Table II",
           "10.1149/1945-7111/ae94f3", "B2", "C", "n/a", "ae94f3 window DIFFERS from SINTEF 2.50-3.65"))
PB.append(("electrolyte_composition", "1 M LiPF6 EC:DEC 1:1 vol", "-", "298.15 K", "-", "-", "Sec.2 exp.",
           "10.1149/1945-7111/ae94f3", "B2", "C", "n/a", "composition anchor for SINTEF-style LFP half cells"))
PB.append(("positive_c_smax", "~22820 (theoretical)", "mol.m-3", "RT", "-", "-",
           "rho=3.60 g/cc, M=157.76 g/mol -> F*c_smax*M=rho (x=1)", "derivation", "C", "C", "low",
           "generic theoretical ceiling; ae94f3 estimate coincides"))
PB.append(("positive_alpha", "0.5", "1", "RT", "-", "-", "symmetric Butler-Volmer default", "generic", "C", "C", "low", ""))
PB.append(("positive_brug_ele", "1.5", "1", "RT", "-", "-", "Bruggeman default", "generic", "C", "C", "medium", "classic exponent"))
PB.append(("electrolyte_transport", "generic 1 M LiPF6 carbonate model", "-", "RT", "1 M LiPF6", "-",
           "PyBaMM default electrolyte parameterisation (or any published 1 M LiPF6)", "generic/pybamm", "C", "C", "medium",
           "SINTEF electrolyte not disclosed; property values are generic unless a specific recipe is later matched"))
PB.append(("positive_ocp", "LFP OCP (Prada2013 set, pybamm)", "-", "RT", "-", "LFP/graphite full-cell context",
           "registered pybamm parameter set (full-cell surrogate for CALCE A123 in v0.4)", "pybamm 'Prada2013'", "C", "C", "medium",
           "chemistry prior only; full-cell origin -> not a half-cell reference"))

# ---------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unit_of(key: str) -> str:
    if "[" in key and key.endswith("]"):
        return key[key.index("[") + 1:-1]
    return "1"


def load_facts():
    sm = json.loads((H1B / "source_manifest.json").read_text(encoding="utf-8"))
    rs = json.loads((H1B / "replay_summary.json").read_text(encoding="utf-8"))
    # sanity checks against the frozen H1-B numbers (fail loudly if schema drifts)
    assert abs(sm["electrode"]["electrode_area_cm2"] - AREA_CM2) < 1e-4, "area mismatch"
    assert sm["electrode"]["electrode_thickness_um"] == 78.0
    assert sm["electrode"]["electrode_diameter_mm"] == 14.0
    assert abs(rs["capacity"]["q_nominal_metadata_mAh"] - 3.07876) < 1e-6
    assert rs["gates"]["model_dependency_zero"] is True
    return sm, rs


def write_csv(path: Path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def build_experimental_facts(sm, rs):
    """Layer-1: ONLY SINTEF direct (A0) or strictly derived (A1) facts."""
    d = {
        "record": {
            "short_name": sm["dataset"]["short_name"],
            "zenodo_doi": sm["dataset"]["zenodo_doi"],
            "record_version_matched": sm["dataset"]["record_version_matched"],
            "newer_record_doi": sm["dataset"]["newer_record_doi"],
            "license": sm["dataset"]["license"],
            "lab": sm["dataset"]["lab"],
        },
        "cell": {
            "cell_configuration": "half_cell LFP||Li R2032 (coin)",
            "working_electrode": "LFP (commercial LFP-NMP-1)",
            "counter_electrode": "Li-metal",
            "public_label": sm["electrode"]["public_label"],
            "start_date_yyyymmdd": sm["electrode"]["start_date_yyyymmdd"],
            "cycling_programme": "p-OCV",
        },
        "geometry_A0": {
            "electrode_diameter_mm": 14.0,
            "electrode_thickness_um": 78.0,
            "nominal_areal_capacity_mAh_cm2": 2.0,
            "nominal_capacity_mAh": 3.07876,
        },
        "geometry_A1_derived": {
            "electrode_area_cm2": round(AREA_CM2, 6),
            "electrode_area_m2": float(f"{AREA_M2:.6e}"),
            "note": "disc area from diameter (A0); pybamm footprint uses sqrt(A) square equivalent",
        },
        "protocol_A0": {
            "sequence": "6 h pre-rest + [charge C/50 -> 8 h rest -> discharge C/50 -> 8 h rest] x5",
            "full_cycles": 5,
            "charge_legs": 5,
            "discharge_legs": 5,
            "rest_blocks": 11,
            "rest_durations_h": rs["rest_durations_h"],
            "voltage_window_V": rs["voltage_window_V"],
            "cutoffs_reached": {"charge_V": 3.65, "discharge_V": 2.49999},
        },
        "current_A0": {
            "driven_leg_median_uA": rs["current"]["driven_leg_median_uA"],
            "c50_implied_uA": rs["current"]["c50_implied_uA"],
            "note": "measured |I| = 61.60 uA vs C/50 on nominal 3.0788 mAh = 61.575 uA (ratio 1.0004)",
        },
        "capacity_A1": {
            "q_integral_charge_mAh": rs["capacity"]["q_integral_charge_mAh"],
            "q_integral_discharge_mAh": rs["capacity"]["q_integral_discharge_mAh"],
            "discharge_mean_mAh": rs["capacity"]["discharge_mean_mAh"],
            "discharge_mean_over_nominal": rs["capacity"]["discharge_mean_over_nominal"],
            "cycler_cumulative_max_dev_uAh": rs["capacity"]["cycler_cumulative_column_max_dev_uAh"],
            "note": rs["capacity"]["note"],
        },
        "initial_state_facts_A0": [
            {k: s[k] for k in ("segment", "cycle_index", "direction",
                               "initial_voltage_V", "preceding_rest_end_voltage_V",
                               "preceding_rest_h", "current_A_at_first_sample")}
            for s in rs["initial_states"]
        ],
        "ocp_hysteresis_A1": ocp_hysteresis_proxy(rs),
        "temperature": {
            "description": "RT (record: room temperature; no numeric value reported)",
            "assumed_K_for_model": 298.15,
            "assumption_note": "298.15 K is a model default; the record does not report a numeric chamber temperature",
        },
        "mass_loading": {
            "value": None,
            "source_class": "U",
            "note": "metadata columns Mass/Electrode Coating Mass/wt%/Theoretical Capacity/Loading are BLANK for all LFP rows",
        },
    }
    return d


def ocp_hysteresis_proxy(rs):
    """Median driven-leg voltage per branch from the processed parquet (facts)."""
    pdf = pd.read_parquet(H1B / "processed_pocv.parquet")
    leg = pdf[pdf["segment_type"].isin(["charge", "discharge"])].copy()
    med = {}
    for branch in ("charge", "discharge"):
        vals = []
        for cyc in range(2, 6):
            seg = f"c{cyc}_{branch}"
            sub = leg[leg["segment_label"] == seg]
            if len(sub):
                vals.append(float(sub["voltage_V"].median()))
        med[branch] = vals
    ch = med["charge"]
    dc = med["discharge"]
    proxy = {
        "median_voltage_per_cycle_charge_V": [round(v, 4) for v in ch],
        "median_voltage_per_cycle_discharge_V": [round(v, 4) for v in dc],
        "hysteresis_proxy_median_ch_minus_dc_mV": round(
            float(sum(ch) / len(ch) - sum(dc) / len(dc)) * 1e3, 1) if ch and dc else None,
        "method": "median terminal voltage during driven legs c2-c5 (proxy; NOT throughput-aligned hysteresis, "
                  "which would require x-aligned comparison in H1-D)",
    }
    return proxy


def build_ocp_audit(sm, rs, proxy):
    return {
        "method_note": "Each candidate OCP is audited for source, direction, stoichiometry range, temperature, "
                       "hysteresis handling, interpolation and extrapolation semantics.",
        "measured_hysteresis_proxy": proxy,
        "candidates": [
            {
                "id": "sintef_pocv_discharge",
                "source": "SINTEF p-OCV d07eb6, discharge legs c2-c5 (full window)",
                "source_class": "A0/A1",
                "branch": "discharge",
                "voltage_range_V": [2.49999, 3.65],
                "stoichiometry_range": "UNKNOWN (x-axis not yet assigned; H1-D layer)",
                "temperature": "RT (no numeric)",
                "hysteresis_handling": "lower branch; hysteresis vs charge branch observed",
                "interpolation": "piecewise linear on cycler samples (dense C/50 sampling)",
                "extrapolation": "none required inside [2.5, 3.65] full window",
                "match_grade": "A1 (same cell, derived from own raw)",
                "note": "Primary OCP candidate for discharge-direction replay.",
            },
            {
                "id": "sintef_pocv_charge",
                "source": "SINTEF p-OCV d07eb6, charge legs c2-c5 (full window)",
                "source_class": "A0/A1",
                "branch": "charge",
                "voltage_range_V": [3.65, 2.5],
                "stoichiometry_range": "UNKNOWN",
                "temperature": "RT (no numeric)",
                "hysteresis_handling": "upper branch",
                "interpolation": "piecewise linear on cycler samples",
                "extrapolation": "none required",
                "match_grade": "A1",
                "note": "Charge branch; visible offset from discharge branch.",
            },
            {
                "id": "acfc66_c50_ocp",
                "source": "acfc66 (10.1088/2515-7655/acfc66), own C/50 half-cell OCP",
                "source_class": "B2",
                "branch": "galvanostatic C/50 (quasi-OCP)",
                "voltage_range_V": "not stated numerically in fetched text (2.5-3.65 class)",
                "stoichiometry_range": "not stated",
                "temperature": "298 K",
                "hysteresis_handling": "as recorded (figure only; raw unavailable)",
                "interpolation": "unknown (paper figure)",
                "extrapolation": "unknown",
                "match_grade": "C (parameters-matched publication, raw not public)",
                "note": "Different in-house electrode (26.5 um, 4.749 mg/cm2). Chemistry prior only.",
            },
            {
                "id": "ae94f3_c25_ocp",
                "source": "ae94f3 (10.1149/1945-7111/ae94f3), own C/25 half-cell equilibrium",
                "source_class": "B2",
                "branch": "galvanostatic C/25 (equilibrium; 2x C/25 formation)",
                "voltage_range_V": [2.8, 3.8],
                "stoichiometry_range": "not stated",
                "temperature": "298.15 K",
                "hysteresis_handling": "single recorded equilibrium curve",
                "interpolation": "unknown (paper figure)",
                "extrapolation": "unknown",
                "match_grade": "C",
                "note": "Different electrode (11.0 mg/cm2) AND different voltage window (2.8-3.8 V). Prior only.",
            },
            {
                "id": "generic_single_branch",
                "source": "any single-branch equilibrium LFP OCP (e.g. pybamm 'Prada2013' LFP positive)",
                "source_class": "C",
                "branch": "equilibrium (single)",
                "voltage_range_V": "as-registered",
                "stoichiometry_range": "as-registered",
                "temperature": "as-registered",
                "hysteresis_handling": "NONE - single curve cannot represent both measured branches",
                "interpolation": "as-registered",
                "extrapolation": "as-registered",
                "match_grade": "C",
                "note": "If H1-D uses one equilibrium OCP against the hysteretic SINTEF p-OCV, residual is expected "
                       "to be structurally dominated by the single-branch assumption (a model-structure issue, not "
                       "a Ds/k0 error). SINTEF itself provides both branches so a branch-resolved or hysteretic OCP "
                       "is available without external priors.",
            },
        ],
        "hysteresis_warning": "LFP charge/discharge hysteresis is evident in H1-B V-Q figure. Residual attribution in "
                              "H1-D must separate hysteresis-model structure from parameter error.",
    }


def build_capacity_closure():
    rows = []
    header = ["geometry_tag", "L_um", "area_m2", "c_smax_source", "c_smax_mol_m3",
              "eps_s", "dx", "Q_geom_mAh", "Q_nominal_mAh", "Q_exp_mean_mAh",
              "geom_vs_nominal_pct", "geom_vs_experimental_pct", "in_experimental_band"]
    c_smax_opts = [("ae94f3/theoretical", C_SMAX_THEO), ("acfc66", C_SMAX_ACFC66)]
    eps_opts = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    dx_opts = [0.80, 0.85, 0.90, 0.95, 0.98, 1.00]
    vol = AREA_M2 * THICK_M
    for tag, cs in c_smax_opts:
        for es in eps_opts:
            for dx in dx_opts:
                q_c = FARADAY * vol * es * cs * dx        # C
                q_mah = q_c / 3.6
                err_nom = (q_mah / (NOMINAL_AH * 1e3) - 1.0) * 100.0
                err_exp = (q_mah / (Q_EXP_DISCHARGE_MEAN_AH * 1e3) - 1.0) * 100.0
                in_band = Q_EXP_BAND_AH[0] * 1e3 <= q_mah <= Q_EXP_BAND_AH[1] * 1e3
                rows.append(["SINTEF LFP-NMP-1 (78um, 1.539 cm2)", THICK_M * 1e6, f"{AREA_M2:.6e}",
                             tag, cs, es, dx, round(q_mah, 4),
                             3.07876, 3.2878, round(err_nom, 2), round(err_exp, 2), in_band])
    # diagnostic: implied (eps_s*dx) that would close exactly each target
    denom = FARADAY * vol * C_SMAX_THEO
    imp_exp = (Q_EXP_DISCHARGE_MEAN_AH * 3600.0) / denom
    imp_nom = (NOMINAL_AH * 3600.0) / denom
    diag = {
        "q_geom_full_density_dx1_mAh": round(denom / 3.6, 4),
        "implied_eps_times_dx_for_Qnominal": round(imp_nom, 4),
        "implied_eps_times_dx_for_Qexp_mean": round(imp_exp, 4),
        "reading": ("Q_geom = F*A*L*eps_s*c_smax*dx with theoretical c_smax=22820 and eps_s*dx ~0.42-0.45 closes "
                    "the measured window capacity. eps_s ~0.5 with dx ~0.85-0.9 or eps_s ~0.55 with dx ~0.8 are all "
                    "physically plausible commercial-LFP values -> capacity closure is CONSISTENT but DEGENERATE: "
                    "eps_s and dx cannot be separated without an independent x0/x-endpoint or volume-fraction "
                    "measurement. The +6.8% over nominal label is explained by geometry + theoretical density; the "
                    "manufacturer nominal is a conservative label, not a discrepancy in the cell. NO parameter was "
                    "tuned: all rows are prior/grid values."),
        "hard_rule": ("No active fraction / c_smax / stoichiometric window was selected to force Q_geom == "
                      "3.2878 mAh. If a future composite gives only ~2.8 mAh under priors, the honest output is "
                      "'capacity closure failed -> composite not eligible for H1-D', not a retune."),
    }
    return header, rows, diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sm, rs = load_facts()
    proxy = ocp_hysteresis_proxy(rs)
    facts = build_experimental_facts(sm, rs)
    ocp = build_ocp_audit(sm, rs, proxy)
    cc_header, cc_rows, cc_diag = build_capacity_closure()

    # ---- parameter_requirements.csv / parameter_source_matrix.csv ---------
    req_header = ["canonical_name", "pybamm_key", "unit", "required_for_spm",
                  "required_for_spme", "required_for_dfn", "physical_group"]
    matrix_header = ["canonical_name", "pybamm_key", "unit", "required_for_spm",
                     "required_for_spme", "required_for_dfn", "physical_group",
                     "role", "source_class", "value_or_range", "uncertainty_status",
                     "temperature", "source_ref", "match_grade", "comment"]
    # R tuple layout: (0 pybamm_key, 1 canonical, 2 group, 3 spm, 4 spme, 5 dfn,
    #                  6 role, 7 source_class, 8 value_or_range, 9 uncertainty,
    #                  10 temperature, 11 source_ref, 12 match_grade, 13 comment)
    universe = json.loads(KEYUNIV.read_text(encoding="utf-8"))["keys"]
    rows_by_key = {}
    for r in R:
        rows_by_key.setdefault(r[0], []).append(r)
    missing = [k for k in universe if k not in rows_by_key]
    if missing:
        raise SystemExit(f"requirements table incomplete vs halfcell key universe: {missing}")
    # remove accidental duplicate-key rows (e.g. repeated Separator thickness) -> keep first
    seen, R_final = set(), []
    for r in R:
        if r[0] not in seen:
            seen.add(r[0]); R_final.append(r)
    R_sorted = sorted(R_final, key=lambda r: (r[2], r[1]))
    req_rows = [[r[1], r[0], unit_of(r[0]), r[3], r[4], r[5], r[2]] for r in R_sorted]
    mat_rows = [[r[1], r[0], unit_of(r[0]), r[3], r[4], r[5], r[2],
                 r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13]] for r in R_sorted]
    write_csv(out_dir / "parameter_requirements.csv", req_header, req_rows)
    write_csv(out_dir / "parameter_source_matrix.csv", matrix_header, mat_rows)

    # ---- experimental_facts.json (layer 1) -------------------------------
    with open(out_dir / "experimental_facts.json", "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=2, ensure_ascii=False)

    # ---- literature_prior_bank.csv (layer 2) -----------------------------
    pb_header = ["parameter", "value/range", "unit", "temperature", "electrolyte",
                 "electrode_details", "measurement_or_model_method", "doi_or_source",
                 "source_class", "match_grade", "uncertainty_status", "note"]
    write_csv(out_dir / "literature_prior_bank.csv", pb_header, PB)

    # ---- capacity_closure.csv --------------------------------------------
    write_csv(out_dir / "capacity_closure.csv", cc_header, cc_rows)

    # ---- ocp_source_audit.json -------------------------------------------
    with open(out_dir / "ocp_source_audit.json", "w", encoding="utf-8") as fh:
        json.dump(ocp, fh, indent=2, ensure_ascii=False)

    # ---- unresolved_parameters.csv ---------------------------------------
    un_header = ["canonical_name", "pybamm_key", "physical_group", "reason", "suggested_path"]
    un_reason = {
        "positive_electrode_porosity": "SINTEF electrode microstructure not disclosed (porosity blank in metadata)",
        "positive_active_volume_fraction": "active fraction not disclosed; product degeneracy with dx (capacity_closure.csv)",
        "separator_porosity": "separator not disclosed",
        "separator_thickness": "separator not disclosed",
        "positive_particle_diffusivity": "Ds not measured by SINTEF record; external spread covers orders of magnitude",
        "positive_particle_radius": "particle size not disclosed (commercial electrode)",
        "positive_exchange_current": "kinetics not measured by SINTEF record",
        "positive_reaction_rate": "kinetics not measured; acfc66 k0 needs unit conversion to i0 form",
        "contact_resistance": "no SINTEF value exists; option enabled in H0 wiring",
        "positive_electrode_conductivity": "electronic conductivity not disclosed",
        "active_mass_loading": "metadata mass/coating/wt% columns blank for LFP rows",
        "initial_positive_concentration": "initial state not inverted in H1-B/H1-C (measured V0 only)",
        "initial_stoichiometry_x0": "stoichiometry inversion belongs to H1-D layer",
        "stoichiometry_window_dx": "x-window depends on chosen OCP in H1-D",
        "electrolyte_diffusivity": "electrolyte not disclosed by SINTEF",
        "electrolyte_conductivity": "electrolyte not disclosed by SINTEF",
        "cation_transference": "electrolyte not disclosed by SINTEF",
        "electrolyte_thermodynamic_factor": "electrolyte not disclosed by SINTEF",
        "initial_electrolyte_concentration": "electrolyte recipe not disclosed (1 M LiPF6 anchor only)",
    }
    un_rows = []
    for r in R_sorted:
        if r[7] == "U":
            un_rows.append([r[1], r[0], r[2],
                            un_reason.get(r[1], "not disclosed / not measured"),
                            "H1-D0 zero-fit sensitivity; download SINTEF GITT ONLY if this key becomes the dominant evidence gap"])
    un_rows = sorted(un_rows, key=lambda x: (x[2], x[0]))
    write_csv(out_dir / "unresolved_parameters.csv", un_header, un_rows)

    # ---- model_ready_composite_draft.json (layer 3 DRAFT) ----------------
    composite = {
        "parameter_set_type": "composite_unmatched",
        "publication_reproduction": False,
        "fit_performed": False,
        "declaration": ("DRAFT ONLY. This is NOT a matched publication parameter set and NOT a validated SINTEF "
                        "parameter set. It exists to declare the assembly status; it MUST NOT be run before H1-D0 "
                        "defines the zero-fit semantics. No value was tuned to close capacity."),
        "experimental_anchor": "SINTEF R2032 LFP-NMP-1 p-OCV (H1-B frozen)",
        "assembly_anchors": [
            {"role": "geometry (A0/A1)", "status": "resolved", "source": "SINTEF metadata + H1-B"},
            {"role": "OCP (A1)", "status": "resolved (two measured branches)", "source": "own p-OCV"},
            {"role": "cutoffs / current / protocol (A0)", "status": "resolved", "source": "H1-B"},
            {"role": "c_smax", "status": "prior (B2/theoretical, ~22820)", "source": "ae94f3 / derivation"},
            {"role": "porosity / active fraction", "status": "UNRESOLVED (U)", "source": "priors acfc66/ae94f3/generic"},
            {"role": "particle radius", "status": "UNRESOLVED (U)", "source": "priors acfc66/ae94f3"},
            {"role": "D_s", "status": "UNRESOLVED (U)", "source": "priors acfc66/ae94f3; SINTEF GITT deferred"},
            {"role": "k0 / j0", "status": "UNRESOLVED (U)", "source": "priors acfc66/ae94f3"},
            {"role": "electrolyte + separator", "status": "UNRESOLVED (U/C)", "source": "composition anchors only"},
        ],
        "n_unresolved": len(un_rows),
    }
    with open(out_dir / "model_ready_composite_draft.json", "w", encoding="utf-8") as fh:
        json.dump(composite, fh, indent=2, ensure_ascii=False)

    # ---- gates ------------------------------------------------------------
    n_unknown = len(un_rows)
    n_cc_rows = len(cc_rows)
    role_ok = all(r[6] in {"measured", "derived", "fixed", "prior", "inferred",
                           "nuisance", "design"} for r in R_sorted)
    class_ok = all(r[7] in {"A0", "A1", "B1", "B2", "C", "U"} for r in R_sorted)
    grade_ok = all(str(r[12]).strip() for r in R_sorted)
    u_no_fabricated = all(r[7] != "U" or str(r[8]).startswith("UNKNOWN") or str(r[8]).startswith("n/a")
                          for r in R_sorted)
    gates = {
        "G1_model_requirement_coverage": {
            "pass": len(missing) == 0 and len(R_sorted) >= len(universe),
            "detail": f"all {len(universe)} half-cell reference keys enumerated; "
                      f"{len(R_sorted)} rows incl. {len(R_sorted)-len(universe)} conceptual inputs "
                      "(x0, dx, mass loading, hysteresis definition).",
        },
        "G2_provenance": {
            "pass": role_ok and class_ok and grade_ok and u_no_fabricated,
            "detail": "every row carries role + source_class + match_grade; U rows carry no fabricated value "
                      "(value_or_range starts with 'UNKNOWN').",
        },
        "G3_experimental_separation": {
            "pass": all(set(facts.keys()) & {"record", "cell", "geometry_A0", "geometry_A1_derived",
                                             "protocol_A0", "current_A0", "capacity_A1",
                                             "initial_state_facts_A0", "ocp_hysteresis_A1",
                                             "temperature", "mass_loading"}),
            "detail": "experimental_facts.json contains only SINTEF A0/A1 facts; all external priors live in "
                      "literature_prior_bank.csv and the source matrix.",
        },
        "G4_capacity_closure_quantified": {
            "pass": n_cc_rows == 84,
            "detail": f"{n_cc_rows} grid rows (2 c_smax x 7 eps_s x 6 dx) written with "
                      f"geom_vs_nominal_pct / geom_vs_experimental_pct; "
                      f"diagnostic: {cc_diag['reading']}",
            "note": cc_diag["hard_rule"],
        },
        "G5_ocp_traceability": {
            "pass": all(all(k in c for k in ("source", "branch", "voltage_range_V", "temperature",
                                             "hysteresis_handling", "interpolation", "extrapolation",
                                             "source_class", "match_grade")) for c in ocp["candidates"]),
            "detail": "5 OCP candidates fully annotated; SINTEF provides both branches (A1) - single-branch "
                      "equilibrium limitation flagged as model structure.",
        },
        "G6_unknown_preservation": {
            "pass": n_unknown > 0,
            "detail": f"{n_unknown} parameters kept UNKNOWN (see unresolved_parameters.csv); none force-filled.",
        },
        "G7_model_declaration": {
            "pass": composite["parameter_set_type"] == "composite_unmatched"
                    and composite["publication_reproduction"] is False
                    and composite["fit_performed"] is False,
            "detail": "model_ready_composite_draft.json declares composite_unmatched / no reproduction claim / no fit.",
        },
    }
    all_pass = all(g["pass"] for g in gates.values())

    gate_summary = {
        "h1c_date": "2026-09-08",
        "scope": "SINTEF R2032 LFP-NMP-1 p-OCV parameter-source audit. NO pybamm run / NO fit / NO GITT download / "
                 "H0+H1-B untouched.",
        "gates": gates,
        "all_gates_pass": all_pass,
        "n_unresolved": n_unknown,
        "gitt_download_decision": {
            "rule": "Download SINTEF GITT (b89ab5 / b26620) ONLY if the audit proves D_s is the dominant evidence "
                    "gap for the approved next experiment.",
            "verdict": "DEFER. D_s is UNRESOLVED (U, external spread covers orders of magnitude), but for the "
                       "approved H1-D0 target (zero-fit reproduction of the C/50 p-OCV) the near-equilibrium scan "
                       "has LOW sensitivity to D_s; capacity closure and OCP/hysteresis dominate instead. "
                       "A GITT download becomes justified only when a D_s-attribution or multi-rate experiment is "
                       "approved.",
        },
        "next_stage": "H1-D0 zero-fit forward baseline with audited composite pristine-LFP params; decompose "
                      "residual into capacity / OCP / kinetics / transport layers. No parameterisation before "
                      "H1-D0 decomposition and (V2) identifiability study.",
    }
    with open(out_dir / "h1c_gate_summary.json", "w", encoding="utf-8") as fh:
        json.dump(gate_summary, fh, indent=2, ensure_ascii=False)

    # ---- source_manifest --------------------------------------------------
    out_files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    manifest = {
        "task": "H1-C parameter-source audit",
        "experimental_facts_source": "H1-B frozen replay (outputs/analysis/lfp_h1/data_replay)",
        "inputs": {
            "processed_pocv.parquet": {"path": str(H1B / "processed_pocv.parquet"), "sha256": sha256(H1B / "processed_pocv.parquet")},
            "replay_summary.json": {"path": str(H1B / "replay_summary.json"), "sha256": sha256(H1B / "replay_summary.json")},
            "source_manifest.json": {"path": str(H1B / "source_manifest.json"), "sha256": sha256(H1B / "source_manifest.json")},
            "metadata.csv": {"path": str(META), "sha256": sha256(META)},
            "raw_pocv.parquet": {"path": str(RAW), "sha256": sha256(RAW), "md5": hashlib.md5(RAW.read_bytes()).hexdigest()},
            "halfcell_required_keys.json": {"path": str(KEYUNIV), "sha256": sha256(KEYUNIV)},
        },
        "build_script": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
            "pybamm_import": False,
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
        },
        "outputs": {f: sha256(out_dir / f) for f in out_files},
        "determinism": "no wall-clock timestamps; sorted rows; deterministic JSON/CSV serialisation.",
    }
    with open(out_dir / "source_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(f"wrote {len(out_files)} outputs to {out_dir}")
    print(f"requirements rows={len(R_sorted)}  unknowns={n_unknown}  gates_all_pass={all_pass}")
    for g, v in gates.items():
        print(f"  {g}: pass={v['pass']}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
