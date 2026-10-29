"""Feed W8 pre-driving EIS into the actual workbench, hold out SOC 50%."""
from pathlib import Path
import csv
import hashlib
import io
import json
import re
import numpy as np
import openpyxl
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_eis_grid import run_grid

ROOT=Path('data/public/stanford_aging_w8_candidate_20261029')
OUT=Path('outputs/eis_bms_validation/stanford_aging_w8_eis_20261029')

def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    if manifest['failures']:raise ValueError('source download incomplete')
    for record in manifest['files']:
        path=Path(record['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256_local']:
            raise ValueError('local file changed: '+str(path))
    target=sorted(ROOT.rglob('*EIS*SOC*.xlsx'))
    if len(target)!=3:raise ValueError('expected 3 EIS workbooks')
    stream=io.StringIO(newline='');w=csv.writer(stream)
    w.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    for path in target:
        soc=int(re.search(r'SOC(\d+)',path.name).group(1));wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
        sheet=next(s for s in wb if s.title.startswith('ACIM_')); rows=sheet.iter_rows(values_only=True); header=list(next(rows))
        cols=[header.index(key) for key in ('Freq','Zmod','Zphz')]
        for row in rows:
            if not all(isinstance(row[i],(int,float)) for i in cols):continue
            f,mag,phase=(float(row[i]) for i in cols);z=mag*np.exp(1j*np.deg2rad(phase))
            w.writerow(['W8',f'W8_SOC{soc}', 'test' if soc==50 else 'train',soc/100,23.,f,z.real,z.imag])
        wb.close()
    OUT.mkdir(parents=True,exist_ok=True);raw=stream.getvalue().encode();(OUT/'eis_input.csv').write_bytes(raw)
    result=[]
    # Full range, then an exploratory restricted range: high-frequency
    # positive imaginary impedance is not represented by an RC-only circuit.
    # The held-out spectrum has already been observed in the full-band run.
    for label,high in (('full',20000),('under_500Hz',500)):
        for branches in (1,2):
            config=defaults('eis_grid');config.update(source='https://osf.io/qsabn/',data_origin='public',rc_branches=branches,
                frequency_min_Hz=.001,frequency_max_Hz=high,interpolation='linear')
            try:
                output=run_grid(config,OUT/label/f'{branches}rc',raw)
                result.append({'band':label,'rc_branches':branches,'usable_for_replay':output['grid_usable_for_replay'],
                               'metrics':output['metrics'],'spectra':output['spectra_summary']})
            except Exception as exc:result.append({'band':label,'rc_branches':branches,'error':f'{type(exc).__name__}: {exc}'})
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
