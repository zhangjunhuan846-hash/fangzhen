# Phase B0.5 — capacity consistency (SINTEF graphite R2032 ‖ Li)

- dataset `sintef_graphite` / cell `4ccc47` / model SPM
- geometry: Phase A.5 measured geometry, **fixed in every case**
- OCP / diffusivity / kinetics / voltage window: **unchanged**
- intervention: `eps_am` scaled so that `Q_model == Q_ref` (a MEASURED charge), nothing fitted to any voltage

## Why capacity enters the OCP comparison

The Phase B0 OCP table's abscissa is a charge-based SOC (SOC = Q / Q_ref, Q_ref = 1.9425 mAh). It can only be read
as `OCP(x)` if the model's stoichiometry x means the same thing, i.e. if

```
Q_model = eps_am * L * A * c_max * F / 3600  ==  Q_ref
```

(validated against a measured volume-averaged dx/dt from a constant-current solve: 0.00 % difference). With the Phase A.5 geometry Q_model was 2.2017 mAh, so x lagged the table SOC by 1.1334×.

| parameter set | eps_am | Q_model [mAh] | declared nominal [mAh] |
|---|---|---|---|
| `sintef_graphite_geometry_v1` | 0.261218 | 2.2017 | 2.2017 |
| `sintef_graphite_ocp_lith_v1` | 0.261218 | 2.2017 | 2.2017 |
| `sintef_graphite_ocp_deli_v1` | 0.261218 | 2.2017 | 2.2017 |
| `sintef_graphite_ocp_lith_capmatch_v1` | 0.230465 | 1.9425 | 1.9425 |
| `sintef_graphite_ocp_deli_capmatch_v1` | 0.230465 | 1.9425 | 1.9425 |

`Nominal cell capacity [A.h]` is only a bookkeeping follow-on: a test asserts the particle equation depends on `eps_am` alone.

## Results (zero-fit; nothing fitted to any voltage)

| window | variant | Q_model [mAh] | RMSE [mV] | MAE [mV] | bias [mV] | V_sim end [V] | coverage |
|---|---|---|---|---|---|---|---|
| lith | A5_geom_only | 2.202 | **81.39** | 67.81 | 66.16 | 0.0832 | 1.000 |
| lith | B0_ocp | 2.202 | **45.05** | 7.75 | 4.95 | 0.0416 | 1.000 |
| lith | B0p5_capmatch | 1.942 | **44.64** | 3.20 | -3.20 | 0.0060 | 0.989 |
| deli | A5_geom_only | 2.202 | **109.12** | 61.86 | -61.86 | 0.1965 | 1.000 |
| deli | B0_ocp | 2.202 | **91.86** | 31.19 | -30.87 | 0.2373 | 1.000 |
| deli | B0p5_capmatch | 1.942 | **6.27** | 2.65 | 2.65 | 1.0602 | 1.000 |

## Residual by experimental-voltage region (MAE, mV)

The last region label is inherited from Phase B0, where the
*published* table had no data above 1.43 V; with the measured OCP
the table covers that range, so the label is historical only.

| window | region | B0 measured OCP | B0.5 + capacity matched | change |
|---|---|---|---|---|
| lith | V_exp<=0.15 | 5.34 | 1.27 | -4.07 |
| lith | 0.15<V_exp<=0.60 | 17.82 | 5.83 | -11.99 |
| lith | 0.60<V_exp<=1.43 | 48.38 | 63.32 | +14.94 |
| lith | V_exp>1.43_outside_ref_table | 1936.47 | 1936.47 | +0.00 |
| deli | V_exp<=0.15 | 2.30 | 1.30 | -1.01 |
| deli | 0.15<V_exp<=0.60 | 46.89 | 2.89 | -44.00 |
| deli | 0.60<V_exp<=1.43 | 519.11 | 35.80 | -483.31 |
| deli | V_exp>1.43_outside_ref_table | nan | nan | +nan |

## SOC trajectory (the point of this phase)

| window | variant | x start (avg) | x end (avg) | x end (surface) | exp SOC end | end error (avg) |
|---|---|---|---|---|---|---|
| lith | A5_geom_only | 0.0015 | 0.8836 | 0.8912 | 1.0000 | -0.1164 |
| lith | B0_ocp | 0.0010 | 0.8831 | 0.8907 | 1.0000 | -0.1169 |
| lith | B0p5_capmatch | 0.0010 | 0.9898 | 0.9984 | 0.9890 | +0.0008 |
| deli | A5_geom_only | 0.9582 | 0.1474 | 0.1470 | 0.0812 | +0.0661 |
| deli | B0_ocp | 0.9990 | 0.1882 | 0.1876 | 0.0812 | +0.1069 |
| deli | B0p5_capmatch | 0.9990 | 0.0800 | 0.0798 | 0.0812 | -0.0013 |

## Verdicts

**lith** — B0_ocp (measured OCP, capacity NOT matched) → B0p5_capmatch (eps_am -> Q_ref)
- Q_model 2.2017 → 1.9425 mAh
- RMSE 45.05 → 44.64 mV (×0.99); MAE 7.75 → 3.20 mV
- V_sim end 0.0416 → 0.0060 V (experiment 0.0100 V)
- model x end 0.8831 → 0.9898 (experiment SOC end 0.9890)
- 0.60–1.43 V region MAE 48.38 → 63.32 mV (NOT improved)
  - this slice is the decimated dilute stage (see the caveat below): only one table sample lives above 1.43 V, so its MAE is dominated by interpolation and is unstable between variants. The window's overall MAE still fell 7.75 -> 3.20 mV (x0.41).

**deli** — B0_ocp (measured OCP, capacity NOT matched) → B0p5_capmatch (eps_am -> Q_ref)
- Q_model 2.2017 → 1.9425 mAh
- RMSE 91.86 → 6.27 mV (×0.07); MAE 31.19 → 2.65 mV
- V_sim end 0.2373 → 1.0602 V (experiment 1.0000 V)
- model x end 0.1882 → 0.0800 (experiment SOC end 0.0812)
- 0.60–1.43 V region MAE 519.11 → 35.80 mV (improved)

## Wording (mandatory)

Capacity-CONSISTENT, not fitted: `Q_ref` is a measured charge, `eps_am` is the only physics parameter changed, and OCP / diffusivity / kinetics / voltage window are unchanged by object identity. This is still a zero-fit reference replay and **not** validation of the model for this graphite. Any residual that survives is a hypothesis for Phase B1 (GITT), not a conclusion.

## Caveat found in this phase: the dilute stage is DECIMATED

The lithiation window's `0.60 < V_exp <= 1.43` slice is the near-vertical dilute stage of a fresh cell. Diagnostic `scripts/probe_b05_dilute_resolution.py`: the raw p-OCV file holds 31 samples in the first 300 s of the branch (V 3.000 -> 0.885 V at 10 s spacing), but `adapter.load_raw` decimates the 189 340-row file with a GLOBAL stride of 10 (DEFAULT_MAX_POINTS = 20 000), so only 4 of them survive (t = 0, 90, 190, 280 s). The extracted OCP table therefore jumps 3.0003 -> 1.2349 V between its first two samples, and the residual above 1.43 V is an interpolation artefact of that gap - not a physical finding. Fixing it means re-extracting the OCP with the branch start kept at full resolution (a Phase B0 extraction refinement), which is deliberately NOT done here so that the B0 control stays valid.

The lithiation window's matched run also covers 0.989 of the measured window: with the capacity corrected the model reaches the lower voltage cut-off just before the measured end (the surface stoichiometry leads the volume average).
