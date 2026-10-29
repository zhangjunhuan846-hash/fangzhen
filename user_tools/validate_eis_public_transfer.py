"""Reproducible cell-disjoint frequency-domain benchmark on public EIS.

Stanford: fit four SOC/temperature corner spectra from training cells, select
model using development cells, score held-out cells and interior conditions.
The optional per-cell scale uses a distinct measured calibration spectrum.
Zenodo: independent 54-cell, single-SOC comparison; no per-cell calibration.
This script evaluates impedance, not SOC estimation or time-domain voltage.
"""
from pathlib import Path
import csv
import json
import re
import numpy as np
import openpyxl
from scipy.interpolate import RegularGridInterpolator
from user_tools.workbench.engineering_eis_grid import fit_rc, rc_impedance

ROOT = Path('data/external/eis_public_20261029')
OUT = Path('outputs/eis_bms_validation/public_transfer_20261029')
FREQ = np.geomspace(.5, 1000., 40)
CAL = (.2, 25.)


def to_frequency_grid(freq, z):
    freq = np.asarray(freq, float); z = np.asarray(z, complex)
    valid = np.isfinite(freq) & np.isfinite(z.real) & np.isfinite(z.imag) & (freq > 0)
    freq, z = freq[valid], z[valid]
    order = np.argsort(freq); freq, z = freq[order], z[order]
    if len(freq) < 12 or len(set(freq)) != len(freq) or freq[0] > FREQ[0] or freq[-1] < FREQ[-1]:
        raise ValueError('Spectrum cannot cover common frequency band without extrapolation')
    return np.interp(np.log(FREQ), np.log(freq), z.real) + 1j*np.interp(np.log(FREQ), np.log(freq), z.imag)


def stanford_data():
    data = {}
    for path in sorted((ROOT/'stanford').rglob('*.xlsx')):
        cell_match = re.search(r'_(A\d+)_EIS_', path.name)
        soc_match = re.search(r'_SOC(\d+)_', path.name)
        temp_match = re.search(r'_(\d+)degC_', path.name)
        if not (cell_match and soc_match and temp_match): continue
        cell, soc, temp = cell_match.group(1), int(soc_match.group(1))/100., float(temp_match.group(1))
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = [s for s in workbook if s.title.startswith('ACIM_')]
        if len(sheets) != 1: raise ValueError(f'Unexpected EIS sheets: {path}')
        rows = iter(sheets[0].values); headers = list(next(rows))
        columns = [headers.index(k) for k in ('Freq','Zmod','Zphz')]
        values = [tuple(row[i] for i in columns) for row in rows if all(isinstance(row[i], (int,float)) for i in columns)]
        workbook.close()
        a = np.asarray(values, float)
        z = a[:,1] * np.exp(1j*np.deg2rad(a[:,2]))
        key = (cell, soc, temp)
        if key in data: raise ValueError(f'Duplicate cell/condition: {key}')
        data[key] = to_frequency_grid(a[:,0], z)
    return data


def build_models(data, cells):
    socs = [.2,.8]; temps = [5.,40.]
    nodes = np.array([[np.mean([data[(cell,s,t)] for cell in cells],axis=0) for t in temps] for s in socs])
    predictions = {'direct_complex': (nodes, 'direct')}
    for branches in (1,2):
        array = np.empty((2,2,1+2*branches))
        for i in range(2):
            for j in range(2): array[i,j],_ = fit_rc(FREQ,nodes[i,j],branches)
        predictions[f'{branches}rc'] = (array, 'rc')
        tau = array.copy()
        for k in range(1,array.shape[-1],2): tau[:,:,k+1]=array[:,:,k]*array[:,:,k+1]
        predictions[f'{branches}rc_tau'] = (tau, 'tau')
        predictions[f'{branches}rc_log'] = (np.log(array), 'log')
    models = {}
    for name,(array,kind) in predictions.items():
        models[name]=(RegularGridInterpolator((socs,temps),array,bounds_error=True),kind,False)
        # 1/T coordinates are ordered in reverse of Celsius coordinates.
        invtemps=[1/(t+273.15) for t in reversed(temps)]
        models[name+'_invT']=(RegularGridInterpolator((socs,invtemps),array[:,::-1],bounds_error=True),kind,True)
    return models


def predict(interpolators, model, soc, temp):
    interpolator,kind,invtemp = interpolators[model]
    value = interpolator([[soc,1/(temp+273.15) if invtemp else temp]])[0]
    if kind == 'direct': return value
    if kind == 'log': value = np.exp(value)
    if kind == 'tau':
        value = value.copy()
        for k in range(1,len(value),2): value[k+1] /= value[k]
    return rc_impedance(FREQ,value)


def error(pred, truth):
    return float(np.sqrt(np.mean(np.abs((pred-truth)/truth)**2)))


def scale_from_calibration(interpolators, model, truth):
    p = predict(interpolators,model,*CAL)
    # Weighted least-squares scalar, using the calibration spectrum only.
    weights = 1/np.abs(truth)**2
    scale = float(np.sum(weights*np.real(p*np.conj(truth)))/np.sum(weights*np.abs(p)**2))
    return max(.25,min(4.,scale))


def stanford():
    data = stanford_data()
    all_cells = sorted({k[0] for k in data},key=lambda x:int(x[1:]))
    complete = [cell for cell in all_cells if all((cell,s,t) in data for s in (.2,.5,.8) for t in (5.,25.,40.))]
    if len(complete) < 8: raise ValueError(f'Only {len(complete)} complete cells: {complete}')
    # Deterministic split, chosen before looking at any model scores.
    train, dev, test = complete[:-4], complete[-4:-2], complete[-2:]
    interpolators = build_models(data,train)
    rows = []
    for role, cells in [('development',dev),('test',test)]:
        for cell in cells:
            for model in interpolators:
                for calibrated in (False,True):
                    scale = scale_from_calibration(interpolators,model,data[(cell,*CAL)]) if calibrated else 1.
                    for soc in (.2,.5,.8):
                        for temp in (5.,25.,40.):
                            # Same scored cases in both arms; calibration never scores itself.
                            if (soc,temp)==CAL: continue
                            z=data[(cell,soc,temp)]
                            rows.append(dict(role=role,cell_id=cell,soc=soc,temperature_C=temp,
                                             model=model,calibrated=calibrated,scale=scale,
                                             relative_rms=error(scale*predict(interpolators,model,soc,temp),z)))
    methods = [(model,cal) for model in interpolators for cal in (False,True)]
    summary = []
    for model,cal in methods:
        record = {'model':model,'calibrated':cal}
        for role in ('development','test'):
            group = [r['relative_rms'] for r in rows if r['model']==model and r['calibrated']==cal and r['role']==role]
            record[role+'_mean_relative_rms'] = float(np.mean(group))
            record[role+'_worst_relative_rms'] = float(np.max(group))
        summary.append(record)
    best = min(summary,key=lambda x:x['development_mean_relative_rms'])
    return {'source':'https://doi.org/10.17605/OSF.IO/9CEAV','train_cells':train,'development_cells':dev,'test_cells':test,
            'incomplete_excluded_cells':[c for c in all_cells if c not in complete],
            'train_conditions':[[s,t] for s in (.2,.8) for t in (5.,40.)],
            'calibration_condition':list(CAL),'selection':'minimum mean development-cell error; calibration spectrum excluded from all scored conditions',
            'selected_by_development':{'model':best['model'],'calibrated':best['calibrated']},'methods':summary},rows


def zenodo():
    data = {}
    for path in sorted((ROOT/'zenodo_54').glob('ID*.csv')):
        with path.open(newline='',encoding='utf-8-sig') as fh:
            values = [r for r in csv.DictReader(fh) if r.get('Frequency_Hz')]
        f = [float(r['Frequency_Hz']) for r in values]
        z = [complex(float(r['Real_Ohm']),float(r['Imag_Ohm'])) for r in values]
        data[path.stem] = to_frequency_grid(f,z)
    cells=sorted(data)
    if len(cells)!=54: raise ValueError(f'Expected 54 cells, found {len(cells)}')
    train,dev,test=cells[:40],cells[40:47],cells[47:]
    mean=np.mean([data[c] for c in train],axis=0)
    models={'direct_complex':mean}
    for n in (1,2):
        pars,_=fit_rc(FREQ,mean,n);models[f'{n}rc']=rc_impedance(FREQ,pars)
    rows=[{'role':role,'cell_id':cell,'model':name,'relative_rms':error(z,data[cell])}
          for role,group in [('development',dev),('test',test)] for cell in group for name,z in models.items()]
    scores=[{'model':name,**{f'{role}_mean_relative_rms':float(np.mean([r['relative_rms'] for r in rows if r['model']==name and r['role']==role])) for role in ('development','test')}} for name in models]
    best=min(scores,key=lambda x:x['development_mean_relative_rms'])
    return {'source':'https://doi.org/10.5281/zenodo.15422339','train_cells':train,'development_cells':dev,'test_cells':test,'selected_by_development':best['model'],'methods':scores},rows


def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    if manifest['failures']: raise ValueError('Download failures; inspect manifest before benchmarking')
    # Detect subsequent accidental changes as well as download-time failures.
    import hashlib
    for item in manifest['files']:
        path=Path(item['path'].replace('\\','/'))
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['local_sha256']:
            raise ValueError(f'File missing or changed: {path}')
    a,ar=stanford();b,br=zenodo();OUT.mkdir(parents=True,exist_ok=True)
    result={'frequency_band_Hz':[float(FREQ[0]),float(FREQ[-1])],'stanford':a,'zenodo':b,
            'scope':'frequency-domain only; training and test cells disjoint; spectra interpolated over log frequency; not validation of BMS SOC or voltage'}
    (OUT/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for name,rows in [('stanford_scores.csv',ar),('zenodo_scores.csv',br)]:
        with (OUT/name).open('w',newline='',encoding='utf-8') as fh:
            writer=csv.DictWriter(fh,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
