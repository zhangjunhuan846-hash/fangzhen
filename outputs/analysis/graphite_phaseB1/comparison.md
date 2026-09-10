# Phase B1 — GITT apparent D_s(SOC) and the p-OCV replay

- GITT cell `063b77`, p-OCV cell `4ccc47`, model SPM
- pulses segmented: **981** (1800 s pulse / 9000 s rest)
- D_s defined 958 / accepted **616** of 981 pulses

## What this D_s is

> APPARENT / EFFECTIVE solid-state diffusivity, NOT an intrinsic material coefficient: it is R^2 divided by a diffusion time constant fitted to a one-dimensional single-particle model of ONE particle size

- equation: Weppner & Huggins, J. Electrochem. Soc. 124(10) 1569 (1977); forward relation identical to PyBOP 26.3 pybop/models/lithium_ion/weppner_huggins.py (V = U + U'*(2I/(3Q_th))*sqrt(t*tau_d/pi)), inverted here
- particle radius: Positive particle radius [m] of Ecker2015_graphite_halfcell (13.7 um) - a REFERENCE-SET value, NOT measured for this cell; D scales with R^2 so this is the largest systematic uncertainty
- Q_th: F * eps_am * c_max * L * A from the SINTEF catalog metadata of THIS GITT cell (mass-based eps_am, measured thickness and disc area) with c_max from the reference set
- accepted-pulse median D_s: 616 pulses

| quantity | value |
|---|---|
| R (particle radius) | 13.70 um |
| Q_th (GITT cell) | 2.2464 mAh |
| Ecker2015 D (median over SOC) | 1.219e-14 m2/s |

## SOC-resolved apparent D_s

| branch | SOC | n pulses | D_s [cm2/s] | p25 | p75 | rel. uncertainty |
|---|---|---|---|---|---|---|
| delithiation | 0.14 | 1 | 2.101e-09 | 2.101e-09 | 2.101e-09 | 0.0080 |
| delithiation | 0.16 | 9 | 2.260e-09 | 9.575e-10 | 4.487e-09 | 0.0089 |
| delithiation | 0.18 | 8 | 1.062e-10 | 6.009e-11 | 1.474e-10 | 0.0043 |
| delithiation | 0.20 | 10 | 6.133e-12 | 3.697e-12 | 7.547e-12 | 0.0029 |
| delithiation | 0.22 | 10 | 4.063e-12 | 2.987e-12 | 5.983e-12 | 0.0035 |
| delithiation | 0.24 | 10 | 5.188e-11 | 2.998e-11 | 9.205e-11 | 0.0038 |
| delithiation | 0.26 | 10 | 1.074e-10 | 1.048e-10 | 1.177e-10 | 0.0033 |
| delithiation | 0.28 | 10 | 1.048e-10 | 9.920e-11 | 1.185e-10 | 0.0057 |
| delithiation | 0.30 | 10 | 6.660e-11 | 6.075e-11 | 8.633e-11 | 0.0060 |
| delithiation | 0.32 | 10 | 3.280e-11 | 2.613e-11 | 3.773e-11 | 0.0018 |
| delithiation | 0.34 | 11 | 2.116e-11 | 2.010e-11 | 2.183e-11 | 0.0015 |
| delithiation | 0.36 | 10 | 2.104e-11 | 2.020e-11 | 2.221e-11 | 0.0025 |
| delithiation | 0.38 | 10 | 2.372e-11 | 2.241e-11 | 2.517e-11 | 0.0053 |
| delithiation | 0.40 | 10 | 2.529e-11 | 2.439e-11 | 2.764e-11 | 0.0095 |
| delithiation | 0.42 | 8 | 2.566e-11 | 2.171e-11 | 3.077e-11 | 0.0131 |
| delithiation | 0.44 | 2 | 1.196e-11 | 1.189e-11 | 1.203e-11 | 0.0143 |
| delithiation | 0.54 | 3 | 7.322e-13 | 4.661e-13 | 8.846e-13 | 0.0149 |
| delithiation | 0.56 | 8 | 4.445e-14 | 3.826e-14 | 1.444e-13 | 0.0047 |
| delithiation | 0.58 | 9 | 5.244e-14 | 4.087e-14 | 6.327e-14 | 0.0029 |
| delithiation | 0.60 | 11 | 1.223e-13 | 1.003e-13 | 1.754e-13 | 0.0022 |
| delithiation | 0.62 | 10 | 4.463e-13 | 3.273e-13 | 5.652e-13 | 0.0016 |
| delithiation | 0.64 | 10 | 1.684e-12 | 1.144e-12 | 1.948e-12 | 0.0024 |
| delithiation | 0.66 | 10 | 4.474e-12 | 3.576e-12 | 5.342e-12 | 0.0045 |
| delithiation | 0.68 | 10 | 7.434e-12 | 6.408e-12 | 8.556e-12 | 0.0063 |
| delithiation | 0.70 | 10 | 8.696e-12 | 8.094e-12 | 9.676e-12 | 0.0083 |
| delithiation | 0.72 | 10 | 8.323e-12 | 7.425e-12 | 9.257e-12 | 0.0103 |
| delithiation | 0.74 | 10 | 6.150e-12 | 5.514e-12 | 7.570e-12 | 0.0125 |
| delithiation | 0.76 | 10 | 4.759e-12 | 3.947e-12 | 5.152e-12 | 0.0142 |
| delithiation | 0.78 | 8 | 3.656e-12 | 3.281e-12 | 4.305e-12 | 0.0150 |
| delithiation | 0.80 | 6 | 2.887e-12 | 2.651e-12 | 3.291e-12 | 0.0156 |
| delithiation | 0.82 | 1 | 1.822e-12 | 1.822e-12 | 1.822e-12 | 0.0157 |
| delithiation | 0.84 | 2 | 8.856e-13 | 8.011e-13 | 9.701e-13 | 0.0159 |
| delithiation | 0.86 | 4 | 2.033e-13 | 1.878e-13 | 2.810e-13 | 0.0153 |
| delithiation | 0.88 | 6 | 4.728e-14 | 3.678e-14 | 5.612e-14 | 0.0151 |
| delithiation | 0.98 | 5 | 7.631e-12 | 7.236e-12 | 7.699e-12 | 0.0010 |
| delithiation | 1.00 | 5 | 1.093e-11 | 1.035e-11 | 1.251e-11 | 0.0061 |
| lithiation | 0.06 | 5 | 1.446e-09 | 1.322e-09 | 1.671e-09 | 0.0138 |
| lithiation | 0.08 | 5 | 2.769e-09 | 1.170e-11 | 3.029e-09 | 0.0141 |
| lithiation | 0.10 | 8 | 2.385e-10 | 2.097e-10 | 7.839e-10 | 0.0120 |
| lithiation | 0.12 | 9 | 1.984e-11 | 1.906e-11 | 5.835e-11 | 0.0055 |
| lithiation | 0.14 | 11 | 8.444e-12 | 4.504e-12 | 9.680e-12 | 0.0027 |
| lithiation | 0.16 | 10 | 8.289e-12 | 7.563e-12 | 8.905e-12 | 0.0029 |
| lithiation | 0.18 | 10 | 1.274e-11 | 1.139e-11 | 1.957e-11 | 0.0044 |
| lithiation | 0.20 | 9 | 1.292e-11 | 1.245e-11 | 1.593e-11 | 0.0032 |
| lithiation | 0.22 | 8 | 1.783e-11 | 1.673e-11 | 5.406e-11 | 0.0103 |
| lithiation | 0.24 | 8 | 4.007e-11 | 3.484e-11 | 6.839e-11 | 0.0147 |
| lithiation | 0.26 | 7 | 2.431e-11 | 2.379e-11 | 2.444e-11 | 0.0132 |
| lithiation | 0.44 | 2 | 2.612e-13 | 2.532e-13 | 2.693e-13 | 0.0147 |
| lithiation | 0.46 | 5 | 8.896e-13 | 3.406e-13 | 9.260e-13 | 0.0145 |
| lithiation | 0.48 | 10 | 8.763e-13 | 8.587e-13 | 9.660e-13 | 0.0126 |
| lithiation | 0.50 | 10 | 7.210e-13 | 6.674e-13 | 7.984e-13 | 0.0091 |
| lithiation | 0.52 | 10 | 4.398e-13 | 3.617e-13 | 5.199e-13 | 0.0055 |
| lithiation | 0.54 | 10 | 2.903e-13 | 2.832e-13 | 3.301e-13 | 0.0031 |
| lithiation | 0.56 | 4 | 6.305e-13 | 4.652e-13 | 7.499e-13 | 0.0068 |
| lithiation | 0.62 | 4 | 2.532e-12 | 2.006e-12 | 3.231e-12 | 0.0156 |
| lithiation | 0.64 | 8 | 5.257e-13 | 3.326e-13 | 7.114e-13 | 0.0145 |
| lithiation | 0.66 | 10 | 5.223e-14 | 4.181e-14 | 8.956e-14 | 0.0124 |
| lithiation | 0.68 | 10 | 3.421e-14 | 2.571e-14 | 3.871e-14 | 0.0109 |
| lithiation | 0.70 | 10 | 4.907e-14 | 3.648e-14 | 6.661e-14 | 0.0094 |
| lithiation | 0.72 | 10 | 1.026e-13 | 7.894e-14 | 1.318e-13 | 0.0078 |
| lithiation | 0.74 | 10 | 1.825e-13 | 1.402e-13 | 2.265e-13 | 0.0063 |
| lithiation | 0.76 | 10 | 2.778e-13 | 2.064e-13 | 3.217e-13 | 0.0049 |
| lithiation | 0.78 | 10 | 3.588e-13 | 2.892e-13 | 4.440e-13 | 0.0038 |
| lithiation | 0.80 | 10 | 6.243e-13 | 4.907e-13 | 7.737e-13 | 0.0030 |
| lithiation | 0.82 | 10 | 9.019e-13 | 6.969e-13 | 1.114e-12 | 0.0020 |
| lithiation | 0.84 | 10 | 1.363e-12 | 9.947e-13 | 1.602e-12 | 0.0015 |
| lithiation | 0.86 | 10 | 2.082e-12 | 1.544e-12 | 2.486e-12 | 0.0019 |
| lithiation | 0.88 | 10 | 3.092e-12 | 2.250e-12 | 3.720e-12 | 0.0025 |
| lithiation | 0.90 | 10 | 4.193e-12 | 2.794e-12 | 4.591e-12 | 0.0033 |
| lithiation | 0.92 | 11 | 4.842e-12 | 3.006e-12 | 5.119e-12 | 0.0043 |
| lithiation | 0.94 | 10 | 5.058e-12 | 4.437e-12 | 5.644e-12 | 0.0060 |
| lithiation | 0.96 | 9 | 3.675e-12 | 3.153e-12 | 4.939e-12 | 0.0070 |
| lithiation | 0.98 | 10 | 2.980e-12 | 2.304e-12 | 3.285e-12 | 0.0067 |
| lithiation | 1.00 | 6 | 2.369e-12 | 2.238e-12 | 2.475e-12 | 0.0056 |

## Replay: Ecker2015 D vs SINTEF apparent D_s

Both runs use the SAME frozen set (measured geometry, capacity-matched eps_am, OCP v2) — only the diffusivity differs.

| window | diffusivity | RMSE [mV] | MAE [mV] | bias [mV] | max abs [mV] |
|---|---|---|---|---|---|
| lith | Ecker2015 D | **44.741** | 3.210 | -3.206 | 1939.181 |
| lith | SINTEF apparent D_s | **68.566** | 19.345 | -19.341 | 1939.181 |
| deli | Ecker2015 D | **6.313** | 2.654 | 2.654 | 64.662 |
| deli | SINTEF apparent D_s | **373.960** | 112.802 | 112.421 | 2993.291 |

## Residual distribution (mV)

| window | diffusivity | std | p05 | p50 | p95 |
|---|---|---|---|---|---|
| lith | Ecker2015 D | 44.626 | -5.757 | -1.000 | -0.571 |
| lith | SINTEF apparent D_s | 65.781 | -38.890 | -14.074 | -3.836 |
| deli | Ecker2015 D | 5.728 | 0.588 | 1.331 | 9.089 |
| deli | SINTEF apparent D_s | 356.661 | -2.102 | 40.316 | 347.525 |

## Residual by experimental-voltage region (MAE, mV)

| window | region | n points | Ecker D | SINTEF D_s | change |
|---|---|---|---|---|---|
| lith | V_exp<=0.15 | 1790 | 1.270 | 17.868 | +16.598 |
| lith | 0.15<V_exp<=0.60 | 169 | 5.809 | 7.774 | +1.965 |
| lith | 0.60<V_exp<=1.43 | 18 | 64.194 | 82.361 | +18.167 |
| lith | V_exp>1.43_outside_ref_table | 1 | 1939.181 | 1939.181 | +0.000 |
| deli | V_exp<=0.15 | 1128 | 1.296 | 112.802 | +111.506 |
| deli | 0.15<V_exp<=0.60 | 832 | 2.892 | nan | +nan |
| deli | 0.60<V_exp<=1.43 | 40 | 35.995 | nan | +nan |
| deli | V_exp>1.43_outside_ref_table | 0 | nan | nan | +nan |

## What the replay says about the extracted D_s

The two runs differ ONLY in the diffusivity, so the change in RMSE is the replay's verdict on the extracted curve.

| window | Ecker D | GITT D_s | change | model hit a cutoff? |
|---|---|---|---|---|
| lith | 44.74 mV | 68.57 mV | +23.82 mV | comparison window 1978 -> 932 points |
| deli | 6.31 mV | 373.96 mV | +367.65 mV | comparison window 2000 -> 434 points |

### Verdict

Swapping in the GITT-derived apparent D_s makes BOTH windows **worse**, and in the delithiation window the model runs into the upper voltage cut-off (the comparison window collapses), i.e. the model becomes diffusion-starved.  The extracted curve is therefore **not adopted** as the model's diffusivity.

Accepted pulses: median D_s = 3.782e-16 m2/s (p01 2.94e-18, p99 2.69e-13) against the reference-set value 1.219e-14 m2/s — about 32x SMALLER, with a spread of many orders of magnitude across SOC.

A first-order Weppner-Huggins surface excursion over the p-OCV window would be

| window | Ecker D | GITT D_s |
|---|---|---|
| lith | 10.75 mV | 98.94 mV |
| deli | 20.35 mV | 77.73 mV |

so the extracted D_s predicts a polarisation the measured C/50 p-OCV does not show.  The single-particle inversion is attributing to solid diffusion an overpotential that the porous electrode, the electrolyte and the pseudo-OCP's own polarisation also contribute to — which is exactly the caveat attached to every GITT-derived 'apparent' diffusivity.

### What this does NOT mean

- it does NOT mean the reference (Ecker) D is correct: it is a published fit for a different cell, and it was never validated here either;
- it does NOT invalidate the extraction code: the Weppner-Huggins inversion recovers a known diffusivity exactly in the forward test (`test_weppner_huggins_inversion_recovers_a_known_D`).  What it means is that the SINGLE-PARTICLE MODEL is the wrong lens for this dataset, and the result is reported as an apparent parameter that failed a consistency check.

## Honest limitations of this D_s

- accepted 616 of 981 pulses; rejected 365 (weak sqrt(t) fit, OCP not locally linear, SOC outside the branch table, or a direction inconsistent with I*U')
- the OCP-free cross-check disagrees with the pulse route (median sqrt(D_relax/D_pulse) = 10.9384), so the single-particle Weppner-Huggins regime is only partially satisfied across this pulse train
- D scales with R^2, and R comes from the REFERENCE set, not from a measurement of this material
- uncertainty reported is the 0.9 R^2-gated regression noise only; systematics dominate

## Wording (mandatory)

**Apparent/effective** solid diffusivity, NOT an intrinsic material coefficient and NOT validation.  The p-OCV replay is a consistency check whose diffusion sensitivity is negligible at C/50.
