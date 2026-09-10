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
| delithiation | SOC 0 - 0.1 (dense) | 0.166 | 0.047 |