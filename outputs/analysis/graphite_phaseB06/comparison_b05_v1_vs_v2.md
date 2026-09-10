# Phase B0.6 — high-fidelity OCP extraction (v1 vs v2)

- dataset `sintef_graphite` / cell `4ccc47`
- v1 input: adapter's DECIMATED trace (global stride 10 -> 100 s)
- v2 input: FULL-RESOLUTION trace (10 s, no stride), verified against the adapter's own file name + SHA256
- SOC definition / Q_ref anchor / branch classification: **unchanged** (same extraction core)
- Q_ref: v1 1.942466 mAh vs v2 1.942466 mAh (relative difference 2.72e-07)

## The defect this fixes

- points above 1.43 V in the lithiation table: **v1 1** -> **v2 5**
  (the measurement itself only carries 5 samples there, so v2 is now AT the data's own resolution)
- v2 keeps all branch endpoints: sampling is fidelity-bounded, not stride-bounded

## Point density and fidelity

| branch | version | n points | SOC 0-0.01 | 0.01-0.10 | 0.10-0.50 | 0.50-1.00 | max err vs measured [mV] |
|---|---|---|---|---|---|---|---|
| lithiation | v1 | 1707 | 18 | 153 | 682 | 854 | 751.109 |
| lithiation | v2 | 933 | 152 | 582 | 88 | 111 | 0.161 |
| delithiation | v1 | 1568 | 0 | 33 | 682 | 853 | 5.830 |
| delithiation | v2 | 638 | 0 | 262 | 256 | 120 | 0.181 |

## Voltage deviation between the two tables [mV]

| branch | SOC range | v1 vs v2 max | v1 vs v2 mean |
|---|---|---|---|
| lithiation | full overlap | 751.109 | 0.274 |
| lithiation | SOC 0 - 0.1 (dense) | 1011.150 | 3.582 |
| delithiation | full overlap | 5.830 | 0.021 |

---

# Phase B0.6 — replay: B0.5_v1 vs B0.5_v2 (high-fidelity OCP)

## Replay: B0.5_v1 vs B0.5_v2 (capacity matched, geometry fixed)

| window | version | RMSE [mV] | MAE [mV] | bias [mV] | table error along the model's x: mean / max [mV] |
|---|---|---|---|---|---|
| lith | v1 | **44.64** | 3.20 | -3.20 | 0.041 / 8.161 |
| lith | v2 | **44.74** | 3.21 | -3.21 | 0.016 / 0.160 |
| deli | v1 | **6.27** | 2.65 | 2.65 | 0.012 / 0.162 |
| deli | v2 | **6.31** | 2.65 | 2.65 | 0.017 / 0.177 |

## Residual by experimental-voltage region (MAE, mV)

| window | region | n points | v1 | v2 | change |
|---|---|---|---|---|---|
| lith | V_exp<=0.15 | 1790 | 1.27 | 1.27 | -0.00 |
| lith | 0.15<V_exp<=0.60 | 169 | 5.83 | 5.81 | -0.02 |
| lith | 0.60<V_exp<=1.43 | 18 | 63.32 | 64.19 | +0.87 |
| lith | V_exp>1.43_outside_ref_table | 1 | 1936.47 | 1939.18 | +2.72 |
| deli | V_exp<=0.15 | 1128 | 1.30 | 1.30 | -0.00 |
| deli | 0.15<V_exp<=0.60 | 832 | 2.89 | 2.89 | +0.01 |
| deli | 0.60<V_exp<=1.43 | 40 | 35.80 | 35.99 | +0.19 |
| deli | V_exp>1.43_outside_ref_table | 0 | nan | nan | +nan |

## Verdicts

**lith** — B0.5_v1 (measured OCP v1 + capacity matched) → B0.5_v2 (measured OCP v2 + capacity matched)
- RMSE 44.64 → 44.74 mV (+0.10); MAE 3.20 → 3.21 mV (+0.01)
- table error along the model's own trajectory: max 8.16 → 0.16 mV; mean 0.041 → 0.016 mV

**deli** — B0.5_v1 (measured OCP v1 + capacity matched) → B0.5_v2 (measured OCP v2 + capacity matched)
- RMSE 6.27 → 6.31 mV (+0.04); MAE 2.65 → 2.65 mV (+0.01)
- table error along the model's own trajectory: max 0.16 → 0.18 mV; mean 0.012 → 0.017 mV

## Wording (mandatory)

The v2 table is an **experiment-derived pseudo-OCP** for this electrode at the declared room temperature, re-sampled from the full-resolution measurement. It is not a material constant, not a fitted curve and **not** validation. The replay is still zero-fit: diffusivity, kinetics and the C/50-polarisation character of the curve are unchanged.

## Not done here

- GITT / D_s (Phase B1)
- any PyBaMM model, geometry or capacity change
