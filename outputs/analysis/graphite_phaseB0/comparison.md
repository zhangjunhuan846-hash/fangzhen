# Phase B0 — experiment-derived graphite OCP (Ecker2015 + SINTEF p-OCV)

- dataset `sintef_graphite` / cell `4ccc47` / model SPM
- geometry: Phase A.5 measured geometry (unchanged)
- diffusivity / kinetics: **unchanged** (no GITT in this phase)
- OCP extraction: cycle 1, both branches, Q_ref = 1.942 mAh

## What the extracted OCP is

> pseudo-OCP: extracted from a ~C/50 galvanostatic p-OCV with rests only at the branch endpoints. The curve therefore contains the C/50 polarisation (lithiation branch biased low, delithiation branch biased high) and is NOT a true equilibrium OCP. Using it as the model OCP double-counts that polarisation, so the replay residual is a conservative (pessimistic) estimate. Not a material constant: it is the measured quasi-equilibrium response of this electrode at the declared room temperature.

- hysteresis at fixed SOC: SOC_0.20 → 134.8 mV, SOC_0.50 → 85.8 mV, SOC_0.80 → 64.7 mV
- hand-over gap (NOT hysteresis): 86.7 mV
- C/50 polarisation estimate at the hand-over: 14.3 mV (recorded only)

## Results (zero-fit; nothing fitted to any voltage)

| window | OCP variant | RMSE [mV] | MAE [mV] | bias [mV] | V_sim span [mV] | span ratio |
|---|---|---|---|---|---|---|
| lith | phaseA | **875.75** | 867.93 | 866.28 | 620.0 | 0.206 |
| lith | A5_reference | **81.39** | 67.81 | 66.16 | 1289.0 | 0.429 |
| lith | lithiation | **45.05** | 7.75 | 4.95 | 1038.0 | 0.345 |
| deli | phaseA | **150.06** | 98.63 | -98.63 | 1.1 | 0.001 |
| deli | A5_reference | **109.12** | 61.86 | -61.86 | 116.4 | 0.127 |
| deli | delithiation | **91.86** | 31.19 | -30.87 | 127.5 | 0.139 |
| deli | mean | **397.42** | 144.10 | 114.06 | 2972.9 | 8.534 |

## Residual distribution (mV)

| window | variant | std | p05 | p50 | p95 | max abs |
|---|---|---|---|---|---|---|
| lith | phaseA | 128.44 | 733.86 | 843.09 | 1072.39 | 1643.87 |
| lith | A5_reference | 47.40 | 35.00 | 64.56 | 87.52 | 1643.87 |
| lith | lithiation | 44.78 | 0.39 | 4.67 | 21.55 | 1936.47 |
| deli | phaseA | 113.10 | -319.93 | -66.70 | -31.53 | 918.76 |
| deli | A5_reference | 89.89 | -219.22 | -33.85 | -24.15 | 803.51 |
| deli | delithiation | 86.52 | -171.59 | -4.39 | 0.70 | 762.69 |
| deli | mean | 380.71 | -30.98 | -15.29 | 1194.00 | 2624.60 |

## Residual by experimental-voltage region (MAE, mV)

The `V_exp>1.43` region is exactly where the published reference OCP
table has no data (H1).

| window | region | A5 control (Ecker OCP) | best derived OCP |
|---|---|---|---|
| lith | V_exp<=0.15 | 61.75 | 5.34 |
| lith | 0.15<V_exp<=0.60 | 105.82 | 17.82 |
| lith | 0.60<V_exp<=1.43 | 232.48 | 48.38 |
| lith | V_exp>1.43_outside_ref_table | 1643.87 | 1936.47 |
| deli | V_exp<=0.15 | 31.20 | 2.30 |
| deli | 0.15<V_exp<=0.60 | 79.49 | 46.89 |
| deli | 0.60<V_exp<=1.43 | 560.07 | 519.11 |
| deli | V_exp>1.43_outside_ref_table | nan | nan |

## Hypothesis check (Phase A.5 findings)

**lith**: best derived variant `lithiation`
- control (Ecker OCP, measured geometry) RMSE 81.39 → 45.05 mV (×0.55)
- V_sim span ratio 0.429 → 0.345
- region MAE change [mV]: V_exp<=0.15 -56.41, 0.15<V_exp<=0.60 -88.00, 0.60<V_exp<=1.43 -184.10, V_exp>1.43_outside_ref_table +292.60

**deli**: best derived variant `delithiation`
- control (Ecker OCP, measured geometry) RMSE 109.12 → 91.86 mV (×0.84)
- V_sim span ratio 0.127 → 0.139
- region MAE change [mV]: V_exp<=0.15 -28.89, 0.15<V_exp<=0.60 -32.60, 0.60<V_exp<=1.43 -40.96, V_exp>1.43_outside_ref_table +nan

## Wording (mandatory)

The derived OCP is an **experiment-derived pseudo-OCP** for this
electrode at the declared room temperature. It is not a material
constant and not validation. Diffusivity and kinetics are still the
published reference values, so any residual left in the low-voltage
region is a hypothesis for Phase B1 (GITT), not a conclusion.
