"""Audit the actual CALB files, without inferring absolute chronology from MAT offsets."""
from pathlib import Path
import csv
import hashlib
import json
import numpy as np
from scipy.io import loadmat

ROOT = Path('data/public')
OUT = Path('outputs/eis_bms_validation/calb_pairing_audit_20261029')
GROUPS = ('c20_charge', 'c20_discharge', 'hppc_1c', 'hppc_c3', 'dv_wltp', 'dv_udds', 'dv_us06', 'eis_test')

def analyze(item):
    path = Path(item['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item['sha256']:
        raise ValueError('publisher SHA256 mismatch: '+str(path))
    data = loadmat(path, simplify_cells=True)['Data']
    row = dict(cell_id=item['cell'], temperature_setpoint=item['temperature'],
               test=item['group'], file=str(path), sha256=digest,
               chronology='unverified from per-file relative times', absolute_datetime='unavailable_in_processed_mat')
    if item['group'] == 'eis_test':
        spectra = data if isinstance(data, list) else [data]
        row.update(spectra=len(spectra), note='EIS local timestamps are not comparable with other files')
        return row
    t = np.asarray(data['Times'], dtype=float)
    i = np.asarray(data['CurrentA'], dtype=float)
    v = np.asarray(data['VoltageV'], dtype=float)
    temperature = np.asarray(data['TempC'], dtype=float)
    if len(t) != len(i) or not np.isfinite(t).all() or np.any(np.diff(t) < 0):
        raise ValueError('invalid data/time: '+str(path))
    row.update(samples=len(t), duration_s=float(t[-1]-t[0]), voltage_initial_V=float(v[0]),
               current_initial_A=float(i[0]), current_min_A=float(i.min()), current_max_A=float(i.max()),
               surface_temperature_min_C=float(temperature.min()), surface_temperature_max_C=float(temperature.max()),
               duplicate_timestamps=int(np.sum(np.diff(t)==0)))
    if item['group'].startswith('hppc_'):
        active = i < -10
        edge = np.diff(np.r_[False, active, False].astype(int))
        starts, ends = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)-1
        amplitudes = [-float(np.median(i[a:b+1])) for a,b in zip(starts,ends) if 8 <= t[b]-t[a] <= 12]
        row.update(discharge_10s_count=len(amplitudes), discharge_10s_median_A=float(np.median(amplitudes)) if amplitudes else None,
                   discharge_10s_min_A=float(min(amplitudes)) if amplitudes else None,
                   discharge_10s_max_A=float(max(amplitudes)) if amplitudes else None,
                   note='all 8-12s discharge runs; inspect distribution before assigning pulse family')
    elif item['group'].startswith('dv_'):
        row['note'] = 'initial SOC not assumed; first voltage is loaded and SOC proxy requires independent reference'
    return row

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []
    for root in sorted(ROOT.glob('calb_matched*_v2')):
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf8'))
        for item in manifest['files']:
            if item['group'] not in GROUPS: continue
            try: rows.append(analyze(item))
            except Exception as exc: failures.append({'path':item['path'], 'error':str(exc)})
    fields = sorted({k for r in rows for k in r})
    with (OUT/'pairing_inventory.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    summary={'source':'https://doi.org/10.17632/ycx459r5c3.2','files_ok':len(rows),
             'failures':failures,'cells':sorted({r['cell_id'] for r in rows}),
             'limitations':['Processed MAT Times are per-file relative: they do not establish cross-test dates or chronology.',
              'Manifest roles and protocol ordering require original raw records; no prospective EIS pairing certified.',
              'C/20 and HPPC estimates contain relaxation and load effects; they are not direct SOC ground truth.']}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    if failures: raise SystemExit(1)
if __name__ == '__main__': main()
