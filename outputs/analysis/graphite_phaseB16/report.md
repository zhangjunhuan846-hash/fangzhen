# Phase B1.6 — apparent D_s(SOC) with the equilibrium drift separated from the diffusion signal

- GITT cell `063b77`, p-OCV cell `4ccc47`, model SPM
- pulses: **981**, 1800 s pulse / 9000 s rest
- accepted pulses: v1 **616**, v2 **851**
- `dataset_role` of `sintef_graphite` for this calibration: **identification** (declared in configs/datasets.yaml, enforced by governance/dataset_roles.py)

## What changed

Phase B1 inverted the Weppner-Huggins law from a first-order fit `V = a + m*sqrt(t)`, which assumes the equilibrium voltage is constant over the pulse.  It is not: the bulk composition advances during the pulse, so the equilibrium voltage drifts and the fitted sqrt(t) slope absorbs part of that drift.

Phase B1.6 uses `V(t) = a + b*t + m*sqrt(t), fitted over the pulse with the first IR_SKIP seconds removed; the linear term carries the equilibrium drift caused by the bulk composition advancing during the pulse, so `m` is the diffusional part alone.  Phase B1 instead used V(t) = a + m*sqrt(t).`

Everything else — the inversion, the local OCP slope, the gate values and the SOC binning — is imported from the Phase B1 module, so the two tables differ in exactly one thing.

## Regression self-check

- recomputed v1 table vs the frozen Phase B1 table: **identical** (max relative difference 2.220e-16 over 74 rows)

## What the fit form moved on the real pulses

| quantity | p5 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|---|
| slope (1st order) / slope (drift-corrected) | 0.259 | 0.332 | 0.474 | 0.841 | 1.941 |
| D_v2 / D_v1 (paired, per pulse) | 0.067 | 0.110 | 0.225 | 0.707 | 3.770 |
| fitted linear term / (U'*I/Q_th) | -47.844 | -15.191 | -4.591 | -0.325 | 3.313 |

(851 pulses carry both fits; the drift row is reported for the ones where U' exists.)

## Same-pulse comparison (the fair one)

v1 accepts 616 pulses and v2 851: a quadratic form fits better, so v2 keeps more of the plateau and dilute pulses.  Comparing whole-table medians therefore mixes two populations. On the **614 pulses both accept** the two diffusivities are directly comparable:

| group | n | D_s(v1) median [m2/s] | D_s(v2) median [m2/s] | v2/v1 (ratio of medians) | Ecker/v2 |
|---|---|---|---|---|---|
| all | 614 | 3.803e-16 | **2.155e-16** | 0.567 | — |
| delithiation | 287 | 8.355e-16 | **3.295e-16** | 0.394 | 37.0x |
| lithiation | 327 | 1.427e-16 | **8.436e-17** | 0.591 | 144.5x |

Reference (Ecker2015) median: **1.219e-14 m2/s**.

## How much the fit form moved D — and in which direction

Phase B1.5 measured, on MODEL pulses, that the first-order fit inflates the diffusion slope by a median 2.9x; since D = R^2/tau_d with tau_d ~ m^2, removing that inflation should push D **up** by about 9x.  On the real pulses the first-order fit gives the SMALLER slope, so the correction moves D **down** — and two independent summaries of the same pulses agree on that sign:

| summary | question it answers | value |
|---|---|---|
| paired ratio D_v2/D_v1 (median over the 614 pulses both accept) | what did the fit form do to a typical pulse? | **0.43x** |
| ratio of the medians (same pulses) | where does the bulk of the curve end up? | **0.567x** |

Only 26% of individual pulses move up, and the paired ratios span 0.12x to 6.27x, so the correction is strongly heterogeneous in size and locally in sign — but the sign of the net effect is not in doubt.

The drift diagnostic explains why the SIZE differs so much from Phase B1.5's ~9x: pure equilibrium drift would be `dU/dt = U'*I/Q_th`, but the fitted linear term is **-4.6x** that value (median) and its **sign agrees with the equilibrium drift in only 19%** of pulses.  The extra term is carrying a slow non-equilibrium transient (charge transfer, porous-electrode relaxation, the pseudo-OCP's own settling) rather than the drift the correction was designed for.  So the model-pulse calibration of the bias does not transfer to these electrodes, and the only way to know was to measure it.

## D_s level against the reference (whole table)

| branch | statistic | v1 | v2 | Ecker2015 |
|---|---|---|---|---|
| lithiation | p25 [m2/s] | 3.538e-17 | **9.412e-18** | 1.219e-14 (median) |
| lithiation | p50 [m2/s] | 1.438e-16 | **3.651e-17** | 1.219e-14 (median) |
| lithiation | p75 [m2/s] | 5.947e-16 | **6.723e-16** | 1.219e-14 (median) |
| lithiation | v2 / v1 (median) | 0.254 | — | — |
| lithiation | Ecker / v2 (median) | — | 333.88x | — |
| delithiation | p25 [m2/s] | 2.844e-16 | **3.068e-17** | 1.219e-14 (median) |
| delithiation | p50 [m2/s] | 8.355e-16 | **1.738e-16** | 1.219e-14 (median) |
| delithiation | p75 [m2/s] | 2.597e-15 | **9.269e-16** | 1.219e-14 (median) |
| delithiation | v2 / v1 (median) | 0.208 | — | — |
| delithiation | Ecker / v2 (median) | — | 70.13x | — |

## SOC-resolved table (v2)

| branch | SOC | n | D_s [cm2/s] | p25 | p75 | rel. unc. |
|---|---|---|---|---|---|---|
| delithiation | 0.14 | 1 | 8.828e-10 | 8.828e-10 | 8.828e-10 | 0.0266 |
| delithiation | 0.16 | 10 | 7.398e-10 | 5.399e-10 | 1.140e-09 | 0.0237 |
| delithiation | 0.18 | 9 | 2.956e-10 | 6.735e-11 | 3.686e-10 | 0.0283 |
| delithiation | 0.20 | 10 | 7.131e-12 | 5.611e-12 | 9.466e-12 | 0.0155 |
| delithiation | 0.22 | 10 | 5.843e-12 | 5.199e-12 | 7.437e-12 | 0.0217 |
| delithiation | 0.24 | 10 | 3.757e-11 | 2.697e-11 | 5.702e-11 | 0.0182 |
| delithiation | 0.26 | 10 | 6.982e-11 | 6.347e-11 | 8.259e-11 | 0.0129 |
| delithiation | 0.28 | 10 | 4.290e-11 | 3.274e-11 | 5.478e-11 | 0.0145 |
| delithiation | 0.30 | 10 | 2.958e-11 | 2.526e-11 | 3.508e-11 | 0.0106 |
| delithiation | 0.32 | 10 | 3.804e-11 | 2.741e-11 | 4.367e-11 | 0.0082 |
| delithiation | 0.34 | 11 | 1.637e-11 | 1.296e-11 | 2.228e-11 | 0.0053 |
| delithiation | 0.36 | 10 | 1.220e-11 | 1.123e-11 | 1.320e-11 | 0.0043 |
| delithiation | 0.38 | 10 | 8.474e-12 | 7.365e-12 | 9.114e-12 | 0.0034 |
| delithiation | 0.40 | 10 | 4.902e-12 | 4.677e-12 | 6.006e-12 | 0.0028 |
| delithiation | 0.42 | 10 | 3.304e-12 | 2.766e-12 | 3.975e-12 | 0.0045 |
| delithiation | 0.44 | 10 | 2.228e-12 | 1.843e-12 | 2.479e-12 | 0.0060 |
| delithiation | 0.46 | 10 | 1.439e-12 | 1.249e-12 | 1.714e-12 | 0.0077 |
| delithiation | 0.48 | 10 | 8.672e-13 | 7.334e-13 | 1.084e-12 | 0.0090 |
| delithiation | 0.50 | 10 | 4.407e-13 | 3.457e-13 | 5.705e-13 | 0.0104 |
| delithiation | 0.52 | 10 | 2.116e-13 | 1.723e-13 | 2.372e-13 | 0.0127 |
| delithiation | 0.54 | 9 | 1.191e-13 | 9.578e-14 | 1.366e-13 | 0.0134 |
| delithiation | 0.56 | 10 | 3.135e-14 | 2.014e-14 | 6.467e-14 | 0.0097 |
| delithiation | 0.58 | 9 | 7.348e-14 | 4.987e-14 | 1.093e-13 | 0.0134 |
| delithiation | 0.60 | 11 | 2.224e-13 | 1.842e-13 | 2.859e-13 | 0.0106 |
| delithiation | 0.62 | 10 | 4.792e-13 | 4.427e-13 | 6.129e-13 | 0.0090 |
| delithiation | 0.64 | 10 | 1.057e-12 | 9.820e-13 | 1.333e-12 | 0.0070 |
| delithiation | 0.66 | 10 | 1.928e-12 | 1.750e-12 | 2.137e-12 | 0.0052 |
| delithiation | 0.68 | 10 | 2.379e-12 | 2.041e-12 | 2.492e-12 | 0.0036 |
| delithiation | 0.70 | 10 | 2.111e-12 | 1.836e-12 | 2.373e-12 | 0.0021 |
| delithiation | 0.72 | 10 | 1.543e-12 | 1.320e-12 | 1.798e-12 | 0.0013 |
| delithiation | 0.74 | 10 | 9.388e-13 | 7.952e-13 | 1.216e-12 | 0.0023 |
| delithiation | 0.76 | 10 | 6.261e-13 | 5.068e-13 | 7.442e-13 | 0.0037 |
| delithiation | 0.78 | 10 | 4.270e-13 | 3.293e-13 | 5.240e-13 | 0.0051 |
| delithiation | 0.80 | 10 | 2.949e-13 | 2.319e-13 | 3.596e-13 | 0.0063 |
| delithiation | 0.82 | 10 | 1.672e-13 | 1.365e-13 | 2.131e-13 | 0.0073 |
| delithiation | 0.84 | 10 | 9.033e-14 | 8.112e-14 | 1.169e-13 | 0.0082 |
| delithiation | 0.86 | 11 | 2.725e-14 | 2.034e-14 | 5.228e-14 | 0.0084 |
| delithiation | 0.88 | 10 | 4.763e-15 | 3.461e-15 | 6.203e-15 | 0.0084 |
| delithiation | 0.98 | 5 | 6.300e-12 | 6.077e-12 | 8.836e-12 | 0.0033 |
| delithiation | 1.00 | 5 | 4.236e-12 | 3.630e-12 | 4.444e-12 | 0.0047 |
| lithiation | 0.06 | 5 | 1.987e-10 | 1.683e-10 | 2.180e-10 | 0.0061 |
| lithiation | 0.08 | 10 | 4.947e-10 | 2.217e-10 | 8.279e-10 | 0.0296 |
| lithiation | 0.10 | 10 | 6.386e-11 | 3.835e-11 | 1.159e-10 | 0.0170 |
| lithiation | 0.12 | 10 | 1.230e-11 | 7.573e-12 | 1.892e-11 | 0.0112 |
| lithiation | 0.14 | 11 | 7.663e-12 | 2.436e-12 | 8.813e-12 | 0.0139 |
| lithiation | 0.16 | 10 | 9.623e-12 | 5.355e-12 | 1.025e-11 | 0.0156 |
| lithiation | 0.18 | 10 | 9.700e-12 | 6.135e-12 | 1.323e-11 | 0.0137 |
| lithiation | 0.20 | 10 | 1.234e-11 | 7.053e-12 | 1.563e-11 | 0.0133 |
| lithiation | 0.22 | 10 | 7.728e-12 | 5.438e-12 | 8.707e-12 | 0.0100 |
| lithiation | 0.24 | 10 | 7.104e-12 | 4.540e-12 | 9.501e-12 | 0.0148 |
| lithiation | 0.26 | 10 | 3.236e-12 | 2.233e-12 | 4.478e-12 | 0.0085 |
| lithiation | 0.28 | 10 | 1.303e-12 | 9.603e-13 | 1.767e-12 | 0.0055 |
| lithiation | 0.30 | 10 | 7.200e-13 | 5.448e-13 | 9.059e-13 | 0.0052 |
| lithiation | 0.32 | 10 | 4.321e-13 | 3.048e-13 | 5.339e-13 | 0.0049 |
| lithiation | 0.34 | 10 | 2.139e-13 | 1.518e-13 | 2.716e-13 | 0.0055 |
| lithiation | 0.36 | 10 | 9.595e-14 | 7.113e-14 | 1.159e-13 | 0.0061 |
| lithiation | 0.38 | 10 | 6.851e-14 | 6.074e-14 | 8.126e-14 | 0.0059 |
| lithiation | 0.40 | 11 | 6.511e-14 | 3.777e-14 | 7.465e-14 | 0.0059 |
| lithiation | 0.42 | 9 | 7.217e-14 | 6.184e-14 | 7.967e-14 | 0.0052 |
| lithiation | 0.44 | 10 | 9.242e-14 | 8.324e-14 | 9.646e-14 | 0.0049 |
| lithiation | 0.46 | 9 | 1.133e-13 | 1.045e-13 | 1.191e-13 | 0.0042 |
| lithiation | 0.48 | 10 | 1.309e-13 | 1.230e-13 | 1.417e-13 | 0.0045 |
| lithiation | 0.50 | 10 | 1.659e-13 | 1.496e-13 | 1.756e-13 | 0.0057 |
| lithiation | 0.52 | 10 | 1.856e-13 | 1.814e-13 | 1.920e-13 | 0.0078 |
| lithiation | 0.54 | 10 | 1.809e-13 | 1.715e-13 | 1.916e-13 | 0.0073 |
| lithiation | 0.56 | 10 | 6.678e-13 | 2.202e-13 | 9.543e-13 | 0.0040 |
| lithiation | 0.58 | 10 | 1.385e-12 | 1.169e-12 | 1.717e-12 | 0.0103 |
| lithiation | 0.60 | 10 | 5.782e-13 | 4.121e-13 | 8.315e-13 | 0.0104 |
| lithiation | 0.62 | 10 | 2.108e-13 | 1.426e-13 | 3.055e-13 | 0.0094 |
| lithiation | 0.64 | 10 | 5.698e-14 | 3.949e-14 | 8.560e-14 | 0.0080 |
| lithiation | 0.66 | 11 | 7.554e-15 | 7.035e-15 | 1.435e-14 | 0.0072 |
| lithiation | 0.68 | 10 | 6.625e-15 | 4.943e-15 | 7.422e-15 | 0.0064 |
| lithiation | 0.70 | 10 | 1.038e-14 | 7.485e-15 | 1.466e-14 | 0.0059 |
| lithiation | 0.72 | 10 | 2.696e-14 | 1.899e-14 | 3.738e-14 | 0.0057 |
| lithiation | 0.74 | 10 | 5.674e-14 | 4.284e-14 | 7.572e-14 | 0.0057 |
| lithiation | 0.76 | 10 | 1.059e-13 | 7.693e-14 | 1.329e-13 | 0.0063 |
| lithiation | 0.78 | 10 | 1.653e-13 | 1.254e-13 | 2.167e-13 | 0.0068 |
| lithiation | 0.80 | 10 | 3.570e-13 | 2.668e-13 | 4.820e-13 | 0.0068 |
| lithiation | 0.82 | 10 | 6.243e-13 | 4.983e-13 | 8.510e-13 | 0.0075 |
| lithiation | 0.84 | 10 | 1.198e-12 | 8.783e-13 | 1.649e-12 | 0.0093 |
| lithiation | 0.86 | 10 | 2.431e-12 | 1.733e-12 | 3.152e-12 | 0.0104 |
| lithiation | 0.88 | 10 | 5.075e-12 | 3.960e-12 | 6.695e-12 | 0.0118 |
| lithiation | 0.90 | 10 | 1.038e-11 | 8.607e-12 | 1.386e-11 | 0.0144 |
| lithiation | 0.92 | 11 | 1.997e-11 | 1.301e-11 | 2.533e-11 | 0.0177 |
| lithiation | 0.94 | 10 | 6.420e-11 | 3.859e-11 | 8.510e-11 | 0.0291 |
| lithiation | 0.96 | 7 | 1.122e-10 | 5.490e-11 | 2.313e-10 | 0.0283 |
| lithiation | 0.98 | 10 | 1.018e-10 | 5.200e-11 | 2.005e-10 | 0.0167 |
| lithiation | 1.00 | 6 | 1.931e-11 | 1.528e-11 | 2.710e-11 | 0.0078 |

## p-OCV replay (control = Ecker2015 D, same frozen set)

| window | diffusivity | RMSE [mV] | MAE [mV] | max abs [mV] |
|---|---|---|---|---|
| lith | Ecker2015 D | **1.627** | 1.200 | 13.307 |
| lith | SINTEF D_s (first order) | **19.092** | 15.183 | 67.826 |
| lith | SINTEF D_s (drift-corrected) | **29.711** | 25.082 | 194.002 |
| deli | Ecker2015 D | **2.849** | 1.726 | 26.232 |
| deli | SINTEF D_s (first order) | **370.837** | 112.053 | 2968.789 |
| deli | SINTEF D_s (drift-corrected) | **466.165** | 147.892 | 3072.380 |

### Same comparison on a COMMON time grid

The variants can end at different times (changing the diffusivity moves the voltage event that terminates the run), so the table above scores them on **different point sets** — and a truncated run is only judged where it survived, which understates its error.  Interpolating every variant onto the reference run's grid, restricted to the range all three cover:

| window | common points | Ecker2015 D | D_s (first order) | D_s (drift-corrected) |
|---|---|---|---|---|
| lith | 631 | **1.387** | 10.829 | 29.711 |
| deli | 260 | **1.138** | 35.263 | 466.165 |

**The numbers move a lot, and they move most for the runs that were truncated** (lith: first-order 19.09 → 10.83 mV; deli: first-order 370.84 → 35.26 mV).  The ordering is unchanged — Ecker < first-order < drift-corrected in both windows — so the conclusion is not an artefact of unequal coverage.  But any single RMSE quoted from the table above overstates the first-order curve's error, because that run was only scored where it survived.

## First-order Weppner-Huggins excursion over the p-OCV window

| window | Ecker D | D_s (v2) |
|---|---|---|
| lith | 9.47 mV | 173.07 mV |
| deli | 14.56 mV | 121.92 mV |

## Verdict

Redoing the table with the drift-corrected fit does NOT bring the apparent D_s closer to the reference: on the 614 pulses both reductions accept, the median falls from 3.803e-16 to 2.155e-16 m2/s — **57x below** the Ecker2015 median of 1.219e-14 m2/s.

The correction therefore moved the value AWAY from the reference by a paired median 0.43x — the opposite of what Phase B1.5's model pulses predicted.  The drift diagnostic explains why: the fitted linear term is several times the pure equilibrium drift and its sign disagrees with it in most pulses, so it absorbs non-diffusional relaxation rather than the drift.

This closes the fit-form line of investigation.  Two functionally different inversions of the same pulses agree on the qualitative conclusion — the apparent D_s from a single-particle Weppner-Huggins reduction of this GITT train is one to two orders of magnitude below the reference and does not improve the replay — while disagreeing on the value by a factor 2.34 per pulse and 1.76 in level.  That spread, not either single number, is the honest error bar on any single-particle GITT diffusivity for this electrode.

In the replay on the frozen parameter set:

| window | Ecker2015 D | D_s (first order) | D_s (drift-corrected) |
|---|---|---|---|
| lith | **1.63 mV** | 19.09 mV | 29.71 mV |
| deli | **2.85 mV** | 370.84 mV | 466.16 mV |

Both extracted curves are worse than the reference diffusivity, and the corrected one is worse than the first-order one because it is smaller still and starves the particle further.  **Neither is adopted.**

## Wording (mandatory)

**Apparent/effective** solid diffusivity, NOT an intrinsic material coefficient and NOT validation.  The p-OCV replay is a consistency check whose diffusion sensitivity is negligible at C/50.  Correcting the fit form removes one known functional bias; it does not make the value a material constant, and on this dataset it did not make it a better parameter either.
