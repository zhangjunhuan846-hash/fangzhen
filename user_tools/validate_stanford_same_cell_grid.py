"""Run the actual desktop EIS grid path on held-out spectra of two cells."""
import csv
import io
import json
from pathlib import Path
import re
import numpy as np
import openpyxl
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_eis_grid import run_grid

ROOT=Path('data/external/eis_public_20261029/stanford')
OUT=Path('outputs/eis_bms_validation/stanford_same_cell_20261029')


def raw_for_cell(cell):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    found=set()
    for path in sorted(ROOT.rglob('*.xlsx')):
        if not re.search('_'+re.escape(cell)+'_EIS_',path.name):continue
        s=re.search(r'_SOC(\d+)_',path.name);t=re.search(r'_(\d+)degC_',path.name)
        if not (s and t):continue
        soc=int(s.group(1))/100.;temp=float(t.group(1)); key=(soc,temp)
        if key in found:raise ValueError(f'duplicate {cell} {key}')
        found.add(key)
        role='train' if soc in (.2,.8) and temp in (5.,40.) else 'test'
        wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
        sheet=next(x for x in wb if x.title.startswith('ACIM_'))
        rows=iter(sheet.values);header=list(next(rows));cols=[header.index(k) for k in ('Freq','Zmod','Zphz')]
        for row in rows:
            if not all(isinstance(row[i],(int,float)) for i in cols):continue
            freq,mag,phase=(row[i] for i in cols);z=mag*np.exp(1j*np.deg2rad(phase))
            writer.writerow([cell,path.stem,role,soc,temp,freq,z.real,z.imag])
        wb.close()
    if len(found)!=9:raise ValueError(f'{cell}: expected 9 spectra, found {len(found)}')
    return stream.getvalue().encode()


def main():
    results=[]
    for cell in ('A21','A37'):
        raw=raw_for_cell(cell)
        (OUT/cell).mkdir(parents=True,exist_ok=True)
        (OUT/cell/'eis_input.csv').write_bytes(raw)
        for mode in ('linear','log_invT'):
            cfg=defaults('eis_grid');cfg.update(data_origin='public',source='https://doi.org/10.17605/OSF.IO/9CEAV',rc_branches=2,
                frequency_min_Hz=.5,frequency_max_Hz=1000.,interpolation=mode)
            result=run_grid(cfg,OUT/cell/mode,raw)
            tests=[r for r in result['spectra_summary'] if r['role']=='test']
            results.append({'cell':cell,'interpolation':mode,'mean_test_relative_rms':float(np.mean([r['relative_rms'] for r in tests])),
                            'worst_test_relative_rms':float(max(r['relative_rms'] for r in tests)),
                            'kk_passed':result['metrics']['kk_passed'],'total_spectra':result['metrics']['total_spectra'],
                            'usable_for_replay':result['grid_usable_for_replay']})
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
