# CALCE CS2 Vertical-Slice Provenance (收紧 D)

**Status**: verified 2026-09-07, audit script
`scripts/audit/audit_vertical_slice_provenance.py` (read-only).

## Selected segment (rule-based, no hard-coded locator)

| Field | Value |
|---|---|
| Source file | `CS2_33_8_17_10.xlsx` (first file in **chronological** order; filename sort key M_D_YY = Aug 17, 2010) |
| Original cycle / step | cycle **1** / step **7** (as recorded in the Arbin file) |
| Selection rule | current sign (canonical discharge +), CC amplitude within ±10 % of expected 0.55 A, ≥10 points, monotonic voltage drop, V_start ≥ 4.2 − 0.15 V, V_end ≤ 2.7 + 0.15 V |
| n points | 760 (30 s sampling) |
| Median current | **0.550173 A** (expected 0.55 A, deviation +0.03 %) |
| Voltage start / end | **4.118745 V → 2.699699 V** |
| Duration | 7590.15 s |
| Integrated capacity | **1.1602 Ah** (trapezoidal I(t); NOT the Arbin cumulative column) |
| Canonical rate | c_rate = 0.5, label "C/2", slug `C0p5`, source label `0p5C` |

## Preceding step history (proves full-discharge, not file-split partial)

Raw `Current(A)` signs are CALCE (charge = +, discharge = −); the
table below shows canonical signs (discharge = +) after the
adapter's T1 flip.

| step | n_pts | I start→end [A] | I median [A] | V start→end [V] | duration [s] | inferred mode |
|---|---|---|---|---|---|---|
| 1 | 12 | −0.000 → −0.000 | 0.000 | 3.3796 → 3.3796 | 110.0 | rest (storage V ≈ 3.38 V) |
| 2 | 674 | −0.5500 → −0.5502 | −0.5500 | 3.4943 → 4.2001 | 6731.2 | **CC charge 0.5C → 4.2 V** |
| 3 | 4 | 0 → 0 | 0.000 | 4.1171 → 4.0969 | 90.0 | brief rest (see note) |
| 4 | 20 | −0.9819 → −0.0500 | −0.5065 | 4.2002 → 4.2001 | 2325.9 | **CV hold at 4.2 V, cutoff I ≤ 0.05 A** |
| 5 | 2 | 0 → 0 | 0.000 | 4.1925 → 4.1913 | 30.0 | rest |
| 6 | 1 | +0.0012 → +0.0012 | 0.0012 | 4.1929 → 4.1929 | 0.0 | single-point transition (T5 pseudo-step) |
| **7** | **760** | **+0.5502 → +0.5504** | **+0.5502** | **4.1187 → 2.6997** | **7590.2** | **full CC discharge → 2.7 V** |
| 8–9 | 1, 2 | ≈0 | ≈0 | 3.038 → 3.043 | ≈0–5 | post-discharge transition points |

**Conclusion**: step 7 is preceded, inside the *same file*, by the
complete protocol `rest → CC charge 0.5C → 4.2 V → CV to 0.05 A →
rest → full discharge to 2.7 V`. It is therefore a genuine
beginning-of-life full discharge, **not** a partial segment created
by file splitting (trap T4). The discharge also terminates exactly
at the 2.7 V cutoff and starts from the post-CV rest relaxation
(4.119 V), which is what `get_initial_state()` reports (rest
last-5-min median).

## Sanity notes (recorded honestly)

1. **Step-3 voltage dip**: the 4-point, 90 s "rest" between CC
   charge and CV records V ≈ 4.12 → 4.10 V, below the CV level of
   step 4. This is an Arbin logging quirk (step rows interleave
   near the CC→CV transition); the CC charge itself ends at
   4.2001 V and the CV holds 4.200 V. It does not affect the
   selected discharge segment.
2. **Discharge starts at 4.119 V, not 4.2 V**: expected physics —
   the cell relaxes during the post-CV rest before the discharge
   begins. `get_initial_state()` (last-5-min rest median) captures
   exactly this value, so the simulation starts from the measured
   rest OCV.
3. **First-cycle coulombic accounting** (CC ≈ 1.03 Ah + CV ≈ 0.33 Ah
   charged vs 1.16 Ah discharged) is not unity, as expected for a
   cell recorded from an uncontrolled BOL state (storage voltage
   3.38 V at file start); this is irrelevant to the baseline
   replay, which uses only the measured discharge current.

## Legacy naming note

The original Step-14 outputs (source-label naming `0p5C_*` /
`1C_*`) are preserved verbatim under
`outputs/_legacy_v02_step14/baseline/SPME/cell{33,35}/`.
Canonical-schema reruns (slug naming `C0p5_*`) reproduce the
legacy RMSE **bit-identically** (Δ = 0.0 mV, see
`scripts/audit/cmp_legacy_step14.py`).
