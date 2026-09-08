# Half-cell real-data reproduction benchmark — Birmingham NCM920305 ‖ Li (H0)

**Status:** H1–H10 complete — pilot **frozen**, zero fitting.
**Platform:** v0.4 + additive half-cell capability (H4–H7). `battery_sim/` core runners unchanged for the four frozen datasets (zero-regression gate green).
**Reproduction commands** and every artifact are listed in §7.

This pilot's single goal (per the review brief) was to prove the platform can carry a **real, public, matched half-cell data–parameter–model system without distortion**. It is a *platform / methodology* benchmark, NOT a chemical baseline for recycled LFP, and it is deliberately closed with **no optimisation, no GITT/EIS/pOCV fitting, no SINTEF**.

---

## 1. Is the dataset matched? — YES (numerically matched)

- Raw files: `data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw/` (9 CSVs; 5 replayable RateCapability files at C/10…2C + pOCV/GITT/EIS recorded only).
- Author repo: `external/Jackowska-2025-JPS` (clone `9f3b526`), parameter set `Jackowska2025_2mAh_cm2`.
- **Wording discipline (per review):** *numerically matched to the experimental dataset used in the authors' reported simulations* — NOT "cryptographically identical". Evidence (H2 identity check): our 5 rate files and the authors' saved model-output CSVs share **row-for-row identical time grids** (924 / 679 / 554 / 527 / 490 rows), and our voltage differs from their logged absolute error closure by ~0.025 mV median / ~0.053 mV max.
- Geometry cross-check: disc d = 14.8 mm → 1.72 cm², consistent with experimental 1C = 3.44 mA; R_ct = 22.4 Ω, 2.5/4.2 V window, 298.15 K all match. → `parameter_match: level=exact, grade=A, fitted_to_dataset_family=true`.

## 2. Can the author parameterisation be built on the current PyBaMM? — YES (with a documented mapping)

- Preflight (H3) under **PyBaMM 26.8.0.0**: `Jackowska2025_2mAh_cm2` loads by direct module import (no pip install — the repo pins PyBaMM 25.8.0 / numpy 1.26.4 / PyBOP 25.6 and must not be installed into this env). DFN and SPMe both build/process with the author options `{"working electrode": "positive", "surface form": "differential", "contact resistance": "true"}`.
- H5 auditable mapping table (per-run `*_parameter_mapping.json`): the only PyBaMM-26.8 materialisation is the alias key `Positive particle diffusivity scaling factor` (=1.0, auto-copied from the author's legacy key `Positive electrode diffusivity scaling factor`); no author key is renamed, dropped, or re-purposed.
- The **published default initial concentration (5e3 mol/m³ ⇒ x ≈ 0.10) is unusable**: it contradicts the measured ~4.19 V rest OCV. Following the authors' own figure_5 convention the adapter maps the measured rest OCV through their OCP curve. Because the measured OCV (4.1935 V) sits *above* the tabulated OCP top (4.18595 V), the inversion uses **linear extrapolation** (identical to PyBaMM's linear Interpolant, verified bit-for-bit) → x0 = 0.3028 ⇒ c_s = 14 906 mol/m³. This is an *initialisation convention from data*, not a fitted parameter.

## 3. Does platform wiring change the model result? — NO (Gate A, machine precision)

| check | platform (frozen baseline) | independent replay (same inputs) | verdict |
|---|---|---|---|
| C/10 DFN V(t) | `outputs/platform/birmingham_ncm920305/baseline/DFN/cell2mAhcm2/C0p1_time_aligned.csv` | `scripts/halfcell_birmingham/gate_ab_c10.py` standalone pybamm solve | **max\|ΔV\| = 0.000000 mV** (mean 1.4×10⁻¹³ mV) |

Adapter → schema → registry → parameter-source layer → factory → runner → evaluator is therefore **lossless** for the half-cell path.

## 4. As-published reproduction error across rates (Gate B / H8-A, zero fitting)

Frozen platform baseline: `outputs/platform/birmingham_ncm920305/baseline/DFN/cell2mAhcm2/metrics.csv` (D scaling = 1.0, measured current replay, inverse-OCP init).

| rate | RMSE(t) [mV] | bias [mV] | coverage | Q_sim / Q_exp | model cut-off at |
|---|---|---|---|---|---|
| C/10 | 102.26 | −41.2 | 0.874 | 2.633 / 3.014 mAh (−12.6%) | 87.4 % of exp. time |
| C/5  | 79.34  | −43.0 | 0.842 | −15.8 % | 84.2 % |
| C/2  | 116.40 | −63.4 | 0.811 | −19.1 % | 81.1 % |
| 1C   | 101.74 | −94.8 | 0.774 | −23.1 % | 77.4 % |
| 2C   | 185.14 | −173.0 | 0.734 | −27.6 % | 73.4 % |

**Observed residual structure (C/10, platform CSV):** bias-like −5…−50 mV over the first ~90 % of progress; the final decile collapses to −1065 mV as the model exhausts its OCP window (x → ~0.895, V → 2.5 V) while the experiment is still at ~3.62 V. The residual is therefore dominated by a **capacity / geometry mismatch, not by voltage-shape error at matched state**.

**Attribution (factual; NOT fitted):**
1. The public set's own geometric capacity is `Nominal cell capacity = 3.112 mAh`, while the experimental electrode implies ~3.44 mAh (1C = 3.44 mA) — i.e. the set is ~10–14 % light on capacity. The model's capacity constant implied by its own solve is ≈ 0.00445 Ah/Δx vs ≈ 0.00508 Ah/Δx implied by the experiment → the model reaches the 2.5 V end of the OCP table (~13 % of charge) before the experiment.
2. Diffusivity scaling alone cannot correct a capacity offset. H8-B (author per-rate fitted D = 1.157…12.262, `outputs/analysis/halfcell_h8/h8_rate_table.csv`) raises coverage (e.g. 2C 0.734→0.852) but cannot reach the experimental cutoff capacity either.
3. The authors' *saved* figure_5 results (results/*_discharge.csv, V_min = 2.5159 V, full experimental capacity) were produced from an **internal parameter chain** (`parameters_after_*.pickle`, PyBaMM 25.8; module renamed `Jackowska2024`→`Jackowska2025`, class internals changed `_store`→`store`) and are **not reproducible from the public set alone** under 26.8. That is a property of the released artefacts, not of the platform.

**Interpretation rule respected:** we do not claim "the model is wrong"; we state the public set, taken out-of-the-box with the measured-current convention, under-delivers capacity in this matched replay; any later calibration (out of scope here) would start from this **frozen as-published baseline**.

## 5. What was changed in core code (half-cell extension)

| file | change | regression risk |
|---|---|---|
| `configs/datasets.yaml` | first-class `birmingham_ncm920305` entry (`cell_configuration/working_electrode/counter_electrode/model_options/parameter_source/initialisation_ocp_file_rel`, grade A metadata) | none (new dataset) |
| `battery_sim/models/parameter_sources.py` (new) | external author parameter-set registry; direct module import; sha256/repo-commit; auto-materialised-key audit | none (not on frozen path) |
| `battery_sim/models/pybamm_factory.py` | `build_model(name, options=None)`; `build_model_options()`; `load_parameter_values` external route | default `options=None` ⇒ identical old construction |
| `battery_sim/datasets/birmingham_ncm920305.py` (new) | pure-data adapter: sign flip (discharge +), rule window = rest + single CC to the 2.5 V cutoff row (min-V), inverse-OCP with linear extrapolation, provenance+sha256, initialisation block | none (pure I/O, no pybamm) |
| `battery_sim/simulation/baseline.py` | `_run_one_replay(..., model_options)`; `fixed_initial_concentration` init branch (override before Simulation build); per-rate `*_parameter_mapping.json`; metadata half-cell block — all additive, gated on half-cell/init-block presence | frozen full-cell path byte-identical (see §6) |
| `run_pipeline.py` | display fix only (rate string shown as a list) | none |
| `tests/test_birmingham_halfcell.py` (new) | 14 tests: schema, adapter window/x0, options, external registry, alias audit, one C/2 replay-consistency test | new tests only |

## 6. Regression gate

- Full suite in the `pybamm` env (PyBaMM 26.8.0.0): **88 passed** (74 frozen-platform tests + 14 new Birmingham tests).
- Zero-regression byte gate on a frozen dataset (Chen2020 SPMe cell02, full baseline rerun): all 5 `*_time_aligned.csv` **byte-identical**; `metrics.csv` column schema identical (51 cols) and all 40 scientific numeric columns identical — the only differing column is `runtime_s` (wall clock).

## 7. Reproducibility & artifacts

```text
docs/halfcell_birmingham_audit.md            H1 data audit
docs/halfcell_birmingham_params_audit.md      H2 parameter-set + identity audit
scripts/halfcell_birmingham/preflight_h3.py   H3 preflight (PASS)
scripts/halfcell_birmingham/gate_ab_c10.py    H7 Gate A/B
scripts/halfcell_birmingham/h8_fitted_scaling.py  H8-B
scripts/halfcell_birmingham/probe_*.py, debug_window_h7.py, diff_public_vs_pickle_h7.py  (diagnostics)
outputs/platform/birmingham_ncm920305/baseline/DFN/cell2mAhcm2/   frozen as-published baseline
    metrics.csv | run_metadata.json | C0p1..C2_time_aligned.csv | C0p1..C2_Vt.png | *parameter_mapping.json
outputs/analysis/halfcell_h8/h8_rate_table.csv    H8-B D-scaling attribution
tests/test_birmingham_halfcell.py
```

Key command (first replay):

```bash
python run_pipeline.py --dataset birmingham_ncm920305 --mode baseline \
    --model DFN --cell 2mAhcm2 --rate Cover10   # source tokens Cover10..2C
```

## 8. Stop condition respected — and what this pilot does / does not claim

Done: C/10 → 2C as-published replays, Gate A/B, regression gate, provenance manifests (per-rate mapping JSON: dataset file sha256, OCP file sha256, author repo commit, PyBaMM version, solver rtol/atol). **Not done** (out of scope, frozen): GITT/EIS/pOCV fitting, PyBOP optimisation, per-rate fits as "material constants", SINTEF LFP, any use of the internal pickles.

Claim: **the platform can now carry a real matched half-cell system losslessly, and its out-of-the-box reproduction quality is bounded by the released public parameter set's capacity inconsistency — a documented, frozen starting point for any future calibration.** Next (per the staged plan, not yet started): a matched **public pristine-LFP ‖ Li** dataset, before the recycled-LFP target domain.
