# Phase A.5 — geometry-aware zero-fit vs Phase A (reference geometry)

- dataset `sintef_graphite` / cell `4ccc47` / model SPM
- window: p-OCV cycle 1 rest tail (60 s) + one branch
- Phase A set: `Ecker2015_graphite_halfcell` (85.85 cm², 74 µm, eps_am 0.372403)
- Phase A.5 set: `sintef_graphite_geometry_v1` (measured geometry, registered at runtime,
  OCP / diffusivity / kinetics UNCHANGED, nothing fitted)

## Geometry override (from SINTEF metadata.csv)

| parameter | reference | A.5 (derived from measurement) |
|---|---|---|
| electrode area | 85.85 cm² | 1.5394 cm² |
| thickness | 74.0 µm | 64.0 µm |
| eps_am | 0.372403 | 0.261218 |
| nominal capacity | 156.25 mAh | 2.202 mAh |

## Metrics (recomputed from the time-aligned csv)

| rate | window direction | metric | Phase A | Phase A.5 |
|---|---|---|---|---|
| pOCV-deli | charge (-) | RMSE [mV] | 150.06 | 109.12 |
| pOCV-deli | charge (-) | MAE [mV] | 98.63 | 61.86 |
| pOCV-deli | charge (-) | bias [mV] | -98.63 | -61.86 |
| pOCV-deli | charge (-) | V_sim span [mV] | 1.15 | 116.40 |
| pOCV-deli | charge (-) | **frozen artifact** | PRESENT | **PARTIAL** |
| pOCV-lith | discharge (+) | RMSE [mV] | 875.75 | 81.39 |
| pOCV-lith | discharge (+) | MAE [mV] | 867.93 | 67.81 |
| pOCV-lith | discharge (+) | bias [mV] | 866.28 | 66.16 |
| pOCV-lith | discharge (+) | V_sim span [mV] | 619.96 | 1288.98 |
| pOCV-lith | discharge (+) | **frozen artifact** | PARTIAL | **PARTIAL** |

## Residual by experimental-voltage region (MAE, mV)

| rate | region | Phase A | Phase A.5 |
|---|---|---|---|
| pOCV-deli | low_V_le_0p15 | 45.71 | 31.20 |
| pOCV-deli | mid_0p15_0p60 | 142.76 | 79.49 |
| pOCV-deli | high_V_gt_0p60 | 672.84 | 560.07 |
| pOCV-lith | low_V_le_0p15 | 857.73 | 61.75 |
| pOCV-lith | mid_0p15_0p60 | 1000.53 | 105.82 |
| pOCV-lith | high_V_gt_0p60 | 660.63 | 306.76 |

## Interpretation

- Phase A used a 55.8× too-large electrode: at the same absolute current the model saw a
  ~56× lower current density and its voltage barely moved.
- Phase A.5 replaces only the measured geometry; the frozen artifact is
  removed and the RMSE collapses (see table above).
- What remains is NOT scale: it is the difference between the reference
  OCP/diffusivity/kinetics and this graphite, plus the ~10 % catalog
  internal inconsistency (mass/loading vs punched-disc area) recorded in
  geometry_override.json.
- The lithiation window is the cell's own DISCHARGE direction and is
  convention-clean; the delithiation window is the user-selected primary
  window and is a CHARGE-direction window under the platform convention,
  so the runner's discharge-oriented columns (Q_sim, capacity_error_pct,
  current_peak_discharge_A) are not meaningful for it.

## Wording (mandatory)

Geometry-aware **zero-fit reference replay**: geometry from measurement,
OCP/diffusivity/kinetics from the published reference set, nothing fitted
to voltage, and **not** validation of the model for this graphite.
Remaining residual is a hypothesis for Phase B (OCP extraction), not a
conclusion.
