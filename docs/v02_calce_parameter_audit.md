# v0.2 CALCE CS2 — Parameter / Assumption Audit (Step 16)

**Status**: final, 2026-09-07.
**Scope**: `calce_cs2` (cells 33, 35) × `Ramadass2004` (PyBaMM
26.8.0.0). No fitting performed or planned in v0.2.

This document deliberately separates three categories that must
NEVER be mixed in outputs or reports:

```text
1. Experimental metadata   — measured / reported facts about the CS2 cell
2. Model assumptions       — platform choices where data is missing
3. Surrogate parameter values — Ramadass2004 values, none fitted to CS2
```

---

## 1. Experimental metadata (facts, from CALCE official page + raw files)

| Item | Value | Source |
|---|---|---|
| Cell | CALCE CS2_33 / CS2_35, prismatic | CALCE official |
| Chemistry | **LiCoO2 (LCO) cathode / graphite anode** | CALCE official |
| Nominal capacity | 1.1 Ah | CALCE official |
| Dimensions | 5.4 × 33.6 × 50.6 mm, 21.1 g | CALCE official |
| Charge protocol (all CS2) | CC-CV: 0.5C → 4.2 V, CV until I < 0.05 A | CALCE official + file audit (provenance doc, steps 2/4) |
| CS2_33 discharge | 0.5C CC (0.55 A) → 2.7 V (Type 1) | CALCE official + file audit |
| CS2_35 discharge | 1C CC (1.1 A) → 2.7 V (Type 2) | CALCE official + file audit |
| Voltage window | 2.7 – 4.2 V (observed in files) | file audit |
| Test temperature | **NOT REPORTED** by CALCE | official metadata |
| BOL discharge capacity | CS2_33: 1.1602 Ah; CS2_35: 1.1385 Ah | file audit (I(t) integration) |

## 2. Model assumptions (platform choices — owned by `configs/datasets.yaml`, never by the adapter)

| Assumption | Value | Rationale / confidence |
|---|---|---|
| Ambient temperature | **25 °C, `source: assumed`, `confidence: low`** | CALCE reports no temperature. A secondary review (Kirkaldy et al.) describes CS2 testing as room temperature ≈ 23 °C. A 23-vs-25 °C robustness check is planned; it requires **only a YAML edit** (adapter has no Python default and raises if the config block is missing). |
| Initial state (baseline) | measured rest OCV before the selected discharge (4.1187 V for CS2_33) | measured, from the raw file |
| Capacity semantics (baseline) | `forced_current_window`, **not predictive** | replay integrates the measured current over the measured window, so Q_sim ≈ Q_exp by construction |
| Rate normalization | c_rate = 0.5 / 1.0 (canonical), source labels `0p5C` / `1C` | platform canonical schema (numeric C-rate is the key) |

## 3. Surrogate parameter values (Ramadass2004 — nothing fitted to CS2)

PyBaMM describes Ramadass2004 as a mixed **"Frankenstein" parameter
set** (values assembled from several sources). It is retained
because its *chemistry* matches (graphite / LiCoO2 / LiPF6):

```text
parameter_match: compatible_surrogate
grade: B
fitted_to_dataset: false
```

### 3.1 Chemistry match (why it is B, not A)

| Property | Ramadass2004 | CALCE CS2 | Match |
|---|---|---|---|
| Cathode | LiCoO2 | LiCoO2 | ✅ |
| Anode | graphite | graphite | ✅ |
| Electrolyte | LiPF6 | LiPF6 (typical) | ✅ |

For contrast, Ecker2015 (the alternative LCO-*labelled* set) is a
**C-grade mismatched comparator**: its Kokam SLPB75106100 cathode
is Li(Ni0.4Co0.6)O2, not LiCoO2.

### 3.2 Quantitative differences (why it is only a surrogate)

Actual values dumped from PyBaMM 26.8.0.0
(`scripts/audit/dump_ramadass2004_params.py`):

| Parameter | Ramadass2004 | CALCE CS2 | Consequence |
|---|---|---|---|
| Nominal capacity | 1.0 Ah | 1.1 Ah | 9 % capacity mismatch; C-rate/current scaling off |
| Geometry | electrode 57 mm × 1060.7 mm (area ≈ 0.0605 m²) | prismatic 5.4 × 33.6 × 50.6 mm | completely different cell format |
| Electrode thicknesses | neg 88 µm / pos 80 µm / sep 25 µm | not reported for CS2 | unquantifiable |
| Particle radius | 2 µm / 2 µm | not reported | unquantifiable |
| Electrode diffusivities | stoichiometry-dependent functions (fit to the original cell) | not reported | unquantifiable |
| Exchange-current densities | functions (fit to the original cell) | not reported | unquantifiable |
| Porosities | neg 0.485 / pos 0.385 / sep 0.508 | not reported | unquantifiable |
| Bruggeman exponent | **4.0** (both electrodes) | n/a | unusually high vs typical 1.5–2; "Frankenstein" evidence |
| Electrolyte | diffusivity/conductivity functions (original cell) | n/a | unquantifiable |
| **Lower voltage cutoff** | **2.8 V** | **2.7 V** | model cannot represent the last 0.1 V of the measured discharge |
| Upper voltage cutoff | 4.2 V | 4.2 V | match |
| OCP curves | original cell's measured OCPs | not measured for CS2 | OCP mismatch translates directly into voltage error |
| Temperature | 25 °C assumed (platform) | unrecorded | assumption #2 above |

### 3.3 What the 200–270 mV RMSE(t) means (and what it does NOT)

The observed baseline errors (CS2_33: 200.37 mV; CS2_35: 269.93 mV,
SPMe) are **expected and correctly interpreted**:

* an unfitted, chemistry-compatible surrogate of a different cell
  (different capacity, geometry, OCP curves, transport values);
* evaluated under a forced-current window at an assumed temperature.

They are NOT evidence that "LCO models fail" nor a model-validation
result. Any future report must carry the machine-readable metadata
already emitted in `run_metadata.json`:

```json
"parameter_match": {
  "level": "compatible_surrogate",
  "grade": "B",
  "parameter_set": "Ramadass2004",
  "fitted_to_dataset": false
},
"capacity_metric_type": "forced_current_window",
"capacity_is_predictive": false,
"temperature_source": "assumed",
"temperature_confidence": "low"
```

**Deliberately not done in v0.2**: fitting Ramadass2004 to CS2,
parameter identification, thermodynamic sensitivity, thermal
modelling. Predictive capacity would require a constant-current run
where the model itself reaches the cutoff — reserved for a future
version.
