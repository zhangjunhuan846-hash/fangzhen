"""H1-D0: build_parameter_lock.py  (0 model runs; pybamm not imported).

Produces outputs/analysis/lfp_h1/forward_baseline/parameter_lock.json and
model_discrepancy.json. Every parameter is frozen with role / source_class /
source_reference / selection_reason and selected_before_forward_run=true.
The lock sha256 is computed over the canonical payload (excluding the hash
field itself). NO value is allowed to change after the first forward run;
any change must become a new hypothesis run (D0-A2), never an overwrite.

Checks performed (consistency with frozen H1-B/H1-C products):
  - SINTEF A0/A1 facts echo (geometry / window / C/50 current / nominal label)
  - template = Jackowska2025_2mAh_cm2 51-key universe
  - every override key maps to either a template key or a declared extra
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # scripts/lfp_h1d
ROOT = HERE.parents[1]                          # project root
sys.path.insert(0, str(HERE))                   # h1d0_spec
sys.path.insert(0, str(ROOT))                   # battery_sim

import h1d0_spec as S                            # noqa: E402
from h1d0_spec import (                          # noqa: E402
    AUDIT_DIR, FACTS_PATH, OUT_DIR, TEMPLATE_SET, json_default,
    sha256_of, SCALAR_OVERRIDES, FUNCTION_OVERRIDES, PER_LEG, MODEL_OPTIONS, SOLVER,
    D0B_REFERENCE_LEGS, LEG_KEYS_ALLOWED, TEMPLATE_SOURCE,
)
from battery_sim.models.parameter_sources import load_parameter_dict


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    geom0 = facts["geometry_A0"]
    geom1 = facts["geometry_A1_derived"]
    cur = facts["current_A0"]
    win = facts["protocol_A0"]["voltage_window_V"]

    # ---- consistency gates vs frozen facts -----------------------------------
    errors = []
    if abs(geom1["electrode_area_m2"] - S.A_M2) > 1e-12:
        errors.append("A_M2 mismatch vs facts")
    if abs(geom0["electrode_thickness_um"] * 1e-6 - S.THICKNESS_M) > 1e-12:
        errors.append("thickness mismatch vs facts")
    if abs(cur["c50_implied_uA"] - 61.5752) > 1e-3:
        errors.append("C/50 current drift")
    if win["expected"] != [2.5, 3.65]:
        errors.append("window mismatch")
    if errors:
        print("LOCK CONSISTENCY ERRORS:", *errors, sep="\n  ")
        return 2

    # ---- template universe ----------------------------------------------------
    tmpl = {k: v for k, v in load_parameter_dict(TEMPLATE_SET).items()
            if k not in ("chemistry", "citations")}
    n_tmpl = len(tmpl)
    if n_tmpl != 51:
        print(f"WARN template keys = {n_tmpl} (expected 51)")

    override = {}
    for e in SCALAR_OVERRIDES:
        override[e["key"]] = e
    for e in FUNCTION_OVERRIDES:
        override[e["key"]] = e

    unknown_extra = [k for k in override if k not in tmpl and k not in LEG_KEYS_ALLOWED]
    print("override keys outside template (declared extras):",
          [k for k in override if k not in tmpl])
    if unknown_extra:
        print("UNEXPECTED EXTRAS:", unknown_extra)
        return 2

    # ---- assemble full parameter entries --------------------------------------
    parameters = {}
    for key in sorted(set(tmpl) | set(override)):
        if key in LEG_KEYS_ALLOWED:
            continue
        if key in override:
            e = override[key]
            entry = {
                "selected_before_forward_run": True,
                "inherited": False,
                "role": e["role"],
                "source_class": e["source_class"],
                "source_reference": e["source_reference"],
                "selection_reason": e["selection_reason"],
            }
            if "value" in e:
                entry["value"] = e["value"]
            else:  # functional override: authoritative spec
                entry["function"] = {k2: v2 for k2, v2 in e.items()
                                     if k2 not in ("key", "role", "source_class",
                                                   "source_reference", "selection_reason")}
            parameters[key] = entry
        else:
            v = tmpl[key]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                val = float(v)
            elif callable(v):
                val = {"<function>": getattr(v, "__name__", "anonymous")}
            else:
                val = json_default(v)
            parameters[key] = {
                "selected_before_forward_run": True,
                "inherited": True,
                "value": val,
                "role": "structural_default_unmatched",
                "source_class": "U",
                "source_reference": TEMPLATE_SOURCE,
                "selection_reason": "inherited unmatched structural default (not a "
                                    "SINTEF-specific value)",
            }

    payload = {
        "name": "h1d0_parameter_lock",
        "stage": "H1-D0 Zero-fit Composite Forward Baseline",
        "lock_version": "1.0",
        "selected_before_forward_run": True,
        "composite_declaration": (
            "unmatched composite, NOT a publication reproduction, NOT a validated "
            "SINTEF parameter set. Values were locked BEFORE any forward run and were "
            "never chosen to improve agreement with any SINTEF voltage curve."
        ),
        "fit_performed": False,
        "tuning_prohibition": (
            "After the first forward run no parameter value in this file may be changed "
            "to reduce residual. Any parameter change becomes a new hypothesis run "
            "(D0-A2) writing to a new directory; this lock is immutable."
        ),
        "template": {
            "parameter_set": TEMPLATE_SET,
            "keys": n_tmpl,
            "source_note": TEMPLATE_SOURCE,
        },
        "model_options": MODEL_OPTIONS,
        "solver": SOLVER,
        "a0_a1_facts": {
            "electrode_diameter_mm": geom0["electrode_diameter_mm"],
            "electrode_thickness_um": geom0["electrode_thickness_um"],
            "electrode_area_m2": geom1["electrode_area_m2"],
            "nominal_capacity_mAh": geom0["nominal_capacity_mAh"],
            "c50_driven_median_uA": 61.6,
            "c50_implied_uA": cur["c50_implied_uA"],
            "voltage_window_V": win["expected"],
            "temperature_assumed_K": facts["temperature"]["assumed_K_for_model"],
            "ocp_hysteresis_proxy_mV": facts["ocp_hysteresis_A1"]["hysteresis_proxy_median_ch_minus_dc_mV"],
        },
        "capacity_axis_declaration": (
            "eps_s * dx capacity closure is DEGENERATE (H1-C): observed 3.2878 mAh "
            "discharge does not determine eps_s or dx separately. eps_s=0.50 is a "
            "central prior; neither eps_s nor dx was selected to match 3.2878 mAh. "
            "This lock therefore predicts a model full-window capacity of ~3.67 mAh "
            "on the Afshar window, i.e. an anticipated capacity-axis residual."
        ),
        "parameters": parameters,
        "per_leg_variables": PER_LEG,
        "d0b": {
            "note": "branch-aware diagnostic uses measured branch OCP on the frozen "
                    "model capacity axis; NOT an independent prediction",
            "reference_legs": D0B_REFERENCE_LEGS,
        },
    }

    h = sha256_of(payload)
    payload["lock_sha256"] = h
    out = OUT_DIR / "parameter_lock.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True,
                              default=json_default) + "\n", encoding="utf-8")

    # ---- model_discrepancy.json (static structural declaration) ----------------
    discrepancy = {
        "lfp_hysteresis": {
            "represented": False,
            "note": "Single-curve external OCP (Afshar2017) has no two-branch "
                    "structure. SINTEF charge/discharge branches are separated by a "
                    "median-terminal-voltage proxy of 37.5 mV (H1-B); D0-A does not "
                    "represent it, D0-B substitutes measured branch OCP as a "
                    "diagnostic only.",
        },
        "two_phase_dynamics": {
            "represented": "simplified",
            "note": "Mean-field single-particle (per-electrode) DFN/SPMe/SPM with "
                    "smooth Afshar OCP; no moving-boundary two-phase (shrinking-core) "
                    "LFP phase-transformation model and no interfacial phase "
                    "nucleation kinetics. LFP two-phase plateaus are approximated by "
                    "the analytic OCP slope.",
        },
        "particle_size_distribution": {
            "represented": False,
            "note": "Single representative particle radius R_p = 1 um (acfc66 FESEM "
                    "mean). No PSD broadening.",
        },
        "other_simplifications": [
            "constant D_s (3.7e-16 m2/s) - SOC dependence reported by ae94f3 GITT not used",
            "constant j0 (50 A/m2, assumed in ae94f3) - no exchange-current "
            "concentration/SOC dependence beyond Butler-Volmer",
            "isothermal 298.15 K (assumed; SINTEF reports RT only)",
            "contact resistance feature on with value 0.0",
        ],
    }
    (OUT_DIR / "model_discrepancy.json").write_text(
        json.dumps(discrepancy, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8")

    print(f"lock_sha256={h}")
    print(f"wrote {OUT_DIR / 'parameter_lock.json'} "
          f"({len(parameters)} parameters frozen)")
    print(f"wrote {OUT_DIR / 'model_discrepancy.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
