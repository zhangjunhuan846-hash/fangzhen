# Phase B2 — GITT apparent $D_s$: credibility assessment and
## when the extracted diffusivity can be a model input

Phase B2 does **not** fit, tune or re-extract anything.  It asks a
narrower question: **when is the GITT-derived apparent $D_s$ trustworthy as a model input, and when is it irrelevant?**

```
D_s credibility  ->  per-pulse diagnostics + validity flags (B2.1)
D_s sensitivity  ->  constant-D lattice 1e-17..1e-13 m2/s (B2.2)
                      pOCV replay        (experiment available)
                      C/50, 0.5C, 1C, 2C (MODEL-ONLY)
                      SPM and SPMe
criterion        ->  Fo = D t / R^2          (B2.3)
```

- cells: p-OCV `4ccc47`, GITT `063b77`; frozen OCP = Phase B0.6 v2
- lattice: 1e-17, 3e-17, 1e-16, 3e-16, 1e-15, 3e-15, 1e-14, 3e-14, 1e-13 m2/s (9 values)
- $R$ = 13.700 um **from the reference set, not measured** (so $D \propto R^2$ and every $\tau_d$ below carries that systematic)
- $Q_{nom}$ = 1.9425 mAh (capacity-matched set)
- reference diffusivity (Ecker2015 at SOC 0.5) = 1.219e-14 m2/s

## 0. What the data can and cannot support

This cell was measured with a **p-OCV** programme (≈C/50, 41 h) and a
**GITT** programme.  It has **no rate-capability data**.  Therefore:

| column | experiment? | what a change in it means |
|---|---|---|
| p-OCV replay | **yes** | a real RMSE change |
| 0.5C / 1C / 2C | **no** | a model-only forward simulation; the
| | | comparison is between model runs, never against data |

## 1. $D_s$ diagnostics (B2.1)

`Ds_diagnostics.csv` — 981 pulses, **616 valid** (62.8 %), 365 rejected.

| field | meaning |
|---|---|
| `SOC` | pulse midpoint, same charge-based axis as the frozen OCP |
| `Ds_app_m2_s` / `Ds_app_cm2_s` | apparent/effective diffusivity |
| `WH_fit_R2` | $R^2$ of $V = a + m\sqrt{t}$ over the pulse |
| `dE_pulse_mV` | measured pulse overpotential |
| `dE_relax_mV` | measured relaxation overpotential |
| `OCP_slope_V_per_soc` | $U'$ from the frozen Phase B0.6 table |
| `validity_flag` | `valid` / `rejected` (+ `rejection_reasons`) |

Rejection counts (a pulse can fail more than one gate):

- `r2_below_threshold` — 258 pulses
- `ocp_not_locally_linear` — 63 pulses
- `direction_inconsistent` — 45 pulses
- `undefined` — 23 pulses
- `ocp_slope_unavailable` — 23 pulses

Per-SOC rollup (`Ds_diagnostics_by_soc.csv`) — the surviving spread:

| branch | SOC | n_pulses | n_valid | valid_fraction | Ds_median_m2_s | Ds_decades_spanned | Fo_pulse_median |
|---|---|---|---|---|---|---|---|
| delithiation | 0.04 | 5 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.06 | 8 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.08 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.10 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.12 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.14 | 10 | 1 | 0.10 | 2.101e-13 | n/a | 2.0146 |
| delithiation | 0.16 | 10 | 9 | 0.90 | 2.260e-13 | 2.14 | 2.1675 |
| delithiation | 0.18 | 10 | 8 | 0.80 | 1.062e-14 | 0.57 | 0.1018 |
| delithiation | 0.20 | 10 | 10 | 1.00 | 6.133e-16 | 0.83 | 0.0059 |
| delithiation | 0.22 | 10 | 10 | 1.00 | 4.063e-16 | 0.67 | 0.0039 |
| delithiation | 0.24 | 10 | 10 | 1.00 | 5.188e-15 | 0.75 | 0.0498 |
| delithiation | 0.26 | 10 | 10 | 1.00 | 1.074e-14 | 0.15 | 0.1030 |
| delithiation | 0.28 | 10 | 10 | 1.00 | 1.048e-14 | 0.28 | 0.1005 |
| delithiation | 0.30 | 10 | 10 | 1.00 | 6.660e-15 | 0.53 | 0.0639 |
| delithiation | 0.32 | 10 | 10 | 1.00 | 3.280e-15 | 0.33 | 0.0315 |
| delithiation | 0.34 | 11 | 11 | 1.00 | 2.116e-15 | 0.22 | 0.0203 |
| delithiation | 0.36 | 10 | 10 | 1.00 | 2.104e-15 | 0.27 | 0.0202 |
| delithiation | 0.38 | 10 | 10 | 1.00 | 2.372e-15 | 0.29 | 0.0227 |
| delithiation | 0.40 | 10 | 10 | 1.00 | 2.529e-15 | 0.36 | 0.0243 |
| delithiation | 0.42 | 10 | 8 | 0.80 | 2.566e-15 | 0.42 | 0.0246 |
| delithiation | 0.44 | 10 | 2 | 0.20 | 1.196e-15 | 0.01 | 0.0115 |
| delithiation | 0.46 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.48 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.50 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.52 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.54 | 9 | 3 | 0.33 | 7.322e-17 | 0.60 | 0.0007 |
| delithiation | 0.56 | 10 | 8 | 0.80 | 4.445e-18 | 0.84 | 0.0000 |
| delithiation | 0.58 | 9 | 9 | 1.00 | 5.244e-18 | 0.66 | 0.0001 |
| delithiation | 0.60 | 11 | 11 | 1.00 | 1.223e-17 | 0.41 | 0.0001 |
| delithiation | 0.62 | 10 | 10 | 1.00 | 4.463e-17 | 0.40 | 0.0004 |
| delithiation | 0.64 | 10 | 10 | 1.00 | 1.684e-16 | 0.45 | 0.0016 |
| delithiation | 0.66 | 10 | 10 | 1.00 | 4.474e-16 | 0.41 | 0.0043 |
| delithiation | 0.68 | 10 | 10 | 1.00 | 7.434e-16 | 0.37 | 0.0071 |
| delithiation | 0.70 | 10 | 10 | 1.00 | 8.696e-16 | 0.38 | 0.0083 |
| delithiation | 0.72 | 10 | 10 | 1.00 | 8.323e-16 | 0.39 | 0.0080 |
| delithiation | 0.74 | 10 | 10 | 1.00 | 6.150e-16 | 0.42 | 0.0059 |
| delithiation | 0.76 | 10 | 10 | 1.00 | 4.759e-16 | 0.38 | 0.0046 |
| delithiation | 0.78 | 10 | 8 | 0.80 | 3.656e-16 | 0.30 | 0.0035 |
| delithiation | 0.80 | 10 | 6 | 0.60 | 2.887e-16 | 0.20 | 0.0028 |
| delithiation | 0.82 | 10 | 1 | 0.10 | 1.822e-16 | n/a | 0.0017 |
| delithiation | 0.84 | 10 | 2 | 0.20 | 8.856e-17 | 0.15 | 0.0008 |
| delithiation | 0.86 | 11 | 4 | 0.36 | 2.033e-17 | 0.38 | 0.0002 |
| delithiation | 0.88 | 10 | 6 | 0.60 | 4.728e-18 | 0.32 | 0.0000 |
| delithiation | 0.90 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.92 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.94 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.96 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| delithiation | 0.98 | 10 | 5 | 0.50 | 7.631e-16 | 0.20 | 0.0073 |
| delithiation | 1.00 | 5 | 5 | 1.00 | 1.093e-15 | 0.34 | 0.0105 |
| lithiation | 0.00 | 5 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.02 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.04 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.06 | 10 | 5 | 0.50 | 1.446e-13 | 0.85 | 1.3868 |
| lithiation | 0.08 | 10 | 5 | 0.50 | 2.769e-13 | 2.85 | 2.6559 |
| lithiation | 0.10 | 10 | 8 | 0.80 | 2.385e-14 | 1.10 | 0.2287 |
| lithiation | 0.12 | 10 | 9 | 0.90 | 1.984e-15 | 0.86 | 0.0190 |
| lithiation | 0.14 | 11 | 11 | 1.00 | 8.444e-16 | 1.07 | 0.0081 |
| lithiation | 0.16 | 10 | 10 | 1.00 | 8.289e-16 | 1.01 | 0.0079 |
| lithiation | 0.18 | 10 | 10 | 1.00 | 1.274e-15 | 1.17 | 0.0122 |
| lithiation | 0.20 | 10 | 9 | 0.90 | 1.292e-15 | 0.44 | 0.0124 |
| lithiation | 0.22 | 10 | 8 | 0.80 | 1.783e-15 | 0.94 | 0.0171 |
| lithiation | 0.24 | 10 | 8 | 0.80 | 4.007e-15 | 0.78 | 0.0384 |
| lithiation | 0.26 | 10 | 7 | 0.70 | 2.431e-15 | 0.06 | 0.0233 |
| lithiation | 0.28 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.30 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.32 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.34 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.36 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.38 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.40 | 11 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.42 | 9 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.44 | 10 | 2 | 0.20 | 2.612e-17 | 0.05 | 0.0003 |
| lithiation | 0.46 | 9 | 5 | 0.56 | 8.896e-17 | 0.52 | 0.0009 |
| lithiation | 0.48 | 10 | 10 | 1.00 | 8.763e-17 | 0.44 | 0.0008 |
| lithiation | 0.50 | 10 | 10 | 1.00 | 7.210e-17 | 0.31 | 0.0007 |
| lithiation | 0.52 | 10 | 10 | 1.00 | 4.398e-17 | 0.27 | 0.0004 |
| lithiation | 0.54 | 10 | 10 | 1.00 | 2.903e-17 | 0.33 | 0.0003 |
| lithiation | 0.56 | 10 | 4 | 0.40 | 6.305e-17 | 0.41 | 0.0006 |
| lithiation | 0.58 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.60 | 10 | 0 | 0.00 | n/a | n/a | n/a |
| lithiation | 0.62 | 10 | 4 | 0.40 | 2.532e-16 | 0.45 | 0.0024 |
| lithiation | 0.64 | 10 | 8 | 0.80 | 5.257e-17 | 0.68 | 0.0005 |
| lithiation | 0.66 | 11 | 10 | 0.91 | 5.223e-18 | 0.81 | 0.0001 |
| lithiation | 0.68 | 10 | 10 | 1.00 | 3.421e-18 | 0.61 | 0.0000 |
| lithiation | 0.70 | 10 | 10 | 1.00 | 4.907e-18 | 0.57 | 0.0000 |
| lithiation | 0.72 | 10 | 10 | 1.00 | 1.026e-17 | 0.53 | 0.0001 |
| lithiation | 0.74 | 10 | 10 | 1.00 | 1.825e-17 | 0.49 | 0.0002 |
| lithiation | 0.76 | 10 | 10 | 1.00 | 2.778e-17 | 0.45 | 0.0003 |
| lithiation | 0.78 | 10 | 10 | 1.00 | 3.588e-17 | 0.50 | 0.0003 |
| lithiation | 0.80 | 10 | 10 | 1.00 | 6.243e-17 | 0.52 | 0.0006 |
| lithiation | 0.82 | 10 | 10 | 1.00 | 9.019e-17 | 0.53 | 0.0009 |
| lithiation | 0.84 | 10 | 10 | 1.00 | 1.363e-16 | 0.49 | 0.0013 |
| lithiation | 0.86 | 10 | 10 | 1.00 | 2.082e-16 | 0.47 | 0.0020 |
| lithiation | 0.88 | 10 | 10 | 1.00 | 3.092e-16 | 0.44 | 0.0030 |
| lithiation | 0.90 | 10 | 10 | 1.00 | 4.193e-16 | 0.40 | 0.0040 |
| lithiation | 0.92 | 11 | 11 | 1.00 | 4.842e-16 | 0.32 | 0.0046 |
| lithiation | 0.94 | 10 | 10 | 1.00 | 5.058e-16 | 0.28 | 0.0049 |
| lithiation | 0.96 | 9 | 9 | 1.00 | 3.675e-16 | 0.42 | 0.0035 |
| lithiation | 0.98 | 10 | 10 | 1.00 | 2.980e-16 | 0.39 | 0.0029 |
| lithiation | 1.00 | 6 | 6 | 1.00 | 2.369e-16 | 0.19 | 0.0019 |

### 1.1 Which SOC ranges actually support the inversion

This is the diagnostic that matters most for using $D_s$ as a model parameter.  Intervals where at least half the pulses pass every gate:

- **delithiation**: SOC 0.16–0.42; SOC 0.56–0.80; SOC 0.88–0.88; SOC 0.98–1.00
- **lithiation**: SOC 0.06–0.26; SOC 0.46–0.54; SOC 0.64–1.00

The overall valid fraction is 616/981 = 62.8 %.  The rejections are not random: they concentrate where the Weppner-Huggins model itself breaks down —

- the **dilute stage** (near SOC 0, and the mirror end of the delithiation branch), where the OCP is nearly vertical so the pulse step is not a small perturbation, and the frozen table's own resolution is pushed to its limit;
- the **plateaus** (the stage-2/stage-1 flat regions), where the OCP is flat ($U' \to 0$), the pulse produces almost no diffusional overpotential, and the $\sqrt{t}$ regression is fitting noise.

Per-SOC $\log_{10}$ spread of the surviving values: median 0.43 decades, max 2.85 decades.  So the five-decade range of the curve is mostly SOC STRUCTURE between stages, not scatter within one stage.

## 2. Diffusivity sensitivity (B2.2)

### 2.1 p-OCV replay — the only column with an experiment

RMSE against the measured p-OCV window for every prescribed constant $D$, plus the two *curves* (reference-set native $D(SOC)$ and the Phase B1 GITT $D_s(SOC)$).

| model | rate | case | D_prescribed_m2_s | rmse_mV | mae_mV | n_points | coverage_fraction |
|---|---|---|---|---|---|---|---|
| SPM | pOCV-lith | control_native_ecker | n/a | 44.74 | 3.21 | 1978 | 0.989 |
| SPM | pOCV-lith | gitt_curve | n/a | 68.57 | 19.34 | 932 | 0.466 |
| SPM | pOCV-lith | const_1e-17 | 1.000e-17 | 271.25 | 219.24 | 239 | 0.119 |
| SPM | pOCV-lith | const_3e-17 | 3.000e-17 | 217.13 | 161.40 | 377 | 0.188 |
| SPM | pOCV-lith | const_1e-16 | 1.000e-16 | 140.34 | 84.50 | 856 | 0.428 |
| SPM | pOCV-lith | const_3e-16 | 3.000e-16 | 98.09 | 45.16 | 1486 | 0.743 |
| SPM | pOCV-lith | const_1e-15 | 1.000e-15 | 74.72 | 25.67 | 1841 | 0.920 |
| SPM | pOCV-lith | const_3e-15 | 3.000e-15 | 59.26 | 14.79 | 1944 | 0.972 |
| SPM | pOCV-lith | const_1e-14 | 1.000e-14 | 49.91 | 7.63 | 1980 | 0.990 |
| SPM | pOCV-lith | const_3e-14 | 3.000e-14 | 46.74 | 4.61 | 1990 | 0.995 |
| SPM | pOCV-lith | const_1e-13 | 1.000e-13 | 45.36 | 3.29 | 1994 | 0.997 |
| SPM | pOCV-deli | control_native_ecker | n/a | 6.31 | 2.65 | 2000 | 1.000 |
| SPM | pOCV-deli | gitt_curve | n/a | 373.96 | 112.80 | 434 | 0.217 |
| SPM | pOCV-deli | const_1e-17 | 1.000e-17 | 536.73 | 195.56 | 250 | 0.124 |
| SPM | pOCV-deli | const_3e-17 | 3.000e-17 | 611.70 | 245.68 | 390 | 0.195 |
| SPM | pOCV-deli | const_1e-16 | 1.000e-16 | 618.29 | 251.72 | 886 | 0.443 |
| SPM | pOCV-deli | const_3e-16 | 3.000e-16 | 548.29 | 195.42 | 1554 | 0.777 |
| SPM | pOCV-deli | const_1e-15 | 1.000e-15 | 443.44 | 131.59 | 1939 | 0.969 |
| SPM | pOCV-deli | const_3e-15 | 3.000e-15 | 168.42 | 44.23 | 2000 | 1.000 |
| SPM | pOCV-deli | const_1e-14 | 1.000e-14 | 43.35 | 11.29 | 2000 | 1.000 |
| SPM | pOCV-deli | const_3e-14 | 3.000e-14 | 16.61 | 4.72 | 2000 | 1.000 |
| SPM | pOCV-deli | const_1e-13 | 1.000e-13 | 8.53 | 2.72 | 2000 | 1.000 |
| SPMe | pOCV-lith | control_native_ecker | n/a | 44.74 | 3.33 | 1978 | 0.989 |
| SPMe | pOCV-lith | gitt_curve | n/a | 68.59 | 19.47 | 932 | 0.466 |
| SPMe | pOCV-lith | const_1e-17 | 1.000e-17 | 271.40 | 219.40 | 239 | 0.119 |
| SPMe | pOCV-lith | const_3e-17 | 3.000e-17 | 217.27 | 161.54 | 377 | 0.188 |
| SPMe | pOCV-lith | const_1e-16 | 1.000e-16 | 140.44 | 84.63 | 856 | 0.428 |
| SPMe | pOCV-lith | const_3e-16 | 3.000e-16 | 98.17 | 45.29 | 1486 | 0.743 |
| SPMe | pOCV-lith | const_1e-15 | 1.000e-15 | 74.78 | 25.80 | 1841 | 0.920 |
| SPMe | pOCV-lith | const_3e-15 | 3.000e-15 | 59.31 | 14.92 | 1944 | 0.972 |
| SPMe | pOCV-lith | const_1e-14 | 1.000e-14 | 49.94 | 7.76 | 1980 | 0.990 |
| SPMe | pOCV-lith | const_3e-14 | 3.000e-14 | 46.75 | 4.73 | 1990 | 0.995 |
| SPMe | pOCV-lith | const_1e-13 | 1.000e-13 | 45.36 | 3.41 | 1994 | 0.997 |
| SPMe | pOCV-deli | control_native_ecker | n/a | 6.26 | 2.75 | 2000 | 1.000 |
| SPMe | pOCV-deli | gitt_curve | n/a | 373.21 | 112.71 | 434 | 0.217 |
| SPMe | pOCV-deli | const_1e-17 | 1.000e-17 | 535.85 | 195.32 | 250 | 0.124 |
| SPMe | pOCV-deli | const_3e-17 | 3.000e-17 | 611.16 | 245.54 | 390 | 0.195 |
| SPMe | pOCV-deli | const_1e-16 | 1.000e-16 | 618.09 | 251.73 | 886 | 0.443 |
| SPMe | pOCV-deli | const_3e-16 | 3.000e-16 | 548.19 | 195.48 | 1554 | 0.777 |
| SPMe | pOCV-deli | const_1e-15 | 1.000e-15 | 443.34 | 131.66 | 1939 | 0.969 |
| SPMe | pOCV-deli | const_3e-15 | 3.000e-15 | 168.32 | 44.31 | 2000 | 1.000 |
| SPMe | pOCV-deli | const_1e-14 | 1.000e-14 | 43.23 | 11.37 | 2000 | 1.000 |
| SPMe | pOCV-deli | const_3e-14 | 3.000e-14 | 16.48 | 4.80 | 2000 | 1.000 |
| SPMe | pOCV-deli | const_1e-13 | 1.000e-13 | 8.44 | 2.81 | 2000 | 1.000 |

#### What the p-OCV replay can and cannot identify

| model | window | RMSE, control (native $D(SOC)$) | best constant-$D$ RMSE | at $D$ | is that the grid edge? | coverage at the control | weakest-run coverage |
|---|---|---|---|---|---|---|---|
| SPM | pOCV-lith | 44.74 mV | 45.36 mV | 1.0e-13 | yes | 0.989 | 0.119 |
| SPM | pOCV-deli | 6.31 mV | 8.53 mV | 1.0e-13 | yes | 1.000 | 0.124 |
| SPMe | pOCV-lith | 44.74 mV | 45.36 mV | 1.0e-13 | yes | 0.989 | 0.119 |
| SPMe | pOCV-deli | 6.26 mV | 8.44 mV | 1.0e-13 | yes | 1.000 | 0.124 |

Two readings, both important:

1. **No constant $D$ beats the SOC-dependent reference curve** on either window.  The best lattice member is still slightly worse than the control, so the *shape* of $D(SOC)$, not just its magnitude, is doing real work in the replay.
2. Where the minimum sits on the **grid edge**, the experiment does not identify a value: it only says the replay keeps improving as $D$ grows, i.e. it bounds $D$ **from below**.  A bounded-below statement is all a near-equilibrium protocol can give; it can never pin a magnitude.

**Coverage caveat (must travel with these numbers).**  A run whose diffusive overpotential grows enough to reach the lower cut-off early is scored only over the part of the window it survived, so its RMSE is computed on the *easiest* stretch and is therefore an underestimate.  The weakly-starved runs above have coverage as low as 0.12; the direction of the effect makes the 'small $D$ is worse' conclusion conservative, not optimistic.

### 2.2 Constant-current family — model-only

Same initial state as the p-OCV lithiation window ($x_0$ = 0.0010, measured rest OCV 3.0161 V), so the four rates differ only in current.

Two observables are used, both finite for every lattice member:

- **sustained protocol fraction** — how much of the nominal $1/\text{rate}$ hour the model completes before the lower cut-off.  Threshold convention: 5 percentage points.
- **$V$ at $t = \tfrac12 t_{protocol}$** — a pure surface-vs-average signature, because at a fixed *time* the volume-averaged stoichiometry is $D$-independent.  Threshold convention: 5 mV.

$V$ at a fixed *delivered capacity* is deliberately **not** the headline: it saturates, because only the well-equilibrated runs ever reach a given capacity, so the starved members drop out as NaN instead of counting as sensitive.

| model | rate | $t$ [s] | sustained, control | sustained, GITT | sustained spread | $Q$ to cutoff, control [mAh] | $Q$ to cutoff, GITT [mAh] | $Q$ spread [mAh] | $|V(t/2)-$ctrl$|$ [mV] | $D_{thr}$ from sustained [m$^2$/s] | Fo at that $D_{thr}$ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPM | C/50 | 180000 | 0.990 | 0.474 | 0.875 | 1.9232 | 0.9203 | 1.6995 | 11.8 | 1.32e-15 | 1.2645 |
| SPM | 0.5C | 7200 | 0.780 | 0.195 | 0.850 | 1.5147 | 0.3790 | 1.6516 | 9.7 | 8.36e-15 | 0.3208 |
| SPM | 1C | 3600 | 0.628 | 0.176 | 0.796 | 1.2207 | 0.3416 | 1.5466 | 10.8 | 9.56e-15 | 0.1834 |
| SPM | 2C | 1800 | 0.431 | 0.136 | 0.631 | 0.8364 | 0.2633 | 1.2258 | nan | nan | nan |
| SPMe | C/50 | 180000 | 0.990 | 0.474 | 0.875 | 1.9234 | 0.9203 | 1.6997 | 11.8 | 1.32e-15 | 1.2645 |
| SPMe | 0.5C | 7200 | 0.775 | 0.195 | 0.845 | 1.5048 | 0.3781 | 1.6419 | 9.7 | 8.35e-15 | 0.3202 |
| SPMe | 1C | 3600 | 0.613 | 0.174 | 0.778 | 1.1910 | 0.3379 | 1.5106 | 10.8 | 9.70e-15 | 0.1860 |
| SPMe | 2C | 1800 | 0.337 | 0.115 | 0.440 | 0.6555 | 0.2235 | 0.8537 | nan | 2.24e-14 | 0.2150 |

#### $V$ at $Q = 0.5\,Q_{nom}$ [V] across the lattice

**SPM**
| D_prescribed_m2_s | C/50 | 0.5C | 1C | 2C |
|---|---|---|---|---|
| 3.000e-16 | 0.0503 | n/a | n/a | n/a |
| 1.000e-15 | 0.0552 | n/a | n/a | n/a |
| 3.000e-15 | 0.0601 | n/a | n/a | n/a |
| 1.000e-14 | 0.0619 | 0.0404 | 0.0229 | n/a |
| 3.000e-14 | 0.0624 | 0.0465 | 0.0314 | 0.0080 |
| 1.000e-13 | 0.0626 | 0.0509 | 0.0389 | 0.0159 |

**SPMe**
| D_prescribed_m2_s | C/50 | 0.5C | 1C |
|---|---|---|---|
| 3.000e-16 | 0.0502 | n/a | n/a |
| 1.000e-15 | 0.0551 | n/a | n/a |
| 3.000e-15 | 0.0600 | n/a | n/a |
| 1.000e-14 | 0.0618 | 0.0375 | 0.0171 |
| 3.000e-14 | 0.0623 | 0.0436 | 0.0257 |
| 1.000e-13 | 0.0624 | 0.0480 | 0.0331 |


### 2.3 Model comparison (SPM vs SPMe)

| axis | protocol | model | t_protocol_s | rmse_control_mV | rmse_gitt_curve_mV | sustained_control | sustained_gitt_curve | V_half_protocol_deviation_control_mV | sensitivity_threshold_D_from_sustained_m2_s | Fo_at_threshold_from_sustained |
|---|---|---|---|---|---|---|---|---|---|---|
| pocv_replay | pOCV-lith | SPM | 159810 | 44.74 | 68.6 | n/a | n/a | n/a | n/a | n/a |
| pocv_replay | pOCV-deli | SPM | 148521 | 6.31 | 374.0 | n/a | n/a | n/a | n/a | n/a |
| cc_rate | C/50 | SPM | 180000 | n/a | n/a | 0.990 | 0.474 | 11.8 | 1.32e-15 | 1.2645 |
| cc_rate | 0.5C | SPM | 7200 | n/a | n/a | 0.780 | 0.195 | 9.7 | 8.36e-15 | 0.3208 |
| cc_rate | 1C | SPM | 3600 | n/a | n/a | 0.628 | 0.176 | 10.8 | 9.56e-15 | 0.1834 |
| cc_rate | 2C | SPM | 1800 | n/a | n/a | 0.431 | 0.136 | n/a | n/a | n/a |
| pocv_replay | pOCV-lith | SPMe | 159810 | 44.74 | 68.6 | n/a | n/a | n/a | n/a | n/a |
| pocv_replay | pOCV-deli | SPMe | 148521 | 6.26 | 373.2 | n/a | n/a | n/a | n/a | n/a |
| cc_rate | C/50 | SPMe | 180000 | n/a | n/a | 0.990 | 0.474 | 11.8 | 1.32e-15 | 1.2645 |
| cc_rate | 0.5C | SPMe | 7200 | n/a | n/a | 0.775 | 0.195 | 9.7 | 8.35e-15 | 0.3202 |
| cc_rate | 1C | SPMe | 3600 | n/a | n/a | 0.613 | 0.174 | 10.8 | 9.70e-15 | 0.1860 |
| cc_rate | 2C | SPMe | 1800 | n/a | n/a | 0.337 | 0.115 | n/a | 2.24e-14 | 0.2150 |

## 3. Verdict — when the GITT $D_s$ is usable

- Across every model and rate, the sustained-capacity deviation falls below the 5-point level once
  $Fo = D t / R^2 \gtrsim$ **0.32** (range 0.18–1.26).

- **C/50 / SPM**: the GITT curve spans $Fo$ = 3.3e-03 – 2.7e+02 (median 2.1e-01); with it the model sustains 47 % of the protocol against 99 % with the reference diffusivity.
- **0.5C / SPM**: the GITT curve spans $Fo$ = 1.3e-04 – 1.1e+01 (median 8.5e-03); with it the model sustains 20 % of the protocol against 78 % with the reference diffusivity.
- **1C / SPM**: the GITT curve spans $Fo$ = 6.6e-05 – 5.3e+00 (median 4.3e-03); with it the model sustains 18 % of the protocol against 63 % with the reference diffusivity.
- **2C / SPM**: the GITT curve spans $Fo$ = 3.3e-05 – 2.7e+00 (median 2.1e-03); with it the model sustains 14 % of the protocol against 43 % with the reference diffusivity.
- **C/50 / SPMe**: the GITT curve spans $Fo$ = 3.3e-03 – 2.7e+02 (median 2.1e-01); with it the model sustains 47 % of the protocol against 99 % with the reference diffusivity.
- **0.5C / SPMe**: the GITT curve spans $Fo$ = 1.3e-04 – 1.1e+01 (median 8.5e-03); with it the model sustains 19 % of the protocol against 77 % with the reference diffusivity.
- **1C / SPMe**: the GITT curve spans $Fo$ = 6.6e-05 – 5.3e+00 (median 4.3e-03); with it the model sustains 17 % of the protocol against 61 % with the reference diffusivity.
- **2C / SPMe**: the GITT curve spans $Fo$ = 3.3e-05 – 2.7e+00 (median 2.1e-03); with it the model sustains 12 % of the protocol against 34 % with the reference diffusivity.

### SPM vs SPMe

- **C/50**: sustained fraction 99.0 % (SPM) vs 99.0 % (SPMe) with the reference diffusivity; the lattice $D_{thr}$ is 1.32e-15 vs 1.32e-15 m$^2$/s.
- **0.5C**: sustained fraction 78.0 % (SPM) vs 77.5 % (SPMe) with the reference diffusivity; the lattice $D_{thr}$ is 8.36e-15 vs 8.35e-15 m$^2$/s.
- **1C**: sustained fraction 62.8 % (SPM) vs 61.3 % (SPMe) with the reference diffusivity; the lattice $D_{thr}$ is 9.56e-15 vs 9.70e-15 m$^2$/s.
- **2C**: sustained fraction 43.1 % (SPM) vs 33.7 % (SPMe) with the reference diffusivity; the lattice $D_{thr}$ is nan vs 2.24e-14 m$^2$/s.

So the **diffusivity** conclusion is model-structure robust at and below C/2 (SPM and SPMe agree to a couple of percent), while at 2C the two models separate because the electrolyte adds a second limitation: extrapolating the 2C column to a real cell needs SPMe (or DFN), not SPM.

### The decision rule

$$Fo = \frac{D\,t}{R^{2}}\;=\;\frac{t_{protocol}}{\tau_d}$$

| regime | meaning | is the GITT $D_s$ usable? |
|---|---|---|
| $Fo \gtrsim 1$ | particle equilibrated every step | **yes — and it barely matters**: any plausible $D$ gives nearly the same answer, so the five-decade SOC spread is harmless |
| $Fo \approx 0.1\!-\!1$ | diffusion and protocol share a time scale | **marginal**: $D$ enters the answer directly, so both magnitude and SOC shape must be right |
| $Fo \lesssim 0.1$ | surface starved | **no**: the model output is controlled by $D$ itself, and a wrong $D$ is indistinguishable from wrong physics |

## 4. Honest limitations

- $D \propto R^2$ and $R$ = 13.70 um comes from the reference set, not from a measurement of this material: a factor 2 error in $R$ moves every $Fo$ by 4, i.e. a whole regime boundary.
- The 0.5C/1C/2C columns are model-only; they bound when $D$ *would* matter, they do not show that the model reproduces any measured 1C result.
- The p-OCV replay is a near-equilibrium protocol: an RMSE minimum on the lattice is reported as an observation only and is **never adopted** as a fitted diffusivity (Phase B2 does no fitting by construction).
- The constant-$D$ lattice removes the SOC shape on purpose, so the lattice sensitivity is a **lower bound**: a wrong $D(SOC)$ shape can produce more error than any constant — which is exactly what the 'GITT curve' rows show, and why no constant on the lattice out-scores the SOC-dependent reference curve.
- RMSE over a truncated replay window is an underestimate; coverage is reported next to every RMSE and the effect is conservative.

## 5. Wording (mandatory)

**apparent / effective** solid diffusivity, never *intrinsic* and never *the diffusion coefficient*.  $Fo$ is a property of a PROTOCOL and a diffusivity, not of the material.  The GITT curve is a dataset-associated apparent parameter: it does not transfer to another cell, another particle size or another temperature, and it is **not** validated here.
