# PyBaMM Battery Simulation Platform

Physics-based lithium-ion battery simulation: replay measured cycling data with
PyBaMM (SPM / SPMe / DFN), compare against experiment, and analyse residuals.
**Zero-fit by design** — the platform never fits parameters to a dataset unless a
phase explicitly says so.

Platform core `battery_sim/` is **frozen at v0.4**. Scientific logic
(runner / evaluator / model factory) must not be changed.

---

## 1. Environment (read this first)

All simulation runs in **WSL Ubuntu**, conda env `pybamm` (Python 3.11,
PyBaMM 26.8.0.0, casadi 3.7.2, numpy 2.3.5). Windows Python has no PyBaMM.

```bash
wsl.exe -d Ubuntu -e bash -lc 'source ~/miniforge3/etc/profile.d/conda.sh \
  && conda activate pybamm && cd /mnt/c/Users/24330/WorkBuddy/仿真模拟 \
  && python run_pipeline.py --list-datasets'
```

Install: `pip install -r requirements.txt` (numpy **must stay <2.4**, PyBOP requires it).

---

## 2. Entry point

```bash
python run_pipeline.py --config configs/example.yaml  # one-shot YAML run (recommended)
python run_pipeline.py <task> [options]      # positional task
python run_pipeline.py --mode <task> [opts]  # equivalent, historical form
```

List registered datasets:

```bash
python run_pipeline.py --list-datasets
```

Minimal end-to-end case with a real experimental CSV (no 13 GB data dir needed):
see **`examples/half_cell_demo/`** — raw CSV → import/validate → zero-fit DFN
baseline → committed expected results (`RMSE 104.29 mV`).

---

## 3. Available tasks

| Task | What it does | Command |
|---|---|---|
| `baseline` | **Primary.** Time-aligned V(t) replay of the measured current profile; writes `*_time_aligned.csv` + `metrics.csv` (RMSE/MAE/bias, mV) | `python run_pipeline.py baseline --dataset chen2020 --model SPMe --cell 02` |
| `benchmark` | Model × cell sweep + runtime/cost comparison | `python run_pipeline.py benchmark --dataset chen2020 --models SPM SPMe DFN --cells all` |
| `reproduction` | Capacity-aligned (Q) replay, the v0.1 legacy metric | `python run_pipeline.py reproduction --dataset chen2020 --model SPMe --cell 02` |
| `sensitivity` | One-at-a-time (OAT) parameter perturbation study | `python run_pipeline.py sensitivity --dataset chen2020 --model SPMe --cell 02 --parameter Dsn` |

Common options: `--dataset`, `--model/--models`, `--cell/--cells`, `--rate`
(or `--protocol`, dynamic datasets), `--parameter` (sensitivity), `--no-plot`.

**One-shot config**: `--config <yaml>` mirrors all of the above in a single
file (`configs/example.yaml` documents the schema). Explicit CLI flags win
over config values. A `condition.temperature` entry is echoed for the record
but never silently overrides the dataset-native experiment (zero-fit discipline).

Tasks take **no positional arguments beyond the task name**; everything else is a flag.
Default dataset is `chen2020`, default mode `reproduction`.

---

## 4. Datasets (`configs/datasets.yaml`)

| id | Chemistry | Parameter set | Match | Protocol |
|---|---|---|---|---|
| `chen2020` | NMC811/graphite (LG M50) | `Chen2020` | **A** exact | CC (C/10…1.5C) |
| `calce_cs2` | LCO/graphite (CS2) | `Ramadass2004` | B surrogate | CC |
| `calce_20r` | NMC/graphite (INR18650-20R) | `Chen2020` | B surrogate | DST/FUDS/US06 |
| `calce_a123` | LFP/graphite (A123 18650) | `Prada2013` | B surrogate | DST/FUDS/US06 |
| `birmingham_ncm920305` | NMC **half-cell** ‖ Li | `Jackowska2025_2mAh_cm2` | A | CC C/10…2C |

Matching grade: **A** = exact parameter set for that cell; **B** = chemistry-compatible
surrogate; **C** = incompatible. CALCE results are surrogates — **never call them validation**.

---

## 5. Configs

| File | Purpose |
|---|---|
| `configs/datasets.yaml` | Dataset registry: id, chemistry, cells, rates, parameter set, models, paths |
| `configs/chemistry.yaml` | **Explicit chemistry layer**: chemistry id → electrodes/electrolyte/cell form/parameter set + provenance grade. This is the mapping target for literature-agent output like `NMC811\|\|graphite` |
| `configs/models.yaml` | Model ids (SPM / SPMe / DFN) and options |
| `configs/sensitivity.yaml` | OAT parameter list, perturbation levels, metrics |
| `configs/example.yaml` | One-shot run config schema (use with `--config`) |

---

## 6. Outputs

```
outputs/
├── platform/<dataset>/<task>/<MODEL>/cell<id>/
│     ├── metrics.csv              # one row per window: rmse/mae/bias/max_abs (mV)
│     ├── <rate>_time_aligned.csv  # baseline: t, V_exp, V_sim, residual
│     ├── <rate>_Vt.png
│     └── run_metadata.json        # provenance: parameter set, pybamm version, options
├── analysis/                      # scientific analysis (read-only consumer of platform outputs)
│     ├── residual_atlas/          # A1: cross-dataset residual decomposition
│     ├── targeted_sensitivity/    # A2: residual-aligned OAT sensitivity
│     ├── lfp_h1/                  # half-cell H1-B/C/D0 (LFP)
│     └── lfp_gitt_audit/          # new LFP CC+GITT+EV dataset audit
├── user_datasets/                 # self-service imports (validation report + canonical)
└── (legacy: baseline/, reproduction/, sensitivity/, protocol_reproduction/,
     fitting/, validation/, _legacy_*, _golden_backup_* — v0.1–v0.3 leftovers, not current)
```

---

## 7. Repository layout

```
run_pipeline.py        CLI entry point (task dispatch)
battery_sim/           FROZEN platform package
  datasets/            one adapter per dataset (raw -> canonical)
  simulation/          baseline.py benchmark.py reproduction.py sensitivity.py
  models/              PyBaMM factory + external parameter-set routing
  evaluation/          metrics + plotting
  paths.py registry.py schemas.py rates.py protocols/
analysis/              scientific analysis (A1/A2), does not modify battery_sim/
scripts/               phase scripts (half-cell H0/H1-*, dataset audits)
user_tools/            self-service importer (CSV/XLSX -> canonical -> zero-fit baseline)
user_dataset_template/ double-click package for experimental users
examples/              minimal reproducible cases (half_cell_demo: real CSV in,
                       platform out, committed expected results)
docs/                  phase reports and method notes
tests/                 98 tests (regression gate)
data/raw/              datasets (gitignored, ~13 GB)
```

---

## 8. Invariants — do not break

1. **Frozen core**: do not modify runner / evaluator / model-factory scientific logic.
2. **Run the gate**: `python -m pytest tests -q` must stay **98 passed** after any change
   (88 core + 10 run-config/chemistry registry).
3. **Zero-fit**: baseline never fits parameters. Fitting requires its own phase and lock file.
4. **Sign convention**: canonical `current_A` is **discharge = +**, charge = −.
   Adapters convert from the source convention; never re-flip downstream.
5. **Capacity semantics**: baseline capacity is `forced_current_window`
   (`capacity_is_predictive = False`) — Q_sim ≈ Q_exp by construction, never a prediction.
6. **Vocabulary**: surrogate results may be "consistent / inconsistent", never "validated".
7. **Provenance**: every run writes `run_metadata.json`; never silently swap a parameter set.

---

## 9. Sub-projects (separate from the frozen core)

- **`analysis/`** — A1 Residual Atlas (`residual_atlas.py`) and A2 Residual-guided
  Targeted Sensitivity (`targeted_sensitivity/`). Reads platform outputs; writes to
  `outputs/analysis/`. **Not** a fitting stage: A2 reports *candidate explanatory
  directions* only, never "identified parameter" / "root cause".
- **`scripts/`** — half-cell work (H0 Birmingham reproduction, H1-A/B/C/D0 LFP‖Li) and
  dataset audits (`lfp_gitt_audit.py`). All zero-pybamm unless a script says otherwise.
- **`user_tools/` + `user_dataset_template/`** — self-service onboarding: an experimental
  user drops CSV/XLSX into `raw/`, fills `dataset_info.xlsx`, double-clicks
  `导入并检查数据.bat` then `运行仿真.bat`. Explicit mapping only — no guessing of
  chemistry, units, sign, or parameter set.

---

## 10. Tests

```bash
wsl.exe -d Ubuntu -e bash -lc 'source ~/miniforge3/etc/profile.d/conda.sh \
  && conda activate pybamm && cd /path/to/this/repo \
  && python -m pytest tests -q'
```

Golden regression values are asserted in `tests/` (e.g. Chen2020 SPMe cell02
82.33 / 115.81 / 70.02 / 46.84 mV). Changing a number means a new phase, not an edit.

---

## 11. External code (vendored)

`external/Jackowska-2025-JPS` is vendored, not pip-installed. Upstream:
https://github.com/Battery-Intelligence-Lab/Jackowska-2025-JPS
(BSD 3-Clause, see `external/Jackowska-2025-JPS/LICENSE`), pinned at commit
`9f3b526`. The `Jackowska2025_2mAh_cm2` parameter set loads its OCP CSVs
(`2mAh_cm2/results/ocp_*.csv`) at runtime — keep the directory intact,
do not modify it, do not `pip install` it (its own pyproject pins older
PyBaMM versions and would break this environment).

---

## 12. License

This repository's own code (`battery_sim/`, `analysis/`, `scripts/`,
`user_tools/`, `tests/`, configs) is released under the MIT License — see
[`LICENSE`](LICENSE). Vendored third-party code retains its own license
(`external/Jackowska-2025-JPS`: BSD 3-Clause).
